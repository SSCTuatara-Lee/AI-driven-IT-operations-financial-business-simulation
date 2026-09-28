import os
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
os.environ["DATA_DIR"]=str(ROOT/"tests"/".runtime")
os.environ["DATABASE_URL"]="sqlite:///"+str(ROOT/"tests"/".runtime"/"tests.db")
os.environ["MODEL_BASE_URL"]=""
os.environ["CHAT_MODEL"]=""
os.environ["EMBEDDING_MODEL"]=""
os.environ["APP_TOKEN"]=""
from fastapi.testclient import TestClient
from app.db import Base, engine
from app.main import app

@pytest.fixture
def client():
    Base.metadata.drop_all(engine)
    with TestClient(app) as value:
        yield value
