import re

def clean_fighter_stats(fighters: list[dict]) -> list[dict]:
    """
    Strips whitespace from keys and values in each fighter's dictionary.
    
    Args:
        fighters (list[dict]): List of fighter dictionaries.

    Returns:
        list[dict]: Cleaned list of fighter dictionaries.
    """
    pattern = '[^a-zA-Z]' #Matches anything that is not letters

    cleaned_fighters = []
    
    for fighter in fighters: 
        cleaned_fighter = {}
        for key, value in fighter.items():
            clean_key = re.sub(pattern, '', key).lower()
            if clean_key:  # only add non-empty keys
              cleaned_fighter[clean_key] = value.strip()
            
        cleaned_fighters.append(cleaned_fighter)

    return cleaned_fighters



'''
{'url': 'http://ufcstats.com/fighter-details/1338e2c7480bdf9e', 'name': 'Israel Adesanya', 'Height': '6\' 4"', 'Weight': '185 lbs.', 
'Reach': '80"', 'STANCE': 'Switch', 'DOB': 'Jul 22, 1989', 'SLpM': '4.02', 'Str. Acc.': '48%', 'SApM': '3.20', 
'Str. Def': '55%', 'TD Avg.': '0.05', 'TD Acc.': '11%', 'TD Def.': '76%', 
'Sub. Avg.': '0.1', 'Record': '24-5-0', 'MostRecentFight': 'Feb. 01, 2025'}
'''