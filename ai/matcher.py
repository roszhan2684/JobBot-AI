"""
AI job scorer and form filler using Claude API.

Two jobs:
1. score_job()      — given a job posting, score 0-100 fit against user profile
2. fill_form_fields() — given form fields + user profile, return values for each field
3. generate_cover_letter() — write a tailored cover letter for a specific job
"""
import json
import logging
import os
from typing import Dict, List, Optional

import anthropic

logger = logging.getLogger(__name__)

# Use the most capable model for quality matching
MODEL = "claude-opus-4-6"


class AIMatcher:
    def __init__(self, config: dict):
        self.config = config
        self.user = config.get("user", {})
        self.prefs = config.get("job_preferences", {})
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not set in environment")
        self.client = anthropic.Anthropic(api_key=api_key)
        self._resume = self.user.get("resume_text", "")
        self._domain = self.prefs.get("domain", "Software Engineering")
        self._keywords = self.prefs.get("keywords", [])
        # cover_letter_template may live under user: or at root level
        self._cover_template = (
            self.user.get("cover_letter_template")
            or config.get("cover_letter_template", "")
        )

    async def score_job(self, job: dict) -> tuple[int, str]:
        """
        Score a job listing 0-100 based on fit with user profile.
        Returns (score, analysis_text).
        """
        title = job.get("title", "")
        company = job.get("company", "")
        description = (job.get("description", "") or "")[:3000]
        location = job.get("location", "")
        salary = job.get("salary", "")

        prompt = f"""You are a job matching assistant. Score this job listing from 0-100 based on fit with the candidate's profile.

CANDIDATE PROFILE:
{self._resume[:2000]}

TARGET DOMAIN: {self._domain}
TARGET KEYWORDS: {', '.join(self._keywords)}

JOB LISTING:
Title: {title}
Company: {company}
Location: {location}
Salary: {salary}
Description:
{description}

Scoring criteria:
- Title match with candidate's experience (0-30 pts)
- Skills/tech stack match with keywords (0-30 pts)
- Experience level match (0-20 pts)
- Location/remote compatibility (0-10 pts)
- Company quality / growth stage (0-10 pts)

Respond ONLY with valid JSON:
{{
  "score": <integer 0-100>,
  "match_reasons": ["reason1", "reason2"],
  "concerns": ["concern1"],
  "one_line_summary": "brief summary of fit"
}}"""

        try:
            response = self.client.messages.create(
                model=MODEL,
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}]
            )
            text = response.content[0].text.strip()
            # Extract JSON even if there's surrounding text
            json_match = text
            if "```" in text:
                json_match = text.split("```")[1].replace("json", "").strip()
            data = json.loads(json_match)
            score = max(0, min(100, int(data.get("score", 0))))
            summary = data.get("one_line_summary", "")
            reasons = data.get("match_reasons", [])
            concerns = data.get("concerns", [])
            analysis = f"{summary}\n✓ {chr(10).join(reasons)}"
            if concerns:
                analysis += f"\n⚠ {chr(10).join(concerns)}"
            return score, analysis
        except anthropic.BadRequestError as e:
            if "credit" in str(e).lower() or "balance" in str(e).lower():
                logger.warning("Anthropic API: out of credits — using keyword fallback scorer")
                return self._keyword_score(job), "Keyword-based score (API credits exhausted)"
            logger.error(f"AI scoring error: {e}")
            return self._keyword_score(job), f"Fallback score (API error)"
        except Exception as e:
            logger.error(f"AI scoring error: {e}")
            return self._keyword_score(job), f"Fallback score: {e}"

    def _keyword_score(self, job: dict) -> int:
        """
        Fast keyword-based job scorer (no API needed).
        Used as fallback when Anthropic API is unavailable.
        Returns score 0-100.

        Scoring breakdown:
          Title exact match   → 45 pts
          Title partial match → 25 pts
          Skill keywords      → up to 30 pts (3 pts each, max 10)
          Level match         → 15 pts
          Location match      → 10 pts
        A job that matches a target title + 1 skill + right level = 45+3+15 = 63 → rounds to qualifying
        """
        title   = (job.get("title", "")       or "").lower()
        desc    = (job.get("description", "")  or "").lower()
        combined = f"{title} {desc}"

        score = 0

        # ── Title match (up to 45 pts) ───────────────────────────────────────
        target_titles = [t.lower() for t in self.prefs.get("titles", [])]
        title_scored = False
        for tt in target_titles:
            words = tt.split()
            if all(w in title for w in words):
                score += 45       # exact phrase match
                title_scored = True
                break
        if not title_scored:
            # partial: at least one meaningful word matches
            core_words = ["engineer", "developer", "frontend", "backend",
                          "fullstack", "full stack", "ios", "mobile", "software",
                          "design", "product", "ui", "intern"]
            if any(w in title for w in core_words):
                score += 25

        # ── Skill/keyword match (up to 30 pts) ───────────────────────────────
        kws = [k.lower() for k in self._keywords]
        matched = sum(1 for kw in kws if kw in combined)
        score += min(30, matched * 3)

        # ── Seniority/level match (15 pts) ───────────────────────────────────
        levels = self.prefs.get("experience_levels", [])
        level_keywords = {
            "junior": ["junior", "new grad", "entry level", "entry-level", "intern",
                       "associate", "0-1", "0-2", "early career"],
            "mid":    ["mid", "intermediate", "2-4", "2-5", "3-5", "ii ", " ii",
                       "mid-level", "mid level"],
            "senior": ["senior", "sr.", "sr ", "lead", "staff", "principal", "5+",
                       "7+", "iii ", " iii"],
        }
        for level in levels:
            for kw in level_keywords.get(level, []):
                if kw in combined:
                    score += 15
                    break
            else:
                continue
            break
        # If no level signal at all in the title, don't penalise (many postings omit it)
        if not any(
            kw in combined
            for lkws in level_keywords.values()
            for kw in lkws
        ):
            score += 10   # neutral — assume acceptable level

        # ── Location match (10 pts) ───────────────────────────────────────────
        locations = [loc.lower() for loc in self.prefs.get("locations", [])]
        job_loc = (job.get("location", "") or "").lower()
        if any(loc in job_loc or job_loc in loc for loc in locations):
            score += 10
        elif "remote" in job_loc or "anywhere" in job_loc:
            score += 8

        return min(100, score)

    async def fill_form_fields(self, fields: List[Dict], user: dict, job: dict) -> Dict[str, str]:
        """
        Given a list of form field dicts and user profile, return a dict
        of {field_name_or_label: value_to_fill}.
        """
        # Build a simplified field list for the prompt
        field_summaries = []
        for f in fields:
            summary = {
                "label": f.get("label", ""),
                "name": f.get("name", ""),
                "type": f.get("type", "text"),
                "required": f.get("required", False),
            }
            if f.get("options"):
                summary["options"] = [o["text"] for o in f["options"][:10]]
            field_summaries.append(summary)

        prompt = f"""You are filling out a job application form. Use the candidate's profile to fill every field.

CANDIDATE PROFILE:
Name: {user.get('first_name', '')} {user.get('last_name', '')}
Email: {user.get('email', '')}
Phone: {user.get('phone', '')}
Location: {user.get('location', '')}
LinkedIn: {user.get('linkedin_url', '')}
GitHub: {user.get('github_url', '')}
Years Experience: {user.get('years_experience', '5')}
Work Authorization: {user.get('work_authorization', 'Yes')}
Requires Sponsorship: {user.get('requires_sponsorship', 'No')}
Desired Salary: {user.get('desired_salary', '120000')}
Willing to Relocate: {user.get('willing_to_relocate', 'Yes')}
Start Date: {user.get('available_start_date', 'Immediately')}

JOB: {job.get('title', '')} at {job.get('company', '')}

FORM FIELDS:
{json.dumps(field_summaries, indent=2)}

Instructions:
- For SELECT fields, pick the closest matching option from the provided list
- For salary/compensation fields, use the candidate's desired salary
- For "why do you want to work here" or essay questions, write a brief 2-3 sentence answer
- For checkbox fields (yes/no), answer based on the candidate profile
- For fields you cannot determine, use empty string ""
- Skip fields with type "file"

Respond ONLY with valid JSON mapping each field's "name" (or "label" if name is empty) to its value:
{{"field_name_or_label": "value", ...}}"""

        try:
            response = self.client.messages.create(
                model=MODEL,
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}]
            )
            text = response.content[0].text.strip()
            if "```" in text:
                text = text.split("```")[1].replace("json", "").strip()
            return json.loads(text)
        except Exception as e:
            logger.warning(f"AI form fill unavailable ({e}) — using direct field mapping")
            return self._fallback_fill(fields, user)

    def _fallback_fill(self, fields: List[Dict], user: dict) -> Dict[str, str]:
        """Direct field mapping without AI, for common fields."""
        result = {}
        field_map = {
            "first name": user.get("first_name", ""),
            "last name": user.get("last_name", ""),
            "email": user.get("email", ""),
            "phone": user.get("phone", ""),
            "location": user.get("location", ""),
            "city": user.get("city", ""),
            "state": user.get("state", ""),
            "zip": user.get("zip_code", ""),
            "linkedin": user.get("linkedin_url", ""),
            "github": user.get("github_url", ""),
            "website": user.get("portfolio_url", ""),
            "salary": user.get("desired_salary", ""),
            "years": user.get("years_experience", "5"),
        }
        for field in fields:
            label_lower = (field.get("label", "") or "").lower()
            name_lower = (field.get("name", "") or "").lower()
            key = field.get("name") or field.get("label", "")
            for pattern, value in field_map.items():
                if pattern in label_lower or pattern in name_lower:
                    result[key] = value
                    break
        return result

    async def generate_cover_letter(self, job: dict) -> str:
        """Generate a tailored cover letter for this specific job."""
        template = self._cover_template
        description = (job.get("description", "") or "")[:2000]

        prompt = f"""Write a concise, professional cover letter for this job application.

CANDIDATE:
{self._resume[:1500]}

JOB:
Title: {job.get('title', '')}
Company: {job.get('company', '')}
Description: {description}

TEMPLATE TO FOLLOW:
{template}

Requirements:
- Maximum 3 short paragraphs
- Be specific about the company and role
- Highlight 2-3 most relevant skills/experiences
- Professional but conversational tone
- Do NOT use generic phrases like "I am writing to express my interest"
- Replace {{job_title}}, {{company}}, {{domain}}, {{custom_paragraph}} placeholders

Write ONLY the cover letter text, no subject line or date."""

        try:
            response = self.client.messages.create(
                model=MODEL,
                max_tokens=600,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.content[0].text.strip()
        except Exception as e:
            logger.warning(f"Cover letter generation unavailable: {e}")
            # Return a basic template-filled cover letter as fallback
            return template.replace("{job_title}", job.get("title", "this role")) \
                           .replace("{company}", job.get("company", "your company")) \
                           .replace("{domain}", self._domain) \
                           .replace("{custom_paragraph}", "I am eager to bring my skills to your team.")

    async def should_skip_job(self, job: dict) -> tuple[bool, str]:
        """Quick check if a job is obviously not a match (saves API calls on scoring)."""
        title = (job.get("title", "") or "").lower()
        desc = (job.get("description", "") or "").lower()

        # Hard excludes from config
        for kw in self.prefs.get("exclude_keywords", []):
            if kw.lower() in title or kw.lower() in desc:
                return True, f"Excluded keyword: {kw}"

        # Title must contain at least one relevant keyword
        kws = [k.lower() for k in self._keywords + self.prefs.get("titles", [])]
        if not any(kw in title for kw in kws):
            return True, "Title doesn't match any target keywords"

        return False, ""
