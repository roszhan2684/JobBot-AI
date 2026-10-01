"""
Handles logging into job sites and creating accounts where needed.
Stores session cookies so we stay logged in across runs.
"""
import asyncio
import logging
import imaplib
import email as email_lib
import re
from typing import Optional, Dict
from playwright.async_api import Page
from .browser import BrowserManager

logger = logging.getLogger(__name__)


class LoginManager:
    """Manages logins for all job platforms."""

    def __init__(self, config: dict, browser_manager: BrowserManager):
        self.config = config
        self.browser = browser_manager
        self.credentials = config.get("credentials", {})
        self.user = config.get("user", {})

    async def login_all(self, page: Page):
        """Attempt to log in to all configured platforms."""
        sources = self.config.get("job_sources", [])
        for platform in sources:
            creds = self.credentials.get(platform, {})
            if creds.get("email") and creds.get("password"):
                success = await self.login(page, platform)
                if success:
                    logger.info(f"Logged in to {platform}")
                else:
                    logger.warning(f"Failed to log in to {platform}")
            await asyncio.sleep(2)

    async def login(self, page: Page, platform: str) -> bool:
        """Log into a platform. Returns True on success."""
        # Try restoring session first
        restored = await self.browser.restore_cookies(page, platform)
        if restored:
            if platform == "linkedin":
                await page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=25000)
                await asyncio.sleep(3)
                # If URL is not on login page, we're good
                if "/login" not in page.url and "/authwall" not in page.url:
                    logger.info(f"LinkedIn: session restored from cookies")
                    return True

        # Fresh login
        handlers = {
            "linkedin": self._login_linkedin,
            "indeed": self._login_indeed,
            "dice": self._login_dice,
            "glassdoor": self._login_glassdoor,
        }
        handler = handlers.get(platform)
        if not handler:
            return False

        try:
            success = await handler(page)
            if success:
                await self.browser.save_cookies(page, platform)
            return success
        except Exception as e:
            logger.error(f"Login to {platform} failed: {e}")
            return False

    async def _login_linkedin(self, page: Page) -> bool:
        creds = self.credentials.get("linkedin", {})
        if not creds.get("email"):
            return False

        await page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(4)

        try:
            # Wait for the form — increase timeout and try multiple selectors
            username_el = None
            for sel in ["#username", "input[name='session_key']", "input[autocomplete='username']", "input[type='email']"]:
                try:
                    await page.wait_for_selector(sel, timeout=8000)
                    username_el = await page.query_selector(sel)
                    if username_el:
                        break
                except Exception:
                    pass

            if not username_el:
                # If we can't find the login form, maybe we're already logged in
                current_url = page.url
                if "feed" in current_url or "mynetwork" in current_url:
                    logger.info("LinkedIn: already logged in")
                    return True
                logger.warning(f"LinkedIn: login form not found at {current_url}")
                return False

            await username_el.fill(creds["email"])
            await asyncio.sleep(0.8)

            password_el = None
            for sel in ["#password", "input[name='session_password']", "input[type='password']"]:
                password_el = await page.query_selector(sel)
                if password_el:
                    break
            if password_el:
                await password_el.fill(creds["password"])
            await asyncio.sleep(0.8)
            await page.click("button[type='submit']")

            # Don't use networkidle — LinkedIn never fully settles.
            # Wait up to 15s for URL to change away from /login
            try:
                await page.wait_for_url(
                    lambda url: "/login" not in url and "linkedin.com" in url,
                    timeout=15000,
                )
            except Exception:
                pass  # URL may not have changed yet — check below

            await asyncio.sleep(3)

            # Handle 2FA / verification challenge
            if "checkpoint" in page.url or "challenge" in page.url or "verification" in page.url:
                logger.warning("LinkedIn requires 2FA/verification — check your email/phone. Waiting 90s...")
                for _ in range(18):
                    await asyncio.sleep(5)
                    if "feed" in page.url or "/jobs" in page.url or "/in/" in page.url:
                        break

            logged_in = await self.browser.is_logged_in(page, "linkedin") or "feed" in page.url or "/jobs" in page.url
            if logged_in:
                logger.info("LinkedIn: logged in successfully")
            return logged_in

        except Exception as e:
            logger.error(f"LinkedIn login error: {e}")
            return False

    async def _login_indeed(self, page: Page) -> bool:
        creds = self.credentials.get("indeed", {})
        if not creds.get("email"):
            return False

        # Indeed's login URL
        await page.goto(
            "https://secure.indeed.com/auth?hl=en_US&co=US&continue=https%3A%2F%2Fwww.indeed.com%2F&service=my&from=gnav-homepage",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        # Indeed renders the form via JS — wait longer
        await asyncio.sleep(5)

        try:
            # Step 1 — enter email. Indeed uses dynamically-generated IDs, try multiple selectors.
            email_input = None
            selectors_to_try = [
                "input[type='email']",
                "input[name='__email']",
                "input[autocomplete='email']",
                "input[autocomplete='username']",
                "input[type='text']",
            ]
            # Wait up to 10s for any input to appear
            for _ in range(10):
                for sel in selectors_to_try:
                    try:
                        el = await page.query_selector(sel)
                        if el and await el.is_visible():
                            email_input = el
                            break
                    except Exception:
                        pass
                if email_input:
                    break
                await asyncio.sleep(1)

            if not email_input:
                logger.warning("Indeed: email input not found after waiting")
                # Take a screenshot to debug
                try:
                    await page.screenshot(path="./screenshots/indeed_login_debug.png")
                    logger.warning("Indeed: debug screenshot saved to screenshots/indeed_login_debug.png")
                except Exception:
                    pass
                return False

            await email_input.click()
            await asyncio.sleep(0.3)
            await email_input.fill(creds["email"])
            await asyncio.sleep(0.8)

            # Click Continue / Sign in
            submitted = False
            for btn_sel in ["button[type='submit']", "button:has-text('Continue')", "button:has-text('Sign in')"]:
                btn = await page.query_selector(btn_sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    submitted = True
                    break

            if not submitted:
                logger.warning("Indeed: no submit button found after email")
                return False

            await asyncio.sleep(3)

            # Step 2 — enter password (appears on next screen)
            password_input = None
            for sel in ["input[type='password']", "input[name='__password']", "input[autocomplete='current-password']"]:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    password_input = el
                    break

            if password_input:
                await password_input.click()
                await asyncio.sleep(0.3)
                await password_input.fill(creds["password"])
                await asyncio.sleep(0.8)

                for btn_sel in ["button[type='submit']", "button:has-text('Sign in')", "button:has-text('Continue')"]:
                    btn = await page.query_selector(btn_sel)
                    if btn and await btn.is_visible():
                        await btn.click()
                        break

                await asyncio.sleep(4)
            else:
                # Indeed may send a magic link instead of showing password
                logger.warning("Indeed: no password field — check email for magic link")

            logged_in = "indeed.com" in page.url and "auth" not in page.url and "login" not in page.url
            if logged_in:
                logger.info("Indeed: logged in successfully")
            return logged_in

        except Exception as e:
            logger.error(f"Indeed login error: {e}")
            return False

    async def _login_dice(self, page: Page) -> bool:
        creds = self.credentials.get("dice", {})
        if not creds.get("email"):
            return False

        await page.goto("https://www.dice.com/dashboard/login", wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(2)

        try:
            await page.fill("input[name='email'], input[type='email']", creds["email"])
            await asyncio.sleep(0.5)
            continue_btn = await page.query_selector("button[type='submit']")
            if continue_btn:
                await continue_btn.click()
                await asyncio.sleep(1.5)

            password_input = await page.query_selector("input[type='password']")
            if password_input:
                await password_input.fill(creds["password"])
                await asyncio.sleep(0.5)

            signin_btn = await page.query_selector("button[type='submit']")
            if signin_btn:
                await signin_btn.click()
                await asyncio.sleep(4)

            return "dashboard" in page.url or ("dice.com" in page.url and "login" not in page.url)

        except Exception as e:
            logger.error(f"Dice login error: {e}")
            return False

    async def _login_glassdoor(self, page: Page) -> bool:
        creds = self.credentials.get("glassdoor", {})
        if not creds.get("email"):
            return False

        await page.goto("https://www.glassdoor.com/profile/login_input.htm", wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(2)

        try:
            email_input = await page.query_selector("#userEmail, input[name='username']")
            if email_input:
                await email_input.fill(creds["email"])

            password_input = await page.query_selector("#userPassword, input[type='password']")
            if password_input:
                await password_input.fill(creds["password"])

            submit_btn = await page.query_selector("button[type='submit'], #signInBtn")
            if submit_btn:
                await submit_btn.click()
                await asyncio.sleep(4)

            return "glassdoor.com" in page.url and "login" not in page.url

        except Exception as e:
            logger.error(f"Glassdoor login error: {e}")
            return False

    async def create_account(self, page: Page, platform: str, email: str, password: str) -> bool:
        """
        Create a new account on a job platform.
        Uses the provided email and password.
        """
        creators = {
            "indeed": self._create_indeed_account,
            "dice": self._create_dice_account,
        }
        creator = creators.get(platform)
        if not creator:
            logger.warning(f"Account creation not implemented for {platform}")
            return False

        try:
            return await creator(page, email, password)
        except Exception as e:
            logger.error(f"Account creation on {platform} failed: {e}")
            return False

    async def _create_indeed_account(self, page: Page, email: str, password: str) -> bool:
        await page.goto("https://secure.indeed.com/auth?hl=en_US&co=US&continue=/&service=my&from=gnav-homepage", wait_until="domcontentloaded")
        await asyncio.sleep(2)

        create_btn = await page.query_selector("a:has-text('Create an account'), button:has-text('Create')")
        if create_btn:
            await create_btn.click()
            await asyncio.sleep(2)

        email_input = await page.query_selector("input[type='email']")
        if email_input:
            await email_input.fill(email)
            await asyncio.sleep(0.5)

        submit = await page.query_selector("button[type='submit']")
        if submit:
            await submit.click()
            await asyncio.sleep(2)

        # May need email verification
        logger.info("Indeed: check your email for verification link")
        return True

    async def _create_dice_account(self, page: Page, email: str, password: str) -> bool:
        await page.goto("https://www.dice.com/dashboard/register", wait_until="domcontentloaded")
        await asyncio.sleep(2)

        email_input = await page.query_selector("input[name='email'], input[type='email']")
        if email_input:
            await email_input.fill(email)

        password_input = await page.query_selector("input[type='password']")
        if password_input:
            await password_input.fill(password)

        submit = await page.query_selector("button[type='submit']")
        if submit:
            await submit.click()
            await asyncio.sleep(3)

        logger.info("Dice: account creation submitted")
        return True

    def get_verification_code_from_email(self, imap_server: str, email_addr: str, password: str, sender_filter: str) -> Optional[str]:
        """
        Connect to IMAP and extract a verification code from the latest email
        matching sender_filter.
        """
        try:
            mail = imaplib.IMAP4_SSL(imap_server)
            mail.login(email_addr, password)
            mail.select("inbox")

            _, messages = mail.search(None, f'(FROM "{sender_filter}" UNSEEN)')
            if not messages[0]:
                return None

            latest_id = messages[0].split()[-1]
            _, data = mail.fetch(latest_id, "(RFC822)")
            msg = email_lib.message_from_bytes(data[0][1])

            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode()
                        break
            else:
                body = msg.get_payload(decode=True).decode()

            # Extract 6-digit code
            codes = re.findall(r"\b\d{6}\b", body)
            if codes:
                return codes[0]

            # Extract link-based verification
            links = re.findall(r'https?://[^\s<>"]+verify[^\s<>"]*', body)
            if links:
                return links[0]

            mail.logout()
        except Exception as e:
            logger.error(f"IMAP email check failed: {e}")

        return None
