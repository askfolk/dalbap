import io, os, pytest
pytestmark = pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="화면 없음")


def test_gui_builds_with_receipts(tmp_path):
    from PIL import Image
    from dalbap.ledger import Ledger
    from dalbap.gui import App
    L = Ledger(tmp_path); c = L.add_customer("화면테스트"); L.deposit(c["id"], 20000); t = L.deduct(c["id"], 9000)
    b = io.BytesIO(); Image.new("RGB", (300, 500), "white").save(b, "JPEG")
    r = L.add_receipt(b.getvalue(), tx_id=t["id"], cid=c["id"], amount=9000)
    app = App(L, serve=False); app.update()
    assert app.ct.exists(c["id"]) and len(app.dayt.get_children()) == 2
    assert app.dayt.item(t["id"])["values"][4] == "🧾"
    assert "(1)" in app.nb.tab(1, "text")
    app.rct.selection_set(r["id"]); app.update(); app.preview()
    assert app._thumb is not None
    app.shift(1); app.shift(-1); app.update()
    app.destroy()


def test_gui_edit_delete_restore(tmp_path):
    from PIL import Image
    from dalbap.ledger import Ledger
    from dalbap.gui import App
    import dalbap.gui as g
    L = Ledger(tmp_path); c = L.add_customer("수정테스트"); t = L.deposit(c["id"], 20000)
    b = io.BytesIO(); Image.new("RGB", (50, 50)).save(b, "JPEG")
    r = L.add_receipt(b.getvalue(), amount=100)
    app = App(L, serve=False); app.update()
    app.rct.selection_set(r["id"]); app.update()
    w = app.edit_receipt(); v_amt, v_memo, v_c, v_t = w._vars
    v_amt.set("3,500"); v_memo.set("수정됨"); v_c.set("수정테스트"); 
    w._save()
    rr = L.receipts_for()[0]
    assert rr["amount"] == 3500 and rr["memo"] == "수정됨" and rr["cid"] == c["id"] and rr["tx_id"] is None
    g.messagebox.askyesno = lambda *a, **k: True
    app.rct.selection_set(r["id"]); app.update(); app.delete_receipt()
    assert not L.receipts_for() and "(0)" in app.nb.tab(1, "text")
    tw, tv = app.show_trash(); assert tv.exists(r["id"])
    tv.selection_set(r["id"]); tw.update()
    L.restore_receipt(r["id"]); app.refresh()
    assert "(1)" in app.nb.tab(1, "text")
    app.destroy()
