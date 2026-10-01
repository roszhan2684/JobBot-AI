"""
Base scraper interface. All scrapers must implement `scrape()`.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """
    Each scraper returns a list of job dicts with these keys:
        source, job_id, title, company, location, description,
        url, apply_url, salary, job_type, posted_date
    """

    def __init__(self, config: dict, browser_manager=None):
        self.config = config
        self.browser_manager = browser_manager
        self.user = config.get("user", {})
        self.prefs = config.get("job_preferences", {})
        self.settings = config.get("settings", {})
        self.credentials = config.get("credentials", {})

    @property
    def search_titles(self) -> List[str]:
        return self.prefs.get("titles", ["Software Engineer"])

    @property
    def search_locations(self) -> List[str]:
        return self.prefs.get("locations", ["Remote"])

    @property
    def keywords(self) -> List[str]:
        return self.prefs.get("keywords", [])

    @property
    def jobs_per_source(self) -> int:
        return self.settings.get("jobs_per_source", 50)

    @abstractmethod
    async def scrape(self) -> List[Dict]:
        """Scrape jobs and return list of job dicts."""
        pass

    def _clean_job(self, job: dict) -> Optional[dict]:
        """Validate and clean a job dict."""
        if not job.get("url") or not job.get("title") or not job.get("company"):
            return None
        # Exclude filtered companies/keywords
        exclude_companies = self.prefs.get("exclude_companies", [])
        exclude_keywords = self.prefs.get("exclude_keywords", [])
        company_lower = job.get("company", "").lower()
        desc_lower = (job.get("description", "") or "").lower()
        title_lower = job.get("title", "").lower()
        for ec in exclude_companies:
            if ec.lower() in company_lower:
                return None
        for ek in exclude_keywords:
            if ek.lower() in desc_lower or ek.lower() in title_lower:
                return None
        return job

    def _is_remote_job(self, job: dict) -> bool:
        loc = (job.get("location", "") or "").lower()
        desc = (job.get("description", "") or "").lower()
        return "remote" in loc or "remote" in desc or "work from home" in desc
