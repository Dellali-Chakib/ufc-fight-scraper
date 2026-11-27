"""Collect event candidates by default; publication requires a reviewed candidate."""
import argparse
from pathlib import Path
from scraper.event_refresh import main

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    mode=p.add_mutually_exclusive_group()
    mode.add_argument('--dry-run',action='store_true')
    mode.add_argument('--publish-candidate',type=Path)
    p.add_argument('--pace',type=float,default=1)
    p.add_argument('--budget',type=int,default=5400)
    p.add_argument('--workers',type=int,default=4)
    p.add_argument('--max-events',type=int,default=3)
    p.add_argument('--listing-limit',type=int,default=100)
    a=p.parse_args()
    if a.max_events<1 or not 1<=a.listing_limit<=500:
        p.error('Invalid event/listing bounds')
    try:
        main(reviewed=a.publish_candidate,pace=a.pace,budget=a.budget,workers=a.workers,
             max_events=a.max_events,listing_limit=a.listing_limit)
    except Exception as exc:
        p.exit(1,f'Event refresh failed; published state unchanged: {exc}\n')
