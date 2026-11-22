"""Run a validated refresh; source failures must fail the workflow."""
import sys
from scraper.stat_scraper import main

if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'Fighter refresh failed; publication stopped: {error}', file=sys.stderr)
        sys.exit(1)
