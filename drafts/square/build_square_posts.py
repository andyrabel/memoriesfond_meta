"""Build square (1080x1080) candidate posts from four picture books' page art.

Crops come from the animator repo's book images (not the video clips). Each
candidate is written to drafts/square/images/{id}.jpg and described in
drafts/square/candidates.json in the same shape as archive/posts.json entries,
so a selected candidate can be copied straight into the archive.

Crop spec: (x0, y0, side) in source pixels. A square that runs past the image
edge is padded: "fill" pads with the page's own edge colour (white pages),
"smear" stretches the crop's own edge strip outward and blurs it (painted
backgrounds).
`whiten` blanks source columns before x (to drop a fragment of neighbouring art).
"""

import json
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter

BOOKS = Path("/home/aabel/github/animator/books")
OUT = Path(__file__).resolve().parent
SIZE = 1080

LINKS = {
    "a-useless-book": "https://memoriesfond.com/",
    "big-bad-wolfs-birthday": "https://mybook.to/BadWolf2",
    "i-like-earth": "https://mybook.to/ILikeEarth",
    "slice-and-ice": "https://mybook.to/SliceAndIce",
}
TITLES = {
    "a-useless-book": "A Useless Book",
    "big-bad-wolfs-birthday": "The Big Bad Wolf's Birthday",
    "i-like-earth": "I Like Earth",
    "slice-and-ice": "Slice & Ice",
}

UB = "a-useless-book/images/"
BW = "big-bad-wolfs-birthday/images/"
EARTH = "i-like-earth/images/I Like Earth (IngramSpark Hardback) Licensed v10-images-{}.jpg"
SI = "slice-and-ice/images/"


def earth_spread(left, right):
    """Join two facing I Like Earth pages, as build_spreads.py does."""
    a = Image.open(BOOKS / EARTH.format(left)).convert("RGB")
    b = Image.open(BOOKS / EARTH.format(right)).convert("RGB")
    s = Image.new("RGB", (a.width + b.width, a.height))
    s.paste(a, (0, 0))
    s.paste(b, (a.width, 0))
    return s


# id, book, source, (x0, y0, side), pad, text, hashtags, post_months, post_day[, whiten]
CANDIDATES = [
    # ---- A Useless Book (spreads 3352x1700, white page) ----
    ("ub-04-still-reading", "a-useless-book", UB + "page-04-Still-Reading.jpg", (752, -225, 2150), "fill",
     "You're still reading? That's... unexpected 👀 Most books want you to learn something. \"A Useless Book\" by Andrew Abel would really rather you didn't.",
     "#AUselessBook #FunnyKidsBooks #PictureBooks #ReadAloud #MemoriesFond", None, None),
    ("ub-06-smart-and-curious", "a-useless-book", UB + "page-06-Smart-and-Curious.jpg", (1642, 0, 1700), "fill",
     "How do birds learn to sing? Why is one and one two? 🤓 Great questions! Just don't expect any answers from \"A Useless Book.\"",
     "#CuriousKids #KidsWhoRead #AUselessBook #ChildrensBooks #MemoriesFond", None, None),
    ("ub-07a-fawn", "a-useless-book", UB + "page-07-Fawn.jpg", (67, 0, 1700), "fill",
     "If you're hunting for answers, you won't find them here 🦌 (Spoiler: that little spotted cutie is a fawn. Oops, you learned something.) From \"A Useless Book.\"",
     "#AUselessBook #BabyAnimals #Fawn #KidsBooks #MemoriesFond", None, None),
    ("ub-07b-stag", "a-useless-book", UB + "page-07-Fawn.jpg", (1642, 0, 1700), "fill",
     "Not a fawn. Definitely not a sweet baby deer. Just one very unimpressed stag 😒🦌 \"A Useless Book\" by Andrew Abel.",
     "#AUselessBook #FunnyPictureBooks #Deer #ReadAloud #MemoriesFond", None, None),
    ("ub-08-otter", "a-useless-book", UB + "page-08-Otter.jpg", (1508, 0, 1700), "fill",
     "Or that otters use rocks to crack clams near the shore 🦦🐚 Sea otters even tuck a favourite rock into a pouch of loose skin under their arm! (You didn't read that in \"A Useless Book.\")",
     "#SeaOtters #AnimalFacts #AUselessBook #KidsBooks #MemoriesFond", None, None),
    ("ub-09a-wasps", "a-useless-book", UB + "page-09-Wasps-and-Bees.jpg", (0, 0, 1700), "fill",
     "If you're learning that two and a three make a five... 📝 well, this book won't help. \"A Useless Book\" is proudly fact-free (mostly).",
     "#MathForKids #AUselessBook #FunnyKidsBooks #PictureBooks #MemoriesFond", None, None),
    ("ub-09b-bees", "a-useless-book", UB + "page-09-Wasps-and-Bees.jpg", (1642, 0, 1700), "fill",
     "And that wasps build a nest while the bees have a hive 🐝🍯 Sweet as honey, and totally useless. From \"A Useless Book\" by Andrew Abel.",
     "#Bees #HoneyBees #AUselessBook #PictureBooks #MemoriesFond", None, None),
    ("ub-10a-dromedary", "a-useless-book", UB + "page-10-Camels.jpg", (0, 0, 1700), "fill",
     "If you're wanting to learn things, this book's not for you 🐪 Meet the dromedary: one hump, zero interest in your education.",
     "#Camels #AnimalFacts #AUselessBook #KidsBooks #MemoriesFond", None, None),
    ("ub-10b-bactrian", "a-useless-book", UB + "page-10-Camels.jpg", (1676, 0, 1700), "fill",
     "There's no clue on which camels have one hump or two 🐫 (Psst: Bactrian camels have two. Don't tell anyone you read it here.) From \"A Useless Book.\"",
     "#Camels #FunnyKidsBooks #AUselessBook #ReadAloud #MemoriesFond", None, None),
    ("ub-11-goldfish", "a-useless-book", UB + "page-11-Goldfish.jpg", (868, 30, 1390), "fill",
     "Is it true that two sevens really add to fourteen? Or that goldfish see colors that you've never seen? 🐠🌈 (Yes and yes: goldfish can see ultraviolet light!) From \"A Useless Book.\"",
     "#Goldfish #FunFacts #AUselessBook #KidsBooks #MemoriesFond", None, None),
    ("ub-13-twiddle-thumbs", "a-useless-book", UB + "page-13-Twiddle-Thumbs.jpg", (301, -491, 2682), "fill",
     "This small book won't help much with your facts or your sums; you might as well sit and just twiddle your thumbs 👍👍 \"A Useless Book\" by Andrew Abel.",
     "#AUselessBook #RhymingBooks #ReadAloud #ChildrensBooks #MemoriesFond", None, None),
    ("ub-14a-paper-planes", "a-useless-book", UB + "page-14-Paper-Planes.jpg", (134, -55, 1810), "fill",
     "You could fold up these pages to make paper planes ✈️ Finally, a practical use for \"A Useless Book\"!",
     "#PaperPlanes #KidsCrafts #AUselessBook #FunnyKidsBooks #MemoriesFond", None, None),
    ("ub-14b-summer-rain", "a-useless-book", UB + "page-14-Paper-Planes.jpg", (1717, -50, 1800), "fill",
     "Or use them as shelter from light summer rains ☔ Who knew \"A Useless Book\" would make such a handy umbrella?",
     "#SummerRain #AUselessBook #PictureBooks #ReadAloud #MemoriesFond", "6,7,8", None, 1915),
    ("ub-15-wobbly-chair", "a-useless-book", UB + "page-15-Wobbly-Chair.jpg", (251, -591, 2883), "fill",
     "If you place this small book 'neath a wobbly old chair, then at last it's of use, so just leave it right there 🪑📕",
     "#AUselessBook #FunnyKidsBooks #RhymingBooks #ChildrensBooks #MemoriesFond", None, None),
    ("ub-16-read-it-again", "a-useless-book", UB + "page-16-Read-It-Again.jpg", (251, -524, 2749), "fill",
     "If you want something useless with nothing to say, then read it again. That's an order, okay? 📖😄 Happy National Read a Book Day!",
     "#NationalReadABookDay #AUselessBook #ReadAloud #KidsWhoRead #MemoriesFond", "9", "6"),

    # ---- The Big Bad Wolf's Birthday (spreads 2860x1440) ----
    ("bw-01-three-houses", "big-bad-wolfs-birthday", BW + "page-01-Three-Houses.jpg", (128, -495, 2431), "fill",
     "Straw, sticks, and bricks 🏠 You know how the story of the three little pigs began... but do you know what happened next? \"The Big Bad Wolf's Birthday\" by Andrew Abel.",
     "#ThreeLittlePigs #TheBigBadWolfsBirthday #FairyTales #ChildrensBooks #MemoriesFond", None, None),
    ("bw-03-changed-wolf", "big-bad-wolfs-birthday", BW + "page-03-Changed-Wolf.jpg", (1373, 0, 1440), "fill",
     "Meet the new Big Bad Wolf: calmed down, changed, best friends with the pigs, and now... a vegan! 🐺🐷🥕",
     "#TheBigBadWolfsBirthday #ThreeLittlePigs #Friendship #PictureBooks #MemoriesFond", None, None),
    ("bw-04a-knock", "big-bad-wolfs-birthday", BW + "page-04-Knock-at-the-Door.jpg", (0, 0, 1440), "fill",
     "There's a knock at the door, and the wolf has a grin. \"Little pigs, little pigs, will you let me in?\" 🚪🐺",
     "#TheBigBadWolfsBirthday #FairyTaleRetelling #ReadAloud #ChildrensBooks #MemoriesFond", None, None),
    ("bw-04b-let-you-in", "big-bad-wolfs-birthday", BW + "page-04-Knock-at-the-Door.jpg", (1401, 0, 1440), "fill",
     "\"By the hairs of my chinny chin chin... we will let you in! Let the party begin!\" 🎉🐷🐷🐷",
     "#TheBigBadWolfsBirthday #ThreeLittlePigs #BirthdayParty #KidsBooks #MemoriesFond", None, None),
    ("bw-05-balloons", "big-bad-wolfs-birthday", BW + "page-05-Balloons.jpg", (0, 0, 1773), "smear",
     "They made decorations for all of the rooms. He huffed and he puffed, and he blew up balloons 🎈 Best party helper ever.",
     "#TheBigBadWolfsBirthday #PartyDecorations #Balloons #PictureBooks #MemoriesFond", None, None),
    ("bw-06-pinata", "big-bad-wolfs-birthday", BW + "page-06-Pinata.jpg", (0, 0, 1440), "fill",
     "They hung a piñata, and all took a swing 🪅 And yes, that's a pig in sparkly dollar-store bling.",
     "#Pinata #BirthdayParty #TheBigBadWolfsBirthday #KidsBooks #MemoriesFond", None, None),
    ("bw-07-straw-hat", "big-bad-wolfs-birthday", BW + "page-07-Straw-Hat.jpg", (1420, 0, 1440), "fill",
     "Present number one: a hat made out of straw 👒 Doesn't the birthday wolf look dashing?",
     "#TheBigBadWolfsBirthday #ThreeLittlePigs #BirthdayPresents #ChildrensBooks #MemoriesFond", None, None),
    ("bw-08-rocking-chair", "big-bad-wolfs-birthday", BW + "page-08-Rocking-Chair.jpg", (1287, 0, 1440), "fill",
     "Next was a rocking chair made out of sticks 🪑 Somebody's ready for a birthday nap.",
     "#TheBigBadWolfsBirthday #ThreeLittlePigs #ReadAloud #PictureBooks #MemoriesFond", None, None),
    ("bw-09-pizza-oven", "big-bad-wolfs-birthday", BW + "page-09-Pizza-Oven.jpg", (972, 0, 1440), "fill",
     "And lastly, a pizza oven made out of bricks 🧱🔥🍕 Happy National Pizza Day from the birthday wolf!",
     "#NationalPizzaDay #PizzaOven #TheBigBadWolfsBirthday #KidsBooks #MemoriesFond", "2", "9"),
    ("bw-10-birthday-cake", "big-bad-wolfs-birthday", BW + "page-10-Birthday-Cake.jpg", (1320, 0, 1440), "fill",
     "They made him a cake, wrote in icing his name 🎂 He huffed and he puffed, and he blew out the flame!",
     "#BirthdayCake #HappyBirthday #TheBigBadWolfsBirthday #ChildrensBooks #MemoriesFond", None, None),
    ("bw-11-bagpipes", "big-bad-wolfs-birthday", BW + "page-11-Bagpipes.jpg", (0, 0, 1440), "fill",
     "They bought him some bagpipes colored red and maroon. He huffed and he puffed, and he blew out a tune 🎶 Happy Burns Night!",
     "#BurnsNight #Bagpipes #TheBigBadWolfsBirthday #PictureBooks #MemoriesFond", "1", "25"),
    ("bw-12-dancing", "big-bad-wolfs-birthday", BW + "page-12-Dancing.jpg", (1316, 0, 1440), "fill",
     "He started to practice, and then very soon, they were singing and dancing all 'round the room! 💃🐷🎶",
     "#TheBigBadWolfsBirthday #DanceParty #ThreeLittlePigs #ReadAloud #MemoriesFond", None, None),
    ("bw-13-turnip-soup", "big-bad-wolfs-birthday", BW + "page-13-Turnip-Soup.jpg", (1373, 0, 1440), "fill",
     "Hot turnip soup for the birthday wolf 🥣 A vegan feast for the merriest group around.",
     "#SoupSeason #TheBigBadWolfsBirthday #ThreeLittlePigs #KidsBooks #MemoriesFond", None, None),
    ("bw-14-best-friends", "big-bad-wolfs-birthday", BW + "page-14-Best-Friends.jpg", (1420, 0, 1440), "fill",
     "The pigs are so glad that the wolf that was bad has turned out to be... the best friend they've had! 🐺💛🐷",
     "#BestFriends #TheBigBadWolfsBirthday #Friendship #ChildrensBooks #MemoriesFond", None, None),

    # ---- I Like Earth (single pages 2588x2625; spreads joined for planets across the gutter) ----
    ("ile-00-cover", "i-like-earth", EARTH.format(0), (0, 18, 2588), "fill",
     "I like Earth. It's the best place to live! 🌍 A rhyming tour of the solar system that always ends up right back home. \"I Like Earth\" by Andrew Abel.",
     "#ILikeEarthBook #SpaceForKids #SolarSystem #ChildrensBooks #MemoriesFond", None, None),
    ("ile-01-where-to-live", "i-like-earth", EARTH.format(4), (0, 18, 2588), "fill",
     "I like Earth. Where would you like to live? 🌎 Comment below with your pick of the planets!",
     "#ILikeEarthBook #PlanetEarth #SpaceForKids #KidsBooks #MemoriesFond", None, None),
    ("ile-02-mercury", "i-like-earth", EARTH.format(5), (0, 18, 2588), "fill",
     "Mercury is near the sun, but it's too hot, that can't be fun! ☀️🥵 A year on Mercury lasts just 88 Earth days.",
     "#Mercury #ILikeEarthBook #SpaceFacts #KidsSpaceBooks #MemoriesFond", None, None),
    ("ile-03-venus", "i-like-earth", EARTH.format(7), (0, 18, 2588), "fill",
     "Venus is both hot and thick; its poisonous air would make me sick 🤢 Venus spins so slowly that one day there is longer than its whole year!",
     "#Venus #ILikeEarthBook #SpaceFacts #KidsSpaceBooks #MemoriesFond", None, None),
    ("ile-04-moon", "i-like-earth", ("spread", 9, 10), (1294, 18, 2588), "fill",
     "The Moon, it has no atmosphere. I could shout, but you won't hear 🌕 With no wind up there, astronauts' footprints could last for millions of years.",
     "#TheMoon #ILikeEarthBook #SpaceForKids #KidsSpaceBooks #MemoriesFond", None, None),
    ("ile-05-mars", "i-like-earth", EARTH.format(11), (0, 18, 2588), "fill",
     "Mars is cold and has no air; I don't think I would like it there 🔴 Mars is home to Olympus Mons, the tallest volcano in the solar system.",
     "#Mars #ILikeEarthBook #SpaceFacts #KidsSpaceBooks #MemoriesFond", None, None),
    ("ile-06-jupiter", "i-like-earth", EARTH.format(13), (0, 18, 2588), "fill",
     "Jupiter's a big gas ball. No place to jump or bounce a ball 🪐 Its Great Red Spot is a storm bigger than the whole Earth!",
     "#Jupiter #ILikeEarthBook #SpaceFacts #KidsSpaceBooks #MemoriesFond", None, None),
    ("ile-07-saturn", "i-like-earth", ("spread", 15, 16), (1294, 18, 2588), "fill",
     "Saturn has no solid ground. There's nowhere I could run around 🪐 Saturn is so light for its size, it would float in a (very, very big) bathtub!",
     "#Saturn #ILikeEarthBook #SpaceFacts #KidsSpaceBooks #MemoriesFond", None, None),
    ("ile-08-uranus", "i-like-earth", EARTH.format(18), (0, 18, 2588), "fill",
     "Uranus is the coldest planet; I'm pretty sure I could not stand it! 🥶 Uranus is tipped right over, so it rolls around the sun on its side.",
     "#Uranus #ILikeEarthBook #SpaceFacts #KidsSpaceBooks #MemoriesFond", None, None),
    ("ile-09-neptune", "i-like-earth", ("spread", 19, 20), (1294, 18, 2588), "fill",
     "Neptune's far away and blue, fierce winds and storms. I'd skip this too! 💨💙 One year on Neptune lasts about 165 Earth years.",
     "#Neptune #ILikeEarthBook #SpaceFacts #KidsSpaceBooks #MemoriesFond", None, None),
    ("ile-10-pluto", "i-like-earth", EARTH.format(22), (0, 18, 2588), "fill",
     "To Pluto in the Kuiper Belt, with rocks and ice that never melt 🤍 See the big heart? It's a giant plain of frozen nitrogen ice.",
     "#Pluto #ILikeEarthBook #SpaceFacts #KidsSpaceBooks #MemoriesFond", None, None),
    ("ile-11-oceans", "i-like-earth", EARTH.format(23), (0, 18, 2588), "fill",
     "Earth's oceans of blue, and mountains of green, it must be the prettiest planet I've seen 🌊⛰️ Happy World Oceans Day!",
     "#WorldOceansDay #ILikeEarthBook #PlanetEarth #ChildrensBooks #MemoriesFond", "6", "8"),
    ("ile-12-water", "i-like-earth", EARTH.format(24), (0, 18, 2588), "fill",
     "With water to drink, and sweet air to breathe, I don't think it's somewhere that I'd want to leave 💧 Happy World Water Day!",
     "#WorldWaterDay #ILikeEarthBook #PlanetEarth #KidsBooks #MemoriesFond", "3", "22"),
    ("ile-13-somewhere-in-space", "i-like-earth", EARTH.format(25), (0, 18, 2588), "fill",
     "Is there somewhere in space that I'd like to go? I'll tell you right now, the answer is no! 🌌",
     "#ILikeEarthBook #Galaxy #SpaceForKids #RhymingBooks #MemoriesFond", None, None),
    ("ile-14-made-for-us-all", "i-like-earth", EARTH.format(28), (0, 18, 2588), "fill",
     "With all of the creatures that live on this ball, it seems like this planet was made for us all 🌍💚 Happy Earth Day!",
     "#EarthDay #ILikeEarthBook #PlanetEarth #ChildrensBooks #MemoriesFond", "4", "22"),

    # ---- Slice & Ice (single pages 2588x2625, spreads 5176x2625) ----
    ("si-01-bubba", "slice-and-ice", SI + "singles/0006.jpg", (0, 18, 2588), "fill",
     "Meet Bubba! 🍕 Pepperoni please, not so much the cheese, and a vanilla cone on the side. Straight from New York, home of the thin-crust slice.",
     "#NewYorkPizza #SliceAndIce #PizzaNight #ChildrensBooks #MemoriesFond", None, None),
    ("si-02-princess", "slice-and-ice", SI + "singles/0009.jpg", (0, 18, 2588), "fill",
     "Princess likes it all with cheese, and little else besides. She likes a rainbow sherbet, with a unicorn inside! 🦄🌈🍦",
     "#Unicorn #RainbowSherbet #SliceAndIce #KidsBooks #MemoriesFond", None, None),
    ("si-03-mama", "slice-and-ice", SI + "page-03-Mama.jpg", (104, 0, 2625), "fill",
     "Mama likes Hawaiian, with a crust that's gluten free, paired with a fresh young coconut 🥥🍍 Pineapple on pizza: yes or no?",
     "#HawaiianPizza #PineapplePizza #SliceAndIce #PictureBooks #MemoriesFond", None, None),
    ("si-04-papa", "slice-and-ice", SI + "singles/0013.jpg", (0, 18, 2588), "fill",
     "Papa wants Meat Lover's and a long cool soda, half filled with ice 🤠🥤 A Texas-sized order from \"Slice & Ice.\"",
     "#MeatLoversPizza #TexasBBQ #SliceAndIce #PizzaNight #MemoriesFond", None, None),
    ("si-05-granny", "slice-and-ice", SI + "page-05-Granny.jpg", (155, 0, 2625), "fill",
     "Granny likes her veggies, and maybe vegan cheese 🫒🍄 Greetings from San Francisco, the most vegan-friendly city around!",
     "#VeggiePizza #SanFrancisco #SliceAndIce #ChildrensBooks #MemoriesFond", None, None),
    ("si-06-grandpa", "slice-and-ice", SI + "singles/0017.jpg", (0, 18, 2588), "fill",
     "Grandpa likes the combo, with meat and veg and stuff. He likes banana milkshakes; he cannot get enough! 🍌🥤",
     "#BananaMilkshake #ChicagoDeepDish #SliceAndIce #KidsBooks #MemoriesFond", None, None),
    ("si-07-everyone-is-different", "slice-and-ice", SI + "singles/0019.jpg", (160, 169, 2268), "fill",
     "Everyone is different, no one's quite the same 💕 Some like different pizzas, some have different names. From \"Slice & Ice\" by Andrew Abel.",
     "#Family #Kindness #SliceAndIce #ChildrensBooks #MemoriesFond", None, None),
    ("si-08-menu", "slice-and-ice", SI + "singles/0021.jpg", (0, 18, 2588), "fill",
     "So now then, what would you like? Your waiter wants to know 🍕🍦🥤 Tell us your order in the comments!",
     "#PizzaNight #WhatsYourOrder #SliceAndIce #KidsBooks #MemoriesFond", None, None),
]


def blacken_amber(im):
    """Drop amber verse/fact lettering from a black-sky spread (keeps blue/white planets)."""
    r, _, b = im.split()
    redder = ImageChops.subtract(r, b).point(lambda v: 255 if v > 40 else 0)
    bright = r.point(lambda v: 255 if v > 70 else 0)
    mask = ImageChops.multiply(redder, bright)
    im.paste((0, 0, 0), mask=mask.filter(ImageFilter.MaxFilter(5)))
    return im


SOURCE_FIXES = {
    # Saturn itself is amber, so its text fragments are boxed out instead.
    ("spread", 15, 16): lambda im: (im.paste((0, 0, 0), (0, 0, 1708, 945)),
                                    im.paste((0, 0, 0), (3400, 1950, im.width, im.height)), im)[-1],
    ("spread", 19, 20): blacken_amber,
}


def load(src):
    if isinstance(src, tuple):
        im = earth_spread(src[1], src[2])
        return SOURCE_FIXES.get(src, lambda i: i)(im)
    return Image.open(BOOKS / src).convert("RGB")


def edge_colour(im):
    """Median colour of the image's outer border, for seamless padding."""
    w, h = im.size
    px = [im.getpixel((x, y)) for x in range(0, w, max(1, w // 50)) for y in (0, h - 1)]
    px += [im.getpixel((x, y)) for y in range(0, h, max(1, h // 50)) for x in (0, w - 1)]
    return tuple(sorted(c[i] for c in px)[len(px) // 2] for i in range(3))


def square(im, x0, y0, side, pad, whiten=None):
    if whiten:
        im = im.copy()
        im.paste(edge_colour(im), (0, 0, whiten, im.height))
    w, h = im.size
    # Part of the square that lies inside the source image.
    ix0, iy0 = max(0, x0), max(0, y0)
    ix1, iy1 = min(w, x0 + side), min(h, y0 + side)
    inner = im.crop((ix0, iy0, ix1, iy1))
    canvas = Image.new("RGB", (side, side), edge_colour(im))
    px, py = ix0 - x0, iy0 - y0
    if pad == "smear":
        iw, ih = inner.size
        strip = 12
        if py > 0:
            canvas.paste(inner.crop((0, 0, iw, strip)).resize((iw, py)).filter(ImageFilter.GaussianBlur(8)), (px, 0))
        if side - py - ih > 0:
            canvas.paste(inner.crop((0, ih - strip, iw, ih)).resize((iw, side - py - ih)).filter(ImageFilter.GaussianBlur(8)), (px, py + ih))
    canvas.paste(inner, (px, py))
    return canvas.resize((SIZE, SIZE), Image.LANCZOS)


def main():
    (OUT / "images").mkdir(exist_ok=True)
    out = []
    for c in CANDIDATES:
        pid, book, src, (x0, y0, side), pad, text, tags, months, day = c[:9]
        whiten = c[9] if len(c) > 9 else None
        img = square(load(src), x0, y0, side, pad, whiten)
        rel = f"images/{pid}.jpg"
        img.save(OUT / rel, quality=90)
        out.append({
            "post_id": f"book-sq-{pid}",
            "book": TITLES[book],
            "message": f"{text}\n\n{LINKS[book]}\n\n{tags}",
            "post_months": months,
            "post_day": day,
            "image": rel,
        })
    (OUT / "candidates.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"wrote {len(out)} candidates")


if __name__ == "__main__":
    main()
