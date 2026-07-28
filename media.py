"""
Local media cache, Wikimedia Commons license verification, and video assembly
for video posts. Media is cached to a stable, gitignored directory keyed by
id so re-runs don't re-download or re-render.
"""
import hashlib
import subprocess
from pathlib import Path

import imageio_ffmpeg
import requests
from PIL import Image, ImageDraw, ImageFont

CACHE_DIR = Path(__file__).parent / "media_cache"

VIDEO_WIDTH = 1280

# Wikimedia Commons extmetadata.LicenseShortName values that are unambiguously
# public-domain or explicitly permissive. Anything not in this list is gated
# out entirely rather than posted, per CLAUDE.md's licensing requirement.
ALLOWED_COMMONS_LICENSES = {
    "public domain", "pd", "cc0",
    "cc-by-2.0", "cc-by-3.0", "cc-by-4.0",
    "cc-by-sa-2.0", "cc-by-sa-3.0", "cc-by-sa-4.0",
}


def cache_path(key: str, suffix: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    return CACHE_DIR / f"{digest}{suffix}"


def fetch_cached(url: str, key: str, suffix: str) -> Path:
    path = cache_path(key, suffix)
    if path.exists():
        return path
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    path.write_bytes(resp.content)
    return path


def verify_commons_license(file_title: str) -> tuple[bool, str]:
    """Checks a Wikimedia Commons file's extmetadata.LicenseShortName against
    ALLOWED_COMMONS_LICENSES. Returns (ok, license_name) — never trust a search
    result's claimed license, verify it programmatically here instead."""
    resp = requests.get(
        "https://commons.wikimedia.org/w/api.php",
        params={
            "action": "query",
            "titles": file_title,
            "prop": "imageinfo",
            "iiprop": "extmetadata",
            "format": "json",
        },
        timeout=15,
    )
    resp.raise_for_status()
    pages = resp.json().get("query", {}).get("pages", {})
    for page in pages.values():
        imageinfo = page.get("imageinfo") or []
        if not imageinfo:
            continue
        license_name = imageinfo[0].get("extmetadata", {}).get("LicenseShortName", {}).get("value", "")
        return license_name.strip().lower() in ALLOWED_COMMONS_LICENSES, license_name
    return False, ""


def downscale_image(image_path: Path, max_width: int = VIDEO_WIDTH) -> Path:
    """ffmpeg re-decodes a looped image every output frame, so an oversized
    source image tanks encode speed — shrink it before it ever reaches ffmpeg."""
    with Image.open(image_path) as img:
        if img.width <= max_width:
            return image_path
        ratio = max_width / img.width
        resized = img.resize((max_width, int(img.height * ratio)))
        out_path = image_path.with_stem(image_path.stem + "_scaled")
        resized.save(out_path)
        return out_path


def burn_in_caption(image_path: Path, caption: str, credit_text: str | None, out_path: Path) -> Path:
    """Burns caption/credit text into the frame via PIL before ffmpeg touches
    it — bundled ffmpeg builds often lack drawtext support."""
    with Image.open(image_path).convert("RGB") as img:
        draw = ImageDraw.Draw(img)
        font = ImageFont.load_default()
        lines = [line for line in (caption, credit_text) if line]
        line_height = 20
        y = img.height - line_height * len(lines) - 10
        for line in lines:
            draw.text((10, y), line, fill="white", font=font)
            y += line_height
        img.save(out_path)
    return out_path


def build_video(frame_path: Path, audio_path: Path, out_path: Path) -> Path:
    """Builds a video from a static image + audio track using imageio_ffmpeg's
    bundled binary — no system ffmpeg install required."""
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    scaled_frame = downscale_image(frame_path)
    cmd = [
        ffmpeg_exe, "-y",
        "-loop", "1", "-i", str(scaled_frame),
        "-i", str(audio_path),
        "-vf", f"scale={VIDEO_WIDTH}:-2",
        "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path
