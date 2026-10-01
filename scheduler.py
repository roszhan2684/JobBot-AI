"""
JobBot AI — 24/7 Scheduler

Runs the bot on a configurable interval (default every 3 hours).
Also starts the dashboard web server in a background thread.

Usage:
  python scheduler.py              # Start bot + dashboard
  python scheduler.py --bot-only   # Bot only, no dashboard
  python scheduler.py --dash-only  # Dashboard only
"""
import argparse
import asyncio
import logging
import os
import sys
import threading
import time
import yaml
from datetime import datetime
from dotenv import load_dotenv

import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from rich.console import Console
from rich.logging import RichHandler

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[
        RichHandler(rich_tracebacks=True),
        logging.FileHandler("jobbot.log"),
    ],
)
logger = logging.getLogger("scheduler")
console = Console()


def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


# ─── Dashboard thread ─────────────────────────────────────────────────────────

def start_dashboard(host: str, port: int):
    """Run FastAPI dashboard in a separate thread."""
    config = uvicorn.Config(
        "dashboard.app:app",
        host=host,
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    asyncio.run(server.serve())


# ─── Bot job ──────────────────────────────────────────────────────────────────

_bot_running = False


async def run_bot_cycle():
    """Single bot run cycle. Skips if already running."""
    global _bot_running
    if _bot_running:
        logger.warning("Bot cycle already running, skipping this trigger")
        return

    _bot_running = True
    try:
        from main import JobBot, load_config
        config = load_config()
        bot = JobBot(config)
        await bot.run()
    except Exception as e:
        logger.error(f"Bot cycle error: {e}", exc_info=True)
    finally:
        _bot_running = False


# ─── Main ─────────────────────────────────────────────────────────────────────

async def start_scheduler(config: dict, run_immediately: bool = True):
    interval_hours = config.get("settings", {}).get("scrape_interval_hours", 3)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_bot_cycle,
        trigger=IntervalTrigger(hours=interval_hours),
        id="jobbot_cycle",
        name="JobBot full cycle",
        misfire_grace_time=300,  # 5 min grace period
        coalesce=True,
    )
    scheduler.start()

    console.print(f"\n[bold purple]JobBot AI Scheduler Started[/bold purple]")
    console.print(f"[dim]Running every {interval_hours} hour(s)[/dim]")
    console.print(f"[dim]Next run at: {scheduler.get_jobs()[0].next_run_time}[/dim]\n")

    if run_immediately:
        logger.info("Running first cycle immediately...")
        await run_bot_cycle()

    # Keep running forever
    try:
        while True:
            await asyncio.sleep(60)
            # Heartbeat log every hour
            if datetime.now().minute == 0:
                next_run = scheduler.get_jobs()[0].next_run_time
                logger.info(f"[Heartbeat] Scheduler running. Next job cycle: {next_run}")
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler shutting down...")
        scheduler.shutdown()


def main():
    parser = argparse.ArgumentParser(description="JobBot AI Scheduler")
    parser.add_argument("--bot-only", action="store_true", help="Run bot without dashboard")
    parser.add_argument("--dash-only", action="store_true", help="Run dashboard only")
    parser.add_argument("--no-immediate", action="store_true", help="Don't run bot immediately on start")
    args = parser.parse_args()

    config = load_config()
    settings = config.get("settings", {})
    host = settings.get("dashboard_host", "127.0.0.1")
    port = settings.get("dashboard_port", 8080)

    if args.dash_only:
        console.print(f"[bold]Starting dashboard at http://{host}:{port}[/bold]")
        start_dashboard(host, port)
        return

    # Start dashboard in background thread
    if not args.bot_only:
        dash_thread = threading.Thread(
            target=start_dashboard,
            args=(host, port),
            daemon=True,
            name="dashboard",
        )
        dash_thread.start()
        console.print(f"[dim]Dashboard: http://{host}:{port}[/dim]")

    # Run scheduler
    run_immediately = not args.no_immediate
    asyncio.run(start_scheduler(config, run_immediately=run_immediately))


if __name__ == "__main__":
    main()
