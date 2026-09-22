"""
SEC EDGAR 8-K Scraper for PDUFA Dates
Scrapes SEC EDGAR for 8-K filings from biotech companies and extracts PDUFA announcements.

Primary Source: SEC EDGAR full-text search (https://efts.sec.gov/LATEST/search-index)
Data Type: 8-K Material Event Filings
API: Free, no API key required, but SEC requires an identifiable User-Agent.

NOTE: This previously used the legacy `cgi-bin/browse-edgar` endpoint on the
wrong host (data.sec.gov instead of www.sec.gov), which 404'd on every call,
and even after fixing the host it followed the filing *index* page instead
of the actual document -- so this scraper silently produced zero events for
its entire lifetime. It now uses EDGAR's full-text search API to find hits
directly, then builds the real document URL from the accession number and
filename so the PDUFA keyword/date regexes below actually have real text to
run against.
"""

import requests
import json
import os
import re
from datetime import datetime, timedelta
import time

import data_store

# Configuration
DATA_DIR = 'data'
DATA_JSON_FILE = os.path.join(DATA_DIR, 'data.json')

# SEC EDGAR full-text search API (covers filings from 2001 onward)
SEC_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
SEC_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"

# User-Agent required by SEC (they block/throttle requests without a real contact)
HEADERS = {
    'User-Agent': 'FDACatalystTracker/1.0 (akash.sriram@tr.com)',
    'Accept': 'application/json'
}

# Major biotech companies with their CIKs (Central Index Keys)
# This is a curated list of NBI companies with known PDUFA catalysts
BIOTECH_CIKS = {
    "Vertex Pharmaceuticals": "875320",
    "Gilead Sciences": "882095",
    "Amgen": "318154",
    "Biogen": "875045",
    "Regeneron Pharmaceuticals": "872589",
    "Moderna": "1682852",
    "BioNTech": "1776985",
    "Alnylam Pharmaceuticals": "1178670",
    "Sarepta Therapeutics": "873303",
    "BioMarin Pharmaceutical": "1048477",
    "Neurocrine Biosciences": "914475",
    "Incyte Corporation": "879169",
    "Ultragenyx Pharmaceutical": "1564408",
    "Jazz Pharmaceuticals": "1232524",
    "Exelixis": "939767",
    "Arrowhead Pharmaceuticals": "879407",
    "Ionis Pharmaceuticals": "874015",
    "Cytokinetics": "1061983",
    "Insmed": "1104506",
    "Halozyme Therapeutics": "1159036",
    "United Therapeutics": "1082554",
    "Vericel Corporation": "887359",
    "Immunocore Holdings": "1820721",
    "Arvinas": "1713154",
    "Revolution Medicines": "1534120",
    "Relay Therapeutics": "1727299",
    "Kymera Therapeutics": "1787792",
    "Arcellx": "1817410",
    "Legend Biotech": "1801338",
    "Karuna Therapeutics": "1705843",
    "Madrigal Pharmaceuticals": "1157601",
    "Ascendis Pharma": "1642545",
    "argenx": "1697532",
    "Apellis Pharmaceuticals": "1492422",
    "Krystal Biotech": "1714899",
    "Blueprint Medicines": "1597264",
    "Nuvalent": "1826826",
    "Structure Therapeutics": "1839167",
    "Vanda Pharmaceuticals": "1366868",
    "Eton Pharmaceuticals": "1730430",
    "Aquestive Therapeutics": "1398733",
    "MannKind Corporation": "899460",
    "Regenxbio": "1590877",
}

# Search phrases run against SEC's full-text index (one query per phrase per
# company). Kept short and high-signal to stay within SEC's rate limits
# (~10 requests/sec) across 42 companies.
SEARCH_PHRASES = [
    "PDUFA",
    "target action date",
    "complete response letter",
]

# Date patterns to extract PDUFA dates from filing text
DATE_PATTERNS = [
    # "PDUFA date of March 15, 2026"
    r'(?:PDUFA|target action|goal)\s*date\s*(?:of|is|:|set for)?\s*([A-Z][a-z]+\s+\d{1,2},?\s+\d{4})',
    # "target action date: March 2026"
    r'(?:target action|PDUFA)\s*date\s*(?:of|is|:|set for)?\s*([A-Z][a-z]+\s+\d{4})',
    # "decision by Q1 2026" - quarterly
    r'(?:decision|review|PDUFA)\s*(?:by|in|expected)\s*(Q[1-4]\s+\d{4})',
    # "2026-03-15" ISO format
    r'(?:PDUFA|target action|goal)\s*date[:\s]+(\d{4}-\d{2}-\d{2})',
]

# PDUFA-related keywords to confirm a filing is actually relevant (defense
# in depth on top of the full-text search match itself)
PDUFA_KEYWORDS = [
    "PDUFA", "target action date", "FDA acceptance", "NDA acceptance",
    "BLA acceptance", "FDA has accepted", "FDA accepted",
    "complete response letter", "priority review",
]


def search_filings(cik, phrase):
    """Full-text search SEC EDGAR for 8-K filings from `cik` containing `phrase`."""
    params = {
        "q": f'"{phrase}"',
        "forms": "8-K",
        "ciks": cik.zfill(10),
    }
    try:
        response = requests.get(SEC_SEARCH_URL, headers=HEADERS, params=params, timeout=20)
        if response.status_code != 200:
            return []
        return response.json().get('hits', {}).get('hits', [])
    except Exception as e:
        print(f"    Error searching CIK {cik} for '{phrase}': {e}")
        return []


def build_document_url(hit):
    """Build the real filing document URL from a full-text search hit."""
    source = hit.get('_source', {})
    ciks = source.get('ciks') or []
    adsh = source.get('adsh', '')
    filename = hit.get('_id', '').split(':')[-1]
    if not (ciks and adsh and filename):
        return None
    cik_no_zeros = str(int(ciks[0]))
    adsh_no_dashes = adsh.replace('-', '')
    return f"{SEC_ARCHIVES_BASE}/{cik_no_zeros}/{adsh_no_dashes}/{filename}"


def get_filing_text(filing_url):
    """Fetch the full text of an 8-K exhibit/document."""
    try:
        response = requests.get(filing_url, headers=HEADERS, timeout=15)
        if response.status_code != 200:
            return ""
        return response.text
    except Exception:
        return ""


def extract_pdufa_date(text):
    """Extract PDUFA target action date from filing text."""
    for pattern in DATE_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            date_str = match.group(1)

            for fmt in ['%B %d, %Y', '%B %d %Y', '%B, %Y', '%B %Y', '%Y-%m-%d']:
                try:
                    dt = datetime.strptime(date_str.replace(',', ''), fmt)
                    return dt.strftime('%Y-%m-%d')
                except ValueError:
                    continue

            # Handle quarterly dates (Q1 2026 -> 2026-03-28)
            q_match = re.match(r'Q([1-4])\s+(\d{4})', date_str)
            if q_match:
                quarter = int(q_match.group(1))
                year = int(q_match.group(2))
                month = quarter * 3
                return f"{year}-{month:02d}-28"

            return date_str  # Return raw if can't parse

    return None


def has_pdufa_content(text):
    """Check if filing contains PDUFA-related content."""
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in PDUFA_KEYWORDS)


def search_sec_filings():
    """Search SEC EDGAR full-text index for PDUFA announcements in 8-K filings."""
    print("=" * 60)
    print("SEC EDGAR 8-K Scraper for PDUFA Dates (full-text search)")
    print("=" * 60)

    events = []
    seen_doc_urls = set()
    cutoff = datetime.now() - timedelta(days=365)

    for company_name, cik in BIOTECH_CIKS.items():
        print(f"\nSearching: {company_name} (CIK: {cik})...")
        company_hit_count = 0

        for phrase in SEARCH_PHRASES:
            hits = search_filings(cik, phrase)
            company_hit_count += len(hits)

            for hit in hits:
                source = hit.get('_source', {})
                file_date_str = source.get('file_date', '')
                try:
                    if file_date_str and datetime.strptime(file_date_str, '%Y-%m-%d') < cutoff:
                        continue
                except ValueError:
                    pass

                doc_url = build_document_url(hit)
                if not doc_url or doc_url in seen_doc_urls:
                    continue
                seen_doc_urls.add(doc_url)

                text = get_filing_text(doc_url)
                if not text or not has_pdufa_content(text):
                    continue

                pdufa_date = extract_pdufa_date(text)
                display_name = (source.get('display_names') or [company_name])[0]

                if pdufa_date:
                    print(f"    ✓ Found PDUFA date: {pdufa_date}")
                    events.append({
                        'company': company_name,
                        'drug': 'Check Filing',
                        'type': 'PDUFA Date',
                        'date': pdufa_date,
                        'title': f"FDA Target Action Date - {display_name}",
                        'link': doc_url,
                        'source': 'SEC EDGAR 8-K'
                    })
                else:
                    events.append({
                        'company': company_name,
                        'drug': 'Check Filing',
                        'type': 'FDA Announcement',
                        'date': file_date_str,
                        'title': f"FDA-Related 8-K Filing - {display_name}",
                        'link': doc_url,
                        'source': 'SEC EDGAR 8-K'
                    })

            time.sleep(0.15)  # Be polite to SEC servers (stay under ~10 req/sec)

        print(f"  Found {company_hit_count} full-text search hits across {len(SEARCH_PHRASES)} phrases")
        time.sleep(0.3)

    print(f"\n{'=' * 60}")
    print(f"Found {len(events)} PDUFA-related events from SEC EDGAR")
    print(f"{'=' * 60}")

    return events


def main():
    events = search_sec_filings()
    added, updated, total = data_store.update_database(events, path=DATA_JSON_FILE)
    print(f"\nDatabase updated. Added {added} new events. Total events: {total}.")
    print("\nDone!")


if __name__ == "__main__":
    main()
