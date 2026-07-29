"""
Emails a summary of newly scheduled posts to MY_EMAIL_ADDRESS, called from
scheduler.py's `schedule` command after each run. Uses smtplib (stdlib) —
no new dependency, and consistent with the rest of the project's plain
requests/no-SDK style.

Preview links use the standard Facebook permalink format,
https://www.facebook.com/{page-id}/posts/{post-id} — Page admins can open
this for a scheduled/unpublished post and see it with a "Scheduled" preview
banner. This isn't a formally documented Graph API feature, just the
standard permalink shape, so treat the link as best-effort.
"""
import os
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage

REQUIRED_ENV_VARS = ("MY_EMAIL_ADDRESS", "SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD")


def _preview_url(page_id: str, item_type: str, result: dict) -> str | None:
    if item_type == "video":
        post_id = result.get("post_id")
        video_id = result.get("video_id")
        if post_id:
            suffix = post_id.split("_", 1)[-1]
            return f"https://www.facebook.com/{page_id}/posts/{suffix}"
        return f"https://www.facebook.com/{page_id}/videos/{video_id}" if video_id else None

    post_id = result.get("id")
    if not post_id:
        return None
    suffix = post_id.split("_", 1)[-1]
    return f"https://www.facebook.com/{page_id}/posts/{suffix}"


def build_summary(page_id: str, scheduled_items: list[dict]) -> str:
    lines = [f"{len(scheduled_items)} post(s) newly scheduled:", ""]
    for entry in scheduled_items:
        when = datetime.fromtimestamp(entry["scheduled_ts"], tz=timezone.utc).isoformat()
        lines.append(f"- {entry['id']}  [{entry['type']}]  {when}")
        lines.append(f"  {entry['message'][:200]!r}")
        url = _preview_url(page_id, entry["type"], entry["result"])
        lines.append(f"  preview: {url or '(not available)'}")
        lines.append("")
    return "\n".join(lines)


def send_schedule_summary(page_id: str, scheduled_items: list[dict]) -> None:
    """Best-effort: never raises. Skips quietly if SMTP/recipient env vars
    aren't set, since the email summary is a convenience, not something that
    should block or fail a schedule run."""
    if not scheduled_items:
        return

    env = {name: os.getenv(name) for name in REQUIRED_ENV_VARS}
    missing = [name for name, value in env.items() if not value]
    if missing:
        print(f"  (skipping email summary — missing env vars: {', '.join(missing)})")
        return

    sender = os.getenv("SMTP_FROM", env["SMTP_USERNAME"])
    msg = EmailMessage()
    msg["Subject"] = f"Memories Fond: {len(scheduled_items)} post(s) newly scheduled"
    msg["From"] = sender
    msg["To"] = env["MY_EMAIL_ADDRESS"]
    msg.set_content(build_summary(page_id, scheduled_items))

    try:
        with smtplib.SMTP(env["SMTP_HOST"], int(env["SMTP_PORT"])) as smtp:
            smtp.starttls()
            smtp.login(env["SMTP_USERNAME"], env["SMTP_PASSWORD"])
            smtp.send_message(msg)
        print(f"  Email summary sent to {env['MY_EMAIL_ADDRESS']}.")
    except Exception as e:
        print(f"  Warning: failed to send email summary: {e}")
