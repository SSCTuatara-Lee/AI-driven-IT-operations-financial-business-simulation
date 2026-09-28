import json,sys,uuid
from pathlib import Path
import httpx
sys.stdout.reconfigure(encoding="utf-8")
root=Path(__file__).resolve().parents[1]
with httpx.Client(base_url="http://127.0.0.1:8000",timeout=10,trust_env=False) as client:
    assert client.get("/health/ready").status_code==200
    body={"kind":"transfer","source_id":"ACC-1001","target_id":"ACC-1002","amount":123}
    key="LIVE-"+uuid.uuid4().hex
    first=client.post("/api/trades",json=body,headers={"Idempotency-Key":key})
    assert first.status_code==200 and first.json()["status"]=="SUCCEEDED"
    repeated=client.post("/api/trades",json=body,headers={"Idempotency-Key":key})
    assert repeated.json()["replayed"] and repeated.json()["id"]==first.json()["id"]
    ledger=client.post("/api/reconcile").json()
    assert ledger["balanced"]
    logs=client.get("/api/logs",params={"trace_id":first.json()["trace_id"]}).json()
    assert any(log["event"]=="LEDGER_COMMITTED" for log in logs)
    chat=client.post("/api/chat",json={"question":"交易超时如何幂等重试？","session_id":"smoke-live-check"}).json()
    assert chat["citations"] and chat["mode"]=="retrieval_only"
    result={"health":"passed","trade":"passed","idempotency":"passed","reconciliation":"passed","logs":"passed","knowledge_chat":"passed","trade_id":first.json()["id"],"database":"sqlite","browser_verified":False}
    (root/"data"/"live-verification.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))
