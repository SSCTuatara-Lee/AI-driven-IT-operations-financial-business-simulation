import httpx
from app import knowledge

def mock_http(monkeypatch,handler):
    original=httpx.Client
    monkeypatch.setattr(knowledge,"API_BASE","https://model.invalid/v1")
    monkeypatch.setattr(knowledge,"CHAT_MODEL","test-chat")
    monkeypatch.setattr(knowledge,"EMBED_MODEL","test-embedding")
    monkeypatch.setattr(knowledge.httpx,"Client",lambda **kwargs: original(transport=httpx.MockTransport(handler),**kwargs))

def test_embedding_and_generation_adapter(client,monkeypatch):
    def handler(request):
        import json
        data=json.loads(request.content)
        if request.url.path.endswith("/embeddings"):
            return httpx.Response(200,json={"data":[{"index":i,"embedding":[1.0,0.0,0.0]} for i,_ in enumerate(data["input"])]})
        assert data["model"]=="test-chat"
        assert "manuals" in data["messages"][-1]["content"]
        return httpx.Response(200,json={"choices":[{"message":{"content":"请先按原幂等键查询交易状态。"}}]})
    mock_http(monkeypatch,handler)
    doc=knowledge.save_document("超时重试手册","交易超时后应使用原幂等键查询最终状态，不应更换新键重复支付。")
    assert doc["indexed_mode"]=="hybrid"
    retrieval=knowledge.search("交易超时")
    assert retrieval["mode"]=="hybrid"
    result=knowledge.answer("交易超时","adapter-session")
    assert result["mode"]=="rag" and result["citations"]
    assert "原幂等键" in result["answer"]

def test_model_failure_reports_fallback(client,monkeypatch):
    mock_http(monkeypatch,lambda request:httpx.Response(503,json={"error":"unavailable"}))
    result=knowledge.answer("交易超时","failure-session")
    assert result["mode"]=="retrieval_only"
    assert result["warning"] and result["citations"]
