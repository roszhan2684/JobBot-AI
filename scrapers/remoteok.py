"""
RemoteOK scraper - uses their public JSON API, no login needed.
"""
import httpx
import asyncio
import logging
from typing import List, Dict
from .base import BaseScraper

logger = logging.getLogger(__name__)

REMOTEOK_API = "https://remoteok.com/api"


class RemoteOKScraper(BaseScraper):

    async def scrape(self) -> List[Dict]:
        jobs = []
        try:
            async with httpx.AsyncClient(timeout=30, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            }) as client:
                resp = await client.get(REMOTEOK_API)
                resp.raise_for_status()
                data = resp.json()

            # First element is legal notice, skip it
            listings = [item for item in data if isinstance(item, dict) and item.get("slug")]

            # Filter by keywords
            kws = [k.lower() for k in self.keywords + self.search_titles]
            count = 0
            for item in listings:
                if count >= self.jobs_per_source:
                    break
                tags = [t.lower() for t in (item.get("tags") or [])]
                title_lower = (item.get("position", "") or "").lower()
                desc_lower = (item.get("description", "") or "").lower()

                relevant = any(
                    kw in title_lower or kw in " ".join(tags) or kw in desc_lower
                    for kw in kws
                )
                if not relevant:
                    continue

                job = {
                    "source": "remoteok",
                    "job_id": item.get("id"),
                    "title": item.get("position", ""),
                    "company": item.get("company", ""),
                    "location": "Remote",
                    "description": self._strip_html(item.get("description", "")),
                    "url": item.get("url", f"https://remoteok.com/remote-jobs/{item.get('slug')}"),
                    "apply_url": item.get("apply_url") or item.get("url"),
                    "salary": self._format_salary(item),
                    "job_type": "remote",
                    "posted_date": item.get("date"),
                }
                cleaned = self._clean_job(job)
                if cleaned:
                    jobs.append(cleaned)
                    count += 1

            logger.info(f"RemoteOK: found {len(jobs)} matching jobs")
        except Exception as e:
            logger.error(f"RemoteOK scrape failed: {e}")

        return jobs

    def _format_salary(self, item: dict) -> str:
        lo = item.get("salary_min")
        hi = item.get("salary_max")
        if lo and hi:
            return f"${lo:,} - ${hi:,}"
        elif lo:
            return f"${lo:,}+"
        return ""

    def _strip_html(self, text: str) -> str:
        if not text:
            return ""
        import re
        clean = re.compile("<.*?>")
        return re.sub(clean, "", text).strip()
