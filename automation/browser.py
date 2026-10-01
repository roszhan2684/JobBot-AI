"""
Playwright browser manager.
Handles browser lifecycle, stealth settings, cookie persistence,
and provides a context manager for pages.
"""
import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

logger = logging.getLogger(__name__)

COOKIES_DIR = Path("./cookies")
COOKIES_DIR.mkdir(exist_ok=True)


class BrowserManager:
    """
    Manages a single persistent Playwright browser instance.
    Applies stealth headers to reduce detection.
    """

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None

    async def start(self):
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--window-size=1920,1080",
                "--disable-extensions",
                "--disable-dev-shm-usage",
                "--no-first-run",
                "--no-default-browser-check",
            ]
        )
        self._context = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="America/New_York",
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        # Stealth: hide webdriver flag
        await self._context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            window.chrome = { runtime: {} };
        """)
        logger.info("Browser started (headless=%s)", self.headless)

    async def stop(self):
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("Browser stopped")

    @asynccontextmanager
    async def new_page(self):
        """Context manager that yields a fresh page and closes it after."""
        page = await self._context.new_page()
        try:
            yield page
        finally:
            try:
                await page.close()
            except Exception:
                pass

    async def save_cookies(self, page: Page, platform: str):
        """Save current page cookies to disk for reuse."""
        try:
            cookies = await self._context.cookies()
            path = COOKIES_DIR / f"{platform}.json"
            path.write_text(json.dumps(cookies))
            logger.debug(f"Saved {len(cookies)} cookies for {platform}")
        except Exception as e:
            logger.warning(f"Could not save cookies for {platform}: {e}")

    async def restore_cookies(self, page: Page, platform: str) -> bool:
        """Load saved cookies back into the browser context."""
        path = COOKIES_DIR / f"{platform}.json"
        if not path.exists():
            return False
        try:
            cookies = json.loads(path.read_text())
            await self._context.add_cookies(cookies)
            logger.debug(f"Restored {len(cookies)} cookies for {platform}")
            return True
        except Exception as e:
            logger.warning(f"Could not restore cookies for {platform}: {e}")
            return False

    async def clear_cookies(self, platform: Optional[str] = None):
        """Clear cookies for a platform or all cookies."""
        if platform:
            path = COOKIES_DIR / f"{platform}.json"
            if path.exists():
                path.unlink()
        await self._context.clear_cookies()

    async def take_screenshot(self, page: Page, filename: str) -> str:
        """Take a screenshot and save it."""
        screenshots_dir = Path("./screenshots")
        screenshots_dir.mkdir(exist_ok=True)
        path = screenshots_dir / filename
        await page.screenshot(path=str(path), full_page=True)
        return str(path)

    async def is_logged_in(self, page: Page, platform: str) -> bool:
        """Check if we are currently logged into a platform."""
        indicators = {
            "linkedin": ["nav.global-nav", ".global-nav__me-photo", "[data-test-id='nav-account']"],
            "indeed": [".gnav-logged-in", "#auth-header-link"],
            "dice": [".user-nav", ".logged-in"],
            "glassdoor": [".user-menu", ".signinStatus"],
        }
        for selector in indicators.get(platform, []):
            try:
                el = await page.query_selector(selector)
                if el:
                    return True
            except Exception:
                pass
        return False

    async def detect_captcha(self, page: Page) -> bool:
        """Detect if a CAPTCHA is blocking the page."""
        captcha_selectors = [
            "#recaptcha",
            ".g-recaptcha",
            "iframe[src*='recaptcha']",
            "iframe[src*='hcaptcha']",
            "#challenge-form",
            ".cf-challenge-running",
            "[data-testid='captcha']",
        ]
        for sel in captcha_selectors:
            try:
                el = await page.query_selector(sel)
                if el:
                    return True
            except Exception:
                pass
        return False
