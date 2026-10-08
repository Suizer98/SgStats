from __future__ import annotations

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from app.constants import (
    BATCH_SIZE,
    DATAGOV_LIST_URL,
    DEFAULT_COOLDOWN,
    DUPLICATE_OVERLAP,
    EMBED_RETRY,
    FREQUENCY_WORDS,
    GEMINI_EMBED_MODEL,
    HEADERS,
    INDEX_MAX_AGE,
    INTERNAL_MIN_SCORE,
    MAX_CANDIDATES,
    MEANING_PHRASES,
    MEANING_TIMEOUT,
    SINGSTAT_BONUS,
    SINGSTAT_PHRASES,
    SINGSTAT_SEARCH_URL,
    STOPWORDS,
    VECTOR_SLOTS,
)
from app.core import settings, store
from app.gov import data, embed, sources
from app.llm.client import complete_text

index_cache: list[dict] | None = None
refreshing = threading.Event()
embedding = threading.Event()
embed_paused_until = 0.0
meaning_note = ""
embed_note = ""


def phrase_list(text: str) -> list[str]:
    quoted = re.findall(r'"([^"]+)"', text)
    pieces = quoted or re.split(r"[\n,;]+", text)
    found: list[str] = []
    for piece in pieces:
        words = re.findall(r"[a-z][a-z0-9\-]*", piece.lower())
        cleaned = " ".join(word for word in words[:8] if word not in {"phrases", "phrase"})
        if cleaned and cleaned not in found:
            found.append(cleaned)
        if len(found) >= MEANING_PHRASES:
            break
    return found


def meaning_phrases(query: str) -> list[str]:
    """Ask the chat model what the question means, in words a statistics catalogue would use."""
    global meaning_note
    meaning_note = ""
    if not settings.BIFROST_URL or not query.strip():
        return []
    try:
        text = complete_text(
            system=(
                "Turn the question into search phrases for Singapore official statistics catalogues. "
                "Expand short forms into the names those catalogues use. "
                "Reply with 1 to 4 short phrases separated by commas, and nothing else."
            ),
            human="{query}",
            variables={"query": query},
            timeout=MEANING_TIMEOUT,
        )
    except Exception as error:
        meaning_note = f"The rewrite failed ({error.__class__.__name__})."
        return []
    found = phrase_list(text)
    if not found:
        meaning_note = "The rewrite reply had no search phrases."
    return found


def search_terms(query: str, sector: str | None = None, extra: list[str] | None = None) -> dict:
    """Phrases drive catalog search; tokens (which also include the sector) rank datasets and series."""
    words = re.findall(r"[a-z][a-z\-]*", query.lower())
    keywords = [word for word in words if word not in STOPWORDS and len(word) > 1]
    phrases: list[str] = []
    for phrase in extra or []:
        cleaned = " ".join(str(phrase).lower().split())
        if cleaned:
            phrases.append(cleaned)
    if len(keywords) > 1:
        phrases.append(" ".join(keywords[:3]))
    phrases.extend(keywords)
    phrases = list(dict.fromkeys(phrases))
    tokens: set[str] = set()
    for phrase in phrases:
        tokens |= data.tokenize(phrase)
    tokens -= {data.stem(word) for word in STOPWORDS}
    sector_tokens = data.tokenize(sector or "") - {"and"}
    return {"phrases": phrases, "tokens": tokens | sector_tokens}


def year_of(value: str | None) -> int | None:
    match = re.match(r"(\d{4})", value or "")
    return int(match[1]) if match else None


def score_title(title: str, terms: dict) -> float:
    lowered = title.lower()
    score = float(data.relevance(title, terms["tokens"]))
    score += sum(2.0 for phrase in terms["phrases"] if " " in phrase and phrase in lowered)
    if "footnote" in lowered:
        score -= 3.0
    return score


def fit_bonus(item: dict, year_from: int, year_to: int) -> float:
    bonus = 0.0
    start, end = item.get("coverage_start"), item.get("coverage_end")
    if end and end < year_from:
        bonus -= 1.5
    elif start and start > year_to:
        bonus -= 1.5
    elif end and end >= year_to - 1:
        bonus += 0.5
    if year_to - year_from >= 3 and "annual" in item["title"].lower():
        bonus += 0.3
    return bonus


def candidate(provider: str, item: dict, score: float) -> dict:
    start, end = item.get("coverage_start"), item.get("coverage_end")
    return {
        "provider": provider,
        "id": item["id"],
        "title": item["title"],
        "agency": item.get("agency", ""),
        "coverage": f"{start}-{end}" if start and end else "",
        "score": round(score, 2),
    }


def crawl_datagov() -> list[dict]:
    items = []
    page = 1
    retries = 0
    with httpx.Client(timeout=20, headers=HEADERS) as client:
        while True:
            response = client.get(DATAGOV_LIST_URL, params={"page": page})
            if response.status_code == 429 and retries < 5:
                retries += 1
                time.sleep(5 * retries)
                continue
            response.raise_for_status()
            retries = 0
            datasets = response.json().get("data", {}).get("datasets") or []
            if not datasets:
                break
            for entry in datasets:
                if entry.get("format") != "CSV" or entry.get("status") != "active":
                    continue
                items.append(
                    {
                        "id": entry["datasetId"],
                        "title": entry.get("name", ""),
                        "agency": entry.get("managedByAgencyName", ""),
                        "coverage_start": year_of(entry.get("coverageStart")),
                        "coverage_end": year_of(entry.get("coverageEnd")),
                    }
                )
            page += 1
    return items


def refresh_index() -> int:
    global index_cache
    items = crawl_datagov()
    if items:
        store.save_datagov_catalog(items)
        index_cache = items
    return len(items)


def index_is_stale() -> bool:
    age = store.catalog_age_seconds()
    return age is None or age > INDEX_MAX_AGE


def refresh_in_background(embed_catalog: bool = False) -> None:
    if refreshing.is_set():
        return
    refreshing.set()

    def work() -> None:
        try:
            refresh_index()
        except Exception:
            pass
        finally:
            refreshing.clear()
        if embed_catalog:
            embed_missing_in_background()

    threading.Thread(target=work, daemon=True).start()


def load_index() -> list[dict]:
    global index_cache
    if index_cache is None:
        index_cache = store.list_datagov()
    return index_cache or []


def embed_allowed() -> bool:
    return bool(settings.BIFROST_URL) and store.postgres_enabled() and not settings.MCP_URL


def warm() -> None:
    if index_is_stale():
        refresh_in_background(embed_allowed())
        return
    if embed_allowed():
        embed_missing_in_background()


def embed_missing_in_background() -> None:
    if embedding.is_set() or time.time() < embed_paused_until or not embed_allowed():
        return
    embedding.set()

    def work() -> None:
        global embed_paused_until
        try:
            embed_missing()
            if not vectors_ready():
                embed_paused_until = time.time() + DEFAULT_COOLDOWN
        except Exception:
            embed_paused_until = time.time() + DEFAULT_COOLDOWN
        finally:
            embedding.clear()

    threading.Thread(target=work, daemon=True).start()


def embed_missing() -> int:
    """Fill catalogue rows that have no vector yet. Stops if the model changes mid-run."""
    if not settings.BIFROST_URL or not store.postgres_enabled():
        return 0
    saved = 0
    model = store.datagov_embedding_model() or GEMINI_EMBED_MODEL
    while True:
        rows = store.datagov_without_embedding(BATCH_SIZE)
        if not rows:
            break
        texts = [embed.document_text(row["title"], row.get("agency") or "", model) for row in rows]
        try:
            matrix, used = embed.embed_texts(texts, model, patient=True)
        except Exception:
            break
        if saved and used != model:
            break
        model = used
        store.upsert_datasets(
            [
                {
                    "provider": "datagov",
                    "dataset_id": row["id"],
                    "title": row["title"],
                    "agency": row.get("agency") or "",
                    "detail": row.get("agency") or "",
                    "embedding": vector.tolist(),
                    "embedding_model": used,
                }
                for row, vector in zip(rows, matrix)
            ]
        )
        saved += len(rows)
        print(f"embedded {saved} catalogue titles via {used}", flush=True)
    return saved


def search_datagov(terms: dict, year_from: int, year_to: int) -> list[dict]:
    found = []
    for item in load_index():
        score = score_title(item["title"], terms)
        if score >= 1:
            found.append(candidate("datagov", item, score + fit_bonus(item, year_from, year_to)))
    return found


def singstat_records(phrase: str) -> list[dict]:
    try:
        with httpx.Client(timeout=settings.FETCH_TIMEOUT, headers=HEADERS) as client:
            response = client.get(SINGSTAT_SEARCH_URL, params={"keyword": phrase, "searchOption": "all"})
            response.raise_for_status()
            return response.json().get("Data", {}).get("records") or []
    except Exception:
        return []


def search_singstat(terms: dict, year_from: int, year_to: int) -> list[dict]:
    phrases = terms["phrases"][:SINGSTAT_PHRASES]
    with ThreadPoolExecutor(max_workers=max(len(phrases), 1)) as pool:
        batches = list(pool.map(singstat_records, phrases))
    seen: dict[str, dict] = {}
    for records in batches:
        for record in records:
            item = {"id": record["id"], "title": record.get("title", ""), "agency": "Singapore Department of Statistics"}
            score = score_title(item["title"], terms)
            if score >= 1 and item["id"] not in seen:
                total = score + fit_bonus(item, year_from, year_to) + SINGSTAT_BONUS
                seen[item["id"]] = candidate("singstat", item, total)
    return list(seen.values())


def search_internal(terms: dict, year_from: int, year_to: int) -> list[dict]:
    found = []
    for item in sources.INTERNAL:
        score = score_title(f"{item['title']} {item['keywords']}", terms)
        if score >= INTERNAL_MIN_SCORE:
            found.append(candidate("internal", item, score + fit_bonus(item, year_from, year_to)))
    return found


def is_duplicate(title: str, kept: list[dict]) -> bool:
    """Data.gov.sg mirrors many SingStat tables, and SingStat splits one table by frequency."""
    words = data.tokenize(title) - FREQUENCY_WORDS
    for item in kept:
        other = data.tokenize(item["title"]) - FREQUENCY_WORDS
        smaller = min(len(words), len(other))
        if smaller >= 3 and len(words & other) / smaller >= DUPLICATE_OVERLAP:
            return True
    return False


def dataset_detail(dataset: dict) -> str:
    records = dataset.get("records") or []
    series = list(dict.fromkeys(str(row.get("series")) for row in records if row.get("series")))[:12]
    measures = list(dict.fromkeys(str(row.get("measure")) for row in records if row.get("measure")))[:6]
    parts = [dataset.get("source") or ""]
    if dataset.get("grain"):
        parts.append(str(dataset["grain"]))
    if series:
        parts.append("series: " + ", ".join(series))
    if measures:
        parts.append("measures: " + ", ".join(measures))
    return " | ".join(part for part in parts if part)


def remember(dataset: dict) -> None:
    """Store one fetched dataset, including its series and measure labels, for the next search."""
    if not settings.BIFROST_URL or not store.postgres_enabled():
        return
    current = store.datagov_embedding_model()
    model = current or GEMINI_EMBED_MODEL
    try:
        detail = dataset_detail(dataset)
        matrix, used = embed.embed_texts(
            [embed.document_text(dataset.get("title") or "", detail, model)],
            model,
        )
        if current and used != current:
            return
        store.upsert_datasets(
            [
                {
                    "provider": dataset["provider"],
                    "dataset_id": dataset["dataset_id"],
                    "title": dataset.get("title") or "",
                    "agency": dataset.get("source") or "",
                    "detail": detail,
                    "embedding": matrix[0].tolist(),
                    "embedding_model": used,
                }
            ]
        )
    except Exception:
        return


def vectors_ready() -> bool:
    if not settings.BIFROST_URL or not store.postgres_enabled():
        return False
    total, ready = store.datagov_counts()
    return total > 0 and ready == total and store.datagov_embedding_model() is not None


def covers(item: dict, year_from: int, year_to: int) -> bool:
    start, end = item.get("coverage_start"), item.get("coverage_end")
    if end and end < year_from:
        return False
    if start and start > year_to:
        return False
    return True


def search_text(query: str, terms: dict) -> str:
    named = [phrase for phrase in terms["phrases"] if " " in phrase]
    if named:
        return " ".join(named[:MEANING_PHRASES])
    return query


def search_stored(query: str, year_from: int, year_to: int, terms: dict | None = None) -> list[dict] | None:
    model = store.datagov_embedding_model()
    if not model:
        return None
    text = search_text(query, terms) if terms else query
    matrix, used = embed.embed_texts([embed.query_text(text, model)], model)
    if used != model:
        return None
    rows = store.rank_datasets(matrix[0].tolist(), VECTOR_SLOTS, model)
    found = []
    for row in rows:
        if not covers(row, year_from, year_to):
            continue
        found.append(candidate(row["provider"], row, row["score"]))
    return found or None


def keep_ranked(found: list[dict]) -> list[dict]:
    kept: list[dict] = []
    for item in found:
        if not is_duplicate(item["title"], kept):
            kept.append(item)
        if len(kept) >= MAX_CANDIDATES:
            break
    return kept


def clear_embed_note() -> None:
    global embed_note
    embed_note = ""


def record_embed_failure(failed: bool) -> None:
    global embed_note
    paused = time.time() < embed_paused_until or time.time() < embed.blocked_until
    if not failed and not paused:
        embed_note = ""
        return
    detail = embed.limit_message.strip()
    embed_note = f"{EMBED_RETRY} Rate limit: {detail}" if detail else EMBED_RETRY


def search(
    query: str,
    year_from: int,
    year_to: int,
    sector: str | None = None,
    phrases: list[str] | None = None,
) -> list[dict]:
    if phrases is None:
        phrases = meaning_phrases(query)
    terms = search_terms(query, sector, phrases)
    if index_is_stale():
        refresh_in_background(embed_allowed())
    if not terms["phrases"]:
        record_embed_failure(False)
        return []
    others = search_singstat(terms, year_from, year_to) + search_internal(terms, year_from, year_to)
    ready = False
    try:
        ready = vectors_ready()
    except Exception:
        ready = False
    if not ready and embed_allowed():
        embed_missing_in_background()
    stored_failed = False
    if ready:
        try:
            stored = search_stored(query, year_from, year_to, terms)
        except Exception:
            stored = None
            stored_failed = True
        if stored:
            clear_embed_note()
            return keep_ranked(stored + sorted(others, key=lambda entry: -entry["score"]))
    record_embed_failure(stored_failed)
    found = search_datagov(terms, year_from, year_to) + others
    return keep_ranked(sorted(found, key=lambda entry: -entry["score"]))


def pinned_candidates() -> list[dict]:
    return [candidate(item["provider"], item, 0.0) for item in sources.PINNED]


if __name__ == "__main__":
    print(f"Indexed {refresh_index()} Data.gov.sg CSV datasets")
