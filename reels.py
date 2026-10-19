"""
Cuts short 9:16 promo reels out of the animated "Seasons with Dad" read-aloud
(archive/video/, gitignored — the source is over GitHub's 100MB file limit)
and queues them as occasional video posts for Facebook + Instagram Reels.

The source is ~2.04:1 (2204x1080), so a 9:16 window keeps barely a quarter
of the width. Rather than one fixed centre crop, each scene has its own crop
keyframes (fraction of source width the window is centred on), eased between
— a slow pan from one character to the other, the way the page would be read.

Usage:
  python reels.py preview              # contact sheets with crop boxes drawn on (media_cache/reel_preview/)
  python reels.py build                # render every reel to archive/reels/{id}.mp4
  python reels.py build --only sw-autumn-1
  python reels.py queue --dry-run      # show what would be appended to scheduled/queue.json
  python reels.py queue                # append reels + claim their days in planned_days.json

archive/reels/*.mp4 are checked in (see .gitignore) for the same reason
archive/images/ is: Instagram's Graph API needs a publicly reachable
video_url, served from raw.githubusercontent.com. Commit and push a reel
before its date arrives or publish-instagram will fail to fetch it.
"""
import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw

import selector

BASE_DIR = Path(__file__).parent
SOURCE_VIDEO = BASE_DIR / "archive" / "video" / "Seasons with Dad Animaed v1 - No Subtitles.mp4"
REELS_DIR = BASE_DIR / "archive" / "reels"
PREVIEW_DIR = BASE_DIR / "media_cache" / "reel_preview"

SRC_W, SRC_H = 2204, 1080
OUT_W, OUT_H = 1080, 1920
# Source upscaled to the output height *before* cropping, so a slow pan moves
# in whole output pixels rather than 1.78px jumps.
SCALED_W = round(SRC_W * OUT_H / SRC_H / 2) * 2

# The cover/title card (0:00-0:04.8, narrated title + credits) closes every
# reel. Its title text is far wider than a 9:16 crop, so it's shown whole,
# letterboxed over a blurred fill of itself.
END_CARD = (0.0, 4.9)

TAGS = "#SeasonsWithDad #ChildrensBooks #ReadAloud #PictureBook #MemoriesFond"
LINK = "https://mybook.to/SeasonsWithDad"

# Each reel: source in/out (cut on narration pauses, not scene cuts — the
# verse often runs across a scene change) and crop keyframes as
# (source_time, centre_fraction). Two keyframes at a scene cut make the window
# jump with the cut rather than drift across it.
REELS = [
    {
        "id": "sw-reel-spring",
        "date": "2027-03-21",
        "start": 5.65, "end": 29.45,
        "keys": [(5.5, 0.27), (7.0, 0.32), (8.5, 0.45), (12.0, 0.45), (13.5, 0.36), (17.69, 0.55),
                 (17.7, 0.26), (22.0, 0.28), (29.5, 0.55)],
        "message": "🌼 Spring with Dad — racing through the bluebell woods and watching the narrowboats drift along the canal. A little moment from the animated read-aloud of \"Seasons with Dad\" by Andrew Abel, illustrated by Graeme Holding.\n\n" + LINK + "\n\n#SpringWalk " + TAGS,
    },
    {
        "id": "sw-reel-summer-1",
        "date": "2027-06-05",
        "start": 29.45, "end": 53.07,
        "keys": [(29.5, 0.30), (31.5, 0.30), (34.5, 0.72), (37.0, 0.72), (41.29, 0.40),
                 (41.3, 0.25), (44.0, 0.35), (47.5, 0.45), (49.5, 0.45), (53.1, 0.68)],
        "message": "🚂 Waving at the steam train from the bridge, then a picnic up by the old castle — summer days from \"Seasons with Dad,\" now as an animated read-aloud.\n\n" + LINK + "\n\n#SummerVibes " + TAGS,
    },
    {
        "id": "sw-reel-summer-2",
        "date": "2027-07-17",
        "start": 53.07, "end": 82.4,
        "keys": [(53.0, 0.70), (55.26, 0.70),
                 (55.27, 0.45), (59.5, 0.48), (63.0, 0.62), (64.79, 0.65),
                 (64.8, 0.43), (68.56, 0.43),
                 (68.57, 0.12), (75.0, 0.12), (82.4, 0.62)],
        "message": "🍦 Ice cream by the sea wall, donkey rides on the sand, and a hedgehog visitor by torchlight 🦔 Summer from \"Seasons with Dad,\" animated.\n\n" + LINK + "\n\n#Seaside " + TAGS,
    },
    {
        "id": "sw-reel-autumn-1",
        "date": "2026-10-24",
        "start": 82.5, "end": 107.4,
        "keys": [(82.5, 0.27), (94.72, 0.40),
                 (94.73, 0.25), (107.4, 0.52)],
        "message": "🎣 Bait on the line with Dad, then feeding the ducks at the village pond 🦆 Autumn from the animated read-aloud of \"Seasons with Dad.\"\n\n" + LINK + "\n\n#AutumnVibes " + TAGS,
    },
    {
        "id": "sw-reel-autumn-2",
        "date": "2026-11-03",
        "start": 107.4, "end": 141.1,
        "keys": [(107.4, 0.45), (107.62, 0.45),
                 (107.63, 0.27), (114.5, 0.27), (117.5, 0.75), (118.76, 0.75),
                 (118.77, 0.20), (126.0, 0.20), (130.0, 0.75), (131.32, 0.75),
                 (131.33, 0.68), (141.1, 0.68)],
        "message": "🍂 One big pile of leaves to jump in, then bonfire night with fireworks and cinder toffee 🎆 Autumn into winter, from the animated read-aloud of \"Seasons with Dad.\"\n\n" + LINK + "\n\n#BonfireNight " + TAGS,
    },
    {
        "id": "sw-reel-winter",
        "date": "2026-12-11",
        "start": 141.1, "end": 163.7,
        "keys": [(141.1, 0.65), (142.76, 0.65),
                 (142.77, 0.20), (153.66, 0.36),
                 (153.67, 0.40), (163.7, 0.46)],
        "message": "❄️ Sledging down the hill, a Christmas full of family stories, and games on the blanket with Dad 🎄 The last pages of the animated \"Seasons with Dad.\"\n\n" + LINK + "\n\n#WinterFun #Christmas " + TAGS,
    },
]


def crop_centre(keys: list[tuple[float, float]], t: float) -> float:
    """Python twin of _crop_x_expr(), used to draw the preview boxes."""
    if t <= keys[0][0]:
        return keys[0][1]
    for (t0, c0), (t1, c1) in zip(keys, keys[1:]):
        if t < t1:
            u = (t - t0) / (t1 - t0)
            return c0 + (c1 - c0) * u * u * (3 - 2 * u)
    return keys[-1][1]


def _crop_x_expr(keys: list[tuple[float, float]], start: float) -> str:
    """ffmpeg expression for the crop window's left edge, in scaled-source
    pixels. Smoothstep-eased between keyframes; `t` restarts at 0 because of
    the input-side -ss, hence the +start."""
    T = f"(t+{start})"

    def px(c):
        return f"({c}*{SCALED_W}-{OUT_W / 2})"

    expr = px(keys[-1][1])
    for (t0, c0), (t1, c1) in reversed(list(zip(keys, keys[1:]))):
        u = f"(({T}-{t0})/{t1 - t0})"
        seg = f"({px(c0)}+({px(c1)}-{px(c0)})*{u}*{u}*(3-2*{u}))"
        expr = f"if(lt({T},{t1}),{seg},{expr})"
    expr = f"if(lt({T},{keys[0][0]}),{px(keys[0][1])},{expr})"
    return f"max(0,min({SCALED_W - OUT_W},{expr}))"


def build_reel(reel: dict) -> Path:
    if not SOURCE_VIDEO.exists():
        sys.exit(f"Source video not found: {SOURCE_VIDEO}")
    REELS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REELS_DIR / f"{reel['id']}.mp4"

    dur = reel["end"] - reel["start"]
    card_dur = END_CARD[1] - END_CARD[0]
    x_expr = _crop_x_expr(reel["keys"], reel["start"])
    filtergraph = (
        f"[0:v]scale={SCALED_W}:{OUT_H}:flags=lanczos,crop={OUT_W}:{OUT_H}:x='{x_expr}':y=0,"
        f"setsar=1,fps=30,format=yuv420p[main];"
        f"[0:a]afade=t=in:d=0.15,afade=t=out:st={dur - 0.35:.2f}:d=0.35[maina];"
        f"[1:v]split[c1][c2];"
        f"[c2]scale={SCALED_W}:{OUT_H},crop={OUT_W}:{OUT_H},boxblur=30:2,eq=brightness=-0.08[bg];"
        f"[c1]scale={OUT_W}:-2:flags=lanczos[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,fps=30,format=yuv420p,"
        f"fade=t=in:d=0.3,fade=t=out:st={card_dur - 0.4:.2f}:d=0.4[card];"
        f"[1:a]afade=t=in:d=0.2,afade=t=out:st={card_dur - 0.4:.2f}:d=0.4[carda];"
        f"[main][maina][card][carda]concat=n=2:v=1:a=1[v][a]"
    )
    cmd = [
        imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
        "-ss", str(reel["start"]), "-t", f"{dur:.3f}", "-i", str(SOURCE_VIDEO),
        "-ss", str(END_CARD[0]), "-t", f"{card_dur:.3f}", "-i", str(SOURCE_VIDEO),
        "-filter_complex", filtergraph, "-map", "[v]", "-map", "[a]",
        # Instagram Reels: H.264 + AAC, moov atom up front, <=25Mbps.
        "-c:v", "libx264", "-preset", "slow", "-crf", "21", "-maxrate", "8M", "-bufsize", "16M",
        "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart",
        str(out_path),
    ]
    subprocess.run(cmd, check=True)
    return out_path


def cmd_build(args):
    for reel in REELS:
        if args.only and reel["id"] not in args.only:
            continue
        out = build_reel(reel)
        print(f"  {reel['id']}  -> {out.relative_to(BASE_DIR)}  ({out.stat().st_size / 1e6:.1f} MB)")


def cmd_preview(_args):
    """One contact sheet per reel: a source frame every 1.5s with the crop
    window outlined, for checking keyframes without rendering anything."""
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    thumb_w = 400
    thumb_h = round(thumb_w * SRC_H / SRC_W)
    box_w = thumb_w * (OUT_W / SCALED_W)
    for reel in REELS:
        times = []
        t = reel["start"] + 0.2
        while t < reel["end"]:
            times.append(t)
            t += 1.5
        thumbs = []
        for t in times:
            frame = PREVIEW_DIR / "frame.jpg"
            subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(SOURCE_VIDEO),
                            "-frames:v", "1", "-vf", f"scale={thumb_w}:{thumb_h}", str(frame)], check=True)
            im = Image.open(frame).convert("RGB")
            left = crop_centre(reel["keys"], t) * thumb_w - box_w / 2
            left = max(0, min(thumb_w - box_w, left))
            draw = ImageDraw.Draw(im)
            draw.rectangle([left, 0, left + box_w, thumb_h - 1], outline="red", width=3)
            draw.rectangle([0, 0, 52, 16], fill="black")
            draw.text((3, 2), f"{int(t // 60)}:{t % 60:04.1f}", fill="yellow")
            thumbs.append(im)
        cols = 5
        rows = (len(thumbs) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * thumb_w, rows * thumb_h), "black")
        for i, im in enumerate(thumbs):
            sheet.paste(im, ((i % cols) * thumb_w, (i // cols) * thumb_h))
        out = PREVIEW_DIR / f"{reel['id']}.jpg"
        sheet.save(out, quality=85)
        print(f"  {out}")


def _queue_item(reel: dict) -> dict:
    d = date.fromisoformat(reel["date"])
    return {
        "id": reel["id"],
        "type": "video",
        "scheduled_publish_time": selector._scheduled_datetime(d).isoformat(),
        "message": reel["message"],
        "source_facts": {
            "book": "Seasons with Dad",
            "clip": f"animated read-aloud, {reel['start']:.1f}s-{reel['end']:.1f}s",
        },
        "video_path": f"archive/reels/{reel['id']}.mp4",
        # Posted to Instagram as a Reel by publish-instagram (see
        # instagram_poster_api.create_reel_post) — always 9:16 by construction.
        "ig_eligible": True,
    }


def cmd_queue(args):
    queue_path = Path(args.queue_out)
    queue = json.loads(queue_path.read_text(encoding="utf-8")) if queue_path.exists() else []
    queued_ids = {item["id"] for item in queue}
    planned = selector.load_planned_days()

    new_items = []
    for reel in REELS:
        if reel["id"] in queued_ids:
            print(f"  {reel['id']}  already queued — skipping")
            continue
        if not (BASE_DIR / "archive" / "reels" / f"{reel['id']}.mp4").exists():
            print(f"  {reel['id']}  not built yet — run `python reels.py build` first, skipping")
            continue
        day = reel["date"]
        if day in planned and planned[day] != reel["id"]:
            print(f"  {reel['id']}  {day} is already taken by {planned[day]} — pick another date, skipping")
            continue
        planned[day] = reel["id"]
        new_items.append(_queue_item(reel))
        print(f"  {reel['id']}  -> {day}")

    if args.dry_run or not new_items:
        print(f"\n{len(new_items)} reel(s) would be queued (dry run)." if args.dry_run else "\nNothing new to queue.")
        return

    queue.extend(new_items)
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    queue_path.write_text(json.dumps(queue, indent=2, ensure_ascii=False), encoding="utf-8")
    # Claiming the day keeps selector.py's photo rotation off it ("never more
    # than one post per day").
    selector.save_planned_days(planned)
    print(f"\n{len(new_items)} reel(s) appended to {queue_path}.")


def main():
    parser = argparse.ArgumentParser(description="Cut and queue 'Seasons with Dad' promo reels")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("preview", help="Contact sheets with crop boxes drawn on")
    build = sub.add_parser("build", help="Render reels to archive/reels/")
    build.add_argument("--only", nargs="+", help="Reel id(s) to build (default: all)")
    queue = sub.add_parser("queue", help="Append built reels to the scheduler queue")
    queue.add_argument("--queue-out", default=str(selector.SCHEDULED_DIR / "queue.json"))
    queue.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()
    if args.command == "preview":
        cmd_preview(args)
    elif args.command == "build":
        cmd_build(args)
    elif args.command == "queue":
        cmd_queue(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
