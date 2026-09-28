import hashlib
import json
import threading
from sqlalchemy import func, select
from .db import Account, Entry, Session, Trade
from .observability import emit, now, row, uid

# SQLite development and MySQL demo both run one application worker.
# MySQL row locks and unique keys additionally enforce storage constraints.
write_lock = threading.RLock()
CLEARING = "SYS-CLEARING"

class BusinessError(Exception):
    def __init__(self, code, message, status=409):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)

def public_trade(trade):
    value = row(trade)
    value.pop("fingerprint", None)
    return value

def initialize():
    with write_lock, Session.begin() as db:
        if not db.get(Account, CLEARING):
            db.add(Account(id=CLEARING, name="模拟外部清算账户", kind="system", balance=0, created_at=now()))
        for account_id, name, kind in [("ACC-1001", "林晓 · 个人账户", "customer"), ("ACC-1002", "陈晨 · 个人账户", "customer"), ("MCH-2001", "星河商店 · 商户账户", "merchant")]:
            if not db.get(Account, account_id):
                db.add(Account(id=account_id, name=name, kind=kind, balance=0, created_at=now()))
    # Funding is journaled, not a direct balance mutation.
    for account_id in ("ACC-1001", "ACC-1002"):
        execute_trade({"kind": "deposit", "source_id": None, "target_id": account_id, "amount": 1000000, "original_id": None}, "seed-" + account_id, uid())

def execute_trade(payload, idempotency_key, trace_id):
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    with write_lock, Session.begin() as db:
        existing = db.scalar(select(Trade).where(Trade.idempotency_key == idempotency_key))
        if existing:
            if existing.fingerprint != fingerprint:
                raise BusinessError("IDEMPOTENCY_CONFLICT", "同一幂等键不能用于不同交易")
            result = public_trade(existing)
            result["replayed"] = True
            return result
        kind, amount = payload["kind"], payload["amount"]
        source, target = payload.get("source_id"), payload.get("target_id")
        original = None
        if kind == "deposit":
            source = CLEARING
        elif kind == "withdrawal":
            target = CLEARING
        elif kind == "refund":
            original = db.scalar(select(Trade).where(Trade.id == payload.get("original_id")).with_for_update())
            if not original or original.kind != "payment" or original.status != "SUCCEEDED":
                raise BusinessError("INVALID_ORIGINAL", "退款需要一笔成功的支付交易")
            source, target = original.target_id, original.source_id
        if not source or not target or source == target:
            raise BusinessError("INVALID_ACCOUNTS", "请选择两个不同的有效账户", 422)
        if kind in ("transfer", "payment") and CLEARING in (source, target):
            raise BusinessError("SYSTEM_ACCOUNT", "清算账户不能用于转账或支付", 422)
        accounts = {a.id: a for a in db.scalars(select(Account).where(Account.id.in_(sorted([source, target]))).order_by(Account.id).with_for_update())}
        if len(accounts) != 2:
            raise BusinessError("ACCOUNT_NOT_FOUND", "账户不存在", 404)
        debit, credit = accounts[source], accounts[target]
        if kind == "deposit" and credit.kind == "system" or kind == "withdrawal" and debit.kind == "system":
            raise BusinessError("SYSTEM_ACCOUNT", "请选择业务账户", 422)
        if kind == "payment" and (credit.kind != "merchant" or debit.kind != "customer"):
            raise BusinessError("INVALID_PAYMENT", "支付需从个人账户付款至商户账户", 422)
        error = ""
        if debit.currency != credit.currency:
            error = "CURRENCY_MISMATCH"
        elif debit.frozen or credit.frozen:
            error = "ACCOUNT_FROZEN"
        elif original and original.refunded + amount > original.amount:
            error = "REFUND_LIMIT"
        elif debit.kind != "system" and debit.balance < amount:
            error = "INSUFFICIENT_FUNDS"
        trade = Trade(id=uid("TX-"), idempotency_key=idempotency_key, fingerprint=fingerprint, kind=kind, source_id=source, target_id=target, amount=amount, status="REJECTED" if error else "SUCCEEDED", error_code=error, original_id=original.id if original else None, trace_id=trace_id, created_at=now(), refunded=0, currency="CNY")
        db.add(trade)
        db.flush()
        if not error:
            debit.balance -= amount
            credit.balance += amount
            db.add_all([Entry(trade_id=trade.id, account_id=source, side="DEBIT", delta=-amount, created_at=now()), Entry(trade_id=trade.id, account_id=target, side="CREDIT", delta=amount, created_at=now())])
            if original:
                original.refunded += amount
        emit(trace_id, error or "LEDGER_COMMITTED", "交易被业务规则拒绝" if error else "交易与双边分录已原子记账", transaction_id=trade.id, level="WARN" if error else "INFO", session=db)
        result = public_trade(trade)
        result["replayed"] = False
    return result

def reconcile():
    with write_lock, Session() as db:
        accounts = list(db.scalars(select(Account)))
        balances = dict(db.execute(select(Entry.account_id, func.sum(Entry.delta)).group_by(Entry.account_id)).all())
        account_diffs = [{"account_id": a.id, "balance": a.balance, "journal_balance": balances.get(a.id, 0)} for a in accounts if a.balance != balances.get(a.id, 0)]
        grouped = db.execute(select(Entry.trade_id, func.sum(Entry.delta), func.count(Entry.id)).group_by(Entry.trade_id)).all()
        entry_map = {t: (s, n) for t, s, n in grouped}
        detail_map = {}
        for entry in db.scalars(select(Entry)):
            detail_map.setdefault(entry.trade_id, []).append((entry.account_id, entry.side, entry.delta))
        trade_diffs = []
        for trade in db.scalars(select(Trade)):
            total, count = entry_map.get(trade.id, (0, 0))
            expected = 2 if trade.status == "SUCCEEDED" else 0
            expected_entries = sorted([(trade.source_id, "DEBIT", -trade.amount), (trade.target_id, "CREDIT", trade.amount)]) if trade.status == "SUCCEEDED" else []
            actual_entries = sorted(detail_map.get(trade.id, []))
            if total != 0 or count != expected or actual_entries != expected_entries:
                trade_diffs.append({"trade_id": trade.id, "delta": total, "entry_count": count, "expected": expected})
        return {"checked_at": now(), "balanced": not account_diffs and not trade_diffs and sum(a.balance for a in accounts) == 0, "account_count": len(accounts), "entry_count": sum(n for _, _, n in grouped), "net_balance": sum(a.balance for a in accounts), "account_differences": account_diffs, "trade_differences": trade_diffs}
