"""
Thin wrapper around the Instagram Graph API v21.0 — posting only. Parallel to
poster_api.py (Facebook's posting client) but a genuinely different API shape:
Instagram publishing is a two-step container flow (create a media container,
poll until Instagram finishes processing it, then publish the container) and
it requires a publicly reachable image_url rather than a raw file upload —
there is no equivalent of poster_api.py's multipart /photos upload.

There is also no Instagram equivalent of scheduled_publish_time for content
publishing: a container can be created ahead of time, but media_publish posts
it live immediately. Callers are responsible for only publishing when the
post is actually due (see scheduler.py's `publish-instagram` command).
"""
import time

import requests
from PIL import Image

GRAPH_URL = "https://graph.facebook.com/v21.0"

MAX_RETRIES = 5
RETRY_BACKOFF_SECONDS = 5

CONTAINER_POLL_ATTEMPTS = 10
CONTAINER_POLL_DELAY_SECONDS = 3

# Instagram feed images must fall within this aspect ratio (width/height) band
# — anything outside it is rejected at container-creation time.
MIN_ASPECT_RATIO = 4 / 5
MAX_ASPECT_RATIO = 1.91

# Instagram caption limit; truncate defensively rather than let the API reject
# an otherwise-fine post over a caption that's grown too long.
MAX_CAPTION_LENGTH = 2200


class InstagramPosterError(Exception):
    def __init__(self, message, code=None, error_subcode=None, fbtrace_id=None):
        parts = [message]
        if error_subcode:
            parts.append(f"subcode={error_subcode}")
        if fbtrace_id:
            parts.append(f"trace={fbtrace_id}")
        super().__init__(" | ".join(parts))
        self.code = code
        self.error_subcode = error_subcode
        self.fbtrace_id = fbtrace_id


class ContainerProcessingError(InstagramPosterError):
    pass


def _raise_for_error(body: dict):
    err = body.get("error")
    if not err:
        return
    raise InstagramPosterError(
        err.get("message", str(err)), err.get("code"), err.get("error_subcode"), err.get("fbtrace_id"),
    )


def is_aspect_ratio_ok(image_path: str) -> bool:
    """Checks a local image against Instagram's allowed feed aspect-ratio
    band (4:5 to 1.91:1) before ever attempting to post it."""
    with Image.open(image_path) as im:
        ratio = im.width / im.height
    return MIN_ASPECT_RATIO - 1e-6 <= ratio <= MAX_ASPECT_RATIO + 1e-6


class InstagramPoster:
    def __init__(self, ig_user_id: str, page_token: str):
        self.ig_user_id = ig_user_id
        self.page_token = page_token

    def _request(self, method: str, endpoint: str, data: dict | None = None) -> dict:
        url = f"{GRAPH_URL}/{endpoint}"
        params = {**(data or {}), "access_token": self.page_token}

        delay = RETRY_BACKOFF_SECONDS
        for attempt in range(MAX_RETRIES):
            resp = requests.get(url, params=params) if method == "GET" else requests.post(url, data=params)
            body = resp.json()
            if "error" in body and body["error"].get("code") in (4, 17, 32, 613):
                if attempt == MAX_RETRIES - 1:
                    raise InstagramPosterError(f"Rate limited after {MAX_RETRIES} attempts: {body}")
                time.sleep(delay)
                delay *= 2
                continue
            _raise_for_error(body)
            return body
        raise InstagramPosterError("unreachable")

    def create_media_container(self, image_url: str, caption: str) -> str:
        """POST /{ig-user-id}/media with image_url + caption. Returns the
        container (creation) id; the container isn't live until published."""
        body = self._request("POST", f"{self.ig_user_id}/media", {
            "image_url": image_url,
            "caption": caption[:MAX_CAPTION_LENGTH],
        })
        return body["id"]

    def wait_for_container_ready(self, creation_id: str, attempts: int = CONTAINER_POLL_ATTEMPTS,
                                  delay: int = CONTAINER_POLL_DELAY_SECONDS):
        """Polls GET /{creation_id}?fields=status_code until Instagram finishes
        downloading/processing the image (FINISHED) or reports an error."""
        for attempt in range(attempts):
            body = self._request("GET", creation_id, {"fields": "status_code"})
            status = body.get("status_code")
            if status == "FINISHED":
                return
            if status == "ERROR":
                raise ContainerProcessingError(f"container {creation_id} failed processing: {body}")
            if attempt < attempts - 1:
                time.sleep(delay)
        raise ContainerProcessingError(f"container {creation_id} did not finish processing in time")

    def publish_container(self, creation_id: str) -> str:
        """POST /{ig-user-id}/media_publish with the creation_id. Returns the
        published Instagram media id."""
        body = self._request("POST", f"{self.ig_user_id}/media_publish", {"creation_id": creation_id})
        return body["id"]

    def get_permalink(self, media_id: str) -> str | None:
        body = self._request("GET", media_id, {"fields": "permalink"})
        return body.get("permalink")

    def create_photo_post(self, image_url: str, caption: str) -> dict:
        """Full container -> poll -> publish flow. Publishes immediately —
        there is no scheduled_publish_time equivalent for Instagram."""
        creation_id = self.create_media_container(image_url, caption)
        self.wait_for_container_ready(creation_id)
        media_id = self.publish_container(creation_id)
        permalink = self.get_permalink(media_id)
        return {"id": media_id, "creation_id": creation_id, "permalink": permalink}
