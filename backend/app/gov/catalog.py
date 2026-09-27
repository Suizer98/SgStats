from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import numpy as np

from app.core import settings, store
from app.gov import data, embed, sources

DATAGOV_LIST_URL = "https://api-production.data.gov.sg/v2/public/api/datasets"
SINGSTAT_SEARCH_URL = "https://tablebuilder.singstat.gov.sg/api/table/resourceid"
HEADERS = {"User-Agent": "SgStats/0.1", "Accept": "application/json"}
INDEX_PATH = settings.DATA_DIR / "datagov_index.json"
VECTOR_PATH = settings.DATA_DIR / "datagov_vectors.npz"
EMBED_MARGIN = 0.08
INDEX_MAX_AGE = 7 * 24 * 3600
MAX_CANDIDATES = 12
SINGSTAT_PHRASES = 3

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "between", "by", "compare", "current", "data", "did", "do",
    "does", "for", "from", "how", "in", "is", "latest", "many", "much", "now", "of", "on", "over",
    "present", "show", "since", "singapore", "sg", "the", "to", "total", "trend", "trends", "was",
    "were", "what", "which", "who", "with", "year", "years", "analyse", "analyze", "tell", "me",
    "give", "change", "changes", "during", "past", "last", "number", "numbers", "stats",
    "statistics", "today", "until", "vs", "versus", "perform", "performance", "say", "about",
    "has", "have", "had", "been", "changed", "changing", "grown", "grow", "looks", "like", "can",
    "could", "would", "should", "please", "overall", "recent", "recently", "compared",
}
SINGSTAT_BONUS = 0.6
INTERNAL_MIN_SCORE = 2
DUPLICATE_OVERLAP = 0.9
FREQUENCY_WORDS = {"annual", "half", "yearly", "quarterly", "monthly", "weekly", "daily", "seasonally", "adjusted"}
SYNONYMS = {
    "ep": ["employment pass", "foreign workforce"],
    "eps": ["employment pass", "foreign workforce"],
    "spass": ["s pass", "foreign workforce"],
    "wp": ["work permit", "foreign workforce"],
    "foreigners": ["foreign workforce", "non-resident population"],
    "cpi": ["consumer price index"],
    "inflation": ["consumer price index"],
    "gdp": ["gross domestic product"],
    "coe": ["certificate of entitlement"],
    "pr": ["permanent resident"],
    "prs": ["permanent resident"],
    "fertility": ["births and fertility"],
    "tfr": ["fertility rate"],
    "jobless": ["unemployment"],
}

index_cache: list[dict] | None = None
vector_cache: tuple[list[str], np.ndarray] | None = None
refreshing = threading.Event()


def search_terms(query: str, sector: str | None = None) -> dict:
    """Phrases drive catalog search; tokens (which also include the sector) rank datasets and series."""
    words = re.findall(r"[a-z][a-z\-]*", query.lower())
    keywords = [word for word in words if word not in STOPWORDS and len(word) > 1]
    phrases: list[str] = []
    for word in keywords:
        phrases.extend(SYNONYMS.get(word, []))
    content = [word for word in keywords if word not in SYNONYMS]
    if len(content) > 1:
        phrases.append(" ".join(content[:3]))
    phrases.extend(content)
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
        temp = INDEX_PATH.with_suffix(".tmp")
        temp.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
        temp.replace(INDEX_PATH)
        index_cache = items
    return len(items)


def index_is_stale() -> bool:
    return not INDEX_PATH.exists() or time.time() - INDEX_PATH.stat().st_mtime > INDEX_MAX_AGE


def refresh_in_background() -> None:
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

    threading.Thread(target=work, daemon=True).start()


def load_index() -> list[dict]:
    global index_cache
    if index_cache is None and INDEX_PATH.exists():
        index_cache = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    return index_cache or []


def load_vectors() -> tuple[list[str], np.ndarray, str] | None:
    global vector_cache
    if vector_cache is None and VECTOR_PATH.exists():
        saved = np.load(VECTOR_PATH, allow_pickle=False)
        provider = str(saved["provider"]) if "provider" in saved else embed.GEMINI_PROVIDER
        vector_cache = ([str(item) for item in saved["ids"]], saved["vectors"], provider)
    return vector_cache


def search_datagov_embedded(query: str, year_from: int, year_to: int) -> list[dict] | None:
    """Rank the cached Data.gov.sg titles with the same embedding model that built them."""
    loaded = load_vectors()
    index = load_index()
    if loaded is None or not index:
        return None
    ids, matrix, provider = loaded
    if ids != [item["id"] for item in index]:
        return None
    query_vector = embed.embed_texts([embed.query_text(query, provider)], provider)[0]
    scores = matrix @ query_vector
    best = float(scores.max())
    found = []
    for rank in np.argsort(-scores):
        score = float(scores[rank])
        if best - score > EMBED_MARGIN:
            break
        item = index[int(rank)]
        found.append(candidate("datagov", item, round(score + fit_bonus(item, year_from, year_to), 3)))
        if len(found) >= MAX_CANDIDATES * 2:
            break
    return found


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
    if not settings.GEMINI_API_KEY or not store.postgres_enabled():
        return
    try:
        detail = dataset_detail(dataset)
        vector = embed.embed_texts([embed.document_text(dataset.get("title") or "", detail)])[0]
        store.upsert_datasets(
            [
                {
                    "provider": dataset["provider"],
                    "dataset_id": dataset["dataset_id"],
                    "title": dataset.get("title") or "",
                    "agency": dataset.get("source") or "",
                    "detail": detail,
                    "embedding": vector.tolist(),
                }
            ]
        )
    except Exception:
        return


def sync_saved_vectors() -> int:
    """Copy an existing title-vector file into Postgres once. Later fetches replace those rows."""
    if not store.postgres_enabled() or store.embedded_dataset_count():
        return 0
    loaded = load_vectors()
    indexed = {item["id"]: item for item in load_index()}
    if loaded is None or not indexed:
        return 0
    ids, matrix, provider = loaded
    del provider
    rows = []
    for position, dataset_id in enumerate(ids):
        item = indexed.get(dataset_id)
        if item is None:
            continue
        rows.append(
            {
                "provider": "datagov",
                "dataset_id": dataset_id,
                "title": item["title"],
                "agency": item.get("agency", ""),
                "coverage_start": item.get("coverage_start"),
                "coverage_end": item.get("coverage_end"),
                "detail": item.get("agency", ""),
                "embedding": matrix[position].astype(float).tolist(),
            }
        )
    return store.upsert_datasets(rows)


def search_stored(query: str, year_from: int, year_to: int) -> list[dict] | None:
    if not store.postgres_enabled() or store.embedded_dataset_count() == 0:
        return None
    vector = embed.embed_texts([embed.query_text(query)])[0]
    rows = store.rank_datasets(vector.tolist(), MAX_CANDIDATES * 2)
    if not rows:
        return None
    best = rows[0]["score"]
    found = []
    for row in rows:
        if best - row["score"] > EMBED_MARGIN:
            break
        found.append(candidate(row["provider"], row, row["score"] + fit_bonus(row, year_from, year_to)))
    return found or None


def keep_ranked(found: list[dict]) -> list[dict]:
    kept: list[dict] = []
    for item in found:
        if not is_duplicate(item["title"], kept):
            kept.append(item)
        if len(kept) >= MAX_CANDIDATES:
            break
    return kept


def search(query: str, year_from: int, year_to: int, sector: str | None = None) -> list[dict]:
    terms = search_terms(query, sector)
    if index_is_stale():
        refresh_in_background()
    stored = None
    try:
        stored = search_stored(query, year_from, year_to)
    except Exception:
        stored = None
    if stored:
        seen = {item["id"] for item in stored}
        rest = [item for item in search_datagov(terms, year_from, year_to) if item["id"] not in seen]
        sing_terms = {**terms, "phrases": [stored[0]["title"], *terms["phrases"]]}
        internal = [item for item in search_internal(terms, year_from, year_to) if item["id"] not in seen]
        return keep_ranked(stored + internal + rest + search_singstat(sing_terms, year_from, year_to))
    embedded = None
    try:
        embedded = search_datagov_embedded(query, year_from, year_to)
    except Exception:
        embedded = None
    if embedded is None and not terms["phrases"]:
        return []
    datagov = embedded if embedded is not None else search_datagov(terms, year_from, year_to)
    sing_terms = terms
    if embedded:
        sing_terms = {**terms, "phrases": [embedded[0]["title"], *terms["phrases"]]}
    found = datagov + search_singstat(sing_terms, year_from, year_to) + search_internal(terms, year_from, year_to)
    return keep_ranked(sorted(found, key=lambda entry: -entry["score"]))


def pinned_candidates() -> list[dict]:
    return [candidate(item["provider"], item, 0.0) for item in sources.PINNED]


if __name__ == "__main__":
    print(f"Indexed {refresh_index()} Data.gov.sg CSV datasets into {INDEX_PATH}")
