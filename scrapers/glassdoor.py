"""
Glassdoor job scraper.
Uses Glassdoor's internal GraphQL API (same one the website calls).
No login required for public job listings.
"""
import httpx
import asyncio
import logging
import json
import re
from typing import List, Dict, Optional
from urllib.parse import quote_plus
from .base import BaseScraper

logger = logging.getLogger(__name__)


class GlassdoorScraper(BaseScraper):

    GRAPHQL_URL = "https://www.glassdoor.com/graph"

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
                "Accept": "application/json",
                "Content-Type": "application/json",
                "gd-csrf-token": "Ft6oHEWs3PsKDHFYsxADhQ:0qX5rNQ3M18MwYgLbLQjzOFR6Tu0_cO2dMbfanDgFBh5M0hTfXCUNwRK8iqHxlPnhxFUwKHmzqJFHCXfOVr_rQ:wcqHjxMHoA4IQXZ0JBBHsUo4AHonzFbfWVpgkBr5F2c",
                "Referer": "https://www.glassdoor.com/Job/jobs.htm",
            },
        ) as client:
            for title in self.search_titles[:3]:
                if len(jobs) >= self.jobs_per_source:
                    break
                found = await self._search(client, title)
                jobs.extend(found)
                await asyncio.sleep(2)

        logger.info(f"Glassdoor: found {len(jobs)} jobs")
        return jobs[:self.jobs_per_source]

    async def _search(self, client: httpx.AsyncClient, title: str) -> List[Dict]:
        jobs = []

        # Glassdoor GraphQL payload for job search
        payload = [{
            "operationName": "JobSearchResultsQuery",
            "variables": {
                "excludeJobListingIds": [],
                "filterParams": [],
                "keyword": title,
                "locationId": 0,
                "locationType": "ANYWHERE",
                "numJobsToShow": 30,
                "parameterUrlInput": f"KO0,{len(title)}",
                "pageType": "SERP",
                "pageCursor": None,
                "fromage": 7,
                "sort": "date",
            },
            "query": """
                query JobSearchResultsQuery(
                    $excludeJobListingIds: [Long!]!, $keyword: String,
                    $locationId: Int, $locationType: LocationTypeEnum,
                    $numJobsToShow: Int!, $pageCursor: String,
                    $pageType: PageTypeEnum, $filterParams: [FilterParams],
                    $sort: SortOrderEnum, $fromage: Int
                ) {
                    jobListings(
                        contextHolder: {
                            searchParams: {
                                excludeJobListingIds: $excludeJobListingIds,
                                keyword: $keyword, locationId: $locationId,
                                locationType: $locationType, numPerPage: $numJobsToShow,
                                pageCursor: $pageCursor, pageType: $pageType,
                                filterParams: $filterParams, sort: $sort, fromage: $fromage
                            }
                        }
                    ) {
                        jobListings {
                            jobview {
                                header {
                                    jobTitleText normalizedJobTitle
                                    employerNameFromSearch locationName
                                    indeedJobAttribute { salaryRange }
                                }
                                job { listingId descriptionFragments jobTitleId }
                                overview { squareLogoUrl }
                            }
                        }
                        paginationCursors { cursor pageNumber }
                    }
                }
            """
        }]

        try:
            resp = await client.post(self.GRAPHQL_URL, json=payload)
            if resp.status_code != 200:
                logger.debug(f"Glassdoor API {resp.status_code}: {resp.text[:200]}")
                return []

            data = resp.json()
            listings = data[0].get("data", {}).get("jobListings", {}).get("jobListings", [])

            for item in listings:
                jv = item.get("jobview", {})
                header = jv.get("header", {})
                job_info = jv.get("job", {})

                job_title  = header.get("jobTitleText") or header.get("normalizedJobTitle", "")
                company    = header.get("employerNameFromSearch", "")
                location   = header.get("locationName", "")
                listing_id = job_info.get("listingId", "")
                desc_frags = job_info.get("descriptionFragments", [])
                desc       = " ".join(desc_frags) if desc_frags else ""
                desc       = re.sub(r"<[^>]+>", "", desc)

                salary_info = header.get("indeedJobAttribute", {})
                salary = salary_info.get("salaryRange", "") if salary_info else ""

                if not job_title or not company or not listing_id:
                    continue

                url = f"https://www.glassdoor.com/job-listing/j?jid={listing_id}"
                job = {
                    "source": "glassdoor",
                    "job_id": str(listing_id),
                    "title": job_title,
                    "company": company,
                    "location": location,
                    "description": desc,
                    "url": url,
                    "apply_url": url,
                    "salary": salary,
                    "job_type": None,
                    "posted_date": None,
                }
                cleaned = self._clean_job(job)
                if cleaned:
                    jobs.append(cleaned)

        except Exception as e:
            logger.debug(f"Glassdoor API error for '{title}': {e}")

        return jobs
