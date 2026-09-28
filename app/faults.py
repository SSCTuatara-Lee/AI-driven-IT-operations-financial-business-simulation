import time
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from .db import Fault, Session
from .domain import BusinessError, write_lock
from .observability import emit, now, row, uid

CATALOG = {
    "dependency_latency": {"name": "下游通道延迟", "description": "为交易增加有界等待，观察调用耗时", "stage": "before"},
    "dependency_unavailable": {"name": "下游通道不可用", "description": "交易记账前返回依赖连接错误", "stage": "before"},
    "pool_timeout": {"name": "连接获取超时", "description": "模拟应用获取连接超时，不实际破坏数据库", "stage": "before"},
    "response_lost": {"name": "记账后响应丢失", "description": "记账成功后返回超时，验证查询与幂等重试", "stage": "after"},
}

def active_faults():
    with Session() as db:
        return [row(f) for f in db.scalars(select(Fault).where(Fault.stopped_at.is_(None), Fault.expires_at > now()))]

def start_fault(kind, duration, delay_ms, trace_id):
    if kind not in CATALOG:
        raise BusinessError("INVALID_FAULT", "未知故障模板", 422)
    with write_lock, Session.begin() as db:
        current = db.scalar(select(Fault).where(Fault.stopped_at.is_(None), Fault.expires_at > now()))
        if current:
            raise BusinessError("FAULT_ALREADY_ACTIVE", "请先停止当前演练")
        fault = Fault(id=uid("FLT-"), kind=kind, started_at=now(), expires_at=(datetime.now(timezone.utc) + timedelta(seconds=duration)).isoformat(timespec="milliseconds"), delay_ms=delay_ms)
        db.add(fault)
        db.flush()
        emit(trace_id, "AUDIT_FAULT_START", "local-operator 启动限时应用故障演练", service="audit", session=db)
        return row(fault)

def apply_before(trace_id):
    snapshot = active_faults()
    for fault in snapshot:
        kind = fault["kind"]
        if kind == "dependency_latency":
            start = time.perf_counter()
            time.sleep(fault["delay_ms"] / 1000)
            emit(trace_id, "DEPENDENCY_SLOW", "模拟支付通道请求耗时升高", service="channel", duration_ms=int((time.perf_counter() - start) * 1000), level="WARN")
        elif kind == "dependency_unavailable":
            emit(trace_id, "DEPENDENCY_UNAVAILABLE", "模拟支付通道连接失败，交易尚未进入记账阶段", service="channel", status=503, level="ERROR")
            raise BusinessError("DEPENDENCY_UNAVAILABLE", "下游通道暂不可用，未记账", 503)
        elif kind == "pool_timeout":
            emit(trace_id, "CONNECTION_ACQUIRE_TIMEOUT", "应用等待数据库连接超时；未进入记账阶段", service="database-client", status=503, level="ERROR")
            raise BusinessError("CONNECTION_ACQUIRE_TIMEOUT", "连接获取超时，未记账", 503)
    return snapshot

def apply_after(snapshot, result, trace_id):
    if result["status"] == "SUCCEEDED" and not result["replayed"] and any(f["kind"] == "response_lost" for f in snapshot):
        emit(trace_id, "RESPONSE_TIMEOUT", "记账后响应通道超时；请按交易编号或幂等键查询最终状态", transaction_id=result["id"], status=504, level="ERROR")
        return True
    return False
