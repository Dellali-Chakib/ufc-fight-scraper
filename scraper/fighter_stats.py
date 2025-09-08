import requests
from bs4 import BeautifulSoup
from datetime import date, datetime

def get_fighter_details(url: str) -> dict:
    
    response = requests.get(url)
    page = BeautifulSoup(response.text, "html.parser")

    fighter_data = {}

    name = page.find("span", class_="b-content__title-highlight")
    fighter_data["name"] = name.text.strip() if name else "Unknown"

    fighterDetails = page.find_all(
        "li", class_="b-list__box-list-item b-list__box-list-item_type_block"
    )
    
    for stats in fighterDetails:
        label = stats.i.text.strip()
        stats.i.decompose()
        fighter_data[label.rstrip(":")] = stats.text.strip()

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
