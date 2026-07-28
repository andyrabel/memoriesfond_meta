"""
One-off / occasional utility: exchanges a short-lived User Access Token
(copied from the Graph API Explorer, with pages_show_list, pages_read_engagement,
and pages_manage_posts granted) for a long-lived Page Access Token, and writes
it directly into .env's FB_PAGE_TOKEN.

Needs FB_APP_ID, FB_APP_SECRET, and FB_PAGE_ID in .env. FB_APP_ID/FB_APP_SECRET
are only used here — never read by backfill.py or scheduler.py at runtime.

Usage:
  python get_long_lived_token.py <short-lived-user-token>
"""
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

GRAPH_URL = "https://graph.facebook.com/v21.0"
ENV_FILE = Path(__file__).parent / ".env"


def require_env(*names: str):
    missing = [n for n in names if not os.getenv(n)]
    if missing:
        print(f"Error: missing environment variables: {', '.join(missing)}")
        print("Add them to .env (FB_APP_ID and FB_APP_SECRET are on the "
              "Meta App Dashboard's Settings > Basic page).")
        sys.exit(1)


def _get(endpoint: str, params: dict) -> dict:
    resp = requests.get(f"{GRAPH_URL}/{endpoint}", params=params)
    body = resp.json()
    if "error" in body:
        raise RuntimeError(body["error"].get("message", str(body["error"])))
    return body


def exchange_for_long_lived_user_token(app_id: str, app_secret: str, short_lived_token: str) -> str:
    body = _get("oauth/access_token", {
        "grant_type": "fb_exchange_token",
        "client_id": app_id,
        "client_secret": app_secret,
        "fb_exchange_token": short_lived_token,
    })
    return body["access_token"]


def get_page_token(long_lived_user_token: str, page_id: str) -> str:
    body = _get("me/accounts", {"access_token": long_lived_user_token})
    for page in body.get("data", []):
        if page["id"] == page_id:
            return page["access_token"]
    raise RuntimeError(f"Page {page_id} not found in /me/accounts — is this user an admin of that Page?")


def update_env_file(new_token: str):
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if line.startswith("FB_PAGE_TOKEN="):
            lines[i] = f"FB_PAGE_TOKEN={new_token}"
            break
    else:
        lines.append(f"FB_PAGE_TOKEN={new_token}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    if len(sys.argv) != 2:
        print("Usage: python get_long_lived_token.py <short-lived-user-token>")
        sys.exit(1)

    require_env("FB_APP_ID", "FB_APP_SECRET", "FB_PAGE_ID")
    short_lived_token = sys.argv[1]

    print("Exchanging for a long-lived user token...")
    long_lived_user_token = exchange_for_long_lived_user_token(
        os.environ["FB_APP_ID"], os.environ["FB_APP_SECRET"], short_lived_token,
    )

    print("Fetching the long-lived Page token...")
    page_token = get_page_token(long_lived_user_token, os.environ["FB_PAGE_ID"])

    update_env_file(page_token)
    print(f"Done — FB_PAGE_TOKEN updated in .env (new token length: {len(page_token)}).")


if __name__ == "__main__":
    main()
