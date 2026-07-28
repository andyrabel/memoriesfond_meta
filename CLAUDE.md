# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

This is the **Memories Fond Publisher** app. Phase 1 of a Facebook Page automation project, **read-and-archive only**. It
fetches posts from an existing Facebook Page's last 3 years via the Graph
API, classifies them by attachment type, downloads images for the
text+single-image posts it can act on later, and stores everything locally
as JSON + JPEGs. The eventual goal (a later phase, not yet built) is to
re-post archived posts on their calendar anniversary — this repo does not
contain any posting/scheduling logic, and none should be added without being
explicitly asked.

## Setup and commands

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
cp .env.example .env   # then fill in FB_PAGE_ID and FB_PAGE_TOKEN
```

Run with `/usr/bin/python3` (confirm it's still the system Python before
assuming — check with `which python3`) or the project's `.venv`:

```bash
python backfill.py run                # archive the last 3 years (default)
python backfill.py run --years 1      # override the lookback window
python backfill.py status             # report on what's archived so far
```

There is no test suite or linter configured in this repo.

## Architecture

- `facebook_api.py` — thin wrapper around Graph API v21.0, **read-only**:
  paginated GET of `/{page-id}/posts` (cursor-based via `paging.next`), plus
  raw image byte download. Has `FacebookAPIError` and basic exponential
  backoff/retry on Graph rate-limit error codes (4, 17, 32, 613). No
  posting/writing endpoints exist here.
- `backfill.py` — CLI entry point (argparse; `run` and `status`
  subcommands) and all orchestration/classification/persistence logic,
  kept in one file since Phase 1's scope is intentionally small.
  - `classify_post()` decides keep vs. skip per post from `attachments.data`:
    single photo → keep; multi-photo album, video, shared link, or
    text-only (no attachment) → skip with a reason string.
  - Pagination stops as soon as a post's `created_time` is older than
    `today - years` (leap-day-safe via `years_ago()`), or when
    `paging.next` runs out first.
  - Idempotency: `posts.json`/`skipped_posts.json` are keyed by `post_id`
    on every run — already-recorded posts are skipped, except a kept post
    whose image file is missing on disk gets re-downloaded. A run can
    safely be interrupted and re-run from scratch.

## Data model

Everything lives under `archive/` (gitignored — this holds the Page's real
content and downloaded images, never commit it):

- `archive/posts.json` — list of kept posts:
  `{post_id, message, created_time (ISO date), post_months, post_day, image_path, permalink_url, status}`.
  `created_time` is date-only because a later phase will match posts to
  their calendar anniversary by day-of-year. `status` defaults to `active`;
  editorial curation (content that's stale or needs a rewrite before it's
  ever reposted) sets it to values like `needs_update` or `excluded` via
  `backfill.py flag --contains ... --status ...` rather than moving the
  entry to `skipped_posts.json`, whose reasons are reserved for automatic,
  structural exclusions decided by `classify_post()`.
  - `post_months` / `post_day` — optional CSV strings (`null` when absent)
    restricting which calendar months/days a post is allowed to be
    reposted on, for content tied to a season or holiday rather than
    evergreen (e.g. a Christmas-themed post might have
    `post_months: "11,12"`; a Valentine's/Feb-14-specific post might have
    `post_months: "2"`, `post_day: "14"`). Both were back-filled by guessing
    from each post's text/hashtags when the field was introduced — treat
    existing values as a reasonable first pass, not ground truth, and
    correct them as mis-tags are noticed. Most posts have no seasonal tie
    and carry `null`/`null` (evergreen, postable any time of year).
    **When the scheduler (a later phase) is built, it must honor these
    fields**: a post whose `post_months` is set should only be eligible on
    a calendar date whose month is in that CSV list, and if `post_day` is
    also set, the day-of-month must match too (day is meaningless without
    a corresponding month already narrowing things down, so it's only ever
    set alongside `post_months`). A post with both fields `null` has no
    seasonal restriction and can be scheduled for any anniversary date the
    normal logic picks.
- `archive/skipped_posts.json` — list of `{post_id, reason, created_time}`.
  Reasons: `multi_photo_album`, `video`, `shared_link`,
  `text_only_no_image`, `photo_missing_src`, `image_download_failed:...`,
  `unrecognized_attachment_type:...`.
- `archive/images/{post_id}.jpg` — downloaded image bytes for each kept
  post. Facebook's photo URLs are signed and expire, so the binary is
  always fetched immediately rather than storing the URL.
- `archive/state.json` — `last_run` timestamp, `cutoff_date` used, and
  `window_fully_covered` (whether pagination reached the cutoff date
  rather than just running out of pages).

## Credentials

`.env` (gitignored) holds `FB_PAGE_ID` and `FB_PAGE_TOKEN` — a Page Access
Token needing only `pages_read_engagement` + `pages_show_list` for this
phase. `.env.example` is the checked-in template with placeholders. This
project has its own Meta App and Facebook Page, separate from any other
Facebook-related project on this machine — never reuse another project's
token or Page ID here.

## Scope boundary

This repo is Phase 1 only: read and archive. Do not add posting,
scheduling, or Instagram cross-posting logic here unless explicitly asked
— those are planned as separate later phases.
