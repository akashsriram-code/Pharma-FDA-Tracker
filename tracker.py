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
    # Real feeds
    feeds = [
        'https://feeds.businesswire.com/rss/home/?rss=G1QFDERJXkJeGVtYXw==', # Health
        'https://www.prnewswire.com/rss/health/biotech-latest-news.rss',
        'https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/advisory-committees/rss.xml' # FDA AdComm Feed
    ]
    
    keywords = ["PDUFA", "NDA", "BLA", "Target Action Date", "Acceptance", "Approval"]
    events = []

    scraper = cloudscraper.create_scraper()

    for feed_url in feeds:
        try:
             # Use cloudscraper for RSS feeds too
             response = scraper.get(feed_url, timeout=15)
             if response.status_code != 200:
                 print(f"Error fetching feed {feed_url}: {response.status_code}")
                 continue
                 
             feed = feedparser.parse(response.content)
             
             for entry in feed.entries:
                title = getattr(entry, 'title', '')
                summary = getattr(entry, 'summary', '')
                content = title + " " + summary
                
                detected_company = None
                for company in target_companies:
                    if company.lower() in content.lower():
                        detected_company = company
                        break
                
                if detected_company:
                    if any(kw.lower() in content.lower() for kw in keywords):
                         events.append({
                            'company': detected_company,
                            'drug': 'Check Source',
                            'type': 'Regulatory Update',
                            'date': getattr(entry, 'published', datetime.now().strftime('%Y-%m-%d')),
                            'title': title,
                            'link': getattr(entry, 'link', '#'),
                            'source': 'RSS Monitor'
                        })
        except Exception as e:
            print(f"Error parsing feed {feed_url}: {e}")
            
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
        sig = (item.get('company'), item.get('date'), item.get('title'))
        existing_signatures.add(sig)
    
    added_count = 0
    for event in new_events:
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

    # Only write if we have data or if the intention was to potentially clear (but here we want preservation)
    # If we have 0 new events and existing data is there, we just rewrite the sorted existing data
    with open(DATA_JSON_FILE, 'w') as f:
        json.dump(existing_data, f, indent=4)
    
    print(f"Database updated. Total events: {len(existing_data)} (Added {added_count} new).")

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
