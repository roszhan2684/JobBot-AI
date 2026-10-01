from .linkedin import LinkedInScraper
from .indeed import IndeedScraper
from .dice import DiceScraper
from .remoteok import RemoteOKScraper
from .weworkremotely import WeWorkRemotelyScraper
from .glassdoor import GlassdoorScraper
from .greenhouse import GreenhouseScraper
from .jobright import JobrightScraper
from .faang import FAANGScraper

SCRAPERS = {
    "linkedin": LinkedInScraper,
    "indeed": IndeedScraper,
    "dice": DiceScraper,
    "remoteok": RemoteOKScraper,
    "weworkremotely": WeWorkRemotelyScraper,
    "glassdoor": GlassdoorScraper,
    "greenhouse": GreenhouseScraper,
    "jobright": JobrightScraper,
    "faang": FAANGScraper,
}


def get_scraper(name: str, config: dict, browser_manager=None):
    cls = SCRAPERS.get(name)
    if not cls:
        raise ValueError(f"Unknown scraper: {name}. Available: {list(SCRAPERS.keys())}")
    return cls(config, browser_manager)
