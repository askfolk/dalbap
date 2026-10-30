"""충전 서명 기능 테스트."""
import io, datetime, time
import pytest
from PIL import Image
from dalbap.ledger import Ledger, LedgerError


def sig_png(width=400, height=200) -> bytes:
    """테스트용 서명 PNG 생성."""
    b = io.BytesIO()
    img = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    from PIL import ImageDraw
    draw = ImageDraw.Draw(img)
    draw.line([(50, 100), (350, 100)], fill="black", width=2)
    img.save(b, "PNG")
    return b.getvalue()


@pytest.fixture
def L(tmp_path):
    return Ledger(tmp_path)


def test_save_signature_creates_file(L, tmp_path):
    c = L.add_customer("서명테스트")
    sig = L.save_signature(sig_png(), c["id"], 100000)
    assert sig["file"].startswith("signatures/")
    assert sig["file"].endswith(".png")
    assert (tmp_path / sig["file"]).exists()
    assert sig["cid"] == c["id"]
    assert sig["amount"] == 100000


def test_signature_linked_to_deposit(L):
    c = L.add_customer("충전손님")
    sig = L.save_signature(sig_png(), c["id"], 50000)
    tx = L.deposit(c["id"], 50000, memo="서명충전", signature_file=sig["file"])
    assert tx.get("signature") == sig["file"]
    assert L.balance(c["id"]) == 50000


def test_signature_for_tx(L):
    c = L.add_customer("조회테스트")
    req = L.create_signature_request(c["id"], 30000)
    result = L.complete_signature_request(req["token"], sig_png())
    tx = result["tx"]
    found = L.signature_for_tx(tx["id"])
    assert found is not None
    assert found["tx_id"] == tx["id"]
    assert L.signature_for_tx("nonexistent") is None


def test_reject_empty_signature(L):
    c = L.add_customer("빈서명")
    with pytest.raises(LedgerError):
        L.save_signature(b"", c["id"], 10000)


def test_reject_non_png_signature(L):
    c = L.add_customer("비PNG")
    jpg = io.BytesIO()
    Image.new("RGB", (100, 50)).save(jpg, "JPEG")
    with pytest.raises(LedgerError):
        L.save_signature(jpg.getvalue(), c["id"], 10000)


def test_reject_invalid_customer(L):
    with pytest.raises(LedgerError):
        L.save_signature(sig_png(), "nope", 10000)


# ---------------- 서명 요청 ----------------
def test_create_signature_request(L):
    c = L.add_customer("요청테스트")
    req = L.create_signature_request(c["id"], 200000)
    assert req["cid"] == c["id"]
    assert req["name"] == "요청테스트"
    assert req["amount"] == 200000
    assert "token" in req
    assert not req["completed"]


def test_get_signature_request(L):
    c = L.add_customer("조회")
    req = L.create_signature_request(c["id"], 100000)
    found = L.get_signature_request(req["token"])
    assert found is not None
    assert found["token"] == req["token"]
    assert L.get_signature_request("invalid") is None


def test_complete_signature_request(L):
    c = L.add_customer("완료테스트")
    req = L.create_signature_request(c["id"], 150000)
    result = L.complete_signature_request(req["token"], sig_png())
    assert "tx" in result
    assert "signature" in result
    assert L.balance(c["id"]) == 150000
    assert L.get_signature_request(req["token"]) is None


def test_cannot_complete_twice(L):
    c = L.add_customer("중복완료")
    req = L.create_signature_request(c["id"], 100000)
    L.complete_signature_request(req["token"], sig_png())
    with pytest.raises(LedgerError):
        L.complete_signature_request(req["token"], sig_png())


def test_pending_signature_requests_bound_method(L):
    """GUI 폴링과 동일하게 인자 없이 호출 가능해야 함."""
    c = L.add_customer("폴링")
    req = L.create_signature_request(c["id"], 12000)
    pending = L._pending_signature_requests()
    assert isinstance(pending, dict)
    assert req["token"] in pending
    L.complete_signature_request(req["token"], sig_png())
    assert L.get_signature_request(req["token"]) is None


def test_completed_request_removed_from_pending(L):
    c = L.add_customer("완료후")
    req = L.create_signature_request(c["id"], 9000)
    L.complete_signature_request(req["token"], sig_png())
    assert L.get_signature_request(req["token"]) is None
    assert all(not r.get("completed") for r in L.get_pending_requests_for_owner())


def test_get_pending_requests(L):
    c = L.add_customer("대기목록")
    L.create_signature_request(c["id"], 50000)
    L.create_signature_request(c["id"], 60000)
    pending = L.get_pending_requests_for_owner()
    assert len(pending) == 2
    assert all(r["name"] == "대기목록" for r in pending)


# ---------------- 웹 서명 ----------------
@pytest.fixture
def web(L):
    c = L.add_customer("웹손님")
    L.set_owner_pin("1234")
    from dalbap.web import create_app
    return L, c, create_app(L).test_client()


def login(cl, L, pin="1234"):
    return cl.post(f"/o/{L.owner_token()}/login", data={"pin": pin})


def test_signature_pad_requires_pin(web):
    L, c, cl = web
    req = L.create_signature_request(c["id"], 100000)
    r = cl.get(f"/sig/{req['token']}")
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "웹손님" in html
    assert "100,000" in html
    assert "PIN" in html
    assert "서명해 주세요" not in html


def sig_login(cl, token, pin="1234"):
    return cl.post(f"/sig/{token}/login", data={"pin": pin})


def test_signature_pad_after_pin(web):
    L, c, cl = web
    req = L.create_signature_request(c["id"], 100000)
    sig_login(cl, req["token"])
    r = cl.get(f"/sig/{req['token']}")
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "서명해 주세요" in html


def test_signature_pad_expired(web):
    L, c, cl = web
    r = cl.get("/sig/invalid_token")
    html = r.get_data(as_text=True)
    assert "만료" in html


def test_signature_submit_requires_pin(web):
    L, c, cl = web
    req = L.create_signature_request(c["id"], 80000)
    r = cl.post(f"/sig/{req['token']}/submit",
                data={"signature": (io.BytesIO(sig_png()), "sig.png")},
                content_type="multipart/form-data")
    assert r.status_code == 403
    assert L.balance(c["id"]) == 0


def test_signature_submit_after_pin(web):
    L, c, cl = web
    req = L.create_signature_request(c["id"], 80000)
    sig_login(cl, req["token"])
    r = cl.post(f"/sig/{req['token']}/submit",
                data={"signature": (io.BytesIO(sig_png()), "sig.png")},
                content_type="multipart/form-data")
    assert r.status_code == 200
    assert L.balance(c["id"]) == 80000


def test_signature_submit_expired(web):
    L, c, cl = web
    r = cl.post("/sig/invalid/submit",
                data={"signature": (io.BytesIO(sig_png()), "sig.png")},
                content_type="multipart/form-data")
    assert r.status_code == 400


def test_signature_pin_lockout(web):
    L, c, cl = web
    req = L.create_signature_request(c["id"], 50000)
    for _ in range(5):
        sig_login(cl, req["token"], "0000")
    r = sig_login(cl, req["token"])
    html = r.get_data(as_text=True)
    assert "잠금" in html or r.status_code == 429


def test_owner_page_shows_signature_requests(web):
    L, c, cl = web
    login(cl, L)
    L.create_signature_request(c["id"], 200000)
    r = cl.get(f"/o/{L.owner_token()}")
    html = r.get_data(as_text=True)
    assert "서명 요청" in html
    assert "웹손님" in html
    assert "200,000" in html


def test_customer_cannot_access_signatures(web):
    L, c, cl = web
    sig = L.save_signature(sig_png(), c["id"], 50000)
    r = cl.get(f"/c/{c['token']}")
    html = r.get_data(as_text=True)
    assert "signatures" not in html
    for p in [f"/{sig['file']}", "/signatures"]:
        assert cl.get(p).status_code in (404, 405, 400)


# ---------------- 추가 테스트: 백업, 거래 기록 ----------------
def test_signatures_in_daily_backup(tmp_path):
    import datetime, shutil
    from dalbap.storage import daily_backup
    L = Ledger(tmp_path)
    c = L.add_customer("백업테스트")
    req = L.create_signature_request(c["id"], 100000)
    L.complete_signature_request(req["token"], sig_png())
    today = datetime.date.today().isoformat()
    backup_dir = tmp_path / "backups" / today
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    backup_dir = daily_backup(tmp_path)
    assert backup_dir.name == today
    assert (backup_dir / "signatures" / "signatures.json").exists()


def test_deposit_records_signature_in_tx(L):
    c = L.add_customer("거래기록")
    req = L.create_signature_request(c["id"], 100000)
    result = L.complete_signature_request(req["token"], sig_png())
    tx = result["tx"]
    assert tx.get("signature") is not None
    assert tx["signature"].startswith("signatures/")
    day_txs = L.day(tx["date"])
    deposit_tx = next(t for t in day_txs if t["id"] == tx["id"])
    assert deposit_tx.get("signature") is not None


def test_history_includes_signature_tx(L):
    c = L.add_customer("내역테스트")
    req = L.create_signature_request(c["id"], 50000)
    L.complete_signature_request(req["token"], sig_png())
    history = L.history(c["id"])
    assert len(history) == 1
    assert history[0]["type"] == "deposit"
    assert history[0]["amount"] == 50000
