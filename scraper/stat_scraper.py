from bs4 import BeautifulSoup
import requests
import time
import asyncio
import aiohttp 
from scraper.fighter_model import Fighter
from scraper.clean_data import clean_fighter_stats
from scraper.fighter_stats import get_fighter_details
from scraper.filter_data import filter_fighters
import csv

# === PHASE 1: DATABASE INTEGRATION ===
# Import our new database module for SQLAlchemy ORM functionality
from scraper.database import (
    get_engine,           # Creates database connection
    init_database,        # Creates tables
    add_fighters,         # Bulk insert fighters
    get_fighter_count     # Query fighter count
)

alphabet = [
    'a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k', 'l', 'm',
    'n', 'o', 'p', 'q', 'r', 's', 't', 'u', 'v', 'w', 'x', 'y', 'z'
]
ufc_site_url = "http://ufcstats.com/statistics/fighters?char={}&page=all"
CONCURRENT_REQUESTS = 10
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/115.0 Safari/537.36"
}

async def fetch_letter(letter, session, sem, retries=3):
    async with sem:
        url = ufc_site_url.format(letter)
        for attempt in range(retries):
            try:
                async with session.get(url, ssl=False, headers=HEADERS) as response:
                    return await response.text()
            except (aiohttp.ClientPayloadError, aiohttp.ClientConnectionError) as e:
                if attempt < retries - 1:
                    await asyncio.sleep(1)
                else:
                    print(f"Failed to fetch {url}: {e}")
                    return ""

async def fetch_all_letters():
    sem = asyncio.Semaphore(CONCURRENT_REQUESTS)
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_letter(letter, session, sem) for letter in alphabet]
        html_pages = await asyncio.gather(*tasks)
        return html_pages

async def parse_fighter_urls(html):
    def parse():
        soup = BeautifulSoup(html, "html.parser")
        urls = []
        for tag in soup.find_all("a", href=True):
            # BeautifulSoup type hints issue - suppress with type: ignore
            href = tag.get("href")  # type: ignore
            if href and "fighter-details" in href:
                urls.append(href)
        return urls
    fighter_urls = await asyncio.to_thread(parse)
    return fighter_urls

async def gather_all_urls(html_pages):
    tasks = [parse_fighter_urls(html) for html in html_pages]
    results = await asyncio.gather(*tasks)

    all_urls = set()
    for url_list in results:
        all_urls.update(url_list)
    return list(all_urls)

async def get_all_fighter_urls():
    html_pages = await fetch_all_letters()
    fighter_urls = await gather_all_urls(html_pages)
    return fighter_urls

async def fetch_name(fighter, session, sem, retries=3):
    url = fighter['url']
    async with sem:
        for attempt in range(retries):
            try:
                async with session.get(url, headers=HEADERS, ssl=False) as resp:
                    # Let aiohttp raise its own error if status is bad
                    resp.raise_for_status()
                    text = await resp.text()
                    soup = BeautifulSoup(text, "html.parser")
                    name_tag = soup.find("span", class_="b-content__title-highlight")
                    fighter['name'] = name_tag.text.strip() if name_tag else "Unknown"
                    return
            except Exception as e:
                if attempt < retries - 1:
                    await asyncio.sleep(1)
                else:
                    print(f"Failed to fetch name for {url}: {e}")
                    fighter['name'] = "Unknown"

async def fetch_stats(fighter, session, sem, retries=3):
    url = fighter['url']
    async with sem:
        for attempt in range(retries):
            try:
                fighter_info = await asyncio.to_thread(get_fighter_details, url)
                fighter.update(fighter_info)
                return
            except Exception as e:
                if attempt < retries - 1:
                    await asyncio.sleep(1)
                else:
                    print(f"Failed to fetch stats for {fighter.get('name', url)}: {e}")

async def fetch_all_names_and_stats(fighters):
    sem = asyncio.Semaphore(CONCURRENT_REQUESTS)
    async with aiohttp.ClientSession() as session:
        name_tasks = [fetch_name(fighter, session, sem) for fighter in fighters]
        await asyncio.gather(*name_tasks)

        stats_tasks = [fetch_stats(fighter, session, sem) for fighter in fighters]
        await asyncio.gather(*stats_tasks)

def write_csv(fighters):
    """
    LEGACY FUNCTION: Writes fighters to CSV (kept for backward compatibility).
    
    Phase 1 Update: We're moving to database storage, but keeping this function
    in case you want to export CSV files for analysis or backup.
    """
    file_name = "output.csv"
    if not fighters:
        print("No fighters to write.")
        return
    fighter_dicts = [fighter.to_dict() for fighter in fighters]
    fieldnames = fighter_dicts[0].keys()
    with open(file_name, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(fighter_dicts)
    print(f"CSV file '{file_name}' has been created successfully!")


def save_to_database(fighters, db_path='ufc_fighters.db'):
    """
    NEW FUNCTION (Phase 1): Saves fighters to SQLite database using SQLAlchemy ORM.
    
    HOW THIS WORKS:
    ---------------
    1. Create/connect to database using get_engine()
    2. Initialize tables if they don't exist
    3. Use add_fighters() to bulk insert all fighter data
    4. Return count of saved fighters
    
    LEARNING POINTS:
    ----------------
    - This replaces CSV export with persistent database storage
    - Data is stored in a structured format (SQL table)
    - You can query, filter, and update data efficiently
    - The database file (ufc_fighters.db) persists between script runs
    
    PARAMETERS:
    -----------
    fighters : list
        List of Fighter objects from fighter_model.py
    db_path : str
        Path to SQLite database file (default: 'ufc_fighters.db')
    
    RETURNS:
    --------
    int : Number of fighters successfully saved
    """
    if not fighters:
        print("No fighters to save to database.")
        return 0
    
    print("\n" + "="*80)
    print("PHASE 1: SAVING TO DATABASE")
    print("="*80)
    
    # Step 1: Create database engine (connection to SQLite file)
    engine = get_engine(db_path)
    
    # Step 2: Initialize database (creates 'fighters' table if it doesn't exist)
    init_database(engine)
    
    # Step 3: Add all fighters to database
    count = add_fighters(fighters, engine)
    
    # Step 4: Verify the save
    total_in_db = get_fighter_count(engine)
    print(f"\n📊 Database now contains {total_in_db} total fighters")
    print("="*80 + "\n")
    
    return count

def main():
    """
    Main scraper function - UPDATED FOR PHASE 1: DATABASE INTEGRATION
    
    WHAT CHANGED:
    -------------
    - Added save_to_database() call to persist data to SQLite
    - Kept write_csv() as optional backup/export
    - Added user choice to use database, CSV, or both
    
    WORKFLOW:
    ---------
    1. Scrape fighter URLs from ufcstats.com
    2. Fetch detailed stats for each fighter (async)
    3. Clean and validate data
    4. Create Fighter objects
    5. Filter out bad samples
    6. **NEW**: Save to database using SQLAlchemy ORM
    7. (Optional) Export to CSV for backup
    """
    start = time.time()
    
    # Step 1-2: Scrape fighter URLs and fetch detailed stats
    fighter_urls = asyncio.run(get_all_fighter_urls())
    fighters = [{"url": url} for url in fighter_urls]
    print(f"Total fighters found: {len(fighters)}")

    asyncio.run(fetch_all_names_and_stats(fighters))

    # Step 3: Clean fighter stats
    print("\nCleaning fighter stats...")
    fighters = clean_fighter_stats(fighters)

    # Step 4: Ensure all required keys exist before creating Fighter objects
    required_fields = ['height', 'weight', 'reach', 'stance', 'dob', 'slpm', 'stracc',
                       'sapm', 'strdef', 'tdavg', 'tdacc', 'tddef', 'subavg', 'record',
                       'mostrecentfight', 'fightswithinufc']
    for fighter_data in fighters:
        for field in required_fields:
            fighter_data.setdefault(field, None)

    # Step 5: Instantiate Fighter objects
    print("Instantiating Fighter objects...")
    fighter_class_list = [Fighter(**fighter_data) for fighter_data in fighters]

    # Step 6: Filter fighters (remove those with < 3 UFC fights)
    print("Filtering fighters...")
    good_fighters = [f for f in fighter_class_list if not f.bad_sample]
    print(f"Active/valid fighters: {len(good_fighters)}")

    # ===== PHASE 1: DATABASE INTEGRATION =====
    # Save to database (primary storage method)
    save_to_database(good_fighters, db_path='ufc_fighters.db')
    
    # Optional: Also export to CSV for backward compatibility and easy viewing
    print("Also creating CSV backup...")
    write_csv(good_fighters)
    # ==========================================
    
    end = time.time()
    elapsed = end - start
    print(f'\n⏱️  Total elapsed time: {elapsed:.2f} seconds')
    print(f"✓ Scraping complete! Data saved to database and CSV.")

if __name__ == "__main__":
    main()
