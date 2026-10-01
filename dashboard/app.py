"""
FastAPI dashboard — view all scraped and applied jobs.
Run: uvicorn dashboard.app:app --host 127.0.0.1 --port 8080 --reload
"""
from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
import sys, os

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).parent.parent))
from database import db as database

app = FastAPI(title="JobBot AI Dashboard")

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@app.on_event("startup")
async def startup():
    await database.init_db()


# ─── Pages ───────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    stats = await database.get_stats()
    return templates.TemplateResponse("index.html", {"request": request, "stats": stats})


@app.get("/jobs", response_class=HTMLResponse)
async def jobs_page(
    request: Request,
    status: str = None,
    source: str = None,
    search: str = None,
    page: int = 1,
):
    limit = 50
    offset = (page - 1) * limit
    jobs = await database.get_all_jobs(status=status, source=source, search=search, limit=limit, offset=offset)
    stats = await database.get_stats()
    return templates.TemplateResponse("jobs.html", {
        "request": request,
        "jobs": jobs,
        "stats": stats,
        "status_filter": status,
        "source_filter": source,
        "search": search,
        "page": page,
    })


# ─── API endpoints ────────────────────────────────────────────────────────────

@app.get("/api/stats")
async def api_stats():
    return await database.get_stats()


@app.get("/api/jobs")
async def api_jobs(
    status: str = None,
    source: str = None,
    search: str = None,
    limit: int = 50,
    offset: int = 0,
):
    jobs = await database.get_all_jobs(status=status, source=source, search=search, limit=limit, offset=offset)
    return {"jobs": jobs, "count": len(jobs)}


@app.get("/api/jobs/{job_id}")
async def api_job_detail(job_id: int):
    jobs = await database.get_all_jobs(limit=1, offset=0)
    # Simple fetch by id
    import aiosqlite
    async with aiosqlite.connect(database.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = await cursor.fetchone()
        if not row:
            return JSONResponse({"error": "Not found"}, status_code=404)
        return dict(row)


@app.post("/api/jobs/{job_id}/skip")
async def skip_job(job_id: int):
    await database.update_job_status(job_id, "skipped", notes="Manually skipped from dashboard")
    return {"ok": True}


@app.post("/api/jobs/{job_id}/reset")
async def reset_job(job_id: int):
    """Reset a job back to pending so it gets retried."""
    import aiosqlite
    async with aiosqlite.connect(database.DB_PATH) as db:
        await db.execute(
            "UPDATE jobs SET status='pending', error_message=NULL, retry_count=0 WHERE id=?",
            (job_id,)
        )
        await db.commit()
    return {"ok": True}


@app.get("/export/excel")
async def export_excel():
    """Download applied jobs as Excel file."""
    from database.export import export_applied_jobs
    path = await export_applied_jobs("applied_jobs.xlsx")
    if not Path(path).exists():
        return JSONResponse({"error": "No data yet"}, status_code=404)
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="applied_jobs.xlsx",
    )


@app.get("/export/all-jobs")
async def export_all_jobs():
    """Download ALL scraped jobs as Excel (for manual applying)."""
    from database.export import export_all_scraped_jobs
    path = await export_all_scraped_jobs("all_scraped_jobs.xlsx")
    if not Path(path).exists():
        return JSONResponse({"error": "No data yet"}, status_code=404)
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="all_scraped_jobs.xlsx",
    )


@app.get("/api/run-logs")
async def run_logs():
    import aiosqlite
    async with aiosqlite.connect(database.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM run_log ORDER BY run_date DESC LIMIT 20")
        rows = await cursor.fetchall()
        return {"logs": [dict(r) for r in rows]}
