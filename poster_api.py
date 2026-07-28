"""
Thin wrapper around the Facebook Graph API v21.0 — posting only. Kept separate
from facebook_api.py (Phase 1's read-only client): different credentials
scope (pages_manage_posts vs pages_read_engagement), different failure modes,
and no reason for the archiver to depend on posting code or vice versa.
"""
import json
import time

import requests

GRAPH_URL = "https://graph.facebook.com/v21.0"

MAX_RETRIES = 5
RETRY_BACKOFF_SECONDS = 5

VIDEO_POST_ID_POLL_ATTEMPTS = 5
VIDEO_POST_ID_POLL_DELAY_SECONDS = 3

# Graph error codes that commonly mean FB_PAGE_TOKEN is a User token rather
# than a Page token — these read like generic auth failures but aren't.
WRONG_TOKEN_TYPE_CODES = {100, 200}


class FacebookPosterError(Exception):
    def __init__(self, message, code=None, error_subcode=None, error_user_msg=None, fbtrace_id=None):
        parts = [message]
        if error_subcode:
            parts.append(f"subcode={error_subcode}")
        if fbtrace_id:
            parts.append(f"trace={fbtrace_id}")
        super().__init__(" | ".join(parts))
        self.code = code
        self.error_subcode = error_subcode
        self.error_user_msg = error_user_msg
        self.fbtrace_id = fbtrace_id


class ScheduleTooFarError(FacebookPosterError):
    pass


class WrongTokenTypeError(FacebookPosterError):
    pass


def _raise_for_error(body: dict):
    err = body.get("error")
    if not err:
        return
    message = err.get("message", str(err))
    code = err.get("code")
    subcode = err.get("error_subcode")
    user_msg = err.get("error_user_msg")
    trace = err.get("fbtrace_id")
    haystack = f"{message} {user_msg or ''}".lower()

    if "scheduled" in haystack and ("publish time" in haystack or "publish_time" in haystack):
        raise ScheduleTooFarError(message, code, subcode, user_msg, trace)
    if code in WRONG_TOKEN_TYPE_CODES:
        raise WrongTokenTypeError(
            f"{message} (Graph error code {code} often means FB_PAGE_TOKEN is a User token, "
            "not a Page token — it needs to be a Page Access Token scoped to "
            "pages_manage_posts + pages_read_engagement)",
            code, subcode, user_msg, trace,
        )
    raise FacebookPosterError(message, code, subcode, user_msg, trace)


class FacebookPoster:
    def __init__(self, page_id: str, page_token: str):
        self.page_id = page_id
        self.page_token = page_token

    def _request(self, method: str, endpoint: str, data: dict | None = None, files: dict | None = None) -> dict:
        url = f"{GRAPH_URL}/{endpoint}"
        data = {**(data or {}), "access_token": self.page_token}

        delay = RETRY_BACKOFF_SECONDS
        for attempt in range(MAX_RETRIES):
            if method == "GET":
                resp = requests.get(url, params=data)
            else:
                resp = requests.post(url, data=data, files=files)
            body = resp.json()
            if "error" in body and body["error"].get("code") in (4, 17, 32, 613):
                if attempt == MAX_RETRIES - 1:
                    raise FacebookPosterError(f"Rate limited after {MAX_RETRIES} attempts: {body}")
                time.sleep(delay)
                delay *= 2
                continue
            _raise_for_error(body)
            return body
        raise FacebookPosterError("unreachable")

    def _get(self, endpoint: str, params: dict) -> dict:
        return self._request("GET", endpoint, data=params)

    def _post(self, endpoint: str, data: dict, files: dict | None = None) -> dict:
        return self._request("POST", endpoint, data=data, files=files)

    def create_text_post(self, message: str, scheduled_publish_time: int) -> dict:
        """POST /{page-id}/feed with scheduled_publish_time and published=false."""
        return self._post(f"{self.page_id}/feed", {
            "message": message,
            "scheduled_publish_time": int(scheduled_publish_time),
            "published": "false",
        })

    def upload_unpublished_photo(self, image_path: str) -> dict:
        """POST /{page-id}/photos with published=false, no_story=true — stashes the
        image and returns a photo id, without creating a visible story or post."""
        with open(image_path, "rb") as f:
            return self._post(f"{self.page_id}/photos", {
                "published": "false",
                "no_story": "true",
            }, files={"source": f})

    def create_photo_post(self, photo_id: str, message: str, scheduled_publish_time: int) -> dict:
        """POST /{page-id}/feed referencing a stashed photo id via attached_media.
        Everything routes through /feed (rather than scheduling directly on
        /photos) so Business Suite Planner reports the correct created_time."""
        return self._post(f"{self.page_id}/feed", {
            "message": message,
            "attached_media[0]": json.dumps({"media_fbid": photo_id}),
            "scheduled_publish_time": int(scheduled_publish_time),
            "published": "false",
        })

    def create_video_post(self, video_path: str, message: str, scheduled_publish_time: int) -> dict:
        """POST /{page-id}/videos with scheduled_publish_time directly, then poll
        for the combined {page_id}_{story_id} post id (it can lag behind creation)."""
        with open(video_path, "rb") as f:
            body = self._post(f"{self.page_id}/videos", {
                "description": message,
                "scheduled_publish_time": int(scheduled_publish_time),
                "published": "false",
            }, files={"source": f})

        video_id = body["id"]
        post_id = self._poll_video_post_id(video_id)
        return {"video_id": video_id, "post_id": post_id}

    def _poll_video_post_id(self, video_id: str, attempts: int = VIDEO_POST_ID_POLL_ATTEMPTS,
                             delay: int = VIDEO_POST_ID_POLL_DELAY_SECONDS) -> str | None:
        for attempt in range(attempts):
            body = self._get(str(video_id), {"fields": "post_id"})
            if body.get("post_id"):
                return body["post_id"]
            if attempt < attempts - 1:
                time.sleep(delay)
        return None
