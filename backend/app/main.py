from __future__ import annotations

import asyncio
import json
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app import agents
from app.agents.general.agent import conversation_history
from app.constants import INTERRUPTED
from app.core import store
from app.gov import catalog


@asynccontextmanager
async def lifespan(application: FastAPI):
    await asyncio.to_thread(store.init_db)
    await asyncio.to_thread(catalog.sync_saved_vectors)
    await asyncio.to_thread(store.fail_interrupted, INTERRUPTED)
    yield


app = FastAPI(title="SgStats", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

sockets: dict[str, list[WebSocket]] = defaultdict(list)
jobs: set[str] = set()
stopped: set[str] = set()


class Stopped(Exception):
    pass


class QueryBody(BaseModel):
    query: str
    conversation_id: str | None = None


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/analyses")
def list_analyses():
    return store.list_analyses()


@app.get("/api/conversations")
def list_conversations():
    return store.list_conversations()


@app.get("/api/conversations/{conversation_id}")
def get_conversation(conversation_id: str):
    row = store.get_conversation(conversation_id)
    if not row:
        raise HTTPException(404, "Conversation not found")
    return row


@app.delete("/api/conversations/{conversation_id}")
def remove_conversation(conversation_id: str):
    row = store.get_conversation(conversation_id)
    if not row:
        raise HTTPException(404, "Not found")
    if any(item["id"] in jobs or item["status"] == "running" for item in row["analyses"]):
        raise HTTPException(409, "This analysis is still running.")
    try:
        deleted = store.delete_conversation(conversation_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if not deleted:
        raise HTTPException(404, "Not found")
    return {"deleted": conversation_id}


@app.delete("/api/analyses/{analysis_id}")
def remove_analysis(analysis_id: str):
    if analysis_id in jobs:
        raise HTTPException(409, "This analysis is still running.")
    try:
        deleted = store.delete_analysis(analysis_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if not deleted:
        raise HTTPException(404, "Not found")
    return {"deleted": analysis_id}


@app.delete("/api/analyses")
def remove_history():
    return {"deleted": store.clear_history()}


@app.get("/api/analyses/{analysis_id}")
def get_analysis(analysis_id: str):
    row = store.get_analysis(analysis_id)
    if not row:
        raise HTTPException(404, "Not found")
    return row


@app.post("/api/analyses")
async def create_analysis(body: QueryBody):
    query = body.query.strip()
    if not query:
        raise HTTPException(400, "Query is required")
    analysis_id = str(uuid.uuid4())
    try:
        conversation_id = store.create_analysis(
            analysis_id,
            query,
            body.conversation_id,
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    asyncio.create_task(run_job(analysis_id, query))
    return {
        "id": analysis_id,
        "conversation_id": conversation_id,
        "status": "running",
    }


@app.post("/api/analyses/{analysis_id}/abort")
def abort_analysis(analysis_id: str):
    row = store.get_analysis(analysis_id)
    if not row:
        raise HTTPException(404, "Not found")
    if row["status"] != "running":
        raise HTTPException(409, "This analysis is not running.")
    stopped.add(analysis_id)
    return {"aborted": analysis_id}


@app.websocket("/ws/analyses/{analysis_id}")
async def analysis_socket(websocket: WebSocket, analysis_id: str):
    await websocket.accept()
    sockets[analysis_id].append(websocket)
    try:
        await replay(websocket, analysis_id)
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in sockets[analysis_id]:
            sockets[analysis_id].remove(websocket)


async def replay(websocket: WebSocket, analysis_id: str) -> None:
    """Send everything already recorded so a late or reconnecting client catches up."""
    row = await asyncio.to_thread(store.get_analysis, analysis_id)
    if not row:
        return
    for event in row["events"]:
        await websocket.send_text(json.dumps(event, default=str))
    if row["status"] == "done" and row["result"]:
        await websocket.send_text(
            json.dumps({"step": "done", "analysis_id": analysis_id, "result": row["result"]}, default=str)
        )
    elif row["status"] == "failed":
        await websocket.send_text(
            json.dumps(
                {
                    "step": "error",
                    "analysis_id": analysis_id,
                    "content": row["error"] or "Analysis failed.",
                },
                default=str,
            )
        )


async def run_job(analysis_id: str, query: str) -> None:
    if analysis_id in jobs:
        return
    jobs.add(analysis_id)
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def emit(agent: str, step: str, content: str) -> None:
        if analysis_id in stopped:
            raise Stopped("Stopped.")
        event = store.save_event(analysis_id, agent, step, content)
        loop.call_soon_threadsafe(queue.put_nowait, event)

    async def pump() -> None:
        while True:
            event = await queue.get()
            if event is None:
                break
            await broadcast(analysis_id, event)

    pump_task = asyncio.create_task(pump())
    try:
        history = await asyncio.to_thread(conversation_history, analysis_id)
        result = await asyncio.to_thread(agents.run, query, emit, history)
        if analysis_id in stopped:
            raise Stopped("Stopped.")
        await asyncio.sleep(0)
        await asyncio.to_thread(
            store.save_source_chunks,
            analysis_id,
            result.get("datasets", []),
        )
        result = json.loads(json.dumps(result, default=str))
        store.finish_analysis(analysis_id, result, None)
        await broadcast(analysis_id, {"step": "done", "analysis_id": analysis_id, "result": result})
    except Exception as exc:
        message = "Stopped." if analysis_id in stopped or isinstance(exc, Stopped) else str(exc)
        store.finish_analysis(analysis_id, None, message)
        await broadcast(analysis_id, {"step": "error", "analysis_id": analysis_id, "content": message})
    finally:
        jobs.discard(analysis_id)
        stopped.discard(analysis_id)
        queue.put_nowait(None)
        await pump_task


async def broadcast(analysis_id: str, payload: dict) -> None:
    message = json.dumps(payload)
    living = []
    for socket in sockets[analysis_id]:
        try:
            await socket.send_text(message)
            living.append(socket)
        except Exception:
            pass
    sockets[analysis_id] = living
