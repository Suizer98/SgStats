from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from app.core import store
from app.gov import catalog
from tools import TOOLS, run_tool

app = FastAPI(title="SgStats gov MCP")


class RpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: int | str = 1
    method: str
    params: dict | None = None


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
