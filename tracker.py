import csv
import json
import os
import requests
from bs4 import BeautifulSoup
import feedparser
from datetime import datetime
import re
import pandas as pd
import warnings

# Suppress warnings
warnings.filterwarnings('ignore')

# Configuration
DATA_DIR = 'data'
COMPANIES_FILE = os.path.join(DATA_DIR, 'NASDAQ Biotechnology (NBI).csv')
DATA_JSON_FILE = os.path.join(DATA_DIR, 'data.json')
PDUFA_DATES_FILE = os.path.join(DATA_DIR, 'pdufa_dates.json')
FDA_CALENDAR_URL = 'https://www.fda.gov/advisory-committees/advisory-committee-calendar'

def load_companies():
    """Loads company names and symbols from the CSV file."""
    companies = []
    if not os.path.exists(COMPANIES_FILE):
        print(f"Error: {COMPANIES_FILE} not found.")
        return []
    
    try:
        with open(COMPANIES_FILE, mode='r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if 'Company Name' in row:
                    companies.append(row['Company Name'])
                elif 'Name' in row: # Support for 'Name' header in NBI CSV
                    companies.append(row['Name'])
                elif 'Symbol' in row: # Fallback if just symbol is useful
                     companies.append(row['Symbol'])
    except Exception as e:
        print(f"Error loading companies: {e}")
    return companies

def load_pdufa_dates():
    """Loads curated upcoming PDUFA dates from JSON file."""
    print("Loading upcoming PDUFA dates...")
    events = []
    
    if not os.path.exists(PDUFA_DATES_FILE):
        print(f"  No PDUFA dates file found at {PDUFA_DATES_FILE}")
        return events
    
    try:
        with open(PDUFA_DATES_FILE, 'r') as f:
            pdufa_data = json.load(f)
            
        # Filter to only future dates
        today = datetime.now().strftime('%Y-%m-%d')
        for item in pdufa_data:
            if item.get('date', '') >= today:
                events.append({
                    'company': item.get('company', ''),
                    'drug': item.get('drug', 'Unknown'),
                    'type': item.get('type', 'PDUFA Date'),
                    'date': item.get('date', ''),
                    'title': item.get('title', ''),
                    'link': item.get('link', '#'),
                    'source': item.get('source', 'PDUFA Calendar')
                })
                
        print(f"  Loaded {len(events)} upcoming PDUFA dates.")
    except Exception as e:
        print(f"  Error loading PDUFA dates: {e}")
    
    return events

def fetch_federal_register_adcomm(target_companies):
    """Fetches FDA Advisory Committee meeting notices from the Federal Register API."""
    print("Fetching FDA Advisory Committee meetings from Federal Register...")
    events = []
    
    # diverse set of keywords to catch all relevant meeting notices
    # agency_ids[]=193 is FDA
    # conditions[term]=Advisory Committee
    base_url = "https://www.federalregister.gov/api/v1/documents.json"
    params = {
        "conditions[agency_ids][]": "193",
        "conditions[term]": "Advisory Committee",
        "conditions[type][]": "NOTICE",
        "order": "newest",
        "per_page": 20
    }
    
    try:
        response = requests.get(base_url, params=params, timeout=20)
        
        if response.status_code != 200:
            print(f"Failed to fetch Federal Register. Status: {response.status_code}")
            return events
            
        data = response.json()
        results = data.get('results', [])
        
        if not results:
            print("No recent AdComm notices found in Federal Register.")
            
        for item in results:
            title = item.get('title', '')
            abstract = item.get('abstract', '') or ''
            content = title + " " + abstract
            pub_date = item.get('publication_date', '')
            pdf_url = item.get('pdf_url', '')
            html_url = item.get('html_url', '')
            
            # Check for company matches in the notice title or abstract
            detected_company = None
            for company in target_companies:
                if company.lower() in content.lower():
                    detected_company = company
                    break
            
            # If no specific company, but it's clearly an AdComm, maybe list it generally? 
            # For now, stick to target companies to avoid noise.
            
            if detected_company:
                # Try to extract the actual meeting date from the text if possible
                # (This is hard without full text parsing, so we'll use publication date 
                # effectively as the 'announcement' date, or check 'dates' field if available details exist)
                
                # Federal Register API sometimes provides 'docket_ids' or 'dates' in full text
                # We'll use the publication date as a proxy for "New Meeting Announced" if we can't parse better
                
                event_date = pub_date
                
                # Basic future date extraction Attempt from title (e.g., "September 15, 2026 Meeting of...")
                import re
                date_match = re.search(r'([A-Z][a-z]+\s+\d{1,2},?\s+\d{4})', title)
                if date_match:
                    try:
                        dt = datetime.strptime(date_match.group(1).replace(',', ''), '%B %d %Y')
                        event_date = dt.strftime('%Y-%m-%d')
                    except:
                        pass
                
                events.append({
                    'company': detected_company,
                    'drug': 'Check Notice',
                    'type': 'AdComm Meeting',
                    'date': event_date,
                    'title': title[:200],
                    'link': html_url or pdf_url,
                    'source': 'Federal Register'
                })
                
    except Exception as e:
        print(f"Error fetching from Federal Register: {e}")
            
    print(f"Found {len(events)} AdComm events from Federal Register.")
    return events

def fetch_openfda_approvals(target_companies):
    """Fetches recent drug approvals from the openFDA API."""
    print("Fetching recent approvals from openFDA API...")
    events = []
    
    # Query for recent drug approvals (last 90 days)
    today = datetime.now()
    
    # openFDA API endpoint for drug applications
    api_url = "https://api.fda.gov/drug/drugsfda.json"
    
    # Get submissions with recent approval dates
    params = {
        "limit": 100,
        "search": "submissions.submission_status:AP"
    }
    
    try:
        response = requests.get(api_url, params=params, timeout=20)
        
        if response.status_code != 200:
            print(f"openFDA API returned status: {response.status_code}")
            return events
            
        data = response.json()
        results = data.get('results', [])
        
        for result in results:
            sponsor = result.get('sponsor_name', '')
            products = result.get('products', [])
            submissions = result.get('submissions', [])
            app_number = result.get('application_number', '')
            
            # Check if sponsor matches any target company
            detected_company = None
            for company in target_companies:
                company_words = company.lower().split()
                sponsor_lower = sponsor.lower()
                # Match if main company word is in sponsor name
                if any(word in sponsor_lower for word in company_words if len(word) > 3):
                    detected_company = company
                    break
            
            if detected_company and products:
                # Get the most recent approval
                for sub in submissions:
                    if sub.get('submission_status') == 'AP':
                        sub_date = sub.get('submission_status_date', '')
                        if len(sub_date) == 8:  # Format: YYYYMMDD
                            formatted_date = f"{sub_date[:4]}-{sub_date[4:6]}-{sub_date[6:8]}"
                        else:
                            formatted_date = sub_date
                        
                        brand_name = products[0].get('brand_name', 'Unknown Drug')
                        
                        # Filter out dates before 2024
                        if formatted_date < '2024-01-01':
                            continue
                        
                        events.append({
                            'company': detected_company,
                            'drug': brand_name,
                            'type': 'FDA Approval',
                            'date': formatted_date,
                            'title': f"{brand_name} - {sub.get('submission_type', 'Application')} Approved",
                            'link': f"https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?event=overview.process&ApplNo={app_number.replace('NDA', '').replace('ANDA', '').replace('BLA', '')}",
                            'source': 'openFDA API'
                        })
                        break  # Only take most recent approval per application
                        
    except Exception as e:
        print(f"Error fetching from openFDA: {e}")
    
    print(f"Found {len(events)} openFDA approval events.")
    return events

def scan_rss_feeds(target_companies):
    """Scans RSS feeds for PDUFA/Regulatory keywords and extracts FUTURE dates."""
    print("Scanning RSS feeds...")
    
    # Working feed URLs (GlobeNewswire biotech feed is accessible)
    feeds = [
        ('https://www.globenewswire.com/RssFeed/subjectcode/14-Biotechnology/feedTitle/GlobeNewswire%20-%20Biotechnology', 'GlobeNewswire Biotech'),
        ('https://www.globenewswire.com/RssFeed/subjectcode/15-Healthcare/feedTitle/GlobeNewswire%20-%20Healthcare', 'GlobeNewswire Healthcare'),
    ]
    
    # Keywords to search for in press releases
    keywords = [
        "PDUFA", "NDA", "BLA", "sNDA", "sBLA",
        "Target Action Date", "FDA Approval", "FDA Accepts",
        "Complete Response Letter", "CRL", "Priority Review",
        "Breakthrough Therapy", "Fast Track", "Rolling Submission",
        "Advisory Committee", "AdComm", "ODAC", "Phase 3"
    ]
    
    # Regex patterns for date extraction
    # Matches: "PDUFA date of March 15, 2026", "target action date: March 2026", "decision by Q1 2026"
    date_patterns = [
        r'(?:PDUFA|target action|goal)\s*date\s*(?:of|is|:|set for)?\s*([A-Z][a-z]+\s+\d{1,2},?\s+\d{4})',
        r'(?:target action|PDUFA)\s*date\s*(?:of|is|:|set for)?\s*([A-Z][a-z]+\s+\d{4})',
        r'(?:decision|review|PDUFA)\s*(?:by|in|expected)\s*(Q[1-4]\s+\d{4})',
        r'(?:expected|anticipated)\s*(?:in|by)\s*([A-Z][a-z]+\s+\d{4})',
    ]
    
    events = []
    
    # Use standard requests (cloudscraper can cause issues on GitHub Actions)
    for feed_url, source_name in feeds:
        try:
            response = requests.get(feed_url, timeout=20, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            
            if response.status_code != 200:
                print(f"Error fetching {source_name}: {response.status_code}")
                continue
                
            feed = feedparser.parse(response.content)
            print(f"  {source_name}: {len(feed.entries)} entries found")
            
            for entry in feed.entries:
                title = getattr(entry, 'title', '')
                summary = getattr(entry, 'summary', '')
                content = title + " " + summary
                
                # First check for PDUFA/regulatory keywords
                has_keyword = any(kw.lower() in content.lower() for kw in keywords)
                
                if has_keyword:
                    # Then check if it matches any company
                    detected_company = None
                    for company in target_companies:
                        company_words = company.lower().split()
                        content_lower = content.lower()
                        # Match main company word (4+ chars) to avoid false positives
                        if any(word in content_lower for word in company_words if len(word) > 3):
                            detected_company = company
                            break
                    
                    if detected_company:
                        # Parse publication date as fallback
                        pub_date = getattr(entry, 'published', '')
                        fallback_date = datetime.now().strftime('%Y-%m-%d')
                        if pub_date:
                            try:
                                from email.utils import parsedate_to_datetime
                                dt = parsedate_to_datetime(pub_date)
                                fallback_date = dt.strftime('%Y-%m-%d')
                            except:
                                pass

                        # Try to extract a FUTURE date from text
                        extracted_date = None
                        import re
                        for pattern in date_patterns:
                            match = re.search(pattern, content, re.IGNORECASE)
                            if match:
                                date_str = match.group(1)
                                try:
                                    # Try various formats
                                    for fmt in ['%B %d, %Y', '%B %d %Y', '%B, %Y', '%B %Y']:
                                        try:
                                            dt = datetime.strptime(date_str.replace(',', ''), fmt)
                                            extracted_date = dt.strftime('%Y-%m-%d')
                                            break
                                        except:
                                            continue
                                    
                                    # Handle Quarterly (Q1 2026 -> 2026-03-31)
                                    if not extracted_date:
                                        q_match = re.match(r'Q([1-4])\s+(\d{4})', date_str)
                                        if q_match:
                                            quarter = int(q_match.group(1))
                                            year = int(q_match.group(2))
                                            month = quarter * 3
                                            from calendar import monthrange
                                            day = monthrange(year, month)[1]
                                            extracted_date = f"{year}-{month:02d}-{day:02d}"
                                    
                                    if extracted_date:
                                        break
                                except:
                                    continue
                        
                        # Use extracted date if found and is in future, otherwise use publication date
                        final_date = extracted_date if extracted_date and extracted_date >= fallback_date else fallback_date
                        
                        # Set type based on keyword
                        event_type = 'Press Release'
                        if "PDUFA" in content or "Target Action" in content:
                            event_type = 'PDUFA Update'
                        elif "AdComm" in content or "Advisory Committee" in content:
                            event_type = 'AdComm Update'
                        elif "Approval" in content or "Approved" in content:
                            event_type = 'FDA Approval'
                        
                        events.append({
                            'company': detected_company,
                            'drug': 'Check Source',
                            'type': event_type,
                            'date': final_date,
                            'title': title[:200],
                            'link': getattr(entry, 'link', '#'),
                            'source': source_name
                        })
                        
        except Exception as e:
            print(f"Error parsing {source_name}: {e}")
            
    print(f"Found {len(events)} regulatory press releases.")
    return events

def update_database(new_events):
    """Updates the JSON database with new events, avoiding duplicates."""
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
        # Also filter out old data from existing entries
        item_date = item.get('date', '')
        if item_date and item_date < '2024-01-01':
            continue
        sig = (item.get('company'), item.get('date'), item.get('title'))
        existing_signatures.add(sig)
    
    added_count = 0
    for event in new_events:
        # Filter out dates before 2024
        event_date = event.get('date', '')
        if event_date and event_date < '2024-01-01':
            continue
            
        sig = (event.get('company'), event.get('date'), event.get('title'))
        if sig not in existing_signatures:
            existing_data.append(event)
            existing_signatures.add(sig)
            added_count += 1
    
    # Sort by date
    try:
        existing_data.sort(key=lambda x: x.get('date') or '9999-12-31')
    except:
        pass

    # Filter out all entries before 2024 before writing
    filtered_data = [e for e in existing_data if e.get('date', '') >= '2024-01-01']
    
    with open(DATA_JSON_FILE, 'w') as f:
        json.dump(filtered_data, f, indent=4)
    
    print(f"Database updated. Total events: {len(filtered_data)} (Added {added_count} new).")

def main():
    print("Starting FDA Catalyst Tracker...")
    companies = load_companies()
    if not companies:
        print("No companies loaded. Exiting.")
        return
        
    print(f"Loaded {len(companies)} companies to track.")
    
    # Load curated upcoming PDUFA dates
    pdufa_events = load_pdufa_dates()
    
    # Use Federal Register API for AdComm meetings (more reliable than scraping FDA)
    fda_events = fetch_federal_register_adcomm(companies)
    print(f"Found {len(fda_events)} FDA AdComm events.")
    
    # Fetch from openFDA API (this is not blocked!)
    openfda_events = fetch_openfda_approvals(companies)
    
    rss_events = scan_rss_feeds(companies)
    print(f"Found {len(rss_events)} RSS regulatory events.")
    
    all_events = pdufa_events + fda_events + openfda_events + rss_events
    update_database(all_events)
    print("Done.")

if __name__ == "__main__":
    main()
