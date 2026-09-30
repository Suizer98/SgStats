from __future__ import annotations

import re

from pydantic import BaseModel, Field

from app.agents.types import Emit
from app.constants import DATA_CUES, EDIT_CUES, SYNONYMS
from app.core import settings, store
from app.gov import data
from app.llm.client import complete


class ChatReply(BaseModel):
    message: str = Field(description="A direct conversational reply, with no invented statistics")


class Intent(BaseModel):
    kind: str = Field(description="data to fetch and analyse new statistics, or chat for everything else")
    reason: str = Field(default="", description="One short sentence explaining the choice")


def looks_like_data(query: str) -> bool:
    if DATA_CUES.search(query):
        return True
    words = re.findall(r"[a-z][a-z\-]*", query.lower())
    return any(word in SYNONYMS for word in words)


def thread_outline(history: list[dict]) -> str:
    lines = []
    for turn in history[-4:]:
        label = "analysis" if turn.get("kind") == "data" else "chat"
        lines.append(f"- ({label}) {turn['user']}")
    latest = latest_data_turn(history)
    if latest and latest.get("metrics"):
        lines.append("Latest analysis already shows:")
        lines.extend(f"  - {line}" for line in latest["metrics"])
    return "\n".join(lines) or "none"


def named_years(query: str) -> list[int]:
    return sorted({int(item) for item in re.findall(r"\b(?:19|20)\d{2}\b", query)})


def wants_edit(query: str) -> bool:
    return bool(named_years(query) or EDIT_CUES.search(query) or looks_like_data(query))


def scope_for_edit(query: str, prior: dict) -> dict:
    parsed = data.parse_query(query)
    years = named_years(query)
    return {
        "year_from": parsed["year_from"] if years else prior.get("year_from", parsed["year_from"]),
        "year_to": parsed["year_to"] if years else prior.get("year_to", parsed["year_to"]),
        "sector": parsed.get("sector") or prior.get("sector"),
        "notes": ["This updates the previous analysis in this thread. The same datasets were reused."],
    }


def datasets_for_edit(query: str, datasets: list[dict], scope: dict) -> list[dict]:
    if not named_years(query):
        return datasets
    year_from, year_to = scope["year_from"], scope["year_to"]
    edited = []
    for dataset in datasets:
        kept = []
        for row in dataset.get("records") or []:
            period = str(row.get("period") or "")
            if len(period) >= 4 and period[:4].isdigit() and year_from <= int(period[:4]) <= year_to:
                kept.append(row)
        if kept:
            edited.append({**dataset, "records": kept})
            continue
        title = dataset.get("title") or "A dataset"
        scope["notes"].append(f"{title} has no rows for {year_from}-{year_to}, so the saved rows were kept.")
        edited.append(dataset)
    return edited


def classify(query: str, history: list[dict], emit: Emit) -> str:
    prior = latest_data_turn(history)
    if prior and prior.get("datasets") and wants_edit(query):
        emit("coordinator", "thought", "This thread already has an analysis. Edit that result instead of fetching again.")
        emit("coordinator", "action", "Reuse the saved datasets and apply the requested change.")
        return "edit"
    if prior:
        emit("coordinator", "thought", "This thread already has an analysis. Answer from that result only.")
        emit("coordinator", "action", "Hand off the follow-up to the general agent.")
        return "chat"

    kind = "data" if looks_like_data(query) else "chat"
    reason = ""
    try:
        answer = complete(
            system=(
                "You route messages in a Singapore public-statistics workspace. "
                "Reply with kind data only when answering needs new government data fetched and analysed. "
                "Reply with kind chat for conversation, questions about this app, and follow-ups that the "
                "latest analysis can already answer, such as summarising it, explaining it, or comparing its figures."
            ),
            human="Earlier turns in this thread:\n{outline}\n\nNew message: {query}",
            schema=Intent,
            variables={"query": query, "outline": thread_outline(history)},
            timeout=12,
            models=settings.fast_chat_model_ids(),
        )
        parsed = str(answer["body"].get("kind") or "").lower()
        if parsed in {"data", "chat"}:
            kind = parsed
            reason = str(answer["body"].get("reason") or "")
    except Exception:
        pass
    if kind == "chat":
        emit("coordinator", "thought", reason or "This does not need new statistics fetched.")
        emit("coordinator", "action", "Hand off to the general agent.")
    else:
        emit("coordinator", "thought", reason or "This asks for statistics, so the data agents should handle it.")
    return kind


def conversation_history(analysis_id: str) -> list[dict]:
    row = store.get_analysis(analysis_id)
    if not row or not row.get("conversation_id"):
        return []
    conversation = store.get_conversation(row["conversation_id"])
    if not conversation:
        return []
    turns = []
    for item in conversation["analyses"]:
        if item["id"] == analysis_id or item["status"] != "done":
            continue
        result = item.get("result") or {}
        report = result.get("report") or {}
        reply = (report.get("briefing") or "").strip()
        if not reply:
            continue
        summary = result.get("summary") or {}
        metrics = [
            f"{metric.get('label')}: {metric.get('value')} {metric.get('unit')} ({metric.get('detail')})"
            for metric in (summary.get("metrics") or [])[:6]
        ]
        charts = [chart.get("title") for chart in (summary.get("charts") or [])[:4] if chart.get("title")]
        turns.append(
            {
                "user": item["query"],
                "assistant": reply[:800],
                "kind": "chat" if result.get("kind") == "chat" else "data",
                "metrics": metrics,
                "charts": charts,
                "insights": [str(line) for line in (report.get("insights") or [])[:4]],
                "datasets": result.get("datasets") or [],
                "scope": result.get("scope") or {},
                "plan": result.get("plan") or [],
            }
        )
    kept = turns[-6:]
    latest = latest_data_turn(kept)
    for turn in kept:
        if turn is latest:
            continue
        turn.pop("datasets", None)
        turn.pop("scope", None)
        turn.pop("plan", None)
    return kept


def latest_data_turn(history: list[dict]) -> dict | None:
    for turn in reversed(history):
        if turn.get("kind") == "data":
            return turn
    return None


def analysis_block(turn: dict) -> str:
    metrics = "\n".join(f"- {line}" for line in turn.get("metrics") or []) or "- none"
    charts = "\n".join(f"- {title}" for title in turn.get("charts") or []) or "- none"
    insights = "\n".join(f"- {line}" for line in turn.get("insights") or []) or "- none"
    return (
        f"Question: {turn.get('user')}\n"
        f"Metrics:\n{metrics}\n"
        f"Charts:\n{charts}\n"
        f"Findings:\n{insights}\n"
        f"Briefing:\n{turn.get('assistant') or ''}"
    )


def converse(query: str, history: list[dict], emit: Emit) -> dict:
    emit("general", "thought", "Reply in plain language. Do not fetch datasets or invent figures.")
    latest = latest_data_turn(history)
    latest_position = max(
        (position for position, turn in enumerate(history) if turn.get("kind") == "data"),
        default=-1,
    )
    followups = history[latest_position + 1 :] if latest_position >= 0 else history
    transcript = "\n".join(
        f"User: {turn['user']}\nAssistant: {turn['assistant']}" for turn in followups
    ) or "none"
    try:
        answer = complete(
            system=(
                "You are the general conversation agent for a Singapore public-data workspace. "
                "Talk naturally. If a latest analysis is provided, answer only from that analysis. "
                "Use only figures stated there and never fetch, infer or invent new statistics. "
                "If the answer is not covered, say so and ask the user to start a New conversation for a new analysis. "
                "Earlier turns are conversational context, not a source of facts."
            ),
            human="Latest analysis:\n{analysis}\n\nEarlier turns:\n{transcript}\n\nUser: {query}",
            schema=ChatReply,
            variables={
                "query": query,
                "transcript": transcript,
                "analysis": analysis_block(latest) if latest else "none",
            },
            timeout=12,
            models=settings.fast_chat_model_ids(),
        )
        message = answer["body"].get("message") or local_reply(query, latest)
        provider = answer["provider"]
        usage = answer.get("usage") or {}
        error = ""
    except Exception as failure:
        message = local_reply(query, latest)
        provider = "local"
        usage = {}
        error = failure.__class__.__name__
    emit("general", "observation", message[:240])
    return {
        "kind": "chat",
        "query": query,
        "scope": {"year_from": None, "year_to": None, "sector": None, "notes": []},
        "plan": [],
        "datasets": [],
        "summary": {"metrics": [], "charts": [], "correlations": []},
        "report": {
            "title": "Conversation",
            "insights": [],
            "briefing": message,
            "citations": [],
            "llm_provider": provider,
            "llm_usage": usage,
            "llm_error": error,
            "grounding": {"passed": True, "unsupported_numbers": []},
        },
    }


def local_reply(query: str, latest: dict | None = None) -> str:
    if latest:
        return (
            f"I could not answer that follow-up from the existing analysis of: {latest.get('user', 'this topic')}. "
            "Start a New conversation if you want me to fetch and analyse different data."
        )
    text = query.strip()
    if re.search(r"\b(hi|hello|hey|good morning|good afternoon)\b", text, re.I):
        return "Hello. I can chat normally, or analyse Singapore public statistics if you name a topic such as employment, CPI, housing or births."
    if re.search(r"\b(thank|thanks)\b", text, re.I):
        return "You're welcome. Ask a follow-up, or give me a statistic to look up."
    return (
        "I can keep this as a normal conversation. "
        "If you want figures, ask about something measurable, for example employment from 2020 to 2024, CPI since 2019, or HDB resale prices."
    )
