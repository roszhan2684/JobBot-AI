"""
Jobright.ai scraper — uses their public search API.
"""
import httpx
import asyncio
import logging
from typing import List, Dict, Optional
from urllib.parse import quote_plus
from .base import BaseScraper

logger = logging.getLogger(__name__)


class JobrightScraper(BaseScraper):

    API_URL = "https://api.jobright.ai/jobs/search"

    async def scrape(self) -> List[Dict]:
        jobs = []
        async with httpx.AsyncClient(
            timeout=20,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
                "Accept": "application/json",
                "Origin": "https://jobright.ai",
                "Referer": "https://jobright.ai/",
            },
        ) as client:
            for title in self.search_titles[:3]:
                if len(jobs) >= self.jobs_per_source:
                    break
                found = await self._search(client, title)
                jobs.extend(found)
                await asyncio.sleep(1.5)

        logger.info(f"Jobright: found {len(jobs)} jobs")
        return jobs[:self.jobs_per_source]

    async def _search(self, client: httpx.AsyncClient, title: str) -> List[Dict]:
        jobs = []
        try:
            resp = await client.get(
                self.API_URL,
                params={
                    "keyword": title,
                    "page": 1,
                    "pageSize": 20,
                    "sortBy": "date",
                },
            )
            if resp.status_code != 200:
                logger.debug(f"Jobright API {resp.status_code}")
                return []

            data = resp.json()
            items = data.get("data", data.get("jobs", data.get("results", [])))
            if not isinstance(items, list):
                return []

            for item in items:
                job = self._parse_item(item)
                if job:
                    cleaned = self._clean_job(job)
                    if cleaned:
                        jobs.append(cleaned)

        except Exception as e:
            logger.debug(f"Jobright search error: {e}")

        return jobs

    def _parse_item(self, item: dict) -> Optional[Dict]:
        try:
            title   = item.get("title") or item.get("jobTitle", "")
            company = item.get("company") or item.get("companyName", "")
            location = item.get("location", "") or ""
            url = item.get("url") or item.get("jobUrl") or item.get("applyUrl", "")
            job_id = str(item.get("id") or item.get("jobId", ""))
            if not url and job_id:
                url = f"https://jobright.ai/jobs/info/{job_id}"

            if not title or not company or not url:
                return None

            return {
                "source": "jobright",
                "job_id": job_id,
                "title": title,
                "company": company,
                "location": location,
                "description": item.get("description", "") or "",
                "url": url,
                "apply_url": url,
                "salary": item.get("salary") or item.get("compensation", ""),
                "job_type": item.get("jobType") or item.get("workType", ""),
                "posted_date": item.get("postedDate") or item.get("createdAt", ""),
            }
        except Exception:
            return None
