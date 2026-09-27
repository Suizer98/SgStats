from __future__ import annotations

import httpx
import pandas as pd

from app import mcp
from app.core import settings
from app.gov import catalog, data, sources

DATAGOV_URL = "https://data.gov.sg/api/action/datastore_search"
DATAGOV_META_URL = "https://api-production.data.gov.sg/v2/public/api/datasets/{}/metadata"
SINGSTAT_URL = "https://tablebuilder.singstat.gov.sg/api/table/tabledata"
HEADERS = {"User-Agent": "SgStats/0.1", "Accept": "application/json"}
ROW_LIMIT = 10000


def get_datagov(dataset_id: str) -> dict:
    with httpx.Client(timeout=settings.FETCH_TIMEOUT, headers=HEADERS) as client:
        response = client.get(DATAGOV_URL, params={"resource_id": dataset_id, "limit": ROW_LIMIT})
        response.raise_for_status()
        result = response.json().get("result") or {}
    records = result.get("records") or []
    if not records:
        raise ValueError("data.gov.sg returned no records")
    return {"records": records, "total": int(result.get("total") or len(records))}


def get_datagov_meta(dataset_id: str) -> dict:
    try:
        with httpx.Client(timeout=settings.FETCH_TIMEOUT, headers=HEADERS) as client:
            response = client.get(DATAGOV_META_URL.format(dataset_id))
            response.raise_for_status()
            meta = response.json().get("data") or {}
    except Exception:
        return {}
    mapping = (meta.get("columnMetadata") or {}).get("metaMapping") or {}
    titles = {item["name"]: item.get("columnTitle") or item["name"] for item in mapping.values() if item.get("name")}
    return {"title": meta.get("name"), "agency": meta.get("managedBy"), "titles": titles}


def get_singstat(table_id: str) -> dict:
    with httpx.Client(timeout=settings.FETCH_TIMEOUT, headers=HEADERS) as client:
        response = client.get(f"{SINGSTAT_URL}/{table_id}")
        response.raise_for_status()
        table = response.json().get("Data") or {}
    if not table.get("row"):
        raise ValueError("SingStat returned no rows")
    return table


def agency_name(text: str | None, default: str) -> str:
    name = (text or "").strip() or default
    if name.isupper():
        name = name.title().replace(" Of ", " of ").replace(" And ", " and ")
    return name


def package(
    meta: dict,
    rows: list[dict],
    year_from: int,
    year_to: int,
    mode: str,
    note: str = "",
    source_records: int | None = None,
    fmt: str = "json",
) -> dict:
    kept, grain, range_note = data.finish_rows(rows, year_from, year_to)
    in_range = len(kept)
    frame = pd.DataFrame(kept)
    keys = ["period", "series", "measure"]
    if not frame.empty and frame.duplicated(keys).any():
        count = len(frame)
        frame = frame.groupby(keys, as_index=False, sort=False)["value"].mean().round(2)
        note = f"{note} Averaged {count:,} records into {len(frame):,} period rows.".strip()
        kept = frame.to_dict(orient="records")
    checked = data.quality_check(frame, ["period", "value"], source_records, len(rows), in_range)
    if not checked["ok"]:
        raise ValueError("no usable time series after normalising")
    return {
        **meta,
        "format": fmt,
        "mode": mode,
        "grain": grain,
        "note": " ".join(item for item in (note, range_note) if item),
        "quality": {k: v for k, v in checked.items() if k != "frame"},
        "records": kept,
    }


def fetch_live(provider: str, dataset_id: str, year_from: int, year_to: int, tokens: set[str], title: str) -> dict:
    fmt = "json"
    if provider == "datagov":
        payload = get_datagov(dataset_id)
        info = get_datagov_meta(dataset_id)
        records = payload["records"]
        rows = data.normalize_any(records, info.get("titles"), tokens)
        title = info.get("title") or title or dataset_id
        agency = agency_name(info.get("agency"), "Data.gov.sg")
        note = f"First {len(records):,} of {payload['total']:,} rows." if payload["total"] > len(records) else ""
        citation = f"{agency}, {title}. data.gov.sg dataset {dataset_id}."
    elif provider == "singstat":
        table = get_singstat(dataset_id)
        records = table["row"]
        rows = data.normalize_singstat(records)
        title = table.get("title") or title or dataset_id
        agency = agency_name(table.get("datasource"), "Singapore Department of Statistics")
        note = ""
        citation = f"{agency}, {title}. SingStat Table Builder {dataset_id}."
    elif provider == "internal":
        item = sources.get_internal(dataset_id)
        if not item:
            raise ValueError(f"Unknown internal dataset: {dataset_id}")
        records = data.read_excel(item["file"])
        rows = data.normalize_any(records, tokens=tokens)
        title = item["title"]
        agency = item["agency"]
        note = "Mock internal data for demonstration, not an official statistic."
        citation = f"{agency}, {title}. {item['file']}."
        fmt = "xlsx"
    else:
        raise ValueError(f"Unknown provider: {provider}")
    meta = {"provider": provider, "dataset_id": dataset_id, "title": title, "source": agency, "citation": citation}
    dataset = package(meta, rows, year_from, year_to, "live", note, len(records), fmt)
    catalog.remember(dataset)
    return dataset


def fetch_dataset(provider: str, dataset_id: str, year_from: int, year_to: int, query: str = "", title: str = "") -> dict:
    tokens = catalog.search_terms(query)["tokens"] if query else set()
    try:
        return fetch_live(provider, dataset_id, year_from, year_to, tokens, title)
    except Exception:
        dataset = snapshot_dataset(provider, dataset_id, year_from, year_to, tokens)
        if not dataset:
            raise
    catalog.remember(dataset)
    return dataset


def snapshot_dataset(provider: str, dataset_id: str, year_from: int, year_to: int, tokens: set[str]) -> dict | None:
    pinned = sources.get_pinned(provider, dataset_id)
    if not pinned:
        return None
    snap = data.load_snapshot(pinned["snapshot"], year_from, year_to, tokens)
    return {
        "provider": provider,
        "dataset_id": dataset_id,
        "title": pinned["title"],
        "source": pinned["agency"],
        "citation": f"{pinned['agency']}, {pinned['title']}. Snapshot retrieved {pinned['retrieved']}, used after live fetch failed.",
        "mode": "snapshot_fallback",
        **snap,
    }


def call_mcp(tool: str, arguments: dict) -> dict:
    return mcp.call_tool(tool, arguments)


def search(query: str, year_from: int, year_to: int, sector: str | None = None) -> list[dict]:
    if settings.MCP_URL:
        arguments = {"query": query, "year_from": year_from, "year_to": year_to, "sector": sector}
        return call_mcp("search_datasets", arguments)["candidates"]
    return catalog.search(query, year_from, year_to, sector)


def extract_one(provider: str, dataset_id: str, year_from: int, year_to: int, query: str = "", title: str = "") -> dict:
    if settings.MCP_URL:
        arguments = {
            "provider": provider,
            "dataset_id": dataset_id,
            "year_from": year_from,
            "year_to": year_to,
            "query": query,
            "title": title,
        }
        try:
            return call_mcp("fetch_dataset", arguments)
        except Exception:
            tokens = catalog.search_terms(query)["tokens"] if query else set()
            dataset = snapshot_dataset(provider, dataset_id, year_from, year_to, tokens)
            if not dataset:
                raise
            dataset["note"] = " ".join(filter(None, [dataset.get("note"), "Data service unreachable, bundled snapshot used."]))
            return dataset
    return fetch_dataset(provider, dataset_id, year_from, year_to, query, title)
