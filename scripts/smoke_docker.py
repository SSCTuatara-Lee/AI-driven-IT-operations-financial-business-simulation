"""Verify the Docker/MySQL lab via public HTTP APIs using dedicated accounts."""
import json
import os
import sys
import uuid
from pathlib import Path
import httpx

root=Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8")
for line in (root/".env").read_text(encoding="utf-8").splitlines():
    if line.startswith("APP_TOKEN="):
        os.environ.setdefault("APP_TOKEN",line.split("=",1)[1].strip().strip('"').strip("'"))
headers={"Authorization":"Bearer "+os.environ["APP_TOKEN"]} if os.getenv("APP_TOKEN") else {}
with httpx.Client(base_url="http://127.0.0.1:8001",headers=headers,timeout=30,trust_env=False) as client:
    def post(path,body=None,extra_headers=None):
        response=client.post(path,json=body or {},headers=extra_headers)
        response.raise_for_status()
        return response.json()
    assert client.get("/health/ready").json()["status"]=="ok"
    assert client.get("/api/config").json()["database"]=="mysql"
    run=uuid.uuid4().hex[:8]
    source=post("/api/accounts",{"name":"容器验收付款 "+run})["id"]
    target=post("/api/accounts",{"name":"容器验收收款 "+run})["id"]
    merchant=post("/api/accounts",{"name":"容器验收商户 "+run,"kind":"merchant"})["id"]
    def trade(kind,amount,from_id=None,to_id=None,original_id=None,key=None):
        return post("/api/trades",{"kind":kind,"amount":amount,"source_id":from_id,"target_id":to_id,"original_id":original_id},{"Idempotency-Key":key or "DOCKER-"+uuid.uuid4().hex})
    assert trade("deposit",10000,to_id=source)["status"]=="SUCCEEDED"
    key="DOCKER-"+uuid.uuid4().hex
    transfer=trade("transfer",2000,source,target,key=key)
    replay=trade("transfer",2000,source,target,key=key)
    assert replay["replayed"] and replay["id"]==transfer["id"]
    assert trade("withdrawal",500,source)["status"]=="SUCCEEDED"
    payment=trade("payment",1000,source,merchant)
    assert payment["status"]=="SUCCEEDED"
    assert trade("refund",400,original_id=payment["id"])["status"]=="SUCCEEDED"
    assert trade("refund",700,original_id=payment["id"])["error_code"]=="REFUND_LIMIT"
    accounts={a["id"]:a for a in client.get("/api/accounts").json()}
    assert [accounts[a]["balance"] for a in (source,target,merchant)]==[6900,2000,600]
    logs=client.get("/api/logs",params={"trace_id":transfer["trace_id"]}).json()
    assert any(log["event"]=="LEDGER_COMMITTED" for log in logs)
    fault_verified=False
    if not client.get("/api/faults").json()["active"]:
        fault=post("/api/faults",{"kind":"response_lost","duration_seconds":30})
        try:
            lost_key="DOCKER-"+uuid.uuid4().hex
            body={"kind":"transfer","amount":1,"source_id":source,"target_id":target,"original_id":None}
            response=client.post("/api/trades",json=body,headers={"Idempotency-Key":lost_key})
            assert response.status_code==504
            found=client.get("/api/trades",params={"q":lost_key}).json()
            assert len(found)==1 and found[0]["status"]=="SUCCEEDED"
            diagnosis=post("/api/diagnose",{"trace_id":response.json()["trace_id"]})
            assert {event["event"] for event in diagnosis["evidence"]}>={"LEDGER_COMMITTED","RESPONSE_TIMEOUT"}
            fault_verified=True
        finally:
            post("/api/faults/"+fault["id"]+"/stop")
        assert post("/api/trades",body,{"Idempotency-Key":lost_key})["replayed"]
    ledger=post("/api/reconcile")
    assert ledger["balanced"]
    chat=post("/api/chat",{"question":"交易超时如何幂等重试？","session_id":"docker-verify-"+run})
    assert chat["citations"] and chat["mode"] in {"retrieval_only","rag"}
    result={"database":"mysql","health":"passed","dedicated_accounts":[source,target,merchant],"deposit_withdrawal_transfer_payment_refund":"passed","refund_limit":"passed","idempotency":"passed","logs":"passed","lost_response_and_diagnosis":fault_verified,"reconciliation":ledger,"knowledge_chat":"passed","browser_verified":False}
    (root/"data/docker-verification.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))
