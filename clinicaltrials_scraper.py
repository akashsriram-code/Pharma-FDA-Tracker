"""
ClinicalTrials.gov Scraper for Late-Stage Trials
Queries ClinicalTrials.gov API for Phase 3/4 trials from biotech companies.

Primary Source: ClinicalTrials.gov (https://clinicaltrials.gov)
Data Type: Clinical trial completion dates and regulatory status
API: Free, no API key required
"""

import requests
import json
import os
import csv
from datetime import datetime, timedelta
import time

# Configuration
DATA_DIR = 'data'
COMPANIES_FILE = os.path.join(DATA_DIR, 'NASDAQ Biotechnology (NBI).csv')
DATA_JSON_FILE = os.path.join(DATA_DIR, 'data.json')

# ClinicalTrials.gov API v2
CT_API_URL = "https://clinicaltrials.gov/api/v2/studies"

HEADERS = {
    'User-Agent': 'FDACatalystTracker/1.0',
    'Accept': 'application/json'
}


def load_companies():
    """Load company names from CSV."""
    companies = []
    if not os.path.exists(COMPANIES_FILE):
        print(f"Error: {COMPANIES_FILE} not found.")
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


def search_clinical_trials(sponsor_name, phase="PHASE3"):
    """Search ClinicalTrials.gov for late-stage trials by sponsor."""
    
    params = {
        'query.spons': sponsor_name,
        'filter.overallStatus': 'ACTIVE_NOT_RECRUITING,COMPLETED',
        'filter.phase': phase,
        'pageSize': 20,
        'fields': 'NCTId,BriefTitle,OfficialTitle,OverallStatus,Phase,StartDate,PrimaryCompletionDate,CompletionDate,LeadSponsorName,Condition,InterventionName'
    }
    
    try:
        response = requests.get(CT_API_URL, params=params, headers=HEADERS, timeout=15)
        if response.status_code != 200:
            return []
        
        data = response.json()
        studies = data.get('studies', [])
        return studies
        
    except Exception as e:
        print(f"    Error searching for {sponsor_name}: {e}")
        return []


def extract_trial_events(studies, company_name):
    """Extract relevant events from trial data."""
    events = []
    
    for study in studies:
        try:
            protocol = study.get('protocolSection', {})
            
            # Identification
            id_module = protocol.get('identificationModule', {})
            nct_id = id_module.get('nctId', '')
            title = id_module.get('briefTitle', id_module.get('officialTitle', 'Unknown Trial'))
            
            # Status
            status_module = protocol.get('statusModule', {})
            overall_status = status_module.get('overallStatus', '')
            
            # Dates
            primary_completion = status_module.get('primaryCompletionDateStruct', {})
            completion_date = primary_completion.get('date', '')
            
            # Only include if we have a completion date
            if not completion_date:
                continue
            
            # Parse date - format is usually "YYYY-MM" or "YYYY-MM-DD"
            try:
                if len(completion_date) == 7:  # YYYY-MM
                    dt = datetime.strptime(completion_date, '%Y-%m')
                    completion_date = dt.strftime('%Y-%m-28')  # Assume end of month
                elif len(completion_date) == 10:  # YYYY-MM-DD
                    pass  # Already correct format
            except:
                continue
            
            # Only include if date is in the future or recent past (last 6 months)
            try:
                dt = datetime.strptime(completion_date, '%Y-%m-%d')
                if dt < datetime.now() - timedelta(days=180):
                    continue
            except:
                pass
            
            # Design module for phase
            design_module = protocol.get('designModule', {})
            phases = design_module.get('phases', [])
            phase_str = ', '.join(phases) if phases else 'Phase 3'
            
            # Condition
            conditions_module = protocol.get('conditionsModule', {})
            conditions = conditions_module.get('conditions', [])
            condition_str = conditions[0] if conditions else 'Various'
            
            # Intervention
            interventions_module = protocol.get('armsInterventionsModule', {})
            interventions = interventions_module.get('interventions', [])
            drug_name = interventions[0].get('name', 'Unknown Drug') if interventions else 'Unknown Drug'
            
            events.append({
                'company': company_name,
                'drug': drug_name[:50],  # Truncate long names
                'type': f'{phase_str} Completion',
                'date': completion_date,
                'title': f"{drug_name}: {condition_str} - Trial Completion Expected",
                'link': f"https://clinicaltrials.gov/study/{nct_id}",
                'source': 'ClinicalTrials.gov'
            })
            
        except Exception as e:
            continue
    
    return events


def search_all_companies(companies):
    """Search ClinicalTrials.gov for all companies in the list."""
    print("=" * 60)
    print("ClinicalTrials.gov Scraper for Phase 3/4 Trials")
    print("=" * 60)
    
    all_events = []
    
    # Focus on major biotechs that typically have Phase 3 trials
    priority_companies = [
        "Vertex", "Gilead", "Amgen", "Biogen", "Regeneron", 
        "Moderna", "BioNTech", "Alnylam", "Sarepta", "BioMarin",
        "Neurocrine", "Incyte", "Ultragenyx", "Jazz", "Exelixis",
        "Ionis", "Cytokinetics", "Insmed", "United Therapeutics",
        "Arvinas", "Legend", "Madrigal", "Ascendis", "argenx",
        "Apellis", "Krystal", "Blueprint", "Nuvalent", "Vanda",
        "Eton", "Aquestive", "MannKind", "Regenxbio"
    ]
    
    for company in priority_companies:
        print(f"\nSearching: {company}...")
        
        # Search Phase 3
        studies_p3 = search_clinical_trials(company, "PHASE3")
        print(f"  Found {len(studies_p3)} Phase 3 trials")
        
        events = extract_trial_events(studies_p3, company)
        all_events.extend(events)
        
        # Also search Phase 4 (post-approval)
        studies_p4 = search_clinical_trials(company, "PHASE4")
        if studies_p4:
            print(f"  Found {len(studies_p4)} Phase 4 trials")
            events_p4 = extract_trial_events(studies_p4, company)
            all_events.extend(events_p4)
        
        time.sleep(0.3)  # Be polite to API
    
    print(f"\n{'=' * 60}")
    print(f"Found {len(all_events)} trial completion events")
    print(f"{'=' * 60}")
    
    return all_events


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
        event_date = event.get('date', '')
        if event_date and event_date < '2024-01-01':
            continue
            
        sig = (event.get('company'), event.get('date'), event.get('title', '')[:50])
        if sig not in existing_signatures:
            existing_data.append(event)
            existing_signatures.add(sig)
            added_count += 1
    
    try:
        existing_data.sort(key=lambda x: x.get('date') or '9999-12-31')
    except:
        pass

    filtered_data = [e for e in existing_data if e.get('date', '') >= '2024-01-01']
    
    with open(DATA_JSON_FILE, 'w') as f:
        json.dump(filtered_data, f, indent=4)
    
    print(f"Database updated. Added {added_count} new events.")


def main():
    companies = load_companies()
    if not companies:
        print("No companies loaded from CSV.")
    
    events = search_all_companies(companies)
    if events:
        update_database(events)
    print("\nDone!")


if __name__ == "__main__":
    main()
