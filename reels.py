"""
Cuts short 9:16 promo reels out of the animated picture-book read-alouds
("Seasons with Dad", "Finding Granny", "Adopt a Dinosaur" — archive/video/,
gitignored since the sources run over GitHub's 100MB file limit) and queues
them as occasional video posts for Facebook + Instagram Reels.

The sources are landscape (2.04:1 and 16:9), so a 9:16 window keeps only a
quarter to a third of the width. "Adopt a Dinosaur" also has its subtitles
burned in, so its picture is cropped above them and the lines re-set as
reel captions. Rather than one fixed centre crop, each
scene has its own crop keyframes (fraction of source width the window is
centred on), eased between — a slow pan from one character to the other, the
way the page would be read.

Usage:
  python reels.py preview              # contact sheets with crop boxes drawn on (media_cache/reel_preview/)
  python reels.py preview --book finding-granny
  python reels.py build                # render every reel to archive/reels/{id}.mp4
  python reels.py build --only sw-reel-autumn-1
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
from PIL import Image, ImageDraw, ImageFont

import selector

BASE_DIR = Path(__file__).parent
VIDEO_DIR = BASE_DIR / "archive" / "video"
REELS_DIR = BASE_DIR / "archive" / "reels"
PREVIEW_DIR = BASE_DIR / "media_cache" / "reel_preview"

OUT_W, OUT_H = 1080, 1920

SW_TAGS = "#SeasonsWithDad #ChildrensBooks #ReadAloud #PictureBook #MemoriesFond"
SW_LINK = "https://mybook.to/SeasonsWithDad"

# Each reel: source in/out (cut on narration pauses, not scene cuts — the
# verse often runs across a scene change) and crop keyframes as
# (source_time, centre_fraction). Two keyframes at a scene cut make the window
# jump with the cut rather than drift across it.
SW_REELS = [
    {
        "id": "sw-reel-spring",
        "date": "2027-03-21",
        "start": 5.65, "end": 29.45,
        "keys": [(5.5, 0.27), (7.0, 0.32), (8.5, 0.45), (12.0, 0.45), (13.5, 0.36), (17.69, 0.55),
                 (17.7, 0.26), (22.0, 0.28), (29.5, 0.55)],
        "message": "🌼 Spring with Dad — racing through the bluebell woods and watching the narrowboats drift along the canal. A little moment from the animated read-aloud of \"Seasons with Dad\" by Andrew Abel, illustrated by Graeme Holding.\n\n" + SW_LINK + "\n\n#SpringWalk " + SW_TAGS,
    },
    {
        "id": "sw-reel-summer-1",
        "date": "2027-06-05",
        "start": 29.45, "end": 53.07,
        "keys": [(29.5, 0.30), (31.5, 0.30), (34.5, 0.72), (37.0, 0.72), (41.29, 0.40),
                 (41.3, 0.25), (44.0, 0.35), (47.5, 0.45), (49.5, 0.45), (53.1, 0.68)],
        "message": "🚂 Waving at the steam train from the bridge, then a picnic up by the old castle — summer days from \"Seasons with Dad,\" now as an animated read-aloud.\n\n" + SW_LINK + "\n\n#SummerVibes " + SW_TAGS,
    },
    {
        "id": "sw-reel-summer-2",
        "date": "2027-07-17",
        "start": 53.07, "end": 82.4,
        "keys": [(53.0, 0.70), (55.26, 0.70),
                 (55.27, 0.45), (59.5, 0.48), (63.0, 0.62), (64.79, 0.65),
                 (64.8, 0.43), (68.56, 0.43),
                 (68.57, 0.12), (75.0, 0.12), (82.4, 0.62)],
        "message": "🍦 Ice cream by the sea wall, donkey rides on the sand, and a hedgehog visitor by torchlight 🦔 Summer from \"Seasons with Dad,\" animated.\n\n" + SW_LINK + "\n\n#Seaside " + SW_TAGS,
    },
    {
        "id": "sw-reel-autumn-1",
        "date": "2026-10-24",
        "start": 82.5, "end": 107.4,
        "keys": [(82.5, 0.27), (94.72, 0.40),
                 (94.73, 0.25), (107.4, 0.52)],
        "message": "🎣 Bait on the line with Dad, then feeding the ducks at the village pond 🦆 Autumn from the animated read-aloud of \"Seasons with Dad.\"\n\n" + SW_LINK + "\n\n#AutumnVibes " + SW_TAGS,
    },
    {
        "id": "sw-reel-autumn-2",
        "date": "2026-11-03",
        "start": 107.4, "end": 141.1,
        "keys": [(107.4, 0.45), (107.62, 0.45),
                 (107.63, 0.27), (114.5, 0.27), (117.5, 0.75), (118.76, 0.75),
                 (118.77, 0.20), (126.0, 0.20), (130.0, 0.75), (131.32, 0.75),
                 (131.33, 0.68), (141.1, 0.68)],
        "message": "🍂 One big pile of leaves to jump in, then bonfire night with fireworks and cinder toffee 🎆 Autumn into winter, from the animated read-aloud of \"Seasons with Dad.\"\n\n" + SW_LINK + "\n\n#BonfireNight " + SW_TAGS,
    },
    {
        "id": "sw-reel-winter",
        "date": "2026-12-11",
        "start": 141.1, "end": 163.7,
        "keys": [(141.1, 0.65), (142.76, 0.65),
                 (142.77, 0.20), (153.66, 0.36),
                 (153.67, 0.40), (163.7, 0.46)],
        "message": "❄️ Sledging down the hill, a Christmas full of family stories, and games on the blanket with Dad 🎄 The last pages of the animated \"Seasons with Dad.\"\n\n" + SW_LINK + "\n\n#WinterFun #Christmas " + SW_TAGS,
    },
]

FG_TAGS = "#FindingGranny #ChildrensBooks #ReadAloud #PictureBook #Grandparents #MemoriesFond"
FG_LINK = "https://memoriesfond.com/"

# A hide-and-seek: the two kids follow Granny's drawn clues room to room. The
# clue close-ups (boy's face left, girl's right, drawing in between) crop
# naturally to the drawing at 0.5; the wide rooms pan toward whoever's moving.
# Cuts land on the quietest stretches under the music bed (29.2s, 53.75s).
FG_REELS = [
    {
        "id": "fg-reel-clues-1",
        "date": "2026-11-19",
        "start": 6.25, "end": 29.2,
        "keys": [(6.3, 0.40), (7.5, 0.45), (9.0, 0.66), (10.29, 0.68),
                 (10.3, 0.45), (14.92, 0.45),
                 (14.93, 0.22), (16.9, 0.48), (19.0, 0.60), (20.05, 0.60),
                 (20.07, 0.52), (24.12, 0.52),
                 (24.13, 0.48), (27.85, 0.48),
                 (27.87, 0.50), (29.2, 0.55)],
        "message": "🔍 Granny's hiding — and she's left a trail of drawn clues around the house! A peek at the animated read-aloud of \"Finding Granny\" by Andrew Abel, illustrated by Graeme Holding.\n\n" + FG_LINK + "\n\n#HideAndSeek " + FG_TAGS,
    },
    {
        "id": "fg-reel-clues-2",
        "date": "2026-12-29",
        "start": 29.2, "end": 53.75,
        "keys": [(29.2, 0.55), (29.92, 0.55),
                 (29.93, 0.47), (33.02, 0.50),
                 (33.03, 0.48), (37.45, 0.48),
                 (37.47, 0.20), (39.0, 0.22), (41.45, 0.66),
                 (41.47, 0.50), (45.65, 0.50),
                 (45.67, 0.52), (49.95, 0.52),
                 (49.97, 0.48), (52.02, 0.55),
                 (52.03, 0.50), (53.75, 0.50)],
        "message": "🛋️ Behind the sofa? ⛺ Inside the tent? Follow the clues with the kids in the animated read-aloud of \"Finding Granny\" — perfect for an indoor hide-and-seek on a holiday afternoon.\n\n" + FG_LINK + "\n\n#HideAndSeek " + FG_TAGS,
    },
    {
        "id": "fg-reel-found",
        "date": "2027-01-21",
        "start": 53.75, "end": 76.9,
        "keys": [(53.75, 0.50), (55.98, 0.50),
                 (56.0, 0.48), (60.25, 0.48),
                 (60.27, 0.80), (61.68, 0.80),
                 (61.7, 0.16), (64.15, 0.16),
                 (64.17, 0.48), (68.25, 0.50),
                 (68.27, 0.66), (72.0, 0.64), (75.0, 0.59), (76.9, 0.59)],
        "message": "🧺 The last clue leads to the laundry basket... and a great big Granny hug! 🤗 Happy National Hugging Day from the animated \"Finding Granny.\"\n\n" + FG_LINK + "\n\n#NationalHuggingDay #GrannyHugs " + FG_TAGS,
    },
]

AD_TAGS = "#AdoptADinosaur #Dinosaurs #ChildrensBooks #ReadAloud #PictureBook #MemoriesFond"
AD_LINK = "https://mybook.to/AdoptADinosaur"

# The only source with karaoke subtitles burned in (black box from y≈617,
# up to 80% of the width — a 9:16 window would chop every line mid-word). So
# the picture is cropped above them (pic_h) and the lines are re-set as reel
# captions from this transcript, timed from the box changing width per line.
# Narration runs one verse per page; page turns are at 8.83, 18.7, 28.73,
# 39.2, 48.53, 58.17, 67.63, 78.6, 88.7, 99.47 and the reels cut in the
# quiet just before each (the next line starts ~0.1s ahead of the picture).
AD_CAPTIONS = [
    (8.85, 10.80, "Tyrannosaurus Rex is grand"),
    (10.80, 13.45, "but not a pet, you'll understand"),
    (13.45, 15.95, "with dagger teeth and hunger vast"),
    (15.95, 18.70, "your living room just wouldn't last"),
    (18.70, 20.65, "smart and sly"),
    (20.65, 23.55, "but not a pet I'll tell you why"),
    (23.55, 25.00, "they'd look around"),
    (25.00, 26.25, "for some way out"),
    (26.25, 28.55, "and soon escape without a doubt"),
    (28.55, 31.40, "Triceratops has three sharp horns"),
    (31.40, 32.75, "they'd like to eat"),
    (32.75, 34.15, "your neighbor's lawns"),
    (34.15, 35.65, "they'd charge around"),
    (35.65, 36.95, "and break your toys"),
    (36.95, 39.00, "and surely make a lot of noise"),
    (39.00, 41.65, "Brachiosaurus towering high"),
    (41.65, 43.95, "but as a pet I wouldn't try"),
    (43.95, 45.30, "They'd bellow loud"),
    (45.30, 46.60, "and stand aloof and"),
    (46.60, 47.35, "push their head"),
    (47.35, 48.55, "right through the roof!"),
    (48.55, 51.15, "Stegosaurus plated spine"),
    (51.15, 53.45, "they'd never make a pet of mine."),
    (53.45, 55.95, "Their spiky tail would swish about"),
    (55.95, 57.20, "and smash the doors"),
    (57.20, 58.20, "and windows out."),
    (58.20, 61.10, "Diplodocus long, long neck."),
    (61.10, 61.95, "Your bedroom"),
    (61.95, 63.45, "would be quite a wreck"),
    (63.45, 65.80, "and on your lap they wouldn't sit."),
    (65.80, 67.65, "You'd never get to cuddle it."),
    (67.65, 69.95, "Pterodon flies in the sky"),
    (69.95, 71.45, "a pet it's not –"),
    (71.45, 72.95, "you should know why"),
    (72.95, 74.15, "they'd flap their wings"),
    (74.15, 75.75, "and smash the light"),
    (75.75, 77.40, "no room to fly"),
    (77.40, 78.60, "it's just not right"),
    (78.60, 80.75, "Ankylosaurus built so strong"),
    (80.75, 83.25, "but as a pet it would be wrong."),
    (83.25, 84.90, "Their club like tail"),
    (84.90, 86.40, "would cause a fuss."),
    (86.40, 88.55, "I'd have to give a no from us."),
    (88.70, 91.35, "Dinosaurs are great to see"),
    (91.35, 92.95, "but not as a pet."),
    (92.95, 94.10, "Just let them be"),
    (94.10, 95.15, "on ancient earth"),
    (95.15, 96.25, "they used to roam"),
    (96.25, 97.50, "they should not live"),
    (97.50, 98.45, "inside our home."),
]

# Two pages per reel, the last three together so the series ends on the
# moral. Pans follow the line being read: T-Rex's jaws then his turn to
# camera, the brachiosaur's neck through the roof, the stegosaur's tail as
# it swishes, the ankylosaur's club tail and back to its face.
AD_REELS = [
    {
        "id": "ad-reel-trex-raptor",
        "date": "2026-11-07",
        "start": 8.9, "end": 28.6,
        "keys": [(8.9, 0.60), (12.0, 0.65), (14.0, 0.62), (15.6, 0.44), (18.69, 0.44),
                 (18.7, 0.43), (28.6, 0.47)],
        "message": "🦖 Tyrannosaurus Rex is grand... but not a pet, you'll understand! A peek at the animated read-aloud of \"Adopt a Dinosaur\" by Andrew Abel — and a sly little raptor with escape plans.\n\n" + AD_LINK + "\n\n" + AD_TAGS,
    },
    {
        "id": "ad-reel-trike-brachio",
        "date": "2027-02-21",
        "start": 28.6, "end": 48.45,
        "keys": [(28.6, 0.19), (32.6, 0.20), (34.0, 0.27), (35.6, 0.21), (39.09, 0.20),
                 (39.1, 0.50), (42.5, 0.62), (48.45, 0.64)],
        "message": "🦕 A triceratops would eat the neighbors' lawns, and a brachiosaurus would put its head right through the roof! From the animated read-aloud of \"Adopt a Dinosaur\" — why prehistoric giants make terrible pets.\n\n" + AD_LINK + "\n\n#DinoHumor " + AD_TAGS,
    },
    {
        "id": "ad-reel-stego-diplo",
        "date": "2027-04-10",
        "start": 48.45, "end": 67.5,
        "keys": [(48.45, 0.52), (51.6, 0.72), (53.4, 0.72), (55.2, 0.50), (56.0, 0.52), (57.2, 0.66), (58.09, 0.66),
                 (58.1, 0.46), (60.2, 0.55), (62.2, 0.50), (64.5, 0.52), (67.5, 0.50)],
        "message": "Swish goes the stegosaurus tail... there go the doors and windows! 🪟 And a diplodocus? You'd never get to cuddle it. From the animated read-aloud of \"Adopt a Dinosaur\" by Andrew Abel.\n\n" + AD_LINK + "\n\n#PetDino " + AD_TAGS,
    },
    {
        "id": "ad-reel-not-a-pet",
        "date": "2027-05-30",
        "start": 67.5, "end": 99.4,
        "keys": [(67.5, 0.50), (70.5, 0.52), (72.5, 0.62), (74.0, 0.58), (76.0, 0.62), (78.49, 0.62),
                 (78.5, 0.58), (81.5, 0.66), (82.6, 0.62), (84.0, 0.32), (85.6, 0.32), (87.0, 0.60), (88.69, 0.62),
                 (88.7, 0.30), (99.4, 0.50)],
        "message": "Dinosaurs are great to see — but not as a pet! 🦕🏡 A pterodactyl in the living room, an ankylosaurus with a club tail, and the moral of the story, from the animated read-aloud of \"Adopt a Dinosaur.\"\n\n" + AD_LINK + "\n\n#DinosaurFacts " + AD_TAGS,
    },
]

# end_card: the title card shown whole (its text is far wider than a 9:16
# crop), letterboxed over a blurred fill of itself, closing every reel.
# pic_h (optional): source rows kept from the top, to crop off burned-in
# subtitles; captions (optional): (start, end, text) re-set over the reel.
BOOKS = {
    "seasons-with-dad": {
        "title": "Seasons with Dad",
        "source": VIDEO_DIR / "Seasons with Dad Animaed v1 - No Subtitles.mp4",
        "src_size": (2204, 1080),
        "end_card": (0.0, 4.9),  # narrated title + credits
        "reels": SW_REELS,
    },
    "finding-granny": {
        "title": "Finding Granny",
        "source": VIDEO_DIR / "Finding Granny - Animated v1 (with no subtitles).mp4",
        "src_size": (1920, 1080),
        "end_card": (76.9, 79.8),  # closing title card with memoriesfond.com
        "reels": FG_REELS,
    },
    "adopt-a-dinosaur": {
        "title": "Adopt a Dinosaur",
        "source": VIDEO_DIR / "Adopt a Dinosaur - Animated v1.mp4",
        "src_size": (1280, 720),
        "pic_h": 612,
        "captions": AD_CAPTIONS,
        "end_card": (99.6, 103.8),  # closing title card, music only
        "reels": AD_REELS,
    },
}

CAPTION_DIR = BASE_DIR / "media_cache" / "reel_captions"
CAPTION_Y = 1320  # caption centre: clear of the Reels UI over the bottom ~quarter
CAPTION_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/mnt/c/Windows/Fonts/arialbd.ttf",
]


def _pic_h(book: dict) -> int:
    return book.get("pic_h", book["src_size"][1])


def _scaled_w(book: dict) -> int:
    """Source width once upscaled to the output height *before* cropping, so a
    slow pan moves in whole output pixels rather than ~1.8px jumps."""
    src_w = book["src_size"][0]
    return round(src_w * OUT_H / _pic_h(book) / 2) * 2


def _caption_font(size: int) -> ImageFont.FreeTypeFont:
    for path in CAPTION_FONTS:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def _render_caption(text: str, out_path: Path):
    """White bold text on a translucent rounded box, wrapped to fit the
    frame — a PNG rather than ffmpeg drawtext, which bundled builds lack."""
    font = _caption_font(64)
    max_w, pad_x, pad_y, gap = 920, 34, 22, 12
    lines = []
    for word in text.split():
        trial = f"{lines[-1]} {word}" if lines else word
        if lines and font.getlength(trial) <= max_w:
            lines[-1] = trial
        else:
            lines.append(word)
    if len(lines) == 2:
        # Even out the break rather than leaving one word dangling.
        words = text.split()
        splits = [(" ".join(words[:i]), " ".join(words[i:])) for i in range(1, len(words))]
        lines = list(min(splits, key=lambda pair: max(font.getlength(p) for p in pair)))
    ascent, descent = font.getmetrics()
    line_h = ascent + descent
    text_w = max(font.getlength(line) for line in lines)
    w = round(text_w) + 2 * pad_x
    h = len(lines) * line_h + (len(lines) - 1) * gap + 2 * pad_y
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)
    draw.rounded_rectangle([0, 0, w - 1, h - 1], radius=20, fill=(0, 0, 0, 190))
    for i, line in enumerate(lines):
        x = (w - font.getlength(line)) / 2
        draw.text((x, pad_y + i * (line_h + gap)), line, font=font, fill="white")
    im.save(out_path)


def _reel_captions(book: dict, reel: dict) -> list[tuple[float, float, Path]]:
    """The book's caption lines falling inside this reel, rendered to PNGs,
    with times shifted to the reel's own clock."""
    out = []
    cap_dir = CAPTION_DIR / reel["id"]
    cap_dir.mkdir(parents=True, exist_ok=True)
    for start, end, text in book.get("captions", []):
        s, e = max(start, reel["start"]), min(end, reel["end"])
        if e - s < 0.2:
            continue
        png = cap_dir / f"{len(out):02d}.png"
        _render_caption(text, png)
        out.append((s - reel["start"], e - reel["start"], png))
    return out


def _selected(args):
    """(book, reel) pairs filtered by --book / --only."""
    for slug, book in BOOKS.items():
        if getattr(args, "book", None) and slug not in args.book:
            continue
        for reel in book["reels"]:
            if getattr(args, "only", None) and reel["id"] not in args.only:
                continue
            yield book, reel



def crop_centre(keys: list[tuple[float, float]], t: float) -> float:
    """Python twin of _crop_x_expr(), used to draw the preview boxes."""
    if t <= keys[0][0]:
        return keys[0][1]
    for (t0, c0), (t1, c1) in zip(keys, keys[1:]):
        if t < t1:
            u = (t - t0) / (t1 - t0)
            return c0 + (c1 - c0) * u * u * (3 - 2 * u)
    return keys[-1][1]


def _crop_x_expr(keys: list[tuple[float, float]], start: float, scaled_w: int) -> str:
    """ffmpeg expression for the crop window's left edge, in scaled-source
    pixels. Smoothstep-eased between keyframes; `t` restarts at 0 because of
    the input-side -ss, hence the +start."""
    T = f"(t+{start})"

    def px(c):
        return f"({c}*{scaled_w}-{OUT_W / 2})"

    expr = px(keys[-1][1])
    for (t0, c0), (t1, c1) in reversed(list(zip(keys, keys[1:]))):
        u = f"(({T}-{t0})/{t1 - t0})"
        seg = f"({px(c0)}+({px(c1)}-{px(c0)})*{u}*{u}*(3-2*{u}))"
        expr = f"if(lt({T},{t1}),{seg},{expr})"
    expr = f"if(lt({T},{keys[0][0]}),{px(keys[0][1])},{expr})"
    return f"max(0,min({scaled_w - OUT_W},{expr}))"


def build_reel(book: dict, reel: dict) -> Path:
    source = book["source"]
    if not source.exists():
        sys.exit(f"Source video not found: {source}")
    scaled_w = _scaled_w(book)
    card_start, card_end = book["end_card"]
    REELS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REELS_DIR / f"{reel['id']}.mp4"

    dur = reel["end"] - reel["start"]
    card_dur = card_end - card_start
    x_expr = _crop_x_expr(reel["keys"], reel["start"], scaled_w)
    captions = _reel_captions(book, reel)
    # Captions are inputs 2.. (single-frame PNGs; overlay holds the last frame,
    # so `enable` alone decides when each shows).
    cap_chain = ""
    for i, (s, e, _) in enumerate(captions):
        cap_chain += (f"[m{i}][{i + 2}:v]overlay=x=(W-w)/2:y={CAPTION_Y}-h/2:"
                      f"enable='between(t,{s:.2f},{e:.2f})'[m{i + 1}];")
    filtergraph = (
        f"[0:v]crop={book['src_size'][0]}:{_pic_h(book)}:0:0,"
        f"scale={scaled_w}:{OUT_H}:flags=lanczos,crop={OUT_W}:{OUT_H}:x='{x_expr}':y=0,"
        f"setsar=1,fps=30[m0];"
        f"{cap_chain}[m{len(captions)}]format=yuv420p[main];"
        f"[0:a]afade=t=in:d=0.15,afade=t=out:st={dur - 0.35:.2f}:d=0.35[maina];"
        f"[1:v]split[c1][c2];"
        f"[c2]scale=-2:{OUT_H},crop={OUT_W}:{OUT_H},boxblur=30:2,eq=brightness=-0.08[bg];"
        f"[c1]scale={OUT_W}:-2:flags=lanczos[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,fps=30,format=yuv420p,"
        f"fade=t=in:d=0.3,fade=t=out:st={card_dur - 0.4:.2f}:d=0.4[card];"
        f"[1:a]afade=t=in:d=0.2,afade=t=out:st={card_dur - 0.4:.2f}:d=0.4[carda];"
        f"[main][maina][card][carda]concat=n=2:v=1:a=1[v][a]"
    )
    cmd = [
        imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
        "-ss", str(reel["start"]), "-t", f"{dur:.3f}", "-i", str(source),
        "-ss", str(card_start), "-t", f"{card_dur:.3f}", "-i", str(source),
        *[arg for _, _, png in captions for arg in ("-i", str(png))],
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
    for book, reel in _selected(args):
        out = build_reel(book, reel)
        print(f"  {reel['id']}  -> {out.relative_to(BASE_DIR)}  ({out.stat().st_size / 1e6:.1f} MB)")


def cmd_preview(args):
    """One contact sheet per reel: a source frame every 1.5s with the crop
    window outlined, for checking keyframes without rendering anything."""
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    thumb_w = 400
    for book, reel in _selected(args):
        src_w, pic_h = book["src_size"][0], _pic_h(book)
        thumb_h = round(thumb_w * pic_h / src_w)
        box_w = thumb_w * (OUT_W / _scaled_w(book))
        times = []
        t = reel["start"] + 0.2
        while t < reel["end"]:
            times.append(t)
            t += 1.5
        thumbs = []
        for t in times:
            frame = PREVIEW_DIR / "frame.jpg"
            subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(book["source"]),
                            "-frames:v", "1", "-vf", f"crop={src_w}:{pic_h}:0:0,scale={thumb_w}:{thumb_h}",
                            str(frame)], check=True)
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


def _queue_item(book: dict, reel: dict) -> dict:
    d = date.fromisoformat(reel["date"])
    return {
        "id": reel["id"],
        "type": "video",
        "scheduled_publish_time": selector._scheduled_datetime(d).isoformat(),
        "message": reel["message"],
        "source_facts": {
            "book": book["title"],
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
    for book, reel in _selected(args):
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
        new_items.append(_queue_item(book, reel))
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
    parser = argparse.ArgumentParser(description="Cut and queue picture-book read-aloud promo reels")
    sub = parser.add_subparsers(dest="command")
    preview = sub.add_parser("preview", help="Contact sheets with crop boxes drawn on")
    build = sub.add_parser("build", help="Render reels to archive/reels/")
    build.add_argument("--only", nargs="+", help="Reel id(s) to build (default: all)")
    queue = sub.add_parser("queue", help="Append built reels to the scheduler queue")
    for p in (preview, build, queue):
        p.add_argument("--book", nargs="+", choices=list(BOOKS), help="Book(s) to act on (default: all)")
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
