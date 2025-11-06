# UFC Fighter Stats Scraper & API

A production-ready UFC fighter statistics scraper with REST API and automated updates.

## Features

- **Data Collection**: Async scraping of 700+ UFC fighters from ufcstats.com
- **Database**: SQLAlchemy ORM with SQLite (PostgreSQL-ready)
  - **Safe UPSERT Logic**: Prevents duplicate entries and UNIQUE constraint errors
  - Reliable reruns in GitHub Actions environments
- **REST API**: FastAPI with automatic documentation (Swagger UI)
- **Automation**: API-triggered and scheduled updates via GitHub Actions
- **CSV Export**: Automatic CSV generation for data analysis
- **Query Tools**: Interactive database query examples and tutorials

## Quick Start

```bash
# 1. Setup
python -m venv venv
.\venv\Scripts\activate  # Windows
source venv/bin/activate  # macOS/Linux
pip install -r requirements.txt

# 2. Scrape data (creates ufc_fighters.db + output.csv)
python run_scraper.py

# 3. Start API
uvicorn app:app --reload

# 4. (Optional) Explore database with query examples
python query_fighters.py
```

Visit http://localhost:8000/docs for interactive API documentation.

**Output files:**
- `ufc_fighters.db` - SQLite database with all fighter data
- `output.csv` - CSV export for data analysis/Excel

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | API info |
| `/fighters` | GET | List fighters (supports `?limit=N&weight_class=X`) |
| `/fighters/{id}` | GET | Get specific fighter |
| `/fighters/search/{name}` | GET | Search by name |
| `/stats/summary` | GET | Database statistics |
| `/update` | POST | Trigger scraper update |

### Examples

```bash
# Get all fighters
curl http://localhost:8000/fighters

# Get 10 Welterweights
curl "http://localhost:8000/fighters?weight_class=Welterweight&limit=10"

# Search
curl http://localhost:8000/fighters/search/McGregor

# Trigger update
curl -X POST http://localhost:8000/update
```

## Automation

### Manual Updates (API)

```bash
curl -X POST http://localhost:8000/update
```

Returns immediately while scraper runs in background.

### Scheduled Updates (GitHub Actions)

**Setup:**
1. Push `.github/workflows/update_data.yml` to GitHub
2. Enable workflow permissions: Settings → Actions → "Read and write permissions"
3. Test: Actions tab → Run workflow

**Schedule:** Runs automatically every Monday at 3 AM UTC.

**Customize schedule** by editing the cron in `update_data.yml`:
```yaml
- cron: '0 0 * * *'  # Daily at midnight
- cron: '0 */6 * * *'  # Every 6 hours
```

## Project Structure

```
├── scraper/               # Scraping and database modules
│   ├── database.py        # SQLAlchemy ORM with UPSERT logic
│   ├── stat_scraper.py    # Main async scraper
│   ├── fighter_model.py   # Fighter data model
│   ├── get_fighter_urls.py  # URL collection
│   ├── fighter_stats.py   # Stats parsing
│   ├── clean_data.py      # Data cleaning utilities
│   ├── filter_data.py     # Data filtering
│   └── fighters_to_csv.py # CSV export
├── app.py                 # FastAPI application (v3.0.0)
├── schemas.py             # Pydantic validation models
├── run_scraper.py         # Scraper entry point
├── query_fighters.py      # Database query examples
├── requirements.txt       # Python dependencies
├── ufc_fighters.db        # SQLite database
├── output.csv             # Exported fighter data
└── .github/workflows/
    └── update_data.yml    # GitHub Actions workflow
```

## Database Schema

**Table:** `fighters`

- **Identity**: id, name, url
- **Physical**: height, weight, weight_class, reach, stance, dob
- **Striking**: slpm, stracc, sapm, strdef
- **Grappling**: tdavg, tdacc, tddef, subavg
- **Record**: record, most_recent_fight, fight_count, fights_in_ufc, bad_sample

## Configuration

### Switch to PostgreSQL

Edit `scraper/database.py`:
```python
engine = create_engine('postgresql://user:pass@localhost/ufc_db')
```

### Change API Port

```bash
uvicorn app:app --reload --port 8001
```

## Requirements

- Python 3.11+
- Dependencies in `requirements.txt`

## Development

```bash
# Run scraper (creates/updates ufc_fighters.db + output.csv)
python run_scraper.py

# Start API with auto-reload
uvicorn app:app --reload

# Interactive database query tutorial
python query_fighters.py
```

### Database UPSERT Logic

The scraper uses **safe UPSERT logic** to prevent UNIQUE constraint errors:

- Queries existing fighters by URL (unique identifier)
- Updates existing records if found
- Inserts new records if not found
- Single atomic commit at the end
- Tracks separately: fighters added vs. updated

This ensures reliable operation when:
- GitHub Actions reruns the scraper
- Updating stale fighter data
- Running multiple scrapes without clearing the database

**Key function:** `add_fighters()` in `scraper/database.py`

### Query Examples Tutorial

The `query_fighters.py` script provides interactive examples for learning database operations:

```bash
python query_fighters.py
```

**Includes examples for:**
- Basic queries (count, retrieve all)
- Filtering data (WHERE clauses, multiple conditions)
- Sorting and ordering
- Aggregate functions (AVG, MAX, MIN, COUNT)
- Specific fighter lookups
- Advanced queries (OR conditions, LIKE patterns)

Perfect for learning SQLAlchemy ORM query patterns!

## License

Educational purposes only. UFC data belongs to UFC/Zuffa LLC.
