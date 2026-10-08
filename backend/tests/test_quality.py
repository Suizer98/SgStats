"""Data quality validation and cleaning."""

import pandas as pd
import pytest

from app.gov import data, fetch, sources
from app.gov.data import normalize_any, quality_check


def frame(values: list[float | None], series: str = "A") -> pd.DataFrame:
    return pd.DataFrame(
        [{"period": str(2015 + i), "series": series, "measure": "Count", "value": v} for i, v in enumerate(values)]
    )


def test_duplicates_are_removed_and_reported():
    duplicated = pd.concat([frame([1.0, 2.0]), frame([1.0])])
    checked = quality_check(duplicated, ["period", "value"])
    assert checked["rows"] == 2
    assert checked["duplicates_removed"] == 1
    assert any("duplicate" in item for item in checked["checks"])


def test_missing_values_are_dropped_and_reported():
    checked = quality_check(frame([1.0, None, 3.0]), ["period", "value"])
    assert checked["rows"] == 2
    assert checked["nulls"]["value"] == 1
    assert any("no numeric value" in item for item in checked["checks"])


def test_missing_required_column_fails_validation():
    checked = quality_check(pd.DataFrame([{"period": "2020"}]), ["period", "value"])
    assert checked["ok"] is False
    assert checked["missing_columns"] == ["value"]


def test_outliers_are_flagged_not_removed():
    checked = quality_check(frame([10.0, 11.0, 10.5, 9.8, 10.2, 250.0]), ["period", "value"])
    assert checked["rows"] == 6
    assert checked["outliers"] == [{"series": "A", "period": "2020", "value": 250.0}]
    assert quality_check(frame([5.0] * 6))["outliers"] == []


def test_coverage_and_counts_are_reported():
    checked = quality_check(pd.concat([frame([1.0, 2.0, 3.0]), frame([4.0, 5.0, 6.0], "B")]))
    assert checked["series"] == 2
    assert checked["periods"] == 3
    assert checked["coverage"] == "2015 to 2017"


def test_messy_values_are_cleaned_during_normalisation():
    records = [
        {"_id": 1, "year": "2020", "count": "1,200"},
        {"_id": 2, "year": "2021", "count": "na"},
        {"_id": 3, "year": "2022", "count": "-"},
        {"_id": 4, "year": "2023", "count": " 1,500 "},
    ]
    rows = normalize_any(records)
    assert [(row["period"], row["value"]) for row in rows] == [("2020", 1200.0), ("2023", 1500.0)]


def test_package_reports_cleaning_steps():
    rows = [
        {"period": "2019", "grain": "year", "series": "A", "measure": "Count", "value": 1.0},
        {"period": "2020", "grain": "year", "series": "A", "measure": "Count", "value": 2.0},
        {"period": "2020", "grain": "year", "series": "A", "measure": "Count", "value": 4.0},
    ]
    dataset = fetch.package({"title": "T"}, rows, 2020, 2024, "live", source_records=5)
    checks = " ".join(dataset["quality"]["checks"])
    assert "Parsed 5 source records into 3" in checks
    assert "dropped 1" in checks
    assert "Averaged 2 records into 1" in checks
    assert dataset["records"] == [{"period": "2020", "series": "A", "measure": "Count", "value": 3.0}]


def test_stale_dataset_gets_coverage_note():
    rows = [{"period": f"{year}-12", "grain": "month", "series": "EP", "measure": "Count", "value": 1.0} for year in (2020, 2021, 2022)]
    kept, grain, note = data.finish_rows(rows, 2020, 2026)
    assert len(kept) == 3
    assert note == "Latest published period is 2022-12, earlier than the requested 2026."
    assert data.finish_rows(rows, 2020, 2023)[2] == ""


def test_unusable_table_is_rejected():
    with pytest.raises(ValueError):
        fetch.package({"title": "T"}, [], 2020, 2024, "live")


@pytest.mark.parametrize("item", sources.PINNED, ids=lambda item: item["id"])
def test_every_snapshot_loads_with_quality_report(item):
    result = data.load_snapshot(item["snapshot"], 2020, 2024)
    assert result["quality"]["ok"] is True
    assert result["quality"]["checks"][0].startswith("Parsed")
    assert {row["period"][:4] for row in result["records"]} >= {"2020", "2024"}


def test_csv_snapshot_is_wide_table():
    result = data.load_snapshot(sources.PINNED[1]["snapshot"], 2020, 2024)
    assert result["format"] == "csv"
    ict = {row["period"]: row["value"] for row in result["records"] if row["series"] == "Information & Communications"}
    assert (ict["2020"], ict["2024"]) == (111.4, 139.1)


def test_indented_sections_keep_breakdowns_apart():
    records = [
        {"DataSeries": "All Industries", "2020": 100, "2021": 110},
        {"DataSeries": "    Services", "2020": 60, "2021": 66},
        {"DataSeries": "Aged 15 - 19", "2020": 5, "2021": 6},
        {"DataSeries": "    Services", "2020": 3, "2021": 4},
    ]
    series = {(row["series"], row["period"]): row["value"] for row in normalize_any(records)}
    assert series[("Services", "2020")] == 60
    assert series[("Services (Aged 15 - 19)", "2020")] == 3
