"""Bounded closed-loop HTTP load generator, separate from the application process."""
import asyncio
import json
import math
import os
import sys
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx

ACTIVE = {"PREPARING", "RUNNING", "VERIFYING", "STOPPING"}

def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")

def atomic_json(path, value):
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)

def validate_target(url):
    parsed = urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("Load tests only target the local lab HTTP service")
    return url.rstrip("/")

def latency_summary(values):
    ordered = sorted(values)
    def percentile(q):
        return round(ordered[max(0, math.ceil(q * len(ordered))-1)], 2) if ordered else 0
    return {"p50":percentile(.5), "p95":percentile(.95), "p99":percentile(.99), "max":round(max(values, default=0),2), "mean":round(sum(values)/len(values),2) if values else 0}

def payload_for(config):
    kind = "transfer" if config["scenario"] == "idempotency" else config["scenario"]
    return {"kind":kind, "amount":config["amount_cents"], "source_id":None if kind == "deposit" else config["source_id"], "target_id":None if kind == "withdrawal" else config["target_id"], "original_id":None}

async def run_load(config, folder, transport=None):
    target = validate_target(config["target"])
    state = dict(config, status="RUNNING", started_at=timestamp(), finished_at=None, issued=0, completed=0, in_flight=0, peak_in_flight=0, reconciliation=None, warning=None)
    counts = Counter()
    codes = Counter()
    latencies = []
    successful_ids = set()
    samples = []
    started = time.perf_counter()
    measured_elapsed = None
    last_completed = started
    stopped_reason = None
    folder.mkdir(parents=True, exist_ok=True)

    def snapshot():
        elapsed = measured_elapsed if measured_elapsed is not None else time.perf_counter()-started
        completed = state["completed"]
        result = dict(state, elapsed_seconds=round(elapsed,3), requests_per_second=round(completed/max(elapsed,.001),2), confirmed_transactions_per_second=round(len(successful_ids)/max(elapsed,.001),2), unique_succeeded_transactions=len(successful_ids), success_requests=counts["success"], business_rejections=counts["business_rejection"], http_errors=counts["http_error"], transport_errors=counts["transport_error"], invalid_responses=counts["invalid_response"], replayed_requests=counts["replay"], uncertain_outcomes=counts["uncertain"], failure_rate=round((completed-counts["success"])/completed,4) if completed else 0, latency_ms=latency_summary(latencies), status_codes=dict(codes), error_samples=samples, stop_reason=stopped_reason)
        atomic_json(folder/"report.json", result)
        return result

    headers = {}
    if os.getenv("APP_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["APP_TOKEN"]
    body = payload_for(config)
    limits = httpx.Limits(max_connections=config["concurrency"], max_keepalive_connections=config["concurrency"])
    async with httpx.AsyncClient(base_url=target, headers=headers, timeout=config["timeout_seconds"], limits=limits, trust_env=False, follow_redirects=False, transport=transport) as client:
        started = time.perf_counter()
        last_completed = started
        async def worker():
            nonlocal stopped_reason, last_completed
            while state["issued"] < config["request_count"]:
                if (folder/"stop").exists():
                    stopped_reason = "user_stop"
                    return
                if time.perf_counter()-started >= config["max_duration_seconds"]:
                    stopped_reason = "duration_limit"
                    return
                index = state["issued"]
                state["issued"] += 1
                state["in_flight"] += 1
                state["peak_in_flight"] = max(state["peak_in_flight"], state["in_flight"])
                key = "LT-"+config["id"]+"-"+str(0 if config["scenario"] == "idempotency" else index)
                tick = time.perf_counter()
                error = None
                trace = ""
                try:
                    # Overall deadline, including waiting for a response body.
                    response = await asyncio.wait_for(client.post("/api/trades", json=body, headers={"Idempotency-Key":key}), timeout=config["timeout_seconds"])
                    codes[str(response.status_code)] += 1
                    trace = response.headers.get("x-trace-id", "")
                    try:
                        data = response.json()
                    except (ValueError, TypeError):
                        data = {}
                    if not isinstance(data, dict):
                        data = {}
                    if response.is_success and data.get("status") == "SUCCEEDED" and data.get("id"):
                        counts["success"] += 1
                        successful_ids.add(data["id"])
                        counts["replay"] += bool(data.get("replayed"))
                    elif response.is_success and data.get("status") == "REJECTED":
                        counts["business_rejection"] += 1
                        error = data.get("error_code", "BUSINESS_REJECTION")
                    elif not response.is_success:
                        counts["http_error"] += 1
                        error = data.get("error_code", "HTTP_"+str(response.status_code))
                        if response.status_code >= 500 and error not in {"DEPENDENCY_UNAVAILABLE", "CONNECTION_ACQUIRE_TIMEOUT"}:
                            counts["uncertain"] += 1
                    else:
                        counts["invalid_response"] += 1
                        counts["uncertain"] += 1
                        error = "INVALID_RESPONSE"
                except (httpx.HTTPError, asyncio.TimeoutError) as exc:
                    counts["transport_error"] += 1
                    counts["uncertain"] += 1
                    error = type(exc).__name__
                finally:
                    last_completed = time.perf_counter()
                    latencies.append((last_completed-tick)*1000)
                    state["completed"] += 1
                    state["in_flight"] -= 1
                if error and len(samples) < 12:
                    samples.append({"idempotency_key":key, "error":error, "trace_id":trace})

        tasks = [asyncio.create_task(worker()) for _ in range(min(config["concurrency"], config["request_count"]))]
        try:
            while not all(task.done() for task in tasks):
                snapshot()
                await asyncio.sleep(.5)
            await asyncio.gather(*tasks)
            measured_elapsed = max(last_completed-started, .001)
            state["status"] = "VERIFYING"
            snapshot()
            try:
                verification = await asyncio.wait_for(client.post("/api/reconcile"), timeout=30)
                verification.raise_for_status()
                result = verification.json()
                if not isinstance(result.get("balanced"), bool):
                    raise ValueError("Invalid reconciliation response")
                state["reconciliation"] = result
            except (httpx.HTTPError, asyncio.TimeoutError, ValueError, AttributeError):
                state["warning"] = "压测已结束，但账务核对请求失败，请在账务页面重新核对。"
            if counts["uncertain"]:
                state["warning"] = (state["warning"] or "") + " 存在未确认结果；超时请求可能仍在服务端执行，当前对账不能证明这些请求全部完成。请按错误样本中的幂等键核查。"
            state["status"] = "STOPPED" if stopped_reason else "COMPLETED"
            state["finished_at"] = timestamp()
            return snapshot()
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

def main():
    folder = Path(sys.argv[1]).resolve()
    config = json.loads((folder/"config.json").read_text(encoding="utf-8"))
    try:
        asyncio.run(run_load(config, folder))
    except Exception as exc:
        previous = json.loads((folder/"report.json").read_text(encoding="utf-8"))
        previous.update(status="FAILED", finished_at=timestamp(), warning="压测进程异常："+type(exc).__name__)
        atomic_json(folder/"report.json", previous)
        raise

if __name__ == "__main__":
    main()
