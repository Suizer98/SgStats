"""LLM-specific tests: hallucination detection, structured output, provider reporting, revision and consistency.

A LangChain fake chat model stands in for the gateway, so the real prompt, parser and
grounding code run without a network call. The live test at the bottom is opt-in.
"""

import json
import os
from pathlib import Path

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from app.agents import check_grounding, run
from app.agents.analytics import agent as analytics
from app.core import settings
from app.gov import catalog, data, fetch, sources
from app.llm import client

SCOPE = {"year_from": 2020, "year_to": 2024, "sector": None, "notes": []}


def summary_and_datasets():
    records = [
        {"period": str(year), "series": "Information and Communications", "measure": "Thousand", "value": value}
        for year, value in zip(range(2020, 2025), [157.6, 163.0, 171.2, 176.9, 180.3])
    ]
    dataset = {"title": "Employment By Sector", "source": "DOS", "citation": "DOS, Employment By Sector.", "grain": "year", "records": records}
    return data.summarise([dataset]), [dataset]


def use_fake_model(monkeypatch: pytest.MonkeyPatch, responses: list[str]) -> FakeListChatModel:
    model = FakeListChatModel(responses=responses)
    monkeypatch.setattr(client, "make_chat_model", lambda timeout=None: model)
    return model


def briefing(text: str, insights: list[str] | None = None) -> str:
    return json.dumps({"title": "ICT employment", "insights": insights or [text], "briefing": text})


def test_grounding_flags_unsupported_numbers():
    invented = check_grounding("ICT employment reached 999.9 thousand.", facts=[157.6, 180.3])
    assert invented["passed"] is False
    assert invented["unsupported_numbers"] == [999.9]
    assert not check_grounding("Employment grew 14.9%.", facts=[14.4])["passed"]
    assert check_grounding("A net change of \u20112,700 in 2020.", facts=[2700.0])["unsupported_numbers"] == [-2700.0]
    assert check_grounding("A net change of +300 in 2024.", facts=[-300.0])["passed"] is False
    text = "Births to women aged 15 - 19 Years fell to 1.3."
    assert not check_grounding(text, facts=[1.3])["passed"]


def test_grounding_accepts_known_forms():
    assert check_grounding("Employment grew about 14% to 180 thousand.", facts=[14.4, 180.3])["passed"]
    assert check_grounding("ICT employment fell by 300 in 2024.", facts=[-300.0])["passed"]
    assert check_grounding("Changes were -300 and +15,200 (\u22125,100).", facts=[-300.0, 15200.0, -5100.0])["passed"]
    assert check_grounding("Between 10-15 and 157.6\u2013180.3 over 2020\u20132024.", facts=[10, 15, 157.6, 180.3])["passed"]
    text = "Stock reached 187,300 (187.3 thousand, or 0.19 million)."
    assert check_grounding(text, facts=[187300.0])["passed"]
    assert check_grounding("Between 2020 and 2024-Q3 and 2022-12 the series moved.", facts=[])["passed"]
    labelled = "Births to women aged 15 - 19 Years fell to 1.3."
    assert check_grounding(labelled, facts=[1.3], labels=["15 - 19 Years"])["passed"]
    assert check_grounding("", facts=[1.0])["passed"]


def test_structured_output_is_parsed_from_the_chat_model(monkeypatch: pytest.MonkeyPatch):
    use_fake_model(monkeypatch, [briefing("ICT employment rose 14.4% from 157.6 to 180.3 thousand.")])
    summary, datasets = summary_and_datasets()
    report = analytics.write_report("ICT employment 2020-2024", SCOPE, summary, datasets)
    assert report["llm_provider"] == "gateway"
    assert report["grounding"]["passed"] is True
    assert report["citations"] == ["DOS, Employment By Sector."]
    assert report["llm_error"] == ""


def test_code_fenced_json_is_accepted(monkeypatch: pytest.MonkeyPatch):
    use_fake_model(monkeypatch, ["```json\n" + briefing("ICT employment was 180.3 thousand in 2024.") + "\n```"])
    summary, datasets = summary_and_datasets()
    assert analytics.write_report("q", SCOPE, summary, datasets)["grounding"]["passed"] is True


def test_malformed_output_falls_back_to_a_grounded_template(monkeypatch: pytest.MonkeyPatch):
    use_fake_model(monkeypatch, ["this is not json"])
    summary, datasets = summary_and_datasets()
    report = analytics.write_report("q", SCOPE, summary, datasets)
    assert report["llm_provider"] == "local"
    assert report["llm_error"]
    assert report["grounding"]["passed"] is True


def test_hallucinated_draft_is_revised_through_the_graph(monkeypatch: pytest.MonkeyPatch):
    use_fake_model(
        monkeypatch,
        [
            json.dumps({"kind": "data", "reason": "Needs fresh statistics."}),
            json.dumps({"datasets": ["datagov:d_293a874aff064ea9408f31c4da9dd4bb"], "rationale": "Employment by industry."}),
            briefing("ICT employment jumped 918.4% in 2024."),
            briefing("ICT employment was reported for 2020 to 2024 in the cited series."),
        ],
    )
    pinned = sources.PINNED[1]
    monkeypatch.setattr(fetch, "search", lambda *args, **kwargs: [catalog.candidate("datagov", pinned, 1.0)])

    def snapshot(provider, dataset_id, year_from, year_to, query="", title=""):
        result = data.load_snapshot(pinned["snapshot"], year_from, year_to)
        return {"provider": provider, "dataset_id": dataset_id, "title": pinned["title"], "source": pinned["agency"], "citation": "c", "mode": "snapshot_fallback", **result}

    monkeypatch.setattr(fetch, "extract_one", snapshot)
    events = []
    result = run("Employment from 2020-2024", lambda agent, step, content: events.append(content))
    assert result["report"]["grounding"]["passed"] is True
    assert result["report"]["llm_provider"] == "gateway"
    assert any("918.4" in content for content in events)
    assert any("Employment by industry." == content for content in events)


def test_summary_is_deterministic():
    first, _ = summary_and_datasets()
    second, _ = summary_and_datasets()
    assert first == second


def test_same_answer_gives_the_same_report(monkeypatch: pytest.MonkeyPatch):
    answer = briefing("ICT employment rose 14.4% to 180.3 thousand.")
    summary, datasets = summary_and_datasets()
    reports = []
    for _ in range(3):
        use_fake_model(monkeypatch, [answer])
        reports.append(analytics.write_report("q", SCOPE, summary, datasets))
    assert all(item == reports[0] for item in reports)


def test_template_report_is_always_grounded():
    summary, datasets = summary_and_datasets()
    body = analytics.fallback_report("q", summary, datasets, ["A note."])
    assert check_grounding(body["briefing"] + " " + " ".join(body["insights"]), summary["facts"])["passed"]
    assert "A note." in body["briefing"]


def test_template_report_with_numbered_labels_is_grounded():
    records = [
        {"period": str(year), "series": series, "measure": "Per Thousand Females", "value": value}
        for series, values in {"15 - 19 Years": [2.6, 2.1, 1.3], "20 - 24 Years": [9.8, 8.1, 7.0]}.items()
        for year, value in zip(range(2017, 2020), values)
    ]
    dataset = {"title": "Births", "source": "DOS", "citation": "c", "grain": "year", "records": records}
    summary = data.summarise([dataset])
    body = analytics.fallback_report("q", summary, [dataset])
    text = body["briefing"] + " " + " ".join(body["insights"])
    assert check_grounding(text, summary["facts"], analytics.summary_labels(summary))["passed"]


def test_bifrost_config_stores_logs_and_settings_in_postgres():
    path = Path(settings.ROOT).parent / "bifrost" / "config.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    assert config["client"]["enable_logging"] is True
    assert set(config["providers"]) == {"gemini", "groq"}
    logs = config["logs_store"]
    stored = config["config_store"]
    assert logs["enabled"] is True and stored["enabled"] is True
    assert logs["type"] == stored["type"] == "postgres"
    assert logs["config"]["db_name"] == stored["config"]["db_name"] == "sgstats"
    assert logs["config"]["host"] == stored["config"]["host"] == "postgres"


def test_gateway_requests_only_the_configured_model(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "BIFROST_URL", "http://bifrost:8080")
    monkeypatch.setattr(settings, "GEMINI_MODEL", "gemini-test")
    monkeypatch.setattr(settings, "GROQ_MODEL", "groq-test")
    model = client.make_chat_model()
    assert model.model_name == "gemini/gemini-test"
    assert not model.extra_body
    assert str(model.openai_api_base).endswith("/v1")


def test_provider_log_lists_gemini_then_groq():
    client.begin_providers()
    client.note_provider("groq")
    client.note_provider("gemini")
    client.note_provider("groq")
    client.note_provider("local")
    assert client.providers_used() == ["gemini", "groq"]


def test_no_gateway_means_no_model(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "BIFROST_URL", "")
    assert client.make_chat_model() is None
    with pytest.raises(client.LLMError):
        client.complete("s", "h", analytics.Briefing, {})


@pytest.mark.skipif(not os.getenv("LIVE_LLM_URL"), reason="set LIVE_LLM_URL to a running Bifrost to run live LLM checks")
def test_live_briefing_is_grounded_and_consistent(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "BIFROST_URL", os.environ["LIVE_LLM_URL"])
    monkeypatch.setattr(settings, "GEMINI_MODEL", os.getenv("GEMINI_MODEL", ""))
    monkeypatch.setattr(settings, "GROQ_MODEL", os.getenv("GROQ_MODEL", ""))
    summary, datasets = summary_and_datasets()
    reports = [analytics.write_report("ICT employment 2020-2024", SCOPE, summary, datasets) for _ in range(2)]
    for report in reports:
        assert report["llm_provider"] in {"gemini", "groq", "gateway"}
        assert report["grounding"]["passed"], report["grounding"]
