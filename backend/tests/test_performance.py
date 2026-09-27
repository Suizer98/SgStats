"""Performance and load checks with budgets generous enough for CI runners."""

import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app import agents
from app.gov import data
from app.main import app

ROW_LIMIT = 10_000
SUMMARY_BUDGET_SECONDS = 3.0
CONCURRENT_REQUESTS = 40
REQUEST_BUDGET_SECONDS = 1.0


def large_dataset() -> dict:
    records = [
        {"period": f"{2000 + index % 25}-{(index % 12) + 1:02d}", "series": f"S{index % 40}", "measure": "Count", "value": float(index)}
        for index in range(ROW_LIMIT)
    ]
    return {"title": "Large", "source": "S", "grain": "month", "records": records}


def test_summarise_ten_thousand_rows_within_budget():
    started = time.perf_counter()
    summary = data.summarise([large_dataset(), large_dataset()])
    elapsed = time.perf_counter() - started
    assert summary["charts"]
    assert elapsed < SUMMARY_BUDGET_SECONDS, f"summarise took {elapsed:.2f}s"


def test_normalise_ten_thousand_rows_within_budget():
    records = [{"_id": index, "year": str(2000 + index % 25), "sector": f"S{index % 30}", "count": str(index)} for index in range(ROW_LIMIT)]
    started = time.perf_counter()
    rows = data.normalize_any(records)
    elapsed = time.perf_counter() - started
    assert len(rows) == ROW_LIMIT
    assert elapsed < SUMMARY_BUDGET_SECONDS, f"normalise took {elapsed:.2f}s"


@pytest.fixture
def quick_pipeline(monkeypatch: pytest.MonkeyPatch):
    def run(query, emit):
        emit("coordinator", "thought", "stub")
        return {"query": query, "datasets": [], "summary": {"metrics": [], "charts": []}, "report": {}}

    monkeypatch.setattr(agents, "run", run)


def test_concurrent_analysis_requests(quick_pipeline):
    client = TestClient(app)

    def submit(index: int) -> tuple[int, float]:
        started = time.perf_counter()
        response = client.post("/api/analyses", json={"query": f"load test {index}"})
        return response.status_code, time.perf_counter() - started

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(submit, range(CONCURRENT_REQUESTS)))

    statuses = [status for status, _ in results]
    latencies = sorted(seconds for _, seconds in results)
    p95 = latencies[int(len(latencies) * 0.95) - 1]
    assert statuses == [200] * CONCURRENT_REQUESTS
    assert p95 < REQUEST_BUDGET_SECONDS, f"p95 {p95:.2f}s"
    assert len(client.get("/api/analyses").json()) == CONCURRENT_REQUESTS
