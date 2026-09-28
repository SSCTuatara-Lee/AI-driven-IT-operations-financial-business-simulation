import os
from pathlib import Path
from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, Text, create_engine, event
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///" + str(DATA_DIR / "finops.db"))
engine = create_engine(DATABASE_URL, pool_pre_ping=True, **({"connect_args": {"check_same_thread": False, "timeout": 30}} if DATABASE_URL.startswith("sqlite") else {}))
if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def sqlite_options(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
Session = sessionmaker(engine, expire_on_commit=False)

LargeText = Text().with_variant(LONGTEXT(), "mysql")

class Base(DeclarativeBase):
    pass

class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(20), default="customer")
    currency: Mapped[str] = mapped_column(String(3), default="CNY")
    balance: Mapped[int] = mapped_column(BigInteger, default=0)
    frozen: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[str] = mapped_column(String(40))

class Trade(Base):
    __tablename__ = "trades"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(20))
    source_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"))
    target_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"))
    amount: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), default="CNY")
    status: Mapped[str] = mapped_column(String(20))
    error_code: Mapped[str] = mapped_column(String(50), default="")
    original_id: Mapped[str | None] = mapped_column(ForeignKey("trades.id"), nullable=True)
    refunded: Mapped[int] = mapped_column(BigInteger, default=0)
    trace_id: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[str] = mapped_column(String(40), index=True)

class Entry(Base):
    __tablename__ = "entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_id: Mapped[str] = mapped_column(ForeignKey("trades.id"), index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True)
    side: Mapped[str] = mapped_column(String(10))
    delta: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[str] = mapped_column(String(40))

class Log(Base):
    __tablename__ = "logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[str] = mapped_column(String(40), index=True)
    level: Mapped[str] = mapped_column(String(10))
    service: Mapped[str] = mapped_column(String(40))
    trace_id: Mapped[str] = mapped_column(String(32), index=True)
    span_id: Mapped[str] = mapped_column(String(16))
    transaction_id: Mapped[str] = mapped_column(String(40), default="", index=True)
    event: Mapped[str] = mapped_column(String(80))
    message: Mapped[str] = mapped_column(LargeText)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[int] = mapped_column(Integer, default=200)

class Fault(Base):
    __tablename__ = "faults"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))
    started_at: Mapped[str] = mapped_column(String(40))
    expires_at: Mapped[str] = mapped_column(String(40))
    stopped_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    delay_ms: Mapped[int] = mapped_column(Integer, default=0)

class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    version: Mapped[str] = mapped_column(String(40))
    service: Mapped[str] = mapped_column(String(40))
    content: Mapped[str] = mapped_column(LargeText)
    updated_at: Mapped[str] = mapped_column(String(40))

class Chunk(Base):
    __tablename__ = "chunks"
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(LargeText)
    embedding: Mapped[str | None] = mapped_column(LargeText, nullable=True)
    embedding_model: Mapped[str] = mapped_column(String(120), default="")

class ChatTurn(Base):
    __tablename__ = "chat_turns"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(40), index=True)
    question: Mapped[str] = mapped_column(LargeText)
    answer: Mapped[str] = mapped_column(LargeText)
    citations: Mapped[str] = mapped_column(LargeText)
    mode: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[str] = mapped_column(String(40))

