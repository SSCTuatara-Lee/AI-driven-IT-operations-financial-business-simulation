"""Start a bounded load run through the same API used by the web page."""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.loadtest_worker import ACTIVE, validate_target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--requests", type=int, default=1000)
    parser.add_argument("--scenario", choices=["transfer","payment","deposit","withdrawal","idempotency"], default="transfer")
    parser.add_argument("--amount-cents", type=int, default=100)
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--duration", type=int, default=120)
    parser.add_argument("--output", help="Optional local JSON report path")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    target = validate_target(args.url)
    token = os.getenv("APP_TOKEN", "")
    if not token and (ROOT/".env").exists():
        for line in (ROOT/".env").read_text(encoding="utf-8").splitlines():
            if line.startswith("APP_TOKEN="):
                token = line.split("=",1)[1].strip().strip('"').strip("'")
    headers = {"Authorization":"Bearer "+token} if token else {}
    with httpx.Client(base_url=target, headers=headers, timeout=60, trust_env=False, follow_redirects=False) as client:
        response = client.post("/api/loadtests", json={"scenario":args.scenario,"concurrency":args.concurrency,"request_count":args.requests,"amount_cents":args.amount_cents,"timeout_seconds":args.timeout,"max_duration_seconds":args.duration})
        if not response.is_success:
            print(response.text)
            return 1
        report = response.json()
        run_id = report["id"]
        print("Started "+run_id, flush=True)
        try:
            while report["status"] in ACTIVE:
                time.sleep(1)
                response = client.get("/api/loadtests/"+run_id)
                response.raise_for_status()
                report = response.json()
        except KeyboardInterrupt:
            client.post("/api/loadtests/"+run_id+"/stop").raise_for_status()
            print("Stop requested; check the web report for in-flight results.")
            return 130
    if args.output:
        Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    fields = ["id","status","scenario","concurrency","completed","peak_in_flight","elapsed_seconds","requests_per_second","confirmed_transactions_per_second","unique_succeeded_transactions","replayed_requests","failure_rate","latency_ms","reconciliation","warning"]
    print(json.dumps({key:report.get(key) for key in fields},ensure_ascii=False,indent=2))
    return 0 if report["status"]=="COMPLETED" and not report.get("failure_rate") and (report.get("reconciliation") or {}).get("balanced") else 1


if __name__ == "__main__":
    raise SystemExit(main())
