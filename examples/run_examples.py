"""Generate the example runs in this directory.

Each example is executed against the live service and saved as a request/response pair,
so the JSON committed here is genuine output rather than a hand-written illustration.

Usage (with the server running on :8000, or pass --base-url)::

    uv run python examples/run_examples.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

HERE = Path(__file__).parent

EXAMPLES: list[tuple[str, dict]] = [
    (
        "01_time_trend",
        {
            "query": "How has the number of trials for this drug changed per year since 2015?",
            "drug_name": "Pembrolizumab",
        },
    ),
    (
        "02_phase_distribution",
        {"query": "How are melanoma trials distributed across phases?"},
    ),
    (
        "03_drug_comparison",
        {"query": "Compare trial phases for pembrolizumab versus nivolumab"},
    ),
    (
        "04_geography",
        {"query": "Which countries have the most recruiting trials for type 2 diabetes?"},
    ),
    (
        "05_sponsor_drug_network",
        {"query": "Show a network of sponsors and the drugs they study for multiple myeloma"},
    ),
    (
        "06_drug_cooccurrence_network",
        {
            "query": "Which drugs are most often studied together in breast cancer "
            "combination trials?"
        },
    ),
    (
        "07_kpi_no_chart_needed",
        {"query": "How many trials is Pfizer running for lung cancer?"},
    ),
    (
        "08_enrollment_histogram",
        {
            "query": "What does the distribution of enrollment sizes look like for "
            "phase 3 oncology trials?"
        },
    ),
    (
        "09_scatter_enrollment_vs_duration",
        {
            "query": "Is there a relationship between enrollment size and trial duration "
            "for phase 3 diabetes trials?"
        },
    ),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--only", help="Run only examples whose name contains this string.")
    args = parser.parse_args()

    failures = 0
    for name, payload in EXAMPLES:
        if args.only and args.only not in name:
            continue
        print(f"→ {name}: {payload['query']}")
        try:
            response = httpx.post(
                f"{args.base_url}/api/v1/visualize", json=payload, timeout=300.0
            )
        except httpx.HTTPError as exc:
            print(f"  FAILED: {exc}")
            failures += 1
            continue

        body = response.json()
        (HERE / f"{name}.json").write_text(
            json.dumps({"request": payload, "response": body}, indent=2) + "\n"
        )

        if response.status_code != 200:
            print(f"  HTTP {response.status_code}: {body.get('message')}")
            failures += 1
            continue

        viz = body.get("visualization")
        if viz is None:
            print(f"  status={body['status']} (no visualization)")
        else:
            size = (
                f"{len(viz.get('nodes') or [])} nodes / {len(viz.get('edges') or [])} edges"
                if viz["type"] == "network_graph"
                else f"{len(viz['data'])} rows"
            )
            print(f"  {viz['type']}: {size} — {viz['title']}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
