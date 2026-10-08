from __future__ import annotations

import time

import httpx
import numpy as np

from app.constants import (
    BATCH_SIZE,
    BATCH_TIMEOUT,
    DEFAULT_COOLDOWN,
    EMBED_DIM,
    GEMINI_EMBED_MODEL,
    GROQ_EMBED_MODEL,
    GROQ_PROVIDER,
    REQUEST_TIMEOUT,
)
from app.core import settings

blocked_until = 0.0


class QuotaError(RuntimeError):
    pass


def rate_limited(provider: str, response: httpx.Response, patient: bool) -> None:
    """Wait out a 429 in batch jobs; in request paths fail fast and pause embedding for the retry window."""
    global blocked_until
    delay = retry_seconds(response)
    if not patient:
        blocked_until = time.time() + (delay or DEFAULT_COOLDOWN)
        raise QuotaError(f"{provider} rate limited")
    if delay is None:
        raise QuotaError(response.text[:300])
    print(f"{provider} rate limited, retry in {delay:.1f}s", flush=True)
    time.sleep(delay)


def document_text(title: str, detail: str = "", model: str = GEMINI_EMBED_MODEL) -> str:
    body = detail.strip() or "none"
    if GROQ_PROVIDER in model:
        return f"search_document: {title}. {body}"
    return f"title: {title} | text: {body}"


def query_text(query: str, model: str = GEMINI_EMBED_MODEL) -> str:
    if GROQ_PROVIDER in model:
        return f"search_query: {query}"
    return f"task: search result | query: {query}"


def embeddings_url() -> str:
    base = settings.BIFROST_URL.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/embeddings"
    return f"{base}/v1/embeddings"


def embed_texts(texts: list[str], model: str = GEMINI_EMBED_MODEL, patient: bool = False) -> tuple[np.ndarray, str]:
    if not texts:
        return np.zeros((0, EMBED_DIM), dtype=np.float32), model
    if not settings.BIFROST_URL:
        raise QuotaError("No embedding gateway")
    if not patient and time.time() < blocked_until:
        raise QuotaError("embedding paused after a rate limit")
    rows: list[list[float]] = []
    resolved = model
    with httpx.Client(timeout=BATCH_TIMEOUT if patient else REQUEST_TIMEOUT) as client:
        for start in range(0, len(texts), BATCH_SIZE):
            chunk = texts[start : start + BATCH_SIZE]
            embedded, resolved = embed_chunk(client, chunk, resolved, patient)
            rows.extend(embedded)
    matrix = np.asarray(rows, dtype=np.float32)
    if matrix.shape != (len(texts), EMBED_DIM):
        raise RuntimeError(f"{resolved} returned shape {matrix.shape}, expected {(len(texts), EMBED_DIM)}")
    return matrix, resolved


def embed_chunk(
    client: httpx.Client,
    texts: list[str],
    model: str,
    patient: bool,
) -> tuple[list[list[float]], str]:
    payload: dict = {"model": model, "input": texts}
    if model == GEMINI_EMBED_MODEL:
        payload["dimensions"] = EMBED_DIM
        payload["fallbacks"] = [GROQ_EMBED_MODEL]
    while True:
        response = client.post(
            embeddings_url(),
            headers={"Authorization": f"Bearer {settings.LLM_API_KEY}"},
            json=payload,
        )
        if response.status_code == 429:
            rate_limited("gateway", response, patient)
            continue
        if response.status_code >= 400:
            raise RuntimeError(f"Embedding failed ({response.status_code}): {response.text[:300]}")
        body = response.json()
        data = body.get("data") or []
        data.sort(key=lambda item: item.get("index", 0))
        if len(data) != len(texts):
            raise RuntimeError(f"Gateway returned {len(data)} vectors for {len(texts)} texts")
        return [item["embedding"] for item in data], str(body.get("model") or model)


def retry_seconds(response: httpx.Response) -> float | None:
    """Read the wait the provider puts on a 429. No delay is invented when the body has none."""
    header = response.headers.get("retry-after")
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    try:
        body = response.json()
    except Exception:
        return None
    details = body.get("error", {}).get("details") or []
    for item in details:
        delay = item.get("retryDelay")
        if isinstance(delay, (int, float)):
            return float(delay)
        if isinstance(delay, str) and delay.endswith("s"):
            try:
                return float(delay[:-1])
            except ValueError:
                continue
    return None


if __name__ == "__main__":
    from app.core import store
    from app.gov.catalog import embed_missing

    store.init_db()
    print(f"Embedded {embed_missing()} catalogue titles")
