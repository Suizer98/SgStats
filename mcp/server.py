from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel

from app.core import store
from app.gov import catalog, fetch

app = FastAPI(title="SgStats gov MCP")

TOOLS = [
    {
        "name": "search_datasets",
        "description": "Search Data.gov.sg, SingStat Table Builder and the mock internal database for datasets matching a policy question.",
        "input": {"query": "string", "year_from": "int", "year_to": "int", "sector": "string | null"},
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


class FetchArgs(BaseModel):
    provider: str
    dataset_id: str
    year_from: int = 2016
    year_to: int = 2026
    query: str = ""
    title: str = ""


class RpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: int | str = 1
    method: str
    params: dict | None = None


def run_tool(name: str, arguments: dict) -> dict:
    if name == "search_datasets":
        args = SearchArgs(**arguments)
        return {"candidates": catalog.search(args.query, args.year_from, args.year_to, args.sector)}
    if name == "fetch_dataset":
        args = FetchArgs(**arguments)
        try:
            result = fetch.fetch_dataset(args.provider, args.dataset_id, args.year_from, args.year_to, args.query, args.title)
        except Exception as error:
            raise HTTPException(502, f"{args.provider}:{args.dataset_id} failed: {error}") from error
        return jsonable_encoder(result)
    raise HTTPException(404, f"Unknown tool {name}")


@app.on_event("startup")
def warm_index() -> None:
    store.init_db()
    catalog.sync_saved_vectors()
    if catalog.index_is_stale():
        catalog.refresh_in_background()


@app.get("/health")
def health():
    return {"ok": True, "service": "gov-mcp", "datagov_datasets": len(catalog.load_index())}


@app.get("/mcp/tools")
def list_tools():
    return {"tools": TOOLS}


@app.post("/mcp/tools/{name}")
def call_tool(name: str, arguments: dict):
    return run_tool(name, arguments)


@app.get("/datasets/search")
def dataset_search(
    q: str = Query(...),
    year_from: int = Query(default=2016),
    year_to: int = Query(default=2026),
):
    return run_tool("search_datasets", {"query": q, "year_from": year_from, "year_to": year_to})


@app.post("/mcp")
def mcp_rpc(body: RpcRequest):
    if body.method == "tools/list":
        return {"jsonrpc": "2.0", "id": body.id, "result": {"tools": TOOLS}}
    if body.method == "tools/call":
        params = body.params or {}
        try:
            result = run_tool(params.get("name", ""), params.get("arguments") or {})
        except HTTPException as error:
            return {"jsonrpc": "2.0", "id": body.id, "error": {"code": -32000, "message": error.detail}}
        return {"jsonrpc": "2.0", "id": body.id, "result": result}
    return {"jsonrpc": "2.0", "id": body.id, "error": {"code": -32601, "message": body.method}}
