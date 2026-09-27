import pytest

from app.agents import run
from app.agents.analytics import agent as analytics
from app.agents.coordinator import agent as coordinator
from app.gov import catalog, data, fetch, sources


def test_pipeline_without_llm_keys(monkeypatch: pytest.MonkeyPatch):
    events = []

    def search(query, year_from, year_to, sector=None):
        return catalog.pinned_candidates()

    def snapshot(provider, dataset_id, year_from, year_to, query="", title=""):
        pinned = sources.get_pinned(provider, dataset_id)
        result = data.load_snapshot(pinned["snapshot"], year_from, year_to)
        return {
            "provider": provider,
            "dataset_id": dataset_id,
            "title": pinned["title"],
            "source": pinned["agency"],
            "citation": pinned["title"],
            "mode": "snapshot_fallback",
            **result,
        }

    monkeypatch.setattr(fetch, "search", search)
    monkeypatch.setattr(fetch, "extract_one", snapshot)
    result = run(
        "Analyse employment trends in the technology sector from 2020-2024",
        lambda agent, step, content: events.append((agent, step, content)),
    )
    assert result["report"]["llm_provider"] == "local"
    assert result["report"]["citations"]
    assert result["summary"]["metrics"]
    chart = result["summary"]["charts"][0]
    assert chart["title"] == sources.PINNED[0]["title"]
    assert chart["xLabel"] in {"Year", "Quarter"} and chart["yLabel"]
    assert len(result["plan"]) == 3
    assert {item["provider"] for item in result["plan"]} == {"datagov", "singstat"}
    assert any("cross-check" in content for _, _, content in events)
    agents = {item[0] for item in events}
    assert agents == {"coordinator", "extractor", "analytics"}
    steps = {item[1] for item in events}
    assert {"thought", "action", "observation"} <= steps


def test_failed_fetch_moves_to_next_candidate(monkeypatch: pytest.MonkeyPatch):
    events = []
    candidates = catalog.pinned_candidates()

    def search(query, year_from, year_to, sector=None):
        return candidates

    def flaky(provider, dataset_id, year_from, year_to, query="", title=""):
        if dataset_id == candidates[0]["id"]:
            raise TimeoutError(dataset_id)
        pinned = sources.get_pinned(provider, dataset_id)
        result = data.load_snapshot(pinned["snapshot"], year_from, year_to)
        return {"title": pinned["title"], "source": pinned["agency"], "citation": "c", "mode": "snapshot_fallback", **result}

    monkeypatch.setattr(fetch, "search", search)
    monkeypatch.setattr(fetch, "extract_one", flaky)
    result = run("Employment from 2020-2024", lambda agent, step, content: events.append((agent, step, content)))
    assert [item["title"] for item in result["datasets"]] == [candidates[1]["title"], candidates[2]["title"]]
    assert any("failed" in content for _, _, content in events)


def test_graph_replans_after_first_candidate_batch_fails(monkeypatch: pytest.MonkeyPatch):
    events = []
    pinned = sources.PINNED[0]
    candidates = [
        {
            "provider": "datagov",
            "id": f"d_{index}",
            "title": f"Candidate {index}",
            "agency": "Test",
            "coverage": "2020-2024",
        }
        for index in range(6)
    ]

    monkeypatch.setattr(fetch, "search", lambda *args, **kwargs: candidates)

    def fetch_candidate(provider, dataset_id, year_from, year_to, query="", title=""):
        if dataset_id in {"d_0", "d_1", "d_2", "d_3"}:
            raise TimeoutError(dataset_id)
        result = data.load_snapshot(pinned["snapshot"], year_from, year_to)
        return {
            "provider": provider,
            "dataset_id": dataset_id,
            "title": title,
            "source": "Test",
            "citation": title,
            "mode": "snapshot_fallback",
            **result,
        }

    monkeypatch.setattr(fetch, "extract_one", fetch_candidate)
    result = run("Employment from 2020-2024", lambda agent, step, content: events.append((agent, step, content)))

    assert [item["dataset_id"] for item in result["datasets"]] == ["d_4", "d_5"]
    assert any("Replan once" in content for _, _, content in events)


def test_graph_revises_unsupported_report_once(monkeypatch: pytest.MonkeyPatch):
    events = []
    candidates = catalog.pinned_candidates()
    calls = 0

    monkeypatch.setattr(fetch, "search", lambda *args, **kwargs: candidates)

    def snapshot(provider, dataset_id, year_from, year_to, query="", title=""):
        pinned = sources.get_pinned(provider, dataset_id)
        result = data.load_snapshot(pinned["snapshot"], year_from, year_to)
        return {
            "provider": provider,
            "dataset_id": dataset_id,
            "title": pinned["title"],
            "source": pinned["agency"],
            "citation": pinned["title"],
            "mode": "snapshot_fallback",
            **result,
        }

    def report(query, scope, summary, datasets, feedback="No correction requested."):
        nonlocal calls
        calls += 1
        passed = calls == 2
        return {
            "title": "Briefing",
            "insights": ["Grounded"] if passed else ["Invented 918.4"],
            "briefing": "Grounded report" if passed else "Invented 918.4",
            "citations": ["Test"],
            "llm_provider": "test",
            "grounding": {"passed": passed, "unsupported_numbers": [] if passed else [918.4]},
        }

    monkeypatch.setattr(fetch, "extract_one", snapshot)
    monkeypatch.setattr(analytics, "write_report", report)
    result = run("Employment from 2020-2024", lambda agent, step, content: events.append((agent, step, content)))

    assert calls == 2
    assert result["report"]["grounding"]["passed"] is True
    assert any("unsupported numbers" in content for _, _, content in events)


def test_general_chat_does_not_fetch_datasets(monkeypatch: pytest.MonkeyPatch):
    calls = []
    monkeypatch.setattr(fetch, "search", lambda *args, **kwargs: calls.append(args))
    events = []
    result = run("hello, what can you do?", lambda agent, step, content: events.append((agent, step, content)))
    assert result["kind"] == "chat"
    assert result["datasets"] == []
    assert calls == []
    assert any(agent == "general" for agent, _, _ in events)
    assert result["report"]["briefing"].startswith("Hello")


def test_statistics_question_is_not_sent_to_the_general_agent():
    from app.agents.general.agent import looks_like_data

    assert looks_like_data("Analyse employment trends in the technology sector from 2020-2024")
    assert not looks_like_data("hello, what can you do?")
    assert not looks_like_data("thanks, that was helpful")


def test_llm_routes_follow_up_and_sees_latest_analysis(monkeypatch: pytest.MonkeyPatch):
    from app.agents.general import agent as general

    prompts = []

    def fake_complete(system, human, schema, variables, **kwargs):
        prompts.append((schema.__name__, variables))
        if schema is general.Intent:
            return {"body": {"kind": "chat", "reason": "Follow-up about the analysis above."}, "provider": "groq"}
        return {"body": {"message": "Manufacturing reached 494.4 thousand."}, "provider": "groq"}

    calls = []
    monkeypatch.setattr(general, "complete", fake_complete)
    monkeypatch.setattr(fetch, "search", lambda *args, **kwargs: calls.append(args))
    history = [
        {
            "user": "How many total EP workers in Singapore from 2020 to current",
            "assistant": "No EP series was found.",
            "kind": "data",
            "metrics": [],
            "charts": [],
            "insights": [],
        },
        {
            "user": "Analyse employment trends in the technology sector from 2020-2024",
            "assistant": "Manufacturing employment rose.",
            "kind": "data",
            "metrics": ["Manufacturing: 494.4 Thousand (increased)"],
            "charts": ["Employment by sector"],
            "insights": ["Manufacturing increased"],
        },
    ]
    result = run("can u summarise the analysis result", lambda *event: None, history)
    assert result["kind"] == "chat"
    assert calls == []
    intent, reply = prompts
    assert "(analysis) Analyse employment trends" in intent[1]["outline"]
    assert "Manufacturing: 494.4" in reply[1]["analysis"]
    assert "EP workers" not in reply[1]["analysis"]


def test_coordinator_notes_when_search_is_down(monkeypatch: pytest.MonkeyPatch):
    def down(*args, **kwargs):
        raise ConnectionError("gov-mcp down")

    monkeypatch.setattr(fetch, "search", down)
    events = []
    scope, terms, chosen, by_key = coordinator.plan("Analyse wages 2020-2024", lambda *event: events.append(event))
    assert scope["notes"] == ["Dataset search was unavailable, so the default labour market and GDP datasets are shown."]
    assert chosen and set(chosen) <= set(by_key)
    assert ("coordinator", "observation", "Catalog search failed (ConnectionError).") in events


def test_coordinator_flags_ambiguous_question(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(fetch, "search", lambda *args, **kwargs: [])
    scope, *_ = coordinator.plan("tell me something", lambda *event: None)
    assert scope["notes"] and "default labour market" in scope["notes"][0]


def test_coordinator_drops_keys_outside_candidates(monkeypatch: pytest.MonkeyPatch):
    real = f"singstat:{sources.PINNED[2]['id']}"
    answer = {"body": {"datasets": ["datagov:invented", real], "rationale": "r"}, "provider": "gateway"}
    monkeypatch.setattr(coordinator, "complete", lambda **kwargs: answer)
    chosen, rationale = coordinator.choose_datasets("q", catalog.pinned_candidates(), 2020, 2024)
    assert chosen == [real]
    assert rationale == "r"


def test_cross_check_prefers_another_government_source():
    by_key = {
        "singstat:A": {"provider": "singstat"},
        "internal:X": {"provider": "internal"},
        "datagov:B": {"provider": "datagov"},
    }
    assert coordinator.cross_check(["singstat:A"], by_key) == "datagov:B"
    assert coordinator.cross_check(["singstat:A"], {k: v for k, v in by_key.items() if k != "datagov:B"}) == "internal:X"
    assert coordinator.cross_check(["singstat:A", "datagov:B"], by_key) is None


def test_coordinator_rejects_plan_with_only_invented_keys(monkeypatch: pytest.MonkeyPatch):
    answer = {"body": {"datasets": ["datagov:invented"], "rationale": ""}, "provider": "gateway"}
    monkeypatch.setattr(coordinator, "complete", lambda **kwargs: answer)
    with pytest.raises(coordinator.LLMError):
        coordinator.choose_datasets("q", catalog.pinned_candidates(), 2020, 2024)
