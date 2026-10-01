"""
JobBot AI — Main Orchestrator

Run order per cycle:
  1. Scrape jobs from all configured sources
  2. Score each new job with Claude AI
  3. Apply to all qualifying jobs (score >= min_score)
  4. Log run stats to database

Run once:   python main.py
Run 24/7:   python scheduler.py
"""
import asyncio
import logging
import os
import random
import sys
import time
import yaml
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table
from rich import print as rprint

# Load environment variables
load_dotenv()

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[RichHandler(rich_tracebacks=True, markup=True)],
)
logger = logging.getLogger("jobbot")
console = Console()

# ─── Project imports ──────────────────────────────────────────────────────────
from database import db as database
from database.export import auto_export, export_all_scraped_jobs
from scrapers import SCRAPERS, get_scraper
from automation.browser import BrowserManager
from automation.login_manager import LoginManager
from automation.form_filler import FormFiller
from ai.matcher import AIMatcher


def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


class JobBot:
    def __init__(self, config: dict):
        self.config = config
        self.settings = config.get("settings", {})
        self.user = config.get("user", {})
        self.sources = config.get("job_sources", ["remoteok"])

        # Stats for this run
        self._scraped = 0
        self._scored = 0
        self._applied = 0
        self._failed = 0
        self._start_time = 0

        # Components (initialized in run())
        self.browser: BrowserManager = None
        self.login_manager: LoginManager = None
        self.form_filler: FormFiller = None
        self.ai: AIMatcher = None

    # ─── Run ──────────────────────────────────────────────────────────────────

    async def run(self):
        """Full run: scrape → score → apply."""
        self._start_time = time.time()
        console.rule("[bold purple]JobBot AI — Starting Run")
        logger.info(f"Run started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        await database.init_db()

        # Init AI
        try:
            self.ai = AIMatcher(self.config)
        except ValueError as e:
            logger.error(f"AI init failed: {e}")
            sys.exit(1)

        # Init browser
        headless = self.settings.get("headless_browser", True)
        self.browser = BrowserManager(headless=headless)
        await self.browser.start()

        self.login_manager = LoginManager(self.config, self.browser)
        self.form_filler = FormFiller(self.config, self.browser, self.ai)

        try:
            # Step 1: Log into job platforms
            await self._login_phase()

            # Step 2: Scrape new jobs
            await self._scrape_phase()

            # Step 3: Score unscored jobs
            await self._score_phase()

            # Step 4: Apply
            await self._apply_phase()

        finally:
            await self.browser.stop()
            duration = time.time() - self._start_time
            await database.log_run(
                self._scraped, self._scored, self._applied, self._failed, duration
            )
            self._print_summary(duration)

    # ─── Phase 1: Login ───────────────────────────────────────────────────────

    async def _login_phase(self):
        console.rule("[bold blue]Phase 1: Login")
        async with self.browser.new_page() as page:
            await self.login_manager.login_all(page)

    # ─── Phase 2: Scrape ──────────────────────────────────────────────────────

    async def _scrape_phase(self):
        console.rule("[bold blue]Phase 2: Scraping Jobs")
        total_new = 0

        for source_name in self.sources:
            logger.info(f"Scraping: [bold]{source_name}[/bold]")
            try:
                scraper = get_scraper(source_name, self.config, self.browser)
                jobs = await scraper.scrape()
            except Exception as e:
                logger.error(f"Scraper {source_name} crashed: {e}")
                jobs = []

            new_count = 0
            for job in jobs:
                job_id, is_new = await database.upsert_job(job)
                if is_new:
                    new_count += 1

            total_new += new_count
            logger.info(f"  {source_name}: {len(jobs)} found, {new_count} new")

        self._scraped = total_new
        logger.info(f"Scraping done — [bold green]{total_new} new jobs[/bold green] added to queue")

        # Export all scraped jobs to Excel immediately after scraping
        try:
            path = await export_all_scraped_jobs()
            logger.info(f"[green]All-jobs Excel updated:[/green] {path}")
        except Exception as e:
            logger.warning(f"All-jobs export failed: {e}")

    # ─── Phase 3: Score ───────────────────────────────────────────────────────

    async def _score_phase(self):
        console.rule("[bold blue]Phase 3: AI Scoring")
        jobs = await database.get_jobs_to_score(limit=200)

        if not jobs:
            logger.info("No unscored jobs — skipping score phase")
            return

        logger.info(f"Scoring {len(jobs)} jobs with Claude AI...")
        scored = 0

        for job in jobs:
            # Quick pre-filter
            skip, reason = await self.ai.should_skip_job(job)
            if skip:
                await database.update_job_status(job["id"], "skipped", notes=reason)
                continue

            score, analysis = await self.ai.score_job(job)

            # Generate cover letter for high-scoring jobs
            cover_letter = None
            if score >= self.settings.get("min_job_score", 65):
                cover_letter = await self.ai.generate_cover_letter(job)

            await database.update_job_score(job["id"], score, analysis, cover_letter)
            scored += 1

            if score >= 70:
                logger.info(f"  [green]Score {score}[/green] — {job['title']} @ {job['company']}")
            elif score >= 50:
                logger.info(f"  [yellow]Score {score}[/yellow] — {job['title']} @ {job['company']}")
            else:
                logger.debug(f"  Score {score} — {job['title']} @ {job['company']}")

            # Small delay to respect rate limits
            await asyncio.sleep(0.5)

        self._scored = scored
        logger.info(f"Scoring done — [bold green]{scored} jobs scored[/bold green]")

    # ─── Phase 4: Apply ───────────────────────────────────────────────────────

    async def _apply_phase(self):
        console.rule("[bold blue]Phase 4: Applying to Jobs")

        max_per_day = self.settings.get("max_applications_per_day", 30)
        min_score = self.settings.get("min_job_score", 65)
        delay_min = self.settings.get("apply_delay_min", 20)
        delay_max = self.settings.get("apply_delay_max", 45)
        retry = self.settings.get("retry_failed", True)
        max_retries = self.settings.get("max_retries", 2)

        # Get jobs to apply — sorted by score (best first)
        jobs_to_apply = await database.get_jobs_to_apply(min_score=min_score, limit=max_per_day)

        # Optionally retry failed jobs
        if retry:
            failed_jobs = await database.get_failed_jobs(max_retries=max_retries, limit=10)
            jobs_to_apply.extend(failed_jobs)

        if not jobs_to_apply:
            logger.info("No qualifying jobs to apply to this run")
            return

        logger.info(f"Applying to [bold]{len(jobs_to_apply)}[/bold] jobs (min score: {min_score})")

        async with self.browser.new_page() as page:
            for i, job in enumerate(jobs_to_apply):
                if self._applied >= max_per_day:
                    logger.warning(f"Daily application limit ({max_per_day}) reached")
                    break

                logger.info(
                    f"[{i+1}/{len(jobs_to_apply)}] Applying: "
                    f"[bold]{job['title']}[/bold] @ {job['company']} "
                    f"(score: {job['ai_score']})"
                )

                # Mark as in-progress
                await database.update_job_status(job["id"], "applying")

                try:
                    success, message = await self.form_filler.apply_to_job(page, job)

                    if success:
                        await database.update_job_status(
                            job["id"], "applied", notes=message
                        )
                        self._applied += 1
                        logger.info(f"  [green]Applied![/green] {message}")
                    else:
                        if "captcha" in message.lower():
                            await database.update_job_status(
                                job["id"], "captcha", error=message
                            )
                            logger.warning(f"  [yellow]CAPTCHA[/yellow] — {message}")
                        else:
                            await database.update_job_status(
                                job["id"], "failed", error=message
                            )
                            await database.increment_retry(job["id"])
                            self._failed += 1
                            logger.warning(f"  [red]Failed[/red] — {message}")

                except Exception as e:
                    await database.update_job_status(job["id"], "failed", error=str(e))
                    await database.increment_retry(job["id"])
                    self._failed += 1
                    logger.error(f"  [red]Exception[/red] — {e}")

                # Random human-like delay between applications
                if i < len(jobs_to_apply) - 1:
                    delay = random.uniform(delay_min, delay_max)
                    logger.debug(f"  Waiting {delay:.0f}s before next application...")
                    await asyncio.sleep(delay)

        logger.info(
            f"Apply phase done — "
            f"[bold green]{self._applied} applied[/bold green], "
            f"[bold red]{self._failed} failed[/bold red]"
        )

        # Auto-export applied jobs to Excel after every apply cycle
        if self._applied > 0:
            excel_path = await auto_export()
            if excel_path:
                logger.info(f"[green]Excel updated:[/green] {excel_path}")

    # ─── Summary ──────────────────────────────────────────────────────────────

    def _print_summary(self, duration: float):
        console.rule("[bold purple]Run Complete")
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("Metric", style="bold")
        table.add_column("Value")
        table.add_row("New jobs scraped", f"[green]{self._scraped}[/green]")
        table.add_row("Jobs scored", f"[cyan]{self._scored}[/cyan]")
        table.add_row("Jobs applied", f"[green]{self._applied}[/green]")
        table.add_row("Jobs failed", f"[red]{self._failed}[/red]")
        table.add_row("Duration", f"{duration:.1f}s")
        console.print(table)
        console.print(f"\n[dim]Dashboard: http://127.0.0.1:{self.config['settings'].get('dashboard_port', 8080)}[/dim]")


# ─── Entry point ──────────────────────────────────────────────────────────────

async def main():
    config = load_config()
    bot = JobBot(config)
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
