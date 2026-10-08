import pytest

from app.agents import check_grounding
from app.core import settings, store
from app.gov import catalog, data, embed, fetch, sources
from app.gov.data import current_year, normalize_any, normalize_singstat, parse_period, parse_query, summarise

FOREIGN_WORKFORCE = [
    {"_id": 1, "month": "2021-12", "work_pass_type": "employment_pass", "count": "161700"},
    {"_id": 2, "month": "2021-12", "work_pass_type": "s_pass", "count": "161800"},
    {"_id": 3, "month": "2022-12", "work_pass_type": "employment_pass", "count": "187300"},
    {"_id": 4, "month": "2022-12", "work_pass_type": "s_pass", "count": "177900"},
]

CPI_WIDE = [
    {"_id": 1, "DataSeries": "All Items", "2021Jan": "95.0", "2021Feb": "97.0", "2022Jan": "100.0"},
    {"_id": 2, "DataSeries": "    Food", "2021Jan": "96.0", "2021Feb": "98.0", "2022Jan": "103.0"},
]

SINGSTAT_ROWS = [
    {"rowText": "Employment Pass Holders", "uoM": "Per Cent", "columns": [{"key": "2020", "value": "12"}, {"key": "2024", "value": "14.5"}]},
    {"rowText": "Work Permit Holders", "uoM": "Per Cent", "columns": [{"key": "2020", "value": "50"}, {"key": "2024", "value": "47"}]},
]


def test_parse_tech_query():
    scope = parse_query("Analyse employment trends in the technology sector from 2020-2024")
    assert scope == {"year_from": 2020, "year_to": 2024, "sector": "Information and Communications"}


def test_parse_open_ended_range():
    assert parse_query("How many EP workers from 2020 to current")["year_to"] == current_year()
    assert parse_query("CPI since 2019")["year_from"] == 2019
    assert parse_query("Births in 2020")["year_to"] == 2020
    assert parse_query("Births and fertility trends")["year_from"] == current_year() - 9


def test_parse_period():
    cases = [
        ("2020", ("2020", 2020, "year")),
        ("2020-Q3", ("2020-Q3", 2020, "quarter")),
        ("2020 3Q", ("2020-Q3", 2020, "quarter")),
        ("1Q2009", ("2009-Q1", 2009, "quarter")),
        ("2020-07", ("2020-07", 2020, "month")),
        ("2026Jul", ("2026-07", 2026, "month")),
        ("2020 Jan", ("2020-01", 2020, "month")),
        ("2020 2H", ("2020-H2", 2020, "half")),
        ("2019/20", ("2019", 2019, "year")),
        ("ANG MO KIO", None),
    ]
    for raw, expected in cases:
        assert parse_period(raw) == expected


def test_long_table_uses_column_titles_and_series():
    rows = normalize_any(FOREIGN_WORKFORCE, titles={"count": "Count"})
    assert {row["series"] for row in rows} == {"Employment Pass", "S Pass"}
    assert {row["measure"] for row in rows} == {"Count"}
    assert rows[0]["period"] == "2021-12"


def test_wide_table_is_unpivoted():
    rows = normalize_any(CPI_WIDE)
    assert len(rows) == 6
    assert {row["series"] for row in rows} == {"All Items", "Food"}


def test_chart_spec_is_built_from_the_data():
    records, grain, _ = data.finish_rows(normalize_any(CPI_WIDE), 2021, 2022)
    dataset = {"dataset_id": "cpi", "title": "Consumer Price Index", "source": "DOS", "grain": grain, "records": records}
    chart = summarise([dataset])["charts"][0]
    assert chart["title"] == "Consumer Price Index"
    assert chart["xLabel"] == "Month"
    assert chart["yLabel"] == "Value"
    assert [item["label"] for item in chart["series"]] == ["All Items", "Food"]
    assert chart["data"][0] == {"period": "2021-01", "s0": 95.0, "s1": 96.0}


def test_sub_annual_duplicates_are_averaged_per_period():
    records = [
        {"period": "2020", "series": "A", "measure": "Count", "value": 10.0},
        {"period": "2020", "series": "A", "measure": "Count", "value": 20.0},
        {"period": "2021", "series": "A", "measure": "Count", "value": 30.0},
    ]
    chart = summarise([{"title": "T", "source": "S", "grain": "year", "records": records}])["charts"][0]
    assert chart["data"] == [{"period": "2020", "s0": 15.0}, {"period": "2021", "s0": 30.0}]


def test_percent_series_report_percentage_points():
    records, grain, _ = data.finish_rows(normalize_singstat(SINGSTAT_ROWS), 2020, 2024)
    summary = summarise([{"title": "Share by pass", "source": "DOS", "grain": grain, "records": records}])
    chart = summary["charts"][0]
    assert chart["yLabel"] == "Per Cent" and chart["unit"] == "%"
    assert summary["metrics"][0]["change"] == 2.5
    assert "pp" in summary["metrics"][0]["detail"]


def test_series_on_a_different_scale_are_dropped():
    records = [
        {"period": "2024", "series": "Fertility rate", "measure": "Value", "value": 0.97},
        {"period": "2024", "series": "Crude birth rate", "measure": "Value", "value": 6.5},
        {"period": "2024", "series": "Live births", "measure": "Value", "value": 30000.0},
    ]
    chart = summarise([{"title": "Births", "source": "DOS", "grain": "year", "records": records}])["charts"][0]
    assert [item["label"] for item in chart["series"]] == ["Fertility rate", "Crude birth rate"]


def test_out_of_range_request_falls_back_to_latest_years():
    rows, _, note = data.finish_rows(normalize_any(FOREIGN_WORKFORCE), 2025, 2026)
    assert rows and note.startswith("No data for 2025-2026")


def test_search_terms_keep_the_question_words():
    terms = catalog.search_terms("How many total EP workers in Singapore from 2020 to current")
    assert "ep" in terms["phrases"]
    assert "employment pass" not in terms["phrases"]
    assert "singapore" not in terms["tokens"]


def test_search_terms_put_the_model_meaning_first():
    terms = catalog.search_terms(
        "How many total EP workers in Singapore from 2020 to current",
        extra=["employment pass", "foreign workforce"],
    )
    assert terms["phrases"][0] == "employment pass"
    assert {"employment", "pass", "foreign", "workforce", "ep"} <= terms["tokens"]


def test_meaning_phrases_follow_the_model(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "BIFROST_URL", "http://bifrost:8080")

    def fake_text(**kwargs):
        assert "EP" in kwargs["variables"]["query"]
        return "Employment Pass, foreign workforce"

    monkeypatch.setattr(catalog, "complete_text", fake_text)
    assert catalog.meaning_phrases("How many EP workers") == ["employment pass", "foreign workforce"]


def test_meaning_phrases_skip_when_the_gateway_is_down():
    assert catalog.meaning_phrases("How many EP workers") == []


def test_embedding_prefixes_differ_by_provider():
    assert embed.query_text("EP workers").startswith("task: search result")
    assert embed.query_text("EP workers", embed.GROQ_PROVIDER).startswith("search_query:")
    assert embed.document_text("Foreign Workforce", "MOM", embed.GROQ_PROVIDER).startswith("search_document:")


def test_retry_delay_comes_from_the_response():
    class Response:
        headers = {"retry-after": "12.5"}

        def json(self):
            return {}

    assert embed.retry_seconds(Response()) == 12.5

    class Body:
        headers = {}

        def json(self):
            return {"error": {"details": [{"retryDelay": "19.046s"}]}}

    assert embed.retry_seconds(Body()) == 19.046

    class Empty:
        headers = {}

        def json(self):
            return {"error": {"message": "quota"}}

    assert embed.retry_seconds(Empty()) is None


def test_vector_search_keeps_keyword_scores_behind(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(catalog, "index_is_stale", lambda: False)
    monkeypatch.setattr(catalog, "vectors_ready", lambda: True)
    monkeypatch.setattr(
        catalog,
        "search_stored",
        lambda query, year_from, year_to, terms=None: [
            {
                "provider": "datagov",
                "id": "ep",
                "title": "Stock of Foreign Workforce by Pass Type",
                "agency": "MOM",
                "coverage": "2017-2022",
                "score": 0.42,
            }
        ],
    )

    def keyword(*args, **kwargs):
        raise AssertionError("keyword catalogue should not run beside a vector hit")

    monkeypatch.setattr(catalog, "search_datagov", keyword)
    monkeypatch.setattr(catalog, "search_singstat", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        catalog,
        "search_internal",
        lambda *args, **kwargs: [
            {
                "provider": "internal",
                "id": "int",
                "title": "Sector Hiring",
                "agency": "Internal",
                "coverage": "",
                "score": 9.0,
            }
        ],
    )
    found = catalog.search("How many EP workers", 2020, 2026)
    assert [item["id"] for item in found] == ["ep", "int"]


def test_keyword_search_sorts_when_vectors_are_not_ready(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(catalog, "index_is_stale", lambda: False)
    monkeypatch.setattr(catalog, "vectors_ready", lambda: False)
    monkeypatch.setattr(
        catalog,
        "search_datagov",
        lambda *args, **kwargs: [
            {"provider": "datagov", "id": "low", "title": "Low", "agency": "", "coverage": "", "score": 1.0},
            {"provider": "datagov", "id": "high", "title": "High", "agency": "", "coverage": "", "score": 4.0},
        ],
    )
    monkeypatch.setattr(catalog, "search_singstat", lambda *args, **kwargs: [])
    monkeypatch.setattr(catalog, "search_internal", lambda *args, **kwargs: [])
    found = catalog.search("employment pass", 2020, 2024)
    assert [item["id"] for item in found] == ["high", "low"]


def test_catalog_is_stored_in_the_database():
    store.save_datagov_catalog(
        [
            {
                "id": "d1",
                "title": "Foreign Workforce",
                "agency": "MOM",
                "coverage_start": 2016,
                "coverage_end": 2024,
            }
        ]
    )
    catalog.index_cache = None
    assert catalog.load_index()[0]["id"] == "d1"
    assert catalog.index_is_stale() is False


def test_frequency_variants_are_duplicates():
    kept = [{"title": "Consumer Price Index (CPI), 2024 As Base Year, Annual"}]
    assert catalog.is_duplicate("Consumer Price Index (CPI), 2024 As Base Year, Half-Yearly", kept)
    assert not catalog.is_duplicate("Total Foreign Workforce", kept)


def test_live_failure_uses_snapshot(monkeypatch: pytest.MonkeyPatch):
    def fail(dataset_id):
        raise TimeoutError(dataset_id)

    monkeypatch.setattr(fetch, "get_datagov", fail)
    pinned = sources.PINNED[1]
    dataset = fetch.fetch_dataset(pinned["provider"], pinned["id"], 2020, 2024)
    assert dataset["mode"] == "snapshot_fallback"
    assert dataset["records"]
    assert dataset["title"] == pinned["title"]


def test_unknown_dataset_failure_raises(monkeypatch: pytest.MonkeyPatch):
    def fail(dataset_id):
        raise TimeoutError(dataset_id)

    monkeypatch.setattr(fetch, "get_datagov", fail)
    with pytest.raises(TimeoutError):
        fetch.fetch_dataset("datagov", "d_not_pinned", 2020, 2024)


def test_extract_one_calls_mcp(monkeypatch: pytest.MonkeyPatch):
    from app import mcp
    from app.core import settings

    monkeypatch.setattr(settings, "MCP_URL", "http://gov-mcp:8100")

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"mode": "live", "records": [{"period": "2020"}], "quality": {"ok": True}}

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, json):
            assert url == "http://gov-mcp:8100/mcp/tools/fetch_dataset"
            assert json["dataset_id"] == "d_abc"
            assert json["year_from"] == 2020
            return FakeResponse()

    monkeypatch.setattr(mcp.httpx, "Client", FakeClient)
    dataset = fetch.extract_one("datagov", "d_abc", 2020, 2024)
    assert dataset["mode"] == "live"


def test_unreachable_mcp_falls_back_to_pinned_snapshot(monkeypatch: pytest.MonkeyPatch):
    from app.core import settings

    monkeypatch.setattr(settings, "MCP_URL", "http://gov-mcp:8100")

    def unreachable(tool, arguments):
        raise TimeoutError("gov-mcp timed out")

    monkeypatch.setattr(fetch, "call_mcp", unreachable)
    pinned = sources.PINNED[0]
    dataset = fetch.extract_one(pinned["provider"], pinned["id"], 2020, 2024)
    assert dataset["mode"] == "snapshot_fallback"
    assert "unreachable" in dataset["note"]
    with pytest.raises(TimeoutError):
        fetch.extract_one("datagov", "d_not_pinned", 2020, 2024)


def test_request_time_embedding_fails_fast_on_rate_limit(monkeypatch: pytest.MonkeyPatch):
    from app.core import settings

    calls = []
    monkeypatch.setattr(settings, "BIFROST_URL", "http://bifrost:8080")
    monkeypatch.setattr(embed, "blocked_until", 0.0)
    monkeypatch.setattr(embed.time, "sleep", lambda seconds: pytest.fail("request path must not sleep"))

    class Limited:
        status_code = 429
        headers = {"retry-after": "30"}
        text = "quota"

    class FakeClient:
        def __init__(self, timeout):
            assert timeout == embed.REQUEST_TIMEOUT

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers, json):
            assert url == "http://bifrost:8080/v1/embeddings"
            assert json["model"] == "gemini/gemini-embedding-2"
            assert json["fallbacks"] == ["groq/nomic-embed-text-v1.5"]
            calls.append(url)
            return Limited()

    monkeypatch.setattr(embed.httpx, "Client", FakeClient)
    with pytest.raises(embed.QuotaError):
        embed.embed_texts(["employment"])
    with pytest.raises(embed.QuotaError):
        embed.embed_texts(["employment"])
    assert len(calls) == 1


def test_grounding_rejects_invented_numbers():
    result = check_grounding("GDP rose by 918.4 percent in 2021", facts=[26.9, 20.2, 185.4])
    assert result["passed"] is False
    assert 918.4 in result["unsupported_numbers"]


def test_grounding_accepts_known_facts():
    result = check_grounding("Employment rose 26.9% from 185.4k in 2020.", facts=[26.9, 185.4, 2020])
    assert result["passed"] is True


def test_grounding_handles_separators_scales_and_periods():
    facts = [187300.0, 5.8]
    text = "EP holders reached 187,300 (about 187.3 thousand) in 2022-12, up 5.8% over 2020-2022 and Q4."
    assert check_grounding(text, facts)["passed"] is True


def test_dataset_detail_includes_series_and_measure():
    detail = catalog.dataset_detail(
        {
            "source": "Ministry of Manpower",
            "grain": "month",
            "records": [
                {"series": "Employment Pass", "measure": "Count"},
                {"series": "S Pass", "measure": "Count"},
            ],
        }
    )
    assert "Employment Pass" in detail
    assert "S Pass" in detail
    assert "Count" in detail


def test_search_reads_stored_dataset_vectors(monkeypatch: pytest.MonkeyPatch):
    class Row:
        def tolist(self):
            return [0.2, 0.8]

    class Matrix:
        def __getitem__(self, index):
            return Row()

    monkeypatch.setattr(catalog, "index_is_stale", lambda: False)
    monkeypatch.setattr(catalog, "vectors_ready", lambda: True)
    monkeypatch.setattr(catalog.store, "datagov_embedding_model", lambda: "gemini/gemini-embedding-2")
    monkeypatch.setattr(
        catalog.store,
        "rank_datasets",
        lambda vector, limit=24, model=None: [
            {
                "provider": "datagov",
                "id": "ep",
                "title": "Stock of Foreign Workforce by Pass Type",
                "agency": "MOM",
                "coverage_start": 2017,
                "coverage_end": 2022,
                "score": 0.81,
            }
        ],
    )
    monkeypatch.setattr(
        catalog.embed,
        "embed_texts",
        lambda texts, model="gemini/gemini-embedding-2", patient=False: (Matrix(), model),
    )
    monkeypatch.setattr(catalog, "search_singstat", lambda terms, year_from, year_to: [])
    monkeypatch.setattr(catalog, "search_internal", lambda terms, year_from, year_to: [])

    found = catalog.search("How many EP workers", 2020, 2026)

    assert found[0]["id"] == "ep"
    assert found[0]["title"] == "Stock of Foreign Workforce by Pass Type"
