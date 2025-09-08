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
            href = tag["href"]
            if "fighter-details" in href:
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
                    if resp.status != 200:
                        raise aiohttp.ClientResponseError(
                            status=resp.status, message=f"Bad status {resp.status}"
                        )
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

def main():
    start = time.time()
    fighter_urls = asyncio.run(get_all_fighter_urls())
    fighters = [{"url": url} for url in fighter_urls]
    print(f"Total fighters found: {len(fighters)}")

    asyncio.run(fetch_all_names_and_stats(fighters))

    print("\nCleaning fighter stats...")
    fighters = clean_fighter_stats(fighters)

    # Ensure all required keys exist before creating Fighter objects
    required_fields = ['height', 'weight', 'reach', 'stance', 'dob', 'slpm', 'stracc',
                       'sapm', 'strdef', 'tdavg', 'tdacc', 'tddef', 'subavg', 'record',
                       'mostrecentfight', 'fightswithinufc']
    for fighter_data in fighters:
        for field in required_fields:
            fighter_data.setdefault(field, None)

    print("Instantiating Fighter objects...")
    fighter_class_list = [Fighter(**fighter_data) for fighter_data in fighters]

    print("Filtering fighters...")
    good_fighters = [f for f in fighter_class_list if not f.bad_sample]
    print(f"Active/valid fighters: {len(good_fighters)}")

    write_csv(good_fighters)
    end = time.time()
    elapsed = end - start
    print(f'Elapsed time: {elapsed:.6f} seconds')

if __name__ == "__main__":
    main()
