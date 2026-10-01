"""
Dice.com job scraper - tech-focused job board.
Uses their public search API.
"""
import httpx
import asyncio
import logging
from typing import List, Dict
from .base import BaseScraper

logger = logging.getLogger(__name__)


class DiceScraper(BaseScraper):

    API_URL = "https://job-search-api.svc.dhigroupinc.com/v1/dice/jobs/search"

    async def scrape(self) -> List[Dict]:
        jobs = []
        kws = self.keywords + self.search_titles

        try:
            async with httpx.AsyncClient(timeout=30, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
                "x-api-key": "1YAt0R9wBg4WfsF9VB2778F5CHLAPMVW3WAZcKd8",
                "Accept": "application/json",
            }) as client:
                for title in self.search_titles[:3]:
                    if len(jobs) >= self.jobs_per_source:
                        break

                    params = {
                        "q": title,
                        "countryCode2": "US",
                        "radius": "30",
                        "radiusUnit": "mi",
                        "page": 1,
                        "pageSize": min(20, self.jobs_per_source),
                        "filters.postedDate": "ONE_DAY",
                        "language": "en",
                    }

                    # Add location if not remote-only
                    locations = self.search_locations
                    if locations and "remote" not in [l.lower() for l in locations]:
                        params["location"] = locations[0]

                    try:
                        resp = await client.get(self.API_URL, params=params)
                        resp.raise_for_status()
                        data = resp.json()

                        for item in data.get("data", []):
                            if len(jobs) >= self.jobs_per_source:
                                break

                            job_id = item.get("id", "")
                            job = {
                                "source": "dice",
                                "job_id": job_id,
                                "title": item.get("title", ""),
                                "company": item.get("companyPageUrl", "").split("/")[-1] or item.get("hiringOrganization", {}).get("name", ""),
                                "location": self._format_location(item),
                                "description": item.get("description", ""),
                                "url": f"https://www.dice.com/job-detail/{job_id}",
                                "apply_url": item.get("applyDataItem", {}).get("applyUrl") or f"https://www.dice.com/job-detail/{job_id}",
                                "salary": self._format_salary(item),
                                "job_type": item.get("workplaceTypes", [""])[0] if item.get("workplaceTypes") else None,
                                "posted_date": item.get("postedDate"),
                            }
                            company_name = item.get("advertiserName") or item.get("companyPageUrl", "").split("/")[-1]
                            job["company"] = company_name or "Unknown"

                            cleaned = self._clean_job(job)
                            if cleaned:
                                jobs.append(cleaned)

                        await asyncio.sleep(1)

                    except Exception as e:
                        logger.error(f"Dice API error for '{title}': {e}")

        except Exception as e:
            logger.error(f"Dice scraper failed: {e}")

        logger.info(f"Dice: found {len(jobs)} jobs")
        return jobs

    def _format_location(self, item: dict) -> str:
        loc = item.get("locationDetails", {})
        city = loc.get("city", "")
        state = loc.get("state", "")
        remote = item.get("workplaceTypes", [])
        if "REMOTE" in remote:
            return "Remote"
        if city and state:
            return f"{city}, {state}"
        return item.get("location", "")

    def _format_salary(self, item: dict) -> str:
        wage = item.get("wage", {})
        if not wage:
            return ""
        lo = wage.get("minimum")
        hi = wage.get("maximum")
        freq = wage.get("period", "year")
        if lo and hi:
            return f"${lo:,} - ${hi:,} / {freq}"
        elif lo:
            return f"${lo:,}+ / {freq}"
        return ""
