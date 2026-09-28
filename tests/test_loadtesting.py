import asyncio
import json
import time
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select

from app import loadtesting
from app.db import Account, Session, Trade
from app.loadtest_worker import atomic_json, run_load, validate_target
from app.main import app


def configuration(**changes):
    return dict(id="a"*32, scenario="transfer", concurrency=4, request_count=12,
                amount_cents=100, timeout_seconds=2, max_duration_seconds=5,
                source_id="source", target_id="target", target="http://127.0.0.1:8000", **changes)


class FakeProcess:
    def __init__(self, *args, **kwargs):
        pass

    def poll(self):
        return None


@pytest.fixture
def load_environment(monkeypatch, tmp_path):
    monkeypatch.setattr(loadtesting, "ROOT", tmp_path)
    monkeypatch.setattr(loadtesting, "_processes", {})
    monkeypatch.setattr(loadtesting.subprocess, "Popen", FakeProcess)
    monkeypatch.delenv("LOADTEST_TARGET", raising=False)
    return tmp_path


@pytest.mark.parametrize("scenario", ["transfer", "payment", "deposit", "withdrawal", "idempotency"])
def test_loadtest_api_accounting(client, load_environment, scenario):
    response = client.post("/api/loadtests", json={"scenario":scenario, "concurrency":4, "request_count":12})
    assert response.status_code == 202
    config = response.json()
    assert client.post("/api/loadtests", json={}).status_code == 409
    report = asyncio.run(run_load(config, load_environment/config["id"], transport=httpx.ASGITransport(app=app)))
    assert report["status"] == "COMPLETED"
    assert report["completed"] == report["success_requests"] == 12
    assert report["peak_in_flight"] == 4
    assert report["failure_rate"] == 0
    expected = 1 if scenario == "idempotency" else 12
    assert report["unique_succeeded_transactions"] == expected
    assert report["replayed_requests"] == (11 if scenario == "idempotency" else 0)
    assert report["reconciliation"]["balanced"]
    with Session() as db:
        assert db.get(Account, "ACC-1001").balance == 1000000
        assert db.get(Account, "ACC-1002").balance == 1000000
        actual = db.scalar(select(func.count()).select_from(Trade).where(Trade.idempotency_key.like("LT-"+config["id"]+"-%")))
        assert actual == expected
    assert client.get("/api/loadtests/"+config["id"]).json()["status"] == "COMPLETED"


@pytest.mark.parametrize("kind,uncertain", [("dependency_unavailable",0),("response_lost",12)])
def test_fault_loadtest_reports_uncertain_commit(client, load_environment, kind, uncertain):
    client.post("/api/faults",json={"kind":kind,"duration_seconds":30})
    config = client.post("/api/loadtests",json={"concurrency":4,"request_count":12}).json()
    report = asyncio.run(run_load(config, load_environment/config["id"], transport=httpx.ASGITransport(app=app)))
    assert report["http_errors"] == 12
    assert report["uncertain_outcomes"] == uncertain
    assert report["unique_succeeded_transactions"] == 0
    assert report["reconciliation"]["balanced"]
    assert bool(report["warning"]) == bool(uncertain)
    with Session() as db:
        actual = db.scalar(select(func.count()).select_from(Trade).where(Trade.idempotency_key.like("LT-"+config["id"]+"-%")))
        assert actual == uncertain


def test_worker_concurrency_and_latency_window(tmp_path):
    active = peak = 0

    async def handler(request):
        nonlocal active, peak
        if request.url.path == "/api/reconcile":
            return httpx.Response(200,json={"balanced":True})
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(.04)
        active -= 1
        return httpx.Response(200,json={"status":"SUCCEEDED","id":request.headers["Idempotency-Key"],"replayed":False})

    report = asyncio.run(run_load(configuration(),tmp_path,httpx.MockTransport(handler)))
    assert peak == 4
    assert report["completed"] == 12
    # Excludes the half-second report polling interval and reconciliation.
    assert .1 <= report["elapsed_seconds"] < .45
    assert report["latency_ms"]["p50"] >= 35


@pytest.mark.parametrize("reason", ["user_stop", "duration_limit"])
def test_stop_drains_inflight_requests(tmp_path, reason):
    seen = 0
    config = configuration()
    if reason == "duration_limit":
        config["max_duration_seconds"] = .01

    async def handler(request):
        nonlocal seen
        if request.url.path == "/api/reconcile":
            return httpx.Response(200,json={"balanced":True})
        seen += 1
        if reason == "user_stop" and seen == 4:
            (tmp_path/"stop").touch()
        await asyncio.sleep(.03)
        return httpx.Response(200,json={"status":"SUCCEEDED","id":request.headers["Idempotency-Key"]})

    report = asyncio.run(run_load(config,tmp_path,httpx.MockTransport(handler)))
    assert report["status"] == "STOPPED"
    assert report["stop_reason"] == reason
    assert report["completed"] == report["issued"] == 4
    assert report["in_flight"] == 0
    assert report["reconciliation"]["balanced"]


def test_error_classification_and_failed_reconciliation(tmp_path):
    async def handler(request):
        if request.url.path == "/api/reconcile":
            return httpx.Response(503)
        index = int(request.headers["Idempotency-Key"].rsplit("-",1)[1])
        if index == 0:
            return httpx.Response(200,json={"status":"REJECTED","error_code":"INSUFFICIENT_FUNDS"})
        if index == 1:
            return httpx.Response(200,text="invalid")
        if index == 2:
            raise httpx.ConnectError("unavailable",request=request)
        if index == 3:
            return httpx.Response(401,json={"error_code":"UNAUTHORIZED"})
        return httpx.Response(200,json={"status":"SUCCEEDED","id":str(index)})

    report = asyncio.run(run_load(configuration(),tmp_path,httpx.MockTransport(handler)))
    assert report["business_rejections"] == report["invalid_responses"] == report["transport_errors"] == report["http_errors"] == 1
    assert report["success_requests"] == 8
    assert report["uncertain_outcomes"] == 2
    assert report["reconciliation"] is None
    assert "账务核对请求失败" in report["warning"]


def test_validation_stop_and_recovery(client, load_environment, monkeypatch):
    for body in [{"concurrency":201},{"concurrency":0},{"concurrency":True},{"request_count":10001},{"scenario":"refund"},{"timeout_seconds":31},{"max_duration_seconds":301}]:
        assert client.post("/api/loadtests",json=body).status_code == 422
    for target in ["https://127.0.0.1:8000", "http://example.com", "http://localhost.evil", "http://user@127.0.0.1:8000", "http://127.0.0.1:8000/api"]:
        with pytest.raises(ValueError):
            validate_target(target)
    monkeypatch.setenv("LOADTEST_TARGET","https://example.com")
    assert client.post("/api/loadtests",json={}).status_code == 422
    monkeypatch.delenv("LOADTEST_TARGET")
    run = client.post("/api/loadtests",json={"request_count":1}).json()
    run_id = run["id"]
    assert client.post("/api/loadtests/"+run_id+"/stop").json()["status"] == "STOPPING"
    assert (load_environment/run_id/"stop").exists()
    monkeypatch.setattr(loadtesting,"_processes",{})
    loadtesting.recover_runs()
    assert loadtesting.get_run(run_id)["status"] == "STOPPING"
    import os
    os.utime(load_environment/run_id/"report.json",(time.time()-60,time.time()-60))
    assert loadtesting.get_run(run_id)["status"] == "INTERRUPTED"


def test_worker_failure_is_visible(client, load_environment):
    run = client.post("/api/loadtests",json={"request_count":1}).json()
    loadtesting._processes[run["id"]].poll = lambda: 1
    report = client.get("/api/loadtests/"+run["id"]).json()
    assert report["status"] == "FAILED"
    assert "子进程已退出" in report["warning"]
