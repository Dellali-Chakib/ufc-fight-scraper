import asyncio
import aiohttp 
import requests
import time
from bs4 import BeautifulSoup
alphabet = [
'a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k', 'l', 'm',
'n', 'o', 'p', 'q', 'r', 's', 't', 'u', 'v', 'w', 'x', 'y', 'z'
]
ufc_site_url = "http://ufcstats.com/statistics/fighters?char={}&page=all"
stat_pages = []
fighers = []

def parse_list_pages(session):
    tasks = []
    for letter in alphabet:
        tasks.append(asyncio.create_task(session.get(ufc_site_url.format(letter), ssl= False)))
    return tasks

async def fetch_list_pages():
    """
    Fetches fighter profile URLs from the UFC stats site for a given letter and page.
    """
    
    async with aiohttp.ClientSession() as session: 
        tasks = get_tasks(session)
        responses = await asyncio.gather(*tasks)
        for response in responses:
            stat_pages.append(await response.text())



    # url = "http://ufcstats.com/statistics/fighters?char={}&page=all"
    # response = requests.get(url.format(letter))
    # time.sleep(1)
    # soup = BeautifulSoup(response.text, "html.parser")

    # fighters = []
    # for tag in soup.find_all("a", href=True):
    #     href = tag["href"]
    #     if "fighter-details" in href:
    #         if href not in [f["url"] for f in fighters]:
    #             fighters.append({"url": href})
async def fetch_fighter_pages():
    return

def parse_fighter_pages():
    return
    



