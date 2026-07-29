# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

This is the **Memories Fond Publisher** app, a Facebook Page automation project with two phases living in this same repo:

- **Phase 1 — archive** (`backfill.py` / `facebook_api.py`), read-and-archive
  only. Fetches posts from an existing Facebook Page's last 3 years via the
  Graph API, classifies them by attachment type, downloads images for the
  text+single-image posts it can act on later, and stores everything locally
  as JSON + JPEGs.
- **Phase 2 — scheduled posting** (`scheduler.py` / `selector.py` /
  `poster_api.py` / `content.py` / `media.py`), posting only. Selects which
  archived post gets scheduled for which upcoming date (`selector.py`), then
  schedules unpublished text, photo, and video posts on the Page ahead of
  time via the Graph API (`scheduler.py`/`poster_api.py`), drafting captions
  from structured facts via the Anthropic API when a post doesn't already
  have one.

The two phases share Facebook Page credentials but otherwise don't depend on
each other's code — `facebook_api.py` stays read-only, `poster_api.py` is a
separate posting-only client. The two are joined by `archive/posts.json` (Phase
1's output) and a queue file (`scheduler.py`'s input) — see Architecture and
Data model below for `selector.py`'s rotation rules.

Paid promotion/boosting (Marketing API — campaigns/adsets/ads) is out of
scope entirely: it needs separate ads-scoped credentials and must never be
invoked automatically from `scheduler.py` — treat it as a manual, deliberate
action only, and don't build it here unless explicitly asked.

## Setup and commands

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
cp .env.example .env   # then fill in FB_PAGE_ID, FB_PAGE_TOKEN, and ANTHROPIC_API_KEY
```

Run with `/usr/bin/python3` (confirm it's still the system Python before
assuming — check with `which python3`) or the project's `.venv`:

```bash
# Phase 1 — archive
python backfill.py run                # archive the last 3 years (default)
python backfill.py run --years 1      # override the lookback window
python backfill.py status             # report on what's archived so far

# Phase 2 — scheduled posting
python scheduler.py plan                                   # select upcoming posts from the archive (selector.py)
python scheduler.py plan --dry-run                          # preview the plan, write nothing
python scheduler.py schedule                                # schedule every pending item in scheduled/queue.json
python scheduler.py schedule --queue queue.json --dry-run  # print Graph API calls only, no network calls
python scheduler.py status                                 # report on what's been scheduled so far

# weekly run (plan + schedule together) — see "Weekly automation" below
python scheduler.py plan && python scheduler.py schedule
```

There is no test suite or linter configured in this repo.

## Architecture

### Phase 1 — archive

- `facebook_api.py` — thin wrapper around Graph API v21.0, **read-only**:
  paginated GET of `/{page-id}/posts` (cursor-based via `paging.next`), plus
  raw image byte download. Has `FacebookAPIError` and basic exponential
  backoff/retry on Graph rate-limit error codes (4, 17, 32, 613). No
  posting/writing endpoints exist here.
- `backfill.py` — CLI entry point (argparse; `run`, `status`, and `flag`
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

### Phase 2 — scheduled posting

- `selector.py` — decides which archived post (from `archive/posts.json`,
  `status: "active"` only) gets scheduled for which upcoming calendar date.
  Rules, in priority order:
  1. A post with `post_day` set (always paired with `post_months`) is
     scheduled on the next upcoming date whose month/day match; if more than
     one active post matches that date, one is chosen at random. `post_day`
     can be a single day (`"25"`), a dash range (`"1-25"`), or a comma
     list/mix of either (`"1-5,25"`) — the post becomes eligible on any day
     in that window and is scheduled (once) on the first such date the
     planning window reaches.
  2. Otherwise, one post is chosen at random every `CADENCE_DAYS` (2) days,
     from posts eligible for that date — `post_day` unset, and `post_months`
     either unset (evergreen) or containing that date's month.
  3. Never more than one post per calendar day (enforced by rule 2 only
     applying when rule 1 found nothing that day) and never the same post
     twice (enforced by `scheduled/planned_days.json`, below).
  The cadence is anchored to a fixed epoch (`CADENCE_EPOCH`, not "N
  days since the last run") so the rotation lands on the same calendar dates
  no matter when `plan` happens to run. The planning window defaults to
  `MAX_SCHEDULE_DAYS`, so each `plan` run tops the schedule back up as far
  out as Meta allows rather than covering only the coming week; it's still
  overridable via `scheduler.py plan --days N`. **`MAX_SCHEDULE_DAYS` is 24,
  not the 75 days Meta's docs claim for `scheduled_publish_time`** — real
  testing against this Page's (Standard Access, not Advanced Access) token
  showed the Graph API accepting a post 24 days out but rejecting one 30
  days out with `(#100) The specified scheduled publish time is invalid.`;
  the 75-day figure likely assumes Advanced Access review. Revisit upward if
  that review is ever completed for `pages_manage_posts`. `plan_queue()`
  returns scheduler.py-shaped queue items with the post's original `message`
  reused verbatim (no Anthropic call — these are literal reposts of
  already-authored captions, not new content) plus `source_facts` as a
  fallback in case `content.py`'s drafting is ever needed for an item with
  no message.
- `poster_api.py` — thin wrapper around Graph API v21.0, **posting only**,
  kept separate from the read-only `facebook_api.py` (different credential
  scope, different failure modes, no reason for either to depend on the
  other). Plain `requests`, no SDK. `FacebookPosterError` carries
  `code`/`error_subcode`/`error_user_msg`/`fbtrace_id`; `ScheduleTooFarError`
  and `WrongTokenTypeError` are raised for recognizable conditions so callers
  can react specifically (a User token produces Graph error code 100/200,
  which reads like a generic auth failure but actually means `FB_PAGE_TOKEN`
  is the wrong token type).
  - `create_text_post()` — one call to `/{page-id}/feed` with
    `scheduled_publish_time` + `published=false`.
  - `upload_unpublished_photo()` + `create_photo_post()` — the two-step photo
    flow: stash the image via `/{page-id}/photos` (`published=false,
    no_story=true`), then schedule via `/{page-id}/feed` with
    `attached_media[0]`. Everything routes through `/feed` (never scheduling
    directly on `/photos`) so Business Suite Planner reports the correct
    `created_time`.
  - `create_video_post()` — one call to `/{page-id}/videos` with
    `scheduled_publish_time` directly, then polls
    `GET /{video_id}?fields=post_id` a few times since the combined
    `{page_id}_{story_id}` post id can lag behind creation.
- `content.py` — drafts post captions via the Anthropic API
  (`anthropic` SDK, `ANTHROPIC_API_KEY`), constrained to the structured
  `source_facts` passed in per queue item — never a hardcoded template, and
  never allowed to invent facts not given. Defaults to `claude-opus-5`
  (override with `ANTHROPIC_MODEL`).
- `media.py` — local gitignored media cache (`media_cache/`, keyed by a
  stable hashed id) so re-runs don't re-download or re-render;
  `verify_commons_license()` checks Wikimedia Commons'
  `extmetadata.LicenseShortName` against an allow-list and gates out
  anything not unambiguously public-domain/permissively-licensed;
  `build_video()` builds an MP4 from a static image + audio track using
  `imageio_ffmpeg`'s bundled binary (no system ffmpeg dependency), with
  caption/credit text burned in via PIL first since bundled ffmpeg builds
  often lack `drawtext`, and the source image downscaled before encoding
  since ffmpeg re-decodes a looped image every output frame.
- `scheduler.py` — CLI entry point (argparse; `plan`, `schedule`, and
  `status` subcommands, `--dry-run` flag on `plan` and `schedule`). `plan`
  calls `selector.plan_queue()` and appends the result to a queue file
  (default `scheduled/queue.json`). `schedule` reads a queue file (see Data
  model below), drafts a caption per item unless one is already given,
  publishes via `poster_api.py`, and persists `scheduled/state.json`
  immediately after each successful action (not batched at the end) so an
  interrupted run can resume without re-scheduling anything. `--dry-run` on
  either subcommand prints/previews without hitting Facebook or the
  Anthropic API or writing any state. `schedule` also skips (without calling
  the Graph API, and without writing `scheduled/state.json`) any item more
  than `selector.MAX_SCHEDULE_DAYS` out — a photo post's two-step flow
  uploads the image to the Page *before* the scheduling call that would
  reject it, so attempting an item known to be too far out would upload an
  orphaned unpublished photo every run until it finally ages into range.
  After a (non-dry-run) `schedule` run, it calls `notify.send_schedule_summary()`
  with whatever was newly scheduled that run (skipped entirely if nothing
  new was scheduled).
- `notify.py` — emails `MY_EMAIL_ADDRESS` a summary of posts newly scheduled
  by a `schedule` run, each with a best-effort preview link
  (`https://www.facebook.com/{page-id}/posts/{post-id}` — the standard Page
  post permalink shape, which admins can open to see a scheduled/unpublished
  post with a "Scheduled" preview banner; not a formally documented Graph API
  feature, just the standard permalink format). Sent via `smtplib` (stdlib)
  through the mail provider configured by the `SMTP_*` env vars — no new
  dependency. If `MY_EMAIL_ADDRESS` or any `SMTP_*` var is unset, the email
  is skipped with a printed warning rather than failing the `schedule` run.

## Weekly automation (Windows Task Scheduler)

`run_weekly.bat` runs `scheduler.py plan` then `scheduler.py schedule` — the
one command a weekly scheduled task should call. To register it:

```
schtasks /create /sc weekly /d MON /st 09:00 /tn "MemoriesFondWeeklyPost" /tr "C:\path\to\memoriesfond_meta\run_weekly.bat"
```

Run that from an elevated `cmd.exe` (or PowerShell) yourself — this isn't
something to script from inside a repo-editing session. `run_weekly.bat`
assumes the venv lives at `.venv\Scripts\python.exe` relative to the repo
root; adjust the path if it's set up differently on the machine that runs it.

## Data model

### Phase 1 — `archive/`

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
    evergreen. `post_day` also accepts a dash range or a comma list/mix of
    either (`"1-25"`, `"1-5,25"`), for holidays spanning more than a single
    date (e.g. Christmas/Santa-themed posts are restricted to Dec 1–25 only:
    `post_months: "12"`, `post_day: "1-25"`); a single-date holiday like
    Valentine's Day gets `post_months: "2"`, `post_day: "14"`. Both fields
    were back-filled by guessing from each post's text/hashtags when the
    field was introduced — treat existing values as a reasonable first pass,
    not ground truth, and correct them as mis-tags are noticed. Most posts
    have no seasonal tie and carry `null`/`null` (evergreen, postable any
    time of year). **Whatever process builds Phase 2's queue file must honor
    these fields**: a post whose `post_months` is set should only be
    eligible on a calendar date whose month is in that CSV list, and if
    `post_day` is also set, the day-of-month must fall in that set/range too
    (day is meaningless without a corresponding month already narrowing
    things down, so it's only ever set alongside `post_months`). A post with
    both fields `null` has no seasonal restriction and can be scheduled for
    any anniversary date the
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

### Phase 2 — queue file, `scheduled/`, `media_cache/`

- **Queue file** (`scheduled/queue.json` by default, gitignored) — a JSON
  list of items to schedule, each:
  `{id, type ("text"|"photo"|"video"), scheduled_publish_time (ISO 8601 or unix timestamp), source_facts, message (optional, skips caption drafting if set), image_path (photo/video), audio_path (video), credit_text (optional, video)}`.
  `selector.py plan` is what normally produces entries in this file (one per
  archived post it's decided to schedule, `id` = the post's `post_id`), but a
  hand-built queue file in the same shape works too — `schedule` doesn't care
  which produced it.
- `scheduled/planned_days.json` (gitignored) — dict of `{iso_date: post_id}`,
  written by `selector.py plan`. This is the day-level ledger that makes
  planning idempotent and enforces "never more than one post per day, never
  the same post twice": a date already present is never re-decided, and
  every post_id that appears as a value is excluded from future picks.
- `scheduled/state.json` (gitignored) — dict keyed by queue item `id`:
  `{status ("scheduled"|"failed"), result/error, scheduled_at/attempted_at}`.
  Written immediately after every successful or failed item, not batched, so
  a `schedule` run can be interrupted and re-run without duplicating posts —
  an item already `status: "scheduled"` is skipped on the next run.
- `media_cache/` (gitignored) — cache of fetched/downloaded/rendered media
  (downscaled frames, built videos), keyed by a stable hashed id so re-runs
  don't redo the work.

## Credentials

`.env` (gitignored) holds:

- `FB_PAGE_ID` / `FB_PAGE_TOKEN` — a Page Access Token, shared by both
  phases. Needs `pages_read_engagement` + `pages_show_list` for Phase 1 and
  `pages_manage_posts` for Phase 2 — **never a User Access Token** (Graph
  error code 100/200 from `poster_api.py` usually means the wrong token type
  was used, not a real permissions problem). This project has its own Meta
  App and Facebook Page, separate from any other Facebook-related project on
  this machine — never reuse another project's token or Page ID here.
- `ANTHROPIC_API_KEY` — used by `content.py` to draft captions. Optional
  `ANTHROPIC_MODEL` override (defaults to `claude-opus-5`).
- `MY_EMAIL_ADDRESS` / `SMTP_HOST` / `SMTP_PORT` / `SMTP_USERNAME` /
  `SMTP_PASSWORD` (optional `SMTP_FROM`, defaults to `SMTP_USERNAME`) — used
  by `notify.py` to email a summary of newly scheduled posts after each
  `scheduler.py schedule` run. For Gmail, `SMTP_PASSWORD` must be an App
  Password, not the account password. All optional as a set — if any is
  missing the email is skipped with a warning, not a hard failure.
- `FB_APP_ID` / `FB_APP_SECRET` — only read by `get_long_lived_token.py`, an
  occasional manual utility (not called by `backfill.py` or `scheduler.py`)
  that exchanges a short-lived User Access Token (from the Graph API
  Explorer, with `pages_manage_posts` etc. granted) for a long-lived Page
  token and writes it straight into `FB_PAGE_TOKEN` above. Both values are on
  the Meta App Dashboard's Settings > Basic page.

`.env.example` is the checked-in template with placeholders, including a
commented-out reminder that any future ads-scoped token
(`ads_management`/`ads_read`/`business_management`) must be a separate
credential from `FB_PAGE_TOKEN`, never reused for boosting.

## Scope boundary

This repo covers Phase 1 (archive) and Phase 2 (scheduled posting, including
`selector.py`'s rotation logic) only. Do not add Instagram cross-posting or
paid promotion/boosting (Marketing API) — those are out of scope unless
explicitly asked for.
