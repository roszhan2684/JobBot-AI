"""
FAANG + Big Tech direct career page scrapers.
Scrapes job listings from: Google, Apple, Amazon, Meta, Netflix,
Microsoft, Nvidia, Salesforce, Oracle, IBM, Twitter/X, Uber, Airbnb.

Each company has its own career site format, handled individually.
"""
import httpx
import asyncio
import logging
import json
import re
from typing import List, Dict, Optional
from .base import BaseScraper

logger = logging.getLogger(__name__)


class FAANGScraper(BaseScraper):
    """Scrapes multiple big tech company career pages."""

    async def scrape(self) -> List[Dict]:
        kws = [k.lower() for k in self.keywords + self.search_titles]
        jobs = []

        scrapers = [
            self._scrape_google(kws),
            self._scrape_meta(kws),
            self._scrape_amazon(kws),
            self._scrape_netflix(kws),
            self._scrape_microsoft(kws),
            self._scrape_apple(kws),
            self._scrape_nvidia(kws),
            self._scrape_uber(kws),
        ]

        results = await asyncio.gather(*scrapers, return_exceptions=True)
        for result in results:
            if isinstance(result, list):
                jobs.extend(result)
            elif isinstance(result, Exception):
                logger.debug(f"FAANG scraper error: {result}")

        logger.info(f"FAANG/BigTech: found {len(jobs)} matching jobs")
        return jobs[:self.jobs_per_source]

    async def _scrape_google(self, kws: List[str]) -> List[Dict]:
        """Google Careers — via Greenhouse ATS (Google uses Greenhouse for many roles)."""
        jobs = []
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
            }) as client:
                # Google's actual careers API endpoint
                for title in self.search_titles[:2]:
                    resp = await client.get(
                        "https://careers.google.com/api/v3/search/",
                        params={"q": title, "sort_by": "date", "jlo": "en_US", "page_size": 20}
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        for item in data.get("jobs", [])[:15]:
                            title_str = item.get("title", "")
                            if not any(kw in title_str.lower() for kw in kws):
                                continue
                            locations = item.get("locations", [{}])
                            loc = locations[0].get("display", "Mountain View, CA") if locations else ""
                            job_id = item.get("job_id", "")
                            job = {
                                "source": "google_careers",
                                "job_id": job_id,
                                "title": title_str,
                                "company": "Google",
                                "location": loc,
                                "description": item.get("summary", ""),
                                "url": f"https://careers.google.com/jobs/results/{job_id}",
                                "apply_url": f"https://careers.google.com/jobs/results/{job_id}",
                                "salary": None,
                                "job_type": None,
                                "posted_date": item.get("publish_date"),
                            }
                            cleaned = self._clean_job(job)
                            if cleaned:
                                jobs.append(cleaned)
                    await asyncio.sleep(1)
        except Exception as e:
            logger.debug(f"Google scrape error: {e}")
        return jobs

    async def _scrape_meta(self, kws: List[str]) -> List[Dict]:
        """Meta Careers — uses their REST search API."""
        jobs = []
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
                "Accept": "application/json",
                "Referer": "https://www.metacareers.com/jobs/",
            }) as client:
                for title in self.search_titles[:2]:
                    try:
                        resp = await client.get(
                            "https://www.metacareers.com/careers/jobs/",
                            params={"q": title, "sort_by_new": "true", "results_per_page": 15}
                        )
                        if resp.status_code != 200:
                            continue
                        data = resp.json()
                        results = data.get("data", [])
                        if not results:
                            results = data.get("results", [])

                        for item in results[:15]:
                            title_str = item.get("title", "")
                            if not any(kw in title_str.lower() for kw in kws):
                                continue
                            job_id = str(item.get("id", ""))
                            loc_data = item.get("locations", item.get("location", {}))
                            if isinstance(loc_data, list):
                                loc = ", ".join(str(l) for l in loc_data[:2])
                            elif isinstance(loc_data, dict):
                                loc = loc_data.get("name", "")
                            else:
                                loc = str(loc_data)
                            job = {
                                "source": "meta_careers",
                                "job_id": job_id,
                                "title": title_str,
                                "company": "Meta",
                                "location": loc,
                                "description": item.get("description", ""),
                                "url": f"https://www.metacareers.com/jobs/{job_id}/",
                                "apply_url": f"https://www.metacareers.com/jobs/{job_id}/",
                                "salary": None,
                                "job_type": None,
                                "posted_date": item.get("post_date"),
                            }
                            cleaned = self._clean_job(job)
                            if cleaned:
                                jobs.append(cleaned)
                    except Exception as e:
                        logger.debug(f"Meta API error: {e}")
                    await asyncio.sleep(1)
        except Exception as e:
            logger.debug(f"Meta scrape error: {e}")
        return jobs

    async def _scrape_amazon(self, kws: List[str]) -> List[Dict]:
        """Amazon Jobs - uses their public search API."""
        jobs = []
        try:
            async with httpx.AsyncClient(timeout=20, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
            }) as client:
                for title in self.search_titles[:2]:
                    resp = await client.get(
                        "https://www.amazon.jobs/en/search.json",
                        params={
                            "query": title,
                            "sort": "recent",
                            "offset": 0,
                            "result_limit": 15,
                        }
                    )
                    if resp.status_code != 200:
                        continue

                    data = resp.json()
                    for item in data.get("jobs", []):
                        title_str = item.get("title", "")
                        if not any(kw in title_str.lower() for kw in kws):
                            continue

                        job_path = item.get("job_path", "")
                        job = {
                            "source": "amazon_jobs",
                            "job_id": item.get("job_id", ""),
                            "title": title_str,
                            "company": "Amazon",
                            "location": item.get("location", ""),
                            "description": item.get("description_short", ""),
                            "url": f"https://www.amazon.jobs{job_path}",
                            "apply_url": f"https://www.amazon.jobs{job_path}",
                            "salary": None,
                            "job_type": None,
                            "posted_date": item.get("posted_date"),
                        }
                        cleaned = self._clean_job(job)
                        if cleaned:
                            jobs.append(cleaned)
                    await asyncio.sleep(1)
        except Exception as e:
            logger.debug(f"Amazon scrape error: {e}")
        return jobs

    async def _scrape_netflix(self, kws: List[str]) -> List[Dict]:
        """Netflix Jobs — uses Greenhouse ATS (Netflix moved to Greenhouse)."""
        jobs = []
        try:
            async with httpx.AsyncClient(
                timeout=20,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
            ) as client:
                resp = await client.get("https://boards-api.greenhouse.io/v1/boards/netflix/jobs")
                if resp.status_code != 200:
                    return jobs
                data = resp.json()
                for item in data.get("jobs", []):
                    title_str = item.get("title", "")
                    if not any(kw in title_str.lower() for kw in kws):
                        continue
                    loc = item.get("location", {})
                    location_str = loc.get("name", "") if isinstance(loc, dict) else str(loc)
                    job = {
                        "source": "netflix_jobs",
                        "job_id": str(item.get("id", "")),
                        "title": title_str,
                        "company": "Netflix",
                        "location": location_str,
                        "description": "",
                        "url": item.get("absolute_url", ""),
                        "apply_url": item.get("absolute_url", ""),
                        "salary": None,
                        "job_type": None,
                        "posted_date": item.get("updated_at"),
                    }
                    cleaned = self._clean_job(job)
                    if cleaned:
                        jobs.append(cleaned)
        except Exception as e:
            logger.debug(f"Netflix scrape error: {e}")
        return jobs

    async def _scrape_microsoft(self, kws: List[str]) -> List[Dict]:
        """Microsoft Careers - uses their public API."""
        jobs = []
        try:
            async with httpx.AsyncClient(timeout=20, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
            }) as client:
                for title in self.search_titles[:2]:
                    resp = await client.get(
                        "https://gcsservices.careers.microsoft.com/search/api/v1/search",
                        params={
                            "q": title,
                            "l": "en_us",
                            "pgSz": 15,
                            "o": "Recent",
                        }
                    )
                    if resp.status_code != 200:
                        continue

                    data = resp.json()
                    for item in data.get("operationResult", {}).get("result", {}).get("jobs", []):
                        title_str = item.get("title", "")
                        if not any(kw in title_str.lower() for kw in kws):
                            continue

                        job_id = item.get("jobId", "")
                        job = {
                            "source": "microsoft_careers",
                            "job_id": job_id,
                            "title": title_str,
                            "company": "Microsoft",
                            "location": item.get("primaryLocation", ""),
                            "description": item.get("descriptionTeaser", ""),
                            "url": f"https://careers.microsoft.com/us/en/job/{job_id}",
                            "apply_url": f"https://careers.microsoft.com/us/en/job/{job_id}",
                            "salary": None,
                            "job_type": None,
                            "posted_date": item.get("postingDate"),
                        }
                        cleaned = self._clean_job(job)
                        if cleaned:
                            jobs.append(cleaned)
                    await asyncio.sleep(1)
        except Exception as e:
            logger.debug(f"Microsoft scrape error: {e}")
        return jobs

    async def _scrape_apple(self, kws: List[str]) -> List[Dict]:
        """Apple Jobs — uses their search API with correct headers."""
        jobs = []
        try:
            async with httpx.AsyncClient(
                timeout=20,
                follow_redirects=False,   # don't follow — Apple redirects to 404
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
                    "Accept": "application/json, text/plain, */*",
                    "Referer": "https://jobs.apple.com/en-us/search",
                }
            ) as client:
                for title in self.search_titles[:2]:
                    resp = await client.get(
                        "https://jobs.apple.com/api/role/search",
                        params={"query": title, "limit": 20, "language": "en-us"}
                    )
                    if resp.status_code not in (200, 201):
                        logger.debug(f"Apple returned {resp.status_code}")
                        continue
                    data = resp.json()
                    for item in data.get("searchResults", []):
                        title_str = item.get("postingTitle", "")
                        if not any(kw in title_str.lower() for kw in kws):
                            continue
                        job_id = item.get("positionId", "")
                        locations = item.get("locations", [{}])
                        loc = locations[0].get("name", "") if locations else ""
                        job = {
                            "source": "apple_jobs",
                            "job_id": job_id,
                            "title": title_str,
                            "company": "Apple",
                            "location": loc,
                            "description": item.get("jobSummary", ""),
                            "url": f"https://jobs.apple.com/en-us/details/{job_id}",
                            "apply_url": f"https://jobs.apple.com/en-us/details/{job_id}",
                            "salary": None,
                            "job_type": None,
                            "posted_date": item.get("postingDate"),
                        }
                        cleaned = self._clean_job(job)
                        if cleaned:
                            jobs.append(cleaned)
                    await asyncio.sleep(1)
        except Exception as e:
            logger.debug(f"Apple scrape error: {e}")
        return jobs

    async def _scrape_nvidia(self, kws: List[str]) -> List[Dict]:
        """Nvidia Jobs - uses their API."""
        jobs = []
        try:
            async with httpx.AsyncClient(timeout=20, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
            }) as client:
                for title in self.search_titles[:2]:
                    resp = await client.get(
                        "https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs",
                        params={"q": title, "limit": 15},
                        headers={"Content-Type": "application/json"}
                    )
                    if resp.status_code != 200:
                        continue

                    data = resp.json()
                    for item in data.get("jobPostings", []):
                        title_str = item.get("title", "")
                        if not any(kw in title_str.lower() for kw in kws):
                            continue

                        ext_id = item.get("externalPath", "").split("/")[-1]
                        job = {
                            "source": "nvidia_jobs",
                            "job_id": ext_id,
                            "title": title_str,
                            "company": "NVIDIA",
                            "location": item.get("locationsText", "Santa Clara, CA"),
                            "description": item.get("jobReqId", ""),
                            "url": f"https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/{ext_id}",
                            "apply_url": f"https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/{ext_id}",
                            "salary": None,
                            "job_type": None,
                            "posted_date": item.get("postedOn"),
                        }
                        cleaned = self._clean_job(job)
                        if cleaned:
                            jobs.append(cleaned)
                    await asyncio.sleep(1)
        except Exception as e:
            logger.debug(f"NVIDIA scrape error: {e}")
        return jobs

    async def _scrape_uber(self, kws: List[str]) -> List[Dict]:
        """Uber Jobs - uses their public API."""
        jobs = []
        try:
            async with httpx.AsyncClient(timeout=20, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
            }) as client:
                for title in self.search_titles[:2]:
                    resp = await client.get(
                        "https://www.uber.com/api/loadSearchJobsResults",
                        params={"query": title, "department": "", "location": "", "limit": 15}
                    )
                    if resp.status_code != 200:
                        continue

                    try:
                        data = resp.json()
                        for item in data.get("data", {}).get("results", []):
                            title_str = item.get("title", "")
                            if not any(kw in title_str.lower() for kw in kws):
                                continue

                            job_id = item.get("id", "")
                            job = {
                                "source": "uber_jobs",
                                "job_id": str(job_id),
                                "title": title_str,
                                "company": "Uber",
                                "location": item.get("location", "San Francisco, CA"),
                                "description": item.get("description", "")[:500],
                                "url": f"https://www.uber.com/global/en/careers/list/{job_id}/",
                                "apply_url": f"https://www.uber.com/global/en/careers/list/{job_id}/",
                                "salary": None,
                                "job_type": None,
                                "posted_date": None,
                            }
                            cleaned = self._clean_job(job)
                            if cleaned:
                                jobs.append(cleaned)
                    except Exception:
                        pass
                    await asyncio.sleep(1)
        except Exception as e:
            logger.debug(f"Uber scrape error: {e}")
        return jobs
