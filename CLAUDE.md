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
- **Instagram cross-posting** (`instagram_poster_api.py`), posting only,
  photo posts only. The same photo posts scheduled on Facebook also get
  published to the Page's linked Instagram Business account, reusing the
  same caption. This is a genuinely different API shape from Facebook's,
  not just another `poster_api.py` method — see its own bullet under
  Architecture below and the `publish-instagram` subcommand under
  `scheduler.py`.

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
python scheduler.py publish-instagram                       # publish any due item to Instagram (see below)
python scheduler.py publish-instagram --dry-run            # preview without hitting Instagram
python scheduler.py status                                 # report on what's been scheduled so far

# weekly run (plan + schedule together) — see "Weekly automation" below
python scheduler.py plan && python scheduler.py schedule

# daily run (Instagram publishing) — see "Daily automation" below
python scheduler.py publish-instagram
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
  no message. Each item also carries `ig_eligible`
  (`instagram_poster_api.is_aspect_ratio_ok()` run against the post's image
  at plan time) so `scheduler.py publish-instagram` doesn't need to
  re-derive it — a post outside Instagram's allowed aspect-ratio band still
  posts to Facebook as normal, it's just skipped for Instagram.
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
- `instagram_poster_api.py` — thin wrapper around the Instagram Graph API
  v21.0, **posting only, photo posts only**. A genuinely different shape
  from `poster_api.py`, not just another method on it:
  - No file upload — Instagram requires a publicly reachable `image_url`
    per post. That's why `archive/images/` and `archive/posts.json` are
    checked into this repo (see Data model below): each image is served
    back out via `raw.githubusercontent.com` (`GITHUB_RAW_BASE_URL` +
    the post's `image_path`) rather than uploaded as bytes.
  - Two-step container flow rather than one call: `create_media_container()`
    (`POST /{ig-user-id}/media` with `image_url` + caption) returns a
    creation id, `wait_for_container_ready()` polls
    `GET /{creation_id}?fields=status_code` until Instagram finishes
    downloading/processing the image, then `publish_container()`
    (`POST /{ig-user-id}/media_publish`) makes it live. `create_photo_post()`
    runs all three in sequence.
  - **No `scheduled_publish_time` equivalent** — `media_publish` posts
    immediately, there is no way to hand Instagram a future timestamp and
    have it hold the post the way Facebook's `/feed` does. This is why
    Instagram publishing is a separate daily step (`scheduler.py
    publish-instagram`, see below) rather than folded into the weekly
    `plan`/`schedule` flow that fronts Facebook's scheduling up to 24 days
    out.
  - `is_aspect_ratio_ok()` checks a local image against Instagram's allowed
    feed aspect-ratio band (4:5 to 1.91:1) — anything outside it is rejected
    by the API at container-creation time, so it's checked locally first
    (used by `selector.py` to set `ig_eligible`, see above).
  - `InstagramPosterError` mirrors `FacebookPosterError`'s shape
    (`code`/`error_subcode`/`fbtrace_id`); `ContainerProcessingError` covers
    a container that errors or never finishes processing.
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
- `scheduler.py` — CLI entry point (argparse; `plan`, `schedule`,
  `publish-instagram`, and `status` subcommands, `--dry-run` flag on `plan`,
  `schedule`, and `publish-instagram`). `plan` calls `selector.plan_queue()`
  and appends the result to a queue file (default `scheduled/queue.json`).
  `schedule` reads a queue file (see Data model below), drafts a caption per
  item unless one is already given, publishes via `poster_api.py`, and
  persists `scheduled/state.json` immediately after each successful action
  (not batched at the end) so an interrupted run can resume without
  re-scheduling anything. `--dry-run` prints/previews without hitting
  Facebook/Instagram or the Anthropic API or writing any state. `schedule`
  also skips (without calling the Graph API, and without writing
  `scheduled/state.json`) any item more than `selector.MAX_SCHEDULE_DAYS`
  out — a photo post's two-step flow uploads the image to the Page *before*
  the scheduling call that would reject it, so attempting an item known to
  be too far out would upload an orphaned unpublished photo every run until
  it finally ages into range. After a (non-dry-run) `schedule` run, it calls
  `notify.send_schedule_summary()` with whatever was newly scheduled that
  run (skipped entirely if nothing new was scheduled).
  - `publish-instagram` is a separate step, meant to run daily rather than
    weekly (see "Daily automation" below), because Instagram has no
    `scheduled_publish_time` equivalent (see `instagram_poster_api.py`
    above) — it walks the same queue file and, for each `type: "photo"`
    item that is `ig_eligible`, already Facebook-`"scheduled"`, not already
    published to Instagram (tracked in `scheduled/instagram_state.json`,
    same idempotency pattern as `state.json`), and whose
    `scheduled_publish_time` has actually arrived, builds the image's
    `raw.githubusercontent.com` URL and calls
    `InstagramPoster.create_photo_post()`. Persists
    `scheduled/instagram_state.json` immediately per item, then calls
    `notify.send_instagram_summary()` with whatever was newly published.
- `notify.py` — emails `MY_EMAIL_ADDRESS` a summary of posts newly scheduled
  by a `schedule` run, each with a best-effort preview link
  (`https://www.facebook.com/{page-id}/posts/{post-id}` — the standard Page
  post permalink shape, which admins can open to see a scheduled/unpublished
  post with a "Scheduled" preview banner; not a formally documented Graph API
  feature, just the standard permalink format). `send_instagram_summary()` is
  the analogous email after a `publish-instagram` run, linking each post's
  real Instagram `permalink` (returned directly by the Graph API, unlike
  Facebook's best-effort guess). Both sent via `smtplib` (stdlib) through the
  mail provider configured by the `SMTP_*` env vars — no new dependency. If
  `MY_EMAIL_ADDRESS` or any `SMTP_*` var is unset, the email is skipped with
  a printed warning rather than failing the run.

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

## Daily automation (Windows Task Scheduler)

`run_daily_instagram.bat` runs `scheduler.py publish-instagram` — separate
from the weekly task above because Instagram content publishing has no
`scheduled_publish_time` equivalent (see `instagram_poster_api.py`):
publishing has to happen on the actual day, not up-front alongside
Facebook's scheduling. To register it:

```
schtasks /create /sc daily /st 07:30 /tn "MemoriesFondDailyInstagram" /tr "C:\path\to\memoriesfond_meta\run_daily_instagram.bat"
```

Same caveats as `run_weekly.bat` — run that from an elevated shell yourself,
and it assumes the same `.venv\Scripts\python.exe` layout. A day with nothing
due is a normal, silent success (`publish-instagram` just skips every item
and exits 0), not a failure — no special-casing needed for that.

`/st` fires in the machine's local time, while `SCHEDULE_HOUR`/`SCHEDULE_TIMEZONE`
(default noon UTC — see selector.py) is what Facebook posts are scheduled
for. If 07:30 local is earlier than that in UTC terms, a post due "today"
won't look due yet at 07:30 and will just get picked up on the *next* day's
run instead (harmless — `publish-instagram` has no upper time limit on
eligibility, so nothing is missed, it's a one-day lag at most). Adjust
`SCHEDULE_HOUR`/`SCHEDULE_TIMEZONE` or this task's time if same-day parity
with the Facebook post going live matters.

## Data model

### Phase 1 — `archive/`

Everything lives under `archive/`, but `posts.json` and `images/` are the
exception to the usual "never commit the archive" rule: `.gitignore` reads

```
archive/*
!archive/images/
!archive/posts.json
```

so those two are checked into the (public) repo and `skipped_posts.json`/
`state.json` stay gitignored as before. This was deliberate, not an
oversight: Instagram's Graph API requires a publicly reachable `image_url`
per post rather than accepting a raw file upload (see
`instagram_poster_api.py`), so `posts.json`/`images/` are served back out via
`raw.githubusercontent.com` at publish time. Everything in this content was
already posted publicly to the Facebook Page; a scan of all archived
messages for anything address/phone/medical/financial turned up nothing
before this was turned on (this is a children's-book author's promo page,
not one handling sensitive personal content) — re-check that assumption if
the Page's content ever changes character.

- `archive/posts.json` — list of kept, currently-**eligible** posts only:
  `{post_id, message, created_time (ISO date), post_months, post_day, image_path, permalink_url, status}`.
  Only ever contains `status: "active"` entries — a post that needs
  editorial curation (stale content, needs a rewrite before ever being
  reposted) is moved *out* to `skipped_posts.json` entirely (with
  `reason: "editorial_status:<status>"`, e.g. `editorial_status:needs_update`
  or `editorial_status:excluded`) rather than staying in `posts.json` with a
  non-`active` status — since `posts.json` is now public, anything not
  actually postable shouldn't be sitting in it. `created_time` is date-only
  because a later phase matches posts to their calendar anniversary by
  day-of-year. `backfill.py flag --contains ... --status ...` performs this
  move for editorial curation, same command as before.
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
- `archive/skipped_posts.json` — list of `{post_id, reason, created_time}`,
  plus the full original post fields for anything moved here from
  `posts.json` by `backfill.py flag` (see above). Reasons:
  `multi_photo_album`, `video`, `shared_link`, `text_only_no_image`,
  `photo_missing_src`, `image_download_failed:...`,
  `unrecognized_attachment_type:...` (automatic, structural — decided by
  `classify_post()`), or `editorial_status:<status>` (e.g.
  `editorial_status:needs_update`, `editorial_status:excluded` — manual,
  via `backfill.py flag`).
- `archive/images/{post_id}.jpg` — downloaded image bytes for each kept
  post. Facebook's photo URLs are signed and expire, so the binary is
  always fetched immediately rather than storing the URL.
- `archive/state.json` — `last_run` timestamp, `cutoff_date` used, and
  `window_fully_covered` (whether pagination reached the cutoff date
  rather than just running out of pages).

### Phase 2 — queue file, `scheduled/`, `media_cache/`

- **Queue file** (`scheduled/queue.json` by default, gitignored) — a JSON
  list of items to schedule, each:
  `{id, type ("text"|"photo"|"video"), scheduled_publish_time (ISO 8601 or unix timestamp), source_facts, message (optional, skips caption drafting if set), image_path (photo/video), audio_path (video), credit_text (optional, video), ig_eligible (photo only)}`.
  `selector.py plan` is what normally produces entries in this file (one per
  archived post it's decided to schedule, `id` = the post's `post_id`), but a
  hand-built queue file in the same shape works too — `schedule` (and
  `publish-instagram`) doesn't care which produced it. `ig_eligible` is only
  meaningful for `type: "photo"` items — whether the image's aspect ratio
  falls inside Instagram's allowed feed range (see `instagram_poster_api.py`).
- `scheduled/planned_days.json` (gitignored) — dict of `{iso_date: post_id}`,
  written by `selector.py plan`. This is the day-level ledger that makes
  planning idempotent and enforces "never more than one post per day, never
  the same post twice": a date already present is never re-decided, and
  every post_id that appears as a value is excluded from future picks.
- `scheduled/state.json` (gitignored) — dict keyed by queue item `id`:
  `{status ("scheduled"|"failed"), result/error, scheduled_at/attempted_at}`.
  Written immediately after every successful or failed item, not batched, so
  a `schedule` run can be interrupted and re-run without duplicating posts —
  an item already `status: "scheduled"` is skipped on the next run. This
  tracks Facebook only.
  - `scheduled/instagram_state.json` (gitignored) — same shape and
    idempotency pattern, but for Instagram:
    `{status ("published"|"failed"), result/error, published_at/attempted_at}`,
    written by `scheduler.py publish-instagram`. Kept as a separate file
    (rather than a key inside `state.json`) since the two platforms publish
    on entirely different triggers — Facebook via `scheduled_publish_time`
    resolved by Meta itself, Instagram via this repo actively calling
    `media_publish` once the date arrives — and can independently succeed or
    fail without affecting each other's retry behavior.
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
  this machine — never reuse another project's token or Page ID here. Also
  needs `instagram_basic` + `instagram_content_publish` for Instagram
  cross-posting (added via Graph API Explorer's "API setup with Facebook
  login" flow — not "API setup with Instagram login", which is a different,
  standalone Instagram Business Login flow that issues its own separate
  token and doesn't fit this project's single-Page-token model).
- `IG_BUSINESS_ACCOUNT_ID` — the Instagram Business account linked to the
  Page, used by `instagram_poster_api.py`. Find it via
  `GET /{page-id}?fields=instagram_business_account`.
- `GITHUB_RAW_BASE_URL` — base URL (`https://raw.githubusercontent.com/<user>/<repo>/<branch>`)
  that `scheduler.py publish-instagram` builds each image's public URL from
  (`GITHUB_RAW_BASE_URL` + `/` + the post's `image_path`), since Instagram's
  Graph API needs a publicly reachable `image_url` rather than accepting a
  file upload. Only works because `archive/images/`/`archive/posts.json` are
  checked into this (public) repo — see Data model above.
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

This repo covers Phase 1 (archive), Phase 2 (scheduled posting, including
`selector.py`'s rotation logic), and Instagram cross-posting
(`instagram_poster_api.py` / `scheduler.py publish-instagram`) — photo posts
only, published same-day rather than scheduled ahead (see
`instagram_poster_api.py` above for why). Do not add Instagram Stories/Reels,
Instagram-only content (not also posted to Facebook), or paid
promotion/boosting (Marketing API) — those remain out of scope unless
explicitly asked for.
