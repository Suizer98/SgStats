from __future__ import annotations

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel

from app.gov import catalog, fetch

TOOLS = [
    {
        "name": "search_datasets",
        "description": "Search Data.gov.sg, SingStat Table Builder and the mock internal database for datasets matching a policy question.",
        "input": {
            "query": "string",
            "year_from": "int",
            "year_to": "int",
            "sector": "string | null",
            "phrases": "string[] | null",
        },
    },
    {
        "name": "fetch_dataset",
        "description": "Fetch one dataset live (JSON API, or Excel for the internal source) and normalise it to period, series, measure, value rows.",
        "input": {
            "provider": "datagov | singstat | internal",
            "dataset_id": "string",
            "year_from": "int",
            "year_to": "int",
            "query": "string",
        },
    },
]


class SearchArgs(BaseModel):
    query: str
    year_from: int = 2016
    year_to: int = 2026
    sector: str | None = None
    phrases: list[str] | None = None


class FetchArgs(BaseModel):
    provider: str
    dataset_id: str
    year_from: int = 2016
    year_to: int = 2026
    query: str = ""
    title: str = ""


def run_tool(name: str, arguments: dict) -> dict:
    if name == "search_datasets":
        args = SearchArgs(**arguments)
        return {
            "candidates": catalog.search(args.query, args.year_from, args.year_to, args.sector, args.phrases),
            "embed_note": catalog.embed_note,
        }
    if name == "fetch_dataset":
        args = FetchArgs(**arguments)
        try:
            result = fetch.fetch_dataset(args.provider, args.dataset_id, args.year_from, args.year_to, args.query, args.title)
        except Exception as error:
            raise HTTPException(502, f"{args.provider}:{args.dataset_id} failed: {error}") from error
        return jsonable_encoder(result)
    raise HTTPException(404, f"Unknown tool {name}")
