"""Accuracy of the deterministic analytics the agents rely on."""

import pytest

from app.gov import data, fetch, sources
from app.gov.data import summarise


def dataset(records: list[dict], title: str = "T") -> dict:
    return {"title": title, "source": "S", "grain": "year", "records": records}


def rows(series: str, values: list[float], start: int = 2019, measure: str = "Count") -> list[dict]:
    return [{"period": str(start + i), "series": series, "measure": measure, "value": v} for i, v in enumerate(values)]


def test_percent_change_matches_hand_calculation():
    metric = summarise([dataset(rows("Jobs", [200.0, 210.0, 250.0]))])["metrics"][0]
    assert metric["value"] == 250.0
    assert metric["change"] == 25.0
    assert "+25.0% since 2019 (200.0)" in metric["detail"]


def test_sign_crossing_series_reports_absolute_change():
    metric = summarise([dataset(rows("Net change", [2700.0, 1000.0, -300.0]))])["metrics"][0]
    assert metric["change"] == -3000.0
    assert "%" not in metric["detail"]


def test_correlation_between_series_is_pearson():
    records = rows("A", [1.0, 2.0, 3.0, 4.0, 5.0]) + rows("B", [2.0, 4.0, 6.0, 8.0, 10.0]) + rows("C", [5.0, 4.0, 3.0, 2.0, 1.0])
    correlations = summarise([dataset(records)])["correlations"]
    by_name = {item["b"]: item for item in correlations}
    assert by_name["B"]["r"] == 1.0 and by_name["B"]["strength"] == "strong positive"
    assert by_name["C"]["r"] == -1.0 and by_name["C"]["strength"] == "strong negative"
    assert by_name["B"]["periods"] == 5


def test_variants_of_the_same_series_are_not_correlated():
    records = (
        rows("Unemployed (Seasonally Adjusted)", [1.0, 2.0, 3.0, 4.0, 5.0])
        + rows("Unemployed (Non Seasonally Adjusted)", [1.1, 2.2, 2.9, 4.1, 5.0])
        + rows("Vacancies", [5.0, 4.0, 3.5, 2.0, 1.0])
    )
    names = {item["b"] for item in summarise([dataset(records)])["correlations"]}
    assert names == {"Vacancies"}


def test_correlation_needs_enough_shared_periods():
    records = rows("A", [1.0, 2.0, 3.0]) + rows("B", [3.0, 2.0, 1.0])
    assert summarise([dataset(records)])["correlations"] == []


def test_correlation_across_datasets_aligns_on_period():
    first = dataset(rows("Employed", [100.0, 110.0, 120.0, 130.0, 140.0]), "Employment")
    second = dataset(rows("Vacancies", [50.0, 40.0, 60.0, 70.0, 80.0], start=2019), "Vacancies")
    correlations = summarise([first, second])["correlations"]
    assert correlations[0]["b"] == "Vacancies"
    assert correlations[0]["b_source"] == "Vacancies"
    assert 0.7 < correlations[0]["r"] < 1.0


def test_facts_include_every_charted_value():
    summary = summarise([dataset(rows("Jobs", [200.0, -300.0, 250.0]))])
    assert {200.0, -300.0, 250.0} <= set(summary["facts"])


def test_internal_excel_source_is_normalised():
    item = sources.INTERNAL[0]
    result = fetch.fetch_dataset("internal", item["id"], 2020, 2024)
    assert result["format"] == "xlsx"
    assert result["mode"] == "live"
    assert {row["measure"] for row in result["records"]} == {"Vacancies", "Placements"}
    assert "Information and Communications" in {row["series"] for row in result["records"]}
    assert {row["period"] for row in result["records"]} == {"2020", "2021", "2022", "2023", "2024"}
    assert "mock" in result["note"].lower()


def test_unknown_internal_dataset_raises():
    with pytest.raises(ValueError):
        fetch.fetch_dataset("internal", "missing", 2020, 2024)


def test_excel_workbook_is_read_as_records():
    records = data.read_excel(sources.INTERNAL[0]["file"])
    assert len(records) == 21
    assert set(records[0]) == {"year", "sector", "vacancies", "placements"}
