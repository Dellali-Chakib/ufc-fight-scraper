import requests
from bs4 import BeautifulSoup
from datetime import date, datetime

from scraper.source import fetch_html, checked_page, profile_id, SourceError
import re


def get_fighter_details(url: str) -> dict:
    return parse_fighter_details(fetch_html(url), url)


def parse_fighter_details(html: str, url: str) -> dict:
    profile_id(url)
    page = checked_page(html, url)
    name = page.select_one('span.b-content__title-highlight')
    record = page.select_one('span.b-content__title-record')
    if not name or not name.get_text(strip=True) or name.get_text(strip=True).lower() == 'unknown' or not record or not re.fullmatch(r'Record:\s*\d+-\d+-\d+(?:\s*\(\d+ NC\))?', record.get_text(strip=True)):
        raise SourceError(f'Missing/invalid profile identity or record: {url}')

    fighter_data = {}

    name = page.find("span", class_="b-content__title-highlight")
    fighter_data["name"] = name.text.strip() if name else "Unknown"

    fighterDetails = page.find_all(
        "li", class_="b-list__box-list-item b-list__box-list-item_type_block"
    )
    
    for stats in fighterDetails:
        if not stats.i:
            continue
        label = stats.i.text.strip()
        stats.i.decompose()
        fighter_data[label.rstrip(":")] = stats.text.strip()

    required_labels = {'Height', 'Weight', 'Reach', 'STANCE', 'DOB', 'SLpM', 'Str. Acc.', 'SApM', 'Str. Def', 'TD Avg.', 'TD Acc.', 'TD Def.', 'Sub. Avg.'}
    if not required_labels.issubset(fighter_data):
        raise SourceError(f'Missing profile stat structure: {url}; absent={sorted(required_labels - fighter_data.keys())}')

    record = page.find("span", class_="b-content__title-record")
    if record:
        fighter_data["Record"] = record.text.strip().lstrip("Record:")

    event_dates = page.find_all("p", class_="b-fight-details__table-text")
    most_recent = None

    if len(event_dates) == 0:
        fighter_data["MostRecentFight"] = "Does Not Exist"
    else:
        for tag in event_dates:
            text = tag.text.strip()

            # Only check strings that look like valid dates with a '.' in fourth character
            if len(text) >= 10 and text[3] == ".":
                try:
                    # Remove period and parse date
                    date_str = text.replace(".", "")
                    date_obj = datetime.strptime(date_str, "%b %d, %Y")
                    if date_obj <= datetime.today():
                        if not most_recent or date_obj > most_recent:
                            most_recent = date_obj
                except ValueError:
                    continue  # Skip anything that fails to parse

        if most_recent:
            fighter_data["MostRecentFight"] = most_recent.strftime("%b %d, %Y")
        else:
            fighter_data["MostRecentFight"] = "Does Not Exist"

    fight_info_tags = page.find_all("a" ,  class_ ="b-link b-link_style_black")
    ufc_fights = 0
    for tag in fight_info_tags:
        if "UFC" in tag.text:
            ufc_fights += 1


    fighter_data['fightswithinufc'] = str(ufc_fights)

    return fighter_data
