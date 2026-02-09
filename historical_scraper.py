"""
Historical Press Release Scraper
Scrapes PRNewsWire and BusinessWire for PDUFA-related press releases from the past 12 months.
This is a one-time scraper to populate historical data.
"""

import requests
import json
import os
import csv
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import time
import re

# Configuration
DATA_DIR = 'data'
COMPANIES_FILE = os.path.join(DATA_DIR, 'NASDAQ Biotechnology (NBI).csv')
DATA_JSON_FILE = os.path.join(DATA_DIR, 'data.json')

# PDUFA-related keywords to search for
SEARCH_TERMS = [
    "PDUFA",
    "FDA approval",
    "FDA accepts",
    "NDA submission",
    "BLA submission",
    "Complete Response Letter",
    "Priority Review",
    "Breakthrough Therapy",
]

def load_companies():
    """Loads company names from the CSV file."""
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
                elif 'Name' in row:
                    companies.append(row['Name'])
    except Exception as e:
        print(f"Error loading companies: {e}")
    return companies

def search_prnewswire(search_term, page=1):
    """Search PRNewsWire for press releases containing the search term."""
    events = []
    
    # PRNewsWire search URL
    url = f"https://www.prnewswire.com/search/news/?keyword={search_term.replace(' ', '+')}&page={page}&pagesize=100"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code != 200:
            print(f"    PRNewsWire search returned {response.status_code}")
            return events
            
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Find all news items
        news_items = soup.select('.newsCards .card') or soup.select('.row.newsCards .card')
        
        for item in news_items:
            try:
                title_elem = item.select_one('h3 a') or item.select_one('.news-release a')
                date_elem = item.select_one('.datetime') or item.select_one('.date')
                
                if title_elem:
                    title = title_elem.get_text(strip=True)
                    link = title_elem.get('href', '')
                    if link and not link.startswith('http'):
                        link = f"https://www.prnewswire.com{link}"
                    
                    date_str = date_elem.get_text(strip=True) if date_elem else ''
                    
                    # Parse date
                    try:
                        # Try common formats
                        for fmt in ['%b %d, %Y', '%B %d, %Y', '%Y-%m-%d']:
                            try:
                                dt = datetime.strptime(date_str, fmt)
                                date_formatted = dt.strftime('%Y-%m-%d')
                                break
                            except:
                                date_formatted = date_str[:10] if len(date_str) >= 10 else ''
                    except:
                        date_formatted = ''
                    
                    # Filter to last 12 months
                    if date_formatted:
                        try:
                            item_date = datetime.strptime(date_formatted, '%Y-%m-%d')
                            cutoff = datetime.now() - timedelta(days=365)
                            if item_date < cutoff:
                                continue
                        except:
                            pass
                    
                    events.append({
                        'title': title,
                        'link': link,
                        'date': date_formatted,
                        'source': 'PRNewsWire'
                    })
                    
            except Exception as e:
                continue
                
    except Exception as e:
        print(f"    Error searching PRNewsWire: {e}")
    
    return events

def search_businesswire(search_term, page=1):
    """Search BusinessWire for press releases containing the search term."""
    events = []
    
    # BusinessWire search URL
    url = f"https://www.businesswire.com/portal/site/home/search/?searchType=news&searchText={search_term.replace(' ', '+')}&searchPage={page}"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code != 200:
            print(f"    BusinessWire search returned {response.status_code}")
            return events
            
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Find all news items
        news_items = soup.select('.bw-news-list li') or soup.select('.bwNewsList li')
        
        for item in news_items:
            try:
                title_elem = item.select_one('a.bw-news-title') or item.select_one('h3 a') or item.select_one('a')
                date_elem = item.select_one('.bw-release-timings') or item.select_one('.date') or item.select_one('time')
                
                if title_elem:
                    title = title_elem.get_text(strip=True)
                    link = title_elem.get('href', '')
                    if link and not link.startswith('http'):
                        link = f"https://www.businesswire.com{link}"
                    
                    date_str = date_elem.get_text(strip=True) if date_elem else ''
                    
                    # Parse date
                    date_formatted = ''
                    try:
                        for fmt in ['%B %d, %Y', '%b %d, %Y', '%Y-%m-%d']:
                            try:
                                dt = datetime.strptime(date_str.split()[0:3] if ' ' in date_str else date_str, fmt)
                                date_formatted = dt.strftime('%Y-%m-%d')
                                break
                            except:
                                pass
                    except:
                        pass
                    
                    events.append({
                        'title': title,
                        'link': link,
                        'date': date_formatted if date_formatted else datetime.now().strftime('%Y-%m-%d'),
                        'source': 'BusinessWire'
                    })
                    
            except Exception as e:
                continue
                
    except Exception as e:
        print(f"    Error searching BusinessWire: {e}")
    
    return events

def match_companies(events, target_companies):
    """Filter events to only those mentioning target companies."""
    matched = []
    
    for event in events:
        title = event.get('title', '')
        
        for company in target_companies:
            company_words = company.lower().split()
            title_lower = title.lower()
            
            # Match if main company word (4+ chars) is in title
            if any(word in title_lower for word in company_words if len(word) > 3):
                matched.append({
                    'company': company,
                    'drug': 'Check Source',
                    'type': 'Press Release',
                    'date': event.get('date', ''),
                    'title': event.get('title', ''),
                    'link': event.get('link', ''),
                    'source': event.get('source', '')
                })
                break  # Only match one company per event
    
    return matched

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
    
    # Create signature set for deduplication
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

    # Filter out all entries before 2024 before writing
    filtered_data = [e for e in existing_data if e.get('date', '') >= '2024-01-01']
    
    with open(DATA_JSON_FILE, 'w') as f:
        json.dump(filtered_data, f, indent=4)
    
    print(f"\nDatabase updated. Total events: {len(filtered_data)} (Added {added_count} new).")
    return added_count

def main():
    print("=" * 60)
    print("Historical Press Release Scraper")
    print("Searching for PDUFA-related press releases from past 12 months")
    print("=" * 60)
    
    # Load companies
    companies = load_companies()
    if not companies:
        print("No companies loaded. Exiting.")
        return
    print(f"Loaded {len(companies)} companies to track.\n")
    
    all_events = []
    
    # Search for each PDUFA-related term
    for term in SEARCH_TERMS:
        print(f"Searching for: '{term}'...")
        
        # Search PRNewsWire
        print(f"  → PRNewsWire...")
        prn_events = search_prnewswire(term)
        print(f"    Found {len(prn_events)} results")
        all_events.extend(prn_events)
        time.sleep(1)  # Be polite to servers
        
        # Search BusinessWire
        print(f"  → BusinessWire...")
        bw_events = search_businesswire(term)
        print(f"    Found {len(bw_events)} results")
        all_events.extend(bw_events)
        time.sleep(1)
    
    print(f"\nTotal raw results: {len(all_events)}")
    
    # Match against company list
    print("Matching against company list...")
    matched_events = match_companies(all_events, companies)
    print(f"Matched {len(matched_events)} events to tracked companies.")
    
    # Update database
    if matched_events:
        added = update_database(matched_events)
        print(f"Added {added} new events to database.")
    else:
        print("No new events to add.")
    
    print("\nDone!")

if __name__ == "__main__":
    main()
