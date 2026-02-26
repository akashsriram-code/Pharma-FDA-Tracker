"""
OpenFDA Drug Label Scraper
Queries OpenFDA for recent major label changes and boxed warnings.
Compares current vs. previous label versions from the DailyMed archive
to produce per-section text diffs.

Primary Source: OpenFDA (https://open.fda.gov/apis/drug/label/)
DailyMed Archive: https://dailymed.nlm.nih.gov/dailymed/services/v2/
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
import io
import zipfile
import difflib
import html as html_module
import xml.etree.ElementTree as ET
import sys

# Suppress SSL warnings for local proxy issues
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configuration
DATA_DIR = 'data'
COMPANIES_FILE = os.path.join(DATA_DIR, 'NASDAQ Biotechnology (NBI).csv')
DATA_JSON_FILE = os.path.join(DATA_DIR, 'data.json')

OPENFDA_API_URL = "https://api.fda.gov/drug/label.json"
DAILYMED_API_BASE = "https://dailymed.nlm.nih.gov/dailymed"

HEADERS = {
    'User-Agent': 'FDACatalystTracker/1.0',
    'Accept': 'application/json'
}

# LOINC codes for common label sections in SPL XML
LOINC_SECTION_MAP = {
    "34067-9":  "Indications and Usage",
    "34068-7":  "Indications and Usage",
    "43678-2":  "Dosage and Administration",
    "43685-7":  "Warnings and Precautions",
    "34071-1":  "Warnings",
    "34073-7":  "Drug Interactions",
    "34084-4":  "Adverse Reactions",
    "34070-3":  "Contraindications",
    "34076-0":  "Boxed Warning",
    "42228-7":  "Use in Specific Populations",
    "34069-5":  "How Supplied/Storage and Handling",
    "34074-5":  "Description",
    "34090-1":  "Clinical Pharmacology",
    "34092-7":  "Clinical Studies",
    "43684-0":  "Use in Specific Populations",
    "34081-0":  "Pediatric Use",
    "34083-6":  "Carcinogenesis and Mutagenesis and Impairment of Fertility",
    "42229-5":  "SPL Unclassified Section",
}

# ------------------------------------------------------------------
# DailyMed Archive Functions
# ------------------------------------------------------------------

def get_label_history(set_id):
    """Fetch the version history for a label from DailyMed.
    
    Returns list of {spl_version, published_date} sorted newest first,
    or empty list on failure.
    """
    url = f"{DAILYMED_API_BASE}/services/v2/spls/{set_id}/history.json"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15, verify=False)
        if resp.status_code != 200:
            return []
        data = resp.json()
        history = data.get('data', {}).get('history', [])
        # Already sorted newest-first from the API, but ensure it
        history.sort(key=lambda h: h.get('spl_version', 0), reverse=True)
        return history
    except Exception as e:
        print(f"  [DailyMed] Error fetching history for {set_id}: {e}")
        return []


def download_spl_zip(set_id, version=None):
    """Download an SPL ZIP from DailyMed and return the XML string.
    
    If version is None, downloads the latest version.
    Returns the XML string or None on failure.
    """
    if version is not None:
        url = f"{DAILYMED_API_BASE}/getFile.cfm?type=zip&setid={set_id}&version={version}"
    else:
        url = f"{DAILYMED_API_BASE}/downloadzipfile.cfm?setId={set_id}"
    
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30, verify=False)
        if resp.status_code != 200:
            return None
        
        # Extract XML from the ZIP in memory
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            xml_files = [n for n in zf.namelist() if n.lower().endswith('.xml')]
            if not xml_files:
                return None
            # Usually there is exactly one XML file
            xml_content = zf.read(xml_files[0])
            return xml_content.decode('utf-8', errors='replace')
    except Exception as e:
        print(f"  [DailyMed] Error downloading ZIP for {set_id} v{version}: {e}")
        return None


def _get_text_recursive(element):
    """Recursively extract all text from an XML element, stripping tags."""
    parts = []
    if element.text:
        parts.append(element.text.strip())
    for child in element:
        parts.append(_get_text_recursive(child))
        if child.tail:
            parts.append(child.tail.strip())
    return " ".join(p for p in parts if p)


def _normalize_section_name(raw_name):
    """Normalize SPL section names for consistent matching.
    
    Converts 'INDICATIONS & USAGE SECTION' -> 'Indications and Usage'
    """
    if not raw_name:
        return raw_name
    
    # Common transformations
    name = raw_name.strip()
    # Remove trailing 'SECTION' suffix
    name = re.sub(r'\s+SECTION\s*$', '', name, flags=re.IGNORECASE)
    # Replace & with 'and'
    name = name.replace('&', 'and')
    # Convert to title case
    name = name.strip().title()
    # Fix common words that shouldn't be capitalized
    for word in ['And', 'Or', 'Of', 'In', 'For', 'The', 'To', 'A']:
        name = re.sub(r'\b' + word + r'\b', word.lower(), name)
    # But capitalize the first word
    if name:
        name = name[0].upper() + name[1:]
    
    return name


def extract_sections_from_spl(xml_string):
    """Parse SPL XML and extract text from major label sections.
    
    Returns dict: { "Normalized Section Name": "full text..." }
    
    Each section only gets its direct <text> content — subsections are
    captured independently on their own iteration pass, avoiding duplication.
    """
    # Sections that are not useful for diffing
    SKIP_SECTIONS = {
        "Spl Unclassified", "Spl Product Data Elements",
        "Recent Major Changes", "Package Label.Principal Display Panel",
    }
    
    sections = {}
    if not xml_string:
        return sections
    
    try:
        root = ET.fromstring(xml_string)
        ns = {'hl7': 'urn:hl7-org:v3'}
        
        for section_el in root.iter('{urn:hl7-org:v3}section'):
            section_name = None
            
            # Strategy 1: Try <code> element (LOINC code or displayName)
            code_el = section_el.find('hl7:code', ns)
            if code_el is not None:
                loinc_code = code_el.get('code', '')
                display_name = code_el.get('displayName', '')
                
                section_name = LOINC_SECTION_MAP.get(loinc_code)
                if not section_name:
                    section_name = _normalize_section_name(display_name)
            
            # Strategy 2: Try <title> element (common for subsections)
            if not section_name:
                title_el = section_el.find('hl7:title', ns)
                if title_el is not None and title_el.text:
                    section_name = _normalize_section_name(title_el.text)
            
            if not section_name:
                continue
            
            # Skip meta/container sections
            if section_name in SKIP_SECTIONS:
                continue
            
            # Only use DIRECT <text> child — subsections are captured separately
            text_el = section_el.find('hl7:text', ns)
            if text_el is None:
                continue
            
            raw_text = _get_text_recursive(text_el)
            raw_text = re.sub(r'\s+', ' ', raw_text).strip()
            
            if not raw_text:
                continue
            
            if section_name in sections:
                sections[section_name] += "\n" + raw_text
            else:
                sections[section_name] = raw_text
    except ET.ParseError as e:
        print(f"  [SPL] XML parse error: {e}")
    except Exception as e:
        print(f"  [SPL] Error extracting sections: {e}")
    
    return sections


def _fuzzy_find_section(target_name, sections_dict):
    """Find the best matching section name in sections_dict for target_name.
    
    Uses case-insensitive, simplified key matching.
    """
    # Exact match first
    if target_name in sections_dict:
        return target_name
    
    target_lower = target_name.lower().strip()
    # Remove common suffixes/words for more flexible matching
    target_simple = re.sub(r'\s+(section|and|of)\s*', ' ', target_lower).strip()
    target_words = set(target_simple.split())
    
    best_match = None
    best_score = 0
    
    for key in sections_dict:
        key_lower = key.lower().strip()
        key_simple = re.sub(r'\s+(section|and|of)\s*', ' ', key_lower).strip()
        key_words = set(key_simple.split())
        
        # Try exact lowercase match
        if key_lower == target_lower:
            return key
        
        # Try if target is contained in key or vice versa
        if target_lower in key_lower or key_lower in target_lower:
            return key
        
        # Word overlap score
        overlap = len(target_words & key_words)
        if overlap > best_score and overlap >= min(2, len(target_words)):
            best_score = overlap
            best_match = key
    
    return best_match


def compute_section_diffs(current_sections, previous_sections, changed_section_names=None):
    """Compute text diffs between current and previous label sections.
    
    Uses fuzzy matching to find section names across versions.
    """
    results = []
    
    if changed_section_names:
        sections_to_check = changed_section_names
    else:
        sections_to_check = set(list(current_sections.keys()) + list(previous_sections.keys()))
    
    for section_name in sections_to_check:
        # Fuzzy-find the actual keys in both dicts
        current_key = _fuzzy_find_section(section_name, current_sections)
        previous_key = _fuzzy_find_section(section_name, previous_sections)
        
        current_text = current_sections.get(current_key, "") if current_key else ""
        previous_text = previous_sections.get(previous_key, "") if previous_key else ""
        
        if not current_text and not previous_text:
            continue
        
        def split_into_chunks(text):
            """Split text into sentence-like chunks for diffing."""
            sentences = re.split(r'(?<=[.!?])\s+', text)
            return [s.strip() for s in sentences if s.strip()]
        
        current_lines = split_into_chunks(current_text)
        previous_lines = split_into_chunks(previous_text)
        
        diff = list(difflib.unified_diff(
            previous_lines,
            current_lines,
            lineterm='',
            n=2
        ))
        
        diff_lines = []
        added_count = 0
        removed_count = 0
        
        if diff:
            for line in diff:
                if line.startswith('+++') or line.startswith('---') or line.startswith('@@'):
                    continue
                elif line.startswith('+'):
                    diff_lines.append({"type": "added", "text": line[1:]})
                    added_count += 1
                elif line.startswith('-'):
                    diff_lines.append({"type": "removed", "text": line[1:]})
                    removed_count += 1
                else:
                    diff_lines.append({"type": "context", "text": line.lstrip()})
        
        has_changes = added_count > 0 or removed_count > 0
        
        if not has_changes and current_text != previous_text:
            has_changes = True
            diff_lines = [
                {"type": "context", "text": "(Minor formatting/whitespace changes detected)"}
            ]
        
        if has_changes:
            results.append({
                "section": section_name,
                "has_changes": has_changes,
                "added_count": added_count,
                "removed_count": removed_count,
                "diff_lines": diff_lines
            })
    
    return results


def fetch_label_diff(set_id, changed_section_names=None):
    """Full pipeline: fetch history, download both versions, compute diff.
    
    Returns a diff_data dict or None if diff computation fails.
    """
    if not set_id:
        return None
    
    # 1. Get version history
    history = get_label_history(set_id)
    if len(history) < 2:
        # Only one version exists — nothing to diff against
        return None
    
    current_version = history[0]
    previous_version = history[1]
    
    current_ver_num = current_version.get('spl_version')
    previous_ver_num = previous_version.get('spl_version')
    
    print(f"    Comparing v{current_ver_num} vs v{previous_ver_num}...")
    
    # 2. Download both versions' SPL XML
    current_xml = download_spl_zip(set_id, version=current_ver_num)
    time.sleep(0.5)  # Rate limiting for DailyMed
    previous_xml = download_spl_zip(set_id, version=previous_ver_num)
    time.sleep(0.5)
    
    if not current_xml or not previous_xml:
        print(f"    Could not download one or both versions.")
        return None
    
    # 3. Extract sections
    current_sections = extract_sections_from_spl(current_xml)
    previous_sections = extract_sections_from_spl(previous_xml)
    
    if not current_sections and not previous_sections:
        return None
    
    # 4. Compute diffs across ALL sections (not just changed_section_names,
    #    because OpenFDA names refer to parent sections while actual changes
    #    are often in more granular subsections)
    section_diffs = compute_section_diffs(current_sections, previous_sections)
    
    if not section_diffs:
        return None
    
    return {
        "current_version": current_ver_num,
        "previous_version": previous_ver_num,
        "current_date": current_version.get('published_date', ''),
        "previous_date": previous_version.get('published_date', ''),
        "sections": section_diffs
    }


# ------------------------------------------------------------------
# Core Scraper Functions
# ------------------------------------------------------------------

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

def get_company_labels(company_name):
    """Fetch label data for a company with recent major changes."""
    url = f"{OPENFDA_API_URL}?search=openfda.manufacturer_name:\"{company_name}\"+AND+_exists_:recent_major_changes&limit=5"
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=10, verify=False)
        if response.status_code != 200:
            return []
        
        data = response.json()
        if 'results' in data and data['results']:
            return data['results']
    except Exception as e:
        pass
    
    return []

def extract_label_events(label_data, company, brand_name, compute_diff=True):
    """Extract events from label data, optionally computing DailyMed diffs."""
    events = []
    
    # Get Link & Set ID
    set_id_list = label_data.get('openfda', {}).get('spl_set_id', [])
    set_id = set_id_list[0] if isinstance(set_id_list, list) and set_id_list else None
    
    if set_id:
        link = f"https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid={set_id}"
    else:
        link = f"https://accessdata.fda.gov/scripts/cder/daf/index.cfm?event=BasicSearch.process&SearchTerm={brand_name}"

    # 1. Recent Major Changes
    if 'recent_major_changes' in label_data:
        changes = label_data['recent_major_changes']
        if isinstance(changes, list):
            change_text = " ".join(changes)
        else:
            change_text = str(changes)
        
        pattern = r"([A-Z][a-zA-Z\s]+)\s*\(\s*([0-9.,\s]+)\s*\)\s*(\d{1,2}/\d{4})"
        matches = re.findall(pattern, change_text)
        
        full_details = []
        final_date = "TBD"
        changed_section_names = []

        if matches:
            dates = [m[2] for m in matches]
            try:
                date_objs = [datetime.strptime(d, '%m/%Y') for d in dates]
                final_date = max(date_objs).strftime('%Y-%m-%d')
                final_date = final_date[:8] + "01" 
            except:
                final_date = datetime.now().strftime('%Y-%m-%d')

            section_map = {
                "Indications and Usage": "indications_and_usage",
                "Dosage and Administration": "dosage_and_administration",
                "Warnings and Precautions": "warnings_and_precautions",
                "Boxed Warning": "boxed_warning",
                "Contraindications": "contraindications",
                "Adverse Reactions": "adverse_reactions",
                "Drug Interactions": "drug_interactions",
                "Use in Specific Populations": "use_in_specific_populations"
            }

            for m in matches:
                section_name = m[0].strip()
                subsection = m[1].strip()
                date_str = m[2].strip()
                
                changed_section_names.append(section_name)
                
                key = section_map.get(section_name)
                if not key:
                    key = section_name.lower().replace(" ", "_")
                
                content = "Content not available in API response."
                if key and key in label_data:
                    raw_content = label_data[key]
                    if isinstance(raw_content, list):
                        content = "\n".join(raw_content)
                    else:
                        content = str(raw_content)
                    if len(content) > 5000:
                        content = content[:5000] + "... (truncated)"

                full_details.append({
                    "section": section_name,
                    "subsection": subsection,
                    "date": date_str,
                    "content": content
                })
        else:
            try:
                date_match = re.search(r"(\d{1,2}/\d{4})", change_text)
                if date_match:
                    dt = datetime.strptime(date_match.group(1), '%m/%Y')
                    final_date = dt.strftime('%Y-%m-01')
                else:
                    final_date = datetime.now().strftime('%Y-%m-%d')
            except:
                final_date = datetime.now().strftime('%Y-%m-%d')

            full_details.append({
                "section": "General Update",
                "subsection": "",
                "date": final_date,
                "content": change_text
            })

        # Check if date is recent
        try:
             dt = datetime.strptime(final_date, '%Y-%m-%d')
             if dt > datetime.now() - timedelta(days=730):
                details_json = json.dumps(full_details)
                
                event = {
                    'company': company,
                    'drug': brand_name,
                    'type': 'Label Update',
                    'date': final_date,
                    'title': f"Label Update: {change_text[:100]}...",
                    'details': details_json,
                    'link': link,
                    'source': 'OpenFDA'
                }
                
                # Compute DailyMed archive diff if requested
                if compute_diff and set_id:
                    try:
                        diff_data = fetch_label_diff(
                            set_id,
                            changed_section_names=changed_section_names if changed_section_names else None
                        )
                        if diff_data:
                            event['diff_data'] = diff_data
                    except Exception as e:
                        print(f"  [Diff] Error computing diff for {brand_name}: {e}")
                
                events.append(event)
        except Exception as e:
            print(f"Error processing date/event for {brand_name}: {e}")

    return events

def fetch_drug_shortages():
    """Download OpenFDA Drug Shortages JSON and map to events."""
    print("\nFetching Drug Shortages from OpenFDA...")
    url = "https://download.open.fda.gov/drug/shortages/drug-shortages-0001-of-0001.json.zip"
    events = []
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        z = zipfile.ZipFile(io.BytesIO(r.content))
        data = json.loads(z.read(z.namelist()[0]))
        
        results = data.get('results', [])
        for item in results:
            if item.get('status') == 'Current':
                company = item.get('company_name', 'Unknown')
                generic = item.get('generic_name', 'Unknown Drug')
                date_str = item.get('initial_posting_date', datetime.now().strftime('%m/%d/%Y'))
                
                # Try to parse MM/DD/YYYY to YYYY-MM-DD
                try:
                    dt = datetime.strptime(date_str, '%m/%d/%Y')
                    final_date = dt.strftime('%Y-%m-%d')
                except ValueError:
                    final_date = datetime.now().strftime('%Y-%m-%d')
                
                reason = item.get('shortage_reason', 'Not specified')
                status = item.get('status')
                
                events.append({
                    'company': company,
                    'drug': generic,
                    'type': 'Drug Shortage',
                    'date': final_date,
                    'title': f"Current Shortage: {generic}",
                    'details': f"Reason: {reason}",
                    'link': "https://www.accessdata.fda.gov/scripts/drugshortages/default.cfm",
                    'source': 'OpenFDA Shortages'
                })
        print(f"  -> Found {len(events)} current drug shortages.")
    except Exception as e:
        print(f"  -> Error fetching drug shortages: {e}")
    
    return events

def run_scraper(compute_diff=True):
    print("=" * 60)
    print("OpenFDA Label Scraper - All Companies")
    if compute_diff:
        print("  (DailyMed diff enabled — this may take longer)")
    else:
        print("  (DailyMed diff disabled — fast mode)")
    print("=" * 60)
    
    companies = load_companies()
    print(f"Loaded {len(companies)} companies to check.")
    
    all_events = []
    
    for i, company in enumerate(companies):
        if i % 10 == 0:
            print(f"Progress: [{i}/{len(companies)}] companies checked...")
            
        labels = get_company_labels(company)
        if labels:
            for label in labels:
                brand_name = "Unknown Drug"
                if 'openfda' in label and 'brand_name' in label['openfda']:
                    brand_name = label['openfda']['brand_name'][0]
                
                events = extract_label_events(label, company, brand_name, compute_diff=compute_diff)
                if events:
                    all_events.extend(events)
        
        time.sleep(0.05)
        
    print(f"\nFound {len(all_events)} total label updates.")
    
    # Also fetch current drug shortages
    shortage_events = fetch_drug_shortages()
    all_events.extend(shortage_events)
    print(f"Total events (including shortages): {len(all_events)}")
    
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
    
    existing_signatures = {}
    for i, item in enumerate(existing_data):
        sig = (item.get('company'), item.get('date'), item.get('title', '')[:50])
        existing_signatures[sig] = i
    
    added_count = 0
    updated_count = 0
    
    for event in new_events:
        sig = (event.get('company'), event.get('date'), event.get('title', '')[:50])
        
        if sig in existing_signatures:
            idx = existing_signatures[sig]
            old_event = existing_data[idx]
            # Update if old data is missing details or diff_data
            needs_update = (
                ('details' not in old_event and 'details' in event) or
                ('diff_data' not in old_event and 'diff_data' in event)
            )
            if needs_update:
                existing_data[idx] = event
                updated_count += 1
        else:
            existing_data.append(event)
            added_count += 1
            
    try:
        existing_data.sort(key=lambda x: x.get('date') or '9999-12-31')
    except:
        pass

    filtered_data = [
        e for e in existing_data 
        if e.get('date', '') >= '2024-01-01' or e.get('type') == 'Drug Shortage'
    ]
    
    with open(DATA_JSON_FILE, 'w') as f:
        json.dump(filtered_data, f, indent=4)
        
    print(f"Database updated. Added {added_count} new, Updated {updated_count} existing label events.")

if __name__ == "__main__":
    skip_diff = '--skip-diff' in sys.argv
    compute_diff = not skip_diff
    
    events = run_scraper(compute_diff=compute_diff)
    if events:
        update_database(events)
