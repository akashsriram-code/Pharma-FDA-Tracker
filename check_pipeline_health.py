"""
Pipeline health check for the daily scraper run.

Compares per-source event counts in data/data.json before and after the
scraper step ran, and tracks (in data/pipeline_health.json) how many
consecutive runs each "critical" source has gone without adding a single
new event. If a source that's expected to contribute regularly stays flat
for too many runs in a row, this fails loudly (non-zero exit code) so the
regression surfaces in the GitHub Actions run log within days -- instead of
silently persisting for a year, the way the sec_edgar_scraper.py host bug
and the label_scraper.py shortage-ordering bug did before this was added.

This intentionally does NOT block the "Commit and Push changes" step --
wire it in with `continue-on-error: true` in the workflow so a health-check
failure is visible without preventing that day's otherwise-good data from
being committed.

Usage:
    python check_pipeline_health.py <before.json> <after.json>
"""

import json
import os
import sys
from datetime import date

import data_store

HEALTH_FILE = os.path.join('data', 'pipeline_health.json')

# Sources expected to contribute new events reasonably regularly. A source
# NOT in this list (e.g. PRNewsWire, which is already known to be sparse)
# won't trip the alert just for being quiet.
CRITICAL_SOURCES = [
    'SEC EDGAR 8-K',
    'OpenFDA Shortages',
    'ClinicalTrials.gov',
    'openFDA API',
    'Federal Register',
    'openFDA Enforcement',
]

# Fail if a critical source has gone this many consecutive runs with zero
# new events added.
MAX_CONSECUTIVE_ZERO_RUNS = 10


def load_health_state():
    if not os.path.exists(HEALTH_FILE):
        return {}
    try:
        with open(HEALTH_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_health_state(state):
    os.makedirs(os.path.dirname(HEALTH_FILE), exist_ok=True)
    with open(HEALTH_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def main():
    if len(sys.argv) != 3:
        print("Usage: python check_pipeline_health.py <before.json> <after.json>")
        sys.exit(2)

    before_path, after_path = sys.argv[1], sys.argv[2]
    before_counts = data_store.count_by_source(before_path)
    after_counts = data_store.count_by_source(after_path)

    state = load_health_state()
    today = date.today().isoformat()

    failing = []
    print("=" * 60)
    print("Pipeline health check")
    print("=" * 60)

    for source in CRITICAL_SOURCES:
        before = before_counts.get(source, 0)
        after = after_counts.get(source, 0)
        delta = after - before
        entry = state.get(source, {'consecutive_zero_runs': 0, 'last_added': None})

        if delta > 0:
            entry['consecutive_zero_runs'] = 0
            entry['last_added'] = today
        else:
            entry['consecutive_zero_runs'] = entry.get('consecutive_zero_runs', 0) + 1

        state[source] = entry

        status = "OK" if entry['consecutive_zero_runs'] < MAX_CONSECUTIVE_ZERO_RUNS else "STALE"
        print(f"  [{status}] {source}: +{delta} this run, "
              f"{entry['consecutive_zero_runs']} consecutive runs with no new events "
              f"(last added: {entry['last_added']})")

        if entry['consecutive_zero_runs'] >= MAX_CONSECUTIVE_ZERO_RUNS:
            failing.append(source)

    save_health_state(state)

    if failing:
        print("\nFAILING: the following sources have contributed nothing for "
              f"{MAX_CONSECUTIVE_ZERO_RUNS}+ consecutive runs and likely need investigation:")
        for source in failing:
            print(f"  - {source}")
        sys.exit(1)

    print("\nAll critical sources healthy.")


if __name__ == "__main__":
    main()
