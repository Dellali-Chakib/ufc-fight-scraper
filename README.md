# UFC Fighter Stats Scraper & API

A UFC fighter statistics scraper with REST API and automated updates.

## Features

- **Data Collection**: Async scraping of 700+ UFC fighters from ufcstats.com
- **Database**: SQLAlchemy ORM with SQLite (PostgreSQL-ready)
- **REST API**: FastAPI with automatic documentation
- **Automation**: API-triggered and scheduled updates via GitHub Actions

## Quick Start

```bash
# 1. Setup
python -m venv venv
.\venv\Scripts\activate  # Windows
source venv/bin/activate  # macOS/Linux
pip install -r requirements.txt

# 2. Scrape data
python run_scraper.py

# 3. Start API
uvicorn app:app --reload
```

Visit http://localhost:8000/docs for interactive API documentation.

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
├── scraper/          # Scraping and database modules
│   ├── database.py   # SQLAlchemy ORM
│   ├── stat_scraper.py  # Main scraper
│   └── ...
├── app.py            # FastAPI application
├── schemas.py        # Pydantic models
├── run_scraper.py    # Scraper entry point
├── requirements.txt  # Dependencies
└── .github/workflows/
    └── update_data.yml  # GitHub Actions workflow
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
# Run scraper
python run_scraper.py

# Start API with auto-reload
uvicorn app:app --reload

# Query database directly
python query_fighters.py
```

## License

Educational purposes only. UFC data belongs to UFC/Zuffa LLC.
