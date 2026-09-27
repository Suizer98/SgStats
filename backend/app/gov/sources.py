from __future__ import annotations

PINNED = [
    {
        "provider": "datagov",
        "id": "d_7fa083fa9b837ef84c83caaba76601fd",
        "title": "Labour Market Statistics, Quarterly",
        "agency": "Singapore Department of Statistics",
        "snapshot": "snapshots/datagov_labour_market.json",
        "retrieved": "2026-09-26",
    },
    {
        "provider": "datagov",
        "id": "d_293a874aff064ea9408f31c4da9dd4bb",
        "title": "Employed Residents by Industry",
        "agency": "Ministry of Manpower",
        "snapshot": "snapshots/datagov_employed_residents.csv",
        "retrieved": "2026-09-26",
    },
    {
        "provider": "singstat",
        "id": "M015721",
        "title": "Gross Domestic Product At Current Prices, By Industry",
        "agency": "Singapore Department of Statistics",
        "snapshot": "snapshots/singstat_gdp_by_industry.json",
        "retrieved": "2026-09-26",
    },
]


INTERNAL = [
    {
        "provider": "internal",
        "id": "int_sector_hiring",
        "title": "Sector Hiring Programme Placements and Vacancies (mock internal database)",
        "agency": "Internal research database (mock)",
        "file": "internal/sector_hiring.xlsx",
        "keywords": "employment jobs hiring vacancies placements workforce technology ict finance manufacturing",
        "coverage_start": 2019,
        "coverage_end": 2025,
    },
]


def get_internal(dataset_id: str) -> dict | None:
    return next((item for item in INTERNAL if item["id"] == dataset_id), None)


def get_pinned(provider: str, dataset_id: str) -> dict | None:
    return next((item for item in PINNED if item["provider"] == provider and item["id"] == dataset_id), None)
