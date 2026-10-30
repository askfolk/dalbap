import io, datetime, re
import pytest
from PIL import Image
from dalbap.ledger import Ledger, LedgerError, MAX_RECEIPT_BYTES
from dalbap.web import create_app


def img(fmt="JPEG", size=(40, 60)):
    b = io.BytesIO(); Image.new("RGB", size, "white").save(b, fmt); return b.getvalue()


@pytest.fixture
def L(tmp_path):
    return Ledger(tmp_path)


def test_add_receipt_paths_and_meta(L, tmp_path):
    c = L.add_customer("a"); t = L.deposit(c["id"], 10000)
    r = L.add_receipt(img(), date="2026-10-05", amount=10000, memo="이체", cid=c["id"], tx_id=t["id"])
    assert r["file"].startswith("receipts/2026/10/2026-10-05_") and r["file"].endswith(".jpg")
    assert (tmp_path / r["file"]).exists()
    assert len(L.receipts_for(date="2026-10-05")) == 1 and len(L.receipts_for(tx_id=t["id"])) == 1
    assert len(Ledger(tmp_path).receipts_for(month="2026-10")) == 1  # 재시작 후 유지
    assert L.add_receipt(img("PNG"))["file"].endswith(".png")


@pytest.mark.parametrize("data", [b"", b"not an image", b"%PDF-1.4 xxx", b"<script>alert(1)</script>"])
def test_rejects_non_images(L, data):
    with pytest.raises(LedgerError):
        L.add_receipt(data)


def test_rejects_other_formats_and_size(L):
    b = io.BytesIO(); Image.new("RGB", (10, 10)).save(b, "BMP")
    with pytest.raises(LedgerError):
        L.add_receipt(b.getvalue())
    with pytest.raises(LedgerError):
        L.add_receipt(img() + b"\0" * MAX_RECEIPT_BYTES)


def test_rejects_bad_refs(L):
    with pytest.raises(LedgerError): L.add_receipt(img(), cid="nope")
    with pytest.raises(LedgerError): L.add_receipt(img(), tx_id="nope")
    with pytest.raises(ValueError): L.add_receipt(img(), date="2026-13-01")


def test_backup_excludes_images_keeps_index(tmp_path):
    L = Ledger(tmp_path); L.add_receipt(img())
    import shutil; shutil.rmtree(tmp_path / "backups")
    Ledger(tmp_path)
    b = tmp_path / "backups" / datetime.date.today().isoformat()
    assert (b / "receipts" / "receipts.json").exists() and not list(b.rglob("*.jpg"))


def test_pin(L):
    with pytest.raises(LedgerError): L.set_owner_pin("12")
    with pytest.raises(LedgerError): L.set_owner_pin("abcd")
    L.set_owner_pin("4989")
    assert L.check_owner_pin("4989") and not L.check_owner_pin("0000") and not L.check_owner_pin("")
    assert "4989" not in (L.dir / "settings.json").read_text()


# ---------- 웹: 사장님 영수증 페이지 ----------
@pytest.fixture
def web(L):
    c = L.add_customer("손님"); L.deposit(c["id"], 50000)
    L.set_owner_pin("4989")
    return L, c, create_app(L).test_client()


def login(cl, L, pin="4989"):
    return cl.post(f"/o/{L.owner_token()}/login", data={"pin": pin})


def test_owner_page_requires_token_and_pin(web):
    L, c, cl = web
    tok = L.owner_token()
    assert cl.get("/o/wrong").status_code == 404
    r = cl.get(f"/o/{tok}"); h = r.get_data(as_text=True)
    assert r.status_code == 200 and "PIN" in h and "영수증 촬영" not in h
    up = cl.post(f"/o/{tok}/upload", data={"photo": (io.BytesIO(img()), "a.jpg")}, content_type="multipart/form-data")
    assert up.status_code == 403 and L.receipts_for() == []
    assert login(cl, L, "0000").status_code == 403
    assert login(cl, L).status_code == 302
    h = cl.get(f"/o/{tok}").get_data(as_text=True)
    assert 'capture="environment"' in h and 'accept="image/*"' in h and "손님" in h


def test_owner_upload_ok_and_invalid(web):
    L, c, cl = web; tok = L.owner_token(); login(cl, L)
    r = cl.post(f"/o/{tok}/upload", data={"photo": (io.BytesIO(img()), "r.jpg"), "amount": "12,000",
                                          "memo": "식자재", "cid": c["id"], "date": "2026-10-30"},
                content_type="multipart/form-data")
    assert r.status_code == 200 and "저장했습니다" in r.get_data(as_text=True)
    rec = L.receipts_for()[0]
    assert rec["amount"] == 12000 and rec["cid"] == c["id"] and rec["source"] == "web" and rec["date"] == "2026-10-30"
    bad = cl.post(f"/o/{tok}/upload", data={"photo": (io.BytesIO(b"<html>"), "x.jpg")}, content_type="multipart/form-data")
    assert bad.status_code == 400 and len(L.receipts_for()) == 1
    big = cl.post(f"/o/{tok}/upload", data={"photo": (io.BytesIO(b"0" * (11 * 1024 * 1024)), "b.jpg")},
                  content_type="multipart/form-data")
    assert big.status_code == 413


def test_pin_lockout(web):
    L, c, cl = web
    for _ in range(5): login(cl, L, "1111")
    assert login(cl, L).status_code == 429


def test_no_pin_set_means_owner_page_closed(tmp_path):
    L = Ledger(tmp_path); cl = create_app(L).test_client()
    assert cl.get(f"/o/{L.owner_token()}").status_code == 404


def test_customer_cannot_reach_receipts(web):
    L, c, cl = web
    r = L.add_receipt(img(), cid=c["id"], memo="비밀메모")
    h = cl.get(f"/c/{c['token']}").get_data(as_text=True)
    assert "비밀메모" not in h and "receipts" not in h
    for p in (f"/{r['file']}", f"/c/{c['token']}/{r['file']}", f"/c/{c['token']}/receipts", "/receipts",
              f"/o/{L.owner_token()}/upload"):
        assert cl.get(p).status_code in (404, 405)
    # 손님 토큰으로 사장님 페이지 불가
    assert cl.get(f"/o/{c['token']}").status_code == 404


def test_owner_session_invalid_after_token_regen(web):
    L, c, cl = web; old = L.owner_token(); login(cl, L)
    new = L.regenerate_owner_token()
    assert cl.get(f"/o/{old}").status_code == 404
    assert "영수증 촬영" not in cl.get(f"/o/{new}").get_data(as_text=True)


# ---------- 수정 / 삭제 / 복원 ----------
def test_update_receipt(L):
    c = L.add_customer("a"); t = L.deposit(c["id"], 5000)
    r = L.add_receipt(img(), amount=1000, memo="x")
    L.update_receipt(r["id"], amount="12,000", memo="식자재", cid=c["id"], tx_id=t["id"])
    r2 = Ledger(L.dir).receipts_for()[0]
    assert (r2["amount"], r2["memo"], r2["cid"], r2["tx_id"]) == (12000, "식자재", c["id"], t["id"]) and r2["edited"]
    L.update_receipt(r["id"], amount=None, cid="", tx_id="")
    assert L.receipts_for()[0]["amount"] is None and L.receipts_for()[0]["cid"] is None
    for bad in ({"cid": "no"}, {"tx_id": "no"}, {"amount": -1}, {"file": "../x"}):
        with pytest.raises(LedgerError):
            L.update_receipt(r["id"], **bad)
    with pytest.raises(LedgerError):
        L.update_receipt("nope", memo="a")


def test_delete_and_restore(L, tmp_path):
    r = L.add_receipt(img(), date="2026-10-05")
    orig = tmp_path / r["file"]
    L.delete_receipt(r["id"])
    assert not orig.exists() and list((tmp_path / "receipts" / "_trash").glob("*.jpg"))
    assert L.receipts_for() == [] and len(L.receipts_for(deleted=True)) == 1
    assert len(Ledger(tmp_path).receipts_for(deleted=True)) == 1  # 기록 유지
    with pytest.raises(LedgerError): L.delete_receipt(r["id"])
    L.restore_receipt(r["id"])
    assert orig.exists() and len(L.receipts_for(date="2026-10-05")) == 1 and not L.receipts_for(deleted=True)
    with pytest.raises(LedgerError): L.restore_receipt(r["id"])


def test_owner_mobile_list_and_delete(web):
    L, c, cl = web; tok = L.owner_token()
    r = L.add_receipt(img(), amount=7000, memo="가스비")
    # 로그인 전: 목록 안 보이고 삭제 불가
    assert "가스비" not in cl.get(f"/o/{tok}").get_data(as_text=True)
    assert cl.post(f"/o/{tok}/delete/{r['id']}").status_code == 403
    assert cl.post(f"/o/wrong/delete/{r['id']}").status_code == 404
    login(cl, L)
    h = cl.get(f"/o/{tok}").get_data(as_text=True)
    assert "가스비" in h and "7,000원" in h and "confirm(" in h
    assert cl.get(f"/o/{tok}/delete/{r['id']}").status_code == 405  # GET으로는 삭제 불가
    assert cl.post(f"/o/{tok}/delete/nope").status_code == 400
    d = cl.post(f"/o/{tok}/delete/{r['id']}")
    assert d.status_code == 200 and "삭제했습니다" in d.get_data(as_text=True)
    assert L.receipts_for() == [] and len(L.receipts_for(deleted=True)) == 1


def test_customer_cannot_delete(web):
    L, c, cl = web
    r = L.add_receipt(img())
    for p in (f"/o/{c['token']}/delete/{r['id']}", f"/c/{c['token']}/delete/{r['id']}"):
        assert cl.post(p).status_code in (404, 405)
    assert len(L.receipts_for()) == 1
