from __future__ import annotations

from pydantic import BaseModel, Field

from app.agents.types import Emit
from app.core import settings
from app.gov import catalog, data, fetch
from app.llm.client import LLMError, complete


CROSS_CHECK_DEPTH = 6
MAX_PLAN = 3
GOVERNMENT_PROVIDERS = {"datagov", "singstat"}


class DatasetPlan(BaseModel):
    datasets: list[str] = Field(default_factory=list, description="Candidate keys like datagov:d_xxx or singstat:M123")
    rationale: str = Field(default="", description="One sentence on why these datasets answer the question")


def choose_datasets(query: str, candidates: list[dict], year_from: int, year_to: int) -> tuple[list[str], str]:
    listing = "\n".join(
        f"- {item['provider']}:{item['id']} | {item['title']} | {item['agency']} | coverage {item['coverage'] or 'unknown'}"
        for item in candidates
    )
    answer = complete(
        system=(
            "Pick the government datasets that best answer the question. Choose 1 to 3 keys from the "
            "candidate list only. Prefer datasets that directly measure what is asked, cover the requested "
            "years, and are aggregate time series rather than transaction records. When both Data.gov.sg "
            "and SingStat offer a relevant series, include one from each so the findings can be cross-checked."
        ),
        human="Question: {query}\nRequested years: {year_from}-{year_to}\nCandidates:\n{listing}",
        schema=DatasetPlan,
        variables={"query": query, "year_from": year_from, "year_to": year_to, "listing": listing},
        timeout=settings.PLANNER_TIMEOUT,
    )
    allowed = {f"{item['provider']}:{item['id']}" for item in candidates}
    chosen = [key for key in dict.fromkeys(answer["body"].get("datasets") or []) if key in allowed]
    if not chosen:
        raise LLMError("Dataset plan selected no valid candidates")
    return chosen[:MAX_PLAN], str(answer["body"].get("rationale") or "")


def cross_check(chosen: list[str], by_key: dict[str, dict]) -> str | None:
    """Add a well-ranked dataset from another provider when the plan relies on a single source."""
    providers = {by_key[key]["provider"] for key in chosen}
    if len(providers) > 1 or len(chosen) >= MAX_PLAN:
        return None
    others = [key for key in list(by_key)[:CROSS_CHECK_DEPTH] if by_key[key]["provider"] not in providers]
    official = [key for key in others if by_key[key]["provider"] in GOVERNMENT_PROVIDERS]
    return (official or others or [None])[0]


def plan(query: str, emit: Emit) -> tuple[dict, dict, list[str], dict[str, dict]]:
    scope = data.parse_query(query)
    terms = catalog.search_terms(query, scope["sector"])
    scope["notes"] = []
    if not terms["phrases"]:
        scope["notes"].append(
            "No specific topic was recognised in the question, so the default labour market and GDP datasets are shown."
        )
        emit("coordinator", "observation", "The question names no measurable topic. Treating it as ambiguous.")
    emit(
        "coordinator",
        "thought",
        f"Scope {scope['year_from']}-{scope['year_to']}. Search Data.gov.sg and SingStat for: "
        f"{', '.join(terms['phrases'][:5]) or 'no keywords found'}.",
    )
    search_failed = False
    try:
        candidates = fetch.search(query, scope["year_from"], scope["year_to"], scope["sector"])
    except Exception as error:
        candidates = []
        search_failed = True
        emit("coordinator", "observation", f"Catalog search failed ({error.__class__.__name__}).")
    if candidates:
        top = "; ".join(f"{item['title']} ({item['provider']})" for item in candidates[:4])
        emit("coordinator", "observation", f"{len(candidates)} candidate datasets. Top matches: {top}.")
    else:
        candidates = catalog.pinned_candidates()
        emit("coordinator", "observation", "No catalog matches. Falling back to the pinned labour and GDP datasets.")
        if search_failed:
            scope["notes"].append(
                "Dataset search was unavailable, so the default labour market and GDP datasets are shown."
            )
        elif terms["phrases"]:
            scope["notes"].append(
                "No dataset matched the question, so the default labour market and GDP datasets are shown. "
                "Try naming a topic such as employment, wages, CPI or housing."
            )

    by_key = {f"{item['provider']}:{item['id']}": item for item in candidates}
    try:
        chosen, rationale = choose_datasets(query, candidates, scope["year_from"], scope["year_to"])
        mode = "LLM-selected"
    except Exception as error:
        chosen = list(by_key)[:2]
        rationale = ""
        mode = "Top-ranked"
        emit("coordinator", "observation", f"Planner unavailable ({error.__class__.__name__}). Using search ranking.")
    if rationale:
        emit("coordinator", "thought", rationale)
    extra = cross_check(chosen, by_key)
    if extra:
        chosen.append(extra)
        emit(
            "coordinator",
            "thought",
            f"Plan uses one provider only. Adding {by_key[extra]['title']} ({by_key[extra]['provider']}) as a cross-check.",
        )
    emit("coordinator", "action", f"{mode} plan: " + "; ".join(by_key[key]["title"] for key in chosen) + ".")
    return scope, terms, chosen, by_key
