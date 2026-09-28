import json
import logging
import time
import uuid
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from prometheus_client import Counter, Histogram
from sqlalchemy import event
from .db import DATA_DIR, Log, Session

REQUESTS = Counter("finops_http_requests_total", "HTTP requests", ["route", "method", "status"])
LATENCY = Histogram("finops_http_duration_seconds", "HTTP latency", ["route"], buckets=(.01, .05, .1, .25, .5, 1, 2, 5, 10))
TRADES = Counter("finops_trade_results_total", "Trade attempts", ["kind", "status"])
logger = logging.getLogger("finops")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = RotatingFileHandler(DATA_DIR / "events.jsonl", maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.addHandler(logging.StreamHandler())

@event.listens_for(Session.class_, "after_commit")
def flush_committed_logs(session):
    for payload in session.info.pop("pending_logs", []):
        logger.info(json.dumps(payload, ensure_ascii=False))

@event.listens_for(Session.class_, "after_rollback")
def discard_rolled_back_logs(session):
    session.info.pop("pending_logs", None)

def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")

def uid(prefix=""):
    return prefix + uuid.uuid4().hex

def row(obj):
    return {column.name: getattr(obj, column.name) for column in obj.__table__.columns}

def emit(trace_id, event, message, *, service="transaction", transaction_id="", level="INFO", status=200, duration_ms=0, session=None):
    payload = dict(timestamp=now(), level=level, service=service, trace_id=trace_id, span_id=uuid.uuid4().hex[:16], transaction_id=transaction_id, event=event, message=message, duration_ms=duration_ms, status=status)
    record = Log(**payload)
    if session is not None:
        session.add(record)
        session.info.setdefault("pending_logs", []).append(payload)
    else:
        logger.info(json.dumps(payload, ensure_ascii=False))
        try:
            with Session.begin() as db:
                db.add(record)
        except Exception:
            logger.error(json.dumps({"event": "LOG_INDEX_UNAVAILABLE", "trace_id": trace_id, "timestamp": now()}))
    return payload
