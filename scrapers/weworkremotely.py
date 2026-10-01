"""
We Work Remotely scraper - scrapes their RSS feed, no login needed.
"""
import httpx
import asyncio
import logging
import re
from xml.etree import ElementTree
from typing import List, Dict
from .base import BaseScraper

logger = logging.getLogger(__name__)

WWR_RSS_URLS = [
    "https://weworkremotely.com/remote-jobs.rss",
    "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
    "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-front-end-programming-jobs.rss",
]


class WeWorkRemotelyScraper(BaseScraper):

    async def scrape(self) -> List[Dict]:
        jobs = []
        kws = [k.lower() for k in self.keywords + self.search_titles]

        async with httpx.AsyncClient(timeout=30, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
        }) as client:
            for rss_url in WWR_RSS_URLS:
                if len(jobs) >= self.jobs_per_source:
                    break
                try:
                    resp = await client.get(rss_url)
                    resp.raise_for_status()
                    root = ElementTree.fromstring(resp.content)

                    for item in root.findall(".//item"):
                        if len(jobs) >= self.jobs_per_source:
                            break

                        title_el = item.find("title")
                        link_el = item.find("link")
                        desc_el = item.find("description")

                        if title_el is None or link_el is None:
                            continue

                        full_title = title_el.text or ""
                        # Format: "Company: Job Title"
                        parts = full_title.split(": ", 1)
                        company = parts[0].strip() if len(parts) > 1 else "Unknown"
                        title = parts[1].strip() if len(parts) > 1 else full_title.strip()

                        desc = self._strip_html(desc_el.text or "") if desc_el is not None else ""
                        url = link_el.text or ""

                        title_lower = title.lower()
                        desc_lower = desc.lower()
                        relevant = any(kw in title_lower or kw in desc_lower for kw in kws)
                        if not relevant:
                            continue

                        pub_date_el = item.find("pubDate")
                        posted = pub_date_el.text if pub_date_el is not None else None

                        job = {
                            "source": "weworkremotely",
                            "job_id": None,
                            "title": title,
                            "company": company,
                            "location": "Remote",
                            "description": desc,
                            "url": url,
                            "apply_url": url,
                            "salary": None,
                            "job_type": "remote",
                            "posted_date": posted,
                        }
                        cleaned = self._clean_job(job)
                        if cleaned:
                            jobs.append(cleaned)

                except Exception as e:
                    logger.warning(f"WWR RSS {rss_url} failed: {e}")

        logger.info(f"WeWorkRemotely: found {len(jobs)} matching jobs")
        return jobs

    def _strip_html(self, text: str) -> str:
        return re.sub(r"<[^>]+>", "", text).strip()
