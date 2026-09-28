from concurrent.futures import ThreadPoolExecutor
import uuid
from sqlalchemy import select
from app.db import Account, Entry, Session, Trade
from app.domain import CLEARING

def send(client,kind="transfer",amount=10000,key=None,**extra):
    body={"kind":kind,"amount":amount,"source_id":"ACC-1001","target_id":"ACC-1002","original_id":None}
    body.update(extra)
    return client.post("/api/trades",headers={"Idempotency-Key":key or uuid.uuid4().hex},json=body)

def test_atomic_transfer_and_reconciliation(client):
    result=send(client).json()
    assert result["status"]=="SUCCEEDED"
    with Session() as db:
        assert db.get(Account,"ACC-1001").balance==990000
        assert db.get(Account,"ACC-1002").balance==1010000
        assert len(list(db.scalars(select(Entry).where(Entry.trade_id==result["id"]))))==2
    assert client.post("/api/reconcile").json()["balanced"]

def test_idempotency_and_mismatch(client):
    key=uuid.uuid4().hex
    first=send(client,key=key).json()
    second=send(client,key=key).json()
    assert second["id"]==first["id"] and second["replayed"]
    assert send(client,key=key,amount=20000).status_code==409
    assert client.post("/api/reconcile").json()["balanced"]

def test_insufficient_funds_no_entries(client):
    result=send(client,amount=1000001).json()
    assert result["status"]=="REJECTED" and result["error_code"]=="INSUFFICIENT_FUNDS"
    assert client.get("/api/entries",params={"trade_id":result["id"]}).json()==[]
    assert client.post("/api/reconcile").json()["balanced"]

def test_money_and_system_account_validation(client):
    for amount in (0,-1,1.2,"100",True):
        assert send(client,amount=amount).status_code==422
    assert send(client,source_id=CLEARING).status_code==422
    assert send(client,target_id="missing").status_code==404
    assert send(client,target_id="ACC-1001").status_code==422

def test_payment_refund_limit(client):
    payment=send(client,kind="payment",amount=10000,target_id="MCH-2001").json()
    assert payment["status"]=="SUCCEEDED"
    first=send(client,kind="refund",amount=6000,source_id=None,target_id=None,original_id=payment["id"]).json()
    second=send(client,kind="refund",amount=5000,source_id=None,target_id=None,original_id=payment["id"]).json()
    assert first["status"]=="SUCCEEDED"
    assert second["error_code"]=="REFUND_LIMIT"
    assert client.post("/api/reconcile").json()["balanced"]

def test_freeze_and_withdrawal(client):
    assert client.put("/api/accounts/ACC-1001/freeze",json={"frozen":True}).status_code==200
    assert send(client).json()["error_code"]=="ACCOUNT_FROZEN"
    client.put("/api/accounts/ACC-1001/freeze",json={"frozen":False})
    assert send(client,kind="withdrawal",target_id=None).json()["status"]=="SUCCEEDED"
    assert client.post("/api/reconcile").json()["balanced"]

def test_concurrent_debits_do_not_overdraw(client):
    with ThreadPoolExecutor(max_workers=8) as executor:
        results=list(executor.map(lambda _:send(client,amount=200000).json(),range(8)))
    assert sum(r["status"]=="SUCCEEDED" for r in results)==5
    with Session() as db:
        assert db.get(Account,"ACC-1001").balance==0
    assert client.post("/api/reconcile").json()["balanced"]

def test_concurrent_idempotent_requests(client):
    key=uuid.uuid4().hex
    with ThreadPoolExecutor(max_workers=6) as executor:
        results=list(executor.map(lambda _:send(client,key=key).json(),range(6)))
    assert len({r["id"] for r in results})==1
    assert sum(not r["replayed"] for r in results)==1

def test_lost_response_preserves_transaction(client):
    client.post("/api/faults",json={"kind":"response_lost","duration_seconds":30})
    key=uuid.uuid4().hex
    first=send(client,key=key)
    assert first.status_code==504
    found=client.get("/api/trades",params={"q":key}).json()
    assert found[0]["status"]=="SUCCEEDED"
    replay=send(client,key=key).json()
    assert replay["id"]==found[0]["id"] and replay["replayed"]
    diagnosis=client.post("/api/diagnose",json={"trace_id":first.json()["trace_id"]}).json()
    assert {e["event"] for e in diagnosis["evidence"]}>={"LEDGER_COMMITTED","RESPONSE_TIMEOUT"}
    assert client.post("/api/reconcile").json()["balanced"]

def test_failure_stop_and_expiration(client):
    r=client.post("/api/faults",json={"kind":"dependency_unavailable","duration_seconds":5}).json()
    assert send(client).status_code==503
    assert client.post("/api/faults",json={"kind":"pool_timeout"}).status_code==409
    client.post("/api/faults/"+r["id"]+"/stop")
    assert send(client).json()["status"]=="SUCCEEDED"
    from app.db import Fault
    f=client.post("/api/faults",json={"kind":"pool_timeout","duration_seconds":5}).json()
    with Session.begin() as db:
        db.get(Fault,f["id"]).expires_at="2000-01-01T00:00:00.000+00:00"
    assert client.get("/api/faults").json()["active"]==[]
    assert send(client).status_code==200

def test_diagnosis_does_not_use_fault_label(client):
    client.post("/api/faults",json={"kind":"pool_timeout"})
    before=client.post("/api/diagnose",json={}).json()
    assert before["candidates"]==[]
    send(client)
    after=client.post("/api/diagnose",json={}).json()
    assert any(c["event"]=="CONNECTION_ACQUIRE_TIMEOUT" for c in after["candidates"])
    assert all(not e["event"].startswith("AUDIT_FAULT") for e in after["evidence"])

def test_document_lifecycle_and_search(client):
    body={"title":"独特故障 ZXQ987","content":"ZXQ987 是独特故障码，排查步骤为检查模拟通道。","version":"1.0"}
    doc=client.post("/api/documents",json=body).json()
    assert client.get("/api/search",params={"q":"ZXQ987"}).json()["hits"][0]["document_id"]==doc["id"]
    body.update(version="2.0",content="新故障码 UVW654，需要检查数据库连接状态。",title="新故障 UVW654")
    client.put("/api/documents/"+doc["id"],json=body)
    assert client.get("/api/search",params={"q":"ZXQ987"}).json()["hits"]==[]
    assert client.get("/api/search",params={"q":"UVW654"}).json()["hits"][0]["version"]=="2.0"
    client.delete("/api/documents/"+doc["id"])
    assert client.get("/api/search",params={"q":"UVW654"}).json()["hits"]==[]

def test_chat_fallback_citations_and_history(client):
    body={"question":"交易超时后如何幂等重试？","session_id":"test-session"}
    answer=client.post("/api/chat",json=body).json()
    assert answer["mode"]=="retrieval_only" and answer["citations"]
    assert len(client.get("/api/chat/test-session").json())==1
    unknown=client.post("/api/chat",json={"question":"zzzznotfound6789"}).json()
    assert unknown["citations"]==[]

def test_live_ready_metrics_and_static(client):
    assert client.get("/health/ready").status_code==200
    assert "finops_http_requests_total" in client.get("/metrics").text
    assert "XIAOTAO" in client.get("/").text

def test_token_auth(client,monkeypatch):
    from app import main
    monkeypatch.setattr(main,"TOKEN","test-only-token")
    assert client.get("/api/accounts").status_code==401
    assert client.get("/api/accounts",headers={"Authorization":"Bearer test-only-token"}).status_code==200


def test_reconciliation_detects_wrong_but_balanced_entries(client):
    trade=send(client,amount=10000).json()
    with Session.begin() as db:
        entries=list(db.scalars(select(Entry).where(Entry.trade_id==trade["id"])))
        for entry in entries:
            account=db.get(Account,entry.account_id)
            account.balance-=entry.delta
            entry.delta=entry.delta//2
            account.balance+=entry.delta
    result=client.post("/api/reconcile").json()
    assert not result["balanced"] and result["trade_differences"]

def test_rollback_never_logs_ledger_committed(client,caplog):
    import pytest
    from app.observability import emit
    caplog.clear()
    with pytest.raises(RuntimeError):
        with Session.begin() as db:
            emit("a"*32,"ROLLBACK_PROBE","not committed",session=db)
            raise RuntimeError("rollback")
    assert not any("ROLLBACK_PROBE" in record.message for record in caplog.records)
