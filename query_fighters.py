"""
===============================================================================
UFC FIGHTER DATABASE - QUERY EXAMPLES (Learning Script)
===============================================================================

This script demonstrates how to query and interact with your UFC fighter database.
Run this AFTER you've scraped data using stat_scraper.py.

PURPOSE:
--------
This is a hands-on tutorial showing you how to:
1. Connect to the database
2. Perform various queries (SELECT statements)
3. Filter and sort data
4. Use SQLAlchemy's query API

USAGE:
------
Run this script: python query_fighters.py

Make sure you've run stat_scraper.py first to populate the database!
"""

from scraper.database import (
    get_engine,
    get_session,
    FighterDB,
    get_all_fighters,
    get_fighters_by_weight_class,
    get_fighter_by_name,
    get_fighter_count
)


def example_1_basic_queries():
    """
    EXAMPLE 1: Basic Database Queries
    
    LEARNING OBJECTIVES:
    --------------------
    - How to get total count of records
    - How to retrieve all records
    - How to access attributes of ORM objects
    """
    print("\n" + "="*80)
    print("EXAMPLE 1: BASIC QUERIES")
    print("="*80)
    
    engine = get_engine('ufc_fighters.db')
    
    # Query 1: Get total count
    print("\n📊 Query 1: Total Fighters in Database")
    print("-" * 40)
    count = get_fighter_count(engine)
    print(f"Total fighters: {count}")
    
    # Query 2: Get first 5 fighters
    print("\n📊 Query 2: First 5 Fighters")
    print("-" * 40)
    all_fighters = get_all_fighters(engine)
    for fighter in all_fighters[:5]:
        print(f"  • {fighter.name} ({fighter.weight_class}) - Record: {fighter.record}")


def example_2_filtering():
    """
    EXAMPLE 2: Filtering Data (WHERE clauses)
    
    LEARNING OBJECTIVES:
    --------------------
    - How to filter by specific attributes
    - Understanding filter() vs filter_by()
    - Chaining multiple filters
    """
    print("\n" + "="*80)
    print("EXAMPLE 2: FILTERING DATA")
    print("="*80)
    
    engine = get_engine('ufc_fighters.db')
    session = get_session(engine)
    
    try:
        # Filter 1: Get all Welterweights
        print("\n📊 Filter 1: All Welterweight Fighters")
        print("-" * 40)
        welterweights = session.query(FighterDB).filter_by(weight_class='Welterweight').all()
        print(f"Found {len(welterweights)} welterweights")
        for fighter in welterweights[:5]:  # Show first 5
            print(f"  • {fighter.name} - Reach: {fighter.reach}\"")
        
        # Filter 2: Get fighters with high striking accuracy (> 50%)
        print("\n📊 Filter 2: Fighters with Striking Accuracy > 50%")
        print("-" * 40)
        # Note: filter() uses Python expressions, filter_by() uses keyword arguments
        accurate_strikers = session.query(FighterDB).filter(FighterDB.stracc > 0.5).all()
        print(f"Found {len(accurate_strikers)} fighters with >50% striking accuracy")
        
        # Show top 5 by accuracy
        sorted_strikers = sorted(accurate_strikers, key=lambda x: x.stracc or 0, reverse=True)
        for fighter in sorted_strikers[:5]:
            print(f"  • {fighter.name} - {fighter.stracc*100:.1f}% accuracy")
        
        # Filter 3: Combine multiple conditions (AND)
        print("\n📊 Filter 3: Lightweight Southpaws")
        print("-" * 40)
        southpaw_lightweights = (session.query(FighterDB)
                                 .filter_by(weight_class='Lightweight', stance='Southpaw')
                                 .all())
        print(f"Found {len(southpaw_lightweights)} Lightweight Southpaws")
        for fighter in southpaw_lightweights[:5]:
            print(f"  • {fighter.name}")
            
    finally:
        session.close()


def example_3_sorting():
    """
    EXAMPLE 3: Sorting and Ordering Results
    
    LEARNING OBJECTIVES:
    --------------------
    - How to use order_by() for sorting
    - Ascending vs descending order
    - Sorting by multiple columns
    """
    print("\n" + "="*80)
    print("EXAMPLE 3: SORTING DATA")
    print("="*80)
    
    engine = get_engine('ufc_fighters.db')
    session = get_session(engine)
    
    try:
        # Sort 1: Fighters by reach (tallest reach first)
        print("\n📊 Sort 1: Longest Reaches")
        print("-" * 40)
        # desc() means descending order (highest to lowest)
        from sqlalchemy import desc
        long_reach_fighters = (session.query(FighterDB)
                               .filter(FighterDB.reach.isnot(None))
                               .order_by(desc(FighterDB.reach))
                               .limit(5)
                               .all())
        for fighter in long_reach_fighters:
            print(f"  • {fighter.name} - {fighter.reach}\" reach ({fighter.height}\" tall)")
        
        # Sort 2: Most active fighters (by fight count)
        print("\n📊 Sort 2: Most Active Fighters")
        print("-" * 40)
        active_fighters = (session.query(FighterDB)
                          .filter(FighterDB.fight_count.isnot(None))
                          .order_by(desc(FighterDB.fight_count))
                          .limit(5)
                          .all())
        for fighter in active_fighters:
            print(f"  • {fighter.name} - {fighter.fight_count} total fights ({fighter.record})")
        
    finally:
        session.close()


def example_4_aggregations():
    """
    EXAMPLE 4: Aggregate Functions (AVG, MAX, MIN, COUNT)
    
    LEARNING OBJECTIVES:
    --------------------
    - How to use SQL aggregate functions
    - Computing averages, maximums, minimums
    - Grouping data
    """
    print("\n" + "="*80)
    print("EXAMPLE 4: AGGREGATE FUNCTIONS")
    print("="*80)
    
    engine = get_engine('ufc_fighters.db')
    session = get_session(engine)
    
    try:
        from sqlalchemy import func, desc
        
        # Aggregate 1: Average stats across all fighters
        print("\n📊 Aggregate 1: Average Stats Across All Fighters")
        print("-" * 40)
        avg_stats = session.query(
            func.avg(FighterDB.height).label('avg_height'),
            func.avg(FighterDB.reach).label('avg_reach'),
            func.avg(FighterDB.slpm).label('avg_slpm'),
            func.avg(FighterDB.stracc).label('avg_stracc')
        ).first()
        
        print(f"  Average Height: {avg_stats.avg_height:.1f} inches")
        print(f"  Average Reach: {avg_stats.avg_reach:.1f} inches")
        print(f"  Average SLpM: {avg_stats.avg_slpm:.2f}")
        print(f"  Average Striking Accuracy: {avg_stats.avg_stracc*100:.1f}%")
        
        # Aggregate 2: Count fighters by weight class
        print("\n📊 Aggregate 2: Fighters per Weight Class")
        print("-" * 40)
        weight_class_counts = (session.query(
            FighterDB.weight_class,
            func.count(FighterDB.id).label('count')
        )
        .group_by(FighterDB.weight_class)
        .order_by(func.count(FighterDB.id).desc())
        .all())
        
        for wc, count in weight_class_counts:
            if wc and wc != 'None':
                print(f"  • {wc}: {count} fighters")
        
        # Aggregate 3: Find fighter with highest takedown average
        print("\n📊 Aggregate 3: Best Takedown Artist")
        print("-" * 40)
        best_td = (session.query(FighterDB)
                  .filter(FighterDB.tdavg.isnot(None))
                  .order_by(desc(FighterDB.tdavg))
                  .first())
        if best_td:
            print(f"  • {best_td.name}: {best_td.tdavg} TDs/15min ({best_td.tdacc*100:.0f}% accuracy)")
        
    finally:
        session.close()


def example_5_specific_fighter():
    """
    EXAMPLE 5: Looking Up Specific Fighters
    
    LEARNING OBJECTIVES:
    --------------------
    - How to search by name
    - Accessing all attributes of a fighter
    - Handling None/NULL values
    """
    print("\n" + "="*80)
    print("EXAMPLE 5: SPECIFIC FIGHTER LOOKUP")
    print("="*80)
    
    engine = get_engine('ufc_fighters.db')
    
    # Try to find some well-known fighters
    fighter_names = ['Conor McGregor', 'Jon Jones', 'Khabib Nurmagomedov']
    
    for name in fighter_names:
        print(f"\n🔍 Searching for: {name}")
        print("-" * 40)
        fighter = get_fighter_by_name(name, engine)
        
        if fighter:
            print(f"  Name: {fighter.name}")
            print(f"  Weight Class: {fighter.weight_class}")
            print(f"  Record: {fighter.record}")
            print(f"  Stance: {fighter.stance}")
            print(f"  Height: {fighter.height}\" | Reach: {fighter.reach}\"")
            print(f"  Striking Accuracy: {fighter.stracc*100:.1f}%" if fighter.stracc else "  Striking Accuracy: N/A")
            print(f"  Total Fights: {fighter.fight_count}")
            print(f"  UFC Fights: {fighter.fights_in_ufc}")
            print(f"  Profile: {fighter.url}")


def example_6_custom_queries():
    """
    EXAMPLE 6: Advanced Custom Queries
    
    LEARNING OBJECTIVES:
    --------------------
    - Complex WHERE clauses
    - Using OR conditions
    - LIKE operator for pattern matching
    """
    print("\n" + "="*80)
    print("EXAMPLE 6: ADVANCED CUSTOM QUERIES")
    print("="*80)
    
    engine = get_engine('ufc_fighters.db')
    session = get_session(engine)
    
    try:
        from sqlalchemy import or_, and_
        
        # Query 1: Find fighters with names starting with "A"
        print("\n📊 Query 1: Fighters with names starting with 'A'")
        print("-" * 40)
        a_fighters = (session.query(FighterDB)
                     .filter(FighterDB.name.like('A%'))
                     .limit(10)
                     .all())
        for fighter in a_fighters:
            print(f"  • {fighter.name}")
        
        # Query 2: Fighters who are tall (>74") OR have long reach (>76")
        print("\n📊 Query 2: Tall Fighters (>74\") OR Long Reach (>76\")")
        print("-" * 40)
        tall_or_long = (session.query(FighterDB)
                       .filter(or_(FighterDB.height > 74, FighterDB.reach > 76))
                       .limit(10)
                       .all())
        for fighter in tall_or_long:
            print(f"  • {fighter.name} - Height: {fighter.height}\", Reach: {fighter.reach}\"")
        
        # Query 3: Well-rounded fighters (good striking AND takedown defense)
        print("\n📊 Query 3: Well-Rounded Fighters (StrDef>60% AND TDDef>70%)")
        print("-" * 40)
        well_rounded = (session.query(FighterDB)
                       .filter(and_(FighterDB.strdef > 0.6, FighterDB.tddef > 0.7))
                       .limit(10)
                       .all())
        for fighter in well_rounded:
            print(f"  • {fighter.name} - StrDef: {fighter.strdef*100:.0f}%, TDDef: {fighter.tddef*100:.0f}%")
        
    finally:
        session.close()


def main():
    """
    Main function - runs all examples
    """
    print("="*80)
    print("UFC FIGHTER DATABASE - INTERACTIVE QUERY TUTORIAL")
    print("="*80)
    print("\nThis script demonstrates various ways to query your fighter database.")
    print("Each example includes educational comments explaining the concepts.")
    
    # Check if database exists
    import os
    if not os.path.exists('ufc_fighters.db'):
        print("\n⚠️  ERROR: Database file 'ufc_fighters.db' not found!")
        print("Please run stat_scraper.py first to create and populate the database.")
        return
    
    try:
        # Run all examples
        example_1_basic_queries()
        example_2_filtering()
        example_3_sorting()
        example_4_aggregations()
        example_5_specific_fighter()
        example_6_custom_queries()
        
        print("\n" + "="*80)
        print("TUTORIAL COMPLETE!")
        print("="*80)
        print("\n💡 Next Steps:")
        print("  1. Modify these queries to explore your data")
        print("  2. Try creating your own custom queries")
        print("  3. Look at scraper/database.py for more query functions")
        print("  4. In Phase 2, we'll add FastAPI to expose this data via REST API")
        print("\n")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("Make sure you've run stat_scraper.py to populate the database first.")


if __name__ == "__main__":
    main()

