"""
Greenhouse ATS scraper.
Greenhouse powers career pages for hundreds of top companies.
We use their public API: https://boards-api.greenhouse.io/v1/boards/{company}/jobs

Companies list includes many well-known tech companies that use Greenhouse.
"""
import httpx
import asyncio
import logging
from typing import List, Dict
from .base import BaseScraper

logger = logging.getLogger(__name__)

# Well-known tech companies using Greenhouse ATS
# Add/remove companies based on your preferences
GREENHOUSE_COMPANIES = [
    "airbnb", "stripe", "databricks", "figma", "notion",
    "airtable", "brex", "scale", "confluent", "hashicorp",
    "mongodb", "cockroachlabs", "vercel", "linear",
    "retool", "segment", "mixpanel", "twilio", "sendgrid",
    "cloudflare", "fastly", "okta", "auth0", "pagerduty",
    "datadog", "newrelic", "splunk", "elastic", "grafana",
    "gitlab", "github", "atlassian", "jira", "zendesk",
    "hubspot", "intercom", "drift", "outreach", "salesloft",
    "asana", "monday", "clickup", "basecamp", "trello",
    "dropbox", "box", "docusign", "zoom", "slack",
    "shopify", "squarespace", "wix", "webflow", "contentful",
    "plaid", "rippling", "gusto", "deel", "remote",
    "duolingo", "coursera", "udemy", "chegg", "kahoot",
    "coinbase", "robinhood", "betterment", "sofi", "affirm",
    "lyft", "doordash", "instacart", "grubhub", "postmates",
    "waymo", "cruise", "aurora", "rivian", "lucidmotors",
]


class GreenhouseScraper(BaseScraper):

    API_BASE = "https://boards-api.greenhouse.io/v1/boards/{company}/jobs"

    async def scrape(self) -> List[Dict]:
        jobs = []
        kws = [k.lower() for k in self.keywords + self.search_titles]

        companies = self.config.get("greenhouse_companies", GREENHOUSE_COMPANIES)

        async with httpx.AsyncClient(timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
        }) as client:
            # Process companies in batches of 5 concurrently
            batch_size = 5
            for i in range(0, len(companies), batch_size):
                if len(jobs) >= self.jobs_per_source:
                    break
                batch = companies[i:i + batch_size]
                tasks = [self._fetch_company_jobs(client, company, kws) for company in batch]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for result in results:
                    if isinstance(result, list):
                        for job in result:
                            if len(jobs) >= self.jobs_per_source:
                                break
                            cleaned = self._clean_job(job)
                            if cleaned:
                                jobs.append(cleaned)

                await asyncio.sleep(0.5)  # Be polite

        logger.info(f"Greenhouse: found {len(jobs)} matching jobs")
        return jobs

    async def _fetch_company_jobs(self, client: httpx.AsyncClient, company: str, kws: List[str]) -> List[Dict]:
        jobs = []
        try:
            url = self.API_BASE.format(company=company)
            resp = await client.get(url)
            if resp.status_code != 200:
                return []

            data = resp.json()
            for item in data.get("jobs", []):
                title = item.get("title", "")
                title_lower = title.lower()
                dept = (item.get("departments", [{}])[0].get("name", "") or "").lower()

                relevant = any(kw in title_lower or kw in dept for kw in kws)
                if not relevant:
                    continue

                location_info = item.get("location", {})
                location = location_info.get("name", "") if isinstance(location_info, dict) else str(location_info)

                job = {
                    "source": "greenhouse",
                    "job_id": str(item.get("id", "")),
                    "title": title,
                    "company": company.replace("-", " ").title(),
                    "location": location,
                    "description": "",  # Brief only in list view
                    "url": item.get("absolute_url", ""),
                    "apply_url": item.get("absolute_url", ""),
                    "salary": None,
                    "job_type": None,
                    "posted_date": item.get("updated_at"),
                }
                jobs.append(job)

        except Exception as e:
            logger.debug(f"Greenhouse {company}: {e}")

        return jobs
