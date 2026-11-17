"""Radar tools (typed from your own account, prefix `.` or `/`):

  .رادار            (reply / @user / id)  deep intelligence report about a user
  .کلون             (reply)               copy name, bio and profile photos of that user
  .بازگردانی [کامل]                       restore your original identity
  .شکارچی           (reply)               add the user to the profile-hunter radar (changes -> Saved Messages)
  .شکارچی لیست | .شکارچی حذف (reply) | .شکارچی حذف همه
  .آنالیز                                 analysis of the current group

Everything here uses only data Telegram really exposes. Not available (and therefore not
faked): who viewed your profile, hidden phone numbers, history from before we first saw a user.
"""
import asyncio
import logging
import os
import time

from pyrogram import filters
from pyrogram.handlers import MessageHandler

log = logging.getLogger(__name__)
_G: dict = {}
_TASKS: dict = {}
HUNT_INTERVAL = 60
HUNT_MAX = 20
HISTORY_MAX = 12

# approximate account-creation year from the numeric id (community-known milestones)
_ID_YEARS = [(10_000_000, "۲۰۱۳"), (50_000_000, "۲۰۱۴–۲۰۱۵"), (150_000_000, "۲۰۱۶–۲۰۱۷"), (300_000_000, "۲۰۱۸"),
             (600_000_000, "۲۰۱۹"), (1_000_000_000, "۲۰۲۰"), (1_500_000_000, "۲۰۲۱"), (2_000_000_000, "۲۰۲۱–۲۰۲۲"),
             (5_000_000_000, "۲۰۲۲–۲۰۲۳"), (6_000_000_000, "۲۰۲۳–۲۰۲۴"), (6_800_000_000, "۲۰۲۴–۲۰۲۵")]


def estimate_year(uid: int) -> str:
    for limit, label in _ID_YEARS:
        if uid < limit:
            return label + " (تقریبی)"
    return "۲۰۲۵ تا ۲۰۲۶ (بسیار جدید ⚡)"


_STATUS = {"ONLINE": "🟢 آنلاین", "OFFLINE": "⚫ آفلاین", "RECENTLY": "🟡 به تازگی", "LAST_WEEK": "🟠 هفته‌ی اخیر",
           "LAST_MONTH": "🔴 ماه اخیر", "LONG_AGO": "⚪ خیلی وقت پیش"}


def status_text(st) -> str:
    name = str(getattr(st, "name", st) or "").split(".")[-1].upper()
    return _STATUS.get(name, "نامشخص")


def yn(v) -> str:
    return "بله" if v else "خیر"


def full_name(u) -> str:
    return " ".join(x for x in (getattr(u, "first_name", None), getattr(u, "last_name", None)) if x) or "—"


# --------------------------------------------------------------------- storage
def _dm(g):
    return (g or {}).get("data_manager")


def _store(g, uid):
    dm = _dm(g)
    if dm is None:
        return {"hist": {}, "hunt": {}, "orig": None}
    d = dm.get_user_data(uid)
    s = d.get("radar")
    if not isinstance(s, dict):
        s = {}
        d["radar"] = s
    s.setdefault("hist", {})
    s.setdefault("hunt", {})
    s.setdefault("orig", None)
    return s


def _save(g, uid, s):
    dm = _dm(g)
    if dm is not None:
        dm.update_user_data(uid, {"radar": s})


def record_identity(s, user_id, name, username, ts=None):
    """Append to the local name/username history when it changed (SangMata-style)."""
    h = s["hist"].setdefault(str(user_id), [])
    entry = {"n": name, "u": username or "", "t": int(ts or time.time())}
    if not h or (h[-1]["n"], h[-1]["u"]) != (entry["n"], entry["u"]):
        h.append(entry)
        del h[:-HISTORY_MAX]
        return True
    return False


def _clock(ts) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


def history_lines(s, user_id):
    h = s["hist"].get(str(user_id), [])
    return [f"• {e['n']} (@{e['u']}) [{_clock(e['t'])}]" if e["u"] else f"• {e['n']} [{_clock(e['t'])}]"
            for e in reversed(h)]


def diff_snapshot(old: dict, new: dict):
    """Human lines describing what changed between two profile snapshots."""
    out = []
    if old.get("name") != new.get("name"):
        out.append(f"👤 نام: {old.get('name') or '—'} ⟵ {new.get('name') or '—'}")
    if old.get("username") != new.get("username"):
        out.append(f"🆔 یوزرنیم: @{old.get('username') or '—'} ⟵ @{new.get('username') or '—'}")
    if old.get("bio") != new.get("bio"):
        out.append(f"📝 بیو: {old.get('bio') or '—'} ⟵ {new.get('bio') or '—'}")
    if old.get("photo") != new.get("photo"):
        out.append("📸 عکس پروفایل تغییر کرد")
    return out


def format_report(d: dict, hist: list) -> str:
    lines = ["🛰 **گزارش رادار · اطلاعات عمیق**", "",
             "**👤 هویت پایه**",
             f"◈ نام کامل ⟢ {d['name']}",
             f"◈ آیدی عددی ⟢ `{d['id']}`",
             f"◈ یوزرنیم ⟢ {('@' + d['username']) if d['username'] else 'ندارد'}",
             f"◈ یوزرنیم‌های کلکسیونی ⟢ {d['usernames'] or 'ندارد'}",
             f"◈ شماره ⟢ {d['phone']}",
             f"◈ تاریخ تولد ⟢ {d['birthday']}",
             f"◈ بیوگرافی ⟢ {d['bio'] or '—'}", "",
             "**🛡 آنالیز فنی و امنیتی**",
             f"◈ قدمت اکانت ⟢ {d['age']}",
             f"◈ دیتاسنتر ⟢ DC {d['dc']} · 📸 عکس‌ها: {d['photos']}",
             f"◈ پریمیوم ⟢ {yn(d['premium'])} · تیک آبی ⟢ {yn(d['verified'])}",
             f"◈ نوع حساب ⟢ {'🤖 ربات' if d['bot'] else '👤 انسان'} · امنیت ⟢ {d['security']}",
             f"◈ آخرین بازدید ⟢ {d['status']}",
             f"◈ مخاطب شما ⟢ {yn(d['contact'])} · کانال شخصی ⟢ {d['channel']}", "",
             "**📊 فعالیت و گروه‌های مشترک**",
             f"◈ گروه‌های مشترک ⟢ {d['common_n']}",
             f"◈ لیست ⟢ {d['common'] or '—'}",
             f"◈ پیام در این چت ⟢ {d['msgs']}",
             f"◈ آخرین پیام در این چت ⟢ {d['last_msg'] or '—'}", "",
             "**📜 سابقه‌ی نام و یوزرنیم (از لحظه‌ی دیده‌شدن)**"]
    lines += hist or ["• هنوز تغییری ثبت نشده"]
    return "\n".join(lines)


def format_group(d: dict) -> str:
    return "\n".join(["🛰 **گزارش رادار چت و آنالیز گروه**", "",
                      f"◈ عنوان ⟢ {d['title']}", f"◈ آیدی چت ⟢ `{d['id']}`",
                      f"◈ کل پیام‌ها ⟢ {d['messages']}", f"◈ اعضا ⟢ {d['members']}",
                      f"◈ ادمین‌ها ⟢ {d['admins']}", f"◈ ربات‌ها ⟢ {d['bots']}",
                      f"◈ دیلیت‌اکانت‌ها (در نمونه) ⟢ {d['deleted']}"])


# ----------------------------------------------------------------- data gather
async def _try(coro, default=None):
    try:
        return await coro
    except Exception:
        return default


async def gather_user(client, chat_id, user_id) -> dict:
    u = await client.get_users(user_id)
    chat = await _try(client.get_chat(user_id))
    photos = await _try(client.get_chat_photos_count(user_id), "نامشخص")
    common = await _try(client.get_common_chats(user_id), []) or []
    msgs = await _try(client.search_messages_count(chat_id, from_user=user_id), "نامشخص")
    last = None
    try:
        async for m in client.search_messages(chat_id, from_user=user_id, limit=1):
            last = (m.text or m.caption or "[رسانه]")[:60]
    except Exception:
        pass
    extra = getattr(u, "usernames", None) or []
    scam, fake = getattr(u, "is_scam", False), getattr(u, "is_fake", False)
    pc = getattr(chat, "personal_chat", None) if chat else None
    bday = getattr(chat, "birthday", None) if chat else None
    if bday and hasattr(bday, "day"):
        bday = f"{getattr(bday, 'day', '?')}/{getattr(bday, 'month', '?')}"
    return {"name": full_name(u), "id": u.id, "username": getattr(u, "username", None) or "",
            "usernames": "، ".join("@" + getattr(x, "username", str(x)) for x in extra if getattr(x, "username", x)),
            "phone": getattr(u, "phone_number", None) or "مخفی 🔒", "birthday": bday or "نامشخص",
            "bio": getattr(chat, "bio", "") if chat else "", "age": estimate_year(u.id),
            "dc": getattr(u, "dc_id", None) or "نامشخص", "photos": photos,
            "premium": getattr(u, "is_premium", False), "verified": getattr(u, "is_verified", False),
            "bot": getattr(u, "is_bot", False),
            "security": "🔴 مشکوک (اسکم/فیک)" if (scam or fake) else "🟢 امن و عادی",
            "status": status_text(getattr(u, "status", None)), "contact": getattr(u, "is_contact", False),
            "channel": getattr(pc, "id", None) or "-",
            "common_n": f"{len(common)} گروه", "common": "، ".join((c.title or str(c.id)) for c in common[:8]),
            "msgs": msgs, "last_msg": last}


async def _resolve(client, message):
    """-> user id from reply, @username or numeric argument."""
    rep = message.reply_to_message
    if rep and rep.from_user:
        return rep.from_user.id
    args = message.command[1:]
    if args:
        a = args[0].lstrip("@")
        return int(a) if a.lstrip("-").isdigit() else a
    return None


async def _answer(client, message, text, keep=True):
    try:
        await message.edit_text(text, disable_web_page_preview=True)
    except Exception:
        try:
            await message.reply_text(text)
        except Exception:
            return
    if not keep:
        asyncio.get_running_loop().call_later(10, lambda: asyncio.create_task(_safe_del(client, message.chat.id, message.id)))


async def _safe_del(client, chat_id, mid):
    try:
        await client.delete_messages(chat_id, mid)
    except Exception:
        pass


async def cmd_radar(client, message):
    uid, g = client.me.id, _G
    target = await _resolve(client, message)
    if target is None:
        return await _answer(client, message, "روی پیام کاربر ریپلای کن یا `.رادار @username` بزن.", keep=False)
    await _answer(client, message, "🛰 در حال اسکن…")
    try:
        d = await gather_user(client, message.chat.id, target)
    except Exception as e:
        return await _answer(client, message, f"❌ کاربر پیدا نشد ({type(e).__name__}).", keep=False)
    s = _store(g, uid)
    record_identity(s, d["id"], d["name"], d["username"])
    _save(g, uid, s)
    await _answer(client, message, format_report(d, history_lines(s, d["id"])))


# ------------------------------------------------------------------ clone
def _clone_dir(uid):
    try:
        from . import economy
        base = os.path.dirname(economy._db_path())
    except Exception:
        base = "/tmp"
    p = os.path.join(base or ".", "clone", str(uid))
    os.makedirs(p, exist_ok=True)
    return p


async def _download_photos(client, who, folder, tag, limit=5):
    paths = []
    try:
        async for i, ph in _aenum(client.get_chat_photos(who), limit):
            try:
                p = await client.download_media(ph.file_id, file_name=os.path.join(folder, f"{tag}{i}.jpg"))
                if p:
                    paths.append(p)
            except Exception:
                pass
    except Exception:
        pass
    return paths


async def _aenum(agen, limit):
    i = 0
    async for x in agen:
        if i >= limit:
            break
        yield i, x
        i += 1


async def cmd_clone(client, message):
    uid, g = client.me.id, _G
    rep = message.reply_to_message
    if not rep or not rep.from_user:
        return await _answer(client, message, "روی پیام کسی ریپلای کن و `.کلون` بزن.", keep=False)
    s = _store(g, uid)
    folder = _clone_dir(uid)
    me = await client.get_me()
    if not s["orig"]:                                    # remember the ORIGINAL identity once
        mech = await _try(client.get_chat("me"))
        s["orig"] = {"first": me.first_name or "", "last": me.last_name or "", "bio": getattr(mech, "bio", "") or "",
                     "photos": await _download_photos(client, "me", folder, "orig")}
        _save(g, uid, s)
    src = rep.from_user
    chat = await _try(client.get_chat(src.id))
    bio = (getattr(chat, "bio", "") or "")[:70]
    try:
        await client.update_profile(first_name=src.first_name or "", last_name=src.last_name or "", bio=bio)
    except Exception as e:
        return await _answer(client, message, f"❌ تغییر نام ممکن نشد ({type(e).__name__}).", keep=False)
    photos = await _download_photos(client, src.id, folder, "clone", limit=1)
    photo_ok = False
    if photos:
        try:
            try:
                old = [p.file_id async for p in client.get_chat_photos("me")]
                if old:
                    await client.delete_profile_photos(old)
            except Exception:
                pass
            await client.set_profile_photo(photo=photos[0])
            photo_ok = True
        except Exception:
            pass
    await _answer(client, message,
                  "🎭 **کلون هویت انجام شد**\n\n"
                  f"◈ نام جدید ⟢ {full_name(src)}\n◈ بیوگرافی جدید ⟢ {bio or '—'}\n"
                  f"◈ عکس پروفایل ⟢ {'🟢 کپی و ست شد' if photo_ok else '⚫ عکسی کپی نشد'}\n\n"
                  "برای بازگشت: `.بازگردانی کامل`")


async def cmd_restore(client, message):
    uid, g = client.me.id, _G
    s = _store(g, uid)
    o = s.get("orig")
    if not o:
        return await _answer(client, message, "هویتی برای بازگردانی ذخیره نشده (کلون نکرده‌ای).", keep=False)
    ok_name = ok_photo = False
    try:
        await client.update_profile(first_name=o["first"], last_name=o["last"], bio=o["bio"])
        ok_name = True
    except Exception:
        pass
    try:
        old = [p.file_id async for p in client.get_chat_photos("me")]
        if old:
            await client.delete_profile_photos(old)
    except Exception:
        pass
    for path in o.get("photos", []):
        try:
            if os.path.exists(path):
                await client.set_profile_photo(photo=path)
                ok_photo = True
        except Exception:
            pass
    for path in o.get("photos", []):
        try:
            os.remove(path)
        except Exception:
            pass
    s["orig"] = None
    _save(g, uid, s)
    await _answer(client, message, f"♻️ **بازگردانی هویت**\n\n◈ نام و بیو ⟢ {'🟢 برگشت' if ok_name else '⚫ انجام نشد'}\n"
                  f"◈ عکس‌ها ⟢ {'🟢 برگشت' if ok_photo else '⚫ عکسی نبود'}")


# ---------------------------------------------------------------- hunter radar
async def snapshot(client, user_id):
    u = await client.get_users(user_id)
    chat = await _try(client.get_chat(user_id))
    ph = getattr(chat, "photo", None) if chat else None
    return {"name": full_name(u), "username": getattr(u, "username", "") or "", "bio": getattr(chat, "bio", "") or "",
            "photo": getattr(ph, "big_file_unique_id", None) or getattr(ph, "small_file_unique_id", None) or ""}


async def cmd_hunter(client, message):
    uid, g = client.me.id, _G
    s = _store(g, uid)
    args = message.command[1:]
    sub = args[0] if args else ""
    hunt = s["hunt"]
    if sub in ("لیست", "list"):
        if not hunt:
            return await _answer(client, message, "رادار شکارچی خالی است.", keep=False)
        lines = [f"• {v['snap']['name']} (@{v['snap']['username']}) — `{k}`" if v["snap"]["username"]
                 else f"• {v['snap']['name']} — `{k}`" for k, v in hunt.items()]
        return await _answer(client, message, "🕵️ **رادار شکارچی**\n\n" + "\n".join(lines))
    if sub in ("حذف", "remove"):
        if len(args) > 1 and args[1] in ("همه", "all"):
            n = len(hunt)
            hunt.clear()
            _save(g, uid, s)
            return await _answer(client, message, f"🧹 {n} نفر از رادار حذف شد.", keep=False)
        rep = message.reply_to_message
        if not rep or not rep.from_user:
            return await _answer(client, message, "روی پیام کاربر ریپلای کن: `.شکارچی حذف`", keep=False)
        hunt.pop(str(rep.from_user.id), None)
        _save(g, uid, s)
        return await _answer(client, message, "🧹 از رادار حذف شد.", keep=False)
    target = await _resolve(client, message)
    if target is None:
        return await _answer(client, message, "روی پیام کاربر ریپلای کن و `.شکارچی` بزن.\n`.شکارچی لیست` · `.شکارچی حذف`", keep=False)
    if len(hunt) >= HUNT_MAX:
        return await _answer(client, message, f"⛔ سقف رادار {HUNT_MAX} نفر است.", keep=False)
    try:
        snap = await snapshot(client, target)
        u = await client.get_users(target)
    except Exception as e:
        return await _answer(client, message, f"❌ کاربر پیدا نشد ({type(e).__name__}).", keep=False)
    hunt[str(u.id)] = {"snap": snap, "since": int(time.time())}
    record_identity(s, u.id, snap["name"], snap["username"])
    _save(g, uid, s)
    await _answer(client, message,
                  "🕵️✅ **کاربر در رادار شکارچی ثبت شد**\n\n"
                  f"◈ نام فعلی ⟢ {snap['name']}\n◈ یوزرنیم ⟢ {('@' + snap['username']) if snap['username'] else '—'}\n"
                  f"◈ بیوگرافی ⟢ {snap['bio'] or '—'}\n\n"
                  "🔔 به محض تغییر نام، یوزرنیم، بیو یا عکس پروفایل، گزارش فوری به Saved Messages ارسال می‌شود.")


async def hunter_tick(client, g, uid):
    """One polling pass over the hunter list (pure of sleeping, easy to test)."""
    s = _store(g, uid)
    changed = False
    for k, v in list(s["hunt"].items()):
        try:
            new = await snapshot(client, int(k))
        except Exception:
            continue
        lines = diff_snapshot(v["snap"], new)
        if lines:
            record_identity(s, int(k), new["name"], new["username"])
            v["snap"] = new
            changed = True
            try:
                await client.send_message("me", f"🕵️ **تغییر در رادار شکارچی**\n\n◈ کاربر ⟢ {new['name']} (`{k}`)\n\n" + "\n".join(lines))
            except Exception:
                pass
    if changed:
        _save(g, uid, s)


async def _hunter_loop(client, g, uid):
    try:
        while uid in (g or {}).get("ACTIVE_BOTS", {}):
            try:
                if _store(g, uid)["hunt"]:
                    await hunter_tick(client, g, uid)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.debug("hunter loop: %s", e)
            await asyncio.sleep(HUNT_INTERVAL)
    finally:
        _TASKS.pop(uid, None)


async def resume(client, g):
    global _G
    _G = g or _G
    uid = None
    for _ in range(240):
        me = getattr(client, "me", None)
        if me and me.id in (g or {}).get("ACTIVE_BOTS", {}):
            uid = me.id
            break
        await asyncio.sleep(0.5)
    if uid is None:
        return
    t = _TASKS.get(uid)
    if not t or t.done():
        _TASKS[uid] = asyncio.create_task(_hunter_loop(client, g, uid))


# ---------------------------------------------------------------- group analysis
async def cmd_analyze(client, message):
    if message.chat.type.name == "PRIVATE":
        return await _answer(client, message, "این دستور را داخل گروه بزن.", keep=False)
    await _answer(client, message, "🛰 در حال آنالیز گروه…")
    cid = message.chat.id
    chat = await _try(client.get_chat(cid))
    total = await _try(client.get_chat_history_count(cid), "نامشخص")
    admins = bots = deleted = 0
    try:
        from pyrogram.enums import ChatMembersFilter
        async for _m in client.get_chat_members(cid, filter=ChatMembersFilter.ADMINISTRATORS):
            admins += 1
        async for _m in client.get_chat_members(cid, filter=ChatMembersFilter.BOTS):
            bots += 1
        n = 0
        async for m in client.get_chat_members(cid, limit=200):
            n += 1
            deleted += 1 if getattr(m.user, "is_deleted", False) else 0
    except Exception:
        pass
    await _answer(client, message, format_group({
        "title": getattr(chat, "title", None) or str(cid), "id": cid, "messages": total,
        "members": getattr(chat, "members_count", None) or "نامشخص", "admins": admins or "نامشخص",
        "bots": bots, "deleted": deleted}))


def register(client):
    global _G
    _G = getattr(client, "g", None) or _G
    pre = ["/", "."]
    for fn, names in ((cmd_radar, ["رادار", "radar"]), (cmd_clone, ["کلون", "clone"]),
                      (cmd_restore, ["بازگردانی", "restore"]), (cmd_hunter, ["شکارچی", "hunter"]),
                      (cmd_analyze, ["آنالیز", "analyze"])):
        client.add_handler(MessageHandler(fn, filters.me & filters.command(names, prefixes=pre)), group=0)
