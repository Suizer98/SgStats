"""Run the README sample queries against a running stack and print a one-line verdict for each."""

import sys
import time

from smoke import call

QUERIES = [
    "Analyse employment trends in the technology sector from 2020-2024",
    "How has CPI inflation changed since 2019",
    "How many total EP workers in Singapore from 2020 to current",
    "HDB resale prices from 2015 to 2024",
    "Births and fertility trends in Singapore",
    "tell me something",
]


def run(query: str) -> bool:
    start = time.time()
    job = call("POST", "/api/analyses", {"query": query})
    while (row := call("GET", f"/api/analyses/{job['id']}"))["status"] == "running":
        time.sleep(2)
    seconds = time.time() - start
    result = row["result"]
    if not result:
        print(f"FAIL {seconds:5.1f}s  {query}: {row['error']}")
        return False
    report = result["report"]
    sources = ", ".join(f"{item['provider']}/{item['mode']}" for item in result["datasets"])
    print(
        f"{'OK  ' if report['grounding']['passed'] else 'WARN'} {seconds:5.1f}s  {query}\n"
        f"      sources: {sources}\n"
        f"      charts={len(result['summary']['charts'])} metrics={len(result['summary']['metrics'])} "
        f"correlations={len(result['summary'].get('correlations', []))} llm={report['llm_provider']} "
        f"notes={result['scope'].get('notes')}\n"
        f"      {report['title']}"
    )
    for metric in result["summary"]["metrics"][:2]:
        print(f"      metric: {metric['label']} = {metric['value']} ({metric['detail']})")
    return True


if __name__ == "__main__":
    queries = sys.argv[1:] or QUERIES
    results = [run(query) for query in queries]
    sys.exit(0 if all(results) else 1)
