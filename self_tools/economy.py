"""SELF RIVAL economy core.

Standalone module: no Pyrogram / bot.py imports, so it can be tested alone.
Storage: SQLite (WAL) next to DATA_FILE (on the Railway Volume) -> /data/economy.db

Rules
-----
* One balance per user (diamonds). Every change is a ledger row.
* 500 diamonds = 5,000 toman  ->  1 diamond = 10 toman.
* 5,000 diamonds = 30 days of self.
* Rewards/payments are idempotent: UNIQUE(uid, reason, ref).
* Game stakes are escrowed (debited on join) and refunded on cancel/draw.
"""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager

# ---------------------------------------------------------------- constants
TOMAN_PER_DIAMOND = 10
MIN_BUY = 500
DIAMONDS_PER_MONTH = 5000
DAYS_PER_MONTH = 30

REF_INVITER_JOIN = 200
REF_INVITEE_JOIN = 100
REF_INVITER_ACTIVE = 500
REF_ACTIVE_DAYS = 3
REF_DAILY_CAP = 20          # max successful joins credited per inviter per day

BET_MIN = 10
BET_MAX = 100_000
TAX_PERCENT = 10            # 10% of the whole pot (both stakes) goes to the house
INVOICE_TTL = 30 * 60
GAME_TTL = 5 * 60           # nobody joined within 5 minutes -> cancelled + refund
MOVE_TTL = 60               # tic-tac-toe: no move within 60 s -> that player loses
TRANSFER_MIN = 10
TRANSFER_TAX_PERCENT = 10   # added on top of the sent amount

DAY = 86400


def _db_path() -> str:
    explicit = os.environ.get("ECONOMY_DB")
    if explicit:
        return explicit
    data_file = os.environ.get("DATA_FILE", "bot_data.json")
    return os.path.join(os.path.dirname(os.path.abspath(data_file)), "economy.db")


class EconomyError(Exception):
    """User-facing error; .code is machine readable."""

    def __init__(self, code: str, msg: str = ""):
        super().__init__(msg or code)
        self.code = code


SCHEMA = """
CREATE TABLE IF NOT EXISTS wallets(
  uid INTEGER PRIMARY KEY,
  balance INTEGER NOT NULL DEFAULT 0 CHECK(balance >= 0),
  username TEXT, name TEXT, created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS ledger(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  uid INTEGER NOT NULL, delta INTEGER NOT NULL, balance_after INTEGER NOT NULL,
  reason TEXT NOT NULL, ref TEXT, ts INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_ledger_once
  ON ledger(uid, reason, ref) WHERE ref IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_ledger_uid ON ledger(uid, id);
CREATE TABLE IF NOT EXISTS subs(uid INTEGER PRIMARY KEY, expires_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS invoices(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  uid INTEGER NOT NULL, diamonds INTEGER NOT NULL, toman INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',   -- pending|receipt|approved|rejected|expired
  created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
  receipt_uid TEXT UNIQUE, receipt_msg TEXT,
  decided_by INTEGER, decided_at INTEGER, note TEXT
);
CREATE TABLE IF NOT EXISTS referrals(
  invitee INTEGER PRIMARY KEY, inviter INTEGER NOT NULL,
  started_at INTEGER NOT NULL, joined_at INTEGER, activated_at INTEGER,
  paid_join INTEGER NOT NULL DEFAULT 0, paid_active INTEGER NOT NULL DEFAULT 0,
  phone_hash TEXT
);
CREATE INDEX IF NOT EXISTS ix_ref_inviter ON referrals(inviter);
CREATE TABLE IF NOT EXISTS rewarded_phones(phone_hash TEXT PRIMARY KEY, ts INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS games(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,                       -- bet|ttt
  chat_id INTEGER NOT NULL, msg_id INTEGER,
  creator INTEGER NOT NULL, opponent INTEGER,
  stake INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',      -- open|running|done|cancelled
  winner INTEGER, state TEXT,
  created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS restrictions(
  uid INTEGER PRIMARY KEY, until INTEGER NOT NULL,   -- 0 = permanent
  reason TEXT, by INTEGER, ts INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS pro(
  uid INTEGER PRIMARY KEY, until INTEGER NOT NULL,      -- 0 = permanent
  by INTEGER, ts INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS gift_codes(
  code TEXT PRIMARY KEY COLLATE NOCASE, amount INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,                        -- 0 = never
  capacity INTEGER NOT NULL, used INTEGER NOT NULL DEFAULT 0,
  created_by INTEGER, created_at INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS gift_uses(
  code TEXT NOT NULL COLLATE NOCASE, uid INTEGER NOT NULL, ts INTEGER NOT NULL,
  PRIMARY KEY(code, uid)
);
"""


class Economy:
    def __init__(self, path: str | None = None):
        self.path = path or _db_path()
        d = os.path.dirname(self.path)
        if d:
            os.makedirs(d, exist_ok=True)
        self._lock = threading.RLock()
        self._c = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._c.row_factory = sqlite3.Row
        self._c.execute("PRAGMA journal_mode=WAL")
        self._c.execute("PRAGMA synchronous=NORMAL")
        self._c.execute("PRAGMA foreign_keys=ON")
        self._c.executescript(SCHEMA)
        cols = [r["name"] for r in self._c.execute("PRAGMA table_info(wallets)")]
        if "started" not in cols:   # wallets that talked to the bot in private
            self._c.execute("ALTER TABLE wallets ADD COLUMN started INTEGER NOT NULL DEFAULT 0")

    # ------------------------------------------------------------ plumbing
    @contextmanager
    def _tx(self):
        with self._lock:
            self._c.execute("BEGIN IMMEDIATE")
            try:
                yield self._c
                self._c.execute("COMMIT")
            except BaseException:
                self._c.execute("ROLLBACK")
                raise

    def _ensure(self, c, uid: int, username=None, name=None):
        c.execute(
            "INSERT OR IGNORE INTO wallets(uid,balance,created_at) VALUES(?,0,?)",
            (uid, int(time.time())),
        )
        if username is not None or name is not None:
            c.execute(
                "UPDATE wallets SET username=COALESCE(?,username), name=COALESCE(?,name) WHERE uid=?",
                (username, name, uid),
            )

    def _move(self, c, uid: int, delta: int, reason: str, ref: str | None = None) -> int:
        """Apply delta + ledger row. Raises on duplicate (uid,reason,ref) or overdraft."""
        self._ensure(c, uid)
        row = c.execute("SELECT balance FROM wallets WHERE uid=?", (uid,)).fetchone()
        new = row["balance"] + delta
        if new < 0:
            raise EconomyError("insufficient", "موجودی کافی نیست")
        try:
            c.execute(
                "INSERT INTO ledger(uid,delta,balance_after,reason,ref,ts) VALUES(?,?,?,?,?,?)",
                (uid, delta, new, reason, ref, int(time.time())),
            )
        except sqlite3.IntegrityError:
            raise EconomyError("duplicate", "این تراکنش قبلاً ثبت شده") from None
        c.execute("UPDATE wallets SET balance=? WHERE uid=?", (new, uid))
        return new

    # -------------------------------------------------------------- wallet
    def touch(self, uid: int, username: str | None = None, name: str | None = None, started: bool = False):
        with self._tx() as c:
            self._ensure(c, uid, username, name)
            if started:
                c.execute("UPDATE wallets SET started=1 WHERE uid=?", (uid,))

    def has_started(self, uid: int) -> bool:
        with self._lock:
            r = self._c.execute("SELECT started FROM wallets WHERE uid=?", (uid,)).fetchone()
        return bool(r and r["started"])

    def find_user(self, ref):
        """ref: int id or '@username'. Returns uid of a STARTED account or None."""
        with self._lock:
            if isinstance(ref, int) or str(ref).isdigit():
                r = self._c.execute("SELECT uid FROM wallets WHERE uid=? AND started=1 AND uid>0", (int(ref),)).fetchone()
            else:
                u = str(ref).lstrip("@").lower()
                r = self._c.execute("SELECT uid FROM wallets WHERE lower(username)=? AND started=1 AND uid>0", (u,)).fetchone()
        return r["uid"] if r else None

    def user_label(self, uid: int) -> str:
        with self._lock:
            r = self._c.execute("SELECT username,name FROM wallets WHERE uid=?", (uid,)).fetchone()
        if r and r["username"]:
            return "@" + r["username"]
        return (r["name"] if r and r["name"] else str(uid))

    def balance(self, uid: int) -> int:
        with self._lock:
            r = self._c.execute("SELECT balance FROM wallets WHERE uid=?", (uid,)).fetchone()
        return r["balance"] if r else 0

    @staticmethod
    def toman(diamonds: int) -> int:
        return diamonds * TOMAN_PER_DIAMOND

    def credit(self, uid: int, amount: int, reason: str, ref: str | None = None) -> int:
        if amount <= 0:
            raise EconomyError("bad_amount")
        with self._tx() as c:
            return self._move(c, uid, amount, reason, ref)

    def debit(self, uid: int, amount: int, reason: str, ref: str | None = None) -> int:
        if amount <= 0:
            raise EconomyError("bad_amount")
        with self._tx() as c:
            return self._move(c, uid, -amount, reason, ref)

    def history(self, uid: int, limit: int = 15):
        with self._lock:
            rows = self._c.execute(
                "SELECT delta,balance_after,reason,ref,ts FROM ledger WHERE uid=? ORDER BY id DESC LIMIT ?",
                (uid, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    # ---------------------------------------------------------- leaderboard
    def top(self, n: int = 10):
        with self._lock:
            rows = self._c.execute(
                "SELECT uid,balance,username,name FROM wallets WHERE balance>0 AND uid>0 "
                "ORDER BY balance DESC, created_at ASC, uid ASC LIMIT ?",
                (n,),
            ).fetchall()
        return [dict(r) for r in rows]

    def rank(self, uid: int):
        """1-based rank by balance (ties broken by older account). None if no wallet."""
        with self._lock:
            me = self._c.execute(
                "SELECT balance,created_at FROM wallets WHERE uid=?", (uid,)
            ).fetchone()
            if not me:
                return None
            r = self._c.execute(
                "SELECT COUNT(*) n FROM wallets WHERE uid>0 AND (balance>? OR "
                "(balance=? AND (created_at<? OR (created_at=? AND uid<?))))",
                (me["balance"], me["balance"], me["created_at"], me["created_at"], uid),
            ).fetchone()
        return r["n"] + 1

    # --------------------------------------------------------- subscription
    def sub_expires(self, uid: int) -> int:
        with self._lock:
            r = self._c.execute("SELECT expires_at FROM subs WHERE uid=?", (uid,)).fetchone()
        return r["expires_at"] if r else 0

    def days_left(self, uid: int) -> int:
        left = self.sub_expires(uid) - int(time.time())
        return max(0, -(-left // DAY))  # ceil

    def is_active(self, uid: int) -> bool:
        return self.sub_expires(uid) > int(time.time())

    def add_days(self, uid: int, days: int, reason: str = "admin_days", ref: str | None = None):
        with self._tx() as c:
            return self._add_days(c, uid, days)

    def _add_days(self, c, uid: int, days: int) -> int:
        now = int(time.time())
        cur = c.execute("SELECT expires_at FROM subs WHERE uid=?", (uid,)).fetchone()
        base = max(now, cur["expires_at"]) if cur else now
        new = base + days * DAY
        c.execute(
            "INSERT INTO subs(uid,expires_at) VALUES(?,?) "
            "ON CONFLICT(uid) DO UPDATE SET expires_at=excluded.expires_at",
            (uid, new),
        )
        return new

    def buy_month(self, uid: int, months: int = 1) -> int:
        """Spend diamonds for months of self. Returns new expiry timestamp."""
        if months < 1 or months > 12:
            raise EconomyError("bad_amount")
        with self._tx() as c:
            self._move(c, uid, -DIAMONDS_PER_MONTH * months, "buy_sub", None)
            return self._add_days(c, uid, DAYS_PER_MONTH * months)

    # -------------------------------------------------------------- invoices
    def create_invoice(self, uid: int, diamonds: int) -> dict:
        if diamonds < MIN_BUY:
            raise EconomyError("min_buy", f"حداقل خرید {MIN_BUY} الماس است")
        if diamonds > 10_000_000:
            raise EconomyError("max_buy")
        now = int(time.time())
        with self._tx() as c:
            self._ensure(c, uid)
            # only one open invoice at a time per user
            open_ = c.execute(
                "SELECT id FROM invoices WHERE uid=? AND status IN('pending','receipt') AND expires_at>?",
                (uid, now),
            ).fetchone()
            if open_:
                raise EconomyError("open_invoice", str(open_["id"]))
            cur = c.execute(
                "INSERT INTO invoices(uid,diamonds,toman,created_at,expires_at) VALUES(?,?,?,?,?)",
                (uid, diamonds, diamonds * TOMAN_PER_DIAMOND, now, now + INVOICE_TTL),
            )
            return self._invoice(c, cur.lastrowid)

    def _invoice(self, c, inv_id: int):
        r = c.execute("SELECT * FROM invoices WHERE id=?", (inv_id,)).fetchone()
        return dict(r) if r else None

    def get_invoice(self, inv_id: int):
        with self._lock:
            return self._invoice(self._c, inv_id)

    def open_invoice_of(self, uid: int):
        now = int(time.time())
        with self._lock:
            r = self._c.execute(
                "SELECT * FROM invoices WHERE uid=? AND status IN('pending','receipt') "
                "AND expires_at>? ORDER BY id DESC LIMIT 1",
                (uid, now),
            ).fetchone()
        return dict(r) if r else None

    def attach_receipt(self, inv_id: int, uid: int, file_unique_id: str, msg_ref: str = ""):
        now = int(time.time())
        with self._tx() as c:
            inv = self._invoice(c, inv_id)
            if not inv or inv["uid"] != uid:
                raise EconomyError("not_found")
            if inv["status"] not in ("pending", "receipt"):
                raise EconomyError("closed")
            if inv["expires_at"] < now:
                c.execute("UPDATE invoices SET status='expired' WHERE id=?", (inv_id,))
                raise EconomyError("expired")
            try:
                c.execute(
                    "UPDATE invoices SET status='receipt', receipt_uid=?, receipt_msg=? WHERE id=?",
                    (file_unique_id, msg_ref, inv_id),
                )
            except sqlite3.IntegrityError:
                raise EconomyError("receipt_reused", "این رسید قبلاً استفاده شده") from None
            return self._invoice(c, inv_id)

    def approve_invoice(self, inv_id: int, admin: int) -> dict:
        """Idempotent: a second approve raises 'closed' and adds nothing."""
        with self._tx() as c:
            inv = self._invoice(c, inv_id)
            if not inv:
                raise EconomyError("not_found")
            if inv["status"] not in ("pending", "receipt"):
                raise EconomyError("closed")
            self._move(c, inv["uid"], inv["diamonds"], "purchase", f"inv{inv_id}")
            c.execute(
                "UPDATE invoices SET status='approved', decided_by=?, decided_at=? WHERE id=?",
                (admin, int(time.time()), inv_id),
            )
            return self._invoice(c, inv_id)

    def reject_invoice(self, inv_id: int, admin: int, note: str = "") -> dict:
        with self._tx() as c:
            inv = self._invoice(c, inv_id)
            if not inv:
                raise EconomyError("not_found")
            if inv["status"] not in ("pending", "receipt"):
                raise EconomyError("closed")
            c.execute(
                "UPDATE invoices SET status='rejected', decided_by=?, decided_at=?, note=? WHERE id=?",
                (admin, int(time.time()), note, inv_id),
            )
            return self._invoice(c, inv_id)

    def expire_invoices(self) -> int:
        with self._tx() as c:
            return c.execute(
                "UPDATE invoices SET status='expired' WHERE status IN('pending','receipt') AND expires_at<?",
                (int(time.time()),),
            ).rowcount

    # -------------------------------------------------------------- referral
    def ref_register(self, invitee: int, inviter: int) -> bool:
        """Called on /start ref_<inviter>. True if recorded."""
        if invitee == inviter:
            return False
        with self._tx() as c:
            self._ensure(c, invitee)
            self._ensure(c, inviter)
            if c.execute("SELECT 1 FROM referrals WHERE invitee=?", (invitee,)).fetchone():
                return False
            # inviter must not be someone the invitee invited (no loops)
            if c.execute(
                "SELECT 1 FROM referrals WHERE invitee=? AND inviter=?", (inviter, invitee)
            ).fetchone():
                return False
            # an existing wallet with history is not a "new" user
            if c.execute("SELECT 1 FROM ledger WHERE uid=? LIMIT 1", (invitee,)).fetchone():
                return False
            c.execute(
                "INSERT INTO referrals(invitee,inviter,started_at) VALUES(?,?,?)",
                (invitee, inviter, int(time.time())),
            )
            return True

    def ref_confirm_join(self, invitee: int) -> dict | None:
        """Invitee passed forced-join: 200 -> inviter, 100 -> invitee. Once only."""
        now = int(time.time())
        with self._tx() as c:
            r = c.execute("SELECT * FROM referrals WHERE invitee=?", (invitee,)).fetchone()
            if not r or r["paid_join"]:
                return None
            today = c.execute(
                "SELECT COUNT(*) n FROM referrals WHERE inviter=? AND paid_join=1 AND joined_at>?",
                (r["inviter"], now - DAY),
            ).fetchone()["n"]
            if today >= REF_DAILY_CAP:
                raise EconomyError("daily_cap")
            self._move(c, r["inviter"], REF_INVITER_JOIN, "ref_join", f"inv{invitee}")
            self._move(c, invitee, REF_INVITEE_JOIN, "ref_welcome", f"inv{invitee}")
            c.execute(
                "UPDATE referrals SET paid_join=1, joined_at=? WHERE invitee=?", (now, invitee)
            )
            return {"inviter": r["inviter"], "inviter_gain": REF_INVITER_JOIN,
                    "invitee_gain": REF_INVITEE_JOIN}

    def ref_mark_activated(self, invitee: int, phone: str | None = None):
        """Self was activated: start the 3-day clock (once)."""
        import hashlib

        ph = hashlib.sha256((phone or "").encode()).hexdigest() if phone else None
        with self._tx() as c:
            c.execute(
                "UPDATE referrals SET activated_at=COALESCE(activated_at,?), "
                "phone_hash=COALESCE(phone_hash,?) WHERE invitee=?",
                (int(time.time()), ph, invitee),
            )

    def ref_pending_active(self, is_still_active) -> list[dict]:
        """Pay the 500 bonus for invitees active >= 3 days.
        is_still_active(uid)->bool is supplied by the bot (self really running)."""
        now = int(time.time())
        paid = []
        with self._lock:
            rows = self._c.execute(
                "SELECT * FROM referrals WHERE paid_join=1 AND paid_active=0 "
                "AND activated_at IS NOT NULL AND activated_at<=?",
                (now - REF_ACTIVE_DAYS * DAY,),
            ).fetchall()
        for r in rows:
            if not is_still_active(r["invitee"]):
                continue
            try:
                with self._tx() as c:
                    if r["phone_hash"]:
                        if c.execute(
                            "SELECT 1 FROM rewarded_phones WHERE phone_hash=?", (r["phone_hash"],)
                        ).fetchone():
                            c.execute(
                                "UPDATE referrals SET paid_active=2 WHERE invitee=?", (r["invitee"],)
                            )
                            continue
                        c.execute(
                            "INSERT INTO rewarded_phones(phone_hash,ts) VALUES(?,?)",
                            (r["phone_hash"], now),
                        )
                    self._move(c, r["inviter"], REF_INVITER_ACTIVE, "ref_active", f"inv{r['invitee']}")
                    c.execute("UPDATE referrals SET paid_active=1 WHERE invitee=?", (r["invitee"],))
                paid.append({"inviter": r["inviter"], "invitee": r["invitee"],
                             "gain": REF_INVITER_ACTIVE})
            except EconomyError:
                continue
        return paid

    def ref_stats(self, inviter: int) -> dict:
        with self._lock:
            r = self._c.execute(
                "SELECT COUNT(*) total, COALESCE(SUM(paid_join=1),0) joined, "
                "COALESCE(SUM(paid_active=1),0) active FROM referrals WHERE inviter=?",
                (inviter,),
            ).fetchone()
        earned = (r["joined"] * REF_INVITER_JOIN) + (r["active"] * REF_INVITER_ACTIVE)
        return {"total": r["total"], "joined": r["joined"], "active": r["active"], "earned": earned}

    # ----------------------------------------------------------------- games
    @staticmethod
    def check_stake(stake: int):
        if not isinstance(stake, int) or stake < BET_MIN:
            raise EconomyError("stake_min", f"حداقل شرط {BET_MIN} الماس است")
        if stake > BET_MAX:
            raise EconomyError("stake_max", f"حداکثر شرط {BET_MAX:,} الماس است")

    @staticmethod
    def tax_of(stake: int) -> int:
        """10% of the whole pot (2 x stake), rounded down."""
        return stake * 2 * TAX_PERCENT // 100

    @staticmethod
    def prize_of(stake: int) -> int:
        return stake * 2 - Economy.tax_of(stake)

    def game_create(self, kind: str, chat_id: int, creator: int, stake: int) -> dict:
        self.check_stake(stake)
        now = int(time.time())
        with self._tx() as c:
            cur = c.execute(
                "INSERT INTO games(kind,chat_id,creator,stake,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                (kind, chat_id, creator, stake, now, now),
            )
            gid = cur.lastrowid
            self._move(c, creator, -stake, f"{kind}_stake", f"g{gid}")
            return self._game(c, gid)

    def _game(self, c, gid: int):
        r = c.execute("SELECT * FROM games WHERE id=?", (gid,)).fetchone()
        return dict(r) if r else None

    def game_get(self, gid: int):
        with self._lock:
            return self._game(self._c, gid)

    def game_set_msg(self, gid: int, msg_id: int):
        with self._tx() as c:
            c.execute("UPDATE games SET msg_id=? WHERE id=?", (msg_id, gid))

    def game_join(self, gid: int, uid: int) -> dict:
        now = int(time.time())
        with self._tx() as c:
            g = self._game(c, gid)
            if not g:
                raise EconomyError("not_found")
            if g["status"] != "open":
                raise EconomyError("not_open", "بازی دیگر باز نیست")
            if g["creator"] == uid:
                raise EconomyError("self_join", "نمی‌توانی با خودت بازی کنی")
            if g["created_at"] + GAME_TTL < now:
                self._cancel(c, g)
                raise EconomyError("expired", "بازی منقضی شد")
            self._move(c, uid, -g["stake"], f"{g['kind']}_stake", f"g{gid}")
            c.execute(
                "UPDATE games SET opponent=?, status='running', updated_at=? WHERE id=?",
                (uid, now, gid),
            )
            return self._game(c, gid)

    def _cancel(self, c, g):
        if g["status"] in ("done", "cancelled"):
            return
        c.execute("UPDATE games SET status='cancelled', updated_at=? WHERE id=?",
                  (int(time.time()), g["id"]))
        self._move(c, g["creator"], g["stake"], f"{g['kind']}_refund", f"g{g['id']}")
        if g["opponent"]:
            self._move(c, g["opponent"], g["stake"], f"{g['kind']}_refund", f"g{g['id']}")

    def game_cancel(self, gid: int, by: int | None = None, force: bool = False) -> dict:
        with self._tx() as c:
            g = self._game(c, gid)
            if not g:
                raise EconomyError("not_found")
            if g["status"] not in ("open", "running"):
                raise EconomyError("closed")
            if not force and by is not None and by != g["creator"]:
                raise EconomyError("forbidden")
            if not force and g["status"] == "running":
                raise EconomyError("forbidden", "بازی شروع شده")
            self._cancel(c, g)
            return self._game(c, gid)

    def game_finish(self, gid: int, winner: int | None) -> dict:
        """winner None => draw (full refund, no tax). Idempotent via status."""
        with self._tx() as c:
            g = self._game(c, gid)
            if not g:
                raise EconomyError("not_found")
            if g["status"] != "running":
                raise EconomyError("closed")
            now = int(time.time())
            if winner is None:
                c.execute("UPDATE games SET status='done', updated_at=? WHERE id=?", (now, gid))
                self._move(c, g["creator"], g["stake"], f"{g['kind']}_draw", f"g{gid}")
                self._move(c, g["opponent"], g["stake"], f"{g['kind']}_draw", f"g{gid}")
                return self._game(c, gid)
            if winner not in (g["creator"], g["opponent"]):
                raise EconomyError("bad_winner")
            tax = self.tax_of(g["stake"])
            payout = g["stake"] * 2 - tax
            self._move(c, winner, payout, f"{g['kind']}_win", f"g{gid}")
            c.execute("UPDATE games SET status='done', winner=?, updated_at=? WHERE id=?",
                      (winner, now, gid))
            self._move_house(c, tax, gid)
            g = self._game(c, gid)
            g["payout"], g["tax"] = payout, tax
            return g

    def _move_house(self, c, tax: int, gid: int):
        # House (tax) is tracked under uid 0 so the books always balance.
        if tax > 0:
            self._move(c, 0, tax, "tax", f"g{gid}")

    def game_pick_winner(self, gid: int) -> dict:
        """Unbiased coin flip between the two players (CSPRNG, no pattern)."""
        g = self.game_get(gid)
        if not g or g["status"] != "running":
            raise EconomyError("closed")
        winner = secrets.choice([g["creator"], g["opponent"]])
        return self.game_finish(gid, winner)

    def active_game_of(self, uid: int, exclude: int | None = None):
        """The open/running game this user is part of (creator or opponent), else None."""
        with self._lock:
            r = self._c.execute(
                "SELECT * FROM games WHERE status IN('open','running') AND (creator=? OR opponent=?) "
                "AND id<>? ORDER BY id DESC LIMIT 1", (uid, uid, exclude or -1)).fetchone()
        return dict(r) if r else None

    def game_state(self, gid: int, state: dict):
        with self._tx() as c:
            c.execute("UPDATE games SET state=?, updated_at=? WHERE id=?",
                      (json.dumps(state), int(time.time()), gid))

    def games_expired(self):
        """Open games past TTL (to cancel+refund) -> list of ids."""
        with self._lock:
            rows = self._c.execute(
                "SELECT id FROM games WHERE status='open' AND created_at<?",
                (int(time.time()) - GAME_TTL,),
            ).fetchall()
        return [r["id"] for r in rows]

    # --------------------------------------------------------------- settings
    def set_setting(self, k: str, v):
        with self._tx() as c:
            c.execute("INSERT INTO settings(k,v) VALUES(?,?) "
                      "ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, json.dumps(v)))

    def get_setting(self, k: str, default=None):
        with self._lock:
            r = self._c.execute("SELECT v FROM settings WHERE k=?", (k,)).fetchone()
        return json.loads(r["v"]) if r else default

    # -------------------------------------------------------------- transfer
    @staticmethod
    def transfer_fee(amount: int) -> int:
        return amount * TRANSFER_TAX_PERCENT // 100

    def transfer(self, sender: int, receiver: int, amount: int) -> dict:
        if sender == receiver:
            raise EconomyError("self_transfer")
        if amount < TRANSFER_MIN:
            raise EconomyError("transfer_min", f"حداقل انتقال {TRANSFER_MIN} الماس است")
        fee = self.transfer_fee(amount)
        ref = "t" + _uuid_hex()
        with self._tx() as c:
            if not c.execute("SELECT 1 FROM wallets WHERE uid=? AND started=1", (receiver,)).fetchone():
                raise EconomyError("no_account")
            self._move(c, sender, -(amount + fee), "transfer_out", ref)
            self._move(c, receiver, amount, "transfer_in", ref)
            if fee:
                self._move(c, 0, fee, "transfer_tax", ref)
            sb = c.execute("SELECT balance FROM wallets WHERE uid=?", (sender,)).fetchone()["balance"]
            rb = c.execute("SELECT balance FROM wallets WHERE uid=?", (receiver,)).fetchone()["balance"]
        return {"amount": amount, "fee": fee, "charged": amount + fee, "sender_balance": sb, "receiver_balance": rb}

    # ---------------------------------------------------------- restrictions
    def restrict(self, uid: int, seconds: int | None, by: int = 0, reason: str = ""):
        """seconds=None -> permanent."""
        until = 0 if seconds is None else int(time.time()) + int(seconds)
        with self._tx() as c:
            self._ensure(c, uid)
            c.execute("INSERT INTO restrictions(uid,until,reason,by,ts) VALUES(?,?,?,?,?) "
                      "ON CONFLICT(uid) DO UPDATE SET until=excluded.until, reason=excluded.reason, "
                      "by=excluded.by, ts=excluded.ts", (uid, until, reason, by, int(time.time())))
        return until

    def unrestrict(self, uid: int) -> bool:
        with self._tx() as c:
            return c.execute("DELETE FROM restrictions WHERE uid=?", (uid,)).rowcount > 0

    def restriction(self, uid: int):
        """None if free; else {'until': ts or 0, 'reason': str}. Expired rows are cleaned."""
        with self._lock:
            r = self._c.execute("SELECT until,reason FROM restrictions WHERE uid=?", (uid,)).fetchone()
        if not r:
            return None
        if r["until"] and r["until"] <= int(time.time()):
            self.unrestrict(uid)
            return None
        return {"until": r["until"], "reason": r["reason"] or ""}

    # ------------------------------------------------------------------ pro
    def pro_grant(self, uid: int, seconds: int | None = None, by: int = 0) -> int:
        """Give/extend PRO (PewPew etc.). seconds=None -> permanent. Returns 'until' (0 = permanent)."""
        now = int(time.time())
        with self._tx() as c:
            self._ensure(c, uid)
            cur = c.execute("SELECT until FROM pro WHERE uid=?", (uid,)).fetchone()
            if seconds is None:
                until = 0
            else:
                base = max(now, cur["until"]) if cur and cur["until"] else now
                until = base + int(seconds)
            c.execute("INSERT INTO pro(uid,until,by,ts) VALUES(?,?,?,?) ON CONFLICT(uid) DO UPDATE SET "
                      "until=excluded.until, by=excluded.by, ts=excluded.ts", (uid, until, by, now))
        return until

    def pro_revoke(self, uid: int) -> bool:
        with self._tx() as c:
            return c.execute("DELETE FROM pro WHERE uid=?", (uid,)).rowcount > 0

    def pro_until(self, uid: int):
        """None = not pro, 0 = permanent, else expiry timestamp (expired rows are cleaned)."""
        with self._lock:
            r = self._c.execute("SELECT until FROM pro WHERE uid=?", (uid,)).fetchone()
        if not r:
            return None
        if r["until"] and r["until"] <= int(time.time()):
            self.pro_revoke(uid)
            return None
        return r["until"]

    def is_pro(self, uid: int) -> bool:
        return self.pro_until(uid) is not None

    def pro_list(self, limit: int = 30):
        with self._lock:
            rows = self._c.execute("SELECT uid,until FROM pro ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------ gift codes
    def gift_create(self, code: str, amount: int, duration_s: int, capacity: int, by: int = 0) -> dict:
        code = (code or "").strip()
        if not code or len(code) > 32 or not all(ch.isalnum() or ch in "_-" for ch in code):
            raise EconomyError("bad_code", "کد فقط حروف، عدد، _ و - (حداکثر ۳۲ کاراکتر)")
        if amount <= 0 or capacity <= 0:
            raise EconomyError("bad_amount")
        exp = 0 if duration_s <= 0 else int(time.time()) + duration_s
        with self._tx() as c:
            try:
                c.execute("INSERT INTO gift_codes(code,amount,expires_at,capacity,created_by,created_at) "
                          "VALUES(?,?,?,?,?,?)", (code, amount, exp, capacity, by, int(time.time())))
            except sqlite3.IntegrityError:
                raise EconomyError("code_exists", "این کد قبلاً ساخته شده") from None
        return self.gift_get(code)

    def gift_get(self, code: str):
        with self._lock:
            r = self._c.execute("SELECT * FROM gift_codes WHERE code=?", (code.strip(),)).fetchone()
        return dict(r) if r else None

    def gift_list(self, limit: int = 15):
        with self._lock:
            rows = self._c.execute("SELECT * FROM gift_codes ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def gift_delete(self, code: str) -> bool:
        with self._tx() as c:
            return c.execute("UPDATE gift_codes SET active=0 WHERE code=? AND active=1", (code,)).rowcount > 0

    def gift_redeem(self, code: str, uid: int) -> dict:
        code = (code or "").strip()
        now = int(time.time())
        with self._tx() as c:
            g = c.execute("SELECT * FROM gift_codes WHERE code=?", (code,)).fetchone()
            if not g or not g["active"]:
                raise EconomyError("code_invalid")
            if g["expires_at"] and g["expires_at"] <= now:
                raise EconomyError("code_expired")
            if g["used"] >= g["capacity"]:
                raise EconomyError("code_full")
            try:
                c.execute("INSERT INTO gift_uses(code,uid,ts) VALUES(?,?,?)", (g["code"], uid, now))
            except sqlite3.IntegrityError:
                raise EconomyError("code_used") from None
            c.execute("UPDATE gift_codes SET used=used+1 WHERE code=?", (g["code"],))
            bal = self._move(c, uid, g["amount"], "gift_code", g["code"].lower())
        return {"amount": g["amount"], "balance": bal}

    # ---------------------------------------------------------------- audit
    def audit(self) -> dict:
        """Sum of all wallets must equal sum of all ledger deltas."""
        with self._lock:
            a = self._c.execute("SELECT COALESCE(SUM(balance),0) s FROM wallets").fetchone()["s"]
            b = self._c.execute("SELECT COALESCE(SUM(delta),0) s FROM ledger").fetchone()["s"]
        return {"wallets": a, "ledger": b, "ok": a == b}


# ------------------------------------------------------------ tic-tac-toe core
WIN_LINES = ((0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6))


def ttt_winner(board: list[str]) -> str | None:
    """board: 9 cells of '', 'X', 'O'. Returns 'X'/'O'/'draw'/None."""
    for a, b, c in WIN_LINES:
        if board[a] and board[a] == board[b] == board[c]:
            return board[a]
    return "draw" if all(board) else None


def _uuid_hex() -> str:
    return secrets.token_hex(8)


def fmt(n: int) -> str:
    return f"{n:,}"


_instance: Economy | None = None


def get() -> Economy:
    global _instance
    if _instance is None:
        _instance = Economy()
    return _instance
