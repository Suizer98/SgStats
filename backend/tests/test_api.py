import time

import pytest
from fastapi.testclient import TestClient

from app import agents
from app.core import store
from app.main import INTERRUPTED, app


client = TestClient(app)


@pytest.fixture(autouse=True)
def quick_pipeline(monkeypatch: pytest.MonkeyPatch):
    def run(query, emit, history=None):
        emit("coordinator", "thought", "stub")
        return {"query": query, "datasets": [], "summary": {"metrics": [], "charts": []}, "report": {}}

    monkeypatch.setattr(agents, "run", run)


def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_rejects_empty_query():
    response = client.post("/api/analyses", json={"query": "  "})
    assert response.status_code == 400


def test_create_and_fetch_analysis():
    response = client.post(
        "/api/analyses",
        json={"query": "Analyse employment trends in the technology sector from 2020-2024"},
    )
    assert response.status_code == 200
    analysis_id = response.json()["id"]
    conversation_id = response.json()["conversation_id"]
    fetched = client.get(f"/api/analyses/{analysis_id}")
    assert fetched.status_code == 200
    assert fetched.json()["query"].startswith("Analyse employment")
    assert fetched.json()["conversation_id"] == conversation_id

    conversation = client.get(f"/api/conversations/{conversation_id}")
    assert conversation.status_code == 200
    assert conversation.json()["analyses"][0]["id"] == analysis_id


def test_follow_up_uses_existing_conversation():
    first = client.post("/api/analyses", json={"query": "Analyse technology employment"})
    conversation_id = first.json()["conversation_id"]

    second = client.post(
        "/api/analyses",
        json={
            "query": "Now compare that with manufacturing",
            "conversation_id": conversation_id,
        },
    )

    assert second.status_code == 200
    assert second.json()["conversation_id"] == conversation_id
    conversation = client.get(f"/api/conversations/{conversation_id}").json()
    assert len(conversation["analyses"]) == 2


def wait_for(live: TestClient, analysis_id: str) -> dict:
    for _ in range(100):
        row = live.get(f"/api/analyses/{analysis_id}").json()
        if row["status"] != "running":
            return row
        time.sleep(0.02)
    raise AssertionError("analysis did not finish")


def test_background_job_finishes_and_websocket_replays_events():
    with TestClient(app) as live:
        analysis_id = live.post("/api/analyses", json={"query": "Analyse employment"}).json()["id"]
        row = wait_for(live, analysis_id)
        assert row["status"] == "done"
        assert row["events"][0]["content"] == "stub"
        with live.websocket_connect(f"/ws/analyses/{analysis_id}") as socket:
            assert socket.receive_json()["content"] == "stub"
            done = socket.receive_json()
        assert done["step"] == "done"
        assert done["result"]["query"] == "Analyse employment"


def test_pipeline_failure_is_stored_and_replayed(monkeypatch: pytest.MonkeyPatch):
    def broken(query, emit, history=None):
        emit("extractor", "observation", "All sources failed")
        raise RuntimeError("No dataset could be loaded")

    monkeypatch.setattr(agents, "run", broken)
    with TestClient(app) as live:
        analysis_id = live.post("/api/analyses", json={"query": "Analyse employment"}).json()["id"]
        row = wait_for(live, analysis_id)
        assert row["status"] == "failed"
        assert row["error"] == "No dataset could be loaded"
        with live.websocket_connect(f"/ws/analyses/{analysis_id}") as socket:
            socket.receive_json()
            assert socket.receive_json() == {"step": "error", "analysis_id": analysis_id, "content": "No dataset could be loaded"}


def test_history_lists_conversations():
    client.post("/api/analyses", json={"query": "Analyse housing"})
    assert any(item["title"].startswith("Analyse housing") for item in client.get("/api/conversations").json())


def test_unknown_resources_return_404():
    assert client.get("/api/analyses/missing").status_code == 404
    assert client.get("/api/conversations/missing").status_code == 404
    response = client.post("/api/analyses", json={"query": "q", "conversation_id": "missing"})
    assert response.status_code == 404


def test_invalid_body_returns_422():
    assert client.post("/api/analyses", json={}).status_code == 422


def test_delete_analysis_removes_it_from_history():
    with TestClient(app) as live:
        created = live.post("/api/analyses", json={"query": "hello there"}).json()
        analysis_id = created["id"]
        wait_for(live, analysis_id)
        assert live.delete(f"/api/analyses/{analysis_id}").status_code == 200
        assert live.get(f"/api/analyses/{analysis_id}").status_code == 404
        assert live.get(f"/api/conversations/{created['conversation_id']}").status_code == 404


def test_clear_history_leaves_a_running_analysis():
    with TestClient(app) as live:
        finished = live.post("/api/analyses", json={"query": "thanks"}).json()["id"]
        wait_for(live, finished)
        store.create_analysis("still-running", "Births and fertility trends in Singapore")
        removed = live.delete("/api/analyses")
        assert removed.status_code == 200
        assert removed.json()["deleted"] >= 1
        listed = live.get("/api/analyses").json()
        assert "still-running" in [row["id"] for row in listed]
        assert finished not in [row["id"] for row in listed]
        assert all(row["status"] == "running" for row in listed)


def test_running_analysis_cannot_be_deleted():
    store.create_analysis("live-1", "Analyse employment")
    assert client.delete("/api/analyses/live-1").status_code == 409


def test_restart_marks_interrupted_analyses_failed():
    store.create_analysis("orphan-1", "Births and fertility trends in Singapore")
    with TestClient(app) as live:
        row = live.get("/api/analyses/orphan-1").json()
    assert row["status"] == "failed"
    assert row["error"] == INTERRUPTED
