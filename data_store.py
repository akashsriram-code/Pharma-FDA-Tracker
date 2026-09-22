"""
Shared data-store utilities for the Pharma-FDA-Tracker scrapers.

Centralizes the dedup / date-cutoff / sort / write logic that was
previously copy-pasted (with drift) across tracker.py, sec_edgar_scraper.py,
clinicaltrials_scraper.py, and label_scraper.py. That drift had a real
consequence: only tracker.py's copy exempted 'Drug Shortage' events from
the historical date cutoff, and each copy left `type` casing untouched,
so the same event type ended up written to data.json as both
"PHASE3 Completion" and "Phase 3 Completion" depending on which script
wrote it.
"""

import json
import os

DATA_DIR = 'data'
DATA_JSON_FILE = os.path.join(DATA_DIR, 'data.json')

# Event types that represent a *current status* rather than a dated
# catalyst, so the historical date cutoff below doesn't apply to them.
EXEMPT_TYPES = {'Drug Shortage'}

# Earliest date we keep in the feed; anything older is stale and no longer
# an actionable catalyst.
DATE_CUTOFF = '2024-01-01'

# Known type-casing/spelling variants seen in the wild -> canonical form.
TYPE_NORMALIZATION = {
    'phase3 completion': 'PHASE3 Completion',
    'phase 3 completion': 'PHASE3 Completion',
    'phase4 completion': 'PHASE4 Completion',
    'phase 4 completion': 'PHASE4 Completion',
    'phase1 completion': 'PHASE1 Completion',
    'phase 1 completion': 'PHASE1 Completion',
    'phase2 completion': 'PHASE2 Completion',
    'phase 2 completion': 'PHASE2 Completion',
}


def normalize_type(event_type):
    """Normalize known type-casing variants; leave unrecognized types untouched."""
    if not event_type:
        return event_type
    return TYPE_NORMALIZATION.get(event_type.strip().lower(), event_type)


def load_existing(path=DATA_JSON_FILE):
    """Load the existing event list, tolerating a missing or corrupt file."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, 'r') as f:
            content = f.read()
            if content.strip():
                return json.loads(content)
    except json.JSONDecodeError:
        pass
    return []


def _signature(item):
    return (item.get('company'), item.get('date'), item.get('title', '')[:50])


def update_database(new_events, path=DATA_JSON_FILE, date_cutoff=DATE_CUTOFF,
                     exempt_types=EXEMPT_TYPES, allow_update=False):
    """
    Merge new_events into the JSON database at `path`.

    - Dedupes on (company, date, title[:50]).
    - Drops events dated before `date_cutoff`, except events whose `type`
      is in `exempt_types` (e.g. Drug Shortage, which represents a current
      status rather than a dated catalyst).
    - Normalizes `type` casing via normalize_type() on both existing and
      incoming events, so old inconsistently-cased rows get cleaned up too.
    - Sorts the merged result by date ascending (undated events sort last).
    - If allow_update=True, an incoming event whose signature matches an
      existing one replaces it when the incoming event carries richer data
      (a 'details' or 'diff_data' field the existing row lacks) — used by
      label_scraper.py to backfill DailyMed diff data onto rows it already
      wrote in an earlier fast-mode run.

    Returns (added_count, updated_count, total_count).
    """
    existing_data = load_existing(path)

    for item in existing_data:
        item['type'] = normalize_type(item.get('type'))

    index_by_sig = {_signature(item): i for i, item in enumerate(existing_data)}

    added = 0
    updated = 0
    for event in new_events:
        event['type'] = normalize_type(event.get('type'))
        event_date = event.get('date', '')
        if event_date and event_date < date_cutoff and event.get('type') not in exempt_types:
            continue

        sig = _signature(event)
        if sig in index_by_sig:
            if allow_update:
                idx = index_by_sig[sig]
                old_event = existing_data[idx]
                needs_update = (
                    ('details' not in old_event and 'details' in event) or
                    ('diff_data' not in old_event and 'diff_data' in event)
                )
                if needs_update:
                    existing_data[idx] = event
                    updated += 1
            continue

        existing_data.append(event)
        index_by_sig[sig] = len(existing_data) - 1
        added += 1

    try:
        existing_data.sort(key=lambda x: x.get('date') or '9999-12-31')
    except Exception:
        pass

    filtered_data = [
        e for e in existing_data
        if e.get('date', '') >= date_cutoff or e.get('type') in exempt_types
    ]

    with open(path, 'w') as f:
        json.dump(filtered_data, f, indent=4)

    return added, updated, len(filtered_data)


def count_by_source(path=DATA_JSON_FILE):
    """Return {source: count} for the current database — used by the CI health check."""
    counts = {}
    for item in load_existing(path):
        source = item.get('source', 'Unknown')
        counts[source] = counts.get(source, 0) + 1
    return counts
