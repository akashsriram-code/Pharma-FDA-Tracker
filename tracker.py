import csv
import json
import os
import requests
from bs4 import BeautifulSoup
import feedparser
from datetime import datetime
import pandas as pd
import warnings
import cloudscraper

# Suppress warnings
warnings.filterwarnings('ignore')

# Configuration
DATA_DIR = 'data'
COMPANIES_FILE = os.path.join(DATA_DIR, 'NASDAQ Biotechnology (NBI).csv')
DATA_JSON_FILE = os.path.join(DATA_DIR, 'data.json')
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

def scrape_fda_adcomm(target_companies):
    """Scrapes the FDA Advisory Committee Calendar for matches."""
    print("Scraping FDA Advisory Committee Calendar...")
    events = []
    
    try:
        # Use cloudscraper to bypass Cloudflare/Bot protection
        scraper = cloudscraper.create_scraper()
        response = scraper.get(FDA_CALENDAR_URL, timeout=20)
        
        if response.status_code != 200:
            print(f"Failed to fetch FDA calendar. Status: {response.status_code}")
        else:
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # FDA structure varies. Common container for views based lists:
            rows = soup.select('.views-row') or soup.find_all('div', class_='views-row')
            
            if not rows:
                print("Warning: No events found in FDA calendar (layout might have changed).")

            for row in rows:
                text_content = row.get_text(separator=' ', strip=True)
                
                # Simple keyword matching
                detected_company = None
                for company in target_companies:
                    if company.lower() in text_content.lower():
                        detected_company = company
                        break
                
                if detected_company:
                    date_tag = row.find('time')
                    event_date = "Unknown"
                    if date_tag:
                        event_date = date_tag.get('datetime') or date_tag.get_text(strip=True)
                    
                    title_tag = row.find('a')
                    title = title_tag.get_text(strip=True) if title_tag else "Advisory Committee Meeting"
                    link = f"https://www.fda.gov{title_tag['href']}" if title_tag else FDA_CALENDAR_URL

                    events.append({
                        'company': detected_company,
                        'drug': 'Check Source',
                        'type': 'AdComm',
                        'date': event_date,
                        'title': title,
                        'link': link,
                        'source': 'FDA Scraper'
                    })

    except Exception as e:
        print(f"Error scraping FDA: {e}")
    
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
    """Scans RSS feeds for PDUFA/Regulatory keywords."""
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
                        # Parse published date
                        pub_date = getattr(entry, 'published', '')
                        if pub_date:
                            try:
                                # Try to parse various date formats
                                from email.utils import parsedate_to_datetime
                                dt = parsedate_to_datetime(pub_date)
                                formatted_date = dt.strftime('%Y-%m-%d')
                            except:
                                formatted_date = pub_date[:10] if len(pub_date) >= 10 else pub_date
                        else:
                            formatted_date = datetime.now().strftime('%Y-%m-%d')
                        
                        events.append({
                            'company': detected_company,
                            'drug': 'Check Source',
                            'type': 'Press Release',
                            'date': formatted_date,
                            'title': title[:200],  # Truncate long titles
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
    
    fda_events = scrape_fda_adcomm(companies)
    print(f"Found {len(fda_events)} FDA AdComm events.")
    
    # NEW: Fetch from openFDA API (this is not blocked!)
    openfda_events = fetch_openfda_approvals(companies)
    
    rss_events = scan_rss_feeds(companies)
    print(f"Found {len(rss_events)} RSS regulatory events.")
    
    all_events = fda_events + openfda_events + rss_events
    update_database(all_events)
    print("Done.")

if __name__ == "__main__":
    main()
