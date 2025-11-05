"""
===============================================================================
UFC FIGHTER DATABASE MODULE - PHASE 1: LEARNING SQLAlchemy ORM
===============================================================================

This module demonstrates how to integrate SQLAlchemy with your UFC scraper.
It's designed to help you learn the core concepts of Object-Relational Mapping (ORM)
while providing a working database layer.

KEY CONCEPTS YOU'LL LEARN:
--------------------------
1. What is an ORM?
   - ORM = Object-Relational Mapping
   - It's a technique that lets you interact with a database using Python objects
     instead of writing raw SQL queries
   - Think of it as a "translator" between Python classes and database tables

2. What is declarative_base?
   - It's the foundation for all your ORM models
   - When you inherit from Base, SQLAlchemy knows this class should be a database table
   - It tracks all your models and can create the actual database schema

3. What is a Session?
   - A session is like a "workspace" for database operations
   - It keeps track of all changes you make (adds, updates, deletes)
   - Changes aren't saved to the database until you call session.commit()
   - Think of it like a shopping cart - you add items, then "checkout" (commit)

4. Why SQLAlchemy?
   - Database-agnostic (works with SQLite, PostgreSQL, MySQL, etc.)
   - Write Python instead of SQL (but you can still use SQL if needed)
   - Automatic migrations and schema management
   - Built-in connection pooling and session management
"""

from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import os

# =============================================================================
# STEP 1: Create the Base Class (Foundation for all models)
# =============================================================================
# declarative_base() returns a class that serves as a foundation for all ORM models.
# Any class that inherits from Base will automatically be tracked by SQLAlchemy
# and can be mapped to a database table.
Base = declarative_base()


# =============================================================================
# STEP 2: Define the FighterDB Model (Maps to a database table)
# =============================================================================
class FighterDB(Base):
    """
    FighterDB is an ORM model that represents the 'fighters' table in the database.
    
    HOW IT WORKS:
    -------------
    - __tablename__ = 'fighters' → Creates a table called "fighters"
    - Each Column() maps to a column in that table
    - Column(Integer, primary_key=True) → Creates an auto-incrementing ID
    - Column(String(255)) → Creates a text field with max length 255
    - Column(Float) → Creates a decimal number field
    - Column(Boolean) → Creates a true/false field
    
    MAPPING TO YOUR FIGHTER CLASS:
    -------------------------------
    Your Fighter class (fighter_model.py) is a Python object that holds data temporarily.
    FighterDB is the DATABASE VERSION - it persists data permanently to disk.
    
    Fighter (in-memory) → FighterDB (persistent) → Database Table
    """
    
    __tablename__ = 'fighters'
    
    # Primary Key: Unique identifier for each fighter
    # autoincrement=True means the database automatically assigns IDs (1, 2, 3, ...)
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Fighter identifying information
    name = Column(String(255), nullable=False, index=True)  # index=True makes searches faster
    url = Column(String(500), unique=True, nullable=False)  # unique=True prevents duplicates
    
    # Physical attributes (nullable=True allows None/NULL values)
    height = Column(Integer, nullable=True)              # Height in inches
    weight = Column(String(50), nullable=True)           # e.g., "170 lbs."
    weight_class = Column(String(100), nullable=True)    # e.g., "Welterweight"
    reach = Column(Integer, nullable=True)               # Reach in inches
    stance = Column(String(50), nullable=True)           # e.g., "Orthodox"
    dob = Column(String(50), nullable=True)              # Date of birth string
    
    # Fighting statistics (Float for decimal numbers like 3.45)
    slpm = Column(Float, nullable=True)      # Significant strikes landed per minute
    stracc = Column(Float, nullable=True)    # Striking accuracy (0.0 to 1.0)
    sapm = Column(Float, nullable=True)      # Significant strikes absorbed per minute
    strdef = Column(Float, nullable=True)    # Striking defense (0.0 to 1.0)
    tdavg = Column(Float, nullable=True)     # Takedown average per 15 minutes
    tdacc = Column(Float, nullable=True)     # Takedown accuracy (0.0 to 1.0)
    tddef = Column(Float, nullable=True)     # Takedown defense (0.0 to 1.0)
    subavg = Column(Float, nullable=True)    # Submission average per 15 minutes
    
    # Fight history
    record = Column(String(50), nullable=True)              # e.g., "22-6-0"
    most_recent_fight = Column(Integer, nullable=True)      # Days since last fight
    fight_count = Column(Integer, nullable=True)            # Total career fights
    fights_in_ufc = Column(String(10), nullable=True)       # Number of UFC fights
    bad_sample = Column(Boolean, default=False)             # Data quality flag
    
    def __repr__(self):
        """
        String representation of the object (useful for debugging).
        When you print a FighterDB object, you'll see this format.
        """
        return f"<Fighter(id={self.id}, name='{self.name}', weight_class='{self.weight_class}')>"
    
    @classmethod
    def from_fighter(cls, fighter):
        """
        Class method to convert a Fighter object to a FighterDB object.
        
        WHAT IS A CLASS METHOD?
        -----------------------
        - @classmethod decorator lets you call this without creating an instance
        - Usage: fighter_db = FighterDB.from_fighter(my_fighter)
        - It's a "factory method" that creates FighterDB instances from Fighter instances
        
        WHY DO WE NEED THIS?
        --------------------
        Your scraper creates Fighter objects (from fighter_model.py).
        This method converts them to FighterDB objects (ready for database storage).
        
        PARAMETERS:
        -----------
        cls : FighterDB class itself
        fighter : Fighter object from fighter_model.py
        
        RETURNS:
        --------
        A new FighterDB instance with all the fighter's data
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


# =============================================================================
# STEP 3: Database Engine Setup (The connection to the database)
# =============================================================================
def get_engine(db_path='ufc_fighters.db'):
    """
    Creates and returns a SQLAlchemy engine.
    
    WHAT IS AN ENGINE?
    ------------------
    - The engine is the connection interface to your database
    - It handles all low-level database communication
    - You create it once and reuse it throughout your application
    
    DATABASE URL FORMAT:
    --------------------
    'sqlite:///ufc_fighters.db'
         ↓        ↓
      dialect   path
    
    - sqlite:/// → Use SQLite database (3 slashes for relative path)
    - ufc_fighters.db → Database file (created in current directory if doesn't exist)
    - For PostgreSQL later: 'postgresql://user:password@localhost/dbname'
    
    PARAMETERS:
    -----------
    db_path : str
        Path to the SQLite database file
    
    RETURNS:
    --------
    engine : SQLAlchemy Engine object
    """
    # Create the database URL (SQLite format)
    database_url = f'sqlite:///{db_path}'
    
    # create_engine establishes the connection strategy
    # echo=False means don't print SQL queries (set to True for debugging)
    engine = create_engine(database_url, echo=False)
    
    print(f"✓ Database engine created: {db_path}")
    return engine


# =============================================================================
# STEP 4: Session Factory (Creates "workspaces" for database operations)
# =============================================================================
def get_session(engine):
    """
    Creates and returns a new database session.
    
    WHAT IS A SESSION?
    ------------------
    - A session is your "workspace" for interacting with the database
    - It tracks all objects you add, modify, or delete
    - Changes are only saved when you call session.commit()
    - If something goes wrong, you can call session.rollback() to undo changes
    
    SESSION LIFECYCLE:
    ------------------
    1. Create session
    2. Add/query/update objects
    3. Commit changes (or rollback on error)
    4. Close session
    
    IMPORTANT:
    ----------
    Always close your session when done (use context manager or try/finally)
    
    PARAMETERS:
    -----------
    engine : SQLAlchemy Engine
    
    RETURNS:
    --------
    session : SQLAlchemy Session object
    """
    # sessionmaker is a factory that produces Session objects
    # bind=engine connects the session to our database
    Session = sessionmaker(bind=engine)
    return Session()


# =============================================================================
# STEP 5: Initialize Database (Create all tables)
# =============================================================================
def init_database(engine):
    """
    Creates all database tables defined by our models.
    
    WHAT DOES THIS DO?
    ------------------
    - Looks at all classes that inherit from Base (e.g., FighterDB)
    - Reads their Column definitions
    - Generates CREATE TABLE SQL statements
    - Executes them to create the actual database tables
    
    WHEN TO CALL THIS:
    ------------------
    - First time you set up the database
    - After adding new models
    - If you delete the database file and need to recreate it
    
    NOTE:
    -----
    This creates tables but doesn't modify existing ones.
    For schema changes, you'll need migrations (Phase 2 with Alembic).
    
    PARAMETERS:
    -----------
    engine : SQLAlchemy Engine
    """
    # Base.metadata contains information about all our models
    # create_all() generates and runs CREATE TABLE statements
    Base.metadata.create_all(engine)
    print("✓ Database tables created successfully!")


# =============================================================================
# STEP 6: Add Fighters to Database (Bulk insert function)
# =============================================================================
def add_fighters(fighters, engine):
    """
    Adds a list of Fighter objects to the database.
    
    HOW IT WORKS:
    -------------
    1. Convert Fighter objects → FighterDB objects (ORM models)
    2. Add them to a session (staging area)
    3. Commit the session (save to database)
    4. Handle any errors gracefully
    
    TRANSACTION SAFETY:
    -------------------
    - session.commit() saves all changes as a single atomic operation
    - If anything fails, session.rollback() undoes all changes
    - This ensures data consistency (all-or-nothing)
    
    PARAMETERS:
    -----------
    fighters : list
        List of Fighter objects (from fighter_model.py)
    engine : SQLAlchemy Engine
    
    RETURNS:
    --------
    int : Number of fighters successfully added
    """
    session = get_session(engine)
    added_count = 0
    
    try:
        print(f"\n📊 Preparing to add {len(fighters)} fighters to database...")
        
        for fighter in fighters:
            # Convert Fighter → FighterDB using our class method
            fighter_db = FighterDB.from_fighter(fighter)
            
            # Add to session (not yet saved to database)

            session.merge(fighter_db)
            added_count += 1
        
        # IMPORTANT: This is where data actually gets saved!
        # commit() executes SQL INSERT statements for all added objects
        session.commit()
        print(f"✓ Successfully added {added_count} fighters to database!")
        
    except Exception as e:
        # If anything goes wrong, rollback (undo) all changes
        session.rollback()
        print(f"✗ Error adding fighters to database: {e}")
        raise
    
    finally:
        # Always close the session to free up resources
        session.close()
    
    return added_count


# =============================================================================
# STEP 7: Query Functions (Retrieve data from database)
# =============================================================================
def get_all_fighters(engine):
    """
    Retrieves all fighters from the database.
    
    QUERYING WITH SQLAlchemy:
    -------------------------
    - session.query(FighterDB) → "SELECT * FROM fighters"
    - .all() → Returns a list of all results
    - .first() → Returns only the first result
    - .filter_by(name='Conor McGregor') → Adds WHERE clause
    
    RETURNS:
    --------
    list : List of FighterDB objects
    """
    session = get_session(engine)
    try:
        # This translates to: SELECT * FROM fighters
        fighters = session.query(FighterDB).all()
        print(f"✓ Retrieved {len(fighters)} fighters from database")
        return fighters
    finally:
        session.close()


def get_fighters_by_weight_class(weight_class, engine):
    """
    Retrieves fighters from a specific weight class.
    
    PARAMETERS:
    -----------
    weight_class : str
        Weight class name (e.g., "Welterweight")
    engine : SQLAlchemy Engine
    
    RETURNS:
    --------
    list : List of FighterDB objects in that weight class
    """
    session = get_session(engine)
    try:
        # This translates to: SELECT * FROM fighters WHERE weight_class = ?
        fighters = session.query(FighterDB).filter_by(weight_class=weight_class).all()
        print(f"✓ Found {len(fighters)} fighters in {weight_class}")
        return fighters
    finally:
        session.close()


def get_fighter_by_name(name, engine):
    """
    Retrieves a specific fighter by name.
    
    PARAMETERS:
    -----------
    name : str
        Fighter's name
    engine : SQLAlchemy Engine
    
    RETURNS:
    --------
    FighterDB object or None
    """
    session = get_session(engine)
    try:
        # .first() returns the first match or None
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
    
    RETURNS:
    --------
    int : Count of fighters
    """
    session = get_session(engine)
    try:
        # .count() translates to: SELECT COUNT(*) FROM fighters
        count = session.query(FighterDB).count()
        return count
    finally:
        session.close()


# =============================================================================
# STEP 8: Utility Functions
# =============================================================================
def clear_database(engine):
    """
    Deletes all fighters from the database (useful for testing).
    
    WARNING: This permanently deletes all data!
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
    
    RETURNS:
    --------
    bool : True if database exists, False otherwise
    """
    return os.path.exists(db_path)


# =============================================================================
# EXAMPLE USAGE (for learning purposes)
# =============================================================================
if __name__ == "__main__":
    """
    This section runs when you execute: python scraper/database.py
    It demonstrates basic database operations.
    """
    print("=" * 80)
    print("UFC FIGHTER DATABASE - DEMONSTRATION")
    print("=" * 80)
    
    # Step 1: Create engine (connection to database)
    engine = get_engine('test_ufc.db')
    
    # Step 2: Initialize database (create tables)
    init_database(engine)
    
    # Step 3: Check fighter count
    count = get_fighter_count(engine)
    print(f"\nCurrent fighter count: {count}")
    
    print("\n" + "=" * 80)
    print("To use this with your scraper, see updated stat_scraper.py")
    print("=" * 80)

