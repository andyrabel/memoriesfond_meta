"""
Phase 2 selection/rotation logic — decides which archived post (from
archive/posts.json) gets scheduled for which upcoming date, and feeds the
result into scheduler.py's `schedule` command via a queue file.

Rules:
  - A post with a post_day (always paired with post_months) is scheduled on
    the next upcoming calendar date matching that month and day. post_day is
    a day-of-month, a dash range ("1-25"), or a comma list/mix of either
    ("1-5,25") — the post becomes eligible on any day in that window and is
    scheduled (once) on the first such date the planning window reaches. If
    more than one active post matches that date, one is chosen at random.
  - Otherwise, one post is scheduled every CADENCE_DAYS (2) days, chosen at
    random from posts eligible for that date (post_day unset; post_months
    unset (evergreen) or matching that date's month).
  - Never more than one post per calendar day.
  - A post already used (recorded in planned_days.json) is never picked
    again.
"""
import json
import random
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import os

BASE_DIR = Path(__file__).parent
POSTS_FILE = BASE_DIR / "archive" / "posts.json"
SCHEDULED_DIR = BASE_DIR / "scheduled"
PLANNED_DAYS_FILE = SCHEDULED_DIR / "planned_days.json"

CADENCE_DAYS = 2
# Fixed reference date so the rotation lands on the same set of
# calendar dates regardless of when `plan` happens to run.
CADENCE_EPOCH = date(2024, 1, 1)

# Meta's docs claim scheduled_publish_time is accepted up to 75 days out,
# but real testing against this Page's token showed the actual enforced
# window is much shorter — a post 24 days out succeeded, one 30 days out
# was rejected with "(#100) The specified scheduled publish time is
# invalid.". This is a Standard-Access token (see CLAUDE.md); the 75-day
# figure likely assumes Advanced Access review. 24 is the last value
# confirmed to work, used here with no further safety margin subtracted
# since it's already an empirical floor, not a documented ceiling. Revisit
# upward if/when Advanced Access is granted for pages_manage_posts.
MAX_SCHEDULE_DAYS = 24

SCHEDULE_TIMEZONE = os.getenv("SCHEDULE_TIMEZONE", "UTC")
SCHEDULE_HOUR = int(os.getenv("SCHEDULE_HOUR", "12"))


def load_active_posts() -> list[dict]:
    if not POSTS_FILE.exists():
        return []
    posts = json.loads(POSTS_FILE.read_text(encoding="utf-8"))
    return [p for p in posts if p.get("status", "active") == "active"]


def load_planned_days() -> dict:
    if PLANNED_DAYS_FILE.exists():
        return json.loads(PLANNED_DAYS_FILE.read_text(encoding="utf-8"))
    return {}


def save_planned_days(planned: dict):
    SCHEDULED_DIR.mkdir(parents=True, exist_ok=True)
    PLANNED_DAYS_FILE.write_text(json.dumps(planned, indent=2, ensure_ascii=False), encoding="utf-8")


def _months_csv_to_set(csv: str | None) -> set[int]:
    if not csv:
        return set()
    return {int(m) for m in csv.split(",") if m.strip()}


def _days_csv_to_set(csv: str | None) -> set[int]:
    """Parses post_day: comma-separated days and/or dash ranges, e.g.
    "25" (single day), "1-25" (range), or "1-5,25" (mixed)."""
    if not csv:
        return set()
    days = set()
    for part in csv.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-", 1)
            days.update(range(int(start), int(end) + 1))
        else:
            days.add(int(part))
    return days


def _is_day_specific_match(post: dict, d: date) -> bool:
    if not post.get("post_day"):
        return False
    return d.month in _months_csv_to_set(post.get("post_months")) and d.day in _days_csv_to_set(post.get("post_day"))


def _is_general_eligible(post: dict, d: date) -> bool:
    if post.get("post_day"):
        return False  # reserved exclusively for its specific calendar date
    months = _months_csv_to_set(post.get("post_months"))
    return not months or d.month in months


def _is_cadence_day(d: date) -> bool:
    return (d - CADENCE_EPOCH).days % CADENCE_DAYS == 0


def _scheduled_datetime(d: date) -> datetime:
    return datetime.combine(d, time(hour=SCHEDULE_HOUR), tzinfo=ZoneInfo(SCHEDULE_TIMEZONE))


def _queue_item(post: dict, d: date) -> dict:
    return {
        "id": post["post_id"],
        "type": "photo",
        "scheduled_publish_time": _scheduled_datetime(d).isoformat(),
        "message": post.get("message", ""),
        "source_facts": {
            "original_message": post.get("message", ""),
            "created_time": post.get("created_time", ""),
            "permalink_url": post.get("permalink_url", ""),
        },
        "image_path": post["image_path"],
    }


def plan_queue(days: int = MAX_SCHEDULE_DAYS, start: date | None = None, persist: bool = True) -> list[dict]:
    """Plans queue items for [start, start + days). `start` defaults to
    tomorrow so a scheduled_publish_time is never already in the past.
    Returns the newly-planned queue items (not previously-planned ones)."""
    posts = load_active_posts()
    planned = load_planned_days()
    used_post_ids = set(planned.values())

    start = start or (date.today() + timedelta(days=1))
    new_items = []

    for offset in range(days):
        d = start + timedelta(days=offset)
        iso_day = d.isoformat()
        if iso_day in planned:
            continue  # this date was already decided in a previous `plan` run

        day_specific_pool = [p for p in posts if p["post_id"] not in used_post_ids and _is_day_specific_match(p, d)]
        if day_specific_pool:
            chosen = random.choice(day_specific_pool)
        elif _is_cadence_day(d):
            general_pool = [p for p in posts if p["post_id"] not in used_post_ids and _is_general_eligible(p, d)]
            chosen = random.choice(general_pool) if general_pool else None
        else:
            chosen = None

        if chosen is None:
            continue

        used_post_ids.add(chosen["post_id"])
        planned[iso_day] = chosen["post_id"]
        new_items.append(_queue_item(chosen, d))

    if persist and new_items:
        save_planned_days(planned)

    return new_items
