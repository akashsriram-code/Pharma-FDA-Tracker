"""
OpenFDA Drug Label Scraper
Queries OpenFDA for recent major label changes and boxed warnings.

Primary Source: OpenFDA (https://open.fda.gov/apis/drug/label/)
Data Type: Label updates (Recent Major Changes, Boxed Warnings)
API: Free, no API key required
"""

import requests
import json
import os
import csv
from datetime import datetime, timedelta
import time
import urllib3
import re

# Suppress SSL warnings for local proxy issues
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configuration
DATA_DIR = 'data'
COMPANIES_FILE = os.path.join(DATA_DIR, 'NASDAQ Biotechnology (NBI).csv')
DATA_JSON_FILE = os.path.join(DATA_DIR, 'data.json')

OPENFDA_API_URL = "https://api.fda.gov/drug/label.json"

# Curated list of mapped drug names to ensure better search results
# (Company -> Brand Name)
KEY_DRUGS = {
    "Vertex": "Trikafta",
    "Gilead": "Biktarvy",
    "Amgen": "Enbrel",
    "Biogen": "Tecfidera",
    "Regeneron": "Eylea",
    "Moderna": "Spikevax",
    "BioNTech": "Comirnaty",
    "Alnylam": "Onpattro",
    "Sarepta": "Exondys 51",
    "BioMarin": "Vimizim",
    "Neurocrine": "Ingrezza",
    "Incyte": "Jakafi",
    "Ultragenyx": "Crysvita",
    "Jazz": "Xyrem",
    "Exelixis": "Cabometyx",
    "United Therapeutics": "Tyvaso",
    "AbbVie": "Humira",
    "Merck": "Keytruda",
    "Bristol Myers Squibb": "Opdivo",
    "Pfizer": "Ibrance",
    "Eli Lilly": "Trulicity",
    "Novo Nordisk": "Ozempic"
}

HEADERS = {
    'User-Agent': 'FDACatalystTracker/1.0',
    'Accept': 'application/json'
}

def load_companies():
    """Load company names from CSV."""
    companies = []
    if not os.path.exists(COMPANIES_FILE):
        return []
    
    try:
        with open(COMPANIES_FILE, mode='r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if 'Name' in row:
                    companies.append(row['Name'])
                elif 'Company Name' in row:
                    companies.append(row['Company Name'])
    except Exception as e:
        print(f"Error loading companies: {e}")
    return companies

def get_drug_label(brand_name):
    """Fetch label data from OpenFDA."""
    url = f"{OPENFDA_API_URL}?search=openfda.brand_name:\"{brand_name}\"&limit=1"
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=10, verify=False)
        if response.status_code != 200:
            return None
        
        data = response.json()
        if 'results' in data and data['results']:
            return data['results'][0]
    except Exception as e:
        print(f"Error fetching label for {brand_name}: {e}")
    
    return None

def extract_label_events(label_data, company, brand_name):
    """Extract events from label data."""
    events = []
    
    # Get Link
    set_id = label_data.get('openfda', {}).get('spl_set_id', [])
    if isinstance(set_id, list) and set_id:
        link = f"https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid={set_id[0]}"
    else:
        link = f"https://accessdata.fda.gov/scripts/cder/daf/index.cfm?event=BasicSearch.process&SearchTerm={brand_name}"

    # 1. Recent Major Changes
    if 'recent_major_changes' in label_data:
        changes = label_data['recent_major_changes']
        
        # Determine Date
        display_date = datetime.now().strftime('%Y-%m-%d')
        effective_time = label_data.get('effective_time', '')
        if effective_time and len(effective_time) >= 8:
             display_date = f"{effective_time[:4]}-{effective_time[4:6]}-{effective_time[6:8]}"
        
        # Try to find a date in the change text itself (e.g., "11/2025")
        # Format often: "Section Name (Number) -- MM/YYYY"
        latest_date_str = ""
        
        change_text = ""
        if isinstance(changes, list):
            change_text = " | ".join(changes)
            for change in changes:
                match = re.search(r'(\d{1,2})/(\d{4})', change)
                if match:
                    # Use the first date found as it's usually the effective date
                    latest_date_str = f"{match.group(2)}-{match.group(1).zfill(2)}-01"
                    break
        else:
             change_text = str(changes)
             match = re.search(r'(\d{1,2})/(\d{4})', change_text)
             if match:
                    latest_date_str = f"{match.group(2)}-{match.group(1).zfill(2)}-01"

        final_date = latest_date_str if latest_date_str else display_date

        # Only include if relatively recent (last 1 year) or in future
        try:
             dt = datetime.strptime(final_date, '%Y-%m-%d')
             if dt > datetime.now() - timedelta(days=365):
                # Store full info for the "Diff" view
                full_details = f"Section: {change.get('section', 'Unknown')}\n\n{change.get('notes', 'No details provided.')}"
                
                events.append({
                    'company': company,
                    'drug': brand_name,
                    'type': 'Label Update',
                    'date': final_date,
                    'title': f"Label Update: {change.get('section', 'General')}...",
                    'details': full_details, # New field for the UI expansion
                    'link': link,
                    'source': 'OpenFDA'
                })
        except:
             pass

    # 2. Boxed Warning (Generic event, maybe duplicate but useful)
    # Only adding if we don't have a label update, to avoid clutter? 
    # Or maybe just add it if it looks new? Hard to tell if new.
    # For now, let's focus on "Recent Major Changes" as that is strictly diff-like.

    return events

def run_scraper():
    print("=" * 60)
    print("OpenFDA Label Scraper")
    print("=" * 60)
    
    companies = load_companies()
    
    # Augment companies list with manual map
    search_list = []
    
    # 1. Add specific key drugs first
    for company, drug in KEY_DRUGS.items():
        search_list.append((company, drug))
    
    # 2. Heuristic for others: many biotechs are named after their lead drug or it's hard to guess.
    # For now, we rely on the manual KEY_DRUGS map as OpenFDA requires precise brand name queries.
    
    all_events = []
    
    for company, drug in search_list:
        print(f"Checking label for {drug} ({company})...")
        label = get_drug_label(drug)
        if label:
            events = extract_label_events(label, company, drug)
            if events:
                print(f"  Found {len(events)} updates.")
                all_events.extend(events)
            else:
                 print("  No recent changes.")
        else:
            print("  Label not found.")
        
        time.sleep(0.2)
        
    print(f"\nFound {len(all_events)} label updates.")
    return all_events

def update_database(new_events):
    start_time = datetime.now()
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
        sig = (event.get('company'), event.get('date'), event.get('title', '')[:50])
        if sig not in existing_signatures:
            existing_data.append(event)
            existing_signatures.add(sig)
            added_count += 1
            
    # Sort and save
    try:
        existing_data.sort(key=lambda x: x.get('date') or '9999-12-31')
    except:
        pass

    filtered_data = [e for e in existing_data if e.get('date', '') >= '2024-01-01']
    
    with open(DATA_JSON_FILE, 'w') as f:
        json.dump(filtered_data, f, indent=4)
        
    print(f"Database updated. Added {added_count} label events. (Saved to {DATA_JSON_FILE})")

if __name__ == "__main__":
    events = run_scraper()
    if events:
        update_database(events)
