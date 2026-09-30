from __future__ import annotations

import time
from pathlib import Path

import httpx
import numpy as np

from app.constants import (
    BATCH_SIZE,
    BATCH_TIMEOUT,
    DEFAULT_COOLDOWN,
    EMBED_DIM,
    GEMINI_PROVIDER,
    GEMINI_URL,
    GROQ_PROVIDER,
    GROQ_URL,
    REQUEST_TIMEOUT,
    VECTOR_PATH,
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


def document_text(title: str, detail: str = "", provider: str = GEMINI_PROVIDER) -> str:
    body = detail.strip() or "none"
    if provider == GROQ_PROVIDER:
        return f"search_document: {title}. {body}"
    return f"title: {title} | text: {body}"


def query_text(query: str, provider: str = GEMINI_PROVIDER) -> str:
    if provider == GROQ_PROVIDER:
        return f"search_query: {query}"
    return f"task: search result | query: {query}"


def embed_texts(texts: list[str], provider: str = GEMINI_PROVIDER, patient: bool = False) -> np.ndarray:
    if not texts:
        return np.zeros((0, EMBED_DIM), dtype=np.float32)
    if not patient and time.time() < blocked_until:
        raise QuotaError("embedding paused after a rate limit")
    rows: list[list[float]] = []
    with httpx.Client(timeout=BATCH_TIMEOUT if patient else REQUEST_TIMEOUT) as client:
        for start in range(0, len(texts), BATCH_SIZE):
            chunk = texts[start : start + BATCH_SIZE]
            if provider == GROQ_PROVIDER:
                rows.extend(embed_groq(client, chunk, patient))
            else:
                rows.extend(embed_gemini(client, chunk, patient))
    matrix = np.asarray(rows, dtype=np.float32)
    if matrix.shape != (len(texts), EMBED_DIM):
        raise RuntimeError(f"{provider} returned shape {matrix.shape}, expected {(len(texts), EMBED_DIM)}")
    return matrix


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


def embed_gemini(client: httpx.Client, texts: list[str], patient: bool = False) -> list[list[float]]:
    if not settings.GEMINI_API_KEY:
        raise QuotaError("GEMINI_API_KEY is not set")
    payload = {
        "requests": [
            {
                "model": "models/gemini-embedding-2",
                "content": {"parts": [{"text": text}]},
                "output_dimensionality": EMBED_DIM,
            }
            for text in texts
        ]
    }
    while True:
        response = client.post(GEMINI_URL, headers={"x-goog-api-key": settings.GEMINI_API_KEY}, json=payload)
        if response.status_code == 429:
            rate_limited("gemini", response, patient)
            continue
        if response.status_code >= 400:
            raise RuntimeError(f"Gemini embedding failed ({response.status_code}): {response.text[:300]}")
        embeddings = response.json().get("embeddings") or []
        if len(embeddings) != len(texts):
            raise RuntimeError(f"Gemini returned {len(embeddings)} vectors for {len(texts)} texts")
        return [item["values"] for item in embeddings]


def embed_groq(client: httpx.Client, texts: list[str], patient: bool = False) -> list[list[float]]:
    if not settings.GROQ_API_KEY:
        raise QuotaError("GROQ_API_KEY is not set")
    response = client.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
        json={"model": GROQ_PROVIDER, "input": texts, "encoding_format": "float"},
    )
    if response.status_code == 429:
        rate_limited("groq", response, patient)
        return embed_groq(client, texts, patient)
    if response.status_code >= 400:
        raise RuntimeError(f"Groq embedding failed ({response.status_code}): {response.text[:300]}")
    rows = response.json().get("data") or []
    rows.sort(key=lambda item: item.get("index", 0))
    if len(rows) != len(texts):
        raise RuntimeError(f"Groq returned {len(rows)} vectors for {len(texts)} texts")
    return [item["embedding"] for item in rows]


def build_title_vectors(items: list[dict], path: Path, provider: str = GEMINI_PROVIDER) -> int:
    """Embed dataset titles in index order. A partial file lets a stopped run continue."""
    ids = [item["id"] for item in items]
    done = 0
    parts: list[np.ndarray] = []
    partial = path.with_suffix(".partial.npz")
    if partial.exists():
        saved = np.load(partial, allow_pickle=False)
        saved_ids = [str(item) for item in saved["ids"]]
        if ids[: len(saved_ids)] == saved_ids and len(saved_ids) > 0:
            done = len(saved_ids)
            parts.append(saved["vectors"])
            if "provider" in saved:
                provider = str(saved["provider"])
    while done < len(items):
        chunk = items[done : done + BATCH_SIZE]
        texts = [document_text(item["title"], item.get("agency", ""), provider) for item in chunk]
        try:
            part = embed_texts(texts, provider, patient=True)
        except QuotaError:
            if done == 0 and provider == GEMINI_PROVIDER and settings.GROQ_API_KEY:
                provider = GROQ_PROVIDER
                print("gemini quota blocked the index, embedding titles with groq", flush=True)
                texts = [document_text(item["title"], item.get("agency", ""), provider) for item in chunk]
                part = embed_texts(texts, provider, patient=True)
            else:
                raise
        parts.append(part)
        done += len(chunk)
        matrix = np.vstack(parts)
        np.savez_compressed(partial, ids=np.array(ids[:done]), vectors=matrix, provider=np.array(provider))
        print(f"embedded {done}/{len(items)} via {provider}", flush=True)
    matrix = np.vstack(parts) if parts else np.zeros((0, EMBED_DIM), dtype=np.float32)
    np.savez_compressed(path, ids=np.array(ids), vectors=matrix, provider=np.array(provider))
    partial.unlink(missing_ok=True)
    return len(ids)


if __name__ == "__main__":
    from app.gov.catalog import load_index

    count = build_title_vectors(load_index(), VECTOR_PATH)
    print(f"Saved {count} title embeddings to {VECTOR_PATH}")
