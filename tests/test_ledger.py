import datetime, json, threading
import pytest
from dalbap.ledger import Ledger, InsufficientBalance, LedgerError


@pytest.fixture
def L(tmp_path):
    return Ledger(tmp_path)


def test_deposit_deduct_balance(L):
    c = L.add_customer("김철수", "010")
    L.deposit(c["id"], 100000)
    L.deduct(c["id"], 9000)
    assert L.balance(c["id"]) == 91000
    h = L.history(c["id"])
    assert [r["balance"] for r in h] == [91000, 100000]


def test_negative_requires_flag(L):
    c = L.add_customer("이영희")
    L.deposit(c["id"], 5000)
    with pytest.raises(InsufficientBalance):
        L.deduct(c["id"], 9000)
    assert L.balance(c["id"]) == 5000
    L.deduct(c["id"], 9000, allow_negative=True)
    assert L.balance(c["id"]) == -4000


def test_cancel_is_reversing_entry(L):
    c = L.add_customer("박")
    t = L.deposit(c["id"], 50000)
    d = L.deduct(c["id"], 9000)
    L.cancel(d["id"], "실수")
    assert L.balance(c["id"]) == 50000
    assert len(L.tx) == 3  # 삭제 없음
    with pytest.raises(LedgerError):
        L.cancel(d["id"])
    cx = [x for x in L.tx if x["type"] == "cancel"][0]
    with pytest.raises(LedgerError):
        L.cancel(cx["id"])
    L.cancel(t["id"])
    assert L.balance(c["id"]) == 0


def test_invalid_amounts(L):
    c = L.add_customer("최")
    for bad in (0, -5):
        with pytest.raises(LedgerError):
            L.deposit(c["id"], bad)
    with pytest.raises(LedgerError):
        L.add_customer("  ")


def test_persistence_and_month_files(tmp_path):
    L = Ledger(tmp_path)
    c = L.add_customer("정")
    L.deposit(c["id"], 30000, when=datetime.datetime(2026, 9, 30, 12))
    L.deduct(c["id"], 9000, when=datetime.datetime(2026, 10, 1, 12))
    assert (tmp_path / "tx" / "2026-09.json").exists() and (tmp_path / "tx" / "2026-10.json").exists()
    L2 = Ledger(tmp_path)
    assert L2.balance(c["id"]) == 21000
    assert json.loads((tmp_path / "customers.json").read_text(encoding="utf-8"))[c["id"]]["name"] == "정"


def test_day_and_month_summary(L):
    a = L.add_customer("A"); b = L.add_customer("B")
    day = datetime.datetime(2026, 10, 5, 12)
    L.deposit(a["id"], 100000, when=day)
    L.deposit(b["id"], 50000, when=day)
    d = L.deduct(a["id"], 9000, when=day)
    L.cancel(d["id"], when=day)
    L.deduct(b["id"], 9000, when=datetime.datetime(2026, 10, 6, 12))
    s = L.month_summary(2026, 10)
    assert s["2026-10-05"]["deposit"] == 150000 and s["2026-10-05"]["deduct"] == 0
    assert s["2026-10-06"]["deduct"] == 9000
    rows = L.day("2026-10-05")
    assert {r["name"] for r in rows} == {"A", "B"} and any(r["cancelled"] for r in rows)


def test_daily_backup_created(tmp_path):
    L = Ledger(tmp_path); L.add_customer("x")
    Ledger(tmp_path)  # 재시작 시 오늘 백업 존재
    assert (tmp_path / "backups" / datetime.date.today().isoformat()).is_dir()


def test_atomic_no_tmp_left(tmp_path):
    L = Ledger(tmp_path); c = L.add_customer("x")
    for _ in range(20): L.deposit(c["id"], 1000)
    assert not list(tmp_path.rglob(".tmp-*.json"))


def test_threaded_deducts_never_overdraw(L):
    c = L.add_customer("동시")
    L.deposit(c["id"], 90000)
    errs = []
    def w():
        try: L.deduct(c["id"], 9000)
        except InsufficientBalance: errs.append(1)
    ts = [threading.Thread(target=w) for _ in range(15)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert L.balance(c["id"]) == 0 and len(errs) == 5


def test_token_unique_and_regen(L):
    a = L.add_customer("a"); b = L.add_customer("b")
    assert a["token"] != b["token"] and len(a["token"]) >= 20
    old = a["token"]; new = L.regenerate_token(a["id"])
    assert L.by_token(old) is None and L.by_token(new)["id"] == a["id"]
