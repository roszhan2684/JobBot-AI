"""
SQLite database for tracking all jobs: scraped, scored, applied, failed.
"""
import aiosqlite
from datetime import datetime
from typing import Optional, List, Dict, Any

DB_PATH = "jobbot.db"


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                job_id TEXT,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                location TEXT,
                description TEXT,
                url TEXT UNIQUE NOT NULL,
                apply_url TEXT,
                salary TEXT,
                job_type TEXT,
                posted_date TEXT,
                scraped_date TEXT NOT NULL,
                ai_score INTEGER DEFAULT 0,
                ai_analysis TEXT,
                status TEXT DEFAULT 'pending',
                applied_date TEXT,
                error_message TEXT,
                retry_count INTEGER DEFAULT 0,
                notes TEXT,
                cover_letter TEXT,
                screenshot_path TEXT
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs(ai_score)
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT UNIQUE NOT NULL,
                cookies TEXT,
                last_login TEXT,
                is_valid INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS run_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_date TEXT NOT NULL,
                jobs_scraped INTEGER DEFAULT 0,
                jobs_scored INTEGER DEFAULT 0,
                jobs_applied INTEGER DEFAULT 0,
                jobs_failed INTEGER DEFAULT 0,
                duration_seconds REAL DEFAULT 0,
                notes TEXT
            )
        """)
        await db.commit()


async def upsert_job(job_data: dict) -> tuple[Optional[int], bool]:
    """
    Insert a new job or ignore if URL already exists.
    Returns (job_id, is_new) — is_new=True only when newly inserted.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            cursor = await db.execute("""
                INSERT OR IGNORE INTO jobs
                (source, job_id, title, company, location, description, url,
                 apply_url, salary, job_type, posted_date, scraped_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job_data.get("source"),
                job_data.get("job_id"),
                job_data.get("title", "Unknown Title"),
                job_data.get("company", "Unknown Company"),
                job_data.get("location"),
                job_data.get("description"),
                job_data.get("url"),
                job_data.get("apply_url"),
                job_data.get("salary"),
                job_data.get("job_type"),
                job_data.get("posted_date"),
                datetime.now().isoformat(),
            ))
            await db.commit()
            if cursor.lastrowid:
                return cursor.lastrowid, True   # newly inserted
            # Already exists
            cur2 = await db.execute("SELECT id FROM jobs WHERE url = ?", (job_data.get("url"),))
            row = await cur2.fetchone()
            return (row[0] if row else None), False
        except Exception as e:
            return None, False


async def update_job_score(job_id: int, score: int, analysis: str = None, cover_letter: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE jobs SET ai_score = ?, ai_analysis = ?, cover_letter = ? WHERE id = ?",
            (score, analysis, cover_letter, job_id)
        )
        await db.commit()


async def update_job_status(
    job_id: int,
    status: str,
    error: str = None,
    notes: str = None,
    screenshot_path: str = None
):
    """status: pending | applying | applied | skipped | failed | captcha | duplicate"""
    async with aiosqlite.connect(DB_PATH) as db:
        applied_date = datetime.now().isoformat() if status == "applied" else None
        await db.execute("""
            UPDATE jobs
            SET status = ?, applied_date = ?, error_message = ?, notes = ?, screenshot_path = ?
            WHERE id = ?
        """, (status, applied_date, error, notes, screenshot_path, job_id))
        await db.commit()


async def increment_retry(job_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE jobs SET retry_count = retry_count + 1 WHERE id = ?",
            (job_id,)
        )
        await db.commit()


async def get_jobs_to_score(limit: int = 100) -> List[Dict]:
    """Jobs scraped but not yet scored."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT * FROM jobs
            WHERE status = 'pending' AND ai_score = 0
            ORDER BY scraped_date DESC
            LIMIT ?
        """, (limit,))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_jobs_to_apply(min_score: int = 65, limit: int = 50) -> List[Dict]:
    """Scored jobs ready to apply to."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT * FROM jobs
            WHERE status = 'pending' AND ai_score >= ?
            ORDER BY ai_score DESC, scraped_date DESC
            LIMIT ?
        """, (min_score, limit))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_failed_jobs(max_retries: int = 2, limit: int = 20) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT * FROM jobs
            WHERE status = 'failed' AND retry_count < ?
            ORDER BY scraped_date DESC
            LIMIT ?
        """, (max_retries, limit))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_all_jobs(
    status: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    search: Optional[str] = None,
) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        conditions = []
        params = []
        if status:
            conditions.append("status = ?")
            params.append(status)
        if source:
            conditions.append("source = ?")
            params.append(source)
        if search:
            conditions.append("(title LIKE ? OR company LIKE ? OR description LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([limit, offset])
        cursor = await db.execute(
            f"SELECT * FROM jobs {where} ORDER BY scraped_date DESC LIMIT ? OFFSET ?",
            params
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_stats() -> Dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'applied' THEN 1 ELSE 0 END) as applied,
                SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                SUM(CASE WHEN status = 'skipped' THEN 1 ELSE 0 END) as skipped,
                SUM(CASE WHEN status = 'captcha' THEN 1 ELSE 0 END) as captcha,
                AVG(CASE WHEN ai_score > 0 THEN ai_score ELSE NULL END) as avg_score
            FROM jobs
        """)
        row = await cursor.fetchone()
        stats = dict(row)
        # Applied today
        today = datetime.now().strftime("%Y-%m-%d")
        cur2 = await db.execute(
            "SELECT COUNT(*) as cnt FROM jobs WHERE status = 'applied' AND applied_date LIKE ?",
            (f"{today}%",)
        )
        row2 = await cur2.fetchone()
        stats["applied_today"] = row2["cnt"] if row2 else 0
        # Sources breakdown
        cur3 = await db.execute("""
            SELECT source, COUNT(*) as cnt,
                   SUM(CASE WHEN status='applied' THEN 1 ELSE 0 END) as applied
            FROM jobs GROUP BY source
        """)
        sources = await cur3.fetchall()
        stats["sources"] = [dict(s) for s in sources]
        return stats


async def save_session(platform: str, cookies: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO sessions (platform, cookies, last_login, is_valid)
            VALUES (?, ?, ?, 1)
        """, (platform, cookies, datetime.now().isoformat()))
        await db.commit()


async def get_session(platform: str) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM sessions WHERE platform = ? AND is_valid = 1",
            (platform,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def log_run(
    jobs_scraped: int,
    jobs_scored: int,
    jobs_applied: int,
    jobs_failed: int,
    duration: float,
    notes: str = None
):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO run_log
            (run_date, jobs_scraped, jobs_scored, jobs_applied, jobs_failed, duration_seconds, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (datetime.now().isoformat(), jobs_scraped, jobs_scored, jobs_applied, jobs_failed, duration, notes))
        await db.commit()
