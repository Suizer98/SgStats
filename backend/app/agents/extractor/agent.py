from __future__ import annotations

from app.agents.types import Emit
from app.constants import MAX_ATTEMPTS
from app.gov import fetch


def collect(
    query: str,
    scope: dict,
    chosen: list[str],
    by_key: dict[str, dict],
    emit: Emit,
    excluded: set[str] | None = None,
) -> tuple[list[dict], list[str]]:
    emit(
        "extractor",
        "thought",
        "Fetch each planned dataset live, normalise its periods and series, and fall back to the next candidate if a fetch fails.",
    )
    excluded = excluded or set()
    selected = [key for key in chosen if key not in excluded]
    backups = [key for key in by_key if key not in chosen and key not in excluded]
    datasets: list[dict] = []
    attempted: list[str] = []
    target = max(1, len(selected))
    for key in selected + backups:
        if len(datasets) >= target or len(attempted) >= MAX_ATTEMPTS:
            break
        attempted.append(key)
        item = by_key[key]
        emit("extractor", "action", f"Call MCP tool fetch_dataset for {key} ({item['title']}).")
        try:
            dataset = fetch.extract_one(
                item["provider"], item["id"], scope["year_from"], scope["year_to"], query, item["title"]
            )
        except Exception as error:
            emit("extractor", "observation", f"{key} failed ({error.__class__.__name__}). Trying the next candidate.")
            continue
        datasets.append(dataset)
        series = len({row["series"] for row in dataset["records"]})
        note = f" {dataset['note']}" if dataset.get("note") else ""
        emit(
            "extractor",
            "observation",
            f"{dataset['title']}: {dataset['mode']}, {len(dataset['records'])} rows by {dataset['grain']}, "
            f"{series} series, quality passed={dataset['quality']['ok']}.{note}",
        )
    return datasets, attempted
