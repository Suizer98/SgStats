from __future__ import annotations

from pydantic import BaseModel, Field

from app.agents.types import Emit
from app.constants import NUMBERS, PERIOD_LABELS
from app.gov import data
from app.llm.client import complete


class Briefing(BaseModel):
    title: str
    insights: list[str] = Field(default_factory=list)
    briefing: str


def close_to_fact(token: str, facts: list[float], sign: str = "") -> bool:
    """A number is supported when some fact, read in units, thousands, millions or billions, rounds to it.

    Unsigned numbers match by magnitude because prose says 'fell by 300' for a value of -300,
    while an explicit sign must agree with the fact's sign.
    """
    text = token.replace(",", "")
    decimals = len(text.split(".")[1]) if "." in text else 0
    size = float(text)
    if sign == "-":
        candidates = [-fact for fact in facts if fact < 0]
    elif sign == "+":
        candidates = [fact for fact in facts if fact > 0]
    else:
        candidates = [abs(fact) for fact in facts]
    for scale in (1, 1_000, 1_000_000, 1_000_000_000):
        if any(round(fact / scale, decimals) == size for fact in candidates):
            return True
    return False


def summary_labels(summary: dict) -> list[str]:
    labels = [metric["label"] for metric in summary.get("metrics", [])]
    for chart in summary.get("charts", []):
        labels.append(chart["title"])
        labels.extend(item["label"] for item in chart["series"])
    return labels


def check_grounding(text: str, facts: list[float], labels: list[str] | None = None) -> dict:
    """Numbers inside series or chart labels, such as the '19' in '15 - 19 Years', are names, not claims."""
    stripped = PERIOD_LABELS.sub(" ", text)
    last_year = data.current_year() + 1
    named = {token for label in labels or [] for _, token in NUMBERS.findall(label)}
    unsupported = []
    for mark, token in NUMBERS.findall(stripped):
        size = float(token.replace(",", ""))
        if size.is_integer() and 1950 <= size <= last_year:
            continue
        if token in named:
            continue
        sign = "+" if mark == "+" else "-" if mark else ""
        if close_to_fact(token, facts, sign):
            continue
        unsupported.append(-size if sign == "-" else size)
    return {
        "passed": len(unsupported) == 0,
        "unsupported_numbers": unsupported[:10],
    }


def chart_preview(charts: list[dict]) -> str:
    lines = []
    for chart in charts:
        labels = {item["key"]: item["label"] for item in chart["series"]}
        lines.append(f"{chart['title']} ({chart['yLabel']} by {chart['xLabel']}; {chart['subtitle']})")
        for row in chart["data"][-6:]:
            values = ", ".join(f"{labels[key]}={value}" for key, value in row.items() if key in labels)
            lines.append(f"  {row['period']}: {values}")
    return "\n".join(lines)


def fallback_report(query: str, summary: dict, datasets: list[dict], notes: list[str] | None = None) -> dict:
    insights = [
        f"{metric['label']}: {metric['value']:,.1f}{metric['unit']} ({metric['detail']})."
        for metric in summary.get("metrics", [])[:3]
    ] or ["No numeric series were available for this question."]
    for item in summary.get("correlations", [])[:1]:
        insights.append(
            f"{item['a']} and {item['b']} show a {item['strength']} correlation (r = {item['r']:.2f}, {item['periods']} periods)."
        )
    titles = ", ".join(item["title"] for item in datasets) or "no datasets"
    return {
        "title": f"Briefing: {datasets[0]['title']}" if datasets else "Policy briefing",
        "insights": insights,
        "briefing": (
            f"This briefing answers: {query}. "
            + " ".join(notes or [])
            + f" It draws on {titles}. "
            + " ".join(insights)
            + " Verify against the cited official series before publishing policy recommendations."
        ),
    }


def write_report(
    query: str,
    scope: dict,
    summary: dict,
    datasets: list[dict],
    feedback: str = "No correction requested.",
) -> dict:
    citations = [item["citation"] for item in datasets]
    facts_lines = [
        f"- {metric['label']}: {metric['value']}{metric['unit']} ({metric['detail']})" for metric in summary["metrics"]
    ]
    facts_lines.extend(
        f"- Correlation {item['a']} vs {item['b']}: r = {item['r']} over {item['periods']} periods ({item['strength']})"
        for item in summary.get("correlations", [])
    )
    try:
        answer = complete(
            system=(
                "You are a careful Singapore policy analyst. Use only numbers in the user message. "
                "Do not invent figures and keep each number's sign exactly as given. "
                "If the data does not fully answer the question, say what it does cover "
                "(for example the latest period available). Mention correlations only as associations, not causes."
            ),
            human=(
                "Query: {query}\nRequested years: {year_from}-{year_to}\nScope notes: {notes}\n"
                "Facts:\n{facts}\nChart data:\n{preview}\nCorrection request: {feedback}"
            ),
            schema=Briefing,
            variables={
                "query": query,
                "year_from": scope["year_from"],
                "year_to": scope["year_to"],
                "notes": " ".join(
                    (scope.get("notes") or []) + [f"{item['title']}: {item['note']}" for item in datasets if item.get("note")]
                )
                or "none",
                "facts": "\n".join(facts_lines),
                "preview": chart_preview(summary["charts"]),
                "feedback": feedback,
            },
        )
        body = answer["body"]
        provider = answer["provider"]
        usage = answer.get("usage", {})
        error = ""
    except Exception as failure:
        body = fallback_report(query, summary, datasets, scope.get("notes"))
        provider = "local"
        usage = {}
        error = failure.__class__.__name__

    briefing = body.get("briefing", "")
    insights = body.get("insights") or []
    grounding = check_grounding(briefing + " " + " ".join(insights), summary.get("facts", []), summary_labels(summary))
    return {
        "title": body.get("title", "Policy briefing"),
        "insights": insights,
        "briefing": briefing,
        "citations": citations,
        "llm_provider": provider,
        "llm_usage": usage,
        "llm_error": error,
        "grounding": grounding,
    }


def analyse(query: str, scope: dict, terms: dict, datasets: list[dict], emit: Emit) -> tuple[dict, dict]:
    emit(
        "analytics",
        "thought",
        "Aggregate each series to one point per period, compute latest values and change, then draft a grounded briefing.",
    )
    emit("analytics", "action", "Summarise with pandas, then a LangChain chain through the gateway writes insights.")
    summary = data.summarise(datasets, terms["tokens"])
    if summary["correlations"]:
        top = summary["correlations"][0]
        emit(
            "analytics",
            "observation",
            f"{len(summary['charts'])} charts, {len(summary['metrics'])} metrics. Strongest correlation: "
            f"{top['a']} vs {top['b']} r={top['r']} ({top['strength']}, {top['periods']} periods).",
        )
    report = write_report(query, scope, summary, datasets)
    emit("analytics", "observation", report_status(report))
    return summary, report


def report_status(report: dict) -> str:
    parts = [f"Report via {report['llm_provider']}"]
    usage = report.get("llm_usage") or {}
    if usage.get("seconds"):
        parts.append(f"{usage['input_tokens']}+{usage['output_tokens']} tokens in {usage['seconds']}s")
    if report.get("llm_error"):
        parts.append(f"LLM unavailable ({report['llm_error']}), used the template report")
    parts.append(f"grounding passed={report['grounding']['passed']}")
    return ". ".join(parts) + "."


def revise_report(
    query: str,
    scope: dict,
    summary: dict,
    datasets: list[dict],
    previous: dict,
    emit: Emit,
) -> dict:
    unsupported = previous["grounding"]["unsupported_numbers"]
    emit(
        "analytics",
        "action",
        f"Grounding found unsupported numbers {unsupported}. Revise the briefing once using only supplied facts.",
    )
    feedback = (
        f"Rewrite the previous draft and remove or correct unsupported numbers {unsupported}. "
        f"Previous briefing: {previous['briefing']}"
    )
    report = write_report(query, scope, summary, datasets, feedback)
    if not report["grounding"]["passed"]:
        body = fallback_report(query, summary, datasets, scope.get("notes"))
        text = body["briefing"] + " " + " ".join(body["insights"])
        report = {
            **body,
            "citations": [item["citation"] for item in datasets],
            "llm_provider": "local",
            "llm_usage": {},
            "llm_error": "Revised draft still had unsupported numbers",
            "grounding": check_grounding(text, summary.get("facts", []), summary_labels(summary)),
        }
    emit("analytics", "observation", "Revised. " + report_status(report))
    return report


def build_chat_message(query: str, scope: dict, datasets: list[dict], summary: dict, report: dict) -> str:
    metrics = summary.get("metrics", [])[:3]
    insights = report.get("insights", [])[:2]
    titles = ", ".join(item.get("title", "a dataset") for item in datasets[:2]) or "available datasets"
    years = f"{scope.get('year_from')}-{scope.get('year_to')}"

    greeting = f"Here's what I found for your question on {query.lower().rstrip('?')} for {years}:"

    if metrics:
        highlights = " Key figures: "
        highlights += ", ".join(
            f"{m['label']} is {m['value']:,.1f}{m['unit']} ({m['detail']})" for m in metrics
        )
        greeting += highlights
    if insights:
        greeting += " " + " ".join(insights)

    greeting += f" I pulled this from {titles}. "

    correlations = summary.get("correlations", [])[:1]
    if correlations:
        corr = correlations[0]
        greeting += f"Notably, {corr['a']} and {corr['b']} show a {corr['strength']} association (r={corr['r']:.2f}). "

    greeting += "You can switch to the Analysis tab above to see the full charts, metrics, and citations. Feel free to ask a follow-up!"
    return greeting


def build_result(
    query: str,
    scope: dict,
    chosen: list[str],
    by_key: dict[str, dict],
    datasets: list[dict],
    summary: dict,
    report: dict,
) -> dict:
    chat_message = build_chat_message(query, scope, datasets, summary, report)
    return {
        "kind": "data",
        "query": query,
        "scope": scope,
        "plan": [by_key[key] for key in chosen],
        "datasets": datasets,
        "summary": {
            "metrics": summary["metrics"],
            "charts": summary["charts"],
            "correlations": summary.get("correlations", []),
        },
        "report": {
            **report,
            "chat_message": chat_message,
        },
    }
