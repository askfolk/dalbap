"""앱에 포함된 Pretendard 글꼴을 설치 없이 이 프로그램 안에서만 등록."""
import sys
from pathlib import Path

FONT_FILES = ("Pretendard-Regular.ttf", "Pretendard-Bold.ttf")


def font_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "dalbap" / "fonts"


def register_fonts() -> bool:
    """Tk 창을 만들기 전에 호출. 성공하면 True (실패해도 프로그램은 기본 글꼴로 동작)."""
    files = [font_dir() / f for f in FONT_FILES]
    files = [f for f in files if f.exists()]
    if not files:
        return False
    try:
        if sys.platform.startswith("win"):
            import ctypes
            FR_PRIVATE = 0x10
            add = ctypes.windll.gdi32.AddFontResourceExW
            n = sum(add(str(f), FR_PRIVATE, 0) for f in files)
            return n > 0
        if sys.platform == "darwin":
            import ctypes, ctypes.util
            cf = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreFoundation"))
            ct = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreText"))
            cf.CFURLCreateFromFileSystemRepresentation.restype = ctypes.c_void_p
            cf.CFURLCreateFromFileSystemRepresentation.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_bool]
            cf.CFRelease.argtypes = [ctypes.c_void_p]
            ct.CTFontManagerRegisterFontsForURL.restype = ctypes.c_bool
            ct.CTFontManagerRegisterFontsForURL.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
            ok = False
            for f in files:
                p = str(f).encode("utf-8")
                url = cf.CFURLCreateFromFileSystemRepresentation(None, p, len(p), False)
                if url:
                    ok |= bool(ct.CTFontManagerRegisterFontsForURL(url, 1, None))  # 1 = kCTFontManagerScopeProcess
                    cf.CFRelease(url)
            return ok
    except Exception:
        return False
    return False  # 리눅스 등: 시스템 글꼴 사용
