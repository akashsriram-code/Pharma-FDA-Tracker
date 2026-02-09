"""
SEC EDGAR 8-K Scraper for PDUFA Dates
Scrapes SEC EDGAR for 8-K filings from biotech companies and extracts PDUFA announcements.

Primary Source: SEC EDGAR (https://data.sec.gov)
Data Type: 8-K Material Event Filings
API: Free, no API key required
"""

import requests
import json
import os
import re
from datetime import datetime, timedelta
import time

# Configuration
DATA_DIR = 'data'
DATA_JSON_FILE = os.path.join(DATA_DIR, 'data.json')
COMPANY_CIKS_FILE = os.path.join(DATA_DIR, 'company_ciks.json')

# SEC EDGAR API base URL
SEC_BASE_URL = "https://data.sec.gov"
SEC_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"

# User-Agent required by SEC (they block requests without it)
HEADERS = {
    'User-Agent': 'FDACatalystTracker contact@example.com',
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

# PDUFA-related keywords to search for in filings
PDUFA_KEYWORDS = [
    "PDUFA",
    "target action date",
    "FDA acceptance",
    "NDA acceptance",
    "BLA acceptance",
    "FDA has accepted",
    "FDA accepted",
    "complete response letter",
    "priority review",
    "standard review",
    "new drug application",
    "biologics license application"
]

# Date patterns to extract PDUFA dates from text
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


def get_company_filings(cik, filing_type="8-K", count=20):
    """Fetch recent filings for a company from SEC EDGAR."""
    # Pad CIK to 10 digits
    cik_padded = cik.zfill(10)
    url = f"{SEC_BASE_URL}/cgi-bin/browse-edgar?action=getcompany&CIK={cik_padded}&type={filing_type}&dateb=&owner=include&count={count}&output=atom"
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        if response.status_code != 200:
            return []
        
        # Parse the Atom feed for filing URLs
        from xml.etree import ElementTree as ET
        root = ET.fromstring(response.content)
        
        filings = []
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        
        for entry in root.findall('.//atom:entry', ns):
            title = entry.find('atom:title', ns)
            link = entry.find('atom:link', ns)
            updated = entry.find('atom:updated', ns)
            
            if title is not None and link is not None:
                filings.append({
                    'title': title.text,
                    'link': link.get('href'),
                    'date': updated.text[:10] if updated is not None else ''
                })
        
        return filings
        
    except Exception as e:
        print(f"  Error fetching filings for CIK {cik}: {e}")
        return []


def get_filing_text(filing_url):
    """Fetch the full text of an 8-K filing."""
    try:
        response = requests.get(filing_url, headers=HEADERS, timeout=15)
        if response.status_code != 200:
            return ""
        return response.text
    except Exception as e:
        return ""


def extract_pdufa_date(text):
    """Extract PDUFA target action date from filing text."""
    for pattern in DATE_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            date_str = match.group(1)
            
            # Try to parse the date into standard format
            for fmt in ['%B %d, %Y', '%B %d %Y', '%B, %Y', '%B %Y', '%Y-%m-%d']:
                try:
                    dt = datetime.strptime(date_str.replace(',', ''), fmt)
                    return dt.strftime('%Y-%m-%d')
                except:
                    continue
            
            # Handle quarterly dates (Q1 2026 -> 2026-03-31)
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
    """Search SEC EDGAR for PDUFA announcements in 8-K filings."""
    print("=" * 60)
    print("SEC EDGAR 8-K Scraper for PDUFA Dates")
    print("=" * 60)
    
    events = []
    
    for company_name, cik in BIOTECH_CIKS.items():
        print(f"\nSearching: {company_name} (CIK: {cik})...")
        
        filings = get_company_filings(cik, "8-K", count=10)
        print(f"  Found {len(filings)} recent 8-K filings")
        
        for filing in filings:
            # Only look at filings from the last year
            filing_date = filing.get('date', '')
            if filing_date:
                try:
                    fd = datetime.strptime(filing_date, '%Y-%m-%d')
                    if fd < datetime.now() - timedelta(days=365):
                        continue
                except:
                    pass
            
            # Get filing text
            filing_url = filing.get('link', '')
            if not filing_url:
                continue
                
            text = get_filing_text(filing_url)
            if not text:
                continue
            
            # Check for PDUFA content
            if has_pdufa_content(text):
                pdufa_date = extract_pdufa_date(text)
                
                if pdufa_date:
                    print(f"    ✓ Found PDUFA date: {pdufa_date}")
                    events.append({
                        'company': company_name,
                        'drug': 'Check Filing',
                        'type': 'PDUFA Date',
                        'date': pdufa_date,
                        'title': f"FDA Target Action Date - {filing.get('title', 'See Filing')}",
                        'link': filing_url,
                        'source': 'SEC EDGAR 8-K'
                    })
                else:
                    # Still capture the PDUFA mention even without extracted date
                    events.append({
                        'company': company_name,
                        'drug': 'Check Filing',
                        'type': 'FDA Announcement',
                        'date': filing_date,
                        'title': filing.get('title', 'FDA-Related Filing'),
                        'link': filing_url,
                        'source': 'SEC EDGAR 8-K'
                    })
        
        time.sleep(0.5)  # Be polite to SEC servers
    
    print(f"\n{'=' * 60}")
    print(f"Found {len(events)} PDUFA-related events from SEC EDGAR")
    print(f"{'=' * 60}")
    
    return events


def update_database(new_events):
    """Updates the JSON database with new events."""
    existing_data = []
    if os.path.exists(DATA_JSON_FILE):
        try:
            with open(DATA_JSON_FILE, 'r') as f:
                content = f.read()
                if content.strip():
                    existing_data = json.loads(content)
        except json.JSONDecodeError:
            pass
    
    existing_signatures = set()
    for item in existing_data:
        sig = (item.get('company'), item.get('date'), item.get('title', '')[:50])
        existing_signatures.add(sig)
    
    added_count = 0
    for event in new_events:
        # Filter out dates before 2024
        event_date = event.get('date', '')
        if event_date and event_date < '2024-01-01':
            continue
            
        sig = (event.get('company'), event.get('date'), event.get('title', '')[:50])
        if sig not in existing_signatures:
            existing_data.append(event)
            existing_signatures.add(sig)
            added_count += 1
    
    # Sort by date
    try:
        existing_data.sort(key=lambda x: x.get('date') or '9999-12-31')
    except:
        pass

    # Filter before 2024
    filtered_data = [e for e in existing_data if e.get('date', '') >= '2024-01-01']
    
    with open(DATA_JSON_FILE, 'w') as f:
        json.dump(filtered_data, f, indent=4)
    
    print(f"Database updated. Added {added_count} new events.")


def main():
    events = search_sec_filings()
    if events:
        update_database(events)
    print("\nDone!")


if __name__ == "__main__":
    main()
