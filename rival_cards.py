"""SELF RIVAL image cards (Pillow).

balance_card()  -> موجودی (days / diamonds / toman / username)
player_card()   -> پروفایل (photo, name, id, username, rank)

Persian shaping: arabic_reshaper + python-bidi when installed (they are in
requirements.txt); otherwise falls back to Pillow's raqm layout if available.
"""
from __future__ import annotations

import io
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont, features

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "self_tools", "assets")
FONT_DIR = os.path.join(HERE, "self_tools")
FONT_CANDIDATES = [
    os.path.join(HERE, "miniapp", "dashboard", "fonts", "Vazirmatn-Bold.ttf"),
    os.path.join(FONT_DIR, "Vazirmatn-Bold.ttf"),
    os.path.join(FONT_DIR, "DejaVuSans-Bold.ttf"),
]
WHITE = (236, 242, 255)
ICE = (170, 205, 255)

try:  # preferred: explicit shaping
    import arabic_reshaper
    from bidi.algorithm import get_display

    _RESHAPER = arabic_reshaper.ArabicReshaper(configuration={"delete_harakat": True})

    def _shape(text: str) -> str:
        return get_display(_RESHAPER.reshape(text))

    _RAQM = False
except Exception:  # pragma: no cover - depends on deployment
    _RAQM = bool(features.check("raqm"))

    def _shape(text: str) -> str:
        return text


def _font(size: int) -> ImageFont.FreeTypeFont:
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            try:
                if _RAQM:
                    return ImageFont.truetype(p, size, layout_engine=ImageFont.Layout.RAQM)
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _is_rtl(text: str) -> bool:
    return any("\u0600" <= ch <= "\u06ff" for ch in text)


def _fit(draw, text, max_w, max_h, start, minimum=16):
    size = start
    while size > minimum:
        f = _font(size)
        l, t, r, b = draw.textbbox((0, 0), text, font=f)
        if (r - l) <= max_w and (b - t) <= max_h:
            return f
        size -= 2
    return _font(minimum)


def _erase(img: Image.Image, box):
    """Wipe baked-in placeholder text: fill with the box's border colour, feathered."""
    x1, y1, x2, y2 = box
    px = img.load()
    ring = []
    for x in range(x1, x2, 6):
        ring += [px[x, y1 - 3], px[x, y2 + 3]]
    for y in range(y1, y2, 6):
        ring += [px[x1 - 3, y], px[x2 + 3, y]]
    col = tuple(sorted(c[i] for c in ring)[len(ring) // 2] for i in range(3))
    patch = Image.new("RGB", (x2 - x1, y2 - y1), col)
    mask = Image.new("L", patch.size, 0)
    ImageDraw.Draw(mask).rectangle((6, 6, patch.width - 7, patch.height - 7), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(5))
    img.paste(patch, (x1, y1), mask)


def _text_center(img, text, cx, cy, max_w, max_h, start, fill=WHITE, glow=True):
    d = ImageDraw.Draw(img)
    shaped = _shape(text)
    f = _fit(d, shaped, max_w, max_h, start)
    l, t, r, b = d.textbbox((0, 0), shaped, font=f)
    x = cx - (r - l) / 2 - l
    y = cy - (b - t) / 2 - t
    if glow:
        g = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(g).text((x, y), shaped, font=f, fill=(60, 140, 255, 200))
        g = g.filter(ImageFilter.GaussianBlur(7))
        img.paste(g, (0, 0), g)
    ImageDraw.Draw(img).text((x, y), shaped, font=f, fill=fill)


def _text_left(img, text, x, cy, max_w, max_h, start, fill=WHITE):
    d = ImageDraw.Draw(img)
    shaped = _shape(text)
    f = _fit(d, shaped, max_w, max_h, start)
    l, t, r, b = d.textbbox((0, 0), shaped, font=f)
    d.text((x - l, cy - (b - t) / 2 - t), shaped, font=f, fill=fill)


def _jpeg(img) -> io.BytesIO:
    bio = io.BytesIO()
    img.convert("RGB").save(bio, "JPEG", quality=90, optimize=True)
    bio.seek(0)
    bio.name = "card.jpg"
    return bio


def fmt(n) -> str:
    try:
        return f"{int(n):,}"
    except Exception:
        return str(n)


# ----------------------------------------------------------------- balance card
BAL_TEMPLATE = os.path.join(ASSETS, "card_balance.jpg")
# boxes measured on the 1672x941 template (baked placeholder text gets erased)
BAL_DAYS = (968, 238, 1232, 312)
BAL_GEMS = (962, 455, 1140, 530)
BAL_TOMAN = (1366, 452, 1554, 548)
BAL_USER = (905, 676, 1436, 735)


def balance_card(username: str | None, diamonds: int, toman: int, days_left: int | None) -> io.BytesIO:
    img = Image.open(BAL_TEMPLATE).convert("RGB")
    for box in (BAL_DAYS, BAL_GEMS, BAL_TOMAN, BAL_USER):
        _erase(img, box)
    days_txt = "—" if days_left is None else (f"{days_left} روز" if days_left > 0 else "منقضی")
    _text_center(img, days_txt, 1100, 276, 250, 62, 54)
    _text_center(img, fmt(diamonds), 1051, 493, 170, 70, 70)
    _text_center(img, fmt(toman), 1460, 484, 176, 56, 54)
    _text_center(img, "تومان", 1460, 527, 120, 30, 30, fill=ICE, glow=False)
    _text_center(img, f"@{username}" if username else "—", 1170, 706, 500, 56, 48)
    return _jpeg(img)


# ------------------------------------------------------------------ player card
PL_TEMPLATE = os.path.join(ASSETS, "card_player.jpg")
PL_CENTER = (836, 448)
PL_RADIUS = 168
PL_NAME = (1350, 362, 1565, 406)
PL_ID = (1296, 456, 1565, 500)
PL_USER = (1408, 549, 1565, 593)
PL_RANK = (562, 675, 745, 719)


def _circle_photo(photo_bytes, initial):
    d = PL_RADIUS * 2
    if photo_bytes:
        try:
            im = Image.open(io.BytesIO(photo_bytes)).convert("RGB")
            s = min(im.size)
            im = im.crop(((im.width - s) // 2, (im.height - s) // 2,
                          (im.width + s) // 2, (im.height + s) // 2)).resize((d, d), Image.LANCZOS)
        except Exception:
            im = None
    else:
        im = None
    if im is None:
        im = Image.new("RGB", (d, d), (14, 26, 70))
        dr = ImageDraw.Draw(im)
        f = _font(int(d * 0.5))
        sh = _shape(initial or "?")
        l, t, r, b = dr.textbbox((0, 0), sh, font=f)
        dr.text(((d - (r - l)) / 2 - l, (d - (b - t)) / 2 - t), sh, font=f, fill=ICE)
    mask = Image.new("L", (d, d), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, d - 1, d - 1), fill=255)
    return im, mask


def player_card(photo_bytes, name, uid, username, rank=None) -> io.BytesIO:
    img = Image.open(PL_TEMPLATE).convert("RGB")
    im, mask = _circle_photo(photo_bytes, (name or "?").strip()[:1].upper())
    img.paste(im, (PL_CENTER[0] - PL_RADIUS, PL_CENTER[1] - PL_RADIUS), mask)
    cy = lambda b: (b[1] + b[3]) / 2
    _text_left(img, (name or "—")[:26], PL_NAME[0], cy(PL_NAME), PL_NAME[2] - PL_NAME[0], 44, 40)
    _text_left(img, str(uid), PL_ID[0], cy(PL_ID), PL_ID[2] - PL_ID[0], 44, 40)
    _text_left(img, f"@{username}" if username else "—", PL_USER[0], cy(PL_USER),
               PL_USER[2] - PL_USER[0], 44, 40)
    _text_left(img, f"#{rank}" if rank else "—", PL_RANK[0], cy(PL_RANK),
               PL_RANK[2] - PL_RANK[0], 44, 40)
    return _jpeg(img)
