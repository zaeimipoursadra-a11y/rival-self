"""PewPew self (PRO): auto-hunt, auto-feed, multi-target auto-kill, auto-art.

Commands (typed from your own account, prefix `.` or `/`):
  .پیو                         status of every configured chat
  .پیو شکار روشن [5m-7m]       send «پیو پیو» at random intervals (this chat)
  .پیو فید روشن [30m-35m]      send 🥩 at random intervals (this chat)
  .پیو آرت روشن                answer every new fan-art with /art instantly
  .پیو آرت پاک روشن [1s]       delete our /art message after a delay
  .پیو شلیک روشن|خاموش          enable the auto-kill engine in this chat
  .پیو پاک روشن [1s]           delete our «شلیک» message after the bot answered
  .پیو پاکبات روشن             also delete the game bot's reply (needs delete rights)
  .پیو دور N                   kills per target before stopping (0 = endless)
  .پیو انتظار 10m|خودکار       wait after a kill before shooting again (auto = from bot text)
  .پیو کولداون N               shared cooldown seconds (ROOT admin only)
  .پیو ربات @username          add another game bot username
  .پیو توقف | .پیو ادامه       emergency stop / resume everything
  .شلیک (reply)                add the replied user as a target and start shooting
  .شلیک حذف (reply) | .شلیک حذف همه | .شلیک لیست
"""
import asyncio
import logging
import random
import re
import time

from pyrogram import filters
from pyrogram.handlers import MessageHandler

log = logging.getLogger(__name__)

BOTS = ("pewpewiebot", "pewpewieivbot", "pewpewie3bot", "pewpewie2bot")
SHOT_TEXT = "شلیک"
HUNT_TEXT = "پیو پیو"
FEED_TEXT = "🥩"
DEFAULT_COOLDOWN = 30
REPLY_TIMEOUT = 15.0
TICK = 1.0
MAX_MISSES = 5

_G: dict = {}
_RT: dict = {}
_ENGINE: dict = {}

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


# --------------------------------------------------------------------- parsing
def norm(t: str) -> str:
    t = (t or "").translate(_DIGITS).replace("ي", "ی").replace("ك", "ک")
    return re.sub(r"\s+", " ", t.replace("\u200c", " ")).strip()


def _flat(t: str) -> str:
    return norm(t).replace(" ", "")


def parse_game_reply(text: str):
    """Classify a game-bot answer to our shot. -> (kind, number) or None.
    kinds: left, room, cd, selfdead, kill, tdead, alive"""
    t = norm(text)
    f = t.replace(" ", "")
    if "دیگهتویاینگروهنیست" in f:
        return ("left", 0)
    if "ازبیرونبهششلیک" in f or ("روم" in f and "ازبیرون" in f):
        return ("room", 0)
    if "هنوزداغه" in f or "لولهیتفنگت" in f:
        m = re.search(r"(\d+)\s*ثانیه", t)
        return ("cd", int(m.group(1)) if m else DEFAULT_COOLDOWN)
    if "ازمیدونبیرونی" in f:
        m = re.search(r"(\d+)\s*دقیقه", t)
        return ("selfdead", int(m.group(1)) if m else 10)
    if "نقشزمینشد" in f:
        m = re.search(r"تا\s*(\d+)\s*دقیقه", t)
        return ("kill", int(m.group(1)) if m else 10)
    if "همینالانمرده" in f or "زندهنمیشه" in f:
        m = re.search(r"تا\s*(\d+)\s*دقیقه", t)
        return ("tdead", int(m.group(1)) if m else 10)
    if "سلامتیباقی" in f:
        return ("alive", 0)
    return None


def is_art_drop(text: str) -> bool:
    f = _flat(text)
    return "/art" in (text or "").lower() and "آرت" in f


_UNITS = {"s": 1, "ثانیه": 1, "m": 60, "دقیقه": 60, "h": 3600, "ساعت": 3600}


def _one(tok: str):
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(s|m|h|ثانیه|دقیقه|ساعت)?", norm(tok).lower())
    if not m:
        return None
    return float(m.group(1)) * _UNITS[m.group(2) or "m"]


def parse_span(text: str):
    """'5m-7m' -> (300,420); '30s' -> (30,30); '10' -> minutes. None if invalid."""
    t = norm(text).lower().replace("–", "-").replace("تا", "-")
    parts = [p for p in re.split(r"\s*-\s*", t) if p]
    if not parts or len(parts) > 2:
        return None
    vals = [_one(p) for p in parts]
    if any(v is None or v <= 0 for v in vals):
        return None
    lo, hi = min(vals), max(vals)
    return (lo, hi)


def jitter(lo, hi) -> float:
    if hi - lo < 2:
        return float(lo)
    pad = 0.02 * (hi - lo)
    return random.uniform(lo + pad, hi - pad)


ON = ("روشن", "on", "1", "فعال")
OFF = ("خاموش", "off", "0", "غیرفعال")


def _onoff(tok):
    t = norm(tok or "").lower()
    return True if t in ON else False if t in OFF else None


# ---------------------------------------------------------------------- config
def _dm(g):
    return (g or {}).get("data_manager")


def _chat_defaults():
    return {"title": "",
            "hunt": {"on": False, "lo": 300, "hi": 420},
            "feed": {"on": False, "lo": 1800, "hi": 2100},
            "art": {"on": False, "del": False, "delay": 1.0},
            "kill": {"on": False, "del_shot": False, "delay": 1.0, "del_bot": False, "rounds": 0, "wait": 0},
            "targets": {}}


def _fill(chat):
    base = _chat_defaults()
    for k, v in base.items():
        if k not in chat:
            chat[k] = v
        elif isinstance(v, dict) and k != "targets":
            for kk, vv in v.items():
                chat[k].setdefault(kk, vv)
    return chat


def cfg_of(g, uid):
    dm = _dm(g)
    if dm is None:
        return {"stop": False, "cooldown": DEFAULT_COOLDOWN, "bots": [], "chats": {}}
    d = dm.get_user_data(uid)
    c = d.get("pewpew")
    if not isinstance(c, dict):
        c = {}
        d["pewpew"] = c
    c.setdefault("stop", False)
    c.setdefault("cooldown", DEFAULT_COOLDOWN)
    c.setdefault("bots", [])
    c.setdefault("chats", {})
    return c


def save(g, uid, cfg=None):
    dm = _dm(g)
    if dm is not None:
        dm.update_user_data(uid, {"pewpew": cfg if cfg is not None else cfg_of(g, uid)})


def chat_of(cfg, cid, title=None):
    ch = cfg["chats"].setdefault(str(cid), {})
    _fill(ch)
    if title:
        ch["title"] = title
    return ch


def bots_for(cfg):
    return set(BOTS) | {b.lower().lstrip("@") for b in cfg.get("bots", [])}


def allowed(g, uid) -> bool:
    """PRO gate: ROOT admin always, everybody else needs an active PRO grant."""
    try:
        if int(uid) == int((g or {}).get("ROOT_ADMIN", 0)):
            return True
        from . import economy
        return economy.get().is_pro(int(uid))
    except Exception:
        return False


def toggle_flag(g, uid, cid, key):
    """Panel/mini-app helper. key: hunt|feed|art|kill|del_shot|del_bot|art_del. Returns new bool or None."""
    cfg = cfg_of(g, uid)
    ch = cfg["chats"].get(str(cid))
    if not ch:
        return None
    _fill(ch)
    if key in ("hunt", "feed", "art", "kill"):
        ch[key]["on"] = not ch[key]["on"]
        new = ch[key]["on"]
    elif key in ("del_shot", "del_bot"):
        ch["kill"][key] = not ch["kill"][key]
        new = ch["kill"][key]
    elif key == "art_del":
        ch["art"]["del"] = not ch["art"]["del"]
        new = ch["art"]["del"]
    else:
        return None
    save(g, uid, cfg)
    return new


def summary_lines(cfg):
    out = []
    for cid, ch in cfg["chats"].items():
        _fill(ch)
        on = lambda b: "🟢" if b else "⚫"
        tg = ch["targets"]
        alive = sum(1 for t in tg.values() if t.get("state") == "active")
        out.append(f"• {ch.get('title') or cid}\n  شکار {on(ch['hunt']['on'])} · فید {on(ch['feed']['on'])} · "
                   f"آرت {on(ch['art']['on'])} · شلیک {on(ch['kill']['on'])} ({alive}/{len(tg)} هدف)")
    return out


# --------------------------------------------------------------------- runtime
def rt(uid):
    return _RT.setdefault(uid, {"cd": 0.0, "dead": 0.0, "rr": 0, "pending": {}, "msgs": {}, "next": {}, "miss": {}})


def _active_gate(g, uid):
    st = (g or {}).get("SELF_ACTIVE_STATUS")
    return st is None or st.get(uid, True)


def _alive(g, uid):
    return uid in (g or {}).get("ACTIVE_BOTS", {})


async def _note(client, text):
    try:
        await client.send_message("me", text)
    except Exception:
        pass


async def _delayed_delete(client, chat_id, msg_id, delay):
    try:
        await asyncio.sleep(max(0.0, float(delay)))
        await client.delete_messages(chat_id, msg_id)
    except Exception:
        pass


def _err_name(e):
    return type(e).__name__


FATAL_SEND = ("ChatWriteForbidden", "UserBannedInChannel", "ChannelPrivate", "ChatRestricted", "UserDeactivated")


async def _send_safe(client, g, uid, cid_s, text, cfg, feat):
    r = rt(uid)
    try:
        await client.send_message(int(cid_s), text)
    except Exception as e:
        n = _err_name(e)
        if n == "FloodWait":
            r["next"][(cid_s, feat)] = time.time() + int(getattr(e, "value", 30) or 30) + 2
        elif n in FATAL_SEND:
            cfg["chats"][cid_s][feat]["on"] = False
            save(g, uid, cfg)
            await _note(client, f"⚠️ پیو پیو: ارسال در «{cfg['chats'][cid_s].get('title') or cid_s}» ممکن نیست ({n}); {feat} خاموش شد.")
        else:
            log.debug("pewpew send: %s", n)


async def _tick_timers(client, g, uid, cfg):
    r, now = rt(uid), time.time()
    for cid_s, chat in list(cfg["chats"].items()):
        _fill(chat)
        for feat, text in (("hunt", HUNT_TEXT), ("feed", FEED_TEXT)):
            conf, key = chat[feat], (cid_s, feat)
            if not conf["on"]:
                r["next"].pop(key, None)
                continue
            due = r["next"].get(key)
            if due is None:
                r["next"][key] = now + random.uniform(3, 10)
                continue
            if now < due:
                continue
            r["next"][key] = now + jitter(conf["lo"], conf["hi"])
            await _send_safe(client, g, uid, cid_s, text, cfg, feat)


async def _find_msg(client, chat_id, user_id, limit=300):
    try:
        async for m in client.get_chat_history(chat_id, limit=limit):
            if m.from_user and m.from_user.id == user_id:
                return m.id
    except Exception:
        pass
    return None


def _candidates(cfg, now):
    out = []
    for cid_s, chat in cfg["chats"].items():
        _fill(chat)
        if not chat["kill"]["on"]:
            continue
        for tid_s, t in chat["targets"].items():
            if t.get("state") == "active" and t.get("next", 0) <= now:
                out.append((cid_s, tid_s))
    return sorted(out)


async def _tick_kill(client, g, uid, cfg):
    r, now = rt(uid), time.time()
    if now < r["cd"] or now < r["dead"]:
        return
    cands = _candidates(cfg, now)
    if not cands:
        return
    cid_s, tid_s = cands[r["rr"] % len(cands)]
    r["rr"] += 1
    await _shoot(client, g, uid, cfg, cid_s, tid_s)


def _target_label(t, tid_s):
    return t.get("name") or ("@" + t["username"] if t.get("username") else tid_s)


async def _shoot(client, g, uid, cfg, cid_s, tid_s):
    r, now = rt(uid), time.time()
    chat = cfg["chats"][cid_s]
    t = chat["targets"][tid_s]
    kc = chat["kill"]
    label = _target_label(t, tid_s)
    msg_id = r["msgs"].get((cid_s, tid_s)) or t.get("msg")
    if not msg_id:
        msg_id = await _find_msg(client, int(cid_s), int(tid_s))
    if not msg_id:
        t["state"] = "off"
        save(g, uid, cfg)
        await _note(client, f"⚠️ پیو پیو: پیامی از {label} پیدا نشد؛ شلیک به او خاموش شد. روی یکی از پیام‌هایش ریپلای و `.شلیک` را بزن.")
        return
    r["cd"] = now + float(cfg.get("cooldown", DEFAULT_COOLDOWN))      # optimistic: never double fire
    try:
        sent = await client.send_message(int(cid_s), SHOT_TEXT, reply_to_message_id=int(msg_id))
    except Exception as e:
        n = _err_name(e)
        if n == "FloodWait":
            r["cd"] = now + int(getattr(e, "value", 30) or 30) + 2
        elif n in FATAL_SEND:
            kc["on"] = False
            save(g, uid, cfg)
            await _note(client, f"⚠️ پیو پیو: در «{chat.get('title') or cid_s}» نمی‌توانم پیام بفرستم ({n}); شلیک خاموش شد.")
        else:                                  # reply target probably deleted -> look it up again next time
            r["msgs"].pop((cid_s, tid_s), None)
            t["msg"] = None
            r["cd"] = now + 2
        return
    fut = asyncio.get_running_loop().create_future()
    r["pending"][sent.id] = (cid_s, fut)
    try:
        res = await asyncio.wait_for(fut, REPLY_TIMEOUT)
    except asyncio.TimeoutError:
        res = None
    finally:
        r["pending"].pop(sent.id, None)
    await apply_result(client, g, uid, cfg, cid_s, tid_s, res)
    if kc.get("del_shot"):
        asyncio.create_task(_delayed_delete(client, int(cid_s), sent.id, kc.get("delay", 1.0)))
    if kc.get("del_bot") and res and len(res) > 2 and res[2]:
        asyncio.create_task(_delayed_delete(client, int(cid_s), res[2], kc.get("delay", 1.0)))


async def apply_result(client, g, uid, cfg, cid_s, tid_s, res):
    """Update target/self state from the game bot's answer (pure state logic, easy to test)."""
    r, now = rt(uid), time.time()
    chat = cfg["chats"][cid_s]
    t = chat["targets"][tid_s]
    kc = chat["kill"]
    label = _target_label(t, tid_s)
    title = chat.get("title") or cid_s
    if res is None:
        k = r["miss"][(cid_s, tid_s)] = r["miss"].get((cid_s, tid_s), 0) + 1
        t["next"] = now + float(cfg.get("cooldown", DEFAULT_COOLDOWN))
        if k >= MAX_MISSES:
            t["state"] = "off"
            r["miss"][(cid_s, tid_s)] = 0
            await _note(client, f"⚠️ پیو پیو: ربات بازی به شلیک‌ها در «{title}» جواب نداد؛ شلیک به {label} خاموش شد.")
    else:
        r["miss"][(cid_s, tid_s)] = 0
        kind, num = res[0], res[1]
        if kind == "kill":
            t["kills"] = t.get("kills", 0) + 1
            rounds = int(kc.get("rounds", 0) or 0)
            if rounds and t["kills"] >= rounds:
                t["state"] = "done"
                await _note(client, f"✅ پیو پیو: {label} در «{title}» {t['kills']} بار کیل شد؛ هدف تمام شد.")
            else:
                wait = float(kc.get("wait", 0) or 0) or (num * 60 + 10)
                t["next"] = now + wait
        elif kind == "alive":
            t["next"] = 0
        elif kind == "cd":
            r["cd"] = now + num + 1.2
        elif kind == "selfdead":
            r["dead"] = now + num * 60 + 5
        elif kind == "tdead":
            t["next"] = now + num * 60 + 8
        elif kind in ("left", "room"):
            t["state"] = "off"
            why = "دیگر در این گروه نیست" if kind == "left" else "در روم دیگری است (یا در روم نیست) و از بیرون نمی‌شود به او شلیک کرد"
            await _note(client, f"⚠️ پیو پیو: {label} {why}؛ شلیک به او خاموش شد. (گروه: «{title}»)")
    save(g, uid, cfg)


async def _engine(client, g, uid):
    try:
        while _alive(g, uid):
            try:
                cfg = cfg_of(g, uid)
                if allowed(g, uid) and not cfg.get("stop") and _active_gate(g, uid):
                    await _tick_timers(client, g, uid, cfg)
                    await _tick_kill(client, g, uid, cfg)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("pewpew engine: %s: %s", _err_name(e), e)
            await asyncio.sleep(TICK)
    finally:
        _ENGINE.pop(uid, None)


async def resume(client, g):
    """Called by self_tools after the self starts (the client may not be connected yet)."""
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
    t = _ENGINE.get(uid)
    if t and not t.done():
        return
    _ENGINE[uid] = asyncio.create_task(_engine(client, g, uid))


# -------------------------------------------------------------------- handlers
async def on_bot_message(client, message):
    g = _G
    uid = client.me.id
    u = message.from_user
    if not u or not u.username:
        return
    cfg = cfg_of(g, uid)
    if u.username.lower() not in bots_for(cfg) or not allowed(g, uid) or cfg.get("stop"):
        return
    cid_s = str(message.chat.id)
    chat = cfg["chats"].get(cid_s)
    if not chat:
        return
    _fill(chat)
    text = message.text or message.caption or ""
    if chat["art"]["on"] and is_art_drop(text):
        try:
            sent = await client.send_message(message.chat.id, "/art", reply_to_message_id=message.id)
            if chat["art"].get("del"):
                asyncio.create_task(_delayed_delete(client, message.chat.id, sent.id, chat["art"].get("delay", 1.0)))
        except Exception as e:
            log.debug("art grab failed: %s", _err_name(e))
        return
    parsed = parse_game_reply(text)
    if not parsed:
        return
    r = rt(uid)
    rid = getattr(message, "reply_to_message_id", None)
    key = rid if rid in r["pending"] and r["pending"][rid][0] == cid_s else None
    if key is None:
        key = next((m for m, (c, f) in r["pending"].items() if c == cid_s and not f.done()), None)
    if key is not None and not r["pending"][key][1].done():
        r["pending"][key][1].set_result((parsed[0], parsed[1], message.id))


async def on_group_message(client, message):
    u = message.from_user
    if not u or u.is_bot:
        return
    uid = client.me.id
    chat = cfg_of(_G, uid)["chats"].get(str(message.chat.id))
    if chat and str(u.id) in chat.get("targets", {}):
        rt(uid)["msgs"][(str(message.chat.id), str(u.id))] = message.id


on_bot_message.force_group = -62
on_group_message.force_group = -61


# ----------------------------------------------------- panel / mini-app helpers
def api_state(g, uid) -> dict:
    ok = allowed(g, uid)
    cfg = cfg_of(g, uid)
    out = {"ok": True, "allowed": ok, "stop": cfg["stop"], "cooldown": cfg["cooldown"],
           "root": int(uid) == int((g or {}).get("ROOT_ADMIN", 0)), "chats": []}
    if not ok:
        return out
    for cid, ch in sorted(cfg["chats"].items()):
        _fill(ch)
        out["chats"].append({
            "id": cid, "title": ch.get("title") or cid,
            "hunt": dict(ch["hunt"]), "feed": dict(ch["feed"]), "art": dict(ch["art"]),
            "kill": {k: ch["kill"][k] for k in ("on", "del_shot", "del_bot", "delay", "rounds", "wait")},
            "targets": [{"id": k, "name": t.get("name") or t.get("username") or k, "state": t.get("state"),
                         "kills": t.get("kills", 0)} for k, t in ch["targets"].items()]})
    return out


def api_op(g, uid, b: dict) -> dict:
    """Mini-app operations. Returns api_state()-shaped dict (+ok/err)."""
    if not allowed(g, uid):
        return {"ok": False, "locked": True, "err": "باید از طریق ادمین اشتراک پرو فعال کنی."}
    cfg = cfg_of(g, uid)
    op, cid = b.get("op"), str(b.get("cid", ""))
    ch = cfg["chats"].get(cid) if cid else None
    err = ""
    if op == "stop":
        cfg["stop"] = True
    elif op == "resume":
        cfg["stop"] = False
    elif op == "cooldown":
        if int(uid) != int((g or {}).get("ROOT_ADMIN", 0)):
            err = "کول‌داون را فقط ادمین اصلی می‌تواند عوض کند."
        else:
            cfg["cooldown"] = max(1, int(b.get("n", DEFAULT_COOLDOWN)))
    elif ch is None:
        err = "گپ پیدا نشد."
    elif op == "toggle":
        if toggle_flag(g, uid, cid, b.get("key")) is None:
            err = "کلید نامعتبر."
    elif op == "rounds":
        ch["kill"]["rounds"] = max(0, int(b.get("n", 0)))
    elif op == "wait":
        ch["kill"]["wait"] = max(0, float(b.get("n", 0)))
    elif op == "span":
        feat = b.get("feat")
        if feat not in ("hunt", "feed"):
            err = "نامعتبر."
        else:
            lo, hi = float(b.get("lo", 0)), float(b.get("hi", 0))
            if lo <= 0 or hi < lo:
                err = "بازه نامعتبر."
            else:
                ch[feat]["lo"], ch[feat]["hi"] = lo, hi
                rt(uid)["next"].pop((cid, feat), None)
    elif op == "target_remove":
        ch["targets"].pop(str(b.get("tid", "")), None)
    elif op == "target_reset":
        t = ch["targets"].get(str(b.get("tid", "")))
        if t:
            t.update(state="active", next=0)
    else:
        err = "عملیات نامعتبر."
    if not err:
        save(g, uid, cfg)
    st = api_state(g, uid)
    st["ok"], st["err"] = not err, err
    return st


# -------------------------------------------------------------------- commands
LOCK_TEXT = "🔒 پیو پیو ویژه‌ی کاربران پرو است.\nباید از طریق ادمین اشتراک پرو فعال کنی."


async def _reply(client, message, text, keep=False):
    """Show feedback by editing our own command message; it disappears after 10 s unless keep=True."""
    try:
        await message.edit_text(text, disable_web_page_preview=True)
    except Exception:
        try:
            await message.reply_text(text)
        except Exception:
            return
    if not keep:
        asyncio.create_task(_delayed_delete(client, message.chat.id, message.id, 10))


def _fmt_span(lo, hi):
    f = lambda v: f"{int(v // 60)}m" if v % 60 == 0 else f"{int(v)}s"
    return f(lo) if lo == hi else f"{f(lo)}-{f(hi)}"


STATUS_HELP = ("\n\nدستورها:\n`.پیو شکار روشن 5m-7m` · `.پیو فید روشن` · `.پیو آرت روشن`\n"
               "`.شلیک` (ریپلای روی هدف) · `.شلیک لیست` · `.پیو شلیک روشن`\n"
               "`.پیو پاک روشن 1s` · `.پیو دور 3` · `.پیو انتظار 10m` · `.پیو توقف`")


def status_text(cfg) -> str:
    lines = summary_lines(cfg)
    head = "🏹 **پیو پیو**" + ("  ⛔ متوقف" if cfg.get("stop") else "")
    return head + "\n\n" + ("\n".join(lines) if lines else "هنوز گپی تنظیم نشده؛ داخل گروه `.پیو شکار روشن` را بزن.") + \
        f"\n\nکول‌داون: {int(cfg.get('cooldown', DEFAULT_COOLDOWN))}s" + STATUS_HELP


async def cmd_pew(client, message):
    g, uid = _G, client.me.id
    if not allowed(g, uid):
        return await _reply(client, message, LOCK_TEXT)
    cfg = cfg_of(g, uid)
    args = message.command[1:]
    sub = norm(args[0]) if args else ""
    rest = args[1:]
    private = message.chat.type.name == "PRIVATE"
    title = getattr(message.chat, "title", None) or str(message.chat.id)
    if sub in ("", "وضعیت"):
        return await _reply(client, message, status_text(cfg), keep=True)
    if sub in ("توقف", "stop"):
        cfg["stop"] = True
        save(g, uid, cfg)
        return await _reply(client, message, "⛔ پیو پیو متوقف شد (`.پیو ادامه` برای ادامه).")
    if sub in ("ادامه", "شروع", "resume"):
        cfg["stop"] = False
        save(g, uid, cfg)
        return await _reply(client, message, "▶️ پیو پیو ادامه یافت.")
    if sub in ("کولداون", "cooldown"):
        if uid != int(g.get("ROOT_ADMIN", 0)):
            return await _reply(client, message, "⛔ کول‌داون را فقط ادمین اصلی می‌تواند عوض کند.")
        try:
            cfg["cooldown"] = max(1, int(norm(rest[0])))
        except Exception:
            return await _reply(client, message, "قالب: `.پیو کولداون 30`")
        save(g, uid, cfg)
        return await _reply(client, message, f"✅ کول‌داون مشترک: {cfg['cooldown']} ثانیه")
    if sub in ("ربات", "bot"):
        if not rest:
            return await _reply(client, message, "قالب: `.پیو ربات @username`")
        name = rest[0].lstrip("@").lower()
        if name not in cfg["bots"]:
            cfg["bots"].append(name)
            save(g, uid, cfg)
        return await _reply(client, message, f"✅ ربات @{name} اضافه شد.")
    if private:
        return await _reply(client, message, "این دستور را داخل گروه بزن.")
    chat = chat_of(cfg, message.chat.id, title)
    flag = _onoff(rest[0]) if rest else None
    if sub in ("شکار", "فید"):
        feat = "hunt" if sub == "شکار" else "feed"
        conf = chat[feat]
        span = parse_span(" ".join(rest[1:])) if len(rest) > 1 else None
        if len(rest) > 1 and span is None:
            return await _reply(client, message, "بازه نامعتبر است؛ مثل `5m-7m` یا `30s`.")
        if span:
            conf["lo"], conf["hi"] = span
        if flag is not None:
            conf["on"] = flag
        save(g, uid, cfg)
        rt(uid)["next"].pop((str(message.chat.id), feat), None)
        return await _reply(client, message, f"{'🟢' if conf['on'] else '⚫'} {sub}: {'روشن' if conf['on'] else 'خاموش'} · بازه {_fmt_span(conf['lo'], conf['hi'])}")
    if sub == "آرت":
        conf = chat["art"]
        if rest and norm(rest[0]) == "پاک":
            f2 = _onoff(rest[1]) if len(rest) > 1 else None
            if f2 is not None:
                conf["del"] = f2
            if len(rest) > 2:
                d = _one(rest[2])
                if d:
                    conf["delay"] = d
        elif flag is not None:
            conf["on"] = flag
        save(g, uid, cfg)
        return await _reply(client, message, f"🎨 آرت: {'🟢' if conf['on'] else '⚫'} · حذف /art: {'روشن' if conf['del'] else 'خاموش'}")
    if sub == "شلیک":
        if flag is not None:
            chat["kill"]["on"] = flag
            save(g, uid, cfg)
        return await _reply(client, message, f"🔫 شلیک خودکار: {'🟢 روشن' if chat['kill']['on'] else '⚫ خاموش'} · اهداف: {len(chat['targets'])}")
    if sub in ("پاک", "پاکبات"):
        key = "del_shot" if sub == "پاک" else "del_bot"
        if flag is not None:
            chat["kill"][key] = flag
        if len(rest) > 1:
            d = _one(rest[1])
            if d:
                chat["kill"]["delay"] = d
        save(g, uid, cfg)
        return await _reply(client, message, f"🧹 {'حذف پیام شلیک' if key == 'del_shot' else 'حذف پاسخ ربات'}: "
                            f"{'روشن' if chat['kill'][key] else 'خاموش'} · تاخیر {chat['kill']['delay']}s")
    if sub == "دور":
        try:
            chat["kill"]["rounds"] = max(0, int(norm(rest[0])))
        except Exception:
            return await _reply(client, message, "قالب: `.پیو دور 3` (۰ = بی‌نهایت)")
        save(g, uid, cfg)
        return await _reply(client, message, f"🔁 تعداد کیل برای هر هدف: {chat['kill']['rounds'] or 'بی‌نهایت'}")
    if sub == "انتظار":
        if rest and norm(rest[0]) in ("خودکار", "auto"):
            chat["kill"]["wait"] = 0
        else:
            sp = parse_span(" ".join(rest)) if rest else None
            if not sp:
                return await _reply(client, message, "قالب: `.پیو انتظار 10m` یا `.پیو انتظار خودکار`")
            chat["kill"]["wait"] = sp[0]
        save(g, uid, cfg)
        w = chat["kill"]["wait"]
        return await _reply(client, message, f"⏳ انتظار بعد از کیل: {'خودکار (از متن ربات)' if not w else _fmt_span(w, w)}")
    return await _reply(client, message, status_text(cfg), keep=True)


async def cmd_shoot(client, message):
    g, uid = _G, client.me.id
    if not allowed(g, uid):
        return await _reply(client, message, LOCK_TEXT)
    cfg = cfg_of(g, uid)
    args = [norm(a) for a in message.command[1:]]
    sub = args[0] if args else ""
    cid = message.chat.id
    private = message.chat.type.name == "PRIVATE"
    if private:
        return await _reply(client, message, "این دستور را داخل گروه بزن.")
    chat = chat_of(cfg, cid, getattr(message.chat, "title", None))
    rep = message.reply_to_message
    user = rep.from_user if rep and rep.from_user else None

    async def quiet(text):
        try:
            await message.delete()
        except Exception:
            pass
        await _note(client, text)

    if sub in ("لیست", "list"):
        if not chat["targets"]:
            return await _reply(client, message, "هدفی ثبت نشده.", keep=True)
        names = {"active": "🟢 فعال", "dead": "☠️", "off": "⚫ خاموش", "done": "✅ تمام"}
        lines = [f"• {_target_label(t, k)} — {names.get(t.get('state'), t.get('state'))} · کیل {t.get('kills', 0)}"
                 for k, t in chat["targets"].items()]
        return await _reply(client, message, "🎯 **اهداف این گپ**\n\n" + "\n".join(lines), keep=True)
    if sub in ("حذف", "remove"):
        if len(args) > 1 and args[1] in ("همه", "all"):
            n = len(chat["targets"])
            chat["targets"].clear()
            save(g, uid, cfg)
            return await quiet(f"🧹 {n} هدف حذف شد.")
        if not user:
            return await _reply(client, message, "روی پیام هدف ریپلای کن: `.شلیک حذف`")
        chat["targets"].pop(str(user.id), None)
        save(g, uid, cfg)
        return await quiet(f"🧹 {user.first_name or user.id} از اهداف حذف شد.")
    if not user:
        return await _reply(client, message, "روی یکی از پیام‌های هدف ریپلای کن و `.شلیک` را بزن.\n`.شلیک لیست` · `.شلیک حذف`")
    if user.is_bot:
        return await _reply(client, message, "نمی‌شود به ربات شلیک کرد.")
    name = " ".join(x for x in (user.first_name, user.last_name) if x)
    chat["targets"][str(user.id)] = {"name": name, "username": user.username or "", "state": "active",
                                     "msg": rep.id, "kills": 0, "next": 0}
    chat["kill"]["on"] = True
    rt(uid)["msgs"][(str(cid), str(user.id))] = rep.id
    save(g, uid, cfg)
    await quiet(f"🎯 هدف ثبت شد: {name or user.id} در «{chat.get('title') or cid}»\n"
                f"شلیک خودکار هر {int(cfg.get('cooldown', DEFAULT_COOLDOWN))} ثانیه تا کیل. (`.پیو توقف` برای قطع)")


def register(client):
    global _G
    _G = getattr(client, "g", None) or _G
    pre = ["/", "."]
    client.add_handler(MessageHandler(cmd_pew, filters.me & filters.command(["پیو", "pew"], prefixes=pre)), group=0)
    client.add_handler(MessageHandler(cmd_shoot, filters.me & filters.command(["شلیک", "shoot"], prefixes=pre)), group=0)
    client.add_handler(MessageHandler(on_bot_message, filters.incoming & filters.bot & filters.group), group=-62)
    client.add_handler(MessageHandler(on_group_message, filters.incoming & filters.group & ~filters.bot), group=-61)
