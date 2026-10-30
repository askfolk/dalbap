import os, pytest
from dalbap.fonts import font_dir, FONT_FILES, register_fonts


def test_font_files_and_license_bundled():
    for f in FONT_FILES:
        p = font_dir() / f
        assert p.exists() and p.stat().st_size > 1_000_000
    assert "Open Font License" in (font_dir() / "Pretendard-LICENSE.txt").read_text(encoding="utf-8")


def test_register_never_crashes():
    assert register_fonts() in (True, False)


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="화면 없음")
def test_ask_string_dialog(tmp_path):
    import tkinter as tk
    from dalbap.gui import ask_string
    root = tk.Tk()
    root.withdraw()

    def _invoke_on_dialog(btn_text, attempts=0):
        tops = [c for c in root.winfo_children() if isinstance(c, tk.Toplevel)]
        if tops:
            top = tops[0]

            def walk(w):
                for ch in w.winfo_children():
                    yield ch
                    yield from walk(ch)

            for w in walk(top):
                if w.winfo_class() in ("Button", "TButton") and btn_text in str(w.cget("text")):
                    w.invoke()
                    return
            top.event_generate("<Return>")
        elif attempts < 60:
            root.after(50, lambda: _invoke_on_dialog(btn_text, attempts + 1))

    root.after(50, lambda: _invoke_on_dialog("확인"))
    assert ask_string("t", "이름:", "홍길동", parent=root) == "홍길동"

    root.after(50, lambda: _invoke_on_dialog("취소"))
    assert ask_string("t", "이름:", parent=root) is None
    root.destroy()
