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
    assert e.balance(70) + e.balance(71) == 2000 - 50          # 10% of 500 profit taxed
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
    assert e.balance(80) == 500 - 100 + 190 and e.balance(81) == 400
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

if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
