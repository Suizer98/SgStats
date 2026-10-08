import pytest

from app.agents import run
from app.agents.analytics import agent as analytics
from app.agents.coordinator import agent as coordinator
from app.gov import catalog, data, fetch, sources


def test_pipeline_without_llm_keys(monkeypatch: pytest.MonkeyPatch):
    events = []

    def search(query, year_from, year_to, sector=None, phrases=None):
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
    assert len(result["plan"]) == 2
    assert {item["provider"] for item in result["plan"]} == {"datagov"}
    agents = {item[0] for item in events}
    assert agents == {"coordinator", "extractor", "analytics"}
    steps = {item[1] for item in events}
    assert {"thought", "action", "observation"} <= steps


def test_failed_fetch_moves_to_next_candidate(monkeypatch: pytest.MonkeyPatch):
    events = []
    candidates = catalog.pinned_candidates()

    def search(query, year_from, year_to, sector=None, phrases=None):
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
    assert looks_like_data("How many total EP workers in Singapore from 2020 to current")
    assert not looks_like_data("hello, what can you do?")
    assert not looks_like_data("thanks, that was helpful")


def saved_employment() -> dict:
    return {
        "user": "Analyse employment trends from 2020 to 2024",
        "assistant": "Manufacturing employment rose.",
        "kind": "data",
        "metrics": ["Manufacturing: 494.4 Thousand (increased)"],
        "charts": ["Employment by sector"],
        "insights": ["Manufacturing increased"],
        "scope": {"year_from": 2020, "year_to": 2024, "sector": None},
        "datasets": [
            {
                "provider": "datagov",
                "dataset_id": "employment",
                "title": "Employment",
                "source": "Ministry of Manpower",
                "citation": "Ministry of Manpower, Employment.",
                "mode": "live",
                "format": "json",
                "quality": {"ok": True},
                "records": [
                    {"period": "2020", "series": "Manufacturing", "measure": "Thousand", "value": 100},
                    {"period": "2024", "series": "Manufacturing", "measure": "Thousand", "value": 120},
                ],
            }
        ],
    }


def test_follow_up_edits_the_saved_analysis(monkeypatch: pytest.MonkeyPatch):
    calls = []
    monkeypatch.setattr(fetch, "search", lambda *args, **kwargs: calls.append(args))
    result = run("Focus on 2020", lambda *event: None, [saved_employment()])
    assert result["kind"] == "data"
    assert calls == []
    assert result["datasets"][0]["dataset_id"] == "employment"
    assert [row["period"] for row in result["datasets"][0]["records"]] == ["2020"]
    assert "same datasets were reused" in " ".join(result["scope"]["notes"])


def test_chat_follow_up_does_not_edit_or_fetch(monkeypatch: pytest.MonkeyPatch):
    from app.agents.general import agent as general

    calls = []
    searches = []
    monkeypatch.setattr(fetch, "search", lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(general, "web_search", lambda query: searches.append(query) or [])
    result = run("thanks, that was helpful", lambda *event: None, [saved_employment()])
    assert result["kind"] == "chat"
    assert calls == []
    assert searches == []


def test_follow_up_searches_the_web_without_fetching_datasets(monkeypatch: pytest.MonkeyPatch):
    from app.agents.general import agent as general
    from app.agents.general import search as web

    page = """
    <a class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.mom.gov.sg%2Fpasses&amp;rut=1">Employment Pass</a>
    <a class="result__snippet" href="https://example.invalid">For professionals.</a>
    <a class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa">Other</a>
    <a class="result__snippet" href="https://example.invalid">Nothing useful.</a>
    """

    class Response:
        text = page

        def raise_for_status(self):
            return None

    class Client:
        def __init__(self, *args, **kwargs):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, data):
            if data["q"].startswith("down"):
                raise RuntimeError("down")
            assert "how come" in data["q"]
            return Response()

    monkeypatch.setattr(web.httpx, "Client", Client)
    found = web.web_search("how come EP more than SP")
    assert found[0]["url"] == "https://www.mom.gov.sg/passes"
    assert found[0]["title"] == "Employment Pass"
    assert "professionals" in found[0]["snippet"]
    assert found[1]["url"] == "https://example.com/a"
    assert web.web_search("down") == []
    assert web.web_search("   ") == []

    calls = []
    searches = []

    def complete(system, human, schema, variables, timeout=None):
        assert "mom.gov.sg" in variables["web"]
        assert "Never replace an analysis figure" in system
        return {
            "body": {"message": "The chart keeps the saved stocks. MOM describes Employment Pass as a pass for professionals."},
            "provider": "test",
            "usage": {},
        }

    monkeypatch.setattr(fetch, "search", lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(general, "web_search", lambda query: searches.append(query) or found[:1])
    monkeypatch.setattr(general, "complete", complete)
    events = []
    result = run(
        "how come EP more than SP",
        lambda agent, step, content: events.append((agent, step, content)),
        [saved_employment()],
    )
    assert result["kind"] == "chat"
    assert result["datasets"] == []
    assert calls == []
    assert searches and "how come EP more than SP" in searches[0]
    assert "professionals" in result["report"]["briefing"]
    assert any(step == "action" and content.startswith("Search the web") for _, step, content in events)


def test_follow_up_uses_safe_local_reply_when_llm_is_down(monkeypatch: pytest.MonkeyPatch):
    from app.agents.general import agent as general

    monkeypatch.setattr(general, "web_search", lambda query: [])
    monkeypatch.setattr(general, "complete", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("down")))
    history = [
        {
            "user": "Analyse employment",
            "assistant": "Employment increased.",
            "kind": "data",
            "metrics": [],
            "charts": [],
            "insights": [],
        }
    ]
    result = run("What about housing?", lambda *event: None, history)
    assert result["kind"] == "chat"
    assert "existing analysis of: Analyse employment" in result["report"]["briefing"]
    assert "New conversation" in result["report"]["briefing"]


def test_coordinator_notes_when_search_is_down(monkeypatch: pytest.MonkeyPatch):
    def down(*args, **kwargs):
        raise ConnectionError("gov-mcp down")

    monkeypatch.setattr(fetch, "search", down)
    events = []
    scope, terms, chosen, by_key = coordinator.plan("Analyse wages 2020-2024", lambda *event: events.append(event))
    assert scope["notes"] == ["Dataset search was unavailable, so datasets with offline snapshots were considered."]
    assert chosen and set(chosen) <= set(by_key)
    assert ("coordinator", "observation", "Catalog search failed (ConnectionError).") in events


def test_coordinator_flags_ambiguous_question(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(fetch, "search", lambda *args, **kwargs: [])
    scope, terms, chosen, by_key = coordinator.plan("tell me something", lambda *event: None)
    assert scope["notes"] and "nothing was charted" in scope["notes"][-1]
    assert terms["phrases"]
    assert chosen == []
    assert by_key == {}


def test_coordinator_drops_keys_outside_candidates(monkeypatch: pytest.MonkeyPatch):
    real = f"singstat:{sources.PINNED[2]['id']}"
    answer = {"body": {"datasets": ["datagov:invented", real], "rationale": "r"}, "provider": "gateway"}
    monkeypatch.setattr(coordinator, "complete", lambda **kwargs: answer)
    chosen, rationale = coordinator.choose_datasets("q", catalog.pinned_candidates(), 2020, 2024)
    assert chosen == [real]
    assert rationale == "r"


def test_unrelated_candidates_are_not_charted(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        fetch,
        "search",
        lambda *args, **kwargs: [
            {
                "provider": "datagov",
                "id": "d_workers",
                "title": "Workers In Manufacturing By Industry, Annual",
                "agency": "DOS",
                "coverage": "2020-2024",
                "score": 3,
            }
        ],
    )
    monkeypatch.setattr(
        coordinator,
        "complete",
        lambda **kwargs: {
            "body": {"datasets": [], "rationale": "Manufacturing workers do not measure employment pass holders."},
            "provider": "gateway",
        },
    )
    result = run("Analyse employment pass holders from 2020 to 2024", lambda *event: None)
    assert result["datasets"] == []
    assert "directly measures" in result["report"]["chat_message"]


def test_coordinator_rejects_plan_with_only_invented_keys(monkeypatch: pytest.MonkeyPatch):
    answer = {"body": {"datasets": ["datagov:invented"], "rationale": ""}, "provider": "gateway"}
    monkeypatch.setattr(coordinator, "complete", lambda **kwargs: answer)
    with pytest.raises(coordinator.LLMError):
        coordinator.choose_datasets("q", catalog.pinned_candidates(), 2020, 2024)
