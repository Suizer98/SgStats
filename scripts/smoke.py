"""Run one query against a running stack and print what each agent did."""

import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8000"


def call(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def main() -> int:
    query = sys.argv[1] if len(sys.argv) > 1 else "Analyse employment trends in the technology sector from 2020-2024"
    start = time.time()
    job = call("POST", "/api/analyses", {"query": query})
    while True:
        row = call("GET", f"/api/analyses/{job['id']}")
        if row["status"] != "running":
            break
        time.sleep(2)
    print(f"status={row['status']} seconds={time.time() - start:.1f} error={row['error']}")
    for event in row["events"]:
        print(f"  [{event['agent']}/{event['step']}] {event['content'][:220]}")
    result = row["result"]
    if not result:
        return 1
    print("scope", result["scope"])
    for item in result["datasets"]:
        print("dataset", item["provider"], item["dataset_id"], item["title"], item["mode"], len(item["records"]), item["grain"])
    for chart in result["summary"]["charts"]:
        labels = [series["label"] for series in chart["series"]]
        print("chart", chart["title"], "|", chart["yLabel"], "by", chart["xLabel"], "|", labels, len(chart["data"]))
    for metric in result["summary"]["metrics"]:
        print("metric", metric)
    report = result["report"]
    print("provider", report["llm_provider"], "grounding", report["grounding"])
    print("title", report["title"])
    for line in report["insights"]:
        print(" -", line)
    print(report["briefing"][:800])
    return 0 if row["status"] == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
