from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from .db import Log, Session
from .observability import row

RULES = {
    "CONNECTION_ACQUIRE_TIMEOUT": ("应用获取数据库连接超时", "连接池容量、慢事务、连接泄漏或数据库连接异常均可能导致该现象。", ["检查连接池活跃数与等待数", "关联慢 SQL、锁等待和连接释放路径"]),
    "DEPENDENCY_UNAVAILABLE": ("下游模拟通道连接失败", "通道不可达是直接观测现象，具体网络或服务原因仍需进一步验证。", ["检查通道健康与连通性", "对齐失败时间和服务事件"]),
    "DEPENDENCY_SLOW": ("下游调用耗时升高", "调用跨度支持下游延迟这一候选原因，尚不能确定下游内部瓶颈。", ["查看下游服务耗时及资源", "检查超时预算与重试放大"]),
    "RESPONSE_TIMEOUT": ("交易响应超时", "客户端超时不代表扣款失败；结合记账证据确认最终状态。", ["按交易号或原幂等键查询", "使用相同幂等键重试，避免重复扣款"]),
    "INSUFFICIENT_FUNDS": ("余额不足导致业务拒绝", "属于业务规则拒绝，无成功记账。", ["核对付款账户可用余额"]),
    "ACCOUNT_FROZEN": ("账户状态导致业务拒绝", "账户冻结阻止本次交易。", ["检查账户冻结状态与操作审计"]),
    "REFUND_LIMIT": ("累计退款超过支付金额", "原交易的退款额度不足。", ["核对原支付金额和已退金额"]),
}

def diagnose(trace_id=None, minutes=15):
    since = (datetime.now(timezone.utc)-timedelta(minutes=minutes)).isoformat(timespec="milliseconds")
    # No fault configuration or fault labels are read by this analyzer.
    with Session() as db:
        query = select(Log).where(Log.timestamp >= since, Log.service != "audit")
        if trace_id:
            query = query.where(Log.trace_id == trace_id)
        logs = [row(x) for x in db.scalars(query.order_by(Log.id.desc()).limit(500))]
    candidates=[]
    for code, (title, explanation, actions) in RULES.items():
        matches=[l for l in logs if l["event"]==code]
        if matches:
            candidates.append({"title":title,"explanation":explanation,"event":code,"evidence_ids":[l["id"] for l in matches],"next_steps":actions,"evidence_strength":"有直接现象证据，底层原因需验证"})
    relevant_traces={l["trace_id"] for l in logs if l["event"] in RULES}
    evidence=[l for l in reversed(logs) if l["event"] in RULES or l["trace_id"] in relevant_traces and l["event"]=="LEDGER_COMMITTED"]
    committed={l["transaction_id"] for l in evidence if l["event"]=="LEDGER_COMMITTED"}
    timedout={l["transaction_id"] for l in evidence if l["event"]=="RESPONSE_TIMEOUT"}
    summary="；".join(c["title"] for c in candidates) if candidates else "所选时间窗口没有足够的异常证据，不能据此确认系统无故障。"
    if committed & timedout:
        summary += "。发现同一交易记账成功后响应超时，请查询交易最终状态，禁止换新幂等键重复支付。"
    return {"summary":summary,"since":since,"trace_id":trace_id,"candidates":candidates,"evidence":evidence[-80:],"scanned_records":len(logs),"truncated":len(logs)==500,"method":"规则与日志证据关联；非模型因果证明"}
