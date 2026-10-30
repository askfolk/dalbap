"""은행 원장 방식 달밥 장부. 거래는 절대 삭제하지 않고, 취소는 반대 거래로 기록."""
import datetime, secrets, threading, uuid
from collections import defaultdict
from pathlib import Path
from .storage import read_json, write_json_atomic, daily_backup

DEPOSIT, DEDUCT, CANCEL = "deposit", "deduct", "cancel"
TYPE_KO = {DEPOSIT: "충전", DEDUCT: "식사 차감", CANCEL: "취소"}


class LedgerError(Exception):
    pass


class InsufficientBalance(LedgerError):
    def __init__(self, balance, amount):
        super().__init__(f"잔액 부족: 잔액 {balance:,}원, 차감 {amount:,}원")
        self.balance, self.amount = balance, amount


class Ledger:
    def __init__(self, data_dir):
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.settings = read_json(self.dir / "settings.json", {"meal_price": 9000, "port": 8765})
        self.customers = read_json(self.dir / "customers.json", {})
        self.tx = []  # 월별 파일 tx/YYYY-MM.json
        for p in sorted((self.dir / "tx").glob("*.json")):
            self.tx.extend(read_json(p, []))
        self.tx.sort(key=lambda t: t["ts"])
        try:
            daily_backup(self.dir)
        except OSError:
            pass

    # ---------- 저장 ----------
    def _save_customers(self):
        write_json_atomic(self.dir / "customers.json", self.customers)

    def _save_month(self, month):
        rows = [t for t in self.tx if t["date"][:7] == month]
        write_json_atomic(self.dir / "tx" / f"{month}.json", rows)

    def save_settings(self):
        with self.lock:
            write_json_atomic(self.dir / "settings.json", self.settings)

    # ---------- 손님 ----------
    def add_customer(self, name, phone="", memo=""):
        name = (name or "").strip()
        if not name:
            raise LedgerError("이름을 입력하세요")
        with self.lock:
            cid = uuid.uuid4().hex[:10]
            self.customers[cid] = {"id": cid, "name": name, "phone": phone.strip(), "memo": memo,
                                   "token": secrets.token_urlsafe(16),
                                   "created": datetime.datetime.now().isoformat(timespec="seconds")}
            self._save_customers()
            return self.customers[cid]

    def regenerate_token(self, cid):
        with self.lock:
            self.customers[cid]["token"] = secrets.token_urlsafe(16)
            self._save_customers()
            return self.customers[cid]["token"]

    def by_token(self, token):
        with self.lock:
            for c in self.customers.values():
                if token and secrets.compare_digest(c["token"], token):
                    return c
        return None

    def search(self, q=""):
        q = (q or "").strip().lower()
        with self.lock:
            res = [c for c in self.customers.values()
                   if not q or q in c["name"].lower() or q in c.get("phone", "")]
        return sorted(res, key=lambda c: c["name"])

    # ---------- 거래 ----------
    def balance(self, cid):
        with self.lock:
            return sum(t["amount"] for t in self.tx if t["cid"] == cid)

    def _add(self, cid, typ, amount, memo, ref=None, when=None):
        if cid not in self.customers:
            raise LedgerError("없는 손님입니다")
        when = when or datetime.datetime.now()
        t = {"id": uuid.uuid4().hex[:12], "cid": cid, "type": typ, "amount": int(amount),
             "memo": memo, "ref": ref, "ts": when.isoformat(timespec="seconds"),
             "date": when.date().isoformat()}
        self.tx.append(t)
        self.tx.sort(key=lambda x: x["ts"])
        try:
            self._save_month(t["date"][:7])
        except Exception:
            self.tx.remove(t)
            raise
        return t

    def deposit(self, cid, amount, memo="", when=None):
        amount = int(amount)
        if amount <= 0:
            raise LedgerError("충전 금액은 0보다 커야 합니다")
        with self.lock:
            return self._add(cid, DEPOSIT, amount, memo, when=when)

    def deduct(self, cid, amount=None, memo="식사", allow_negative=False, when=None):
        amount = int(amount if amount is not None else self.settings.get("meal_price", 9000))
        if amount <= 0:
            raise LedgerError("차감 금액은 0보다 커야 합니다")
        with self.lock:
            bal = self.balance(cid)
            if bal - amount < 0 and not allow_negative:
                raise InsufficientBalance(bal, amount)
            return self._add(cid, DEDUCT, -amount, memo, when=when)

    def is_cancelled(self, tx_id):
        return any(t["type"] == CANCEL and t["ref"] == tx_id for t in self.tx)

    def cancel(self, tx_id, reason="", when=None):
        with self.lock:
            orig = next((t for t in self.tx if t["id"] == tx_id), None)
            if not orig:
                raise LedgerError("거래를 찾을 수 없습니다")
            if orig["type"] == CANCEL:
                raise LedgerError("취소 거래는 다시 취소할 수 없습니다")
            if self.is_cancelled(tx_id):
                raise LedgerError("이미 취소된 거래입니다")
            memo = f"{TYPE_KO[orig['type']]} 취소 ({orig['date']})" + (f" - {reason}" if reason else "")
            return self._add(orig["cid"], CANCEL, -orig["amount"], memo, ref=tx_id, when=when)

    def history(self, cid):
        """잔액 누계 포함, 최신순."""
        with self.lock:
            rows, bal = [], 0
            for t in self.tx:
                if t["cid"] == cid:
                    bal += t["amount"]
                    rows.append(dict(t, balance=bal, cancelled=self.is_cancelled(t["id"])))
        return rows[::-1]

    def day(self, date_str):
        with self.lock:
            rows = [dict(t, name=self.customers.get(t["cid"], {}).get("name", "?"),
                         cancelled=self.is_cancelled(t["id"]))
                    for t in self.tx if t["date"] == date_str]
        return rows

    def month_summary(self, year, month):
        prefix = f"{year:04d}-{month:02d}"
        out = defaultdict(lambda: {"deposit": 0, "deduct": 0, "count": 0})
        with self.lock:
            for t in self.tx:
                if t["date"].startswith(prefix):
                    d = out[t["date"]]
                    d["count"] += 1
                    if t["type"] == DEPOSIT:
                        d["deposit"] += t["amount"]
                    elif t["type"] == DEDUCT:
                        d["deduct"] += -t["amount"]
                    else:  # 취소는 원 거래 종류 합계에서 되돌림
                        if t["amount"] < 0:
                            d["deposit"] += t["amount"]
                        else:
                            d["deduct"] -= t["amount"]
        return dict(out)


# ---------------- 영수증 & 사장님 PIN ----------------
import hashlib, hmac, io, os  # noqa: E402

MAX_RECEIPT_BYTES = 10 * 1024 * 1024
ALLOWED_FORMATS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "GIF": "gif"}


def _receipts_index(self):
    return self.dir / "receipts" / "receipts.json"


def _load_receipts(self):
    if not hasattr(self, "_receipts"):
        self._receipts = read_json(_receipts_index(self), [])
    return self._receipts


def add_receipt(self, data: bytes, date=None, amount=None, memo="", cid=None, tx_id=None, source="desktop"):
    """이미지 검증 후 receipts/YYYY/MM/ 에 저장하고 메타데이터 기록."""
    from PIL import Image, UnidentifiedImageError
    if not data:
        raise LedgerError("빈 파일입니다")
    if len(data) > MAX_RECEIPT_BYTES:
        raise LedgerError("사진이 너무 큽니다 (최대 10MB)")
    try:
        with Image.open(io.BytesIO(data)) as im:
            fmt = im.format
            im.verify()
    except (UnidentifiedImageError, OSError, SyntaxError):
        raise LedgerError("이미지 파일이 아닙니다 (JPG/PNG/WEBP/GIF만 가능)")
    if fmt not in ALLOWED_FORMATS:
        raise LedgerError("지원하지 않는 형식입니다 (JPG/PNG/WEBP/GIF만 가능)")
    if cid and cid not in self.customers:
        raise LedgerError("없는 손님입니다")
    if tx_id and not any(t["id"] == tx_id for t in self.tx):
        raise LedgerError("없는 거래입니다")
    if amount not in (None, ""):
        amount = int(amount)
        if amount < 0:
            raise LedgerError("금액이 올바르지 않습니다")
    else:
        amount = None
    now = datetime.datetime.now()
    date = date or now.date().isoformat()
    datetime.date.fromisoformat(date)
    rid = uuid.uuid4().hex[:12]
    rel = f"receipts/{date[:4]}/{date[5:7]}/{date}_{rid}.{ALLOWED_FORMATS[fmt]}"
    path = self.dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    with open(tmp, "wb") as f:
        f.write(data); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)
    rec = {"id": rid, "date": date, "file": rel, "amount": amount, "memo": (memo or "")[:200],
           "cid": cid or None, "tx_id": tx_id or None, "source": source,
           "ts": now.isoformat(timespec="seconds")}
    with self.lock:
        rs = _load_receipts(self)
        rs.append(rec)
        try:
            write_json_atomic(_receipts_index(self), rs)
        except Exception:
            rs.remove(rec); path.unlink(missing_ok=True); raise
    return rec


def receipts_for(self, date=None, month=None, tx_id=None, deleted=False):
    """deleted=False: 정상만, True: 휴지통만, None: 전부."""
    with self.lock:
        rs = [r for r in _load_receipts(self) if deleted is None or bool(r.get("deleted")) == deleted]
    if date: rs = [r for r in rs if r["date"] == date]
    if month: rs = [r for r in rs if r["date"].startswith(month)]
    if tx_id: rs = [r for r in rs if r["tx_id"] == tx_id]
    return rs


def _get_receipt(self, rid):
    r = next((r for r in _load_receipts(self) if r["id"] == rid), None)
    if not r:
        raise LedgerError("영수증을 찾을 수 없습니다")
    return r


def update_receipt(self, rid, **fields):
    """금액/메모/손님/연결 거래 수정. 값 None 또는 '' 이면 비움."""
    with self.lock:
        r = _get_receipt(self, rid)
        new = dict(r)
        for k, v in fields.items():
            if k not in ("amount", "memo", "cid", "tx_id"):
                raise LedgerError(f"수정할 수 없는 항목: {k}")
            if k == "amount":
                v = None if v in (None, "") else int(str(v).replace(",", ""))
                if v is not None and v < 0: raise LedgerError("금액이 올바르지 않습니다")
            elif k == "memo":
                v = (v or "")[:200]
            elif k == "cid":
                v = v or None
                if v and v not in self.customers: raise LedgerError("없는 손님입니다")
            elif k == "tx_id":
                v = v or None
                if v and not any(t["id"] == v for t in self.tx): raise LedgerError("없는 거래입니다")
            new[k] = v
        new["edited"] = datetime.datetime.now().isoformat(timespec="seconds")
        old = dict(r); r.update(new)
        try:
            write_json_atomic(_receipts_index(self), _load_receipts(self))
        except Exception:
            r.clear(); r.update(old); raise
        return r


def _move_receipt(self, rid, to_trash):
    import shutil
    with self.lock:
        r = _get_receipt(self, rid)
        if bool(r.get("deleted")) == to_trash:
            raise LedgerError("이미 삭제된 영수증입니다" if to_trash else "삭제된 영수증이 아닙니다")
        src = self.dir / r["file"]
        if to_trash:
            dst_rel = "receipts/_trash/" + Path(r["file"]).name
        else:
            dst_rel = r.get("orig_file") or f"receipts/{r['date'][:4]}/{r['date'][5:7]}/" + Path(r["file"]).name
        dst = self.dir / dst_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.exists():
            shutil.move(str(src), str(dst))
        old = dict(r)
        if to_trash:
            r.update(deleted=datetime.datetime.now().isoformat(timespec="seconds"), orig_file=r["file"], file=dst_rel)
        else:
            r.pop("deleted", None); r.pop("orig_file", None); r["file"] = dst_rel
        try:
            write_json_atomic(_receipts_index(self), _load_receipts(self))
        except Exception:
            if dst.exists(): shutil.move(str(dst), str(src))
            r.clear(); r.update(old); raise
        return r


def delete_receipt(self, rid):
    """휴지통(receipts/_trash/)으로 이동 + 삭제 표시. 복원 가능."""
    return _move_receipt(self, rid, True)


def restore_receipt(self, rid):
    return _move_receipt(self, rid, False)


def receipt_path(self, rec):
    return self.dir / rec["file"]


def _hash_pin(pin, salt):
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), 200_000).hex()


def set_owner_pin(self, pin):
    pin = (pin or "").strip()
    if not (pin.isdigit() and 4 <= len(pin) <= 8):
        raise LedgerError("PIN은 숫자 4~8자리로 정하세요")
    with self.lock:
        salt = secrets.token_hex(16)
        self.settings.update(owner_pin_salt=salt, owner_pin_hash=_hash_pin(pin, salt))
        self.settings.setdefault("owner_token", secrets.token_urlsafe(18))
        self.settings["web_secret"] = secrets.token_hex(32)  # PIN 바꾸면 기존 로그인 무효
        self.save_settings()


def check_owner_pin(self, pin):
    h, salt = self.settings.get("owner_pin_hash"), self.settings.get("owner_pin_salt")
    if not h or not pin:
        return False
    return hmac.compare_digest(h, _hash_pin(str(pin), salt))


def owner_token(self):
    with self.lock:
        if "owner_token" not in self.settings:
            self.settings["owner_token"] = secrets.token_urlsafe(18); self.save_settings()
        return self.settings["owner_token"]


def regenerate_owner_token(self):
    with self.lock:
        self.settings["owner_token"] = secrets.token_urlsafe(18)
        self.settings["web_secret"] = secrets.token_hex(32)
        self.save_settings()
        return self.settings["owner_token"]


def web_secret(self):
    with self.lock:
        if "web_secret" not in self.settings:
            self.settings["web_secret"] = secrets.token_hex(32); self.save_settings()
        return self.settings["web_secret"]


for _f in (add_receipt, receipts_for, update_receipt, delete_receipt, restore_receipt, receipt_path, set_owner_pin, check_owner_pin, owner_token,
           regenerate_owner_token, web_secret):
    setattr(Ledger, _f.__name__, _f)
Ledger.has_owner_pin = lambda self: bool(self.settings.get("owner_pin_hash"))
