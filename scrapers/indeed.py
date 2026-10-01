"""
Indeed job scraper.
Uses Indeed's internal search API (same one the website calls).
No login needed for scraping public listings.
"""
import httpx
import asyncio
import logging
import json
import re
from typing import List, Dict, Optional
from urllib.parse import urlencode, quote_plus
from .base import BaseScraper

logger = logging.getLogger(__name__)


class IndeedScraper(BaseScraper):
    """Scrapes Indeed using their internal JSON search endpoint."""

    BASE_URL = "https://www.indeed.com"

    async def scrape(self) -> List[Dict]:
        jobs = []
        async with httpx.AsyncClient(
            timeout=20,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        ) as client:
            for title in self.search_titles[:4]:
                for location in self.search_locations[:2]:
                    if len(jobs) >= self.jobs_per_source:
                        break
                    found = await self._search(client, title, location)
                    jobs.extend(found)
                    await asyncio.sleep(2)

        logger.info(f"Indeed: found {len(jobs)} jobs")
        return jobs[:self.jobs_per_source]

    async def _search(self, client: httpx.AsyncClient, title: str, location: str) -> List[Dict]:
        jobs = []
        params = {
            "q": title,
            "l": location,
            "sort": "date",
            "fromage": "7",       # last 7 days
            "limit": "20",
            "format": "json",
        }
        try:
            # Hit the public search page and extract embedded JSON
            resp = await client.get(
                f"{self.BASE_URL}/jobs",
                params={"q": title, "l": location, "sort": "date", "fromage": "7"},
            )
            if resp.status_code != 200:
                logger.debug(f"Indeed search returned {resp.status_code}")
                return []

            html = resp.text
            # Indeed embeds job data as JSON in a <script> tag
            # Try to extract the jobKeysWithInfo or mosaic data
            match = re.search(r'window\.mosaic\.providerData\["mosaic-provider-jobcards"\]\s*=\s*(\{.*?\});', html, re.DOTALL)
            if not match:
                # Try alternate pattern
                match = re.search(r'"jobKeys"\s*:\s*(\[.*?\])', html, re.DOTALL)

            if match:
                try:
                    raw = json.loads(match.group(1))
                    results = raw.get("metaData", {}).get("mosaicProviderJobCardsModel", {}).get("results", [])
                    if not results:
                        results = raw.get("results", [])
                except Exception:
                    results = []

                for item in results[:20]:
                    job = self._parse_item(item)
                    if job:
                        cleaned = self._clean_job(job)
                        if cleaned:
                            jobs.append(cleaned)
            else:
                # Fallback: parse job cards from HTML directly
                jobs.extend(self._parse_html_cards(html))

        except Exception as e:
            logger.debug(f"Indeed search error for '{title}': {e}")

        return jobs

    def _parse_item(self, item: dict) -> Optional[Dict]:
        try:
            job_key = item.get("jobkey", "")
            title = item.get("normTitle") or item.get("title", "")
            company = item.get("company", "")
            location = item.get("formattedLocation") or item.get("location", "")
            salary = ""
            salary_info = item.get("extractedSalary", {})
            if salary_info:
                lo = salary_info.get("min")
                hi = salary_info.get("max")
                t  = salary_info.get("type", "year")
                if lo and hi:
                    salary = f"${lo:,.0f} - ${hi:,.0f} / {t}"

            snippet = item.get("snippet", "") or ""
            desc = re.sub(r"<[^>]+>", "", snippet)

            if not title or not company or not job_key:
                return None

            url = f"https://www.indeed.com/viewjob?jk={job_key}"
            return {
                "source": "indeed",
                "job_id": job_key,
                "title": title,
                "company": company,
                "location": location,
                "description": desc,
                "url": url,
                "apply_url": url,
                "salary": salary,
                "job_type": None,
                "posted_date": item.get("pubDate") or item.get("createDate"),
            }
        except Exception:
            return None

    def _parse_html_cards(self, html: str) -> List[Dict]:
        """Last-resort: regex-based HTML parse."""
        jobs = []
        # Extract job keys
        job_keys = re.findall(r'data-jk="([a-f0-9]+)"', html)
        titles   = re.findall(r'class="jobTitle[^"]*"[^>]*>\s*<[^>]+>([^<]+)<', html)
        companies = re.findall(r'class="companyName[^"]*"[^>]*>([^<]+)<', html)

        for i, jk in enumerate(job_keys[:20]):
            title   = titles[i].strip()   if i < len(titles)    else "Software Engineer"
            company = companies[i].strip() if i < len(companies) else "Unknown"
            url = f"https://www.indeed.com/viewjob?jk={jk}"
            job = {
                "source": "indeed",
                "job_id": jk,
                "title": title,
                "company": company,
                "location": "",
                "description": "",
                "url": url,
                "apply_url": url,
                "salary": None,
                "job_type": None,
                "posted_date": None,
            }
            cleaned = self._clean_job(job)
            if cleaned:
                jobs.append(cleaned)
        return jobs
