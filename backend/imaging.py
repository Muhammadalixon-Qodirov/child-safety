"""Screenshot storage (with a blurred copy for the parent) and synthetic demo screens."""
import io
import time
import uuid

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .config import SHOTS_DIR


def save_with_blur(image_bytes):
    """Stores the original and a blurred preview. Returns (original_path, blurred_path)."""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    img.thumbnail((1600, 1600))
    name = f"{int(time.time())}_{uuid.uuid4().hex[:8]}"
    original = SHOTS_DIR / f"{name}.jpg"
    blurred = SHOTS_DIR / f"{name}_blur.jpg"
    img.save(original, quality=80)
    small = img.copy()
    small.thumbnail((800, 800))
    small.filter(ImageFilter.GaussianBlur(radius=14)).save(blurred, quality=70)
    return str(original), str(blurred)


def _font(size):
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "C:/Windows/Fonts/segoeui.ttf",
                 "/System/Library/Fonts/Supplemental/Arial.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _wrap(draw, text, font, width):
    words, lines, line = text.split(), [], ""
    for word in words:
        test = f"{line} {word}".strip()
        if draw.textlength(test, font=font) <= width:
            line = test
        else:
            lines.append(line)
            line = word
    lines.append(line)
    return lines


def render_chat(title, messages, app_name="GameChat"):
    """Draws a fake chat window. messages: list of (is_child, text). Synthetic demo data only."""
    w, h = 900, 120 + 95 * len(messages)
    img = Image.new("RGB", (w, h), "#f4f6fb")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w, 56], fill="#5865f2")
    d.text((20, 15), f"{app_name}  ·  {title}", font=_font(22), fill="white")
    y, font = 80, _font(20)
    for is_child, text in messages:
        lines = _wrap(d, text, font, 520)
        bh = 20 + 28 * len(lines)
        bw = max(d.textlength(l, font=font) for l in lines) + 36
        x = w - bw - 30 if is_child else 30
        d.rounded_rectangle([x, y, x + bw, y + bh], radius=16, fill="#4f8cff" if is_child else "white",
                            outline=None if is_child else "#d9deea")
        for i, l in enumerate(lines):
            d.text((x + 18, y + 10 + 28 * i), l, font=font, fill="white" if is_child else "#1d2433")
        y += bh + 18
    img = img.crop((0, 0, w, min(h, y + 20)))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def render_page(domain, headline, body):
    w, h = 900, 420
    img = Image.new("RGB", (w, h), "#101418")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w, 50], fill="#e8eaed")
    d.rounded_rectangle([20, 10, w - 20, 40], radius=14, fill="white")
    d.text((40, 15), f"https://{domain}", font=_font(18), fill="#333")
    d.text((40, 90), headline, font=_font(38), fill="#ffd400")
    for i, line in enumerate(_wrap(d, body, _font(22), w - 80)):
        d.text((40, 170 + 32 * i), line, font=_font(22), fill="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


DEMO_SCENARIOS = {
    "grooming": {
        "app": "Roblox chat", "kind": "chat", "title": "xX_Pro_Gamer_Xx",
        "messages": [(False, "hey ur really good at this game!! how old are you?"),
                     (True, "im 11"),
                     (False, "cool me too haha. i can give you 1000 robux for free"),
                     (False, "but this is our secret ok? dont tell your parents"),
                     (False, "add me on telegram and send me a selfie first 😊")],
    },
    "pii": {
        "app": "Discord", "kind": "chat", "title": "#general",
        "messages": [(False, "where do you live? which school do you go to?"),
                     (True, "Chilonzor, 45-maktab, 6-sinf"),
                     (True, "my number is +998 90 123 45 67")],
    },
    "bullying": {
        "app": "Telegram", "kind": "chat", "title": "Class 6B group",
        "messages": [(False, "lol look at Sam's photo"),
                     (False, "you're so ugly, nobody likes you"),
                     (False, "everyone hates you, just leave the group loser")],
    },
    "scam": {
        "app": "Chrome", "kind": "page", "domain": "free-robux-now.xyz",
        "headline": "FREE 10,000 ROBUX!!!",
        "body": "Claim your prize in 60 seconds. Enter your Roblox username and password and send the code we text you to verify your account.",
    },
    "gambling": {
        "app": "Chrome", "kind": "page", "domain": "1xbet.com",
        "headline": "Live casino · Place your bet",
        "body": "Jackpot 50,000,000 so'm! Bet now on today's match and win big. Casino bonus for new players.",
    },
    "safe": {
        "app": "Chrome", "kind": "page", "domain": "khanacademy.org",
        "headline": "Fractions: adding unlike denominators",
        "body": "To add 1/3 and 1/4, first find a common denominator. Practice 5 questions to level up.",
    },
}


def render_demo(name):
    sc = DEMO_SCENARIOS[name]
    if sc["kind"] == "chat":
        img = render_chat(sc["title"], sc["messages"], sc["app"])
        text = "\n".join(m for _, m in sc["messages"])
    else:
        img = render_page(sc["domain"], sc["headline"], sc["body"])
        text = f"{sc['domain']}\n{sc['headline']}\n{sc['body']}"
    return img, text, sc
