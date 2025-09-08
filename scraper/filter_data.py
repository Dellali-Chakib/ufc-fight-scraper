
def filter_fighters(fighters):
    good_fighters = []
    for fighter in fighters:
        if(fighter.bad_sample == False):
            good_fighters.append(fighter)
    
    return good_fighters