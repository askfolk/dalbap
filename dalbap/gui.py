"""사장님용 데스크톱 화면 (tkinter, 업무용 소프트웨어 스타일)."""
import calendar, datetime, os, subprocess, sys
from pathlib import Path
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox, filedialog
import qrcode
from .ledger import Ledger, LedgerError, InsufficientBalance, TYPE_KO, DEPOSIT, DEDUCT
from .web import start_server, customer_url, owner_url

WIN, MAC = sys.platform.startswith("win"), sys.platform == "darwin"
FAMILY = "Malgun Gothic" if WIN else "Apple SD Gothic Neo" if MAC else None

# 색상 (모던 웹앱 스타일 - 깔끔하고 정돈된 팔레트)
BG = "#f8fafc"          # 배경 (밝은 회색)
CARD = "#ffffff"        # 카드 배경
LINE = "#e2e8f0"        # 테두리 (부드러운 회색)
HEAD = "#f1f5f9"        # 헤더/섹션 배경
TEXT = "#1e293b"        # 기본 텍스트 (진한 슬레이트)
SUB = "#64748b"         # 보조 텍스트 (중간 회색)
ACCENT = "#2563eb"      # 강조색 (파란색)
ACCENT_HOVER = "#1d4ed8" # 강조색 호버
PLUS = "#16a34a"        # 충전 (녹색)
MINUS = "#dc2626"       # 차감 (빨간색)
ZEBRA = "#f8fafc"       # 줄무늬 배경
SEL = "#dbeafe"         # 선택 배경 (연한 파란색)
HEADER_BG = "#1e40af"   # 상단 바 배경 (진한 파란색)
won = lambda n: f"{n:,}원"

# 최소 크기 상수
MIN_CENTER_WIDTH = 500
MIN_PREVIEW_WIDTH = 200


def short(n):
    if n >= 10000:
        v = n / 10000
        return f"{v:.0f}만" if v == int(v) or v >= 10 else f"{v:.1f}만"
    return f"{n/1000:.0f}천" if n >= 1000 else f"{n}"


def open_file(path):
    try:
        if WIN: os.startfile(path)  # noqa
        elif MAC: subprocess.Popen(["open", path])
        else: subprocess.Popen(["xdg-open", path])
    except Exception as e:
        messagebox.showerror("열기 실패", str(e))


class Card(tk.Frame):
    """흰 배경 + 얇은 테두리 패널. 제목 줄 포함."""
    def __init__(self, master, title=None, **kw):
        super().__init__(master, bg=CARD, highlightbackground=LINE, highlightthickness=1, **kw)
        if title is not None:
            h = tk.Frame(self, bg=HEAD, highlightbackground=LINE, highlightthickness=1)
            h.pack(fill="x", padx=1, pady=(1, 0))
            self.title_lbl = tk.Label(h, text=title, bg=HEAD, fg=TEXT, font="TitleFont")
            self.title_lbl.pack(side="left", padx=14, pady=10)
            self.header = h
        self.body = tk.Frame(self, bg=CARD)
        self.body.pack(fill="both", expand=True, padx=16, pady=(12, 14))


class SlideNotebook(tk.Frame):
    """탭 전환: 슬라이드 + 강조선 이동 (<=200ms). <<NotebookTabChanged>> 호환."""
    _ANIM_MS = 160
    _ANIM_STEPS = 8

    def __init__(self, master, active_font=None, inactive_font=None, **kw):
        super().__init__(master, bg=CARD, **kw)
        self._active_font = active_font
        self._inactive_font = inactive_font or active_font
        self._tab_bar = tk.Frame(self, bg=LINE)
        self._tab_bar.pack(fill="x")
        self._tabs_row = tk.Frame(self._tab_bar, bg=CARD)
        self._tabs_row.pack(fill="x")
        self._accent = tk.Frame(self._tab_bar, bg=ACCENT, height=3)
        self._content = tk.Frame(self, bg=CARD)
        self._content.pack(fill="both", expand=True, pady=(6, 0))
        self._pages = []
        self._tab_labels = []
        self._cur = 0
        self._animating = False

    def add(self, child, text):
        idx = len(self._pages)
        lbl = tk.Label(
            self._tabs_row, text=text, bg=HEAD, fg=SUB, padx=16, pady=9, cursor="hand2",
            font=self._inactive_font,
        )
        lbl.pack(side="left")
        lbl.bind("<Button-1>", lambda _e, i=idx: self.select(i))
        self._tab_labels.append(lbl)
        child.place(in_=self._content, relx=0, rely=0, relwidth=1, relheight=1)
        if idx:
            child.place_forget()
        else:
            self._style_tab(0, active=True)
            self.after_idle(lambda: self._move_accent(0))
        self._pages.append(child)

    def tab(self, idx, **kw):
        if "text" in kw:
            self._tab_labels[idx].config(text=kw["text"])
            if idx == self._cur:
                self.after_idle(lambda i=idx: self._move_accent(i))

    def select(self, idx):
        if idx < 0 or idx >= len(self._pages) or self._animating or idx == self._cur:
            return
        self._animate(self._cur, idx)

    def _style_tab(self, idx, active=False):
        lbl = self._tab_labels[idx]
        lbl.config(
            bg=CARD if active else HEAD,
            fg=ACCENT if active else SUB,
            font=self._active_font if active else self._inactive_font,
        )

    def _tab_metrics(self, idx):
        self._tab_bar.update_idletasks()
        lbl = self._tab_labels[idx]
        x = self._tabs_row.winfo_x() + lbl.winfo_x()
        y = self._tabs_row.winfo_y() + self._tabs_row.winfo_height() - 3
        return x, y, max(lbl.winfo_width(), 28)

    def _move_accent(self, idx, from_idx=None):
        x, y, w = self._tab_metrics(idx)
        if from_idx is None or from_idx == idx:
            self._accent.place(x=x, y=y, width=w, height=3)
            return
        x0, y0, w0 = self._tab_metrics(from_idx)
        step = {"n": 0}

        def tick():
            t = step["n"] / self._ANIM_STEPS
            ease = 1 - (1 - t) ** 2
            cx = int(x0 + (x - x0) * ease)
            cw = int(w0 + (w - w0) * ease)
            self._accent.place(x=cx, y=y, width=cw, height=3)
            if step["n"] < self._ANIM_STEPS:
                step["n"] += 1
                self.after(max(1, self._ANIM_MS // self._ANIM_STEPS), tick)
            else:
                self._accent.place(x=x, y=y, width=w, height=3)

        tick()

    def _animate(self, old, new):
        self._animating = True
        old_w, new_w = self._pages[old], self._pages[new]
        direction = 1 if new > old else -1
        w = max(self._content.winfo_width(), 320)
        step = {"n": 0}

        def tick():
            t = step["n"] / self._ANIM_STEPS
            ease = 1 - (1 - t) ** 2
            ox = int(-direction * w * ease)
            nx = int(direction * w * (1 - ease))
            lift = int(10 * (1 - ease))
            old_w.place(relx=0, rely=0, relwidth=1, relheight=1, x=ox, y=0)
            new_w.place(relx=0, rely=0, relwidth=1, relheight=1, x=nx, y=lift)
            if step["n"] < self._ANIM_STEPS:
                step["n"] += 1
                self.after(max(1, self._ANIM_MS // self._ANIM_STEPS), tick)
            else:
                old_w.place_forget()
                new_w.place(relx=0, rely=0, relwidth=1, relheight=1)
                self._cur = new
                self._animating = False
                for i in range(len(self._tab_labels)):
                    self._style_tab(i, active=(i == new))
                self._move_accent(new)
                self.event_generate("<<NotebookTabChanged>>")

        for i in range(len(self._tab_labels)):
            self._style_tab(i, active=(i == new))
        new_w.place(relx=0, rely=0, relwidth=1, relheight=1, x=direction * w, y=10)
        self._move_accent(new, from_idx=old)
        tick()


def ask_string(title, prompt, initialvalue="", show=None, parent=None):
    """단정한 입력 창 (ttk Entry, 넉넉한 여백, Enter=확인, Esc=취소). 취소하면 None."""
    w = tk.Toplevel(parent, bg=CARD); w.title(title); w.resizable(False, False)
    w.transient(parent)
    res = {"v": None}
    f = tk.Frame(w, bg=CARD); f.pack(padx=22, pady=18)
    tk.Label(f, text=prompt, bg=CARD, fg=TEXT, justify="left", anchor="w").pack(fill="x", pady=(0, 8))
    var = tk.StringVar(value="" if initialvalue is None else str(initialvalue))
    e = ttk.Entry(f, textvariable=var, width=34, show=show or "")
    e.pack(fill="x", ipady=3)
    bar = tk.Frame(f, bg=CARD); bar.pack(fill="x", pady=(14, 0))
    def ok(_=None):
        res["v"] = var.get(); w.destroy()
    ttk.Button(bar, text="취소", command=w.destroy).pack(side="right")
    ttk.Button(bar, text="확인", style="Accent.TButton", command=ok).pack(side="right", padx=(0, 6))
    w.bind("<Return>", ok); w.bind("<KP_Enter>", ok); w.bind("<Escape>", lambda _e: w.destroy())
    w.update_idletasks()
    if parent is not None:
        x = parent.winfo_rootx() + (parent.winfo_width() - w.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - w.winfo_height()) // 3
        w.geometry(f"+{max(x, 0)}+{max(y, 0)}")
    e.focus_set(); e.select_range(0, "end"); e.icursor("end")
    try:
        w.grab_set()
    except tk.TclError:
        pass
    w.wait_window()
    return res["v"]


class SignatureDialog:
    """PC용 서명 캔버스 다이얼로그. 마우스/터치스크린으로 서명."""
    def __init__(self, parent, customer_name: str, amount: int):
        self.result = None
        self.strokes = []
        self.current_stroke = []
        
        self.w = tk.Toplevel(parent, bg=CARD)
        self.w.title("서명")
        self.w.resizable(False, False)
        self.w.transient(parent)
        
        f = tk.Frame(self.w, bg=CARD)
        f.pack(padx=20, pady=16)
        
        tk.Label(f, text=f"{customer_name} 님", bg=CARD, fg=TEXT, 
                 font=("TkDefaultFont", 16, "bold")).pack()
        tk.Label(f, text=f"충전 금액: {amount:,}원", bg=CARD, fg=ACCENT,
                 font=("TkDefaultFont", 14)).pack(pady=(4, 12))
        tk.Label(f, text="아래에 서명해 주세요", bg=CARD, fg=SUB).pack()
        
        canvas_frame = tk.Frame(f, bg=LINE, highlightbackground=LINE, highlightthickness=2)
        canvas_frame.pack(pady=8)
        self.canvas = tk.Canvas(canvas_frame, width=400, height=200, bg="white",
                                highlightthickness=0, cursor="pencil")
        self.canvas.pack()
        
        self.canvas.bind("<Button-1>", self._start_stroke)
        self.canvas.bind("<B1-Motion>", self._draw)
        self.canvas.bind("<ButtonRelease-1>", self._end_stroke)
        
        bar = tk.Frame(f, bg=CARD)
        bar.pack(fill="x", pady=(12, 0))
        ttk.Button(bar, text="취소", command=self._cancel).pack(side="left")
        ttk.Button(bar, text="다시 쓰기", command=self._clear).pack(side="left", padx=(8, 0))
        self.ok_btn = ttk.Button(bar, text="확인", style="Accent.TButton", 
                                  command=self._confirm, state="disabled")
        self.ok_btn.pack(side="right")
        
        self.w.bind("<Escape>", lambda e: self._cancel())
        self.w.update_idletasks()
        if parent is not None:
            x = parent.winfo_rootx() + (parent.winfo_width() - self.w.winfo_width()) // 2
            y = parent.winfo_rooty() + (parent.winfo_height() - self.w.winfo_height()) // 3
            self.w.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        try:
            self.w.grab_set()
        except tk.TclError:
            pass
    
    def _start_stroke(self, e):
        self.current_stroke = [(e.x, e.y)]
    
    def _draw(self, e):
        if self.current_stroke:
            x0, y0 = self.current_stroke[-1]
            self.canvas.create_line(x0, y0, e.x, e.y, fill="black", width=2, 
                                    capstyle="round", smooth=True)
            self.current_stroke.append((e.x, e.y))
    
    def _end_stroke(self, e):
        if self.current_stroke:
            self.strokes.append(self.current_stroke)
            self.current_stroke = []
            self._update_ok_state()
    
    def _update_ok_state(self):
        has_content = len(self.strokes) > 0 and any(len(s) > 1 for s in self.strokes)
        self.ok_btn.config(state="normal" if has_content else "disabled")
    
    def _clear(self):
        self.canvas.delete("all")
        self.strokes = []
        self.current_stroke = []
        self._update_ok_state()
    
    def _cancel(self):
        self.result = None
        self.w.destroy()
    
    def _confirm(self):
        if not self.strokes:
            return
        self.result = self._canvas_to_png()
        self.w.destroy()
    
    def _canvas_to_png(self) -> bytes:
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (400, 200), (255, 255, 255, 255))
        draw = ImageDraw.Draw(img)
        for stroke in self.strokes:
            if len(stroke) > 1:
                draw.line(stroke, fill="black", width=2)
        import io
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    
    def wait(self):
        self.w.wait_window()
        return self.result


class App(tk.Tk):
    def __init__(self, ledger: Ledger, serve=True):
        super().__init__()
        self.L = ledger
        self.title("마당 달밥 장부")
        self.geometry("1360x820"); self.minsize(1180, 700)
        self.configure(bg=BG)
        self._load_icon()
        self._fonts(); self._style(); self._install_cursors()
        self.sel = datetime.date.today()
        self.server_error = None
        self._thumb = None
        if serve:
            try:
                start_server(ledger, ledger.settings.get("port", 8765))
            except Exception as e:
                self.server_error = str(e)
        self._build()
        self.refresh()

    def _load_icon(self):
        """앱 아이콘 로드 (번들된 PNG)."""
        self._app_icon = None
        self._app_icon_small = None
        try:
            from PIL import Image, ImageTk
            base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
            icon_path = base / "dalbap" / "icon64.png"
            icon_small_path = base / "dalbap" / "icon.png"
            if icon_path.exists():
                img = Image.open(icon_path)
                self._app_icon = ImageTk.PhotoImage(img)
                self.iconphoto(True, self._app_icon)
            if icon_small_path.exists():
                img_small = Image.open(icon_small_path)
                self._app_icon_small = ImageTk.PhotoImage(img_small)
        except Exception:
            pass

    # ---------------- 스타일 ----------------
    def _fonts(self):
        base = tkfont.nametofont("TkDefaultFont")
        fams = set(tkfont.families(self))
        fam = next((f for f in ("Pretendard", FAMILY, "Malgun Gothic", "Apple SD Gothic Neo", "Noto Sans CJK KR", "NanumGothic",
                                "Gothic A1") if f and f in fams), base.actual("family"))
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            tkfont.nametofont(name).configure(family=fam, size=11)
        self.f_small = tkfont.Font(family=fam, size=9)
        self.f_bold = tkfont.Font(family=fam, size=11, weight="bold")
        tkfont.Font(name="TitleFont", family=fam, size=13, weight="bold")
        self.f_big = tkfont.Font(family=fam, size=17, weight="bold")
        self.fam = fam

    def _style(self):
        st = ttk.Style(self)
        st.theme_use("clam")  # 윈도우·맥 모두 같은 단정한 모양
        st.configure(".", background=CARD, foreground=TEXT)
        st.configure("Treeview", rowheight=28, background=CARD, fieldbackground=CARD, bordercolor=LINE, borderwidth=1)
        st.configure("Treeview.Heading", font=self.f_bold, background=HEAD, foreground=TEXT, relief="flat", padding=(6, 5))
        st.map("Treeview", background=[("selected", SEL)], foreground=[("selected", TEXT)])
        st.map("Treeview.Heading", background=[("active", "#e2e7ee")])
        st.configure("TButton", padding=(12, 7))
        st.configure("Accent.TButton", padding=(12, 8), font=self.f_bold, background=ACCENT, foreground="white")
        st.map("Accent.TButton", background=[("active", ACCENT_HOVER), ("disabled", LINE)],
               foreground=[("disabled", SUB)])
        st.map("TButton", background=[("active", HEAD)])
        st.configure("TNotebook", background=CARD, borderwidth=0)
        st.configure("TNotebook.Tab", padding=(16, 8))
        st.configure("TLabelframe", background=CARD, bordercolor=LINE)
        st.configure("TLabelframe.Label", background=CARD, foreground=SUB, font=self.f_small)
        for w in ("TEntry", "TSpinbox", "TCombobox"):
            st.configure(w, padding=(8, 6), fieldbackground="white", bordercolor=LINE, lightcolor=LINE,
                         darkcolor=LINE, insertcolor=TEXT, selectbackground=SEL, selectforeground=TEXT,
                         arrowsize=14, borderwidth=1)
            st.map(w, bordercolor=[("focus", ACCENT)], lightcolor=[("focus", ACCENT)],
                   darkcolor=[("focus", ACCENT)], fieldbackground=[("readonly", HEAD), ("disabled", BG)])
        self.option_add("*TEntry*Font", "TkTextFont"); self.option_add("*TSpinbox*Font", "TkTextFont")
        self.option_add("*TCombobox*Font", "TkTextFont"); self.option_add("*TCombobox*Listbox.font", "TkTextFont")

    def _install_cursors(self):
        """버튼·탭에 손가락 커서 (웹앱 느낌)."""
        def _hand(_e):
            try:
                _e.widget.configure(cursor="hand2")
            except tk.TclError:
                pass

        def _reset(_e):
            try:
                _e.widget.configure(cursor="")
            except tk.TclError:
                pass

        for cls in ("TButton", "Accent.TButton"):
            self.bind_class(cls, "<Enter>", _hand, add="+")
            self.bind_class(cls, "<Leave>", _reset, add="+")

    def _tree(self, parent, cols, heads, widths, anchors=None, height=None, min_table_width=None):
        """열 최소 너비 유지 + 가로/세로 스크롤 (창이 좁아져도 글꼴 축소 없음)."""
        min_table_width = min_table_width or sum(widths) + 24
        wrap = tk.Frame(parent, bg=CARD)
        wrap.grid_rowconfigure(0, weight=1)
        wrap.grid_columnconfigure(0, weight=1)
        table = tk.Frame(wrap, bg=CARD)
        table.grid(row=0, column=0, sticky="nsew")
        table.grid_rowconfigure(0, weight=1)
        table.grid_columnconfigure(0, weight=1)
        tv = ttk.Treeview(table, columns=cols, show="headings", height=height or 10)
        for c, h, w in zip(cols, heads, widths):
            a = (anchors or {}).get(c, "center")
            tv.heading(c, text=h, anchor=a)
            tv.column(c, width=w, minwidth=w, anchor=a, stretch=False)
        vsb = ttk.Scrollbar(table, orient="vertical", command=tv.yview)
        hsb = ttk.Scrollbar(wrap, orient="horizontal", command=tv.xview)
        tv.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        tv.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        def _sync_xscroll(_event=None):
            tv.update_idletasks()
            need = max(min_table_width, sum(widths) + 8)
            if tv.winfo_width() < need:
                tv.xview_moveto(hsb.get()[0] if hsb.get() else 0)

        tv.bind("<Configure>", _sync_xscroll)
        tv.tag_configure("odd", background=ZEBRA)
        tv.tag_configure("plus", foreground=PLUS)
        tv.tag_configure("minus", foreground=MINUS)
        tv.tag_configure("muted", foreground="#9aa0a6")
        return wrap, tv

    # ---------------- 레이아웃 ----------------
    def _build(self):
        # 상단 제목 줄
        top = tk.Frame(self, bg=HEADER_BG)
        top.pack(fill="x")
        if self._app_icon_small:
            tk.Label(top, image=self._app_icon_small, bg=HEADER_BG).pack(side="left", padx=(20, 10), pady=10)
        tk.Label(top, text="마당", bg=HEADER_BG, fg="#e0e7ff", font=self.f_bold).pack(side="left", pady=10)
        tk.Label(top, text="달밥 장부", bg=HEADER_BG, fg="white", font=self.f_big).pack(side="left", padx=(10, 0), pady=8)
        tk.Label(top, text="월정액 선불 식사 관리", bg=HEADER_BG, fg="#bfdbfe", font=self.f_small).pack(
            side="left", padx=(14, 0), pady=(12, 0))
        self.clock = tk.Label(top, bg=HEADER_BG, fg="#e0e7ff")
        self.clock.pack(side="right", padx=20, pady=10)

        # 상태 표시줄
        sbar = tk.Frame(self, bg=HEAD, highlightbackground=LINE, highlightthickness=1); sbar.pack(side="bottom", fill="x")
        self.st_price = tk.Label(sbar, bg=HEAD, fg=TEXT, padx=12, pady=4); self.st_price.pack(side="left")
        ttk.Separator(sbar, orient="vertical").pack(side="left", fill="y", pady=3)
        self.st_web = tk.Label(sbar, bg=HEAD, fg=TEXT, padx=12); self.st_web.pack(side="left")
        ttk.Separator(sbar, orient="vertical").pack(side="left", fill="y", pady=3)
        self.st_data = tk.Label(sbar, bg=HEAD, fg=SUB, padx=12); self.st_data.pack(side="left")
        self.st_msg = tk.Label(sbar, bg=HEAD, fg=ACCENT, padx=12); self.st_msg.pack(side="right")

        main = tk.Frame(self, bg=BG); main.pack(fill="both", expand=True, padx=14, pady=14)
        main.columnconfigure(1, weight=1, minsize=MIN_CENTER_WIDTH)
        main.rowconfigure(0, weight=1)
        self._build_calendar(main); self._build_day(main); self._build_customers(main)

    def _build_calendar(self, main):
        card = Card(main, "달력"); card.grid(row=0, column=0, sticky="ns", padx=(0, 12))
        nav = tk.Frame(card.header, bg=CARD); nav.pack(side="right")
        ttk.Button(nav, text="◀", width=3, command=lambda: self.shift(-1)).pack(side="left")
        self.y = tk.IntVar(value=self.sel.year); self.m = tk.IntVar(value=self.sel.month)
        ttk.Spinbox(nav, from_=2020, to=2100, textvariable=self.y, width=5, command=self.refresh).pack(side="left", padx=(6, 2))
        tk.Label(nav, text="년", bg=CARD).pack(side="left")
        ttk.Spinbox(nav, from_=1, to=12, textvariable=self.m, width=3, command=self.refresh).pack(side="left", padx=(6, 2))
        tk.Label(nav, text="월", bg=CARD).pack(side="left")
        ttk.Button(nav, text="▶", width=3, command=lambda: self.shift(1)).pack(side="left", padx=(6, 0))
        ttk.Button(nav, text="오늘", command=self.today).pack(side="left", padx=(6, 0))
        self.cal = tk.Frame(card.body, bg=LINE); self.cal.pack(pady=(6, 10))
        legend = tk.Frame(card.body, bg=CARD); legend.pack(fill="x")
        for t, c in (("+ 충전", PLUS), ("− 차감", MINUS), ("🧾 영수증", SUB)):
            tk.Label(legend, text=t, fg=c, bg=CARD, font=self.f_small).pack(side="left", padx=(0, 12))
        ttk.Separator(card.body).pack(fill="x", pady=10)
        sm = tk.Frame(card.body, bg=CARD); sm.pack(fill="x")
        self.month_lbl = tk.Label(sm, bg=CARD, font="TitleFont", anchor="w"); self.month_lbl.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        self.m_dep, self.m_ded, self.m_rc = (tk.Label(sm, bg=CARD, anchor="e", font=self.f_bold, fg=c) for c in (PLUS, MINUS, TEXT))
        for i, (t, l) in enumerate((("충전 합계", self.m_dep), ("차감 합계", self.m_ded), ("영수증", self.m_rc)), start=1):
            tk.Label(sm, text=t, bg=CARD, fg=SUB, anchor="w").grid(row=i, column=0, sticky="w", pady=2)
            l.grid(row=i, column=1, sticky="e", padx=(40, 0))
        sm.columnconfigure(1, weight=1)

    def _build_day(self, main):
        card = Card(main, ""); card.grid(row=0, column=1, sticky="nsew")
        self.day_title = card.title_lbl
        chips = tk.Frame(card.body, bg=CARD); chips.pack(fill="x", pady=(0, 10))
        self.chip = {}
        for k, t, c in (("dep", "충전", PLUS), ("ded", "식사 차감", MINUS), ("rc", "영수증", TEXT)):
            f = tk.Frame(chips, bg=HEAD, highlightbackground=LINE, highlightthickness=1)
            f.pack(side="left", padx=(0, 12), pady=(0, 2))
            tk.Label(f, text=t, bg=HEAD, fg=SUB, font=self.f_small).pack(anchor="w", padx=12, pady=(6, 0))
            v = tk.Label(f, bg=HEAD, fg=c, font="TitleFont"); v.pack(anchor="w", padx=12, pady=(0, 6))
            self.chip[k] = v
        self.nb = SlideNotebook(card.body, active_font=self.f_bold, inactive_font=self.f_small)
        self.nb.pack(fill="both", expand=True)
        # 거래 탭
        t1 = tk.Frame(self.nb._content, bg=CARD)
        self.nb.add(t1, text="거래 내역")
        day_cols = ("time", "name", "kind", "amount", "sig", "rc", "memo")
        day_widths = (70, 120, 120, 100, 30, 30, 180)
        w, self.dayt = self._tree(
            t1, day_cols,
            ("시간", "손님", "구분", "금액", "✍", "🧾", "메모"), day_widths,
            {"amount": "e", "memo": "w", "name": "w"},
            min_table_width=sum(day_widths) + 40,
        )
        w.pack(fill="both", expand=True, pady=(8, 0))
        bar = tk.Frame(t1, bg=CARD); bar.pack(fill="x", pady=(8, 0))
        ttk.Button(bar, text="선택 거래에 영수증 첨부", command=self.attach_to_tx).pack(side="left")
        ttk.Button(bar, text="선택 거래 취소", command=self.cancel_day_tx).pack(side="right")
        tk.Label(bar, text="취소는 삭제하지 않고 반대 거래로 기록됩니다", bg=CARD, fg=SUB, font=self.f_small).pack(side="right", padx=10)
        # 영수증 탭
        t2 = tk.Frame(self.nb._content, bg=CARD)
        self.nb.add(t2, text="영수증")
        rc_widths = (70, 100, 100, 160)
        t2.columnconfigure(0, weight=1, minsize=sum(rc_widths) + 48)
        t2.columnconfigure(1, minsize=MIN_PREVIEW_WIDTH, weight=0)
        t2.rowconfigure(0, weight=1)
        w, self.rct = self._tree(
            t2, ("time", "amount", "name", "memo"), ("등록", "금액", "손님", "메모"), rc_widths,
            {"amount": "e", "memo": "w"},
            min_table_width=sum(rc_widths) + 40,
        )
        w.grid(row=0, column=0, sticky="nsew", pady=(8, 0))
        self.rct.bind("<<TreeviewSelect>>", lambda e: self.preview())
        self.rct.bind("<Double-1>", lambda e: self.open_receipt())
        pv = tk.Frame(t2, bg=HEAD, width=max(300, MIN_PREVIEW_WIDTH), highlightbackground=LINE, highlightthickness=1)
        pv.grid(row=0, column=1, sticky="ns", padx=(10, 0), pady=(8, 0))
        pv.grid_propagate(False)
        self.pv = tk.Label(pv, bg=HEAD, fg=SUB, text="영수증을 선택하면\n미리보기가 나타납니다"); self.pv.pack(fill="both", expand=True)
        bar = tk.Frame(t2, bg=CARD); bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(bar, text="이 날짜에 영수증 추가", command=self.attach_standalone).pack(side="left")
        ttk.Button(bar, text="원본 크게 보기", command=self.open_receipt).pack(side="right")
        ttk.Button(bar, text="휴지통", command=self.show_trash).pack(side="right", padx=(0, 6))
        ttk.Button(bar, text="삭제", command=self.delete_receipt).pack(side="right", padx=(0, 6))
        ttk.Button(bar, text="수정", command=self.edit_receipt).pack(side="right", padx=(0, 6))

    def _build_customers(self, main):
        card = Card(main, "손님"); card.grid(row=0, column=2, sticky="ns", padx=(12, 0))
        self.q = tk.StringVar(); self.q.trace_add("write", lambda *_: self.refresh_customers())
        sf = tk.Frame(card.body, bg=CARD); sf.pack(fill="x", pady=(0, 8))
        tk.Label(sf, text="🔍", bg=CARD).pack(side="left")
        ttk.Entry(sf, textvariable=self.q).pack(side="left", fill="x", expand=True, padx=(4, 0), ipady=2)
        w, self.ct = self._tree(card.body, ("name", "bal"), ("이름", "잔액"), (150, 110), {"name": "w", "bal": "e"}, height=7)
        w.pack(fill="both", expand=True)
        self.ct.bind("<Double-1>", lambda e: self.show_history())
        def group(title, items, accent_first=False):
            g = ttk.LabelFrame(card.body, text=f" {title} ", padding=(6, 2, 6, 6)); g.pack(fill="x", pady=(8, 0))
            for i, (t, cmd) in enumerate(items):
                b = ttk.Button(g, text=t, command=cmd, style="Accent.TButton" if accent_first else "TButton")
                b.grid(row=i // 2, column=i % 2, sticky="ew", padx=3, pady=2)
            g.columnconfigure(0, weight=1, uniform="b"); g.columnconfigure(1, weight=1, uniform="b")
        group("식사 · 충전", (("식사 차감", self.quick_deduct), ("충전", self.charge)), True)
        group("손님 관리", (("새 손님", self.new_customer), ("내역 보기", self.show_history), ("손님 QR", self.show_qr)))
        group("영수증", (("사진 첨부", self.attach_standalone), ("휴대폰 등록", self.show_owner_qr)))
        group("설정", (("1식 가격", self.set_price), ("사장님 PIN", self.set_pin)))

    # ---------------- 갱신 ----------------
    def shift(self, d):
        m = self.m.get() + d; y = self.y.get()
        if m < 1: m, y = 12, y - 1
        if m > 12: m, y = 1, y + 1
        self.y.set(y); self.m.set(m); self.refresh()

    def today(self):
        self.sel = datetime.date.today(); self.y.set(self.sel.year); self.m.set(self.sel.month); self.refresh()

    def pick(self, d):
        self.sel = d; self.refresh()

    def note(self, msg):
        self.st_msg.config(text=msg); self.after(5000, lambda: self.st_msg.config(text=""))

    def _cell(self, r, c, d, s, nrc):
        today = datetime.date.today()
        bg = SEL if d == self.sel else CARD
        f = tk.Frame(self.cal, bg=bg, width=66, height=58, cursor="hand2"); f.grid(row=r, column=c, padx=(0, 1), pady=(0, 1))
        f.grid_propagate(False); f.pack_propagate(False)
        fg = MINUS if c == 6 else ("#2f5fa8" if c == 5 else TEXT)
        num = tk.Label(f, text=str(d.day), bg=ACCENT if d == today else bg, fg="white" if d == today else fg,
                       font=self.f_bold if d in (today, self.sel) else None, padx=4)
        num.place(x=4, y=3)
        kids = [num]
        y = 24
        if s and s["deposit"]:
            kids.append(tk.Label(f, text="+" + short(s["deposit"]), bg=bg, fg=PLUS, font=self.f_small)); kids[-1].place(x=4, y=y); y += 16
        if s and s["deduct"]:
            kids.append(tk.Label(f, text="−" + short(s["deduct"]), bg=bg, fg=MINUS, font=self.f_small)); kids[-1].place(x=4, y=y)
        if nrc:
            kids.append(tk.Label(f, text=f"🧾{nrc}", bg=bg, fg=SUB, font=self.f_small)); kids[-1].place(relx=1, x=-4, y=3, anchor="ne")
        for w in [f] + kids:
            w.bind("<Button-1>", lambda e, d=d: self.pick(d))

    def refresh(self):
        try:
            y, m = int(self.y.get()), int(self.m.get())
        except (tk.TclError, ValueError):
            return
        for w in self.cal.winfo_children(): w.destroy()
        for i, d in enumerate("월화수목금토일"):
            tk.Label(self.cal, text=d, bg=HEAD, fg=MINUS if i == 6 else SUB, width=8, pady=4).grid(row=0, column=i, padx=(0, 1), pady=(0, 1), sticky="ew")
        summ = self.L.month_summary(y, m)
        mrc = self.L.receipts_for(month=f"{y:04d}-{m:02d}")
        rc_by_day = {}
        for r in mrc: rc_by_day[r["date"]] = rc_by_day.get(r["date"], 0) + 1
        for r, week in enumerate(calendar.Calendar().monthdatescalendar(y, m), start=1):
            for c, d in enumerate(week):
                if d.month != m:
                    tk.Frame(self.cal, bg="#f7f8fa", width=66, height=58).grid(row=r, column=c, padx=(0, 1), pady=(0, 1))
                else:
                    self._cell(r, c, d, summ.get(d.isoformat()), rc_by_day.get(d.isoformat(), 0))
        self.month_lbl.config(text=f"{y}년 {m}월 합계")
        self.m_dep.config(text=won(sum(v["deposit"] for v in summ.values())))
        self.m_ded.config(text=won(sum(v["deduct"] for v in summ.values())))
        self.m_rc.config(text=f"{len(mrc)}장")
        self.refresh_day(); self.refresh_customers(); self.refresh_status()

    def refresh_day(self):
        ds = self.sel.isoformat()
        rows = self.L.day(ds)
        rcs = self.L.receipts_for(date=ds)
        self.day_title.config(text=self.sel.strftime("%Y년 %m월 %d일 ") + "월화수목금토일"[self.sel.weekday()] + "요일")
        live = lambda typ: [t for t in rows if t["type"] == typ and not t["cancelled"]]
        self.chip["dep"].config(text=f"{won(sum(t['amount'] for t in live(DEPOSIT)))} · {len(live(DEPOSIT))}건")
        self.chip["ded"].config(text=f"{won(-sum(t['amount'] for t in live(DEDUCT)))} · {len(live(DEDUCT))}건")
        self.chip["rc"].config(text=f"{len(rcs)}장")
        rc_tx = {}
        for r in self.L.receipts_for(): 
            if r["tx_id"]: rc_tx[r["tx_id"]] = rc_tx.get(r["tx_id"], 0) + 1
        self.dayt.delete(*self.dayt.get_children())
        for i, t in enumerate(sorted(rows, key=lambda t: t["ts"], reverse=True)):
            tags = ["odd"] if i % 2 else []
            tags.append("muted" if t["cancelled"] or t["type"] == "cancel" else ("plus" if t["amount"] > 0 else "minus"))
            kind = TYPE_KO[t["type"]] + (" (취소됨)" if t["cancelled"] else "")
            has_sig = "✍" if t.get("signature") or self.L.signature_for_tx(t["id"]) else ""
            self.dayt.insert("", "end", iid=t["id"], tags=tags, values=(t["ts"][11:16], t["name"], kind,
                             f"{t['amount']:+,}", has_sig, "🧾" if rc_tx.get(t["id"]) else "", t["memo"]))
        self.nb.tab(1, text=f"영수증 ({len(rcs)})")
        self.rct.delete(*self.rct.get_children())
        for i, r in enumerate(sorted(rcs, key=lambda r: r["ts"], reverse=True)):
            name = self.L.customers.get(r["cid"], {}).get("name", "") if r["cid"] else ""
            memo = r["memo"] + (" [거래 연결]" if r["tx_id"] else "") + (" [휴대폰]" if r["source"] == "web" else "")
            self.rct.insert("", "end", iid=r["id"], tags=["odd"] if i % 2 else [],
                            values=(r["ts"][11:16], f"{r['amount']:,}" if r["amount"] is not None else "", name, memo))
        self._thumb = None
        self.pv.config(image="", text="영수증을 선택하면\n미리보기가 나타납니다")

    def refresh_customers(self):
        keep = self.ct.selection()
        self.ct.delete(*self.ct.get_children())
        for i, c in enumerate(self.L.search(self.q.get())):
            b = self.L.balance(c["id"])
            tags = (["odd"] if i % 2 else []) + (["minus"] if b < 0 else [])
            self.ct.insert("", "end", iid=c["id"], values=(c["name"], f"{b:,}"), tags=tags)
        for k in keep:
            if self.ct.exists(k): self.ct.selection_set(k)

    def refresh_status(self):
        self.clock.config(text=datetime.date.today().strftime("%Y-%m-%d"))
        self.st_price.config(text=f"1식 가격  {won(self.L.settings.get('meal_price', 9000))}")
        if self.server_error:
            self.st_web.config(text="손님 페이지  ● 오류: " + self.server_error[:60], fg=MINUS)
        else:
            self.st_web.config(text="손님 페이지  ● 실행 중 (매장 와이파이)", fg=PLUS)
        self.st_data.config(text=f"데이터  {self.L.dir}")

    # ---------------- 영수증 ----------------
    def _rec(self):
        s = self.rct.selection()
        return next((r for r in self.L.receipts_for() if s and r["id"] == s[0]), None)

    def preview(self):
        r = self._rec()
        if not r: return
        try:
            from PIL import Image, ImageTk, ImageOps
            with Image.open(self.L.receipt_path(r)) as im:
                im = ImageOps.exif_transpose(im); im.thumbnail((280, 380))
                self._thumb = ImageTk.PhotoImage(im)
            self.pv.config(image=self._thumb, text="")
        except Exception as e:
            self.pv.config(image="", text=f"미리보기 실패\n{e}")

    def open_receipt(self):
        r = self._rec()
        if r: open_file(str(self.L.receipt_path(r)))

    def delete_receipt(self):
        r = self._rec()
        if not r: messagebox.showinfo("선택", "삭제할 영수증을 선택하세요."); return
        if not messagebox.askyesno("영수증 삭제", "이 영수증을 삭제할까요?\n(휴지통으로 옮겨지며 언제든 복원할 수 있습니다)"):
            return
        try:
            self.L.delete_receipt(r["id"])
        except LedgerError as e:
            messagebox.showerror("삭제 실패", str(e)); return
        self.refresh(); self.nb.select(1); self.note("영수증을 휴지통으로 옮겼습니다")

    def show_trash(self):
        w = tk.Toplevel(self, bg=BG); w.title("영수증 휴지통"); w.geometry("720x420")
        card = Card(w, "삭제한 영수증"); card.pack(fill="both", expand=True, padx=12, pady=12)
        wrap, tv = self._tree(card.body, ("date", "amount", "deleted", "memo"), ("날짜", "금액", "삭제한 때", "메모"),
                              (100, 100, 150, 220), {"amount": "e", "memo": "w"})
        wrap.pack(fill="both", expand=True)
        def load():
            tv.delete(*tv.get_children())
            for i, r in enumerate(sorted(self.L.receipts_for(deleted=True), key=lambda r: r["deleted"], reverse=True)):
                tv.insert("", "end", iid=r["id"], tags=["odd"] if i % 2 else [], values=(
                    r["date"], f"{r['amount']:,}" if r["amount"] is not None else "", r["deleted"].replace("T", " ")[:16], r["memo"]))
        def restore():
            if not tv.selection(): return
            try:
                self.L.restore_receipt(tv.selection()[0])
            except LedgerError as e:
                messagebox.showerror("복원 실패", str(e), parent=w); return
            load(); self.refresh(); self.note("영수증을 복원했습니다")
        def view():
            if tv.selection():
                r = next(r for r in self.L.receipts_for(deleted=True) if r["id"] == tv.selection()[0])
                open_file(str(self.L.receipt_path(r)))
        bar = tk.Frame(card.body, bg=CARD); bar.pack(fill="x", pady=(8, 0))
        ttk.Button(bar, text="선택한 영수증 복원", style="Accent.TButton", command=restore).pack(side="right")
        ttk.Button(bar, text="사진 보기", command=view).pack(side="right", padx=(0, 6))
        load()
        return w, tv

    def edit_receipt(self):
        r = self._rec()
        if not r: messagebox.showinfo("선택", "수정할 영수증을 선택하세요."); return None
        w = tk.Toplevel(self, bg=CARD); w.title("영수증 수정"); w.transient(self); w.resizable(False, False)
        f = tk.Frame(w, bg=CARD); f.pack(padx=22, pady=18)
        custs = [("", "- 없음 -")] + [(c["id"], c["name"]) for c in self.L.search("")]
        txs = [("", "- 연결 안 함 -")] + [
            (t["id"], f"{t['ts'][11:16]} {t['name']} {TYPE_KO[t['type']]} {t['amount']:+,}") for t in self.L.day(r["date"])]
        v_amt = tk.StringVar(value="" if r["amount"] is None else f"{r['amount']:,}")
        v_memo = tk.StringVar(value=r["memo"])
        v_c = tk.StringVar(value=dict(custs).get(r["cid"] or "", "- 없음 -"))
        v_t = tk.StringVar(value=dict(txs).get(r["tx_id"] or "", "- 연결 안 함 -"))
        rows = (("금액", ttk.Entry(f, textvariable=v_amt, width=32)),
                ("메모", ttk.Entry(f, textvariable=v_memo, width=32)),
                ("손님", ttk.Combobox(f, textvariable=v_c, values=[n for _, n in custs], state="readonly", width=30)),
                (f"연결 거래 ({r['date']})", ttk.Combobox(f, textvariable=v_t, values=[n for _, n in txs], state="readonly", width=30)))
        for i, (lbl, wd) in enumerate(rows):
            tk.Label(f, text=lbl, bg=CARD, fg=SUB, anchor="w").grid(row=i, column=0, sticky="w", pady=5, padx=(0, 12))
            wd.grid(row=i, column=1, sticky="ew", pady=5, ipady=2)
        def save(_=None):
            cid = next((k for k, n in custs if n == v_c.get()), "")
            tx = next((k for k, n in txs if n == v_t.get()), "")
            amt = v_amt.get().replace(",", "").replace("원", "").strip()
            if amt and not amt.isdigit():
                messagebox.showerror("입력 오류", "금액은 숫자로 입력하세요.", parent=w); return
            try:
                self.L.update_receipt(r["id"], amount=amt or None, memo=v_memo.get(), cid=cid, tx_id=tx)
            except LedgerError as e:
                messagebox.showerror("수정 실패", str(e), parent=w); return
            w.destroy(); self.refresh(); self.nb.select(1); self.note("영수증을 수정했습니다")
        bar = tk.Frame(f, bg=CARD); bar.grid(row=len(rows), column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(bar, text="저장", style="Accent.TButton", command=save).pack(side="left", padx=(0, 6))
        ttk.Button(bar, text="취소", command=w.destroy).pack(side="left")
        w.bind("<Return>", save); w.bind("<Escape>", lambda e: w.destroy())
        rows[0][1].focus_set()
        w._save, w._vars = save, (v_amt, v_memo, v_c, v_t)  # 테스트용
        return w

    def _pick_image(self):
        p = filedialog.askopenfilename(title="영수증 사진 선택", parent=self,
                                       filetypes=[("이미지", "*.jpg *.jpeg *.png *.webp *.gif"), ("모든 파일", "*.*")])
        if not p: return None
        with open(p, "rb") as f:
            return f.read()

    def _save_receipt(self, **kw):
        data = self._pick_image()
        if data is None: return
        try:
            self.L.add_receipt(data, **kw)
        except LedgerError as e:
            messagebox.showerror("영수증 등록 실패", str(e)); return
        self.refresh(); self.nb.select(1); self.note("영수증을 저장했습니다")

    def attach_to_tx(self):
        s = self.dayt.selection()
        if not s:
            messagebox.showinfo("거래 선택", "영수증을 붙일 거래를 목록에서 선택하세요."); return
        t = next(t for t in self.L.tx if t["id"] == s[0])
        self._save_receipt(date=t["date"], amount=abs(t["amount"]), memo=TYPE_KO[t["type"]], cid=t["cid"], tx_id=t["id"])

    def attach_standalone(self):
        amt = ask_string("영수증", f"{self.sel:%m월 %d일} 영수증 금액 (모르면 비워두세요):", parent=self)
        if amt is None: return
        amt = amt.replace(",", "").replace("원", "").strip()
        if amt and not amt.isdigit():
            messagebox.showerror("입력 오류", "금액은 숫자로 입력하세요."); return
        memo = ask_string("영수증", "메모 (예: 식자재, 가스비) - 비워도 됩니다:", parent=self) or ""
        cs = self.ct.selection()
        self._save_receipt(date=self.sel.isoformat(), amount=amt or None, memo=memo,
                           cid=cs[0] if cs and messagebox.askyesno("손님 연결", "선택된 손님에게 연결할까요?") else None)

    # ---------------- 동작 ----------------
    def cur(self):
        s = self.ct.selection()
        if not s:
            messagebox.showinfo("손님 선택", "오른쪽 목록에서 손님을 먼저 선택하세요."); return None
        return self.L.customers[s[0]]

    def ask_amount(self, title, prompt, initial):
        v = ask_string(title, prompt, initialvalue=f"{initial}", parent=self)
        if v is None: return None
        try:
            n = int(v.replace(",", "").replace("원", "").strip())
            if n <= 0: raise ValueError
            return n
        except ValueError:
            messagebox.showerror("입력 오류", "금액을 숫자로 입력하세요."); return None

    def quick_deduct(self):
        c = self.cur()
        if not c: return
        n = self.ask_amount("식사 차감", f"{c['name']} 님 (잔액 {won(self.L.balance(c['id']))})\n차감 금액:",
                            self.L.settings.get("meal_price", 9000))
        if n is None: return
        try:
            self.L.deduct(c["id"], n, memo="식사")
        except InsufficientBalance as e:
            if not messagebox.askyesno("잔액 부족", f"{e}\n그래도 차감할까요? (잔액이 마이너스가 됩니다)", icon="warning"):
                return
            self.L.deduct(c["id"], n, memo="식사 (잔액부족 승인)", allow_negative=True)
        self.today(); self.note(f"{c['name']} 님 {won(n)} 차감")

    def charge(self):
        c = self.cur()
        if not c: return
        n = self.ask_amount("충전", f"{c['name']} 님 충전 금액:", 200000)
        if n is None: return
        memo = ask_string("메모", "메모 (예: 계좌이체, 현금) - 비워도 됩니다", parent=self) or ""
        choice = self._ask_signature_method(c["name"], n)
        if choice is None:
            return
        if choice == "pc":
            sig_dialog = SignatureDialog(self, c["name"], n)
            sig_data = sig_dialog.wait()
            if sig_data is None:
                return
            try:
                sig = self.L.save_signature(sig_data, c["id"], n)
                t = self.L.deposit(c["id"], n, memo, signature_file=sig["file"])
                sig["tx_id"] = t["id"]
                from .storage import write_json_atomic
                write_json_atomic(self.L._signatures_index(), self.L._load_signatures())
            except LedgerError as e:
                messagebox.showerror("충전 실패", str(e))
                return
            self.today()
            self.note(f"{c['name']} 님 {won(n)} 충전 완료")
        elif choice == "ipad":
            try:
                req = self.L.create_signature_request(c["id"], n)
            except LedgerError as e:
                messagebox.showerror("오류", str(e))
                return
            self._show_signature_wait(c, n, memo, req)
            return
        if messagebox.askyesno("영수증", "이 충전에 영수증(이체 내역 등) 사진을 첨부할까요?"):
            t_id = next((tx["id"] for tx in reversed(self.L.tx) if tx["cid"] == c["id"] and tx["type"] == "deposit"), None)
            if t_id:
                tx = next(tx for tx in self.L.tx if tx["id"] == t_id)
                self._save_receipt(date=tx["date"], amount=n, memo="충전", cid=c["id"], tx_id=t_id)
    
    def _ask_signature_method(self, name, amount):
        """서명 방법 선택 다이얼로그. pc/ipad/None(취소) 반환."""
        w = tk.Toplevel(self, bg=CARD)
        w.title("서명 받기")
        w.resizable(False, False)
        w.transient(self)
        result = {"v": None}
        
        f = tk.Frame(w, bg=CARD)
        f.pack(padx=24, pady=20)
        
        tk.Label(f, text=f"{name} 님 충전 {amount:,}원", bg=CARD, fg=TEXT,
                 font=("TkDefaultFont", 14, "bold")).pack(pady=(0, 12))
        tk.Label(f, text="충전을 완료하려면 손님 서명이 필요합니다.\n서명 방법을 선택하세요:", 
                 bg=CARD, fg=SUB, justify="center").pack(pady=(0, 16))
        
        def pick(v):
            result["v"] = v
            w.destroy()
        
        ttk.Button(f, text="🖱 이 PC에서 서명 (마우스/터치)", style="Accent.TButton",
                   command=lambda: pick("pc")).pack(fill="x", pady=4)
        ttk.Button(f, text="📱 아이패드로 서명 받기", 
                   command=lambda: pick("ipad")).pack(fill="x", pady=4)
        ttk.Button(f, text="취소", command=w.destroy).pack(fill="x", pady=(12, 0))
        
        w.bind("<Escape>", lambda e: w.destroy())
        w.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - w.winfo_width()) // 2
        y = self.winfo_rooty() + (self.winfo_height() - w.winfo_height()) // 3
        w.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        try:
            w.grab_set()
        except tk.TclError:
            pass
        w.wait_window()
        return result["v"]
    
    def _show_signature_wait(self, customer, amount, memo, req):
        """아이패드 서명 대기 화면."""
        from .web import signature_url
        w = tk.Toplevel(self, bg=CARD)
        w.title("서명 대기 중")
        w.resizable(False, False)
        w.transient(self)
        
        f = tk.Frame(w, bg=CARD)
        f.pack(padx=24, pady=20)
        
        tk.Label(f, text=f"{customer['name']} 님 충전 {amount:,}원", bg=CARD, fg=TEXT,
                 font=("TkDefaultFont", 14, "bold")).pack()
        tk.Label(f, text="아이패드/휴대폰에서 서명을 기다리는 중...", 
                 bg=CARD, fg=SUB).pack(pady=(8, 16))
        
        url = signature_url(self.L, req["token"])
        qr = qrcode.QRCode(border=2)
        qr.add_data(url)
        qr.make(fit=True)
        mat = qr.get_matrix()
        cell = max(4, 280 // len(mat))
        cv = tk.Canvas(f, width=len(mat)*cell, height=len(mat)*cell, bg="white", highlightthickness=0)
        cv.pack(pady=8)
        for r_idx, row in enumerate(mat):
            for c_idx, on in enumerate(row):
                if on:
                    cv.create_rectangle(c_idx*cell, r_idx*cell, (c_idx+1)*cell, (r_idx+1)*cell, 
                                        fill="black", outline="")
        
        tk.Label(f, text="이미 사장님 페이지에 로그인된 기기에서\n서명 요청이 표시됩니다.", 
                 bg=CARD, fg=SUB, font=self.f_small, justify="center").pack(pady=8)
        
        status_lbl = tk.Label(f, text="⏳ 서명 대기 중 (5분 후 만료)", bg=CARD, fg=ACCENT)
        status_lbl.pack(pady=8)
        
        completed = {"done": False, "tx": None}
        
        def check():
            if completed["done"] or not w.winfo_exists():
                return
            updated_req = self.L.get_signature_request(req["token"])
            if updated_req is None:
                reqs = self.L._pending_signature_requests()
                if not any(r["token"] == req["token"] and r.get("completed") 
                          for r in reqs.values()):
                    status_lbl.config(text="❌ 서명 요청이 만료되었습니다", fg=MINUS)
                    return
            reqs = self.L._pending_signature_requests()
            done_req = reqs.get(req["token"])
            if done_req and done_req.get("completed"):
                completed["done"] = True
                completed["tx"] = done_req.get("tx_id")
                status_lbl.config(text="✅ 서명 완료!", fg=PLUS)
                w.after(1000, w.destroy)
                return
            w.after(1000, check)
        
        def cancel():
            w.destroy()
        
        ttk.Button(f, text="취소", command=cancel).pack(pady=(8, 0))
        
        check()
        w.wait_window()
        
        if completed["done"]:
            self.today()
            self.note(f"{customer['name']} 님 {won(amount)} 충전 완료 (서명)")

    def new_customer(self):
        name = ask_string("새 손님", "이름:", parent=self)
        if not name: return
        phone = ask_string("새 손님", "전화번호 (선택):", parent=self) or ""
        try:
            c = self.L.add_customer(name, phone)
        except LedgerError as e:
            messagebox.showerror("오류", str(e)); return
        self.q.set(""); self.refresh_customers(); self.ct.selection_set(c["id"]); self.ct.see(c["id"])
        if messagebox.askyesno("충전", f"{name} 님을 등록했습니다. 바로 충전할까요?"): self.charge()

    def cancel_day_tx(self):
        s = self.dayt.selection()
        if not s: messagebox.showinfo("선택", "취소할 거래를 목록에서 선택하세요."); return
        self._cancel(s[0])

    def _cancel(self, tx_id):
        t = next(t for t in self.L.tx if t["id"] == tx_id)
        if not messagebox.askyesno("거래 취소", f"{TYPE_KO[t['type']]} {t['amount']:+,}원 거래를 취소할까요?\n(삭제하지 않고 반대 거래로 기록합니다)"):
            return
        reason = ask_string("취소 사유", "사유 (선택):", parent=self) or ""
        try:
            self.L.cancel(tx_id, reason)
        except LedgerError as e:
            messagebox.showerror("취소 불가", str(e)); return
        self.refresh()

    def show_history(self):
        c = self.cur()
        if not c: return
        w = tk.Toplevel(self, bg=BG); w.title(f"{c['name']} 님 내역"); w.geometry("820x580")
        card = Card(w, f"{c['name']} 님  ·  잔액 {won(self.L.balance(c['id']))}"); card.pack(fill="both", expand=True, padx=12, pady=12)
        hist_widths = (150, 120, 100, 100, 220)
        wrap, tv = self._tree(
            card.body, ("ts", "kind", "amount", "bal", "memo"), ("일시", "구분", "금액", "잔액", "메모"),
            hist_widths, {"amount": "e", "bal": "e", "memo": "w"},
            min_table_width=sum(hist_widths) + 40,
        )
        wrap.pack(fill="both", expand=True)
        for i, t in enumerate(self.L.history(c["id"])):
            tags = (["odd"] if i % 2 else []) + ["muted" if t["cancelled"] or t["type"] == "cancel" else ("plus" if t["amount"] > 0 else "minus")]
            tv.insert("", "end", iid=t["id"], tags=tags, values=(t["ts"].replace("T", " ")[:16], TYPE_KO[t["type"]] + (" (취소됨)" if t["cancelled"] else ""),
                                                                f"{t['amount']:+,}", f"{t['balance']:,}", t["memo"]))
        def do():
            if tv.selection(): self._cancel(tv.selection()[0]); w.destroy()
        ttk.Button(card.body, text="선택한 거래 취소", command=do).pack(anchor="e", pady=(8, 0))

    def _qr_window(self, title, headline, url, note, regen):
        w = tk.Toplevel(self, bg=BG); w.title(title)
        card = Card(w, headline); card.pack(padx=12, pady=12)
        qr = qrcode.QRCode(border=2); qr.add_data(url); qr.make(fit=True)
        mat = qr.get_matrix(); cell = max(4, 320 // len(mat))
        cv = tk.Canvas(card.body, width=len(mat) * cell, height=len(mat) * cell, bg="white", highlightthickness=0); cv.pack(pady=6)
        for r, row in enumerate(mat):
            for col, on in enumerate(row):
                if on: cv.create_rectangle(col * cell, r * cell, (col + 1) * cell, (r + 1) * cell, fill="black", outline="")
        e = ttk.Entry(card.body, width=58); e.insert(0, url); e.pack(pady=6)
        tk.Label(card.body, text=note, bg=CARD, fg=SUB, font=self.f_small, justify="left").pack(anchor="w")
        def do():
            if messagebox.askyesno("링크 새로 만들기", "예전 링크는 더 이상 열리지 않습니다. 계속할까요?", parent=w):
                regen(); w.destroy()
        ttk.Button(card.body, text="링크 새로 만들기", command=do).pack(anchor="e", pady=(8, 0))
        return w

    def show_qr(self):
        c = self.cur()
        if not c: return
        self._qr_window(f"{c['name']} 님 전용 QR", f"{c['name']} 님 휴대폰 카메라로 찍으세요", customer_url(self.L, c),
                        "※ 매장 와이파이에 연결된 상태에서만 열립니다. 본인 잔액·내역만 보입니다.",
                        lambda: (self.L.regenerate_token(c["id"]), self.show_qr()))

    def show_owner_qr(self):
        if not self.L.has_owner_pin():
            messagebox.showinfo("사장님 PIN", "먼저 사장님 PIN(숫자 4~8자리)을 정해 주세요.")
            if not self.set_pin(): return
        self._qr_window("영수증 휴대폰 등록", "사장님 아이패드·휴대폰으로 찍으세요", owner_url(self.L),
                        "※ 사장님 전용입니다. 손님에게 보여주지 마세요. 접속 후 PIN을 입력하면\n   '영수증 촬영' 버튼으로 사진을 찍어 이 PC로 보낼 수 있습니다.",
                        lambda: (self.L.regenerate_owner_token(), self.show_owner_qr()))

    def set_pin(self):
        p1 = ask_string("사장님 PIN", "새 PIN (숫자 4~8자리):", show="•", parent=self)
        if not p1: return False
        p2 = ask_string("사장님 PIN", "한 번 더 입력:", show="•", parent=self)
        if p1 != p2:
            messagebox.showerror("PIN", "두 번 입력한 PIN이 다릅니다."); return False
        try:
            self.L.set_owner_pin(p1)
        except LedgerError as e:
            messagebox.showerror("PIN", str(e)); return False
        self.note("사장님 PIN을 저장했습니다 (휴대폰 로그인은 다시 해야 합니다)"); return True

    def set_price(self):
        n = self.ask_amount("1식 가격", "기본 1식 차감 금액:", self.L.settings.get("meal_price", 9000))
        if n: self.L.settings["meal_price"] = n; self.L.save_settings(); self.refresh()


def main():
    from .storage import default_data_dir
    from .fonts import register_fonts
    register_fonts()  # Tk 시작 전에 Pretendard 등록
    App(Ledger(default_data_dir())).mainloop()
