"""
UFC Fighter Scraper - Main Entry Point

Run this script to scrape UFC fighter data and save to database.

Usage:
    python run_scraper.py

This script properly handles Python path issues and runs the scraper.
"""

if __name__ == "__main__":
    # Import and run the main scraper
    from scraper.stat_scraper import main
    
    print("="*80)
    print("UFC FIGHTER DATA SCRAPER - Phase 1 (Database Integration)")
    print("="*80)
    print("Starting scraper...")
    print("This will scrape ufcstats.com and save data to 'ufc_fighters.db'\n")
    
    main()

