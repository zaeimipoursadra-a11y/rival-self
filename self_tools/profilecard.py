"""/card — builds a profile card image from assets/card_template.jpg.

Usage:  /card            -> your own card
        /card @user      -> card of that user (or numeric id)
        (reply) /card    -> card of the replied user
"""
import asyncio
import io
import os

from PIL import Image, ImageDraw, ImageFont
from pyrogram import filters
from pyrogram.handlers import MessageHandler

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = HERE  # template + font live next to this file in self_tools/
TEMPLATE = os.path.join(ASSETS, "card_template.jpg")
FONT_PATH = os.path.join(ASSETS, "DejaVuSans-Bold.ttf")

# Geometry of the 1672x941 template (measured from the image)
CIRCLE_CENTER = (836, 408)
CIRCLE_RADIUS = 206
ID_BOX = (1148, 436, 1578, 509)        # x1, y1, x2, y2 (pill under "ID:")
USER_BOX = (745, 674, 1125, 766)       # text area right of the "@"

WHITE = (240, 244, 255)
BLUE = (70, 140, 255)


def _font(size):
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except Exception:
        try:
            return ImageFont.load_default(size=size)
        except Exception:
            return ImageFont.load_default()


def _fit_text(draw, text, box, start, minimum=18):
    """Largest font size (<= start) that makes `text` fit inside box."""
    w_max = box[2] - box[0] - 10
    h_max = box[3] - box[1] - 10
    size = start
    while size > minimum:
        f = _font(size)
        l, t, r, b = draw.textbbox((0, 0), text, font=f)
        if (r - l) <= w_max and (b - t) <= h_max:
            return f
        size -= 2
    return _font(minimum)


def _circle_photo(photo_bytes, initial):
    d = CIRCLE_RADIUS * 2
    if photo_bytes:
        try:
            img = Image.open(io.BytesIO(photo_bytes)).convert("RGB")
            side = min(img.size)
            left, top = (img.width - side) // 2, (img.height - side) // 2
            img = img.crop((left, top, left + side, top + side)).resize((d, d), Image.LANCZOS)
        except Exception:
            img = None
    else:
        img = None
    if img is None:  # placeholder with the first letter
        img = Image.new("RGB", (d, d), (16, 30, 70))
        dr = ImageDraw.Draw(img)
        f = _font(int(d * 0.5))
        l, t, r, b = dr.textbbox((0, 0), initial, font=f)
        dr.text(((d - (r - l)) / 2 - l, (d - (b - t)) / 2 - t), initial, font=f, fill=BLUE)
    mask = Image.new("L", (d * 4, d * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, d * 4 - 1, d * 4 - 1), fill=255)
    mask = mask.resize((d, d), Image.LANCZOS)
    return img, mask


def build_card(photo_bytes, user_id, username, name):
    """New SELF RIVAL player card (Name / ID / Username / Rank)."""
    rank = None
    try:
        from . import economy as _eco
        rank = _eco.get().rank(int(user_id))
    except Exception:
        pass
    import sys
    root = os.path.dirname(HERE)
    if root not in sys.path:
        sys.path.insert(0, root)
    import rival_cards
    return rival_cards.player_card(photo_bytes, name or username or "", user_id, username, rank)


async def _resolve_user(client, message):
    parts = (message.text or "").split(maxsplit=1)
    arg = parts[1].strip() if len(parts) > 1 else ""
    if not arg and message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user.id
    if not arg:
        return "me"
    arg = arg.replace("https://t.me/", "").replace("t.me/", "").lstrip("@").strip()
    return int(arg) if arg.lstrip("-").isdigit() else arg


async def _get_photo(client, user):
    try:
        if getattr(user, "photo", None):
            data = await client.download_media(user.photo.big_file_id, in_memory=True)
            if data:
                return data.getvalue()
    except Exception:
        pass
    try:
        async for p in client.get_chat_photos(user.id, limit=1):
            data = await client.download_media(p.file_id, in_memory=True)
            if data:
                return data.getvalue()
    except Exception:
        pass
    return None


async def handler(client, message):
    try:
        u = await client.get_users(await _resolve_user(client, message))
    except Exception as e:
        return await message.reply_text(f"❌ کاربر پیدا نشد.\n`{type(e).__name__}`")
    try:
        photo = await _get_photo(client, u)
        name = " ".join(x for x in (u.first_name, u.last_name) if x)
        card = await asyncio.to_thread(build_card, photo, u.id, u.username, name)
        reply_to = None
        if message.reply_to_message:
            reply_to = message.reply_to_message.id
        await client.send_photo(message.chat.id, card, reply_to_message_id=reply_to)
        try:
            await message.delete()
        except Exception:
            pass
    except Exception as e:
        await message.reply_text(f"❌ ساخت کارت ناموفق بود.\n`{type(e).__name__}: {e}`")


def register(client):
    client.add_handler(
        MessageHandler(handler, filters.me & filters.command(["card", "pcard", "کارت"], prefixes=["/", "."])),
        group=0,
    )
