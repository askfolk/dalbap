import multiprocessing, sys, os
if __name__ == "__main__":
    multiprocessing.freeze_support()
    if "--selftest" in sys.argv:  # 빌드 결과 확인용: 화면 없이 장부+웹 동작 점검
        import tempfile
        os.environ["DALBAP_DATA"] = tempfile.mkdtemp()
        from dalbap.ledger import Ledger
        from dalbap.web import create_app
        L = Ledger(os.environ["DALBAP_DATA"]); c = L.add_customer("테스트")
        L.deposit(c["id"], 10000); L.deduct(c["id"], 9000)
        r = create_app(L).test_client().get("/c/" + c["token"])
        ok = r.status_code == 200 and "1,000원" in r.get_data(as_text=True) and L.balance(c["id"]) == 1000
        import io; from PIL import Image, ImageTk  # noqa: 번들에 Pillow/tkinter 포함 확인
        b = io.BytesIO(); Image.new("RGB", (8, 8)).save(b, "JPEG"); ok = ok and bool(L.add_receipt(b.getvalue()))
        L.set_owner_pin("1234"); ok = ok and create_app(L).test_client().get("/o/" + L.owner_token()).status_code == 200
        from dalbap.fonts import font_dir, FONT_FILES
        ok = ok and all((font_dir() / f).exists() for f in FONT_FILES)
        print("SELFTEST", "OK" if ok else "FAIL"); sys.exit(0 if ok else 1)
    from dalbap.gui import main
    main()
