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
    def type_and_enter():
        w = [c for c in root.winfo_children() if isinstance(c, tk.Toplevel)][0]
        w.focus_get().delete(0, "end"); w.focus_get().insert(0, "홍길동")
        w.event_generate("<Return>")
    root.after(300, type_and_enter)
    assert ask_string("t", "이름:", "x", parent=root) == "홍길동"
    root.after(300, lambda: [c for c in root.winfo_children() if isinstance(c, tk.Toplevel)][0].event_generate("<Escape>"))
    assert ask_string("t", "이름:", parent=root) is None
    root.destroy()
