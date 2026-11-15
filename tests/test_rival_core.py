"""Offline tests for rival_core (no Telegram, no Pyrogram needed: tiny stubs are injected)."""
import asyncio, os, sys, tempfile, types, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["ECONOMY_DB"] = os.path.join(tempfile.mkdtemp(), "e.db")

try:
    import pyrogram  # noqa
except Exception:
    pg = types.ModuleType("pyrogram")
    class StopPropagation(Exception): ...
    class _F:
        def __getattr__(self, n): return self
        def __call__(self, *a, **k): return self
        def __and__(self, o): return self
        def __or__(self, o): return self
        def __invert__(self): return self
    pg.StopPropagation = StopPropagation
    pg.filters = types.SimpleNamespace(create=lambda f: _F(), regex=lambda *a, **k: _F(), command=lambda *a, **k: _F(),
        private=_F(), group=_F(), text=_F(), photo=_F(), document=_F(), me=_F())
    sys.modules["pyrogram"] = pg

try:
    import aiohttp  # noqa
except Exception:
    sys.modules["aiohttp"] = types.ModuleType("aiohttp")

import rival_core as R
from self_tools import economy as E


class FakeDM:
    def __init__(self): self.data = {"users": {}, "global_fjoin_active": False, "global_fjoin_chats": []}
    def get_admins(self): return [1]


SENT = []
EDITS = []

async def fake_send(chat_id, text, markup_fn=None, photo=None, reply_to=None):
    SENT.append((chat_id, text, markup_fn(True) if markup_fn else None, photo))
    return {"message_id": len(SENT)}

async def fake_edit(chat_id, msg_id, text, markup_fn=None, is_photo=False):
    EDITS.append((chat_id, msg_id, text, markup_fn(True) if markup_fn else None))
    return True

R.send, R.edit = fake_send, fake_edit
R.G.update({"data_manager": FakeDM(), "ROOT_ADMIN": 1, "ACTIVE_BOTS": {}, "LOGIN_STATES": {}, "BOT_USERNAME": "selfrival_bot"})
R.eco = lambda: E.get()


class U:
    def __init__(self, id, first="A", username=None): self.id, self.first_name, self.last_name, self.username, self.is_bot = id, first, None, username, False

class CB:
    def __init__(self, user, data, msg_id=1, chat=None):
        self.from_user, self.data = user, data
        self.message = types.SimpleNamespace(id=msg_id, chat=chat or types.SimpleNamespace(id=user.id))
        self.answers = []
    async def answer(self, text="", show_alert=False): self.answers.append((text, show_alert))
    def stop_propagation(self): pass

def run(c): return asyncio.get_event_loop().run_until_complete(c) if False else asyncio.run(c)


def test_keyboard_layout_and_matching():
    kb = R.main_kb_json(True)["keyboard"]
    assert [len(r) for r in kb] == [1, 2, 1, 3]
    styles = [b["style"] for r in kb for b in r]
    assert styles == ["primary", "success", "success", "primary", "danger", "success", "danger"]
    assert R.KEYMAP[R.norm("⚙️ مـدیـریـت ســلـف")] == "manage"
    assert R.KEYMAP[R.norm("⚙️ مدیریت سلف")] == "manage"          # tatweel-insensitive
    assert R.KEYMAP[R.norm("✅ فعالسازی")] == "manage"              # legacy keyboard still works
    assert "مدیریت گروه" not in str(kb)

def test_caption_limits():
    assert R.utf16len(R.WELCOME_HTML) <= 1024, R.utf16len(R.WELCOME_HTML)
    assert R.utf16len(R.ABOUT_HTML) < 4096

def test_pad_text_and_markup():
    t = R.pad_text("1")
    assert "کد: 1 - - - -" in t
    rows = R.pad_markup(True)["inline_keyboard"]
    assert [len(r) for r in rows] == [3, 3, 3, 3, 1]
    assert rows[-1][0]["callback_data"] == "kp:ok"
    assert all(len(b["callback_data"]) <= 64 for r in rows for b in r)

def test_pad_flow():
    u = U(50)
    R.G["LOGIN_STATES"][50] = {"step": "code", "client": None, "pad": {"digits": "", "msg": 7}}
    called = {}
    async def fake_text_handler(client, m): called["code"] = m.text; R.G["LOGIN_STATES"].pop(50, None)
    R.G["text_handler"] = fake_text_handler
    R.G["_MenuMsg"] = lambda c, user, chat, text: types.SimpleNamespace(text=text, from_user=user)
    async def go():
        for d in "12345":
            await R.cb_pad(None, CB(u, f"kp:{d}", 7))
        await R.cb_pad(None, CB(u, "kp:del", 7))
        await R.cb_pad(None, CB(u, "kp:5", 7))
        c = CB(u, "kp:ok", 7); await R.cb_pad(None, c)
    run(go())
    assert called["code"] == "12345"
    # short code is refused
    R.G["LOGIN_STATES"][50] = {"step": "code", "client": None, "pad": {"digits": "12", "msg": 7}}
    c = CB(u, "kp:ok", 7); run(R.cb_pad(None, c))
    assert c.answers and c.answers[-1][1] is True
    # wrong message id (stale pad) is rejected
    c = CB(u, "kp:3", 99); run(R.cb_pad(None, c))
    assert c.answers[-1][1] is True

def test_invoice_flow_via_callbacks():
    e = E.get(); SENT.clear()
    run(R.make_invoice(60, 60, 1500))
    inv = e.open_invoice_of(60); assert inv and inv["toman"] == 15000
    assert "فاکتور" in SENT[-1][1]
    e.attach_receipt(inv["id"], 60, "RCPT1")
    adm = U(1)
    c = CB(adm, f"ad:ok:{inv['id']}"); run(R.cb_admin_invoice(None, c))
    assert e.balance(60) == 1500
    c2 = CB(adm, f"ad:ok:{inv['id']}"); run(R.cb_admin_invoice(None, c2))
    assert e.balance(60) == 1500 and c2.answers[-1][1] is True       # no double credit
    nonadm = U(61); c3 = CB(nonadm, "ad:ok:1"); run(R.cb_admin_invoice(None, c3))
    assert c3.answers[-1][1] is True

def test_bet_game_in_official_chat_only():
    e = E.get(); e.credit(70, 1000, "t", "x"); e.credit(71, 1000, "t", "y")
    SENT.clear(); EDITS.clear()
    class M:
        def __init__(s, u, chat_id): s.from_user, s.id = u, 5; s.chat = types.SimpleNamespace(id=chat_id, type=types.SimpleNamespace(name="SUPERGROUP"))
    e.set_setting("official_chat", -100)
    run(R.new_game(None, M(U(70), -555), "bet", 500))        # wrong chat
    assert e.balance(70) == 1000 and "رسمی" in SENT[-1][1]
    run(R.new_game(None, M(U(70), -100), "bet", 500))        # right chat
    assert e.balance(70) == 500
    gid = max(g for g in range(1, 20) if e.game_get(g))
    async def join():
        await R.cb_game(None, CB(U(71), f"gm:j:{gid}", 1, types.SimpleNamespace(id=-100)))
    import unittest.mock as mock
    _real_sleep = asyncio.sleep
    async def _fast(*_a, **_k): return await _real_sleep(0)
    with mock.patch.object(R.asyncio, "sleep", _fast):
        run(join())
    g = e.game_get(gid); assert g["status"] == "done" and g["winner"] in (70, 71)
    assert e.balance(70) + e.balance(71) == 2000 - 100         # 10% of the 1000 pot taxed
    assert e.audit()["ok"]

def test_ttt_full_game():
    e = E.get(); e.credit(80, 500, "t", "x"); e.credit(81, 500, "t", "y")
    g = e.game_create("ttt", -100, 80, 100)
    c = types.SimpleNamespace(id=-100)
    run(R.cb_game(None, CB(U(81), f"gm:j:{g['id']}", 1, c)))
    seq = [(80, 0), (81, 3), (80, 1), (81, 4), (80, 2)]           # X wins top row
    for uid, idx in seq:
        run(R.cb_game(None, CB(U(uid), f"gm:m:{g['id']}:{idx}", 1, c)))
    done = e.game_get(g["id"])
    assert done["status"] == "done" and done["winner"] == 80
    assert e.balance(80) == 500 - 100 + 180 and e.balance(81) == 400
    # wrong turn is refused
    g2 = e.game_create("ttt", -100, 80, 10); run(R.cb_game(None, CB(U(81), f"gm:j:{g2['id']}", 1, c)))
    cb = CB(U(81), f"gm:m:{g2['id']}:0", 1, c); run(R.cb_game(None, cb))
    assert cb.answers[-1][1] is True

def test_top_and_balance_text():
    e = E.get(); e.touch(90, "u90", "نفر نود"); e.credit(90, 99999, "t", "q")
    t = R.top_text(90); assert "نفر نود" in t and "🥇" in t
    assert "جایگاه تو" not in t
    e.touch(91, "u91", "x"); e.credit(91, 1, "t", "z")
    for i in range(100, 112): e.touch(i, f"u{i}", f"n{i}"); e.credit(i, 5000 + i, "t", "k")
    assert "جایگاه تو" in R.top_text(91)

def test_subscription_hooks():
    e = E.get(); R.G["ACTIVE_BOTS"] = {123: (None, [])}
    stopped = []
    async def stop(uid): stopped.append(uid); R.G["ACTIVE_BOTS"].pop(uid, None)
    R.G["stop_user_bot"] = stop
    R.on_login(123, "+98900")
    assert e.is_active(123) and e.days_left(123) == 5
    R.on_login(123, "+98900"); assert e.days_left(123) == 5          # trial only once
    e._c.execute("UPDATE subs SET expires_at=? WHERE uid=123", (int(time.time()) - 5,))
    R.G["ACTIVE_BOTS"] = {123: (None, [])}
    SENT.clear(); run(R.subs_tick())
    assert stopped == [123] and any("تمام" in s[1] for s in SENT)
    assert R.sub_ok(1) and not R.sub_ok(123)                         # admin exempt

def test_migration_grace():
    R.G["data_manager"].data["users"] = {"500": {"session_string": "x"}, "501": {}}
    assert R.migrate_existing() == 1 and E.get().days_left(500) == 7
    assert R.migrate_existing() == 0

def test_referral_notifications():
    e = E.get(); SENT.clear()
    assert e.ref_register(200, 201)
    R.G["data_manager"].data.update({"global_fjoin_active": True, "global_fjoin_chats": ["@c"]})
    async def joined(uid): return True
    R.joined_all = joined
    run(R.try_confirm_ref(200))
    assert e.balance(201) == 200 and e.balance(200) == 100 and len(SENT) == 2


class Msg:
    def __init__(self, user, chat_id, text="", reply_user=None, match=None, ctype="SUPERGROUP"):
        self.from_user, self.id, self.text = user, 9, text
        self.chat = types.SimpleNamespace(id=chat_id, type=types.SimpleNamespace(name=ctype))
        self.reply_to_message = types.SimpleNamespace(from_user=reply_user) if reply_user else None
        self.matches = [match] if match else []
        self.command = text.lstrip("/").split()
    def stop_propagation(self): pass

import re as _re

def _m(rx, text): return _re.match(rx, text)

TR = r"^(?:/transfer(?:@\w+)?|انتقال)\s+([0-9۰-۹٠-٩,٬]+)(?:\s+(@\w+|\d+))?$"


def test_english_digits_everywhere():
    assert R.fa(1234567) == "1,234,567"
    t = R.table_caption("ttt", 1, 866)
    assert "1,559" in t and "866" in t and "۸" not in t and "2 نفر" in t


def test_balance_buttons_layout():
    e = E.get(); e.credit(300, 30000, "t", "bb"); e.add_days(300, 600)
    R.G["ACTIVE_BOTS"] = {300: (None, [])}
    rows = R.balance_markup(300, 30000)(True)["inline_keyboard"]
    assert [len(r) for r in rows] == [1, 2, 1]
    assert rows[0][0]["text"] == "30,000 💎" and rows[0][0]["style"] == "primary"
    assert rows[1][0]["text"] == "✅ روشن" and rows[1][0]["style"] == "success" and rows[1][1]["text"] == "600 روز"
    assert rows[2][0]["text"] == "300,000 تومان" and rows[2][0]["style"] == "success"
    R.G["ACTIVE_BOTS"] = {}


def test_result_buttons_layout():
    rows = R.result_markup(1559, 2000, 122)(True)["inline_keyboard"]
    assert [[b["text"] for b in r] for r in rows] == [["جایزه", "1,559"], ["موجودی برنده", "2,000"], ["موجودی بازنده", "122"]]
    assert [[b["style"] for b in r] for r in rows] == [["primary"] * 2, ["success"] * 2, ["danger"] * 2]


def test_transfer_command():
    e = E.get(); e.set_setting("official_chat", -100)
    e.credit(400, 1000, "t", "x"); e.touch(401, "capitanwew", "Cap", started=True); e.touch(402, "ghost", "Ghost")
    SENT.clear()
    run(R.transfer_cmd(None, Msg(U(400), -100, "انتقال 100", reply_user=U(401), match=_m(TR, "انتقال 100"))))
    assert e.balance(401) == 100 and e.balance(400) == 890
    txt = SENT[0][1]
    assert "انتقال الماس انجام شد" in txt and "@capitanwew" in txt and "کسر شده: 110💎" in txt and "مالیات: 10%" in txt
    rows = SENT[0][2]["inline_keyboard"]
    assert rows[0][0]["text"] == "موجودی فرستنده" and rows[0][1]["text"] == "890" and rows[1][1]["text"] == "100"
    assert rows[1][0]["style"] == "danger"
    SENT.clear(); R._CD.clear()                                     # receiver never started the bot
    run(R.transfer_cmd(None, Msg(U(400), -100, "انتقال 50", reply_user=U(402), match=_m(TR, "انتقال 50"))))
    assert "حساب ندارد" in SENT[0][1] and e.balance(400) == 890
    SENT.clear(); R._CD.clear()                                     # wrong chat
    run(R.transfer_cmd(None, Msg(U(400), -999, "انتقال 50", reply_user=U(401), match=_m(TR, "انتقال 50"))))
    assert "فقط در گپ رسمی" in SENT[0][1] and e.balance(400) == 890
    SENT.clear(); R._CD.clear()
    run(R.transfer_cmd(None, Msg(U(400), -100, "انتقال 5000 @capitanwew", match=_m(TR, "انتقال 5000 @capitanwew"))))
    assert "الماس کافی نداری" in SENT[0][1]


def test_game_timers_and_result_view():
    e = E.get(); e.credit(410, 1000, "t", "a"); e.credit(411, 1000, "t", "b")
    g = e.game_create("ttt", -100, 410, 100); e.game_set_msg(g["id"], 3)
    e._c.execute("UPDATE games SET created_at=? WHERE id=?", (int(time.time()) - E.GAME_TTL - 1, g["id"]))
    EDITS.clear(); run(R.games_tick())
    assert e.game_get(g["id"])["status"] == "cancelled" and e.balance(410) == 1000
    assert "باطل" in EDITS[-1][2]
    g2 = e.game_create("ttt", -100, 410, 100); e.game_set_msg(g2["id"], 4); e.game_join(g2["id"], 411)
    e.game_state(g2["id"], {"board": [""] * 9, "turn": "X", "x": 410, "o": 411, "ts": time.time() - E.MOVE_TTL - 1})
    EDITS.clear(); run(R.games_tick())
    done = e.game_get(g2["id"]); assert done["status"] == "done" and done["winner"] == 411   # X (410) didn't move
    cap, mk = EDITS[-1][2], EDITS[-1][3]["inline_keyboard"]
    assert "حرکت نکرد" in cap and "برنده" in cap
    assert mk[0][0]["text"] == "جایزه" and mk[0][1]["text"] == "180"
    assert mk[1][1]["text"] == str(f"{e.balance(411):,}") and mk[2][1]["text"] == str(f"{e.balance(410):,}")
    assert E.MOVE_TTL == 60 and E.GAME_TTL == 300


def test_gift_code_flow_and_wizard():
    e = E.get(); admin = U(1)
    R.STATE[1] = {"k": "gc", "step": 0, "data": {}, "ts": time.time()}
    for text in ["EID1405", "500", "24 ساعت", "2"]:
        run(R.on_state_text(None, Msg(admin, 1, text, ctype="PRIVATE")))
    g = e.gift_get("eid1405")
    assert g and g["amount"] == 500 and g["capacity"] == 2 and 0 < g["expires_at"] - time.time() <= 86400
    SENT.clear()
    R.STATE[420] = {"k": "gift", "ts": time.time()}
    run(R.on_state_text(None, Msg(U(420), 420, "eid1405", ctype="PRIVATE")))
    assert e.balance(420) == 500 and "کد هدیه ثبت شد" in SENT[-1][1]
    R.STATE[420] = {"k": "gift", "ts": time.time()}
    run(R.on_state_text(None, Msg(U(420), 420, "EID1405", ctype="PRIVATE")))
    assert "قبلاً" in SENT[-1][1] and e.balance(420) == 500
    assert R.parse_duration("7 روز") == 7 * 86400 and R.parse_duration("30 دقیقه") == 1800 and R.parse_duration("0") == 0
    assert R.parse_duration("abc") is None


def test_admin_started_validation_and_limit():
    e = E.get(); admin = U(1); SENT.clear()
    run(R.admin_commands(None, Msg(admin, 1, "/addgems 999999 100", ctype="PRIVATE")))
    assert "آیدی اشتباه است" in SENT[-1][1] and e.balance(999999) == 0
    e.touch(430, "t", "T", started=True); e.credit(430, 500, "t", "z"); e.add_days(430, 5)
    run(R.admin_commands(None, Msg(admin, 1, "/subgems 430 200", ctype="PRIVATE")))
    assert e.balance(430) == 300
    run(R.admin_commands(None, Msg(admin, 1, "/subgems 430 9999", ctype="PRIVATE")))
    assert "کافی نیست" in SENT[-1][1] and e.balance(430) == 300
    stopped = []
    async def stop(uid): stopped.append(uid)
    R.G["stop_user_bot"] = stop; R.G["ACTIVE_BOTS"] = {430: (None, [])}
    run(R.admin_commands(None, Msg(admin, 1, "/limit 430 7 روز", ctype="PRIVATE")))
    assert e.restriction(430) and stopped == [430] and not R.sub_ok(430)
    assert R.blocked_reason(430) == "restricted"
    run(R.admin_commands(None, Msg(admin, 1, "/unlimit 430", ctype="PRIVATE")))
    assert e.restriction(430) is None and R.sub_ok(430)
    run(R.admin_commands(None, Msg(admin, 1, "/limit 430", ctype="PRIVATE")))          # permanent
    assert e.restriction(430)["until"] == 0
    R.G["ACTIVE_BOTS"] = {}


def test_top_layout_spacing():
    t = R.top_text(90)
    assert "\n\n" in t and "\u2003" in t and t.count("💎") >= 2

if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
