"""UFC Fighter Stats REST API"""

from fastapi import FastAPI, Depends, HTTPException, Query, BackgroundTasks
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import Optional
import uvicorn
from datetime import datetime

from scraper.database import (
    get_engine,
    get_session,
    FighterDB,
    get_fighter_count,
    init_database
)

from schemas import (
    FighterSchema,
    FighterListResponse,
    FighterDetailResponse,
    MessageResponse,
    ErrorResponse
)


app = FastAPI(
    title="UFC Fighter Stats API",
    description="REST API for querying UFC fighter statistics",
    version="3.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

engine = get_engine('ufc_fighters.db')


def get_db() -> Session:
    """Database session dependency."""
    db = get_session(engine)
    try:
        yield db
    finally:
        db.close()


@app.get("/", response_model=MessageResponse)
async def root():
    """API root endpoint."""
    return {
        "message": "UFC Fighter Stats API",
        "success": True
    }


@app.get("/fighters", response_model=FighterListResponse)
async def get_all_fighters(
    limit: Optional[int] = Query(None, description="Max number of fighters to return"),
    weight_class: Optional[str] = Query(None, description="Filter by weight class"),
    db: Session = Depends(get_db)
):
    """Get all fighters with optional filtering."""
    query = db.query(FighterDB)
    
    if weight_class:
        query = query.filter(FighterDB.weight_class == weight_class)
    
    if limit:
        query = query.limit(limit)
    
    fighters = query.all()
    
    return {
        "count": len(fighters),
        "fighters": fighters
    }


@app.get("/fighters/{fighter_id}", response_model=FighterDetailResponse)
async def get_fighter_by_id(
    fighter_id: int,
    db: Session = Depends(get_db)
):
    """Get a specific fighter by ID."""
    fighter = db.query(FighterDB).filter(FighterDB.id == fighter_id).first()
    
    if not fighter:
        raise HTTPException(
            status_code=404,
            detail=f"Fighter with ID {fighter_id} not found"
        )
    
    return {"fighter": fighter}


@app.get("/fighters/search/{name}", response_model=FighterListResponse)
async def search_fighters_by_name(
    name: str,
    db: Session = Depends(get_db)
):
    """Search for fighters by name (partial match)."""
    fighters = db.query(FighterDB).filter(
        FighterDB.name.ilike(f"%{name}%")
    ).all()
    
    return {
        "count": len(fighters),
        "fighters": fighters
    }


@app.get("/stats/summary", response_model=dict)
async def get_database_stats(db: Session = Depends(get_db)):
    """Get summary statistics about the database."""
    from sqlalchemy import func
    
    total = db.query(func.count(FighterDB.id)).scalar()
    
    weight_class_counts = db.query(
        FighterDB.weight_class,
        func.count(FighterDB.id).label('count')
    ).group_by(FighterDB.weight_class).all()
    
    weight_classes = {
        wc: count for wc, count in weight_class_counts 
        if wc and wc != 'None'
    }
    
    avg_stats = db.query(
        func.avg(FighterDB.height).label('avg_height'),
        func.avg(FighterDB.reach).label('avg_reach'),
        func.avg(FighterDB.stracc).label('avg_stracc')
    ).first()
    
    return {
        "total_fighters": total,
        "weight_class_distribution": weight_classes,
        "average_height_inches": round(avg_stats.avg_height, 1) if avg_stats.avg_height else None,
        "average_reach_inches": round(avg_stats.avg_reach, 1) if avg_stats.avg_reach else None,
        "average_striking_accuracy": round(avg_stats.avg_stracc * 100, 1) if avg_stats.avg_stracc else None
    }


@app.post("/update", response_model=MessageResponse)
async def trigger_update(background_tasks: BackgroundTasks):
    """Trigger database update by running scraper in background."""
    background_tasks.add_task(run_scraper_update)
    
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "message": f"Database update started at {current_time}. Scraper running in background.",
        "success": True
    }


def run_scraper_update():
    """Background task that runs the scraper."""
    try:
        print("\n" + "="*80)
        print("BACKGROUND TASK: Starting scraper update")
        print("="*80)
        
        from scraper.stat_scraper import main as scraper_main
        scraper_main()
        
        print("="*80)
        print("BACKGROUND TASK: Scraper update completed successfully!")
        print("="*80 + "\n")
        
    except Exception as e:
        print("="*80)
        print(f"BACKGROUND TASK ERROR: Scraper update failed!")
        print(f"Error: {str(e)}")
        print("="*80 + "\n")


@app.exception_handler(404)
async def not_found_handler(request, exc):
    """Custom 404 error handler."""
    return JSONResponse(
        status_code=404,
        content={
            "detail": "Resource not found",
            "error_code": "NOT_FOUND"
        }
    )


@app.on_event("startup")
async def startup_event():
    """Run on API startup."""
    print("="*80)
    print("UFC FIGHTER API STARTING UP")
    print("="*80)
    print(f"Database: ufc_fighters.db")
    
    init_database(engine)
    count = get_fighter_count(engine)
    print(f"Total fighters in database: {count}")
    
    print("\n📖 API Documentation:")
    print("   http://localhost:8000/docs")
    print("="*80 + "\n")


if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
