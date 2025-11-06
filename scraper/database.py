"""
UFC Fighter Database Module

SQLAlchemy ORM implementation for persisting UFC fighter data.
Uses SQLite for local storage with support for upsert operations.
"""

from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import os

# Base class for all ORM models
Base = declarative_base()


class FighterDB(Base):
    """
    ORM model for the fighters table.
    Maps Fighter objects from the scraper to persistent database records.
    """
    
    __tablename__ = 'fighters'
    
    # Primary key - auto-incrementing ID
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Fighter identification
    name = Column(String(255), nullable=False, index=True)
    url = Column(String(500), unique=True, nullable=False)  # Unique constraint prevents duplicates
    
    # Physical attributes
    height = Column(Integer, nullable=True)
    weight = Column(String(50), nullable=True)
    weight_class = Column(String(100), nullable=True)
    reach = Column(Integer, nullable=True)
    stance = Column(String(50), nullable=True)
    dob = Column(String(50), nullable=True)
    
    # Fighting statistics
    slpm = Column(Float, nullable=True)
    stracc = Column(Float, nullable=True)
    sapm = Column(Float, nullable=True)
    strdef = Column(Float, nullable=True)
    tdavg = Column(Float, nullable=True)
    tdacc = Column(Float, nullable=True)
    tddef = Column(Float, nullable=True)
    subavg = Column(Float, nullable=True)
    
    # Fight history
    record = Column(String(50), nullable=True)
    most_recent_fight = Column(Integer, nullable=True)
    fight_count = Column(Integer, nullable=True)
    fights_in_ufc = Column(String(10), nullable=True)
    bad_sample = Column(Boolean, default=False)
    
    def __repr__(self):
        """String representation for debugging."""
        return f"<Fighter(id={self.id}, name='{self.name}', weight_class='{self.weight_class}')>"
    
    @classmethod
    def from_fighter(cls, fighter):
        """
        Factory method to convert a Fighter object to a FighterDB instance.
        
        Args:
            fighter: Fighter object from fighter_model.py
        
        Returns:
            FighterDB instance ready for database persistence
        """
        return cls(
            name=fighter.name,
            url=fighter.url,
            height=fighter.height,
            weight=fighter.weight,
            weight_class=fighter.weight_class,
            reach=fighter.reach,
            stance=fighter.stance,
            dob=fighter.dob,
            slpm=fighter.slpm,
            stracc=fighter.stracc,
            sapm=fighter.sapm,
            strdef=fighter.strdef,
            tdavg=fighter.tdavg,
            tdacc=fighter.tdacc,
            tddef=fighter.tddef,
            subavg=fighter.subavg,
            record=fighter.record,
            most_recent_fight=fighter.most_recent_fight,
            fight_count=fighter.fight_count,
            fights_in_ufc=fighter.fightswithinufc,
            bad_sample=fighter.bad_sample
        )


def get_engine(db_path='ufc_fighters.db'):
    """
    Creates a SQLAlchemy engine for database connection.
    
    Args:
        db_path: Path to the SQLite database file
    
    Returns:
        SQLAlchemy Engine instance
    """
    database_url = f'sqlite:///{db_path}'
    engine = create_engine(database_url, echo=False)
    print(f"✓ Database engine created: {db_path}")
    return engine


def get_session(engine):
    """
    Creates a new database session.
    
    Args:
        engine: SQLAlchemy Engine instance
    
    Returns:
        SQLAlchemy Session for database operations
    """
    Session = sessionmaker(bind=engine)
    return Session()


def init_database(engine):
    """
    Creates all database tables from the Base models.
    Safe to call multiple times - only creates tables that don't exist.
    
    Args:
        engine: SQLAlchemy Engine instance
    """
    Base.metadata.create_all(engine)
    print("✓ Database tables created successfully!")


def add_fighters(fighters, engine):
    """
    Adds or updates fighters using upsert logic (insert or update if exists).
    
    Implementation notes:
    - Queries by URL (unique field) to check for existing records
    - Updates all fields if fighter exists, inserts if new
    - Uses atomic transaction - all changes commit together or roll back on error
    
    Args:
        fighters: List of Fighter objects from fighter_model.py
        engine: SQLAlchemy Engine instance
    
    Returns:
        int: Total number of fighters processed
    """
    session = get_session(engine)
    added_count = 0
    updated_count = 0
    
    try:
        print(f"\n📊 Preparing to upsert {len(fighters)} fighters to database...")
        
        for fighter in fighters:
            fighter_db = FighterDB.from_fighter(fighter)
            existing_fighter = session.query(FighterDB).filter_by(url=fighter.url).first()
            
            if existing_fighter:
                # Update existing record with current data
                existing_fighter.name = fighter.name
                existing_fighter.height = fighter.height
                existing_fighter.weight = fighter.weight
                existing_fighter.weight_class = fighter.weight_class
                existing_fighter.reach = fighter.reach
                existing_fighter.stance = fighter.stance
                existing_fighter.dob = fighter.dob
                existing_fighter.slpm = fighter.slpm
                existing_fighter.stracc = fighter.stracc
                existing_fighter.sapm = fighter.sapm
                existing_fighter.strdef = fighter.strdef
                existing_fighter.tdavg = fighter.tdavg
                existing_fighter.tdacc = fighter.tdacc
                existing_fighter.tddef = fighter.tddef
                existing_fighter.subavg = fighter.subavg
                existing_fighter.record = fighter.record
                existing_fighter.most_recent_fight = fighter.most_recent_fight
                existing_fighter.fight_count = fighter.fight_count
                existing_fighter.fights_in_ufc = fighter.fightswithinufc
                existing_fighter.bad_sample = fighter.bad_sample
                updated_count += 1
            else:
                # Insert new fighter
                session.add(fighter_db)
                added_count += 1
        
        session.commit()
        print(f"✓ Successfully processed {len(fighters)} fighters:")
        print(f"  • {added_count} new fighters added")
        print(f"  • {updated_count} existing fighters updated")
        
    except Exception as e:
        session.rollback()
        print(f"✗ Error adding fighters to database: {e}")
        raise
    
    finally:
        session.close()
    
    return added_count + updated_count


def get_all_fighters(engine):
    """
    Retrieves all fighters from the database.
    
    Args:
        engine: SQLAlchemy Engine instance
    
    Returns:
        list: List of FighterDB objects
    """
    session = get_session(engine)
    try:
        fighters = session.query(FighterDB).all()
        print(f"✓ Retrieved {len(fighters)} fighters from database")
        return fighters
    finally:
        session.close()


def get_fighters_by_weight_class(weight_class, engine):
    """
    Retrieves fighters from a specific weight class.
    
    Args:
        weight_class: Weight class name (e.g., "Welterweight")
        engine: SQLAlchemy Engine instance
    
    Returns:
        list: List of FighterDB objects in that weight class
    """
    session = get_session(engine)
    try:
        fighters = session.query(FighterDB).filter_by(weight_class=weight_class).all()
        print(f"✓ Found {len(fighters)} fighters in {weight_class}")
        return fighters
    finally:
        session.close()


def get_fighter_by_name(name, engine):
    """
    Retrieves a specific fighter by name.
    
    Args:
        name: Fighter's name
        engine: SQLAlchemy Engine instance
    
    Returns:
        FighterDB object or None if not found
    """
    session = get_session(engine)
    try:
        fighter = session.query(FighterDB).filter_by(name=name).first()
        if fighter:
            print(f"✓ Found fighter: {fighter.name}")
        else:
            print(f"✗ Fighter not found: {name}")
        return fighter
    finally:
        session.close()


def get_fighter_count(engine):
    """
    Returns the total number of fighters in the database.
    
    Args:
        engine: SQLAlchemy Engine instance
    
    Returns:
        int: Count of fighters
    """
    session = get_session(engine)
    try:
        count = session.query(FighterDB).count()
        return count
    finally:
        session.close()


def clear_database(engine):
    """
    Deletes all fighters from the database.
    WARNING: This permanently deletes all data.
    
    Args:
        engine: SQLAlchemy Engine instance
    """
    session = get_session(engine)
    try:
        deleted = session.query(FighterDB).delete()
        session.commit()
        print(f"✓ Cleared {deleted} fighters from database")
    except Exception as e:
        session.rollback()
        print(f"✗ Error clearing database: {e}")
        raise
    finally:
        session.close()


def database_exists(db_path='ufc_fighters.db'):
    """
    Checks if the database file exists.
    
    Args:
        db_path: Path to the database file
    
    Returns:
        bool: True if database exists, False otherwise
    """
    return os.path.exists(db_path)


if __name__ == "__main__":
    """Basic database operations demonstration."""
    print("=" * 80)
    print("UFC FIGHTER DATABASE - DEMONSTRATION")
    print("=" * 80)
    
    engine = get_engine('test_ufc.db')
    init_database(engine)
    
    count = get_fighter_count(engine)
    print(f"\nCurrent fighter count: {count}")
    
    print("\n" + "=" * 80)
    print("To use this with your scraper, see updated stat_scraper.py")
    print("=" * 80)

