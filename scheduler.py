"""
Phase 2 — schedule unpublished Facebook Page posts ahead of time, and publish
their Instagram cross-post once the date actually arrives.

Usage:
  python3 scheduler.py plan                                    # select upcoming posts from the archive (see selector.py)
  python3 scheduler.py plan --dry-run                          # preview the plan, write nothing
  python3 scheduler.py schedule                                # schedule every pending item in scheduled/queue.json
  python3 scheduler.py schedule --queue queue.json --dry-run   # print Graph API calls only
  python3 scheduler.py publish-instagram                       # publish any due item to Instagram (run daily)
  python3 scheduler.py publish-instagram --dry-run             # preview without hitting Instagram
  python3 scheduler.py status                                  # report on what's been scheduled

  # weekly run (see run_weekly.bat for a Windows Task Scheduler wrapper):
  python3 scheduler.py plan && python3 scheduler.py schedule

  # daily run (see run_daily_instagram.bat) — Instagram has no
  # scheduled_publish_time equivalent, so publishing has to happen on the
  # actual day rather than up-front alongside Facebook's scheduling:
  python3 scheduler.py publish-instagram

`plan` is selector.py's rotation logic (day-specific posts on their calendar
date, otherwise one random eligible post every 3 days, never more than one
post/day) writing to scheduled/queue.json. Each run tops the schedule back up
to the Graph API's full 75-day scheduling window (see selector.MAX_SCHEDULE_DAYS),
not just the coming week, so a weekly `plan` keeps it topped up rather than
covering only the days since the last run. `schedule` reads a queue file —
by default the same scheduled/queue.json `plan` writes to, but any hand-built
queue file works too. Each queue item is a dict:
  {
    "id": "unique-string",
    "type": "text" | "photo" | "video",
    "scheduled_publish_time": "2026-08-01T15:00:00-04:00" (ISO 8601) or a unix timestamp,
    "source_facts": {...},          # passed to the Anthropic API to draft a caption
    "message": null,                # optional pre-written caption; skips drafting if set
    "image_path": "...",            # required for "photo" and "video"
    "audio_path": "...",            # required for "video"
    "credit_text": null             # optional, burned into the video frame alongside the caption
  }

State is persisted to scheduled/state.json (gitignored) immediately after each
successful action, keyed by item id, so an interrupted run can resume without
re-scheduling anything already scheduled.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

import content
import media
import notify
import selector
from instagram_poster_api import InstagramPoster
from poster_api import FacebookPoster

load_dotenv()

BASE_DIR = Path(__file__).parent
STATE_DIR = BASE_DIR / "scheduled"
STATE_FILE = STATE_DIR / "state.json"
INSTAGRAM_STATE_FILE = STATE_DIR / "instagram_state.json"
QUEUE_FILE = STATE_DIR / "queue.json"


def require_env(*names: str):
    missing = [n for n in names if not os.getenv(n)]
    if missing:
        print(f"Error: missing environment variables: {', '.join(missing)}")
        print("Copy .env.example to .env and fill in your credentials.")
        sys.exit(1)


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def load_instagram_state() -> dict:
    if INSTAGRAM_STATE_FILE.exists():
        return json.loads(INSTAGRAM_STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_instagram_state(state: dict):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    INSTAGRAM_STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def parse_scheduled_time(value) -> int:
    if isinstance(value, int):
        return value
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _build_video_path(item: dict) -> str:
    if item.get("video_path"):
        return item["video_path"]

    frame_path = Path(item["image_path"])
    caption_or_credit = item.get("message") or item.get("credit_text")
    if caption_or_credit:
        burned_path = media.cache_path(item["id"] + "-frame", ".jpg")
        frame_path = media.burn_in_caption(frame_path, item.get("message") or "", item.get("credit_text"), burned_path)

    out_path = media.cache_path(item["id"] + "-video", ".mp4")
    media.build_video(frame_path, Path(item["audio_path"]), out_path)
    return str(out_path)


def _publish_item(poster: FacebookPoster, item: dict, message: str, scheduled_ts: int) -> dict:
    post_type = item["type"]
    if post_type == "text":
        return poster.create_text_post(message, scheduled_ts)
    if post_type == "photo":
        photo = poster.upload_unpublished_photo(item["image_path"])
        return poster.create_photo_post(photo["id"], message, scheduled_ts)
    if post_type == "video":
        video_path = _build_video_path(item)
        return poster.create_video_post(video_path, message, scheduled_ts)
    raise ValueError(f"unknown post type: {post_type!r} (item {item['id']})")


def _print_dry_run_calls(item: dict, message: str, scheduled_ts: int):
    post_type = item["type"]
    print("    [dry-run] would call:")
    if post_type == "text":
        print(f"      POST /{{page-id}}/feed  message={message!r}  "
              f"scheduled_publish_time={scheduled_ts}  published=false")
    elif post_type == "photo":
        print(f"      POST /{{page-id}}/photos  published=false  no_story=true  "
              f"source={item.get('image_path')!r}")
        print(f"      POST /{{page-id}}/feed  message={message!r}  "
              f"attached_media[0]={{'media_fbid': <photo_id>}}  "
              f"scheduled_publish_time={scheduled_ts}  published=false")
    elif post_type == "video":
        print(f"      [build video from {item.get('image_path')!r} + {item.get('audio_path')!r}]")
        print(f"      POST /{{page-id}}/videos  description={message!r}  "
              f"scheduled_publish_time={scheduled_ts}  published=false  source=<built video>")
        print("      GET  /{video_id}?fields=post_id  (polled until the story id resolves)")


def cmd_plan(args):
    new_items = selector.plan_queue(days=args.days, persist=not args.dry_run)

    if not new_items:
        print("Nothing new to plan for this window.")
        return

    for item in new_items:
        print(f"  {item['id']}  -> {item['scheduled_publish_time']}  {item['message'][:60]!r}")

    if args.dry_run:
        print(f"\n{len(new_items)} item(s) would be planned "
              f"(dry run — planned_days.json and the queue file were not written).")
        return

    queue_path = Path(args.queue_out)
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    existing = json.loads(queue_path.read_text(encoding="utf-8")) if queue_path.exists() else []
    existing_ids = {item["id"] for item in existing}
    existing.extend(item for item in new_items if item["id"] not in existing_ids)
    queue_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n{len(new_items)} item(s) planned and appended to {queue_path}.")


def cmd_schedule(args):
    queue = json.loads(Path(args.queue).read_text(encoding="utf-8"))
    state = load_state()
    poster = None
    if not args.dry_run:
        require_env("FB_PAGE_ID", "FB_PAGE_TOKEN")
        poster = FacebookPoster(page_id=os.environ["FB_PAGE_ID"], page_token=os.environ["FB_PAGE_TOKEN"])

    scheduled_count = failed_count = skipped_count = pending_count = 0
    max_horizon_seconds = selector.MAX_SCHEDULE_DAYS * 86400
    newly_scheduled = []

    for item in queue:
        item_id = item["id"]
        if state.get(item_id, {}).get("status") == "scheduled":
            print(f"  {item_id}  already scheduled — skipping")
            skipped_count += 1
            continue

        scheduled_ts = parse_scheduled_time(item["scheduled_publish_time"])

        # Skip without calling the Graph API at all if this is still further
        # out than the empirically-known-good window (selector.MAX_SCHEDULE_DAYS):
        # a photo post would otherwise upload an orphaned unpublished photo
        # to the Page every run before failing at the /feed step. Left out of
        # state entirely so it's retried automatically once within range.
        if scheduled_ts - datetime.now(timezone.utc).timestamp() > max_horizon_seconds:
            print(f"  {item_id}  [{item['type']}] scheduled for {item['scheduled_publish_time']} — "
                  f"more than {selector.MAX_SCHEDULE_DAYS} days out, skipping for now "
                  "(will retry once it's closer)")
            pending_count += 1
            continue

        print(f"  {item_id}  [{item['type']}] scheduled for {item['scheduled_publish_time']} ({scheduled_ts})")

        if args.dry_run:
            message = item.get("message") or "<caption drafted at run time from source_facts>"
            print(f"    message: {message!r}")
            _print_dry_run_calls(item, message, scheduled_ts)
            continue

        try:
            message = item.get("message") or content.draft_caption(item.get("source_facts", {}), item["type"])
            print(f"    message: {message!r}")
            result = _publish_item(poster, item, message, scheduled_ts)
        except Exception as e:
            print(f"    failed: {e}")
            state[item_id] = {
                "status": "failed",
                "error": str(e),
                "attempted_at": datetime.now(timezone.utc).isoformat(),
            }
            save_state(state)
            failed_count += 1
            continue

        state[item_id] = {
            "status": "scheduled",
            "scheduled_publish_time": scheduled_ts,
            "result": result,
            "scheduled_at": datetime.now(timezone.utc).isoformat(),
        }
        save_state(state)
        print(f"    ok: {result}")
        scheduled_count += 1
        newly_scheduled.append({
            "id": item_id,
            "type": item["type"],
            "scheduled_ts": scheduled_ts,
            "message": message,
            "result": result,
        })

    if not args.dry_run:
        print(f"\nDone: {scheduled_count} scheduled, {failed_count} failed, "
              f"{skipped_count} already-scheduled, {pending_count} not yet in the schedulable window.")
        notify.send_schedule_summary(os.environ["FB_PAGE_ID"], newly_scheduled)


def cmd_publish_instagram(args):
    """Publishes queue items to Instagram once their scheduled_publish_time has
    actually arrived. Unlike Facebook, Instagram content publishing has no
    scheduled_publish_time equivalent — a container can be created ahead of
    time, but media_publish makes it live immediately — so this is meant to
    run daily (see run_daily_instagram.bat), separately from the weekly
    plan+schedule cadence that fronts Facebook's scheduling up to 24 days out."""
    queue = json.loads(Path(args.queue).read_text(encoding="utf-8"))
    fb_state = load_state()
    ig_state = load_instagram_state()
    poster = None
    if not args.dry_run:
        require_env("IG_BUSINESS_ACCOUNT_ID", "FB_PAGE_TOKEN", "GITHUB_RAW_BASE_URL")
        poster = InstagramPoster(ig_user_id=os.environ["IG_BUSINESS_ACCOUNT_ID"], page_token=os.environ["FB_PAGE_TOKEN"])
    base_url = os.getenv("GITHUB_RAW_BASE_URL", "")

    now_ts = datetime.now(timezone.utc).timestamp()
    published_count = failed_count = skipped_count = not_due_count = 0
    newly_published = []

    for item in queue:
        item_id = item["id"]

        if item["type"] != "photo":
            continue  # Instagram posting only supports photo items for now
        if not item.get("ig_eligible", False):
            print(f"  {item_id}  aspect ratio out of Instagram's allowed range — Facebook-only, skipping")
            continue
        if ig_state.get(item_id, {}).get("status") == "published":
            print(f"  {item_id}  already published to Instagram — skipping")
            skipped_count += 1
            continue
        if fb_state.get(item_id, {}).get("status") != "scheduled":
            print(f"  {item_id}  not yet scheduled on Facebook — skipping")
            continue

        scheduled_ts = parse_scheduled_time(item["scheduled_publish_time"])
        if scheduled_ts > now_ts:
            print(f"  {item_id}  scheduled for {item['scheduled_publish_time']} — not due yet, skipping")
            not_due_count += 1
            continue

        message = item.get("message") or content.draft_caption(item.get("source_facts", {}), item["type"])
        image_url = f"{base_url.rstrip('/')}/{item['image_path']}"
        print(f"  {item_id}  scheduled for {item['scheduled_publish_time']} — due now")
        print(f"    message: {message!r}")
        print(f"    image_url: {image_url}")

        if args.dry_run:
            print("    [dry-run] would call: POST /{ig-user-id}/media, poll status, POST /{ig-user-id}/media_publish")
            continue

        try:
            result = poster.create_photo_post(image_url, message)
        except Exception as e:
            print(f"    failed: {e}")
            ig_state[item_id] = {
                "status": "failed",
                "error": str(e),
                "attempted_at": datetime.now(timezone.utc).isoformat(),
            }
            save_instagram_state(ig_state)
            failed_count += 1
            continue

        ig_state[item_id] = {
            "status": "published",
            "result": result,
            "published_at": datetime.now(timezone.utc).isoformat(),
        }
        save_instagram_state(ig_state)
        print(f"    ok: {result}")
        published_count += 1
        newly_published.append({"id": item_id, "message": message, "result": result})

    if not args.dry_run:
        print(f"\nDone: {published_count} published, {failed_count} failed, "
              f"{skipped_count} already-published, {not_due_count} not yet due.")
        notify.send_instagram_summary(newly_published)


def cmd_status(_args):
    state = load_state()
    if not state:
        print("No items tracked yet — run `scheduler.py schedule --queue <file>` first.")
        return

    by_status: dict[str, int] = {}
    for entry in state.values():
        status = entry.get("status", "unknown")
        by_status[status] = by_status.get(status, 0) + 1

    print(f"Tracked items: {len(state)}")
    for status, count in sorted(by_status.items(), key=lambda kv: -kv[1]):
        print(f"  - {status}: {count}")


def main():
    parser = argparse.ArgumentParser(description="Phase 2: schedule unpublished Facebook Page posts ahead of time")
    sub = parser.add_subparsers(dest="command")

    plan = sub.add_parser("plan", help="Select archived posts for upcoming dates (see selector.py) and queue them")
    plan.add_argument("--days", type=int, default=selector.MAX_SCHEDULE_DAYS,
                       help=f"How many days ahead to plan (default: {selector.MAX_SCHEDULE_DAYS} — "
                            "as far out as the Graph API's 75-day scheduling limit allows)")
    plan.add_argument("--queue-out", default=str(QUEUE_FILE),
                       help=f"Queue file to append planned items to (default: {QUEUE_FILE})")
    plan.add_argument("--dry-run", action="store_true",
                       help="Preview the plan without writing planned_days.json or the queue file")

    schedule = sub.add_parser("schedule", help="Schedule every not-yet-scheduled item in a queue file")
    schedule.add_argument("--queue", default=str(QUEUE_FILE),
                           help=f"Path to a JSON queue file (default: {QUEUE_FILE}; see CLAUDE.md for the schema)")
    schedule.add_argument("--dry-run", action="store_true",
                           help="Print the exact Graph API calls/payloads without hitting Facebook or the Anthropic API")

    publish_ig = sub.add_parser("publish-instagram",
                                 help="Publish any due queue item to Instagram (run daily — see run_daily_instagram.bat)")
    publish_ig.add_argument("--queue", default=str(QUEUE_FILE),
                             help=f"Path to a JSON queue file (default: {QUEUE_FILE})")
    publish_ig.add_argument("--dry-run", action="store_true",
                             help="Print what would be published without hitting Instagram or the Anthropic API")

    sub.add_parser("status", help="Report on what's been scheduled so far")

    args = parser.parse_args()
    if args.command == "plan":
        cmd_plan(args)
    elif args.command == "schedule":
        cmd_schedule(args)
    elif args.command == "publish-instagram":
        cmd_publish_instagram(args)
    elif args.command == "status":
        cmd_status(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
