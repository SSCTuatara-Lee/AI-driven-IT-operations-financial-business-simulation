from pathlib import Path
import sys
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from sqlalchemy import create_mock_engine
from app.db import Base
statements=[]
engine=create_mock_engine("mysql+pymysql://",lambda sql,*a,**kw:statements.append(str(sql.compile(dialect=engine.dialect))))
Base.metadata.create_all(engine)
assert any("LONGTEXT" in sql for sql in statements)
assert any("UNIQUE (idempotency_key)" in sql for sql in statements)
(root/"docs"/"mysql-schema.sql").write_text(";\n".join(statements)+";\n",encoding="utf-8")
print(f"MySQL DDL compiled for {len(Base.metadata.tables)} tables; no real MySQL connection used")
