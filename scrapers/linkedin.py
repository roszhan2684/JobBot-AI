"""
LinkedIn job scraper using Playwright.
Searches public job listings and scrapes details.
Easy Apply jobs are flagged for auto-application.
"""
import asyncio
import logging
import re
from typing import List, Dict, Optional
from urllib.parse import urlencode, quote_plus
from .base import BaseScraper

logger = logging.getLogger(__name__)


class LinkedInScraper(BaseScraper):

    BASE_URL = "https://www.linkedin.com"

    async def scrape(self) -> List[Dict]:
        if not self.browser_manager:
            logger.warning("LinkedIn scraper needs browser_manager, skipping")
            return []

        jobs = []
        titles = self.search_titles[:3]  # Top 3 titles to avoid too many searches
        locations = self.search_locations[:2]

        async with self.browser_manager.new_page() as page:
            # Try to restore session
            await self.browser_manager.restore_cookies(page, "linkedin")

            for title in titles:
                for location in locations:
                    if len(jobs) >= self.jobs_per_source:
                        break
                    found = await self._search_jobs(page, title, location)
                    jobs.extend(found)
                    await asyncio.sleep(2)

        logger.info(f"LinkedIn: found {len(jobs)} jobs")
        return jobs[:self.jobs_per_source]

    async def _search_jobs(self, page, title: str, location: str) -> List[Dict]:
        jobs = []
        params = {
            "keywords": title,
            "location": location,
            "f_TPR": "r86400",  # Last 24 hours
            "sortBy": "DD",    # Date posted
        }
        url = f"{self.BASE_URL}/jobs/search/?{urlencode(params)}"
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)

            # Scroll to load more
            for _ in range(3):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(1.5)

            # LinkedIn updates its DOM frequently — try multiple selectors
            job_cards = []
            for card_sel in [
                "li.jobs-search-results__list-item",
                "div[data-job-id]",
                ".job-card-container",
                ".jobs-search__results-list li",
                ".scaffold-layout__list-item",
                ".job-search-card",
                ".base-card",
            ]:
                job_cards = await page.query_selector_all(card_sel)
                if job_cards:
                    break

            logger.info(f"LinkedIn '{title}' @ '{location}': {len(job_cards)} cards found")

            for card in job_cards[:25]:
                try:
                    job = await self._parse_card(card, page)
                    if job:
                        cleaned = self._clean_job(job)
                        if cleaned:
                            jobs.append(cleaned)
                except Exception as e:
                    logger.debug(f"Card parse error: {e}")

        except Exception as e:
            logger.error(f"LinkedIn search error: {e}")

        return jobs

    async def _parse_card(self, card, page) -> Optional[Dict]:
        try:
            # Try multiple selectors for each field — LinkedIn's DOM changes often
            title = ""
            for sel in [
                ".job-card-list__title", ".job-card-container__link",
                ".base-search-card__title", "h3", "a[data-control-name]",
                ".artdeco-entity-lockup__title",
            ]:
                el = await card.query_selector(sel)
                if el:
                    title = (await el.inner_text()).strip()
                    if title:
                        break

            company = ""
            for sel in [
                ".job-card-container__company-name", ".base-search-card__subtitle",
                ".job-card-list__company-name", ".artdeco-entity-lockup__subtitle",
                "h4",
            ]:
                el = await card.query_selector(sel)
                if el:
                    company = (await el.inner_text()).strip()
                    if company:
                        break

            location = ""
            for sel in [
                ".job-card-container__metadata-item", ".job-search-card__location",
                ".base-search-card__metadata", ".artdeco-entity-lockup__caption",
            ]:
                el = await card.query_selector(sel)
                if el:
                    location = (await el.inner_text()).strip()
                    if location:
                        break

            url = ""
            for sel in ["a.job-card-list__title--link", "a.base-card__full-link", "a[href*='/jobs/view/']", "a"]:
                link_el = await card.query_selector(sel)
                if link_el:
                    href = await link_el.get_attribute("href")
                    if href and ("/jobs/" in href or "linkedin.com" in href):
                        url = href
                        break

            if not url or not title:
                return None

            if url.startswith("/"):
                url = self.BASE_URL + url
            url = url.split("?")[0]

            # Check for Easy Apply badge
            easy_apply = False
            card_text = (await card.inner_text()).lower()
            easy_apply = "easy apply" in card_text

            # Salary
            salary_el = await card.query_selector(".job-search-card__salary-info, .job-card-container__salary-info")
            salary = (await salary_el.inner_text()).strip() if salary_el else None

            # Posted date
            date_el = await card.query_selector("time")
            posted = await date_el.get_attribute("datetime") if date_el else None

            return {
                "source": "linkedin",
                "job_id": self._extract_job_id(url),
                "title": title,
                "company": company,
                "location": location,
                "description": "",  # Will be fetched separately if needed
                "url": url,
                "apply_url": url,
                "salary": salary,
                "job_type": "easy_apply" if easy_apply else "external",
                "posted_date": posted,
            }
        except Exception as e:
            logger.debug(f"LinkedIn card parse error: {e}")
            return None

    def _extract_job_id(self, url: str) -> str:
        # LinkedIn URLs: /jobs/view/1234567890
        match = re.search(r"/view/(\d+)", url)
        return match.group(1) if match else ""

    async def fetch_job_description(self, page, job_url: str) -> str:
        """Fetch full job description for scoring."""
        try:
            await page.goto(job_url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(2)
            desc_el = await page.query_selector(".show-more-less-html__markup, .description__text")
            if desc_el:
                return (await desc_el.inner_text()).strip()
        except Exception as e:
            logger.debug(f"Couldn't fetch LinkedIn description: {e}")
        return ""
