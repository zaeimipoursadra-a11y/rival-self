import os, sys, tempfile, threading, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "self_tools"))
import economy as E

def fresh():
    return E.Economy(os.path.join(tempfile.mkdtemp(), "e.db"))

def raises(code, fn, *a, **k):
    try: fn(*a, **k)
    except E.EconomyError as e:
        assert e.code == code, (e.code, code); return
    raise AssertionError("no error, wanted " + code)

def test_wallet_and_overdraft():
    e = fresh(); e.credit(1, 100, "t", "a")
    assert e.balance(1) == 100
    raises("insufficient", e.debit, 1, 101, "t")
    raises("duplicate", e.credit, 1, 5, "t", "a")
    assert e.audit()["ok"]

def test_invoice_flow_idempotent():
    e = fresh(); inv = e.create_invoice(1, 1500)
    assert inv["toman"] == 15000
    raises("min_buy", e.create_invoice, 2, 400)
    raises("open_invoice", e.create_invoice, 1, 500)
    e.attach_receipt(inv["id"], 1, "FILE1")
    e.approve_invoice(inv["id"], 99)
    raises("closed", e.approve_invoice, inv["id"], 99)
    assert e.balance(1) == 1500
    inv2 = e.create_invoice(2, 500)
    raises("receipt_reused", e.attach_receipt, inv2["id"], 2, "FILE1")
    e.reject_invoice(inv2["id"], 99)
    assert e.balance(2) == 0 and e.audit()["ok"]

def test_subscription():
    e = fresh(); e.credit(1, 12000, "t", "a")
    exp = e.buy_month(1)
    assert e.balance(1) == 7000 and e.days_left(1) == 30
    exp2 = e.buy_month(1)
    assert exp2 - exp == 30 * 86400          # stacks on remaining time
    raises("insufficient", e.buy_month, 1, 2)

def test_referral_rules():
    e = fresh()
    assert not e.ref_register(5, 5)
    assert e.ref_register(2, 1)
    assert not e.ref_register(2, 3)          # only first inviter counts
    assert not e.ref_register(1, 2)          # no loops
    g = e.ref_confirm_join(2)
    assert g["inviter_gain"] == 200 and e.balance(1) == 200 and e.balance(2) == 100
    assert e.ref_confirm_join(2) is None     # once
    e.ref_mark_activated(2, "+98900")
    assert e.ref_pending_active(lambda u: True) == []   # < 3 days
    e._c.execute("UPDATE referrals SET activated_at=activated_at-?", (4 * 86400,))
    assert e.ref_pending_active(lambda u: False) == []  # not active anymore
    assert len(e.ref_pending_active(lambda u: True)) == 1
    assert e.balance(1) == 700
    assert e.ref_pending_active(lambda u: True) == []   # once
    # same phone can't pay twice
    e.ref_register(3, 1); e.ref_confirm_join(3); e.ref_mark_activated(3, "+98900")
    e._c.execute("UPDATE referrals SET activated_at=activated_at-?", (4 * 86400,))
    assert e.ref_pending_active(lambda u: True) == [] and e.balance(1) == 900
    assert e.audit()["ok"]

def test_referral_existing_user_not_new():
    e = fresh(); e.credit(7, 10, "t", "x")
    assert not e.ref_register(7, 1)

def test_bet_tax_and_escrow():
    e = fresh(); e.credit(1, 1000, "t", "a"); e.credit(2, 1000, "t", "b")
    raises("stake_min", e.game_create, "bet", 9, 1, 9)
    raises("stake_max", e.game_create, "bet", 9, 1, 100001)
    g = e.game_create("bet", -100, 1, 500)
    assert e.balance(1) == 500
    raises("self_join", e.game_join, g["id"], 1)
    e.game_join(g["id"], 2)
    assert e.balance(2) == 500
    r = e.game_pick_winner(g["id"])
    assert r["payout"] == 950 and r["tax"] == 50
    w = r["winner"]; l = 1 if w == 2 else 2
    assert e.balance(w) == 1450 and e.balance(l) == 500
    raises("closed", e.game_finish, g["id"], w)
    assert e.balance(0) == 50 and e.audit()["ok"]

def test_cancel_and_draw_refund():
    e = fresh(); e.credit(1, 1000, "t", "a"); e.credit(2, 1000, "t", "b")
    g = e.game_create("ttt", 1, 1, 100)
    raises("forbidden", e.game_cancel, g["id"], 2)
    e.game_cancel(g["id"], 1); assert e.balance(1) == 1000
    g = e.game_create("ttt", 1, 1, 100); e.game_join(g["id"], 2)
    e.game_finish(g["id"], None)
    assert e.balance(1) == 1000 and e.balance(2) == 1000 and e.audit()["ok"]

def test_ttt_logic():
    assert E.ttt_winner(["X","X","X","","","","","",""]) == "X"
    assert E.ttt_winner(list("XOXXOOOXX")) == "draw"
    assert E.ttt_winner([""]*9) is None

def test_top_rank():
    e = fresh()
    for i, b in enumerate([50, 300, 300, 10, 700]):
        e.touch(i + 1, f"u{i+1}"); e.credit(i + 1, b, "t", "a"); time.sleep(0.001)
    top = e.top(3)
    assert [t["uid"] for t in top] == [5, 2, 3]
    assert e.rank(5) == 1 and e.rank(3) == 3 and e.rank(4) == 5
    e.game_create("bet", 1, 5, 100); e.game_join(1, 2); e.game_finish(1, 2)
    assert 0 not in [t["uid"] for t in e.top(10)]

def test_concurrent_no_overdraft():
    e = fresh(); e.credit(1, 1000, "t", "a")
    ok = []
    def w(i):
        try: e.debit(1, 100, "spend", f"r{i}"); ok.append(1)
        except E.EconomyError: pass
    ts = [threading.Thread(target=w, args=(i,)) for i in range(30)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert len(ok) == 10 and e.balance(1) == 0 and e.audit()["ok"]

def test_fair_coin():
    import secrets
    c = sum(secrets.choice([0, 1]) for _ in range(4000))
    assert 1800 < c < 2200

if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
