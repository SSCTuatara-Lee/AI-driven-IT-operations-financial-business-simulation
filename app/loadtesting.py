import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from .db import Account, DATA_DIR, Session, engine
from .domain import BusinessError, execute_trade, write_lock
from .loadtest_worker import ACTIVE, atomic_json, validate_target
from .observability import emit, now, uid

ROOT = DATA_DIR.resolve()/"loadtests"
ROOT.mkdir(parents=True, exist_ok=True)
_guard = threading.RLock()
_processes = {}

class LoadTestInput(BaseModel):
    scenario: Literal["transfer", "payment", "deposit", "withdrawal", "idempotency"] = "transfer"
    concurrency: int = Field(default=20, ge=1, le=200, strict=True)
    request_count: int = Field(default=1000, ge=1, le=10000, strict=True)
    amount_cents: int = Field(default=100, ge=1, le=100000, strict=True)
    timeout_seconds: int = Field(default=15, ge=1, le=30, strict=True)
    max_duration_seconds: int = Field(default=120, ge=1, le=300, strict=True)

def folder_for(run_id):
    if not re.fullmatch(r"[0-9a-f]{32}", run_id):
        raise BusinessError("INVALID_RUN", "压测编号无效", 422)
    return ROOT/run_id

def get_run(run_id):
    folder = folder_for(run_id)
    if not (folder/"report.json").exists():
        raise BusinessError("RUN_NOT_FOUND", "压测记录不存在", 404)
    report = json.loads((folder/"report.json").read_text(encoding="utf-8"))
    process = _processes.get(run_id)
    if report["status"] in ACTIVE and process is not None and process.poll() is not None:
        report.update(status="FAILED", warning="压测子进程已退出，报告未正常完成。", finished_at=now())
        atomic_json(folder/"report.json", report)
    if report["status"] in ACTIVE and process is None and time.time()-(folder/"report.json").stat().st_mtime > 45:
        report.update(status="INTERRUPTED", warning="压测进程失联；已停止继续发压，请核查在途请求并重新对账。", finished_at=now())
        (folder/"stop").touch()
        atomic_json(folder/"report.json", report)
    if report["status"] in ACTIVE and (folder/"stop").exists():
        report["status"] = "STOPPING"
    return report

def list_runs():
    folders = sorted(ROOT.glob("*/report.json"), key=lambda p:p.stat().st_mtime, reverse=True)
    return [get_run(path.parent.name) for path in folders[:30]]

def start_run(body, trace_id):
    with _guard:
        if any(r["status"] in ACTIVE for r in list_runs()):
            raise BusinessError("LOADTEST_BUSY", "已有压测在运行，请等待结束或停止", 409)
        try:
            target = validate_target(os.getenv("LOADTEST_TARGET", "http://127.0.0.1:8000"))
        except ValueError:
            raise BusinessError("INVALID_LOADTEST_TARGET", "压测地址必须是本地实验服务的 HTTP 地址", 422)
        run_id = uid()
        folder = folder_for(run_id)
        folder.mkdir()
        source, target_account = uid("LT-A-"), uid("LT-B-")
        with write_lock, Session.begin() as db:
            db.add_all([Account(id=source, name="压测付款 "+run_id[:8], kind="customer", balance=0, created_at=now()), Account(id=target_account, name="压测收款 "+run_id[:8], kind="merchant" if body.scenario == "payment" else "customer", balance=0, created_at=now())])
        # Provisioning is outside the measured workload, but fully journaled.
        if body.scenario != "deposit":
            result = execute_trade({"kind":"deposit", "source_id":None, "target_id":source, "amount":body.request_count*body.amount_cents, "original_id":None}, "LT-FUND-"+run_id, trace_id)
            if result["status"] != "SUCCEEDED":
                raise BusinessError("LOADTEST_SETUP_FAILED", "压测专用账户准备失败", 503)
        config = dict(body.model_dump(), id=run_id, created_at=now(), target=target, source_id=source, target_id=target_account, database=engine.dialect.name)
        atomic_json(folder/"config.json", config)
        atomic_json(folder/"report.json", dict(config,status="PREPARING",issued=0,completed=0))
        emit(trace_id, "AUDIT_LOADTEST_START", "local-operator 启动压测 "+run_id, service="audit")
        try:
            with (folder/"worker.log").open("ab") as output:
                _processes[run_id] = subprocess.Popen([sys.executable, "-m", "app.loadtest_worker", str(folder)], cwd=Path(__file__).resolve().parents[1], stdout=output, stderr=output, creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
        except OSError:
            atomic_json(folder/"report.json", dict(config,status="FAILED",issued=0,completed=0,warning="无法启动压测进程"))
            raise BusinessError("LOADTEST_START_FAILED", "无法启动压测进程", 503)
        return get_run(run_id)

def stop_run(run_id, trace_id):
    report = get_run(run_id)
    if report["status"] in ACTIVE:
        (folder_for(run_id)/"stop").touch()
        emit(trace_id, "AUDIT_LOADTEST_STOP", "local-operator 请求停止压测 "+run_id, service="audit")
    return get_run(run_id)

def recover_runs():
    # Stop old workers after an application restart; never silently resume a load.
    for path in ROOT.glob("*/report.json"):
        report = json.loads(path.read_text(encoding="utf-8"))
        if report["status"] in ACTIVE:
            (path.parent/"stop").touch()
            # The worker owns its report until it drains in-flight requests.
            # A stale orphan is marked interrupted by get_run after 45 seconds.

def shutdown_runs():
    for run_id, process in list(_processes.items()):
        if process.poll() is None:
            (folder_for(run_id)/"stop").touch()
