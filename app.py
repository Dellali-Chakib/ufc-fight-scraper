"""Read-only per-request SQLite snapshots and a lock-protected background refresh."""

import logging
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Annotated

import uvicorn
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query

from schemas import FighterDetailResponse, FighterListResponse, MessageResponse
from scraper.database import reader
from scraper.stat_scraper import main

ROOT = Path(__file__).resolve().parent
app = FastAPI(
    title="UFC Fighter Stats API",
    version="4.0.0",
    description="UFC.com publication with nullable measurements, reported rates and explicit history coverage.",
)


def get_db():
    try:
        db = reader(ROOT / "ufc_fighters.db")
    except sqlite3.OperationalError as exc:
        raise HTTPException(503, "Fighter publication unavailable") from exc
    with closing(db):
        yield db


Database = Annotated[sqlite3.Connection, Depends(get_db)]
logger = logging.getLogger(__name__)


@app.get("/", response_model=MessageResponse)
def root():
    return {"message": "UFC Fighter Stats API", "success": True}


def listing(rows):
    fighters = [dict(row) for row in rows]
    return {"count": len(fighters), "fighters": fighters}


@app.get("/fighters", response_model=FighterListResponse, response_model_by_alias=False)
def get_all_fighters(
    db: Database,
    limit: int | None = Query(None, ge=1),
    weight_class: str | None = None,
):
    sql = "SELECT * FROM fighters"
    params = []
    if weight_class:
        sql += " WHERE weight_class=?"
        params.append(weight_class)
    sql += " ORDER BY id LIMIT ?"
    return listing(db.execute(sql, [*params, limit or -1]))


@app.get(
    "/fighters/{fighter_id}",
    response_model=FighterDetailResponse,
    response_model_by_alias=False,
)
def get_fighter_by_id(fighter_id: int, db: Database):
    row = db.execute("SELECT * FROM fighters WHERE id=?", (fighter_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Fighter not found")
    return {"fighter": dict(row)}


@app.get(
    "/fighters/search/{name}",
    response_model=FighterListResponse,
    response_model_by_alias=False,
)
def search_fighters_by_name(name: str, db: Database):
    return listing(
        db.execute(
            "SELECT * FROM fighters WHERE name LIKE ? ORDER BY id", ("%" + name + "%",)
        )
    )


@app.get("/stats/summary")
def get_database_stats(db: Database):
    stats = dict(
        db.execute(
            "SELECT COUNT(*) total_fighters, ROUND(AVG(height),1) average_height_inches, ROUND(AVG(reach),1) average_reach_inches, ROUND(AVG(stracc)*100,1) average_striking_accuracy FROM fighters"
        ).fetchone()
    )
    stats["weight_class_distribution"] = dict(
        db.execute(
            "SELECT weight_class,COUNT(*) FROM fighters WHERE weight_class IS NOT NULL AND weight_class!='None' GROUP BY weight_class"
        )
    )
    return stats


def run_scraper_update():
    try:
        main(ROOT, publish_now=True)
    except Exception:
        logger.exception("Background refresh failed")


@app.post("/update", response_model=MessageResponse)
def trigger_update(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_scraper_update)
    return {
        "success": True,
        "message": "Refresh queued. See collection-success.json or collection-failure.json for its result.",
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
