from __future__ import annotations

import re

from pydantic import BaseModel, Field

from app.agents.types import Emit
from app.core import settings, store
from app.gov import catalog
from app.llm.client import complete


DATA_CUES = re.compile(
    r"\b(analys|compar|correlat|statistic|dataset|employment|unemploy|wage|salary|cpi|inflation|"
    r"gdp|hdb|fertility|birth|housing|price|vacanc|workforce|sector|resident|population)\b",
    re.I,
)


class ChatReply(BaseModel):
    message: str = Field(description="A direct conversational reply, with no invented statistics")


class Intent(BaseModel):
    kind: str = Field(description="data to fetch and analyse new statistics, or chat for everything else")
    reason: str = Field(default="", description="One short sentence explaining the choice")


def looks_like_data(query: str) -> bool:
    if DATA_CUES.search(query):
        return True
    words = re.findall(r"[a-z][a-z\-]*", query.lower())
    return any(word in catalog.SYNONYMS for word in words)


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


def classify(query: str, history: list[dict], emit: Emit) -> str:
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
            }
        )
    return turns[-6:]


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
    transcript = "\n".join(f"User: {turn['user']}\nAssistant: {turn['assistant']}" for turn in history) or "none"
    try:
        answer = complete(
            system=(
                "You are the general conversation agent for a Singapore public-data workspace. "
                "Talk naturally. When the user refers to results, use the latest analysis below, "
                "which is what they currently see on screen. Use only figures stated there and never invent numbers. "
                "If they want new statistics, suggest asking a specific question such as employment, CPI, housing or births."
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
        message = answer["body"].get("message") or local_reply(query)
        provider = answer["provider"]
        usage = answer.get("usage") or {}
        error = ""
    except Exception as failure:
        message = local_reply(query)
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


def local_reply(query: str) -> str:
    text = query.strip()
    if re.search(r"\b(hi|hello|hey|good morning|good afternoon)\b", text, re.I):
        return "Hello. I can chat normally, or analyse Singapore public statistics if you name a topic such as employment, CPI, housing or births."
    if re.search(r"\b(thank|thanks)\b", text, re.I):
        return "You're welcome. Ask a follow-up, or give me a statistic to look up."
    return (
        "I can keep this as a normal conversation. "
        "If you want figures, ask about something measurable, for example employment from 2020 to 2024, CPI since 2019, or HDB resale prices."
    )
