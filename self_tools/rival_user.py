"""Self-side diamond commands (typed from your own account, any chat).

  .موجودی  /balance   -> balance card + details
  .برترین‌ها /top      -> top-10 board with your position
"""
import asyncio
import io
import sys
import os

from pyrogram import filters
from pyrogram.enums import ParseMode
from pyrogram.handlers import MessageHandler

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


async def _balance(client, message):
    import rival_core
    import rival_cards
    from . import economy as E

    me = client.me or await client.get_me()
    e = E.get()
    e.touch(me.id, me.username, " ".join(x for x in (me.first_name, me.last_name) if x))
    bal = e.balance(me.id)
    days = None if rival_core.is_admin(me.id) else e.days_left(me.id)
    card = await asyncio.to_thread(rival_cards.balance_card, me.username, bal, E.Economy.toman(bal), days)
    cap = rival_core.balance_caption(me.id, me.first_name, bal)
    reply_to = message.reply_to_message.id if message.reply_to_message else None
    await client.send_photo(message.chat.id, card, caption=cap, parse_mode=ParseMode.HTML,
                            reply_to_message_id=reply_to)
    try:
        await message.delete()
    except Exception:
        pass


async def _top(client, message):
    import rival_core

    me = client.me or await client.get_me()
    txt = rival_core.top_text(me.id)
    await client.send_message(message.chat.id, txt, parse_mode=ParseMode.HTML,
                              disable_web_page_preview=True)
    try:
        await message.delete()
    except Exception:
        pass


def register(client):
    pre = ["/", "."]
    client.add_handler(MessageHandler(_balance, filters.me & filters.command(["balance", "موجودی"], prefixes=pre)), group=0)
    client.add_handler(MessageHandler(_top, filters.me & filters.command(["top", "برترین‌ها", "برترینها"], prefixes=pre)), group=0)
