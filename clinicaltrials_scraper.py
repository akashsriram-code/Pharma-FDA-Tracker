"""
ClinicalTrials.gov Scraper for Late-Stage Trials
Queries ClinicalTrials.gov API for Phase 3/4 trials from biotech companies.

Primary Source: ClinicalTrials.gov (https://clinicaltrials.gov)
Data Type: Clinical trial completion dates and regulatory status
API: Free, no API key required
"""

import requests
import os
import csv
from datetime import datetime, timedelta
import time

import data_store

# Configuration
DATA_DIR = 'data'
COMPANIES_FILE = os.path.join(DATA_DIR, 'NASDAQ Biotechnology (NBI).csv')
DATA_JSON_FILE = os.path.join(DATA_DIR, 'data.json')

# Upper bound on how far out a "primary completion date" estimate can be and
# still count as a near-term catalyst. Without this, ClinicalTrials.gov
# registry placeholders (e.g. 2039/2040 estimated completion dates) dilute
# the near-term Clinical Trials feed with low-relevance long-horizon entries.
MAX_FUTURE_DAYS = 730  # ~24 months

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
    
    # Create session with retry strategy
    session = requests.Session()
    session.verify = False
    
    # Manually construct URL to mimic the working curl command exactly
    # We must use PIPE separation for multiple statuses, NOT repeated keys.
    # We also use query.term for phase because filter.phase is not a valid V2 API parameter.
    
    base_url = f"{CT_API_URL}?"
    
    parts = []
    parts.append(f"query.spons={sponsor_name}")
    parts.append(f"query.term={phase}")
    parts.append("pageSize=20")
    parts.append("fields=NCTId,BriefTitle,OfficialTitle,OverallStatus,Phase,StartDate,PrimaryCompletionDate,CompletionDate,LeadSponsorName,Condition,InterventionName")
    
    # Use pipe delimiter for multiple statuses
    statuses = ['ACTIVE_NOT_RECRUITING', 'COMPLETED', 'RECRUITING', 'ENROLLING_BY_INVITATION']
    status_str = "|".join(statuses)
    parts.append(f"filter.overallStatus={status_str}")
        
    full_url = base_url + "&".join(parts)
        
    try:
        # verify=False is needed for some corporate networks (Zscaler)
        response = session.get(full_url, headers=HEADERS, timeout=15)
        if response.status_code != 200:
            print(f"    Request failed with status: {response.status_code}")
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
            
            # Only include if date is in the future (but not implausibly far
            # out) or recent past (last 6 months)
            try:
                dt = datetime.strptime(completion_date, '%Y-%m-%d')
                now = datetime.now()
                if dt < now - timedelta(days=180):
                    continue
                if dt > now + timedelta(days=MAX_FUTURE_DAYS):
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

    # Search the full tracked-company universe (loaded from the NBI CSV),
    # not just a hardcoded shortlist. `companies` used to be loaded and then
    # silently discarded here in favor of a 33-name internal list, which
    # meant ~88% of tracked companies never got searched at all.
    search_companies = [c.strip() for c in companies if c and c.strip()]

    for company in search_companies:
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


def main():
    companies = load_companies()
    if not companies:
        print("No companies loaded from CSV.")

    events = search_all_companies(companies)
    if events:
        added, updated, total = data_store.update_database(events, path=DATA_JSON_FILE)
        print(f"Database updated. Added {added} new events. Total events: {total}.")
    print("\nDone!")


if __name__ == "__main__":
    main()
