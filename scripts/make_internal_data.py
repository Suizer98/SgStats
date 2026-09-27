"""Generate the mock internal Excel workbook. The figures are invented for the demo, not official."""

from pathlib import Path

import pandas as pd

OUTPUT = Path(__file__).resolve().parents[1] / "backend" / "data" / "internal" / "sector_hiring.xlsx"

ROWS = {
    "Information and Communications": [(4200, 3100), (3900, 2600), (5600, 4300), (6100, 4700), (5200, 3900), (5400, 4200), (5800, 4500)],
    "Financial and Insurance Services": [(3100, 2400), (2900, 2100), (3500, 2800), (3800, 3000), (3600, 2900), (3700, 3000), (3900, 3100)],
    "Manufacturing": [(2800, 2000), (2300, 1500), (2600, 1900), (2900, 2100), (2700, 2000), (2750, 2050), (2800, 2100)],
}


def main() -> None:
    records = []
    for sector, values in ROWS.items():
        for offset, (vacancies, placements) in enumerate(values):
            records.append({"year": 2019 + offset, "sector": sector, "vacancies": vacancies, "placements": placements})
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(records).to_excel(OUTPUT, index=False, sheet_name="hiring")
    print(f"Wrote {len(records)} rows to {OUTPUT}")


if __name__ == "__main__":
    main()
