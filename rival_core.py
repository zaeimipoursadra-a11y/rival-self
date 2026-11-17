"""SELF RIVAL core: user keyboard, diamonds shop, referral, games, admin tools, background jobs.

Installed from bot.py with ``rival_core.install(globals())`` once the manager bot,
DataManager and helpers exist.  Everything here talks to the manager bot only; the
per-user Pyrogram clients (self) are untouched except through start/stop helpers.
"""
from __future__ import annotations

import asyncio
import html
import io
import json
import logging
import os
import re
import sqlite3
import time
import uuid as _uuid
from datetime import datetime

import aiohttp
from pyrogram import StopPropagation, filters

from self_tools import economy as E

log = logging.getLogger("rival_core")
G: dict = {}
HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "self_tools", "assets")
BANNER = os.path.join(HERE, "self_tools", "rival_banner.jpg")
SUPPORT_URL = "https://t.me/sadzr"
PLACEHOLDER = "انتخاب کن - RIVAL"

ASSET_FILES = {
    "banner": BANNER,
    "referral": os.path.join(ASSETS, "banner_referral.jpg"),
    "bet": os.path.join(ASSETS, "banner_bet.jpg"),
    "dooz": os.path.join(ASSETS, "banner_dooz.jpg"),
    "balance": os.path.join(ASSETS, "card_balance.jpg"),
}

# ------------------------------------------------------------------ text helpers
_FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
_EN = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def fa(n) -> str:
    """Numbers are always shown with English digits and thousands commas."""
    return f"{int(n):,}"


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def mention(uid, name=None) -> str:
    return f'<a href="tg://user?id={int(uid)}">{esc(name or uid)}</a>'


def norm(t: str) -> str:
    return re.sub(r"[\u0640\ufe0f\u200c\u200d\s]+", "", t or "")


def to_int(s: str):
    s = (s or "").translate(_EN).replace(",", "").replace("٬", "").strip()
    return int(s) if s.isdigit() else None


def utf16len(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def kv(k, v) -> str:
    return f"◈ {k} ⟢ {v}"


def title(t: str, icon: str = "") -> str:
    return f"<b>‹ ʀɪᴠᴀʟ ›  {icon + ' ' if icon else ''}{t}</b>"


def eco() -> E.Economy:
    return E.get()


def admins() -> list:
    try:
        return [int(x) for x in G["data_manager"].get_admins()]
    except Exception:
        return [int(G.get("ROOT_ADMIN", 0))]


def is_admin(uid) -> bool:
    return int(uid) in admins() or int(uid) == int(G.get("ROOT_ADMIN", 0))


def user_name(u) -> str:
    n = " ".join(x for x in (getattr(u, "first_name", None), getattr(u, "last_name", None)) if x)
    return n or getattr(u, "username", None) or str(getattr(u, "id", ""))


def touch(u, private=False):
    try:
        eco().touch(u.id, getattr(u, "username", None), user_name(u), started=private)
    except Exception:
        pass


# ------------------------------------------------------------------- copy (texts)
WELCOME_HTML = (
    "<b>👑 SELF RIVAL</b>\n"
    "<i>فراتر از حد معمول</i>\n\n"
    "سلف، دستیاری روی اکانت خودته؛ دستورها را در هر چتی می‌نویسی و اجرا می‌شود.\n\n"
    "◈ <b>ابزار</b> ⟢ ترجمه، جستجو، هوش مصنوعی، دانلود، نرخ ارز\n"
    "◈ <b>حریم</b> ⟢ ضدحذف، منشی خودکار، قفل پیوی\n"
    "◈ <b>الماس</b> ⟢ اشتراک بخر یا رایگان بگیر\n"
    "◈ <b>رقابت</b> ⟢ شرط‌بندی و دوز در گپ رسمی\n\n"
    "از دکمه‌های پایین شروع کن 👇\n\n"
    "⚡ 𝐒𝐄𝐋𝐅 𝐑𝐈𝐕𝐀𝐋 | 𝘽𝙪𝙞𝙡𝙩 𝘽𝙚𝙮𝙤𝙣𝙙 𝙇𝙞𝙢𝙞𝙩𝙨"
)

ABOUT_HTML = (
    title("سلف چیست؟", "❓") + "\n\n"
    "سلف یک ربات جداگانه نیست؛ <b>دستیاری است که روی خود اکانت تلگرامت کار می‌کند</b>. "
    "بعد از فعال‌سازی، هر دستوری که در هر چتی (گروه، پیوی، کانال) بنویسی اجرا می‌شود و "
    "نتیجه مثل پیام خودت دیده می‌شود. مثلاً <code>.پنل</code> پنل کنترل را باز می‌کند.\n\n"
    "<b>چه کارهایی می‌کند؟</b>\n"
    "◈ ساعت و تاریخ زنده در نام و بیو، فونت‌های ویژه\n"
    "◈ ضدحذف و ضدویرایش پیام، ذخیره‌ی عکس‌های یک‌بارمصرف\n"
    "◈ منشی خودکار، پاسخ خودکار به لیست‌های دوست، دشمن و کراش\n"
    "◈ ترجمه، جستجو، هوش مصنوعی، نرخ ارز و طلا\n"
    "◈ دانلود ویدیو و موزیک از لینک، ساخت استیکر و گیف\n"
    "◈ ابزار گروه: تگ، پاک‌سازی پیام، ترک و حذف دسته‌جمعی\n"
    "◈ بیش از ۵۰ ابزار کوچک با <code>/</code> یا <code>.</code> (ماشین‌حساب، QR، فونت و …)\n\n"
    "<b>امنیت</b>\n"
    "ورود فقط با کد رسمی تلگرام خودت انجام می‌شود، نشست رمزنگاری ذخیره می‌شود و هر لحظه با "
    "«غیرفعال‌سازی» کاملاً از اکانتت خارج می‌شود.\n\n"
    "<b>اشتراک</b>\n"
    "هر ۵٬۰۰۰ الماس = ۳۰ روز سلف. هدیه‌ی شروع داری و الماس را می‌توانی بخری یا رایگان بگیری.\n\n"
    "برای شروع «⚙️ مدیریت سلف» را بزن."
)


# ---------------------------------------------------------------------- buttons
def B(text, style=None, **kw):
    d = {"text": text, **kw}
    if style:
        d["_s"] = style
    return d


def mk(rows, styled=True):
    out = []
    for r in rows:
        nr = []
        for b in r:
            b = dict(b)
            s = b.pop("_s", None)
            if styled and s:
                b["style"] = s
            nr.append(b)
        out.append(nr)
    return {"inline_keyboard": out}


BTN = {
    "manage": ("⚙️ مـدیـریـت ســلـف", "primary"),
    "acc": ("👤 حساب کاربری", "success"),
    "about": ("❓ سلف چیست", "success"),
    "buy": ("🛒 خــریـد الــمــاس", "primary"),
    "help": ("📨 پشتیبانی و راهنما", "danger"),
    "free": ("💎 الماس رایگان", "success"),
    "mini": ("☑️ مینی اپ", "danger"),
}
LAYOUT = [["manage"], ["acc", "about"], ["buy"], ["help", "free", "mini"]]
KEYMAP = {norm(v[0]): k for k, v in BTN.items()}
KEYMAP.update({norm("✅ فعالسازی"): "manage", norm("⛔ غیرفعال‌سازی"): "manage",
               norm("📨 راهنما و پشتیبانی"): "help"})


def main_kb_json(styled=True):
    rows = []
    for r in LAYOUT:
        row = []
        for k in r:
            d = {"text": BTN[k][0]}
            if styled:
                d["style"] = BTN[k][1]
            row.append(d)
        rows.append(row)
    return {"keyboard": rows, "resize_keyboard": True, "is_persistent": True,
            "input_field_placeholder": PLACEHOLDER}


def main_kb_pyro():
    KB, RK = G["KeyboardButton"], G["ReplyKeyboardMarkup"]
    rows = [[KB(BTN[k][0]) for k in r] for r in LAYOUT]
    try:
        return RK(rows, resize_keyboard=True, placeholder=PLACEHOLDER)
    except TypeError:
        return RK(rows, resize_keyboard=True)


# ------------------------------------------------------------------ Bot API I/O
async def api(method, payload, timeout=10.0):
    return await G["bot_api_request"](method, payload, timeout)


_FILE_IDS: dict = {}


async def _post_photo(chat_id, photo, caption, markup, reply_to=None):
    url = f"https://api.telegram.org/bot{G['BOT_TOKEN']}/sendPhoto"
    form = aiohttp.FormData()
    form.add_field("chat_id", str(chat_id))
    form.add_field("caption", caption[:1024])
    form.add_field("parse_mode", "HTML")
    if markup:
        form.add_field("reply_markup", json.dumps(markup, ensure_ascii=False))
    if reply_to:
        form.add_field("reply_parameters", json.dumps({"message_id": reply_to, "allow_sending_without_reply": True}))
    key = photo if isinstance(photo, str) else None
    if key and _FILE_IDS.get(key):
        form.add_field("photo", _FILE_IDS[key])
    else:
        if key:
            with open(ASSET_FILES[key], "rb") as f:
                raw = f.read()
        else:
            raw = photo.getvalue() if hasattr(photo, "getvalue") else bytes(photo)
        form.add_field("photo", raw, filename="card.jpg", content_type="image/jpeg")
    async with aiohttp.ClientSession() as sess:
        async with sess.post(url, data=form, timeout=aiohttp.ClientTimeout(total=30)) as r:
            j = await r.json(content_type=None)
    if j.get("ok") and key:
        try:
            _FILE_IDS[key] = j["result"]["photo"][-1]["file_id"]
        except Exception:
            pass
    elif key and not j.get("ok"):
        _FILE_IDS.pop(key, None)
    return j


async def send(chat_id, text, markup_fn=None, photo=None, reply_to=None):
    """Send HTML text/photo. markup_fn(styled)->markup. Falls back to unstyled buttons."""
    last = None
    for styled in (True, False):
        markup = markup_fn(styled) if markup_fn else None
        try:
            if photo is not None:
                j = await _post_photo(chat_id, photo, text, markup, reply_to)
                if not j.get("ok") and isinstance(photo, str) and _FILE_IDS.get(photo) is None:
                    pass
            else:
                payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                           "disable_web_page_preview": True}
                if markup:
                    payload["reply_markup"] = markup
                if reply_to:
                    payload["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
                j = await api("sendMessage", payload)
            if j.get("ok"):
                return j["result"]
            last = j
        except Exception as e:  # network etc.
            last = {"error": str(e)}
    log.warning("send failed: %s", str(last)[:200])
    return None


async def edit(chat_id, msg_id, text, markup_fn=None, is_photo=False):
    for styled in (True, False):
        markup = markup_fn(styled) if markup_fn else {"inline_keyboard": []}
        if is_photo:
            payload = {"chat_id": chat_id, "message_id": msg_id, "caption": text[:1024], "parse_mode": "HTML",
                       "reply_markup": markup}
            j = await api("editMessageCaption", payload)
        else:
            payload = {"chat_id": chat_id, "message_id": msg_id, "text": text, "parse_mode": "HTML",
                       "disable_web_page_preview": True, "reply_markup": markup}
            j = await api("editMessageText", payload)
        if j.get("ok") or "not modified" in str(j.get("description", "")).lower():
            return True
    return False


async def notify(uid, text, markup_fn=None):
    try:
        await send(uid, text, markup_fn)
    except Exception:
        pass


# -------------------------------------------------------------- forced join gate
_CHAT_INFO: dict = {}


async def chat_info(chat):
    """(title, url) of a forced-join chat; cached 10 min, falls back to a generic label."""
    hit = _CHAT_INFO.get(str(chat))
    if hit and time.time() - hit[0] < 600:
        return hit[1], hit[2]
    title_, url = None, None
    try:
        c = await G["manager_bot"].get_chat(chat)
        title_ = c.title or c.first_name
        if getattr(c, "username", None):
            url = f"https://t.me/{c.username}"
        elif getattr(c, "invite_link", None):
            url = c.invite_link
    except Exception:
        pass
    if not url:
        url = (f"https://t.me/{str(chat).lstrip('@')}" if isinstance(chat, str) and str(chat).startswith("@")
               else f"https://t.me/c/{str(chat).replace('-100', '')}/1")
    title_ = title_ or (str(chat) if isinstance(chat, str) else "کانال / گروه")
    _CHAT_INFO[str(chat)] = (time.time(), title_, url)
    return title_, url


async def fjoin_prompt(chat_id, uid, chats):
    infos = [await chat_info(c) for c in chats]
    text = ("برای استفاده از سلف ؛\n"
            "☑️ ابتدا باید در کانال یا گروه زیر عضو شوید\n\n"
            "☑️ پس از عضویت روی دکمه عضو شدم بزنید تا ربات فعال شه")
    rows = [[B(t[:60], "primary", url=u)] for t, u in infos]
    rows.append([B("عــضــو شــدم ✅", "success", callback_data=f"chk_manager_join_{uid}")])
    await send(chat_id, text, lambda s=True: mk(rows, s))


async def joined_all(uid):
    """None = forced join not configured, True/False otherwise."""
    dm = G["data_manager"]
    chats = dm.data.get("global_fjoin_chats", [])
    if not dm.data.get("global_fjoin_active", False) or not chats:
        return None
    CMS = G["ChatMemberStatus"]
    for chat in chats:
        try:
            m = await G["manager_bot"].get_chat_member(chat, uid)
            if m.status in (CMS.LEFT, CMS.BANNED):
                return False
        except Exception:
            return False
    return True


class _Shim:
    """Message-like wrapper so callbacks can reuse message-based helpers."""

    def __init__(self, client, user, chat):
        self._c, self.from_user, self.chat = client, user, chat
        self.chat_id = chat.id

    async def reply_text(self, text, **kw):
        return await self._c.send_message(self.chat_id, text, **kw)


async def gate(client, message) -> bool:
    """Same prompt as the global forced-join check; False if the user must join first."""
    if hasattr(message, "data") and hasattr(message, "message"):  # CallbackQuery
        message = _Shim(client, message.from_user, message.message.chat)
    elif message.__class__.__name__ == "Message" and message.from_user and getattr(message.from_user, "is_bot", False):
        return True
    try:
        await G["manager_global_fjoin_check"](client, message)
    except StopPropagation:
        return False
    return True


# ============================================================== self management
def blocked_reason(uid):
    """None if the self may run; 'restricted' (admin block) or 'expired'."""
    uid = int(uid)
    if is_admin(uid):
        return None
    if eco().restriction(uid):
        return "restricted"
    if not eco().is_active(uid):
        return "expired"
    return None


def sub_ok(uid) -> bool:
    return blocked_reason(uid) is None


def fmt_until(until) -> str:
    return "دائمی" if not until else datetime.fromtimestamp(until).strftime("%Y-%m-%d %H:%M")


def fmt_days(uid) -> str:
    if is_admin(uid):
        return "نامحدود (ادمین)"
    r = eco().restriction(uid)
    if r:
        return f"⛔ محدود ({fmt_until(r['until'])})"
    d = eco().days_left(uid)
    return f"{fa(d)} روز مانده" if d > 0 else "منقضی‌شده"


def self_state(uid):
    dm = G["data_manager"]
    ud = dm.data.get("users", {}).get(str(uid), {})
    if uid in G["ACTIVE_BOTS"]:
        return "🟢 فعال و متصل", True, True
    if ud.get("session_string"):
        return "🟡 ثبت‌شده؛ در حال اتصال یا متوقف", False, True
    return "🔴 فعال نشده", False, False


def manage_text(uid) -> str:
    st, _, _ = self_state(uid)
    bal = eco().balance(uid)
    return (title("مدیریت سلف", "⚙️") + "\n\n"
            + kv("وضعیت", st) + "\n"
            + kv("اشتراک", fmt_days(uid)) + "\n"
            + kv("الماس", f"{fa(bal)} 💎") + "\n\n"
            + "فرمان‌های سلف را در تلگرام خودت می‌نویسی؛ <code>.پنل</code> برای کنترل کامل.")


def manage_markup(uid):
    _, running, has = self_state(uid)

    def fn(styled=True):
        rows = []
        if running or has:
            rows.append([B("⏹ غیرفعال‌سازی", "danger", callback_data="rv:dask")])
        else:
            rows.append([B("▶️ فعال‌سازی", "success", callback_data="rv:act")])
        if not is_admin(uid):
            rows.append([B(f"🔁 تمدید ۳۰ روزه ({fa(E.DIAMONDS_PER_MONTH)} 💎)", "primary", callback_data="sb:buy")])
        if running:
            rows.append([B("🎛 پنل سلف", "primary", switch_inline_query_current_chat="panel")])
        return mk(rows, styled)
    return fn


async def cmd_manage(client, message):
    uid = message.from_user.id
    await send(message.chat.id, manage_text(uid), manage_markup(uid))


async def start_self_session(uid):
    ud = G["data_manager"].data.get("users", {}).get(str(uid), {})
    phone = ud.get("phone")
    sess = G["_db_decrypt"](ud.get("session_string", "") or "")
    if phone and sess:
        asyncio.create_task(G["start_bot_instance"](sess, phone, uid, "stylized"))
        return True
    return False


async def cb_self(client, cb):
    uid = cb.from_user.id
    chat_id = cb.message.chat.id if cb.message else uid
    act = (cb.data or "").split(":", 1)[-1]
    try:
        if act == "act":
            if not await gate(client, cb):  # join gate
                return await cb.answer()
            _, running, has = self_state(uid)
            if has and not sub_ok(uid):
                await cb.answer("استفاده از سلف برای حساب تو محدود شده." if blocked_reason(uid) == "restricted"
                                else "اشتراکت تمام شده؛ اول تمدید کن.", show_alert=True)
            else:
                await cb.answer()
                await G["start_handler"](client, G["_MenuMsg"](client, cb.from_user, chat_id, "فعال‌سازی سلف"))
        elif act == "dask":
            await cb.answer()
            await edit(chat_id, cb.message.id,
                       title("غیرفعال‌سازی", "⚠️") + "\n\nبا تأیید، ربات از اکانتت خارج می‌شود و سلف خاموش می‌شود. "
                       "(روزهای باقی‌مانده‌ات سر جایش می‌ماند.)\nمطمئنی؟",
                       lambda s=True: mk([[B("✅ تأیید", "success", callback_data="rv:dyes"),
                                           B("❌ لغو", "danger", callback_data="rv:dno")]], s))
        elif act == "dno":
            await cb.answer("لغو شد")
            await edit(chat_id, cb.message.id, manage_text(uid), manage_markup(uid))
        elif act == "dyes":
            await cb.answer()
            await edit(chat_id, cb.message.id, "⏳ در حال غیرفعال‌سازی…")
            try:
                await G["_deactivate_self"](uid)
                done = title("انجام شد", "✅") + "\n\nسلف خاموش شد و ربات از اکانتت خارج شد. هر وقت خواستی دوباره فعالش کن."
            except Exception as e:
                log.warning("deactivate failed: %s", e)
                done = "❌ غیرفعال‌سازی کامل انجام نشد؛ دوباره امتحان کن."
            await edit(chat_id, cb.message.id, done, manage_markup(uid))
    finally:
        cb.stop_propagation()


async def cb_sub(client, cb):
    uid = cb.from_user.id
    chat_id = cb.message.chat.id if cb.message else uid
    try:
        try:
            eco().buy_month(uid)
        except E.EconomyError as e:
            if e.code == "insufficient":
                need = E.DIAMONDS_PER_MONTH - eco().balance(uid)
                await cb.answer(f"{fa(need)} الماس کم داری.", show_alert=True)
                await send(chat_id, title("الماس کافی نیست", "💎") + f"\n\nبرای ۳۰ روز، {fa(need)} الماس دیگر لازم داری.",
                           lambda s=True: mk([[B("🛒 خرید الماس", "primary", callback_data="bg:menu"),
                                               B("💎 الماس رایگان", "success", callback_data="rf:open")]], s))
            else:
                await cb.answer("خطا", show_alert=True)
            return
        await cb.answer("✅ تمدید شد")
        if uid not in G["ACTIVE_BOTS"]:
            await start_self_session(uid)
        await edit(chat_id, cb.message.id, manage_text(uid), manage_markup(uid))
    finally:
        cb.stop_propagation()


# ================================================================= account / info
async def cmd_account(client, message):
    user = message.from_user
    uid = user.id
    touch(user, True)
    ud = G["data_manager"].data.get("users", {}).get(str(uid), {})
    phone = str(ud.get("phone") or "")
    phone_txt = ("•••• " + phone[-4:]) if len(phone) >= 4 else "ثبت نشده"
    st, _, _ = self_state(uid)
    rank = eco().rank(uid)
    cap = (title("حساب کاربری", "👤") + "\n\n"
           + kv("نام", esc(user_name(user))) + "\n"
           + kv("شناسه", f"<code>{uid}</code>") + "\n"
           + kv("شماره", phone_txt) + "\n"
           + kv("وضعیت سلف", st) + "\n"
           + kv("اشتراک", fmt_days(uid)) + "\n"
           + kv("الماس", f"{fa(eco().balance(uid))} 💎") + "\n"
           + kv("رتبه", f"#{fa(rank)}" if rank else "—"))
    photo = None
    try:
        entry = G["ACTIVE_BOTS"].get(uid)
        data = await G["_card_for_user"](uid, [G["manager_bot"], entry[0] if entry else None])
        if data:
            photo = io.BytesIO(data)
    except Exception as e:
        log.warning("account card: %s", e)
    fn = lambda s=True: mk([[B("💎 موجودی", "primary", callback_data="bal:me"),
                              B("🏆 برترین‌ها", "success", callback_data="top:me")]], s)
    await send(message.chat.id, cap, fn, photo=photo)


async def cmd_about(client, message):
    await send(message.chat.id, ABOUT_HTML, lambda s=True: mk([[B("⚙️ شروع و فعال‌سازی", "primary", callback_data="rv:act")]], s))


async def cmd_help(client, message):
    txt = (title("پشتیبانی و راهنما", "📨") + "\n\n"
           "راهنما همه‌ی دستورها را دسته‌بندی‌شده نشان می‌دهد. اگر مشکلی داشتی یا سؤالی، مستقیم به پشتیبانی پیام بده.")
    await send(message.chat.id, txt, lambda s=True: mk([[B("📖 راهنما", "primary", switch_inline_query_current_chat="help"),
                                                         B("💬 پشتیبانی", "success", url=SUPPORT_URL)]], s))


async def cmd_mini(client, message):
    url = ""
    try:
        url = G["_miniapp_public_url"]() or ""
    except Exception:
        pass
    if not url.startswith("https://"):
        return await send(message.chat.id, "مینی‌اپ فعلاً در دسترس نیست.")
    await send(message.chat.id, title("مینی‌اپ", "☑️") + "\n\nپنل کامل سلف، الماس و برترین‌ها در یک محیط شیشه‌ای.",
               lambda s=True: mk([[B("🚀 باز کردن مینی‌اپ", "success", web_app={"url": url})]], s))


# ====================================================================== balance
def balance_caption(user_id, name, bal) -> str:
    rank = eco().rank(user_id)
    return (title("موجودی", "💎") + "\n\n"
            + kv("الماس", f"<b>{fa(bal)}</b> 💎") + "\n"
            + kv("معادل", f"{fa(E.Economy.toman(bal))} تومان") + "\n\n"
            + kv("اشتراک", fmt_days(user_id)) + "\n"
            + kv("رتبه", f"#{fa(rank)}" if rank else "—"))


def balance_markup(user_id, bal):
    running = user_id in G["ACTIVE_BOTS"]
    days = "نامحدود" if is_admin(user_id) else f"{fa(eco().days_left(user_id))} روز"

    def fn(styled=True):
        return mk([[B(f"{fa(bal)} 💎", "primary", callback_data="noop")],
                   [B("✅ روشن" if running else "⛔ خاموش", "success" if running else "danger", callback_data="noop"),
                    B(days, "primary", callback_data="noop")],
                   [B(f"{fa(E.Economy.toman(bal))} تومان", "success", callback_data="noop")]], styled)
    return fn


async def cb_noop(client, cb):
    try:
        await cb.answer()
    finally:
        cb.stop_propagation()


async def build_balance_photo(user_id, username):
    import rival_cards
    bal = eco().balance(user_id)
    days = None if is_admin(user_id) else eco().days_left(user_id)
    return await asyncio.to_thread(rival_cards.balance_card, username, bal, E.Economy.toman(bal), days)


_CD: dict = {}


def cooldown(key, secs=6.0) -> bool:
    now = time.time()
    if now - _CD.get(key, 0) < secs:
        return False
    _CD[key] = now
    return True


async def cmd_balance(client, message):
    u = message.from_user
    if not u:
        return
    private = message.chat.type.name == "PRIVATE"
    if not private and not cooldown(("bal", message.chat.id, u.id)):
        return
    touch(u, private)
    bal = eco().balance(u.id)
    try:
        photo = await build_balance_photo(u.id, u.username)
    except Exception as e:
        log.warning("balance card: %s", e)
        photo = None
    await send(message.chat.id, balance_caption(u.id, user_name(u), bal), balance_markup(u.id, bal), photo=photo,
               reply_to=None if private else message.id)


MEDALS = ["🥇", "🥈", "🥉"]


def top_text(uid) -> str:
    e = eco()
    rows = e.top(10)
    gap = "\u2003"
    lines = [title("برترین‌ها", "🏆"), ""]
    if not rows:
        lines.append("هنوز کسی الماس ندارد.")
    for i, r in enumerate(rows):
        medal = MEDALS[i] if i < 3 else f"<b>{i + 1}.</b>"
        nm = r.get("name") or (("@" + r["username"]) if r.get("username") else str(r["uid"]))
        me = "  ⟵ تو" if r["uid"] == uid else ""
        lines.append(f"{medal}{gap}{mention(r['uid'], nm)}{me}")
        lines.append(f"{gap}{gap}💎 <b>{fa(r['balance'])}</b>")
        lines.append("")
    rank = e.rank(uid)
    if rank and rank > 10:
        lines += [f"📍 جایگاه تو{gap}<b>#{fa(rank)}</b>", f"{gap}{gap}💎 <b>{fa(e.balance(uid))}</b>"]
    elif not rank:
        lines.append("هنوز در جدول نیستی؛ الماس بگیر و بالا بیا.")
    return "\n".join(lines).rstrip()


async def cmd_top(client, message):
    u = message.from_user
    if not u:
        return
    if message.chat.type.name != "PRIVATE" and not cooldown(("top", message.chat.id), 10):
        return
    touch(u, message.chat.type.name == "PRIVATE")
    await send(message.chat.id, top_text(u.id), reply_to=message.id if message.chat.type.name != "PRIVATE" else None)


async def cb_bal_top(client, cb):
    u = cb.from_user
    try:
        await cb.answer()
        chat_id = cb.message.chat.id if cb.message else u.id
        if cb.data.startswith("bal:"):
            m = type("M", (), {"from_user": u, "chat": cb.message.chat, "id": cb.message.id})()
            await cmd_balance(client, m)
        else:
            await send(chat_id, top_text(u.id))
    finally:
        cb.stop_propagation()


# ======================================================================= shop
PRESETS = [500, 1000, 5000, 10000]


def shop_text() -> str:
    return (title("خرید الماس", "🛒") + "\n\n"
            + kv("نرخ", f"هر ۵۰۰ 💎 = {fa(500 * E.TOMAN_PER_DIAMOND)} تومان") + "\n"
            + kv("حداقل", f"{fa(E.MIN_BUY)} 💎") + "\n"
            + kv("اشتراک", f"{fa(E.DIAMONDS_PER_MONTH)} 💎 = ۳۰ روز سلف") + "\n\n"
            "یک بسته انتخاب کن یا مقدار دلخواهت را بفرست.")


def shop_markup(styled=True):
    rows = [[B(f"{fa(p)} 💎 · {fa(p * E.TOMAN_PER_DIAMOND)} ت", "primary", callback_data=f"bg:n:{p}")
             for p in PRESETS[i:i + 2]] for i in range(0, len(PRESETS), 2)]
    rows.append([B("✍️ مقدار دلخواه", "success", callback_data="bg:custom")])
    return mk(rows, styled)


async def cmd_buy(client, message):
    if not await gate(client, message):
        return
    touch(message.from_user, True)
    await send(message.chat.id, shop_text(), shop_markup)


def pay_info() -> str:
    card = eco().get_setting("pay_card", "")
    return card or "<i>روش پرداخت هنوز توسط ادمین تنظیم نشده؛ از پشتیبانی بپرس.</i>"


def invoice_text(inv) -> str:
    left = max(0, int((inv["expires_at"] - time.time()) // 60))
    return (title(f"فاکتور #{fa(inv['id'])}", "🧾") + "\n\n"
            + kv("مقدار", f"{fa(inv['diamonds'])} 💎") + "\n"
            + kv("مبلغ", f"<b>{fa(inv['toman'])}</b> تومان") + "\n"
            + kv("اعتبار", f"{fa(left)} دقیقه") + "\n\n"
            + "<b>پرداخت</b>\n" + pay_info() + "\n\n"
            "بعد از پرداخت، <b>عکس رسید</b> را همین‌جا بفرست تا ادمین بررسی و الماس را اضافه کند.")


async def make_invoice(chat_id, uid, amount):
    try:
        inv = eco().create_invoice(uid, amount)
    except E.EconomyError as e:
        if e.code == "min_buy":
            return await send(chat_id, f"حداقل خرید {fa(E.MIN_BUY)} الماس است.")
        if e.code == "open_invoice":
            inv = eco().get_invoice(int(str(e)))
            return await send(chat_id, "یک فاکتور باز داری:\n\n" + invoice_text(inv),
                              lambda s=True: mk([[B("❌ لغو فاکتور", "danger", callback_data=f"bg:x:{inv['id']}")]], s))
        return await send(chat_id, "خطا در ساخت فاکتور.")
    await send(chat_id, invoice_text(inv),
               lambda s=True: mk([[B("❌ لغو فاکتور", "danger", callback_data=f"bg:x:{inv['id']}")]], s))


STATE: dict = {}


async def cb_shop(client, cb):
    uid = cb.from_user.id
    chat_id = cb.message.chat.id if cb.message else uid
    parts = cb.data.split(":")
    try:
        if not is_admin(uid) and not await gate(client, cb):
            return await cb.answer()
        touch(cb.from_user, True)
        if parts[1] == "menu":
            await cb.answer()
            await send(chat_id, shop_text(), shop_markup)
        elif parts[1] == "n":
            await cb.answer()
            await make_invoice(chat_id, uid, int(parts[2]))
        elif parts[1] == "custom":
            await cb.answer()
            STATE[uid] = {"k": "amount", "ts": time.time()}
            await send(chat_id, f"مقدار الماس را بفرست (حداقل {fa(E.MIN_BUY)}).\nبرای لغو: <code>لغو</code>")
        elif parts[1] == "x":
            try:
                eco().reject_invoice(int(parts[2]), uid, "لغو توسط کاربر")
                await cb.answer("فاکتور لغو شد")
                await edit(chat_id, cb.message.id, "❌ فاکتور لغو شد.")
            except E.EconomyError:
                await cb.answer("این فاکتور قبلاً بسته شده.", show_alert=True)
    finally:
        cb.stop_propagation()


async def on_receipt(client, message):
    """Photo/document from a user with an open invoice -> forward to admins."""
    u = message.from_user
    if not u or is_admin(u.id) or u.id in G["LOGIN_STATES"]:
        return
    inv = eco().open_invoice_of(u.id)
    if not inv:
        return
    media = message.photo or message.document
    fuid = getattr(media, "file_unique_id", None)
    if not fuid:
        return
    try:
        inv = eco().attach_receipt(inv["id"], u.id, fuid, str(message.id))
    except E.EconomyError as e:
        txt = {"receipt_reused": "این رسید قبلاً استفاده شده است.",
               "expired": "فاکتور منقضی شده؛ دوباره بساز."}.get(e.code, "ثبت رسید ممکن نشد.")
        await send(message.chat.id, txt)
        return message.stop_propagation()
    cap = (title(f"رسید فاکتور #{fa(inv['id'])}", "🧾") + "\n\n"
           + kv("کاربر", mention(u.id, user_name(u)) + (f" @{u.username}" if u.username else "")) + "\n"
           + kv("آیدی", f"<code>{u.id}</code>") + "\n"
           + kv("مقدار", f"{fa(inv['diamonds'])} 💎") + "\n"
           + kv("مبلغ", f"{fa(inv['toman'])} تومان"))
    fn = lambda s=True: mk([[B("✅ تأیید", "success", callback_data=f"ad:ok:{inv['id']}"),
                              B("❌ رد", "danger", callback_data=f"ad:no:{inv['id']}")]], s)
    for a in admins():
        try:
            await client.forward_messages(a, message.chat.id, message.id)
            await send(a, cap, fn)
        except Exception as e:
            log.warning("receipt -> admin %s failed: %s", a, e)
    await send(message.chat.id, "✅ رسید دریافت شد؛ بعد از تأیید ادمین، الماس به حسابت اضافه می‌شود.")
    message.stop_propagation()


async def cb_admin_invoice(client, cb):
    aid = cb.from_user.id
    try:
        if not is_admin(aid):
            return await cb.answer("اجازه نداری.", show_alert=True)
        _, act, sid = cb.data.split(":")
        inv_id = int(sid)
        try:
            if act == "ok":
                inv = eco().approve_invoice(inv_id, aid)
                await cb.answer("✅ تأیید شد")
                await edit(cb.message.chat.id, cb.message.id,
                           title(f"فاکتور #{fa(inv_id)} تأیید شد", "✅") + f"\n\n{fa(inv['diamonds'])} 💎 به {mention(inv['uid'])} اضافه شد.")
                await notify(inv["uid"], title("پرداخت تأیید شد", "✅") + f"\n\n{fa(inv['diamonds'])} 💎 به حسابت اضافه شد.\n"
                             f"موجودی: <b>{fa(eco().balance(inv['uid']))}</b> 💎")
            else:
                inv = eco().reject_invoice(inv_id, aid, "رد شد")
                await cb.answer("رد شد")
                await edit(cb.message.chat.id, cb.message.id, title(f"فاکتور #{fa(inv_id)} رد شد", "❌"))
                await notify(inv["uid"], "❌ رسید تأیید نشد. اگر پرداخت کرده‌ای به پشتیبانی پیام بده.")
        except E.EconomyError as e:
            await cb.answer("این فاکتور قبلاً بررسی شده." if e.code == "closed" else "خطا", show_alert=True)
    finally:
        cb.stop_propagation()


# ================================================================= free diamonds
async def cmd_free(client, message):
    if not await gate(client, message):
        return
    await send_referral(message.chat.id, message.from_user)


async def send_referral(chat_id, user):
    touch(user, True)
    uname = G.get("BOT_USERNAME") or ""
    link = f"https://t.me/{uname}?start=ref_{user.id}"
    st = eco().ref_stats(user.id)
    cap = (title("الماس رایگان", "🎁") + "\n\n"
           "دوستانت را با لینک اختصاصی دعوت کن:\n\n"
           f"◈ ورود دوست و عضویت در کانال/گپ ⟢ <b>{fa(E.REF_INVITER_JOIN)} 💎</b> برای تو، "
           f"<b>{fa(E.REF_INVITEE_JOIN)} 💎</b> برای او\n"
           f"◈ فعال ماندن سلف او تا {fa(E.REF_ACTIVE_DAYS)} روز ⟢ <b>{fa(E.REF_INVITER_ACTIVE)} 💎</b> دیگر برای تو\n\n"
           f"🔗 لینک تو:\n<code>{link}</code>\n\n"
           f"دعوت‌ها: {fa(st['total'])} · وارد شده: {fa(st['joined'])} · سلف‌فعال: {fa(st['active'])} · درآمد: {fa(st['earned'])} 💎\n\n"
           "کد هدیه داری؟ دکمه‌ی پایین را بزن.")
    share = "https://t.me/share/url?url=" + link + "&text=" + "سلف%20ریوال؛%20دستیار%20هوشمند%20تلگرام%20با%20الماس%20رایگان"
    await send(chat_id, cap, lambda s=True: mk([[B("📤 اشتراک‌گذاری لینک", "primary", url=share)],
                                                 [B("🎁 ثبت کد هدیه", "success", callback_data="rf:gift")]], s), photo="referral")


async def cb_referral(client, cb):
    try:
        await cb.answer()
        uid = cb.from_user.id
        chat_id = cb.message.chat.id if cb.message else uid
        if not await gate(client, cb):
            return
        if cb.data == "rf:gift":
            STATE[uid] = {"k": "gift", "ts": time.time()}
            await send(chat_id, title("کد هدیه", "🎁") + "\n\nکد هدیه را بفرست.\nلغو: <code>لغو</code>")
        else:
            await send_referral(chat_id, cb.from_user)
    finally:
        cb.stop_propagation()


async def on_start_ref(client, message):
    """Record /start ref_<id> (does not stop propagation: the normal /start flow continues)."""
    u = message.from_user
    if not u or getattr(u, "is_bot", False):
        return
    touch(u, True)
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) == 2 and parts[1].strip() == "mini":
        await cmd_mini(client, message)
        return
    if len(parts) == 2 and parts[1].strip() == "gift":
        if await joined_all(u.id) is not False:
            STATE[u.id] = {"k": "gift", "ts": time.time()}
            await send(u.id, title("کد هدیه", "🎁") + "\n\nکد هدیه را بفرست.\nلغو: <code>لغو</code>")
        return
    if len(parts) < 2 or not parts[1].startswith("ref_"):
        return
    inv = to_int(parts[1][4:])
    if not inv or is_admin(u.id):
        return
    if str(u.id) in G["data_manager"].data.get("users", {}):
        return  # not a new user
    try:
        if eco().ref_register(u.id, inv):
            asyncio.create_task(try_confirm_ref(u.id))
    except Exception as e:
        log.warning("ref register: %s", e)


async def try_confirm_ref(uid):
    try:
        if await joined_all(uid) is not True:
            return
        res = eco().ref_confirm_join(uid)
    except E.EconomyError:
        return
    except Exception as e:
        log.warning("ref confirm: %s", e)
        return
    if res:
        await notify(res["inviter"], title("دعوت موفق", "🎉") + f"\n\nیک نفر با لینکت وارد شد.\n+{fa(res['inviter_gain'])} 💎\n"
                     f"اگر سلفش را {fa(E.REF_ACTIVE_DAYS)} روز فعال نگه دارد، {fa(E.REF_INVITER_ACTIVE)} 💎 دیگر می‌گیری.")
        await notify(uid, title("هدیه‌ی خوش‌آمد", "🎁") + f"\n\n+{fa(res['invitee_gain'])} 💎 به حسابت اضافه شد.")


async def cb_joined(client, cb):
    uid = cb.from_user.id
    try:
        ok = await joined_all(uid)
        if ok is False:
            return await cb.answer("هنوز در همه‌ی کانال‌ها/گپ‌ها عضو نشدی.", show_alert=True)
        await cb.answer("✅ عضویت تأیید شد")
        try:
            await cb.message.delete()
        except Exception:
            pass
        await try_confirm_ref(uid)
        await G["send_main_menu"](cb.message.chat.id if cb.message else uid)
    finally:
        cb.stop_propagation()


# ===================================================================== games
def official_chat():
    return eco().get_setting("official_chat")


def _name_of(uid):
    with eco()._lock:
        r = eco()._c.execute("SELECT name,username FROM wallets WHERE uid=?", (uid,)).fetchone()
    return (r["name"] or ("@" + r["username"] if r["username"] else None)) if r else None


def pname(uid):
    return mention(uid, _name_of(uid) or uid)


def game_markup_open(gid):
    return lambda s=True: mk([[B("🎲 پیوستن", "success", callback_data=f"gm:j:{gid}"),
                                B("🚫 لغو", "danger", callback_data=f"gm:c:{gid}")]], s)


def result_markup(prize, wbal, lbal):
    def fn(styled=True):
        return mk([[B("جایزه", "primary", callback_data="noop"), B(fa(prize), "primary", callback_data="noop")],
                   [B("موجودی برنده", "success", callback_data="noop"), B(fa(wbal), "success", callback_data="noop")],
                   [B("موجودی بازنده", "danger", callback_data="noop"), B(fa(lbal), "danger", callback_data="noop")]], styled)
    return fn


def draw_markup(stake):
    return lambda s=True: mk([[B("برگشت شرط", "primary", callback_data="noop"), B(f"{fa(stake)} 💎", "primary", callback_data="noop")]], s)


def board_text(board):
    sym = {"X": "❌", "O": "⭕", "": "▫️"}
    return "\n".join("".join(sym[board[r * 3 + c]] for c in range(3)) for r in range(3))


def table_caption(kind, creator_id, stake):
    nm = "دوز" if kind == "ttt" else "شرطی"
    return (f"🎮 <b>میز جدید بازی {nm}</b>\n\n"
            f"👤 سازنده: {pname(creator_id)}\n"
            f"👥 تعداد بازیکن: 2 نفر\n"
            f"💰 مبلغ ورودی: {fa(stake)} 💎\n"
            f"🔝 جایزه برنده: {fa(E.Economy.prize_of(stake))} 💎\n\n"
            f"✍️ منتظر پیوستن بازیکن دوم هستیم…\n"
            f"⏱ مهلت پیوستن: {E.GAME_TTL // 60} دقیقه")


async def official_gate(message, what):
    chat = message.chat
    off = official_chat()
    if not off:
        if cooldown(("noff", chat.id), 30):
            await send(chat.id, "گپ رسمی هنوز تنظیم نشده است.", reply_to=message.id)
        return False
    if chat.id != off:
        if cooldown(("woff", chat.id), 30):
            await send(chat.id, f"{what} فقط در گپ رسمی ممکن است.", reply_to=message.id)
        return False
    return True


async def new_game(client, message, kind, stake):
    u = message.from_user
    if not u or getattr(u, "is_bot", False):
        return
    chat = message.chat
    if not await official_gate(message, "🎮 بازی‌ها"):
        return
    touch(u)
    if not cooldown(("newgame", u.id), 3):
        return
    ag = eco().active_game_of(u.id)
    if ag:
        if ag["status"] == "open":
            return await send(chat.id, "⏳ بازی قبلی‌ات هنوز کسی نپیوسته.\nیا لغوش کن، یا صبر کن تا کسی بپیوندد.",
                              lambda s=True, i=ag["id"]: mk([[B("🚫 لغو بازی قبلی", "danger", callback_data=f"gm:c:{i}")]], s),
                              reply_to=message.id)
        return await send(chat.id, "🎮 الان وسط یک بازی هستی؛ بعد از پایانش می‌توانی بازی جدید بسازی.", reply_to=message.id)
    try:
        g = eco().game_create(kind, chat.id, u.id, stake)
    except E.EconomyError as e:
        msg = {"stake_min": f"حداقل مبلغ ورودی {fa(E.BET_MIN)} الماس است.",
               "stake_max": f"حداکثر مبلغ ورودی {fa(E.BET_MAX)} الماس است.",
               "insufficient": "الماس کافی نداری. در پیوی ربات «الماس رایگان» یا «خرید الماس» را بزن."}.get(e.code, "خطا")
        return await send(chat.id, msg, reply_to=message.id)
    res = await send(chat.id, table_caption(kind, u.id, stake), game_markup_open(g["id"]),
                     photo="dooz" if kind == "ttt" else "bet")
    if res:
        eco().game_set_msg(g["id"], res["message_id"])
    else:
        eco().game_cancel(g["id"], force=True)


def ttt_markup(gid, board, over=False):
    def fn(styled=True):
        rows = []
        for r in range(3):
            row = []
            for c in range(3):
                v = board[r * 3 + c]
                label = {"X": "❌", "O": "⭕"}.get(v, "▫️")
                style = {"X": "danger", "O": "primary"}.get(v)
                row.append(B(label, style, callback_data=("gm:z" if over else f"gm:m:{gid}:{r * 3 + c}")))
            rows.append(row)
        return mk(rows, styled)
    return fn


def ttt_caption(g, st):
    turn_uid = st["x"] if st["turn"] == "X" else st["o"]
    return ("🎮 <b>بازی دوز</b>\n\n"
            f"❌ {pname(st['x'])}\n⭕ {pname(st['o'])}\n\n"
            f"💰 مبلغ ورودی: {fa(g['stake'])} 💎\n"
            f"🔝 جایزه برنده: {fa(E.Economy.prize_of(g['stake']))} 💎\n\n"
            f"🎯 نوبت: {pname(turn_uid)} {'❌' if st['turn'] == 'X' else '⭕'}\n"
            f"⏱ مهلت هر حرکت: {E.MOVE_TTL} ثانیه")


def settle_view(kind, g, winner, board=None, note=""):
    """(caption, markup_fn) for a finished (non-draw) game; money must already be settled."""
    loser = g["opponent"] if winner == g["creator"] else g["creator"]
    nm = "دوز" if kind == "ttt" else "شرطی"
    cap = f"🏁 <b>نتیجه‌ی بازی {nm}</b>\n\n"
    if board:
        cap += board_text(board) + "\n\n"
    if note:
        cap += note + "\n\n"
    cap += f"🏆 برنده: {pname(winner)}\n💔 بازنده: {pname(loser)}"
    prize = E.Economy.prize_of(g["stake"])
    return cap, result_markup(prize, eco().balance(winner), eco().balance(loser))


def _st(g):
    try:
        return json.loads(g["state"]) if g.get("state") else None
    except Exception:
        return None


async def cb_game(client, cb):
    u = cb.from_user
    parts = cb.data.split(":")
    chat_id = cb.message.chat.id if cb.message else None
    mid = cb.message.id if cb.message else None
    try:
        if parts[1] == "z":
            return await cb.answer()
        gid = int(parts[2])
        g = eco().game_get(gid)
        if not g:
            return await cb.answer("بازی پیدا نشد.", show_alert=True)
        touch(u)
        if parts[1] == "c":
            if u.id != g["creator"] and not is_admin(u.id):
                return await cb.answer("فقط سازنده می‌تواند لغو کند.", show_alert=True)
            try:
                eco().game_cancel(gid, force=is_admin(u.id))
            except E.EconomyError:
                return await cb.answer("بازی دیگر قابل لغو نیست.", show_alert=True)
            await cb.answer("لغو شد و مبلغ برگشت.")
            if g.get("msg_id"):
                await edit(g["chat_id"], g["msg_id"], "⛔ بازی توسط سازنده لغو شد.", None, True)
            if mid and mid != g.get("msg_id"):
                await edit(chat_id, mid, "✅ بازی قبلی لغو شد و مبلغ برگشت؛ حالا می‌توانی بازی جدید بسازی.", None, False)
            return
        if parts[1] == "j":
            if eco().active_game_of(u.id, exclude=gid):
                return await cb.answer("تو یک بازی فعال داری؛ اول تمامش کن یا لغوش کن.", show_alert=True)
            try:
                g = eco().game_join(gid, u.id)
            except E.EconomyError as e:
                return await cb.answer({"insufficient": "الماس کافی نداری.", "self_join": "با خودت نمی‌شود بازی کرد.",
                                        "not_open": "این بازی دیگر باز نیست.", "expired": "بازی منقضی شد."}.get(e.code, "خطا"),
                                       show_alert=True)
            await cb.answer("پیوستی! 🎲")
            if g["kind"] == "bet":
                await edit(chat_id, mid, "🎲 <b>بازی شرطی</b>\n\n"
                           f"{pname(g['creator'])}  🆚  {pname(g['opponent'])}\n\n⏳ قرعه‌کشی…", None, True)
                await asyncio.sleep(2.0)
                r = eco().game_pick_winner(gid)
                cap, mk_ = settle_view("bet", r, r["winner"])
                await edit(chat_id, mid, cap, mk_, True)
            else:
                st = {"board": [""] * 9, "turn": "X", "x": g["creator"], "o": g["opponent"], "ts": time.time()}
                eco().game_state(gid, st)
                await edit(chat_id, mid, ttt_caption(g, st), ttt_markup(gid, st["board"]), True)
            return
        if parts[1] == "m":
            async with _GL.setdefault(gid, asyncio.Lock()):
                return await _ttt_move(cb, gid, int(parts[3]), chat_id, mid)
    except Exception as e:
        log.exception("game callback: %s", e)
        try:
            await cb.answer("خطای موقت؛ دوباره امتحان کن.", show_alert=True)
        except Exception:
            pass
    finally:
        cb.stop_propagation()


_GL: dict = {}


async def _ttt_move(cb, gid, idx, chat_id, mid):
    u = cb.from_user
    g = eco().game_get(gid)
    st = _st(g)
    if g["status"] != "running" or not st:
        return await cb.answer("بازی تمام شده.", show_alert=True)
    cur = st["x"] if st["turn"] == "X" else st["o"]
    if u.id not in (st["x"], st["o"]):
        return await cb.answer("بازیکن نیستی.", show_alert=True)
    if u.id != cur:
        return await cb.answer("نوبت تو نیست.", show_alert=True)
    if st["board"][idx]:
        return await cb.answer("این خانه پر است.", show_alert=True)
    st["board"][idx] = st["turn"]
    res = E.ttt_winner(st["board"])
    if res is None:
        st["turn"] = "O" if st["turn"] == "X" else "X"
        st["ts"] = time.time()
        eco().game_state(gid, st)
        await cb.answer()
        return await edit(chat_id, mid, ttt_caption(g, st), ttt_markup(gid, st["board"]), True)
    eco().game_state(gid, st)
    await cb.answer()
    if res == "draw":
        eco().game_finish(gid, None)
        await edit(chat_id, mid, "🏁 <b>نتیجه‌ی بازی دوز</b>\n\n" + board_text(st["board"]) + "\n\n🤝 مساوی شد؛ مبلغ ورودی هر دو برگشت.",
                   draw_markup(g["stake"]), True)
    else:
        winner = st["x"] if res == "X" else st["o"]
        r = eco().game_finish(gid, winner)
        cap, mk_ = settle_view("ttt", r, winner, st["board"])
        await edit(chat_id, mid, cap, mk_, True)


async def games_tick():
    """Cancel un-joined games (5 min) and forfeit stalled tic-tac-toe moves (60 s)."""
    e = eco()
    for gid in e.games_expired():
        try:
            g = e.game_cancel(gid, force=True)
            if g.get("msg_id"):
                await edit(g["chat_id"], g["msg_id"], "⌛ زمان پیوستن تمام شد؛ بازی باطل و مبلغ ورودی برگشت.", None, True)
        except Exception:
            pass
    with e._lock:
        rows = e._c.execute("SELECT * FROM games WHERE status='running' AND kind='ttt'").fetchall()
    for r in rows:
        g = dict(r)
        st = _st(g)
        if not st or time.time() - st.get("ts", time.time()) < E.MOVE_TTL:
            continue
        loser = st["x"] if st["turn"] == "X" else st["o"]
        winner = st["o"] if loser == st["x"] else st["x"]
        try:
            done = e.game_finish(g["id"], winner)
            cap, mk_ = settle_view("ttt", done, winner, st["board"],
                                   note=f"⌛ {pname(loser)} در {E.MOVE_TTL} ثانیه حرکت نکرد.")
            if g.get("msg_id"):
                await edit(g["chat_id"], g["msg_id"], cap, mk_, True)
        except Exception:
            pass



def parse_duration(text):
    """'24 ساعت' / '7 روز' / '30 دقیقه' / '2d' -> seconds; '0' -> 0 (never); invalid -> None."""
    t = (text or "").translate(_EN).strip().lower()
    if t in ("0", "بدون", "نامحدود", "ندارد", "دائمی"):
        return 0
    m = re.fullmatch(r"(\d+)\s*(دقیقه|ساعت|روز|m|h|d)?", t)
    if not m:
        return None
    mult = {"دقیقه": 60, "m": 60, "ساعت": 3600, "h": 3600, "روز": 86400, "d": 86400}[m.group(2) or "ساعت"]
    return int(m.group(1)) * mult


def fmt_duration(sec) -> str:
    if not sec:
        return "بدون انقضا"
    if sec % 86400 == 0:
        return f"{sec // 86400} روز"
    if sec % 3600 == 0:
        return f"{sec // 3600} ساعت"
    return f"{max(1, sec // 60)} دقیقه"


async def need_started(chat_id, uid) -> bool:
    if eco().has_started(uid):
        return True
    await send(chat_id, "❌ آیدی اشتباه است؛ این کاربر ربات را استارت نکرده و حساب ندارد.")
    return False


GIFT_ERR = {"code_invalid": "این کد وجود ندارد.", "code_expired": "این کد منقضی شده است.",
            "code_full": "ظرفیت این کد تمام شده است.", "code_used": "قبلاً از این کد استفاده کرده‌ای."}


async def redeem_code(chat_id, user, code):
    try:
        r = eco().gift_redeem(code, user.id)
    except E.EconomyError as e:
        return await send(chat_id, "❌ " + GIFT_ERR.get(e.code, "کد معتبر نیست."))
    await send(chat_id, title("کد هدیه ثبت شد", "🎁") + "\n\n"
               + kv("دریافت", f"<b>+{fa(r['amount'])}</b> 💎") + "\n"
               + kv("موجودی", f"{fa(r['balance'])} 💎"))


def gift_text(g) -> str:
    left = max(0, g["capacity"] - g["used"])
    exp = fmt_until(g["expires_at"]) if g["expires_at"] else "بدون انقضا"
    return (title("کد هدیه", "🎁") + "\n\n"
            + kv("کد", f"<code>{esc(g['code'])}</code>") + "\n"
            + kv("جایزه", f"{fa(g['amount'])} 💎 برای هر نفر") + "\n"
            + kv("ظرفیت", f"{fa(g['used'])} / {fa(g['capacity'])} (باقی‌مانده {fa(left)})") + "\n"
            + kv("اعتبار", exp if g["expires_at"] else "بدون انقضا") + "\n"
            + kv("وضعیت", "🟢 فعال" if g["active"] else "⚫ حذف شده"))


GC_STEPS = [("code", "متن کد را بفرست (حروف و عدد، یا بنویس «تصادفی»):"),
            ("amount", "چند الماس برای هر نفر؟"),
            ("dur", "مدت اعتبار؟ مثال: 24 ساعت · 7 روز · 30 دقیقه (یا 0 = بدون انقضا)"),
            ("cap", "ظرفیت: چند نفر می‌توانند استفاده کنند؟")]


async def transfer_cmd(client, message):
    m = message.matches[0]
    amount, ref = to_int(m.group(1)), m.group(2)
    u = message.from_user
    if not u or getattr(u, "is_bot", False) or not amount:
        return
    if not await official_gate(message, "🔄 انتقال الماس"):
        return
    touch(u)
    if not cooldown(("xfer", u.id), 3):
        return
    target = None
    rm = message.reply_to_message
    if rm and rm.from_user and not getattr(rm.from_user, "is_bot", False):
        target = rm.from_user.id
    elif ref:
        target = eco().find_user(int(ref) if ref.isdigit() else ref)
    chat = message.chat.id
    if not target:
        return await send(chat, "👤 گیرنده مشخص نیست.\nروی پیام او ریپلای کن و بنویس <code>انتقال 100</code> "
                          "(یا <code>انتقال 100 @username</code>).", reply_to=message.id)
    try:
        r = eco().transfer(u.id, target, amount)
    except E.EconomyError as e:
        need = amount + eco().transfer_fee(amount)
        txt = {"no_account": "❌ این کاربر حساب ندارد؛ باید ابتدا ربات را استارت کند.",
               "self_transfer": "❌ انتقال به خودت ممکن نیست.",
               "transfer_min": f"❌ حداقل انتقال {fa(E.TRANSFER_MIN)} الماس است.",
               "insufficient": f"❌ الماس کافی نداری. برای این انتقال {fa(need)} 💎 لازم است."}.get(e.code, "❌ انتقال انجام نشد.")
        return await send(chat, txt, reply_to=message.id)
    label = eco().user_label(target)
    label = label if label.startswith("@") else mention(target, label)
    txt = ("🔄 <b>انتقال الماس انجام شد.</b>\n\n"
           f"💎 تعداد {fa(r['amount'])} الماس با موفقیت به کاربر {label} انتقال داده شد.\n\n"
           f"مالیات: {E.TRANSFER_TAX_PERCENT}%\n"
           f"کسر شده: {fa(r['charged'])}💎\n\n"
           "💰 موجودی جدید دو کاربر:")
    fn = lambda s=True: mk([[B("موجودی فرستنده", "success", callback_data="noop"), B(fa(r["sender_balance"]), "success", callback_data="noop")],
                             [B("موجودی گیرنده", "danger", callback_data="noop"), B(fa(r["receiver_balance"]), "danger", callback_data="noop")]], s)
    await send(chat, txt, fn, reply_to=message.id)
    await notify(target, f"🔄 {fa(r['amount'])} 💎 از طرف {mention(u.id, user_name(u))} به حسابت منتقل شد.")


# ================================================================ admin tools
def eco_admin_text() -> str:
    e = eco()
    a = e.audit()
    now = int(time.time())
    with e._lock:
        users = e._c.execute("SELECT COUNT(*) n FROM wallets WHERE uid>0 AND started=1").fetchone()["n"]
        pend = e._c.execute("SELECT COUNT(*) n FROM invoices WHERE status IN('pending','receipt')").fetchone()["n"]
        subs = e._c.execute("SELECT COUNT(*) n FROM subs WHERE expires_at>?", (now,)).fetchone()["n"]
        restr = e._c.execute("SELECT COUNT(*) n FROM restrictions WHERE until=0 OR until>?", (now,)).fetchone()["n"]
        codes = e._c.execute("SELECT COUNT(*) n FROM gift_codes WHERE active=1").fetchone()["n"]
    off = official_chat()
    return (title("اقتصاد · مدیریت", "💎") + "\n\n"
            + kv("کاربران", fa(users)) + "\n"
            + kv("مجموع الماس", f"{fa(a['wallets'])} 💎 {'✅' if a['ok'] else '⚠️ ناهمخوان'}") + "\n"
            + kv("اشتراک فعال", fa(subs)) + "\n"
            + kv("محدودشده", fa(restr)) + "\n"
            + kv("فاکتور باز", fa(pend)) + "\n"
            + kv("کد هدیه فعال", fa(codes)) + "\n"
            + kv("گپ رسمی", f"<code>{off}</code>" if off else "تنظیم نشده") + "\n"
            + kv("هدیه‌ی شروع", f"{fa(e.get_setting('trial_days', 5))} روز") + "\n\n"
            "<b>دستورها</b>\n"
            "<code>/addgems آیدی تعداد</code>\n<code>/subgems آیدی تعداد</code>\n<code>/adddays آیدی روز</code>\n"
            "<code>/limit آیدی [مدت]</code> (بدون مدت = دائمی)\n<code>/unlimit آیدی</code>\n"
            "<code>/newcode</code> · <code>/codes</code>\n<code>/pro آیدی [مدت]</code> · <code>/unpro آیدی</code> · <code>/pros</code>\n<code>/settrial روز</code> · <code>/setcard متن</code>\n"
            "<code>/setofficial</code> (داخل گپ رسمی) · <code>/unsetofficial</code>")


def eco_admin_markup(styled=True):
    return mk([[B("🧾 فاکتورهای باز", "primary", callback_data="ad:pend"),
                B("💳 تنظیم پرداخت", "success", callback_data="ad:card")],
               [B("➕ شارژ الماس", "success", callback_data="ad:add"),
                B("➖ کسر الماس", "danger", callback_data="ad:sub")],
               [B("📅 افزودن روز", "success", callback_data="ad:days"),
                B("⛔ محدودسازی سلف", "danger", callback_data="ad:lim")],
               [B("✅ رفع محدودیت", "success", callback_data="ad:unlim"),
                B("🎁 ساخت کد هدیه", "primary", callback_data="ad:gc")],
               [B("📋 کدهای هدیه", "primary", callback_data="ad:codes"),
                B("📊 بروزرسانی", "primary", callback_data="ad:stats")],
               [B("🏹 فعال‌سازی پرو", "success", callback_data="ad:pro"),
                B("❌ لغو پرو", "danger", callback_data="ad:unpro")]], styled)


async def do_gems(chat_id, uid, n, sign=1):
    if not await need_started(chat_id, uid):
        return
    e = eco()
    ref = f"a{int(time.time() * 1000)}"
    try:
        if sign > 0:
            e.credit(uid, n, "admin_add", ref)
            await notify(uid, f"🎁 {fa(n)} 💎 توسط مدیریت به حسابت اضافه شد.")
        else:
            e.debit(uid, n, "admin_sub", ref)
    except E.EconomyError as ex:
        return await send(chat_id, "❌ موجودی کاربر کافی نیست." if ex.code == "insufficient" else f"خطا: {ex.code}")
    await send(chat_id, f"✅ موجودی {uid}: {fa(e.balance(uid))} 💎")


async def do_days(chat_id, uid, n):
    if not await need_started(chat_id, uid):
        return
    eco().add_days(uid, n)
    await send(chat_id, f"✅ {fa(n)} روز به {uid} اضافه شد ({fmt_days(uid)}).")
    if uid not in G["ACTIVE_BOTS"] and sub_ok(uid):
        await start_self_session(uid)


async def do_limit(chat_id, admin_id, uid, seconds):
    if not await need_started(chat_id, uid):
        return
    if is_admin(uid):
        return await send(chat_id, "❌ ادمین‌ها را نمی‌شود محدود کرد.")
    until = eco().restrict(uid, seconds if seconds else None, admin_id)
    if uid in G["ACTIVE_BOTS"]:
        try:
            await G["stop_user_bot"](uid)
        except Exception:
            pass
    await notify_expired(uid)
    await send(chat_id, f"⛔ سلف {uid} محدود شد ({fmt_until(until)}).")


async def do_unlimit(chat_id, uid):
    if not await need_started(chat_id, uid):
        return
    if eco().unrestrict(uid):
        await notify(uid, "✅ محدودیت سلف شما برداشته شد.")
        if uid not in G["ACTIVE_BOTS"] and sub_ok(uid):
            await start_self_session(uid)
        await send(chat_id, f"✅ محدودیت {uid} برداشته شد.")
    else:
        await send(chat_id, "این کاربر محدودیتی ندارد.")


async def do_pro(chat_id, admin_id, uid, seconds):
    if int(admin_id) != int(G.get("ROOT_ADMIN", 0)):
        return await send(chat_id, "⛔ فقط ادمین اصلی می‌تواند اشتراک پرو بدهد.")
    if not await need_started(chat_id, uid):
        return
    until = eco().pro_grant(uid, seconds if seconds else None, admin_id)
    await send(chat_id, f"🏹 پرو فعال شد برای {uid} ({fmt_until(until)}).")
    await notify(uid, title("اشتراک پرو فعال شد", "🏹") + "\n\n" + kv("مدت", fmt_until(until)) + "\n\n"
                 "حالا «پیو پیو» از منوی دسترسی سریع (`.پنل`) و مینی‌اپ برایت باز است.")


async def do_unpro(chat_id, admin_id, uid):
    if int(admin_id) != int(G.get("ROOT_ADMIN", 0)):
        return await send(chat_id, "⛔ فقط ادمین اصلی می‌تواند اشتراک پرو را لغو کند.")
    if eco().pro_revoke(uid):
        await send(chat_id, f"❌ پرو {uid} لغو شد.")
        await notify(uid, "اشتراک پرو شما لغو شد.")
    else:
        await send(chat_id, "این کاربر پرو نیست.")


async def cmd_eco_admin(client, message):
    if not is_admin(message.from_user.id):
        return
    await send(message.chat.id, eco_admin_text(), eco_admin_markup)


async def cb_admin(client, cb):
    aid = cb.from_user.id
    chat_id = cb.message.chat.id if cb.message else aid
    parts = cb.data.split(":", 2)
    act = parts[1]
    try:
        if not is_admin(aid):
            return await cb.answer("اجازه نداری.", show_alert=True)
        await cb.answer()
        prompts = {"card": ("card", "متن پرداخت را بفرست (شماره کارت، نام صاحب حساب، …). HTML ساده مجاز است."),
                   "add": ("addgems", "بفرست: <code>آیدی تعداد</code>  مثل <code>123456 500</code>"),
                   "sub": ("subgems", "بفرست: <code>آیدی تعداد</code>  مثل <code>123456 200</code>"),
                   "days": ("adddays", "بفرست: <code>آیدی روز</code>  مثل <code>123456 30</code>"),
                   "lim": ("limit", "بفرست: <code>آیدی مدت</code>  مثل <code>123456 7 روز</code>\nبدون مدت = محدودیت دائمی."),
                   "unlim": ("unlimit", "آیدی کاربر را بفرست."),
                   "pro": ("pro", "بفرست: <code>آیدی مدت</code>  مثل <code>123456 30 روز</code>\nبدون مدت = پرو دائمی. (فقط ادمین اصلی)"),
                   "unpro": ("unpro", "آیدی کاربر را بفرست. (فقط ادمین اصلی)")}
        if act == "stats":
            await edit(chat_id, cb.message.id, eco_admin_text(), eco_admin_markup)
        elif act in prompts:
            kind, txt = prompts[act]
            STATE[aid] = {"k": kind, "ts": time.time()}
            await send(chat_id, txt + "\nلغو: <code>لغو</code>")
        elif act == "gc":
            STATE[aid] = {"k": "gc", "step": 0, "data": {}, "ts": time.time()}
            await send(chat_id, title("ساخت کد هدیه", "🎁") + "\n\n" + GC_STEPS[0][1] + "\nلغو: <code>لغو</code>")
        elif act == "codes":
            rows = eco().gift_list(10)
            if not rows:
                return await send(chat_id, "هنوز کدی نساخته‌ای.")
            for g in rows:
                fn = (lambda s=True, c=g["code"]: mk([[B("🗑 حذف", "danger", callback_data=f"ad:gdel:{c}")]], s)) if g["active"] else None
                await send(chat_id, gift_text(g), fn)
        elif act == "gdel":
            ok = eco().gift_delete(parts[2])
            await send(chat_id, "🗑 کد حذف شد." if ok else "این کد قبلاً حذف شده.")
        elif act == "pend":
            with eco()._lock:
                rows = eco()._c.execute("SELECT * FROM invoices WHERE status IN('pending','receipt') ORDER BY id DESC LIMIT 10").fetchall()
            if not rows:
                return await send(chat_id, "فاکتور بازی نیست.")
            for r in rows:
                fn = lambda s=True, i=r["id"]: mk([[B("✅ تأیید", "success", callback_data=f"ad:ok:{i}"),
                                                    B("❌ رد", "danger", callback_data=f"ad:no:{i}")]], s)
                await send(chat_id, title(f"فاکتور #{fa(r['id'])}", "🧾") + f"\n\n{mention(r['uid'])} · {fa(r['diamonds'])} 💎 · "
                           f"{fa(r['toman'])} ت · {'رسید دارد' if r['status'] == 'receipt' else 'بدون رسید'}", fn)
    finally:
        cb.stop_propagation()


async def admin_commands(client, message):
    u = message.from_user
    if not u or not is_admin(u.id):
        return
    cmd = message.command[0].lower()
    args = message.command[1:]
    chat = message.chat
    e = eco()
    try:
        if cmd in ("addgems", "subgems"):
            uid, n = int(args[0]), int(args[1])
            await do_gems(chat.id, uid, abs(n), 1 if (cmd == "addgems") == (n >= 0) else -1)
        elif cmd == "adddays":
            await do_days(chat.id, int(args[0]), int(args[1]))
        elif cmd == "limit":
            dur = parse_duration(" ".join(args[1:])) if len(args) > 1 else 0
            if dur is None:
                return await send(chat.id, "مدت نامعتبر است؛ مثل <code>7 روز</code> یا <code>12 ساعت</code>.")
            await do_limit(chat.id, u.id, int(args[0]), dur)
        elif cmd == "unlimit":
            await do_unlimit(chat.id, int(args[0]))
        elif cmd == "pro":
            dur = parse_duration(" ".join(args[1:])) if len(args) > 1 else 0
            if dur is None:
                return await send(chat.id, "مدت نامعتبر است؛ مثل <code>30 روز</code> (بدون مدت = دائمی).")
            await do_pro(chat.id, u.id, int(args[0]), dur)
        elif cmd == "unpro":
            await do_unpro(chat.id, u.id, int(args[0]))
        elif cmd == "pros":
            rows = e.pro_list()
            await send(chat.id, title("کاربران پرو", "🏹") + "\n\n" + ("\n".join(
                f"◈ <code>{r['uid']}</code> ⟢ {fmt_until(r['until'])}" for r in rows) or "هنوز کسی پرو نیست."))
        elif cmd == "settrial":
            e.set_setting("trial_days", int(args[0]))
            await send(chat.id, f"✅ هدیه‌ی شروع: {fa(int(args[0]))} روز")
        elif cmd == "setcard":
            e.set_setting("pay_card", message.text.split(maxsplit=1)[1])
            await send(chat.id, "✅ اطلاعات پرداخت ذخیره شد.")
        elif cmd == "setofficial":
            if chat.type.name == "PRIVATE":
                return await send(chat.id, "این دستور را داخل گپ رسمی بزن.")
            e.set_setting("official_chat", chat.id)
            await send(chat.id, "✅ این گپ به‌عنوان گپ رسمی ثبت شد؛ بازی‌ها و انتقال الماس فقط اینجا فعال‌اند.")
        elif cmd == "unsetofficial":
            e.set_setting("official_chat", None)
            await send(chat.id, "گپ رسمی برداشته شد.")
        elif cmd == "economy":
            await send(chat.id, eco_admin_text(), eco_admin_markup)
        elif cmd == "newcode":
            STATE[u.id] = {"k": "gc", "step": 0, "data": {}, "ts": time.time()}
            await send(chat.id, title("ساخت کد هدیه", "🎁") + "\n\n" + GC_STEPS[0][1] + "\nلغو: <code>لغو</code>")
        elif cmd == "codes":
            for g in e.gift_list(10) or []:
                fn = (lambda s=True, c=g["code"]: mk([[B("🗑 حذف", "danger", callback_data=f"ad:gdel:{c}")]], s)) if g["active"] else None
                await send(chat.id, gift_text(g), fn)
    except (IndexError, ValueError):
        await send(chat.id, "قالب دستور درست نیست.")
    except E.EconomyError as ex:
        await send(chat.id, f"خطا: {ex.code}")


async def on_state_text(client, message):
    """Free-text input steps (custom amount, gift code, admin forms)."""
    u = message.from_user
    if not u or u.id not in STATE or u.id in G["LOGIN_STATES"]:
        return
    st = STATE[u.id]
    if time.time() - st["ts"] > 600:
        STATE.pop(u.id, None)
        return
    text = (message.text or "").strip()
    chat_id = message.chat.id
    if text in ("لغو", "/cancel"):
        STATE.pop(u.id, None)
        await send(chat_id, "لغو شد.")
        return message.stop_propagation()
    k = st["k"]
    try:
        if k == "amount":
            n = to_int(text)
            if not n:
                await send(chat_id, "یک عدد بفرست.")
                return message.stop_propagation()
            STATE.pop(u.id, None)
            await make_invoice(chat_id, u.id, n)
        elif k == "gift":
            STATE.pop(u.id, None)
            await redeem_code(chat_id, u, text)
        elif not is_admin(u.id):
            STATE.pop(u.id, None)
            return
        elif k == "card":
            eco().set_setting("pay_card", text)
            STATE.pop(u.id, None)
            await send(chat_id, "✅ ذخیره شد.")
        elif k in ("addgems", "subgems", "adddays"):
            a, b = text.split()[:2]
            uid, n = int(a), int(b.translate(_EN))
            STATE.pop(u.id, None)
            if k == "adddays":
                await do_days(chat_id, uid, n)
            else:
                await do_gems(chat_id, uid, abs(n), 1 if k == "addgems" else -1)
        elif k == "limit":
            parts = text.split(maxsplit=1)
            uid = int(parts[0])
            dur = parse_duration(parts[1]) if len(parts) > 1 else 0
            if dur is None:
                await send(chat_id, "مدت نامعتبر است؛ مثل <code>7 روز</code>. دوباره بفرست یا «لغو».")
                return message.stop_propagation()
            STATE.pop(u.id, None)
            await do_limit(chat_id, u.id, uid, dur)
        elif k == "unlimit":
            uid = int(text)
            STATE.pop(u.id, None)
            await do_unlimit(chat_id, uid)
        elif k == "pro":
            parts = text.split(maxsplit=1)
            dur = parse_duration(parts[1]) if len(parts) > 1 else 0
            if dur is None:
                await send(chat_id, "مدت نامعتبر است؛ مثل <code>30 روز</code>. دوباره بفرست یا «لغو».")
                return message.stop_propagation()
            STATE.pop(u.id, None)
            await do_pro(chat_id, u.id, int(parts[0]), dur)
        elif k == "unpro":
            uid = int(text)
            STATE.pop(u.id, None)
            await do_unpro(chat_id, u.id, uid)
        elif k == "gc":
            step = st["step"]
            key = GC_STEPS[step][0]
            d = st["data"]
            if key == "code":
                import secrets as _sec
                d["code"] = ("".join(_sec.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))
                             if text in ("تصادفی", "random") else text)
            elif key == "amount":
                n = to_int(text)
                if not n or n <= 0:
                    await send(chat_id, "یک عدد مثبت بفرست.")
                    return message.stop_propagation()
                d["amount"] = n
            elif key == "dur":
                dur = parse_duration(text)
                if dur is None:
                    await send(chat_id, "مدت نامعتبر است؛ مثل <code>24 ساعت</code> یا <code>7 روز</code> یا <code>0</code>.")
                    return message.stop_propagation()
                d["dur"] = dur
            else:
                n = to_int(text)
                if not n or n <= 0:
                    await send(chat_id, "یک عدد مثبت بفرست.")
                    return message.stop_propagation()
                d["cap"] = n
                STATE.pop(u.id, None)
                try:
                    g = eco().gift_create(d["code"], d["amount"], d["dur"], d["cap"], u.id)
                except E.EconomyError as ex:
                    await send(chat_id, "❌ " + (str(ex) or ex.code))
                    return message.stop_propagation()
                await send(chat_id, gift_text(g))
                return message.stop_propagation()
            st["step"] += 1
            st["ts"] = time.time()
            await send(chat_id, GC_STEPS[st["step"]][1])
    except (ValueError, E.EconomyError):
        await send(chat_id, "ورودی درست نیست؛ دوباره بفرست یا «لغو».")
    message.stop_propagation()


async def cmd_user_menu(client, message):
    await G["send_main_menu"](message.chat.id)


# ------------------------------------------------------------- backup / restore
async def send_economy_backup(target_id):
    try:
        path = f"/tmp/economy_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        e = eco()
        with e._lock:
            dst = sqlite3.connect(path)
            e._c.backup(dst)
            dst.close()
        await G["manager_bot"].send_document(target_id, path, caption="بکاپ اقتصاد (الماس‌ها، فاکتورها، بازی‌ها)")
        os.remove(path)
        return True
    except Exception as ex:
        log.warning("economy backup failed: %s", ex)
        return False


async def on_restore_doc(client, message):
    u = message.from_user
    if not u or u.id != G["ROOT_ADMIN"] or not message.document:
        return
    name = (message.document.file_name or "").lower()
    if not (name.startswith("economy") and name.endswith(".db")):
        return
    path = await client.download_media(message, file_name=f"/tmp/restore_{int(time.time())}.db")
    try:
        src = sqlite3.connect(path)
        ok = src.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        src.execute("SELECT COUNT(*) FROM wallets")
        if not ok:
            raise ValueError("integrity")
        e = eco()
        with e._lock:
            src.backup(e._c)
        src.close()
        await send(message.chat.id, "✅ دیتابیس اقتصاد بازیابی شد.")
    except Exception as ex:
        await send(message.chat.id, f"❌ فایل معتبر نیست: {esc(ex)}")
    finally:
        try:
            os.remove(path)
        except Exception:
            pass
    message.stop_propagation()


# =========================================================== subscription hooks
async def notify_expired(uid):
    e = eco()
    why = blocked_reason(uid)
    if why == "restricted":
        r = e.restriction(uid) or {"until": 0}
        marker = f"resn:{uid}:{r['until']}"
        if e.get_setting(marker):
            return
        e.set_setting(marker, True)
        await notify(uid, title("سلف محدود شد", "⛔") + "\n\n"
                     "استفاده از سلف برای حساب تو توسط مدیریت محدود شده است.\n\n"
                     + kv("مدت", fmt_until(r["until"])) + "\n\nاگر فکر می‌کنی اشتباه شده، به پشتیبانی پیام بده.",
                     lambda s=True: mk([[B("💬 پشتیبانی", "danger", url=SUPPORT_URL)]], s))
        return
    marker = f"expn:{uid}:{e.sub_expires(uid)}"
    if e.get_setting(marker):
        return
    e.set_setting(marker, True)
    await notify(uid, title("اشتراک تمام شده", "⌛") + "\n\nبرای روشن شدن سلف، اشتراکت را تمدید کن.",
                 lambda s=True: mk([[B("🔁 تمدید ۳۰ روزه", "primary", callback_data="sb:buy"),
                                     B("🛒 خرید الماس", "success", callback_data="bg:menu")]], s))


def on_login(uid, phone=None):
    """Called by finalize_login: trial days once, start the referral 3-day clock."""
    e = eco()
    try:
        key = f"trial:{uid}"
        if not e.get_setting(key) and not is_admin(uid):
            days = int(e.get_setting("trial_days", 5))
            if days > 0:
                e.add_days(uid, days)
            e.set_setting(key, True)
        e.ref_mark_activated(uid, phone)
    except Exception as ex:
        log.warning("on_login: %s", ex)


def _migrate_started():
    """Wallets that obviously talked to the bot privately count as 'started' (one-time)."""
    e = eco()
    if e.get_setting("migrated_started_v2"):
        return
    with e._tx() as c:
        c.execute("UPDATE wallets SET started=1 WHERE uid>0 AND uid IN (SELECT DISTINCT uid FROM ledger)")
        for uid in G["data_manager"].data.get("users", {}).keys():
            try:
                c.execute("INSERT OR IGNORE INTO wallets(uid,balance,created_at) VALUES(?,0,?)", (int(uid), int(time.time())))
                c.execute("UPDATE wallets SET started=1 WHERE uid=?", (int(uid),))
            except Exception:
                pass
    e.set_setting("migrated_started_v2", True)


def migrate_existing():
    """One-time grace for users who already had a self before the diamond system."""
    e = eco()
    try:
        _migrate_started()
    except Exception as ex:
        log.warning("migrate started: %s", ex)
    if e.get_setting("migrated_v1"):
        return 0
    n = 0
    days = int(e.get_setting("grace_days", 7))
    for uid, ud in G["data_manager"].data.get("users", {}).items():
        if isinstance(ud, dict) and ud.get("session_string"):
            try:
                e.add_days(int(uid), days)
                e.set_setting(f"trial:{uid}", True)
                n += 1
            except Exception:
                pass
    e.set_setting("migrated_v1", True)
    log.info("economy migration: %s users got %s grace days", n, days)
    return n


async def subs_tick():
    e = eco()
    today = datetime.now().strftime("%Y%m%d")
    for uid in list(G["ACTIVE_BOTS"].keys()):
        why = blocked_reason(uid)
        if why:
            try:
                await G["stop_user_bot"](uid)
            except Exception as ex:
                log.warning("stop blocked %s: %s", uid, ex)
            await notify_expired(uid)
            continue
        if is_admin(uid):
            continue
        left = e.days_left(uid)
        if left <= 3:
            marker = f"warn:{uid}:{today}"
            if not e.get_setting(marker):
                e.set_setting(marker, True)
                await notify(uid, title("اشتراک رو به پایان است", "⏰") + f"\n\n{fa(left)} روز دیگر سلفت متوقف می‌شود.",
                             lambda s=True: mk([[B("🔁 تمدید ۳۰ روزه", "primary", callback_data="sb:buy")]], s))
    paid = e.ref_pending_active(lambda uid: uid in G["ACTIVE_BOTS"])
    for p in paid:
        await notify(p["inviter"], title("پاداش فعال‌سازی", "🎉") + f"\n\nدوستت {E.REF_ACTIVE_DAYS} روز سلف را فعال نگه داشت.\n+{fa(p['gain'])} 💎")


async def background():
    t_sub = t_inv = 0.0
    try:
        migrate_existing()
    except Exception as ex:
        log.warning("migrate: %s", ex)
    while True:
        try:
            await games_tick()
            now = time.time()
            if now - t_inv > 60:
                t_inv = now
                eco().expire_invoices()
            if now - t_sub > 300:
                t_sub = now
                await subs_tick()
        except asyncio.CancelledError:
            raise
        except Exception as ex:
            log.warning("rival background: %s", ex)
        await asyncio.sleep(5)


def start_background():
    return asyncio.create_task(background())


# =========================================================== quick access menu (v3)
# (emoji, short label for the 3-per-row grid, full title, [(item label, help key)])
QA_CATS = [
    ("👤", "پروفایل", "پروفایل و ظاهر", [
        ("⏰ ساعت", "datetime"), ("🪪 پروفایل", "profile"), ("🖼 آواتار", "avatar"),
        ("🎨 لوگو", "logo"), ("✨ افکت", "fun")]),
    ("💬", "پیام", "پیام و تعامل", [
        ("🅱️ قالب متن", "textstyle"), ("🗂 منشی", "secretary"), ("😍 ری‌اکشن", "react"),
        ("🥇 کامنت اول", "firstcomment"), ("⭐ پریمیوم", "pemoji"), ("↩️ ریپلای", "reply"),
        ("🎯 لیست‌ها", "lists"), ("⏱ زمان‌دار", "timed")]),
    ("🛡", "امنیت", "امنیت و مدیریت", [
        ("🔒 پیوی", "security"), ("🗑 ضد حذف", "antidel"), ("🚫 فیلتر", "wordfilter"),
        ("🔗 عضویت", "fjoin"), ("👥 گروه", "group"), ("🧹 پاکسازی", "cleanexit"),
        ("🏗 ساخت", "create"), ("🔐 رمز", "crypto"), ("💾 بکاپ", "backup")]),
    ("🔎", "رسانه", "سرچ و رسانه", [
        ("🔍 جستجو", "media"), ("⬇️ دانلود", "downloader"), ("🎵 آهنگ", "music"),
        ("📥 سیو", "privatechan"), ("🎞 رسانه", "toolsmedia"), ("🖼 متادیتا", "imgmeta"),
        ("🌐 اینترنت", "tools2")]),
    ("🧠", "هوش", "هوش و ترجمه", [
        ("🤖 هوش", "ai"), ("🧠 پیشرفته", "aiplus"), ("🧩 ابزار هوش", "toolsai"), ("🌐 ترجمه", "translate")]),
    ("📣", "تبچی", "تبچی و خودکار", [
        ("📣 تبچی", "tabchi"), ("🔁 خودکار", "selfloop"), ("📡 حضور", "pres")]),
    ("🧰", "ابزار", "ابزارها", [
        ("📚 اصلی", "main"), ("🧮 ریاضی", "toolsmath"), ("🔑 رمز", "toolshash"),
        ("🕒 زمان", "toolstime"), ("ℹ️ اطلاعات", "toolsinfo"), ("💵 ارز", "rate"),
        ("👛 کیف پول", "wallet"), ("🎛 کنترل", "panel"), ("🛠 ابزارها", "tools"), ("🛰 رادار", "radar")]),
    ("🎮", "سرگرمی", "سرگرمی و الماس", [
        ("🎲 بازی", "cheat"), ("🐱 میو", "meowgame"), ("🌾 فارم", "farm"),
        ("⭕ دوز", "ttt"), ("💎 الماس", "diamond")]),
]
PP_GI = len(QA_CATS)                      # the PewPew (PRO) category sits after the regular ones

# help key -> [(setting key in miniapp_api.T/CYC, button label)]
QA_TOGGLES = {
    "datetime": [("clock", "ساعت پروفایل"), ("bio_clock", "ساعت بیو"), ("bio_date", "تاریخ بیو"), ("bio_date_type", "تقویم")],
    "profile": [("font", "استایل نام"), ("bio_font", "استایل بیو"), ("panel_color", "پنل رنگی"), ("help_color", "راهنمای رنگی")],
    "avatar": [("avatar", "آواتار زنده")],
    "textstyle": [("bold", "بولد"), ("spoiler", "اسپویلر"), ("code", "نقل و قول"), ("underline", "زیرخط"),
                  ("gradual", "تدریجی"), ("dot_commands", "دستور با نقطه")],
    "secretary": [("secretary", "منشی خودکار")],
    "firstcomment": [("first_comment", "کامنت اول")],
    "pemoji": [("pemoji", "ایموجی پریمیوم")],
    "lists": [("enemy_active", "دشمن"), ("friend_active", "دوست"), ("crash_active", "کراش")],
    "timed": [("self_destruct", "پیام پاک‌شونده")],
    "security": [("pv_lock", "قفل کامل"), ("pv_photo", "عکس"), ("pv_video", "ویدیو"), ("pv_gif", "گیف"),
                 ("pv_voice", "ویس"), ("pv_music", "آهنگ"), ("pv_sticker", "استیکر"), ("pv_loc", "لوکیشن"),
                 ("pv_emo", "ایموجی"), ("pv_txt", "متن")],
    "antidel": [("anti_delete", "ضد دیلیت"), ("anti_edit", "ضد ادیت"), ("tag_alert", "هشدار تگ"),
                ("auto_seen", "سین خودکار"), ("auto_save", "ذخیره تایم‌دار")],
    "wordfilter": [("filter_words_active", "فیلتر کلمات")],
    "fjoin": [("forced_join_active", "عضویت اجباری")],
    "pres": [("typing", "تایپینگ"), ("playing", "در حال بازی"), ("upload_photo", "ارسال عکس"),
             ("record_voice", "ضبط ویس"), ("watch_gif", "تماشای گیف")],
    "tabchi": [("tabchi_pv", "پیوی"), ("tabchi_gp", "گروه"), ("tabchi_smart", "هوشمند"), ("tabchi_speed", "سرعت")],
    "ai": [("ai_stream", "نمایش زنده"), ("ai_search", "جستجو"), ("ai_footer", "پانوشت"), ("ai_auto", "پاسخ خودکار")],
}
TRANSLATE_CHOICES = [("en", "English"), ("ru", "Русский"), ("zh-CN", "中文"), ("off", "خاموش")]

EXTRA_HELP = {
    "textstyle": "**‹ ʀɪᴠᴀʟ ›  قالب متن**\n\n"
                 "پیام‌هایی که از اکانتت می‌فرستی خودکار قالب می‌گیرند؛ لازم نیست هر بار چیزی بنویسی.\n\n"
                 "◈ `بولد` ⟢ همه‌ی پیام‌ها پررنگ\n◈ `اسپویلر` ⟢ متن مخفی تا لمس\n◈ `نقل و قول` ⟢ قالب کد\n"
                 "◈ `زیرخط` ⟢ زیرخط‌دار\n◈ `تدریجی` ⟢ متن حرف‌به‌حرف تایپ می‌شود\n\n"
                 "**نکته:** بولد، اسپویلر، نقل و قول، زیرخط و تدریجی هم‌زمان کار نمی‌کنند؛ روشن کردن یکی دیگری را خاموش می‌کند.\n"
                 "◈ `دستور با نقطه` ⟢ دستورها باید با نقطه نوشته شوند (مثل `.پنل`).",
    "antidel": "**‹ ʀɪᴠᴀʟ ›  ضد حذف و هشدارها**\n\n"
               "◈ `ضد دیلیت` ⟢ پیام‌هایی که طرف مقابل پاک می‌کند در پیام‌های ذخیره‌شده‌ات می‌ماند\n"
               "◈ `ضد ادیت` ⟢ متن قبل از ویرایش را نگه می‌دارد\n"
               "◈ `هشدار تگ` ⟢ وقتی در گروه‌ها منشنت کنند خبرت می‌کند\n"
               "◈ `سین خودکار` ⟢ پیام‌های پیوی خودکار خوانده می‌شوند\n"
               "◈ `ذخیره تایم‌دار` ⟢ عکس و ویدیوی یک‌بارمصرف در ذخیره‌شده‌ها می‌ماند",
    "pres": "**‹ ʀɪᴠᴀʟ ›  حضور و فعالیت**\n\n"
            "وضعیتی که دیگران هنگام آنلاین بودنت می‌بینند را عوض می‌کند. فقط یکی از این‌ها هم‌زمان فعال است.\n\n"
            "◈ `تایپینگ` ⟢ «در حال تایپ…»\n◈ `در حال بازی` ⟢ «در حال بازی»\n◈ `ارسال عکس` ⟢ «در حال ارسال عکس»\n"
            "◈ `ضبط ویس` ⟢ «در حال ضبط ویس»\n◈ `تماشای گیف` ⟢ «در حال دیدن گیف»",
    "translate": "**‹ ʀɪᴠᴀʟ ›  ترجمه‌ی خودکار**\n\n"
                 "◈ با انتخاب یک زبان پایین، همه‌ی پیام‌هایی که می‌فرستی خودکار به آن زبان ترجمه می‌شوند.\n"
                 "◈ `.ترجمه` روی پیام دیگران (ریپلای) ⟢ ترجمه‌ی همان پیام\n"
                 "◈ «خاموش» ترجمه‌ی خودکار را قطع می‌کند.",
    "radar": "**‹ ʀɪᴠᴀʟ ›  رادار**\n\n"
             "◈ `.رادار` (ریپلای یا `@یوزرنیم`) ⟢ گزارش کامل هویت، دیتاسنتر، گروه‌های مشترک و سابقه‌ی نام\n"
             "◈ `.کلون` (ریپلای) ⟢ کپی نام، بیو و عکس آن کاربر روی اکانتت\n"
             "◈ `.بازگردانی کامل` ⟢ برگشت به هویت اصلی\n"
             "◈ `.شکارچی` (ریپلای) ⟢ ثبت در رادار؛ هر تغییر نام، یوزرنیم، بیو یا عکس به Saved Messages می‌آید\n"
             "◈ `.شکارچی لیست` · `.شکارچی حذف` · `.شکارچی حذف همه`\n"
             "◈ `.آنالیز` ⟢ آنالیز گروه (پیام‌ها، ادمین‌ها، ربات‌ها)\n\n"
             "**توجه:** تلگرام اینکه چه کسی پروفایلت را دیده نشان نمی‌دهد؛ شماره‌ی مخفی هم مخفی می‌ماند.",
}

PP_GUIDE = ("**‹ ʀɪᴠᴀʟ ›  🏹 پیو پیو**\n\n"
            "**راه‌اندازی** (داخل خود گروه و با دستور از اکانت سلف):\n"
            "◈ `.پیو شکار روشن 5m-7m` ⟢ هر ۵ تا ۷ دقیقه (تصادفی) «پیو پیو» می‌فرستد\n"
            "◈ `.پیو فید روشن 30m-35m` ⟢ هر ۳۰ تا ۳۵ دقیقه 🥩 می‌فرستد\n"
            "◈ `.پیو آرت روشن` ⟢ هر آرت جدید را فوری با `/art` می‌گیرد\n"
            "◈ `.شلیک` روی پیام هدف (ریپلای) ⟢ هدف ثبت می‌شود و هر ۳۰ ثانیه تا کیل شلیک می‌کند\n"
            "◈ `.شلیک لیست` · `.شلیک حذف` · `.پیو دور 3` · `.پیو انتظار 10m`\n"
            "◈ `.پیو پاک روشن 1s` ⟢ پیام شلیک بعد از جواب ربات پاک شود\n"
            "◈ `.پیو توقف` ⟢ توقف اضطراری\n\n"
            "دکمه‌های زیر تنظیمات همین گپ‌هاست.")
PP_KEYS = {"h": "hunt", "f": "feed", "a": "art", "k": "kill", "s": "del_shot", "b": "del_bot"}
QA_PATTERN = (3, 3, 1, 3, 3)          # buttons per row on every page
QA_PER_PAGE = sum(QA_PATTERN)


def qa_grid(buttons, page, nav_cb):
    """Lay buttons out as 3-3-1-3-3 per page; adds ⏪/⏩ when there is more than one page."""
    start = page * QA_PER_PAGE
    chunk = buttons[start:start + QA_PER_PAGE]
    rows, i = [], 0
    for n in QA_PATTERN:
        if i >= len(chunk):
            break
        rows.append(chunk[i:i + n])
        i += n
    nav = []
    if page > 0:
        nav.append(B("⏪", "primary", callback_data=nav_cb(page - 1)))
    if start + QA_PER_PAGE < len(buttons):
        nav.append(B("⏩", "primary", callback_data=nav_cb(page + 1)))
    if nav:
        rows.append(nav)
    return rows


def _h(text: str) -> str:
    try:
        return G["_md_to_html"](text)
    except Exception:
        return esc(text)


def pro_ok(uid) -> bool:
    try:
        return int(uid) == int(G.get("ROOT_ADMIN", 0)) or eco().is_pro(int(uid))
    except Exception:
        return False


def _settings(uid) -> dict:
    fn = G.get("_rv_settings")
    if fn:
        return fn(uid)
    try:
        import miniapp_api
        return miniapp_api._settings(G, uid)
    except Exception:
        return {}


async def _apply_toggle(uid, key, val=None):
    fn = G.get("_rv_toggle")
    if fn:
        return await fn(uid, key, val)
    import miniapp_api
    return await miniapp_api.apply_toggle(G, uid, key, val)


def panel_home_markup(uid):
    bot = G.get("BOT_USERNAME") or ""

    def fn(styled=True):
        return mk([[B("⚡ دسترسی سریع", "success", callback_data=f"qa:home:{uid}"),
                    B("🤖 مینی اپ و پنل", "success", url=f"https://t.me/{bot}?start=mini")],
                   [B("✖️ بستن", "danger", callback_data=f"close_{uid}")]], styled)
    return fn


def panel_home_text(uid) -> str:
    return _h(G["_panel_caption"](uid))


def qa_home_view(uid, page=0):
    btns = [B(f"{sym} {short}", "success", callback_data=f"qa:cat:{uid}:{gi}:0")
            for gi, (sym, short, _full, _it) in enumerate(QA_CATS)]
    if pro_ok(uid):
        btns.append(B("🏹 پیو پیو", "success", callback_data=f"qa:pp:{uid}:0"))
    else:
        btns.append(B("🔒 پیو پیو", "danger", callback_data=f"qa:lock:{uid}"))
    rows = qa_grid(btns, page, lambda p: f"qa:home:{uid}:{p}")
    rows.append([B("↩️ برگشت", "danger", callback_data=f"qa:panel:{uid}")])
    names = "\n".join(f"◈ {sym} {full}" for sym, _s, full, _i in QA_CATS) + "\n◈ 🏹 پیو پیو (ویژه‌ی پرو)"
    text = ("<b>‹ ʀɪᴠᴀʟ ›  دسترسی سریع</b>\n\nهمه‌ی قابلیت‌ها در بخش‌های زیر مرتب شده‌اند:\n\n"
            f"{names}\n\nیک بخش را انتخاب کن.")
    return text, rows


def qa_cat_view(uid, gi, page=0):
    sym, _short, full, items = QA_CATS[gi]
    btns = [B(label, "primary", callback_data=f"qa:item:{uid}:{gi}:{idx}") for idx, (label, _k) in enumerate(items)]
    rows = qa_grid(btns, page, lambda p: f"qa:cat:{uid}:{gi}:{p}")
    rows.append([B("↩️ برگشت", "danger", callback_data=f"qa:home:{uid}")])
    text = f"<b>‹ ʀɪᴠᴀʟ ›  {esc(full)}</b>\n\n{sym} {len(items)} بخش؛ یکی را انتخاب کن."
    return text, rows


def _help_html(key, label) -> str:
    sec = (G.get("HELP_SECTIONS") or {}).get(key)
    if sec:
        return _h(sec["text"])
    if key in EXTRA_HELP:
        return _h(EXTRA_HELP[key])
    return f"<b>{esc(label)}</b>\n\nراهنمای این بخش هنوز آماده نیست."


def qa_item_view(uid, gi, idx):
    """Full usage guide + every setting button of that section (changes apply in place)."""
    _sym, _short, _full, items = QA_CATS[gi]
    label, key = items[idx]
    text = _help_html(key, label)
    st = _settings(uid)
    rows = []
    if key == "translate":
        cur = st.get("translate") or "off"
        rows.append([B(("🟢 " if cur == v else "") + name, "success" if cur == v else "primary",
                       callback_data=f"qa:tr:{uid}:{gi}:{idx}:{v}") for v, name in TRANSLATE_CHOICES])
    else:
        btns = []
        for n, (sk, lb) in enumerate(QA_TOGGLES.get(key, [])):
            if sk.startswith("ai_") and sk not in st:
                continue
            v = st.get(sk)
            if isinstance(v, bool) or v is None and sk not in ("font", "bio_font", "bio_date_type", "tabchi_speed"):
                btns.append(B(("🟢 " if v else "⚫ ") + lb, "success" if v else "primary", callback_data=f"qa:tg:{uid}:{gi}:{idx}:{n}"))
            else:
                btns.append(B(f"{lb}: {v}", "primary", callback_data=f"qa:tg:{uid}:{gi}:{idx}:{n}"))
        rows += qa_grid(btns, 0, lambda p: "noop")
    if QA_TOGGLES.get(key) or key == "translate":
        try:
            running = uid in G["ACTIVE_BOTS"]
        except Exception:
            running = True
        if not running:
            text += "\n\n⚠️ سلف روشن نیست؛ برای تغییر تنظیمات اول فعالش کن."
    rows.append([B("↩️ برگشت", "danger", callback_data=f"qa:cat:{uid}:{gi}:0")])
    return text[:4000], rows


def qa_pp_view(uid, page=0):
    from self_tools import pewpew
    st = pewpew.api_state(G, uid)
    chats = st["chats"]
    per = 3
    pages = max(1, -(-len(chats) // per))
    page = max(0, min(page, pages - 1))
    rows = [[B("▶️ ادامه" if st["stop"] else "🛑 توقف اضطراری", "success" if st["stop"] else "danger",
               callback_data=f"qa:ppa:{uid}:{'resume' if st['stop'] else 'stop'}")]]
    dot = lambda b: "🟢 " if b else "⚫ "
    lines = []
    for ci in range(page * per, min(len(chats), (page + 1) * per)):
        c = chats[ci]
        k = c["kill"]
        alive = sum(1 for t in c["targets"] if t["state"] == "active")
        rows.append([B(f"📍 {c['title'][:24]}", "primary", callback_data="noop")])
        rows.append([B(dot(c["hunt"]["on"]) + "🎯 شکار", "success" if c["hunt"]["on"] else "primary", callback_data=f"qa:pt:{uid}:{page}:{ci}:h"),
                     B(dot(c["feed"]["on"]) + "🥩 فید", "success" if c["feed"]["on"] else "primary", callback_data=f"qa:pt:{uid}:{page}:{ci}:f"),
                     B(dot(c["art"]["on"]) + "🎨 آرت", "success" if c["art"]["on"] else "primary", callback_data=f"qa:pt:{uid}:{page}:{ci}:a")])
        rows.append([B(dot(k["on"]) + "🔫 کیل", "success" if k["on"] else "primary", callback_data=f"qa:pt:{uid}:{page}:{ci}:k"),
                     B(dot(k["del_shot"]) + "🧹 حذف شلیک", "success" if k["del_shot"] else "primary", callback_data=f"qa:pt:{uid}:{page}:{ci}:s"),
                     B(dot(k["del_bot"]) + "🗑 حذف پاسخ", "success" if k["del_bot"] else "primary", callback_data=f"qa:pt:{uid}:{page}:{ci}:b")])
        wait = "خودکار" if not k["wait"] else f"{int(k['wait'] // 60)}m"
        lines.append(f"◈ {esc(c['title'])} ⟢ {alive}/{len(c['targets'])} هدف · دور {k['rounds'] or '∞'} · انتظار {wait}")
    if pages > 1:
        nav = []
        if page > 0:
            nav.append(B("⏪", "primary", callback_data=f"qa:pp:{uid}:{page - 1}"))
        if page < pages - 1:
            nav.append(B("⏩", "primary", callback_data=f"qa:pp:{uid}:{page + 1}"))
        rows.append(nav)
    rows.append([B("↩️ برگشت", "danger", callback_data=f"qa:home:{uid}")])
    body = "\n".join(lines) if lines else "هنوز گپی تنظیم نشده؛ داخل گروه `.پیو شکار روشن` را بزن."
    head = _h(PP_GUIDE)
    state = "\n\n⛔ <b>متوقف است</b>" if st["stop"] else ""
    return (head + "\n\n" + _h(body) + state)[:4000], rows


async def edit_inline(cb, text, rows):
    for styled in (True, False):
        payload = {"text": text, "parse_mode": "HTML", "disable_web_page_preview": True,
                   "reply_markup": mk(rows, styled)}
        if getattr(cb, "inline_message_id", None):
            payload["inline_message_id"] = cb.inline_message_id
        else:
            payload["chat_id"], payload["message_id"] = cb.message.chat.id, cb.message.id
        j = await api("editMessageText", payload)
        if j.get("ok") or "not modified" in str(j.get("description", "")).lower():
            return True
    return False


async def cb_qa(client, cb):
    try:
        p = (cb.data or "").split(":")
        uid = int(p[2])
        if cb.from_user.id != uid and cb.from_user.id != int(G.get("ROOT_ADMIN", 0)):
            return await cb.answer("این پنل مال خودت نیست.", show_alert=True)
        act = p[1]
        if act == "lock":
            return await cb.answer("🔒 پیو پیو ویژه‌ی کاربران پرو است.\nباید از طریق ادمین اشتراک پرو فعال کنی.", show_alert=True)
        if act in ("pp", "pt", "ppa") and not pro_ok(uid):
            return await cb.answer("🔒 باید از طریق ادمین اشتراک پرو فعال کنی.", show_alert=True)
        if act == "tg":
            gi, idx, n = int(p[3]), int(p[4]), int(p[5])
            skey = QA_TOGGLES[QA_CATS[gi][3][idx][1]][n][0]
            ok, err, _s = await _apply_toggle(uid, skey)
            if not ok:
                return await cb.answer(err or "انجام نشد", show_alert=True)
            await cb.answer()
            text, rows = qa_item_view(uid, gi, idx)
        elif act == "tr":
            gi, idx, val = int(p[3]), int(p[4]), p[5]
            ok, err, _s = await _apply_toggle(uid, "translate", val)
            if not ok:
                return await cb.answer(err or "انجام نشد", show_alert=True)
            await cb.answer()
            text, rows = qa_item_view(uid, gi, idx)
        elif act == "pt":
            from self_tools import pewpew
            page, ci, k = int(p[3]), int(p[4]), p[5]
            chats = pewpew.api_state(G, uid)["chats"]
            if ci >= len(chats) or k not in PP_KEYS:
                return await cb.answer("گپ پیدا نشد.", show_alert=True)
            pewpew.toggle_flag(G, uid, chats[ci]["id"], PP_KEYS[k])
            await cb.answer()
            text, rows = qa_pp_view(uid, page)
        elif act == "ppa":
            from self_tools import pewpew
            pewpew.api_op(G, uid, {"op": p[3]})
            await cb.answer("انجام شد")
            text, rows = qa_pp_view(uid, 0)
        else:
            await cb.answer()
            if act == "panel":
                return await edit_inline(cb, panel_home_text(uid), panel_home_markup(uid)(True)["inline_keyboard"])
            if act == "home":
                text, rows = qa_home_view(uid, int(p[3]) if len(p) > 3 else 0)
            elif act == "cat":
                text, rows = qa_cat_view(uid, int(p[3]), int(p[4]) if len(p) > 4 else 0)
            elif act == "item":
                text, rows = qa_item_view(uid, int(p[3]), int(p[4]))
            elif act == "pp":
                text, rows = qa_pp_view(uid, int(p[3]) if len(p) > 3 else 0)
            else:
                return
        await edit_inline(cb, text, rows)
    except Exception as e:
        log.exception("quick access: %s", e)
    finally:
        cb.stop_propagation()


# ============================================================ login code keypad
PAD_LEN = 5
PAD_MAX = 6
_KEY = ["0️⃣", "1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"]


def pad_text(digits: str, note: str = "") -> str:
    slots = [digits[i] if i < len(digits) else "-" for i in range(max(PAD_LEN, len(digits)))]
    txt = (title("کد ورود", "🔐") + "\n\n"
           "کدی که تلگرام فرستاد را با دکمه‌ها وارد کن (نه تایپ در چت؛ تایپ کد باعث باطل شدنش می‌شود).\n\n"
           f"کد: {' '.join(slots)}")
    if note:
        txt += "\n\n" + note
    return txt


def pad_markup(styled=True):
    def b(label, key, style):
        return B(label, style, callback_data=f"kp:{key}")
    rows = [[b(_KEY[0], "0", "primary"), b(_KEY[1], "1", "primary"), b(_KEY[2], "2", "primary")],
            [b(_KEY[3], "3", "primary"), b(_KEY[4], "4", "primary"), b(_KEY[5], "5", "primary")],
            [b(_KEY[6], "6", "primary"), b(_KEY[7], "7", "primary"), b(_KEY[8], "8", "primary")],
            [b(_KEY[9], "9", "primary"), b("⌫ حذف کد", "del", "danger"), b("✖️ انصراف", "cancel", "danger")],
            [b("✅ تأیید", "ok", "success")]]
    return mk(rows, styled)


async def send_code_pad(uid):
    st = G["LOGIN_STATES"].get(uid)
    if not st:
        return None
    res = await send(uid, pad_text(""), pad_markup)
    if res:
        st["pad"] = {"digits": "", "msg": res["message_id"]}
    return res


async def cb_pad(client, cb):
    uid = cb.from_user.id
    key = (cb.data or "").split(":", 1)[-1]
    try:
        st = G["LOGIN_STATES"].get(uid)
        pad = st.get("pad") if st else None
        if not st or not pad or st.get("step") != "code" or (cb.message and cb.message.id != pad["msg"]):
            await cb.answer("این صفحه منقضی شده؛ دوباره فعال‌سازی را بزن.", show_alert=True)
            return
        chat_id = cb.message.chat.id
        if key.isdigit():
            if len(pad["digits"]) >= PAD_MAX:
                return await cb.answer("کد کامل است.")
            pad["digits"] += key
            await cb.answer()
            await edit(chat_id, pad["msg"], pad_text(pad["digits"]), pad_markup)
        elif key == "del":
            pad["digits"] = pad["digits"][:-1]
            await cb.answer()
            await edit(chat_id, pad["msg"], pad_text(pad["digits"]), pad_markup)
        elif key == "cancel":
            await cb.answer("لغو شد")
            client_u = st.get("client")
            G["LOGIN_STATES"].pop(uid, None)
            if client_u:
                try:
                    await asyncio.wait_for(client_u.disconnect(), timeout=4)
                except Exception:
                    pass
            await edit(chat_id, pad["msg"], title("ورود لغو شد", "✖️") + "\n\nهر وقت خواستی از «مدیریت سلف» دوباره شروع کن.")
        elif key == "ok":
            if len(pad["digits"]) < PAD_LEN:
                return await cb.answer(f"کد باید {fa(PAD_LEN)} رقم باشد.", show_alert=True)
            await cb.answer("در حال بررسی…")
            digits = pad["digits"]
            await edit(chat_id, pad["msg"], pad_text(digits, "⏳ در حال بررسی…"))
            await G["text_handler"](client, G["_MenuMsg"](client, cb.from_user, uid, digits))
            st2 = G["LOGIN_STATES"].get(uid)
            if st2 and st2.get("step") == "code":  # wrong / expired code: let them retry
                st2["pad"]["digits"] = ""
                await edit(chat_id, st2["pad"]["msg"], pad_text("", "❌ کد اشتباه یا منقضی بود؛ دوباره وارد کن."), pad_markup)
            else:
                await edit(chat_id, pad["msg"], title("کد پذیرفته شد", "✅") + "\n\nادامه‌ی مراحل را دنبال کن.")
    except Exception as e:
        log.exception("code pad: %s", e)
    finally:
        cb.stop_propagation()


# ================================================================== registration
_BTN_ACTIONS = {"manage": cmd_manage, "acc": cmd_account, "about": cmd_about, "buy": cmd_buy,
                "help": cmd_help, "free": cmd_free, "mini": cmd_mini}


def install(g: dict):
    """Bind bot globals and register all handlers on the manager bot."""
    global G
    G = g  # live reference: BOT_USERNAME etc. change at runtime
    mb = g["manager_bot"]
    MH, CH = g["MessageHandler"], g["CallbackQueryHandler"]
    PRIV = filters.private

    async def on_button(client, message):
        if not message.from_user:
            return
        key = KEYMAP.get(norm(message.text))
        if key:
            try:
                if is_admin(message.from_user.id) or key in ("about", "help") or await gate(client, message):
                    await _BTN_ACTIONS[key](client, message)
            except StopPropagation:
                raise
            except Exception as ex:
                log.exception("button %s failed: %s", key, ex)
        message.stop_propagation()

    is_btn = filters.create(lambda _, __, m: bool(m.text) and norm(m.text) in KEYMAP)

    def reg_msg(fn, flt, group):
        mb.add_handler(MH(fn, flt), group=group)

    def reg_cb(fn, pattern, group=-13):
        mb.add_handler(CH(fn, filters.regex(pattern)), group=group)

    reg_msg(on_start_ref, PRIV & filters.command("start"), -16)
    reg_msg(on_button, PRIV & is_btn, -13)
    reg_msg(cmd_eco_admin, PRIV & filters.regex(r"^💎 اقتصاد$"), -13)
    reg_msg(cmd_user_menu, PRIV & filters.regex(r"^🔙 منوی کاربری$"), -13)
    reg_msg(admin_commands, filters.command(["addgems", "subgems", "adddays", "limit", "unlimit", "settrial",
                                             "setcard", "setofficial", "unsetofficial", "economy", "newcode", "codes",
                                             "pro", "unpro", "pros"]), -13)
    reg_msg(on_restore_doc, PRIV & filters.document, -13)
    reg_msg(on_state_text, PRIV & filters.text, -12)
    reg_msg(on_receipt, PRIV & (filters.photo | filters.document), -12)

    bal_re = r"^(?:/balance(?:@\w+)?|/موجودی|موجودی|\.موجودی)$"
    top_re = r"^(?:/top(?:@\w+)?|/برترین‌ها|برترین‌ها|برترین ها|برترینها)$"
    reg_msg(cmd_balance, filters.text & filters.regex(bal_re), -14)
    reg_msg(cmd_top, filters.text & filters.regex(top_re), -14)

    stake_re = r"^([0-9۰-۹٠-٩,٬]+)$"

    async def bet_cmd(client, message):
        n = to_int(message.matches[0].group(1))
        if n:
            await new_game(client, message, "bet", n)

    async def dooz_cmd(client, message):
        n = to_int(message.matches[0].group(1))
        if n:
            await new_game(client, message, "ttt", n)

    reg_msg(bet_cmd, filters.group & filters.text & filters.regex(r"^(?:/bet(?:@\w+)?|بازی)\s+([0-9۰-۹٠-٩,٬]+)$"), -14)
    reg_msg(transfer_cmd, filters.group & filters.text & filters.regex(
        r"^(?:/transfer(?:@\w+)?|انتقال)\s+([0-9۰-۹٠-٩,٬]+)(?:\s+(@\w+|\d+))?$"), -14)
    reg_msg(dooz_cmd, filters.group & filters.text & filters.regex(r"^(?:/dooz(?:@\w+)?|دوز)\s+([0-9۰-۹٠-٩,٬]+)$"), -14)

    reg_cb(cb_self, r"^rv:")
    reg_cb(cb_noop, r"^noop$")
    reg_cb(cb_sub, r"^sb:")
    reg_cb(cb_shop, r"^bg:")
    reg_cb(cb_admin_invoice, r"^ad:(ok|no):")
    reg_cb(cb_admin, r"^ad:")
    reg_cb(cb_referral, r"^rf:")
    reg_cb(cb_bal_top, r"^(bal|top):")
    reg_cb(cb_game, r"^gm:")
    reg_cb(cb_joined, r"^chk_manager_join_")
    reg_cb(cb_pad, r"^kp:")
    reg_cb(cb_qa, r"^qa:")
    log.info("rival_core installed")
