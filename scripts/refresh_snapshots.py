"""Capture real records for the pinned datasets so the offline fallback serves official figures.

Run from backend/: PYTHONPATH=. uv run python ../scripts/refresh_snapshots.py
"""

import json
from datetime import date

import pandas as pd

from app.core.settings import DATA_DIR
from app.gov import fetch, sources


def main() -> None:
    retrieved = date.today().isoformat()
    for item in sources.PINNED:
        path = DATA_DIR / item["snapshot"]
        path.parent.mkdir(parents=True, exist_ok=True)
        if item["provider"] == "singstat":
            table = fetch.get_singstat(item["id"])
            payload = {"provider": "singstat", "dataset_id": item["id"], "title": table.get("title"), "retrieved": retrieved, "records": table["row"]}
            path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
            count = len(table["row"])
        else:
            records = fetch.get_datagov(item["id"])["records"]
            if path.suffix == ".csv":
                pd.DataFrame(records).drop(columns=["_id"], errors="ignore").to_csv(path, index=False)
            else:
                payload = {"provider": "datagov", "dataset_id": item["id"], "retrieved": retrieved, "records": records}
                path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
            count = len(records)
        print(f"{item['id']}: {count} records -> {path}")


if __name__ == "__main__":
    main()
