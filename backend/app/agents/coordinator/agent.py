from __future__ import annotations

from pydantic import BaseModel, Field

from app.agents.types import Emit
from app.constants import MAX_PLAN
from app.core import settings
from app.gov import catalog, data, fetch
from app.llm.client import LLMError, complete


class DatasetPlan(BaseModel):
    datasets: list[str] = Field(
        default_factory=list,
        description="Keys from the candidate list that directly measure the question. Empty when none do.",
    )
    rationale: str = Field(default="", description="One sentence on why these datasets answer the question, or why none do")


def choose_datasets(query: str, candidates: list[dict], year_from: int, year_to: int) -> tuple[list[str], str]:
    listing = "\n".join(
        f"- {item['provider']}:{item['id']} | {item['title']} | {item['agency']} | coverage {item['coverage'] or 'unknown'}"
        for item in candidates
    )
    answer = complete(
        system=(
            "Choose government datasets that directly measure the question. Use only keys from the candidate "
            "list, at most 3. A table that breaks the requested group out, such as foreign workforce by pass "
            "type, is a match even when other groups are in the same table. A single combined total that never "
            "names the group is not. The word worker alone does not make a dataset relevant. Return no keys "
            "when every candidate is only related by a shared word. When two providers each have a series that "
            "directly measures the question, include one from each."
        ),
        human="Question: {query}\nRequested years: {year_from}-{year_to}\nCandidates:\n{listing}",
        schema=DatasetPlan,
        variables={"query": query, "year_from": year_from, "year_to": year_to, "listing": listing},
        timeout=settings.PLANNER_TIMEOUT,
    )
    requested = answer["body"].get("datasets") or []
    allowed = {f"{item['provider']}:{item['id']}" for item in candidates}
    chosen = [key for key in dict.fromkeys(requested) if key in allowed]
    if requested and not chosen:
        raise LLMError("Dataset plan selected no valid candidates")
    return chosen[:MAX_PLAN], str(answer["body"].get("rationale") or "")


def plan(query: str, emit: Emit) -> tuple[dict, dict, list[str], dict[str, dict]]:
    scope = data.parse_query(query)
    phrases = catalog.meaning_phrases(query)
    terms = catalog.search_terms(query, scope["sector"], phrases)
    scope["notes"] = []
    if phrases:
        emit("coordinator", "thought", "Reading the question as: " + ", ".join(phrases) + ".")
    elif settings.BIFROST_URL:
        emit(
            "coordinator",
            "observation",
            "The question was searched as typed. " + (catalog.meaning_note or "The rewrite returned no phrases."),
        )
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
        candidates = fetch.search(query, scope["year_from"], scope["year_to"], scope["sector"], phrases)
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
    if mode == "LLM-selected" and not chosen:
        scope["notes"].append("No candidate dataset directly measures this question, so nothing was charted.")
        emit("coordinator", "observation", scope["notes"][-1])
        emit("coordinator", "action", "No dataset selected.")
        return scope, terms, [], {}
    emit("coordinator", "action", f"{mode} plan: " + "; ".join(by_key[key]["title"] for key in chosen) + ".")
    return scope, terms, chosen, by_key
