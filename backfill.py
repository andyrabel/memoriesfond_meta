"""
Phase 1 — read-and-archive only.

Usage:
  python3 backfill.py run                     # fetch/archive the last 3 years of posts
  python3 backfill.py run --years 1            # override the lookback window
  python3 backfill.py status                   # report on what's been archived so far

Reads every post from the configured Facebook Page going back N years (default
3), keeps only text+single-image posts (the only kind Phase 2 will be able to
re-post), downloads each kept post's image immediately (Facebook's photo URLs
are signed and expire), and records everything else in skipped_posts.json with
a reason. No posting/scheduling logic lives here — that's Phase 2.
"""
import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv

from facebook_api import FacebookAPI, FacebookAPIError, POST_FIELDS

load_dotenv()

BASE_DIR = Path(__file__).parent
ARCHIVE_DIR = BASE_DIR / "archive"
IMAGES_DIR = ARCHIVE_DIR / "images"
POSTS_FILE = ARCHIVE_DIR / "posts.json"
SKIPPED_FILE = ARCHIVE_DIR / "skipped_posts.json"
STATE_FILE = ARCHIVE_DIR / "state.json"

DEFAULT_YEARS_BACK = 3
PAGE_SIZE = 50


def require_env(*names: str):
    missing = [n for n in names if not os.getenv(n)]
    if missing:
        print(f"Error: missing environment variables: {', '.join(missing)}")
        print("Copy .env.example to .env and fill in your credentials.")
        sys.exit(1)


def load_json_list(path: Path) -> list:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return []


def save_json_list(path: Path, data: list):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"window_fully_covered": False, "last_run": None, "cutoff_date": None}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def years_ago(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year - years)
    except ValueError:
        # d was Feb 29 and the target year has no leap day
        return d.replace(month=2, day=28, year=d.year - years)


def parse_fb_datetime(s: str) -> datetime:
    """Facebook's created_time looks like '2023-07-20T15:23:01+0000'."""
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z")


def classify_post(post: dict) -> tuple[str, str | None, str | None]:
    """Returns (decision, skip_reason, image_url) where decision is 'keep' or 'skip'."""
    attachments = post.get("attachments", {}).get("data", [])

    if not attachments:
        return "skip", "text_only_no_image", None

    if len(attachments) > 1:
        return "skip", "multi_photo_album", None

    att = attachments[0]
    media_type = att.get("media_type") or att.get("type")

    if att.get("subattachments", {}).get("data"):
        return "skip", "multi_photo_album", None
    if media_type in ("album",):
        return "skip", "multi_photo_album", None
    if media_type in ("video", "video_inline", "video_autoplay"):
        return "skip", "video", None
    if media_type == "link" or att.get("type") == "share":
        return "skip", "shared_link", None
    if media_type == "photo":
        src = att.get("media", {}).get("image", {}).get("src")
        if not src:
            return "skip", "photo_missing_src", None
        return "keep", None, src

    return "skip", f"unrecognized_attachment_type:{media_type}", None


def cmd_run(args):
    require_env("FB_PAGE_ID", "FB_PAGE_TOKEN")
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    api = FacebookAPI(page_id=os.environ["FB_PAGE_ID"], page_token=os.environ["FB_PAGE_TOKEN"])

    posts = load_json_list(POSTS_FILE)
    skipped = load_json_list(SKIPPED_FILE)
    posts_by_id = {p["post_id"]: p for p in posts}
    skipped_ids = {s["post_id"] for s in skipped}

    cutoff = years_ago(date.today(), args.years)
    print(f"Archiving posts back to {cutoff.isoformat()} ({args.years} year(s))...\n")

    kept_count = skipped_count = 0
    reached_cutoff = False
    page = 0

    body = api.get_posts_page({"fields": POST_FIELDS, "limit": PAGE_SIZE})

    while True:
        page += 1
        batch = body.get("data", [])
        print(f"  page {page}: {len(batch)} post(s)")

        for post in batch:
            post_id = post["id"]
            created_dt = parse_fb_datetime(post["created_time"])
            if created_dt.date() < cutoff:
                reached_cutoff = True
                break

            if post_id in posts_by_id or post_id in skipped_ids:
                # Already classified in a previous run. Only work left to do
                # is make sure a kept post's image actually made it to disk.
                existing = posts_by_id.get(post_id)
                if existing:
                    image_path = BASE_DIR / existing["image_path"]
                    if not image_path.exists():
                        decision, _reason, image_url = classify_post(post)
                        if decision == "keep" and image_url:
                            print(f"    {post_id}  re-downloading missing image...", end="", flush=True)
                            try:
                                image_bytes = api.download_image(image_url)
                                image_path.write_bytes(image_bytes)
                                print(" ok")
                            except FacebookAPIError as e:
                                print(f" failed ({e})")
                continue

            decision, reason, image_url = classify_post(post)
            if decision == "skip":
                entry = {"post_id": post_id, "reason": reason, "created_time": created_dt.date().isoformat()}
                skipped.append(entry)
                skipped_ids.add(post_id)
                save_json_list(SKIPPED_FILE, skipped)
                skipped_count += 1
                print(f"    {post_id}  skip ({reason})")
                continue

            image_filename = f"{post_id}.jpg"
            image_path = IMAGES_DIR / image_filename
            print(f"    {post_id}  downloading image...", end="", flush=True)
            try:
                image_bytes = api.download_image(image_url)
                image_path.write_bytes(image_bytes)
            except FacebookAPIError as e:
                print(f" failed ({e}) — logging as skipped instead")
                entry = {"post_id": post_id, "reason": f"image_download_failed:{e}",
                          "created_time": created_dt.date().isoformat()}
                skipped.append(entry)
                skipped_ids.add(post_id)
                save_json_list(SKIPPED_FILE, skipped)
                skipped_count += 1
                continue
            print(" ok")

            entry = {
                "post_id": post_id,
                "message": post.get("message", ""),
                "created_time": created_dt.date().isoformat(),
                "image_path": str(image_path.relative_to(BASE_DIR)),
                "permalink_url": post.get("permalink_url", ""),
            }
            posts.append(entry)
            posts_by_id[post_id] = entry
            save_json_list(POSTS_FILE, posts)
            kept_count += 1

        if reached_cutoff:
            break

        next_url = body.get("paging", {}).get("next")
        if not next_url:
            # Ran out of pages before reaching the cutoff date — the whole
            # page history is shorter than the requested window.
            reached_cutoff = True
            break

        body = api.get_next_page(next_url)

    state = load_state()
    state["window_fully_covered"] = reached_cutoff
    state["last_run"] = datetime.now().isoformat()
    state["cutoff_date"] = cutoff.isoformat()
    save_state(state)

    print(f"\nDone: {kept_count} kept, {skipped_count} skipped this run.")
    print(f"Archive totals: {len(posts)} kept, {len(skipped)} skipped.")


def cmd_flag(args):
    """Sets a post's editorial status. posts.json only ever holds currently-
    eligible (status: "active") posts — it's checked into the repo for
    Instagram's image-hosting needs (see CLAUDE.md), so anything not actually
    postable shouldn't be sitting in it. Setting a non-"active" status moves
    the entry out to skipped_posts.json (reason: "editorial_status:<status>");
    setting "active" moves a previously-flagged entry back in."""
    posts = load_json_list(POSTS_FILE)
    skipped = load_json_list(SKIPPED_FILE)
    if not posts and not skipped:
        print("No posts found — run `backfill.py run` first.")
        return

    needles = [c.lower() for c in (args.contains or [])]
    post_ids = set(args.post_id or [])

    def matches(post_id: str, message: str) -> bool:
        message = (message or "").lower()
        return post_id in post_ids or any(n in message for n in needles)

    matched_posts = [p for p in posts if matches(p["post_id"], p.get("message"))]
    matched_skipped = [s for s in skipped if s.get("reason", "").startswith("editorial_status:")
                        and matches(s["post_id"], s.get("message"))]
    matched = len(matched_posts) + len(matched_skipped)

    if args.dry_run:
        for p in matched_posts + matched_skipped:
            action = "stay in posts.json" if args.status == "active" else "move to skipped_posts.json"
            print(f"  {p['post_id']}  would set status={args.status!r} ({action})  {p.get('message', '')[:60]!r}")
        print(f"\n{matched} post(s) matched (dry run — no changes written).")
        return

    if args.status == "active":
        for p in matched_posts:
            p["status"] = "active"
        for entry in matched_skipped:
            entry["status"] = "active"
            entry.pop("reason", None)
            posts.append(entry)
        skipped = [s for s in skipped if s not in matched_skipped]
    else:
        for p in matched_posts:
            p["status"] = args.status
            p["reason"] = f"editorial_status:{args.status}"
            skipped.append(p)
        posts = [p for p in posts if p not in matched_posts]
        for entry in matched_skipped:
            entry["status"] = args.status
            entry["reason"] = f"editorial_status:{args.status}"

    save_json_list(POSTS_FILE, posts)
    save_json_list(SKIPPED_FILE, skipped)
    print(f"{matched} post(s) updated to status={args.status!r}.")


def cmd_status(_args):
    posts = load_json_list(POSTS_FILE)
    skipped = load_json_list(SKIPPED_FILE)
    state = load_state()

    total_found = len(posts) + len(skipped)
    print(f"Posts found:   {total_found}")
    print(f"  kept:        {len(posts)}  (text + single image)")
    if posts:
        statuses: dict[str, int] = {}
        for p in posts:
            statuses[p.get("status", "active")] = statuses.get(p.get("status", "active"), 0) + 1
        for status, count in sorted(statuses.items(), key=lambda kv: -kv[1]):
            print(f"    - {status}: {count}")
    print(f"  skipped:     {len(skipped)}")

    if skipped:
        reasons: dict[str, int] = {}
        for s in skipped:
            reasons[s["reason"]] = reasons.get(s["reason"], 0) + 1
        for reason, count in sorted(reasons.items(), key=lambda kv: -kv[1]):
            print(f"    - {reason}: {count}")

    all_dates = [p["created_time"] for p in posts] + [s["created_time"] for s in skipped]
    if all_dates:
        print(f"\nDate range covered: {min(all_dates)} to {max(all_dates)}")
    else:
        print("\nDate range covered: (none — run `backfill.py run` first)")

    if state.get("last_run"):
        print(f"\nLast run: {state['last_run']}")
        print(f"Cutoff target: {state.get('cutoff_date')}")
        print(f"3-year window fully covered: {'yes' if state.get('window_fully_covered') else 'no — run again'}")
    else:
        print("\nNo run recorded yet — run `backfill.py run` first.")


def main():
    parser = argparse.ArgumentParser(description="Phase 1: archive a Facebook Page's posts (read-only)")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="Fetch and archive posts from the last N years")
    run.add_argument("--years", type=int, default=DEFAULT_YEARS_BACK,
                      help=f"How many years back to archive (default: {DEFAULT_YEARS_BACK})")

    sub.add_parser("status", help="Report on what's been archived so far")

    flag = sub.add_parser("flag", help="Mark kept posts matching text patterns or IDs with a status")
    flag.add_argument("--contains", action="append",
                       help="Case-insensitive substring to match in the post message (repeatable)")
    flag.add_argument("--post-id", action="append",
                       help="Exact post_id to match, for image-only posts with no text (repeatable)")
    flag.add_argument("--status", required=True,
                       help="Status to set on matching posts, e.g. needs_update, excluded")
    flag.add_argument("--dry-run", action="store_true",
                       help="Preview matches without writing changes")

    args = parser.parse_args()

    if args.command == "run":
        cmd_run(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "flag":
        cmd_flag(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
