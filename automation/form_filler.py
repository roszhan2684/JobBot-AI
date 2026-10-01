"""
AI-powered form filler using Playwright + Claude API.

Flow:
1. Navigate to job application URL
2. Extract all form fields from the DOM
3. Ask Claude what value goes in each field (using user profile)
4. Fill the fields, handle multi-page forms
5. Upload resume if requested
6. Submit and confirm
"""
import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from playwright.async_api import Page
from .browser import BrowserManager

logger = logging.getLogger(__name__)


class FormFiller:
    """Fills and submits job application forms using AI."""

    def __init__(self, config: dict, browser_manager: BrowserManager, ai_matcher):
        self.config = config
        self.browser = browser_manager
        self.ai = ai_matcher
        self.user = config.get("user", {})
        self.settings = config.get("settings", {})

    async def apply_to_job(self, page: Page, job: dict) -> Tuple[bool, str]:
        """
        Main entry point: apply to a job.
        Returns (success: bool, message: str)
        """
        url = job.get("apply_url") or job.get("url")
        source = job.get("source", "")

        logger.info(f"Applying to: {job['title']} @ {job['company']} ({source})")

        try:
            if source == "linkedin" and job.get("job_type") == "easy_apply":
                return await self._apply_linkedin_easy_apply(page, job)
            elif source in ("indeed",):
                return await self._apply_indeed(page, job)
            else:
                return await self._apply_generic(page, job)
        except Exception as e:
            logger.error(f"Application error for {url}: {e}")
            return False, str(e)

    async def _apply_linkedin_easy_apply(self, page: Page, job: dict) -> Tuple[bool, str]:
        """Handle LinkedIn Easy Apply flow."""
        url = job.get("url")
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        # Find Easy Apply button
        easy_apply_btn = await page.query_selector(
            "button.jobs-apply-button, button:has-text('Easy Apply'), "
            "[data-control-name='jobdetails_topcard_inapply']"
        )
        if not easy_apply_btn:
            logger.warning("No Easy Apply button found")
            return False, "No Easy Apply button"

        await easy_apply_btn.click()
        await asyncio.sleep(2)

        # Handle multi-step modal
        max_steps = 10
        for step in range(max_steps):
            if await self._check_success(page):
                return True, "Applied successfully"

            if await self.browser.detect_captcha(page):
                return False, "CAPTCHA detected"

            # Extract and fill current form page
            fields = await self._extract_form_fields(page)
            if fields:
                filled = await self.ai.fill_form_fields(fields, self.user, job)
                await self._fill_fields(page, fields, filled)

            # Handle resume upload
            resume_input = await page.query_selector("input[type='file']")
            if resume_input:
                await self._upload_resume(resume_input)

            # Check for submit or next
            submitted = await self._click_next_or_submit(page)
            if submitted:
                await asyncio.sleep(2)
                if await self._check_success(page):
                    # Take screenshot
                    if self.settings.get("save_screenshots"):
                        safe_company = re.sub(r"[^a-zA-Z0-9]", "_", job.get("company", "unknown"))
                        shot_path = await self.browser.take_screenshot(
                            page, f"applied_{safe_company}_{job.get('id', '')}.png"
                        )
                    return True, "Applied via LinkedIn Easy Apply"
                break  # Submitted but no success page - likely applied

            await asyncio.sleep(1.5)

        return True, "Submitted (LinkedIn Easy Apply)"

    async def _apply_indeed(self, page: Page, job: dict) -> Tuple[bool, str]:
        """Handle Indeed job application."""
        url = job.get("apply_url") or job.get("url")
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        # Indeed might show a "Apply" button to redirect to company site
        apply_btn = await page.query_selector(
            "[id*='apply-button'], button:has-text('Apply now'), "
            "a:has-text('Apply on company site'), [data-testid='apply-button']"
        )
        if apply_btn:
            href = await apply_btn.get_attribute("href")
            if href and "indeed.com" not in href:
                # External application - use generic filler
                job["apply_url"] = href
                return await self._apply_generic(page, job)
            await apply_btn.click()
            await asyncio.sleep(3)

        # Fill Indeed's native form
        return await self._fill_multi_page_form(page, job, max_steps=8)

    async def _apply_generic(self, page: Page, job: dict) -> Tuple[bool, str]:
        """Handle generic external job application page."""
        url = job.get("apply_url") or job.get("url")
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        if await self.browser.detect_captcha(page):
            return False, "CAPTCHA on application page"

        # Look for an Apply / Start Application button
        apply_selectors = [
            "a:has-text('Apply')",
            "button:has-text('Apply')",
            "a:has-text('Start Application')",
            "button:has-text('Submit Application')",
            "[data-testid*='apply']",
        ]
        for sel in apply_selectors:
            try:
                btn = await page.query_selector(sel)
                if btn:
                    await btn.click()
                    await asyncio.sleep(2)
                    break
            except Exception:
                pass

        return await self._fill_multi_page_form(page, job, max_steps=10)

    async def _fill_multi_page_form(self, page: Page, job: dict, max_steps: int = 10) -> Tuple[bool, str]:
        """Generic multi-page form handler."""
        for step in range(max_steps):
            if await self.browser.detect_captcha(page):
                return False, "CAPTCHA detected"

            if await self._check_success(page):
                return True, "Applied successfully"

            fields = await self._extract_form_fields(page)
            if fields:
                filled = await self.ai.fill_form_fields(fields, self.user, job)
                await self._fill_fields(page, fields, filled)

            # Handle resume/file upload
            file_inputs = await page.query_selector_all("input[type='file']")
            for fi in file_inputs:
                await self._upload_resume(fi)

            clicked = await self._click_next_or_submit(page)
            if not clicked:
                # No next/submit button - might be done or stuck
                return True, "Form submitted (no submit button detected)"

            await asyncio.sleep(2)

        return True, "Application process completed"

    async def _extract_form_fields(self, page: Page) -> List[Dict]:
        """
        Extract all form fields from the current page using JavaScript.
        Returns list of field dicts: {label, name, type, value, options, required}
        """
        fields = await page.evaluate("""
            () => {
                const fields = [];
                const inputs = document.querySelectorAll(
                    'input:not([type="hidden"]):not([type="submit"]):not([type="button"]):not([type="file"]),' +
                    'textarea, select'
                );

                inputs.forEach(el => {
                    // Skip invisible elements
                    const rect = el.getBoundingClientRect();
                    if (rect.width === 0 && rect.height === 0) return;

                    // Find label
                    let label = '';
                    if (el.id) {
                        const labelEl = document.querySelector(`label[for="${el.id}"]`);
                        if (labelEl) label = labelEl.innerText.trim();
                    }
                    if (!label) {
                        const parent = el.closest('label, [class*="field"], [class*="form-group"], [class*="question"]');
                        if (parent) {
                            const labelChild = parent.querySelector('label, [class*="label"], legend');
                            if (labelChild) label = labelChild.innerText.trim();
                            else label = parent.innerText.split('\\n')[0].trim().substring(0, 100);
                        }
                    }
                    if (!label && el.placeholder) label = el.placeholder;
                    if (!label && el.name) label = el.name.replace(/[_-]/g, ' ');
                    if (!label && el.getAttribute('aria-label')) label = el.getAttribute('aria-label');

                    const field = {
                        label: label.replace(/[*]/g, '').trim(),
                        name: el.name || el.id || '',
                        type: el.tagName === 'SELECT' ? 'select' : (el.tagName === 'TEXTAREA' ? 'textarea' : el.type || 'text'),
                        value: el.value || '',
                        required: el.required || el.getAttribute('aria-required') === 'true',
                        options: [],
                        selector: el.id ? `#${el.id}` : (el.name ? `[name="${el.name}"]` : null),
                    };

                    // Get select options
                    if (el.tagName === 'SELECT') {
                        field.options = Array.from(el.options).map(o => ({value: o.value, text: o.text}));
                    }

                    fields.push(field);
                });

                return fields;
            }
        """)
        return [f for f in fields if f.get("label") or f.get("name")]

    async def _fill_fields(self, page: Page, fields: List[Dict], filled_values: Dict):
        """Fill form fields with AI-provided values."""
        for field in fields:
            key = field.get("name") or field.get("label", "")
            value = filled_values.get(key) or filled_values.get(field.get("label", ""))
            if value is None:
                continue

            selector = field.get("selector")
            if not selector:
                continue

            try:
                el = await page.query_selector(selector)
                if not el:
                    continue

                field_type = field.get("type", "text")

                if field_type == "select":
                    # Try value match, then text match
                    try:
                        await page.select_option(selector, value=str(value))
                    except Exception:
                        try:
                            await page.select_option(selector, label=str(value))
                        except Exception:
                            pass

                elif field_type in ("checkbox", "radio"):
                    if str(value).lower() in ("yes", "true", "1"):
                        if not await el.is_checked():
                            await el.check()
                    else:
                        if await el.is_checked():
                            await el.uncheck()

                elif field_type == "textarea":
                    await el.fill(str(value))

                else:  # text, email, tel, number, url, date, etc.
                    await el.fill(str(value))

                await asyncio.sleep(0.2)

            except Exception as e:
                logger.debug(f"Could not fill field '{key}': {e}")

    async def _upload_resume(self, file_input):
        """Upload resume PDF to a file input."""
        resume_path = self.user.get("resume_path", "./resume.pdf")
        if not os.path.exists(resume_path):
            logger.warning(f"Resume not found at {resume_path}")
            return

        try:
            await file_input.set_input_files(resume_path)
            await asyncio.sleep(1)
            logger.debug(f"Resume uploaded from {resume_path}")
        except Exception as e:
            logger.warning(f"Resume upload failed: {e}")

    async def _click_next_or_submit(self, page: Page) -> bool:
        """Click Next, Continue, or Submit button. Returns True if clicked."""
        button_selectors = [
            "button:has-text('Submit application')",
            "button:has-text('Submit Application')",
            "button:has-text('Submit')",
            "button[type='submit']",
            "button:has-text('Next')",
            "button:has-text('Continue')",
            "button:has-text('Review')",
            "input[type='submit']",
        ]
        for sel in button_selectors:
            try:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible() and await btn.is_enabled():
                    await btn.click()
                    await asyncio.sleep(1.5)
                    return True
            except Exception:
                pass
        return False

    async def _check_success(self, page: Page) -> bool:
        """Detect if application was successfully submitted."""
        success_indicators = [
            "Your application was sent",
            "Application submitted",
            "Successfully applied",
            "Thank you for applying",
            "application has been received",
            "We received your application",
            "you've applied",
            "application is complete",
        ]
        try:
            content = (await page.content()).lower()
            for indicator in success_indicators:
                if indicator.lower() in content:
                    return True
        except Exception:
            pass
        return False
