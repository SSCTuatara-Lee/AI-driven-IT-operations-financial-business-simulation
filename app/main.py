import hmac
import json
import os
import re
import time
from contextlib import asynccontextmanager
from typing import Literal
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from . import faults, knowledge, loadtesting
from .db import Account, Base, ChatTurn, Chunk, Document, Entry, Fault, Log, Session, Trade, engine
from .diagnostics import diagnose
from .domain import BusinessError, execute_trade, initialize, public_trade, reconcile, write_lock
from .observability import LATENCY, REQUESTS, TRADES, emit, now, row, uid

TOKEN = os.getenv("APP_TOKEN", "")

@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    initialize()
    knowledge.seed_documents()
    loadtesting.recover_runs()
    try:
        yield
    finally:
        loadtesting.shutdown_runs()

app = FastAPI(title="澄明 · 金融模拟与 AI 运维", version="0.1.0", lifespan=lifespan)

@app.middleware("http")
async def context(request: Request, call_next):
    supplied = request.headers.get("x-trace-id", "")
    request.state.trace_id = supplied if re.fullmatch(r"[0-9a-f]{32}", supplied) and supplied != "0"*32 else uid()
    if request.url.path.startswith("/api/") and TOKEN and not hmac.compare_digest(request.headers.get("authorization", ""), "Bearer " + TOKEN):
        return JSONResponse({"error_code":"UNAUTHORIZED", "message":"请输入本地访问令牌"}, status_code=401)
    start = time.perf_counter()
    response = await call_next(request)
    route = getattr(request.scope.get("route"), "path", "static")
    elapsed = time.perf_counter()-start
    REQUESTS.labels(route, request.method, str(response.status_code)).inc()
    LATENCY.labels(route).observe(elapsed)
    response.headers["X-Trace-ID"] = request.state.trace_id
    if request.url.path.startswith("/api/") and request.method in ("POST", "PUT", "DELETE"):
        emit(request.state.trace_id, "HTTP_REQUEST", request.method + " " + route, service="api", status=response.status_code, duration_ms=round(elapsed*1000), level="ERROR" if response.status_code>=500 else "INFO")
    return response

@app.exception_handler(BusinessError)
async def business_error(request, exc):
    emit(request.state.trace_id, exc.code, exc.message, service="api", status=exc.status, level="WARN")
    return JSONResponse({"error_code":exc.code,"message":exc.message,"trace_id":request.state.trace_id}, status_code=exc.status)

@app.exception_handler(SQLAlchemyError)
async def database_error(request, exc):
    emit(request.state.trace_id,"DATABASE_ERROR","数据库操作失败，事务结果请按幂等键核验",status=503,level="ERROR")
    return JSONResponse({"error_code":"DATABASE_ERROR","message":"数据库暂不可用，请保留幂等键并查询交易结果", "trace_id":request.state.trace_id}, status_code=503)

@app.get("/health/live")
def live():
    return {"status":"ok"}

@app.get("/health/ready")
def ready():
    try:
        with Session() as db:
            db.execute(text("SELECT 1"))
        return {"status":"ok"}
    except SQLAlchemyError:
        return JSONResponse({"status":"database_unavailable"}, status_code=503)

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.get("/api/config")
def config():
    return {"version":"0.1.0", "environment":"本地模拟实验室", "database":engine.dialect.name, "model_configured":bool(knowledge.API_BASE and knowledge.CHAT_MODEL), "embedding_configured":bool(knowledge.API_BASE and knowledge.EMBED_MODEL), "fault_catalog":faults.CATALOG, "access_mode":"token" if TOKEN else "local"}

@app.get("/api/overview")
def overview():
    with Session() as db:
        total=db.scalar(select(func.count()).select_from(Trade)) or 0
        success=db.scalar(select(func.count()).select_from(Trade).where(Trade.status=="SUCCEEDED")) or 0
        amount=db.scalar(select(func.sum(Trade.amount)).where(Trade.status=="SUCCEEDED")) or 0
        recent=list(db.scalars(select(Trade).order_by(Trade.created_at.desc()).limit(8)))
        requests=list(db.scalars(select(Log).where(Log.event=="HTTP_REQUEST", Log.message=="POST /api/trades").order_by(Log.id.desc()).limit(100)))
        timings=sorted(l.duration_ms for l in requests)
        errors=sum(l.status>=500 for l in requests)
        docs=db.scalar(select(func.count()).select_from(Document))
    return {"trade_count":total,"succeeded":success,"rejected":total-success,"volume":amount,"recent_trades":[public_trade(t) for t in recent],"sample_count":len(requests),"request_error_count":errors,"p95_ms":timings[min(len(timings)-1,int(len(timings)*.95))] if timings else 0,"active_faults":faults.active_faults(),"documents":docs,"trend":[{"timestamp":l.timestamp,"duration_ms":l.duration_ms,"status":l.status} for l in reversed(requests[:30])]}

@app.get("/api/accounts")
def accounts():
    with Session() as db:
        return [row(a) for a in db.scalars(select(Account).order_by(Account.created_at))]

class AccountInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["customer","merchant"] = "customer"

@app.post("/api/accounts", status_code=201)
def create_account(body:AccountInput, request:Request):
    with write_lock, Session.begin() as db:
        account=Account(id=uid("ACC-"),name=body.name,kind=body.kind,balance=0,currency="CNY",frozen=False,created_at=now())
        db.add(account)
        emit(request.state.trace_id,"AUDIT_ACCOUNT_CREATE","local-operator 创建模拟账户 "+account.id,service="audit",session=db)
        db.flush()
        return row(account)

class FreezeInput(BaseModel):
    frozen:bool

@app.put("/api/accounts/{account_id}/freeze")
def freeze_account(account_id:str,body:FreezeInput,request:Request):
    with write_lock, Session.begin() as db:
        account=db.scalar(select(Account).where(Account.id==account_id).with_for_update())
        if not account or account.kind=="system":
            raise BusinessError("INVALID_ACCOUNT","账户不存在或不能修改",404)
        account.frozen=body.frozen
        emit(request.state.trace_id,"AUDIT_ACCOUNT_FREEZE","local-operator 设置 "+account_id+" frozen="+str(body.frozen),service="audit",session=db)
        return row(account)

class TradeInput(BaseModel):
    kind:Literal["deposit","withdrawal","transfer","payment","refund"]
    source_id:str|None=Field(default=None,max_length=40)
    target_id:str|None=Field(default=None,max_length=40)
    amount:int=Field(gt=0,le=10000000000,strict=True,description="金额单位为分，仅限 CNY")
    original_id:str|None=Field(default=None,max_length=40)

@app.post("/api/trades")
def trade(body:TradeInput,request:Request,idempotency_key:str=Header(min_length=8,max_length=100)):
    snapshot=faults.apply_before(request.state.trace_id)
    result=execute_trade(body.model_dump(),idempotency_key,request.state.trace_id)
    TRADES.labels(body.kind,result["status"]).inc()
    if faults.apply_after(snapshot,result,request.state.trace_id):
        return JSONResponse({"error_code":"RESPONSE_TIMEOUT","message":"响应超时，交易可能已经记账。请保留幂等键查询。","transaction_id":result["id"],"trace_id":request.state.trace_id}, status_code=504)
    return result

@app.get("/api/trades")
def trades(q:str="",limit:int=Query(100,ge=1,le=500)):
    with Session() as db:
        query=select(Trade)
        if q:
            query=query.where((Trade.id==q)|(Trade.idempotency_key==q)|(Trade.trace_id==q))
        return [public_trade(t) for t in db.scalars(query.order_by(Trade.created_at.desc()).limit(limit))]

@app.get("/api/entries")
def entries(trade_id:str|None=None,limit:int=Query(100,ge=1,le=500)):
    with Session() as db:
        query=select(Entry)
        if trade_id:
            query=query.where(Entry.trade_id==trade_id)
        return [row(e) for e in db.scalars(query.order_by(Entry.id.desc()).limit(limit))]

@app.post("/api/reconcile")
def reconciliation(request:Request):
    result=reconcile()
    emit(request.state.trace_id,"AUDIT_RECONCILE","local-operator 完成账务核对；balanced="+str(result["balanced"]),service="audit")
    return result

@app.get("/api/logs")
def logs(trace_id:str|None=None,level:str|None=None,limit:int=Query(100,ge=1,le=500)):
    with Session() as db:
        query=select(Log)
        if trace_id:
            query=query.where(Log.trace_id==trace_id)
        if level:
            query=query.where(Log.level==level)
        return [row(l) for l in db.scalars(query.order_by(Log.id.desc()).limit(limit))]

@app.get("/api/faults")
def fault_list():
    with Session() as db:
        return {"active":faults.active_faults(),"history":[row(f) for f in db.scalars(select(Fault).order_by(Fault.started_at.desc()).limit(30))]}

class FaultInput(BaseModel):
    kind:str
    duration_seconds:int=Field(default=60,ge=5,le=300)
    delay_ms:int=Field(default=1200,ge=50,le=5000)

@app.post("/api/faults")
def create_fault(body:FaultInput,request:Request):
    return faults.start_fault(body.kind,body.duration_seconds,body.delay_ms,request.state.trace_id)

@app.post("/api/faults/{fault_id}/stop")
def stop_fault(fault_id:str,request:Request):
    with write_lock, Session.begin() as db:
        fault=db.get(Fault,fault_id)
        if not fault:
            raise BusinessError("NOT_FOUND","演练不存在",404)
        fault.stopped_at=now()
        emit(request.state.trace_id,"AUDIT_FAULT_STOP","local-operator 停止故障演练",service="audit",session=db)
        return row(fault)

class DiagnosisInput(BaseModel):
    trace_id:str|None=Field(default=None,pattern=r"^[0-9a-f]{32}$")
    minutes:int=Field(default=15,ge=1,le=1440)

@app.post("/api/diagnose")
def diagnosis(body:DiagnosisInput):
    return diagnose(body.trace_id,body.minutes)

@app.get("/api/documents")
def documents():
    with Session() as db:
        docs=list(db.scalars(select(Document).order_by(Document.updated_at.desc())))
        return [{k:v for k,v in row(d).items() if k!="content"} for d in docs]

@app.get("/api/documents/{document_id}")
def document(document_id:str):
    with Session() as db:
        doc=db.get(Document,document_id)
        if not doc:
            raise BusinessError("NOT_FOUND","手册不存在",404)
        return row(doc)

class DocumentInput(BaseModel):
    title:str=Field(min_length=1,max_length=120)
    content:str=Field(min_length=10,max_length=20000)
    version:str=Field(default="1",min_length=1,max_length=40)
    service:str=Field(default="all",min_length=1,max_length=40)

@app.post("/api/documents",status_code=201)
def add_document(body:DocumentInput):
    return knowledge.save_document(**body.model_dump())

@app.put("/api/documents/{document_id}")
def update_document(document_id:str,body:DocumentInput):
    return knowledge.save_document(**body.model_dump(),document_id=document_id)

@app.delete("/api/documents/{document_id}")
def remove_document(document_id:str):
    with write_lock, Session.begin() as db:
        doc=db.get(Document,document_id)
        if not doc:
            raise BusinessError("NOT_FOUND","手册不存在",404)
        db.execute(delete(Chunk).where(Chunk.document_id==document_id))
        db.delete(doc)
    return {"deleted":True}

@app.get("/api/search")
def search(q:str=Query(min_length=1,max_length=2000),service:str="all"):
    return knowledge.search(q,service)

class ChatInput(BaseModel):
    question:str=Field(min_length=1,max_length=2000)
    session_id:str=Field(default_factory=lambda:uid("S-"),max_length=40,pattern=r"^[a-zA-Z0-9-]+$")
    include_evidence:bool=False
    trace_id:str|None=Field(default=None,pattern=r"^[0-9a-f]{32}$")

@app.post("/api/chat")
def chat(body:ChatInput):
    return knowledge.answer(body.question,body.session_id,diagnose(body.trace_id) if body.include_evidence else None)

@app.get("/api/chat/{session_id}")
def chat_history(session_id:str):
    with Session() as db:
        turns=list(db.scalars(select(ChatTurn).where(ChatTurn.session_id==session_id).order_by(ChatTurn.created_at.desc()).limit(50)))
        return [dict(row(t),citations=json.loads(t.citations)) for t in reversed(turns)]

@app.get("/api/loadtests")
def loadtest_list():
    return loadtesting.list_runs()

@app.post("/api/loadtests", status_code=202)
def loadtest_start(body:loadtesting.LoadTestInput, request:Request):
    return loadtesting.start_run(body, request.state.trace_id)

@app.get("/api/loadtests/{run_id}")
def loadtest_report(run_id:str):
    return loadtesting.get_run(run_id)

@app.post("/api/loadtests/{run_id}/stop")
def loadtest_stop(run_id:str, request:Request):
    return loadtesting.stop_run(run_id, request.state.trace_id)

app.mount("/",StaticFiles(directory="web",html=True),name="web")
