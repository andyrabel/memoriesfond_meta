"""
Thin wrapper around the Facebook Graph API v21.0 — read-only for Phase 1
(archiving existing posts). No posting/scheduling logic lives here; that's
Phase 2's job.
"""
import time

import requests

GRAPH_URL = "https://graph.facebook.com/v21.0"

POST_FIELDS = "id,message,created_time,permalink_url,attachments{media_type,type,url,media,subattachments}"

MAX_RETRIES = 5
RETRY_BACKOFF_SECONDS = 5

# Graph API error codes/subcodes that indicate a transient rate limit
# (https://developers.facebook.com/docs/graph-api/guides/error-handling/)
RATE_LIMIT_CODES = {4, 17, 32, 613}


class FacebookAPIError(Exception):
    pass


class FacebookAPI:
    def __init__(self, page_id: str, page_token: str):
        self.page_id = page_id
        self.page_token = page_token

    def _handle_errors(self, body: dict) -> bool:
        """Returns True if this error is a rate limit worth retrying."""
        if "error" in body:
            err = body["error"]
            parts = [err.get("message", str(err))]
            if err.get("error_subcode"):
                parts.append(f"subcode={err['error_subcode']}")
            if err.get("fbtrace_id"):
                parts.append(f"trace={err['fbtrace_id']}")
            msg = " | ".join(parts)
            if err.get("code") in RATE_LIMIT_CODES:
                return True
            raise FacebookAPIError(msg)
        return False

    def _get(self, url: str, params: dict | None = None) -> dict:
        """GET with basic exponential backoff on rate-limit errors. `url` may
        be a bare endpoint (joined to GRAPH_URL) or a full `paging.next` URL
        that already carries its own query string and access_token."""
        full_url = url if url.startswith("http") else f"{GRAPH_URL}/{url}"
        params = {**(params or {})}
        if "access_token" not in full_url:
            params.setdefault("access_token", self.page_token)

        delay = RETRY_BACKOFF_SECONDS
        for attempt in range(MAX_RETRIES):
            resp = requests.get(full_url, params=params)
            body = resp.json()
            if self._handle_errors(body):
                if attempt == MAX_RETRIES - 1:
                    raise FacebookAPIError(f"Rate limited after {MAX_RETRIES} attempts: {body}")
                time.sleep(delay)
                delay *= 2
                continue
            return body
        raise FacebookAPIError("unreachable")

    def get_posts_page(self, params: dict) -> dict:
        """Fetch one page of /{page-id}/posts."""
        return self._get(f"{self.page_id}/posts", params)

    def get_next_page(self, next_url: str) -> dict:
        """Follow a `paging.next` cursor URL from a previous response."""
        return self._get(next_url)

    def download_image(self, url: str) -> bytes:
        """Fetch raw image bytes from a (signed, time-limited) Facebook CDN URL."""
        delay = RETRY_BACKOFF_SECONDS
        for attempt in range(MAX_RETRIES):
            resp = requests.get(url)
            if resp.status_code == 200:
                return resp.content
            if resp.status_code in (429, 500, 502, 503) and attempt < MAX_RETRIES - 1:
                time.sleep(delay)
                delay *= 2
                continue
            resp.raise_for_status()
        raise FacebookAPIError(f"Failed to download image from {url}")
