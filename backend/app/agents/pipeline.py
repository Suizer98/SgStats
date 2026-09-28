from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.agents.analytics.agent import analyse, build_result, revise_report
from app.agents.coordinator.agent import plan
from app.agents.extractor.agent import collect
from app.agents.general.agent import classify, converse, datasets_for_edit, latest_data_turn, scope_for_edit
from app.gov import catalog
from app.agents.types import Emit
from app.llm.client import begin_providers, providers_used


class AgentState(TypedDict, total=False):
    query: str
    history: list[dict]
    intent: str
    emit: Emit
    scope: dict
    terms: dict
    chosen: list[str]
    by_key: dict[str, dict]
    datasets: list[dict]
    attempted: list[str]
    summary: dict
    report: dict
    result: dict


def classify_node(state: AgentState) -> dict:
    return {"intent": classify(state["query"], state.get("history") or [], state["emit"])}


def route_intent(state: AgentState) -> str:
    intent = state.get("intent")
    if intent in {"chat", "edit"}:
        return intent
    return "coordinate"


def edit_node(state: AgentState) -> dict:
    prior = latest_data_turn(state["history"]) or {}
    scope = scope_for_edit(state["query"], prior.get("scope") or {})
    datasets = datasets_for_edit(state["query"], prior.get("datasets") or [], scope)
    chosen = []
    by_key = {}
    for dataset in datasets:
        key = f"{dataset.get('provider')}:{dataset.get('dataset_id')}"
        chosen.append(key)
        by_key[key] = {
            "provider": dataset.get("provider"),
            "id": dataset.get("dataset_id"),
            "title": dataset.get("title") or dataset.get("source") or key,
            "agency": dataset.get("source") or "",
            "coverage": "",
            "score": 1,
        }
    state["emit"](
        "coordinator",
        "observation",
        f"Reused {len(datasets)} saved dataset(s) for {scope['year_from']}-{scope['year_to']}.",
    )
    return {
        "scope": scope,
        "terms": catalog.search_terms(state["query"], scope.get("sector")),
        "chosen": chosen,
        "by_key": by_key,
        "datasets": datasets,
        "attempted": chosen,
    }


def chat_node(state: AgentState) -> dict:
    return {"result": converse(state["query"], state.get("history") or [], state["emit"])}


def coordinate_node(state: AgentState) -> dict:
    scope, terms, chosen, by_key = plan(state["query"], state["emit"])
    return {"scope": scope, "terms": terms, "chosen": chosen, "by_key": by_key, "attempted": []}


def extract_node(state: AgentState) -> dict:
    datasets, attempted = collect(
        state["query"],
        state["scope"],
        state["chosen"],
        state["by_key"],
        state["emit"],
        set(state["attempted"]),
    )
    return {"datasets": datasets, "attempted": state["attempted"] + attempted}


def route_extraction(state: AgentState) -> str:
    if state["datasets"]:
        return "analyse"
    if any(key not in state["attempted"] for key in state["by_key"]):
        return "replan"
    return "fail"


def replan_node(state: AgentState) -> dict:
    remaining = [key for key in state["by_key"] if key not in state["attempted"]]
    chosen = remaining[:2]
    titles = "; ".join(state["by_key"][key]["title"] for key in chosen)
    state["emit"]("coordinator", "action", f"Extraction returned no usable data. Replan once with: {titles}.")
    return {"chosen": chosen}


def fail_node(state: AgentState) -> dict:
    raise RuntimeError("No candidate dataset could be fetched for this question.")


def analyse_node(state: AgentState) -> dict:
    summary, report = analyse(
        state["query"],
        state["scope"],
        state["terms"],
        state["datasets"],
        state["emit"],
    )
    return {"summary": summary, "report": report}


def route_grounding(state: AgentState) -> str:
    return "finalise" if state["report"]["grounding"]["passed"] else "revise"


def revise_node(state: AgentState) -> dict:
    report = revise_report(
        state["query"],
        state["scope"],
        state["summary"],
        state["datasets"],
        state["report"],
        state["emit"],
    )
    return {"report": report}


def finalise_node(state: AgentState) -> dict:
    result = build_result(
        state["query"],
        state["scope"],
        state["chosen"],
        state["by_key"],
        state["datasets"],
        state["summary"],
        state["report"],
    )
    return {"result": result}


def create_graph():
    workflow = StateGraph(AgentState)
    workflow.add_node("classify", classify_node)
    workflow.add_node("chat", chat_node)
    workflow.add_node("edit", edit_node)
    workflow.add_node("coordinate", coordinate_node)
    workflow.add_node("extract", extract_node)
    workflow.add_node("replan", replan_node)
    workflow.add_node("fail", fail_node)
    workflow.add_node("analyse", analyse_node)
    workflow.add_node("revise", revise_node)
    workflow.add_node("finalise", finalise_node)
    workflow.add_edge(START, "classify")
    workflow.add_conditional_edges(
        "classify",
        route_intent,
        {"chat": "chat", "edit": "edit", "coordinate": "coordinate"},
    )
    workflow.add_edge("chat", END)
    workflow.add_edge("edit", "analyse")
    workflow.add_edge("coordinate", "extract")
    workflow.add_conditional_edges(
        "extract",
        route_extraction,
        {"analyse": "analyse", "replan": "replan", "fail": "fail"},
    )
    workflow.add_edge("replan", "extract")
    workflow.add_conditional_edges(
        "analyse",
        route_grounding,
        {"revise": "revise", "finalise": "finalise"},
    )
    workflow.add_edge("revise", "finalise")
    workflow.add_edge("finalise", END)
    return workflow.compile()


agent_graph = create_graph()


def run(query: str, emit: Emit | None = None, history: list[dict] | None = None) -> dict:
    def emit_event(agent: str, kind: str, message: str) -> None:
        if emit is not None:
            emit(agent, kind, message)

    begin_providers()
    state = agent_graph.invoke({"query": query, "emit": emit_event, "history": history or []})
    result = state["result"]
    result.setdefault("report", {})["llm_providers"] = providers_used()
    return result
