"""
Excel exporter for applied jobs.
Columns: Serial No. | Company | Job Title | Source | Location | Salary | Date Applied | Link
Auto-saves to applied_jobs.xlsx after every apply cycle.
"""
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict

import openpyxl
from openpyxl.styles import (
    Font, PatternFill, Alignment, Border, Side, GradientFill
)
from openpyxl.utils import get_column_letter

from . import db as database

logger = logging.getLogger(__name__)

EXCEL_PATH        = "applied_jobs.xlsx"
ALL_JOBS_EXCEL    = "all_scraped_jobs.xlsx"

# Applied jobs columns
COLUMNS = [
    ("No.",          "_serial",      6),
    ("Company",      "company",      22),
    ("Job Title",    "title",        35),
    ("Source",       "source",       14),
    ("Location",     "location",     22),
    ("Salary",       "salary",       18),
    ("Date Applied", "applied_date", 16),
    ("Link",         "url",          50),
    ("AI Score",     "ai_score",     10),
    ("Notes",        "notes",        30),
]

# All-jobs columns (for manual review)
ALL_JOBS_COLUMNS = [
    ("No.",         "_serial",    6),
    ("Company",     "company",    22),
    ("Job Title",   "title",      35),
    ("Source",      "source",     14),
    ("Location",    "location",   22),
    ("Salary",      "salary",     18),
    ("AI Score",    "ai_score",   10),
    ("Status",      "status",     12),
    ("Apply Link",  "url",        55),
    ("Posted",      "posted_date",14),
    ("Scraped",     "_scraped",   14),
]

# Status badge colours (fill colour per status)
STATUS_COLOURS = {
    "applied":  "D1FAE5",   # green
    "pending":  "FEF3C7",   # yellow
    "failed":   "FEE2E2",   # red
    "skipped":  "DBEAFE",   # blue
    "captcha":  "EDE9FE",   # purple
    "applying": "E0F2FE",   # sky
}

# Colour scheme
HEADER_BG   = "4B3BCF"   # purple
HEADER_FG   = "FFFFFF"
APPLIED_BG  = "D1FAE5"   # light green
ALT_ROW_BG  = "F8F7FF"   # very light purple
WHITE       = "FFFFFF"
BORDER_CLR  = "C4B5FD"


def _thin_border():
    side = Side(style="thin", color=BORDER_CLR)
    return Border(left=side, right=side, top=side, bottom=side)


async def export_applied_jobs(path: str = EXCEL_PATH) -> str:
    """
    Fetch all applied jobs from the database and write / update the Excel file.
    Returns the file path on success.
    """
    jobs = await database.get_all_jobs(status="applied", limit=10000)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Applied Jobs"

    # ── Header row ────────────────────────────────────────────────────────────
    header_font   = Font(name="Calibri", bold=True, color=HEADER_FG, size=11)
    header_fill   = PatternFill("solid", fgColor=HEADER_BG)
    header_align  = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for col_idx, (header, _, width) in enumerate(COLUMNS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font   = header_font
        cell.fill   = header_fill
        cell.alignment = header_align
        cell.border = _thin_border()
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    ws.row_dimensions[1].height = 22
    ws.freeze_panes = "A2"  # freeze header

    # ── Data rows ─────────────────────────────────────────────────────────────
    for row_idx, job in enumerate(jobs, start=1):
        row_num   = row_idx + 1  # Excel row (1-indexed, +1 for header)
        is_even   = row_idx % 2 == 0
        row_bg    = ALT_ROW_BG if is_even else WHITE
        row_fill  = PatternFill("solid", fgColor=row_bg)
        data_font = Font(name="Calibri", size=10)
        data_align = Alignment(vertical="center", wrap_text=False)

        for col_idx, (_, field, _) in enumerate(COLUMNS, start=1):
            if field == "_serial":
                value = row_idx
            elif field == "applied_date":
                raw = job.get("applied_date", "")
                value = raw[:10] if raw else ""
            elif field == "ai_score":
                value = job.get("ai_score") or ""
            elif field == "url":
                value = job.get("url", "")
            else:
                value = job.get(field, "") or ""

            cell = ws.cell(row=row_num, column=col_idx, value=value)
            cell.font    = data_font
            cell.fill    = row_fill
            cell.border  = _thin_border()
            cell.alignment = data_align

            # Make URL a clickable hyperlink
            if field == "url" and value:
                cell.hyperlink = value
                cell.font = Font(name="Calibri", size=10, color="3B2FC9", underline="single")
                cell.alignment = Alignment(vertical="center")

        ws.row_dimensions[row_num].height = 16

    # ── Summary sheet ─────────────────────────────────────────────────────────
    ws2 = wb.create_sheet("Summary")
    stats = await database.get_stats()

    summary_data = [
        ("Total Scraped",    stats.get("total", 0)),
        ("Applied",          stats.get("applied", 0)),
        ("Applied Today",    stats.get("applied_today", 0)),
        ("Pending",          stats.get("pending", 0)),
        ("Failed",           stats.get("failed", 0)),
        ("Skipped",          stats.get("skipped", 0)),
        ("Avg AI Score",     round(stats.get("avg_score") or 0, 1)),
        ("Export Date",      datetime.now().strftime("%Y-%m-%d %H:%M")),
    ]

    ws2["A1"] = "JobBot AI — Summary"
    ws2["A1"].font = Font(name="Calibri", bold=True, size=14, color=HEADER_BG)
    ws2.column_dimensions["A"].width = 20
    ws2.column_dimensions["B"].width = 18

    for i, (label, val) in enumerate(summary_data, start=3):
        ws2.cell(row=i, column=1, value=label).font = Font(name="Calibri", bold=True, size=11)
        ws2.cell(row=i, column=2, value=val).font   = Font(name="Calibri", size=11)

    # Source breakdown
    ws2.cell(row=3 + len(summary_data) + 2, column=1, value="By Source").font = Font(bold=True, size=11)
    for j, src in enumerate(stats.get("sources", []), start=3 + len(summary_data) + 3):
        ws2.cell(row=j, column=1, value=src["source"].title())
        ws2.cell(row=j, column=2, value=f"{src['applied']} applied / {src['cnt']} scraped")

    # ── Save ──────────────────────────────────────────────────────────────────
    wb.save(path)
    logger.info(f"Excel exported: {path} ({len(jobs)} applied jobs)")
    return path


async def export_all_scraped_jobs(path: str = ALL_JOBS_EXCEL) -> str:
    """
    Export every scraped job (all statuses) to Excel for manual review.
    Each row is colour-coded by status. Apply links are clickable.
    Returns the file path.
    """
    jobs = await database.get_all_jobs(limit=100000)  # get everything

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "All Scraped Jobs"

    header_font  = Font(name="Calibri", bold=True, color=HEADER_FG, size=11)
    header_fill  = PatternFill("solid", fgColor="1E293B")   # dark slate
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for col_idx, (header, _, width) in enumerate(ALL_JOBS_COLUMNS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font      = header_font
        cell.fill      = header_fill
        cell.alignment = header_align
        cell.border    = _thin_border()
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    ws.row_dimensions[1].height = 22
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(ALL_JOBS_COLUMNS))}1"

    data_font  = Font(name="Calibri", size=10)
    data_align = Alignment(vertical="center", wrap_text=False)

    for row_idx, job in enumerate(jobs, start=1):
        row_num = row_idx + 1
        status  = job.get("status", "pending")
        bg      = STATUS_COLOURS.get(status, "FFFFFF")
        row_fill = PatternFill("solid", fgColor=bg)

        for col_idx, (_, field, _) in enumerate(ALL_JOBS_COLUMNS, start=1):
            if field == "_serial":
                value = row_idx
            elif field == "_scraped":
                raw = job.get("scraped_date", "")
                value = raw[:10] if raw else ""
            elif field == "posted_date":
                raw = job.get("posted_date", "")
                value = raw[:10] if raw else ""
            elif field == "ai_score":
                value = job.get("ai_score") or ""
            elif field == "url":
                value = job.get("url", "") or ""
            else:
                value = job.get(field, "") or ""

            cell = ws.cell(row=row_num, column=col_idx, value=value)
            cell.fill      = row_fill
            cell.border    = _thin_border()
            cell.alignment = data_align

            if field == "url" and value:
                cell.hyperlink = value
                cell.font = Font(name="Calibri", size=10, color="1D4ED8", underline="single")
            else:
                cell.font = Font(
                    name="Calibri", size=10,
                    bold=(field == "ai_score" and isinstance(value, int) and value >= 65),
                    color="166534" if status == "applied" else "000000",
                )

        ws.row_dimensions[row_num].height = 15

    # ── Pending sheet: only unapplied jobs sorted by score ───────────────────
    ws_pending = wb.create_sheet("Apply Manually (Pending)")
    pending_jobs = [j for j in jobs if j.get("status") == "pending"]
    pending_jobs.sort(key=lambda j: j.get("ai_score") or 0, reverse=True)

    # Same headers
    for col_idx, (header, _, width) in enumerate(ALL_JOBS_COLUMNS, start=1):
        cell = ws_pending.cell(row=1, column=col_idx, value=header)
        cell.font      = Font(name="Calibri", bold=True, color=HEADER_FG, size=11)
        cell.fill      = PatternFill("solid", fgColor="0F4C81")
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border    = _thin_border()
        ws_pending.column_dimensions[get_column_letter(col_idx)].width = width

    ws_pending.row_dimensions[1].height = 22
    ws_pending.freeze_panes = "A2"
    ws_pending.auto_filter.ref = f"A1:{get_column_letter(len(ALL_JOBS_COLUMNS))}1"

    for row_idx, job in enumerate(pending_jobs, start=1):
        row_num  = row_idx + 1
        score    = job.get("ai_score") or 0
        # Gradient: green for high score, yellow for mid, white for low
        if score >= 70:
            bg = "D1FAE5"
        elif score >= 50:
            bg = "FEF3C7"
        else:
            bg = "FFFFFF"
        row_fill = PatternFill("solid", fgColor=bg)

        for col_idx, (_, field, _) in enumerate(ALL_JOBS_COLUMNS, start=1):
            if field == "_serial":
                value = row_idx
            elif field == "_scraped":
                raw = job.get("scraped_date", "")
                value = raw[:10] if raw else ""
            elif field == "posted_date":
                raw = job.get("posted_date", "")
                value = raw[:10] if raw else ""
            elif field == "ai_score":
                value = score or ""
            elif field == "url":
                value = job.get("url", "") or ""
            else:
                value = job.get(field, "") or ""

            cell = ws_pending.cell(row=row_num, column=col_idx, value=value)
            cell.fill      = row_fill
            cell.border    = _thin_border()
            cell.alignment = Alignment(vertical="center")

            if field == "url" and value:
                cell.hyperlink = value
                cell.font = Font(name="Calibri", size=10, color="1D4ED8", underline="single")
            else:
                cell.font = Font(name="Calibri", size=10, bold=(field == "ai_score"))

        ws_pending.row_dimensions[row_num].height = 15

    wb.save(path)
    logger.info(f"All-jobs Excel exported: {path} ({len(jobs)} total, {len(pending_jobs)} pending)")
    return path


async def auto_export():
    """Called after each scrape/apply cycle — updates both Excel files."""
    results = {}
    try:
        results["applied"] = await export_applied_jobs(EXCEL_PATH)
    except Exception as e:
        logger.error(f"Applied jobs Excel export failed: {e}")

    try:
        results["all_jobs"] = await export_all_scraped_jobs(ALL_JOBS_EXCEL)
    except Exception as e:
        logger.error(f"All-jobs Excel export failed: {e}")

    return results
