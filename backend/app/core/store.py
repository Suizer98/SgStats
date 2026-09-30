from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, event, inspect, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.types import JSON

from app.constants import EMBED_DIM
from app.core import settings


class Base(DeclarativeBase):
    pass


JsonType = JSONB().with_variant(JSON(), "sqlite")
EmbeddingType = Vector(EMBED_DIM).with_variant(JSON(), "sqlite")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id"), nullable=True, index=True)
    query: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    result_json: Mapped[dict | None] = mapped_column(JsonType, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AgentEvent(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("analyses.id"))
    agent: Mapped[str] = mapped_column(String(64))
    step: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class DatasetEntry(Base):
    __tablename__ = "dataset_entries"
    __table_args__ = (UniqueConstraint("provider", "dataset_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(32))
    dataset_id: Mapped[str] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(Text, default="")
    agency: Mapped[str] = mapped_column(Text, default="")
    coverage_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    coverage_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[str] = mapped_column(Text, default="")
    embedding: Mapped[Any] = mapped_column(EmbeddingType, nullable=True)


class SourceChunk(Base):
    __tablename__ = "source_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("analyses.id"))
    source: Mapped[str] = mapped_column(String(128))
    citation: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[Any] = mapped_column(EmbeddingType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


engine = None
SessionLocal = None


def database_url() -> str:
    if settings.DATABASE_URL:
        return settings.DATABASE_URL
    return "sqlite:///:memory:"


def enable_foreign_keys(connection, record) -> None:
    connection.execute("PRAGMA foreign_keys=ON")


def init_db() -> None:
    global engine, SessionLocal
    url = database_url()
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args)
    if url.startswith("sqlite"):
        event.listen(engine, "connect", enable_foreign_keys)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    if url.startswith("postgresql"):
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(bind=engine)
    migrate_conversations()


def migrate_conversations() -> None:
    columns = {column["name"] for column in inspect(engine).get_columns("analyses")}
    if "conversation_id" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE analyses ADD COLUMN conversation_id VARCHAR(36)"))

    db = get_session()
    try:
        rows = db.query(Analysis).filter(Analysis.conversation_id.is_(None)).all()
        for row in rows:
            conversation_id = str(uuid.uuid4())
            db.add(
                Conversation(
                    id=conversation_id,
                    title=row.query[:200],
                    created_at=row.created_at,
                    updated_at=row.created_at,
                )
            )
            row.conversation_id = conversation_id
        db.commit()
    finally:
        db.close()


def get_session():
    if SessionLocal is None:
        init_db()
    return SessionLocal()


def create_analysis(analysis_id: str, query: str, conversation_id: str | None = None) -> str:
    db = get_session()
    try:
        conversation = db.get(Conversation, conversation_id) if conversation_id else None
        if conversation_id and not conversation:
            raise ValueError("Conversation not found")
        if not conversation:
            conversation = Conversation(
                id=str(uuid.uuid4()),
                title=query[:200],
            )
            db.add(conversation)
        conversation.updated_at = datetime.now(timezone.utc)
        db.flush()
        db.add(
            Analysis(
                id=analysis_id,
                conversation_id=conversation.id,
                query=query,
                status="running",
            )
        )
        db.commit()
        return conversation.id
    finally:
        db.close()


def save_event(analysis_id: str, agent: str, step: str, content: str) -> dict:
    db = get_session()
    try:
        row = AgentEvent(
            analysis_id=analysis_id,
            agent=agent,
            step=step,
            content=content,
        )
        db.add(row)
        db.commit()
        return event_to_dict(row)
    finally:
        db.close()


def event_to_dict(row: AgentEvent) -> dict:
    return {
        "id": row.id,
        "analysis_id": row.analysis_id,
        "agent": row.agent,
        "step": row.step,
        "content": row.content,
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }


def fail_interrupted(message: str) -> int:
    db = get_session()
    try:
        rows = db.query(Analysis).filter(Analysis.status == "running").all()
        for row in rows:
            row.status = "failed"
            row.error = message
        db.commit()
        return len(rows)
    finally:
        db.close()


def finish_analysis(analysis_id: str, result: dict | None, error: str | None) -> None:
    db = get_session()
    try:
        row = db.get(Analysis, analysis_id)
        if not row:
            return
        row.status = "failed" if error else "done"
        row.result_json = result
        row.error = error
        db.commit()
    finally:
        db.close()


def postgres_enabled() -> bool:
    return database_url().startswith("postgresql")


def upsert_datasets(rows: list[dict]) -> int:
    if not postgres_enabled() or not rows:
        return 0
    db = get_session()
    try:
        for row in rows:
            existing = (
                db.query(DatasetEntry)
                .filter_by(provider=row["provider"], dataset_id=row["dataset_id"])
                .one_or_none()
            )
            if existing is None:
                db.add(
                    DatasetEntry(
                        provider=row["provider"],
                        dataset_id=row["dataset_id"],
                        title=row.get("title") or "",
                        agency=row.get("agency") or "",
                        coverage_start=row.get("coverage_start"),
                        coverage_end=row.get("coverage_end"),
                        detail=row.get("detail") or "",
                        embedding=row.get("embedding"),
                    )
                )
                continue
            existing.title = row.get("title") or existing.title
            existing.agency = row.get("agency") or existing.agency
            if row.get("coverage_start"):
                existing.coverage_start = row["coverage_start"]
            if row.get("coverage_end"):
                existing.coverage_end = row["coverage_end"]
            if row.get("detail"):
                existing.detail = row["detail"]
            if row.get("embedding") is not None:
                existing.embedding = row["embedding"]
        db.commit()
        return len(rows)
    finally:
        db.close()


def embedded_dataset_count() -> int:
    if not postgres_enabled():
        return 0
    db = get_session()
    try:
        return db.query(DatasetEntry).filter(DatasetEntry.embedding.is_not(None)).count()
    finally:
        db.close()


def rank_datasets(query_vector: list[float], limit: int = 24) -> list[dict]:
    if not postgres_enabled():
        return []
    db = get_session()
    try:
        distance = DatasetEntry.embedding.cosine_distance(query_vector)
        rows = (
            db.query(DatasetEntry, distance.label("distance"))
            .filter(DatasetEntry.embedding.is_not(None))
            .order_by(distance)
            .limit(limit)
            .all()
        )
        found = []
        for row, value in rows:
            found.append(
                {
                    "provider": row.provider,
                    "id": row.dataset_id,
                    "title": row.title,
                    "agency": row.agency,
                    "coverage_start": row.coverage_start,
                    "coverage_end": row.coverage_end,
                    "score": round(1 - float(value), 4),
                }
            )
        return found
    finally:
        db.close()


def save_source_chunks(analysis_id: str, datasets: list[dict]) -> None:
    db = get_session()
    try:
        for dataset in datasets:
            content = json.dumps(
                {
                    "source": dataset.get("source"),
                    "title": dataset.get("title"),
                    "mode": dataset.get("mode"),
                    "records": dataset.get("records", [])[:20],
                }
            )
            db.add(
                SourceChunk(
                    analysis_id=analysis_id,
                    source=str(dataset.get("source", "")),
                    citation=str(dataset.get("citation", "")),
                    content=content,
                )
            )
        db.commit()
    finally:
        db.close()


def delete_conversation(conversation_id: str) -> bool:
    db = get_session()
    try:
        conversation = db.get(Conversation, conversation_id)
        if not conversation:
            return False
        rows = db.query(Analysis).filter(Analysis.conversation_id == conversation_id).all()
        if any(row.status == "running" for row in rows):
            raise ValueError("This analysis is still running.")
        for row in rows:
            db.query(AgentEvent).filter(AgentEvent.analysis_id == row.id).delete()
            db.query(SourceChunk).filter(SourceChunk.analysis_id == row.id).delete()
            db.delete(row)
        db.delete(conversation)
        db.commit()
        return True
    finally:
        db.close()


def delete_analysis(analysis_id: str) -> bool:
    db = get_session()
    try:
        row = db.get(Analysis, analysis_id)
        if not row:
            return False
        if row.status == "running":
            raise ValueError("This analysis is still running.")
        conversation_id = row.conversation_id
        db.query(AgentEvent).filter(AgentEvent.analysis_id == analysis_id).delete()
        db.query(SourceChunk).filter(SourceChunk.analysis_id == analysis_id).delete()
        db.delete(row)
        db.flush()
        if conversation_id and db.query(Analysis).filter(Analysis.conversation_id == conversation_id).count() == 0:
            conversation = db.get(Conversation, conversation_id)
            if conversation:
                db.delete(conversation)
        db.commit()
        return True
    finally:
        db.close()


def clear_history() -> int:
    db = get_session()
    try:
        rows = db.query(Analysis).filter(Analysis.status != "running").all()
        deleted = 0
        for row in rows:
            db.query(AgentEvent).filter(AgentEvent.analysis_id == row.id).delete()
            db.query(SourceChunk).filter(SourceChunk.analysis_id == row.id).delete()
            conversation_id = row.conversation_id
            db.delete(row)
            db.flush()
            if conversation_id and db.query(Analysis).filter(Analysis.conversation_id == conversation_id).count() == 0:
                conversation = db.get(Conversation, conversation_id)
                if conversation:
                    db.delete(conversation)
            deleted += 1
        db.commit()
        return deleted
    finally:
        db.close()


def get_analysis(analysis_id: str) -> dict | None:
    db = get_session()
    try:
        row = db.get(Analysis, analysis_id)
        if not row:
            return None
        events = (
            db.query(AgentEvent)
            .filter(AgentEvent.analysis_id == analysis_id)
            .order_by(AgentEvent.id)
            .all()
        )
        return row_to_dict(row, events)
    finally:
        db.close()


def list_analyses() -> list[dict]:
    db = get_session()
    try:
        rows = db.query(Analysis).order_by(Analysis.created_at.desc()).all()
        return [row_to_dict(row, []) for row in rows]
    finally:
        db.close()


def get_conversation(conversation_id: str) -> dict | None:
    db = get_session()
    try:
        conversation = db.get(Conversation, conversation_id)
        if not conversation:
            return None
        analyses = (
            db.query(Analysis)
            .filter(Analysis.conversation_id == conversation_id)
            .order_by(Analysis.created_at)
            .all()
        )
        return conversation_to_dict(conversation, analyses)
    finally:
        db.close()


def list_conversations() -> list[dict]:
    db = get_session()
    try:
        conversations = db.query(Conversation).order_by(Conversation.updated_at.desc()).all()
        output = []
        for conversation in conversations:
            analyses = (
                db.query(Analysis)
                .filter(Analysis.conversation_id == conversation.id)
                .order_by(Analysis.created_at)
                .all()
            )
            output.append(conversation_to_dict(conversation, analyses))
        return output
    finally:
        db.close()


def conversation_to_dict(conversation: Conversation, analyses: list[Analysis]) -> dict:
    return {
        "id": conversation.id,
        "title": conversation.title,
        "created_at": conversation.created_at.isoformat() if conversation.created_at else "",
        "updated_at": conversation.updated_at.isoformat() if conversation.updated_at else "",
        "analyses": [row_to_dict(row, []) for row in analyses],
    }


def row_to_dict(row: Analysis, events: list[AgentEvent]) -> dict:
    created = row.created_at.isoformat() if row.created_at else ""
    return {
        "id": row.id,
        "conversation_id": row.conversation_id,
        "query": row.query,
        "status": row.status,
        "result": row.result_json,
        "error": row.error,
        "created_at": created,
        "events": [event_to_dict(item) for item in events],
    }
