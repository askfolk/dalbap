"""손님용 읽기 전용 웹 (매장 와이파이). /c/<토큰> 에서 본인 잔액·내역만 표시."""
import socket, threading
from flask import Flask, abort, render_template_string
from .ledger import TYPE_KO

PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>달밥 잔액</title><style>
body{font-family:-apple-system,'Apple SD Gothic Neo','Malgun Gothic',sans-serif;margin:0;background:#f6f3ee;color:#222}
.card{background:#fff;margin:16px;padding:20px;border-radius:16px;box-shadow:0 2px 8px #0001}
h1{font-size:22px;margin:0 0 4px}.bal{font-size:40px;font-weight:800;color:#c0392b}
table{width:100%;border-collapse:collapse;font-size:16px}td{padding:10px 4px;border-bottom:1px solid #eee}
.p{color:#1e7e34}.m{color:#c0392b}.s{color:#999;font-size:13px}.x{text-decoration:line-through;color:#aaa}
</style></head><body>
<div class="card"><h1>{{c.name}} 님</h1><div class="s">현재 잔액</div>
<div class="bal">{{"{:,}".format(bal)}}원</div><div class="s">식사 약 {{meals}}회 남음 (1회 {{"{:,}".format(price)}}원 기준)</div></div>
<div class="card"><h1>이용 내역</h1><table>
{% for t in rows %}<tr><td><div {% if t.cancelled %}class="x"{% endif %}>{{kind[t.type]}} {{t.memo if t.type!='cancel' else ''}}</div>
<div class="s">{{t.ts.replace('T',' ')[:16]}}</div></td>
<td style="text-align:right"><div class="{{'p' if t.amount>0 else 'm'}}">{{"{:+,}".format(t.amount)}}원</div>
<div class="s">잔액 {{"{:,}".format(t.balance)}}</div></td></tr>{% else %}<tr><td>내역이 없습니다</td></tr>{% endfor %}
</table></div><p class="s" style="text-align:center">이 링크는 본인 전용입니다. 다른 사람과 공유하지 마세요.</p>
</body></html>"""


OWNER_PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>달밥 사장님 · 영수증</title><style>
body{font-family:-apple-system,'Apple SD Gothic Neo','Malgun Gothic',sans-serif;margin:0;background:#f3f4f6;color:#222}
.card{background:#fff;margin:14px;padding:18px;border-radius:12px;border:1px solid #e3e5e8}
h1{font-size:20px;margin:0 0 12px}label{display:block;font-size:14px;color:#555;margin:12px 0 4px}
input,select{width:100%;box-sizing:border-box;font-size:18px;padding:10px;border:1px solid #ccc;border-radius:8px}
.btn{display:block;width:100%;padding:16px;font-size:20px;font-weight:700;border:0;border-radius:10px;background:#1f5fae;color:#fff;margin-top:16px}
.cam{background:#2e7d32}.msg{padding:10px;border-radius:8px;margin:14px}.ok{background:#e6f4ea}.err{background:#fde8e8}
.s{color:#888;font-size:13px}</style></head><body>
{% if msg %}<div class="msg {{'ok' if ok else 'err'}}">{{msg}}</div>{% endif %}
{% if not authed %}
<form class="card" method="post" action="{{url_for('owner_login', token=token)}}"><h1>사장님 PIN</h1>
<input name="pin" type="password" inputmode="numeric" autocomplete="off" autofocus>
<button class="btn">확인</button></form>
{% else %}
<form class="card" method="post" enctype="multipart/form-data" action="{{url_for('owner_upload', token=token)}}">
<h1>영수증 등록</h1>
<label class="btn cam" for="f">📷 영수증 촬영</label>
<input id="f" name="photo" type="file" accept="image/*" capture="environment" required style="display:none"
 onchange="document.getElementById('fn').textContent=this.files[0]?this.files[0].name:''">
<div id="fn" class="s"></div>
<label>날짜</label><input name="date" type="date" value="{{today}}">
<label>금액 (선택)</label><input name="amount" inputmode="numeric" pattern="[0-9,]*">
<label>손님 (선택)</label><select name="cid"><option value="">- 없음 -</option>
{% for c in customers %}<option value="{{c.id}}">{{c.name}}</option>{% endfor %}</select>
<label>메모 (선택)</label><input name="memo" maxlength="200">
<button class="btn">PC로 보내기</button>
<p class="s">오늘 등록된 영수증 {{count}}장 · 최대 10MB, JPG/PNG/WEBP</p></form>
<div class="card"><h1>최근 영수증</h1>
{% for r in recent %}<div style="display:flex;align-items:center;border-bottom:1px solid #eee;padding:8px 0">
<div style="flex:1"><div>{{r.date}} · {{"{:,}원".format(r.amount) if r.amount is not none else "금액 없음"}}</div>
<div class="s">{{r.memo}}{% if r.cname %} · {{r.cname}}{% endif %}</div></div>
<form method="post" action="{{url_for('owner_delete', token=token, rid=r.id)}}" onsubmit="return confirm('이 영수증을 삭제할까요? (PC 휴지통에서 복원 가능)')">
<button style="padding:8px 14px;border:1px solid #d33;background:#fff;color:#d33;border-radius:8px;font-size:15px">삭제</button></form></div>
{% else %}<p class="s">등록된 영수증이 없습니다</p>{% endfor %}</div>
<p class="s" style="text-align:center"><a href="{{url_for('owner_logout', token=token)}}">로그아웃</a></p>
{% endif %}</body></html>"""


def create_app(ledger):
    import datetime, time
    from flask import request, session, redirect, url_for
    from .ledger import LedgerError, MAX_RECEIPT_BYTES
    class _App(Flask):
        @property
        def secret_key(self):  # PIN/링크 변경 시 바뀌어 기존 로그인 무효화
            return ledger.web_secret()

        @secret_key.setter
        def secret_key(self, v):
            pass

    app = _App(__name__)
    app.config.update(MAX_CONTENT_LENGTH=MAX_RECEIPT_BYTES + 512 * 1024,
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict",
                      PERMANENT_SESSION_LIFETIME=datetime.timedelta(hours=12))
    fails = {}  # ip -> [횟수, 잠금해제시각]

    def owner_ok(token):
        import secrets as _s
        return bool(token) and _s.compare_digest(token, ledger.owner_token()) and ledger.has_owner_pin()

    def render_owner(token, msg=None, ok=True, code=200):
        authed = session.get("owner") == token
        today = datetime.date.today().isoformat()
        return render_template_string(OWNER_PAGE, token=token, authed=authed, msg=msg, ok=ok, today=today,
                                      customers=ledger.search("") if authed else [],
                                      count=len(ledger.receipts_for(date=today)) if authed else 0,
                                      recent=recent(10) if authed else []), code

    def recent(n):
        rs = sorted(ledger.receipts_for(), key=lambda r: r["ts"], reverse=True)[:n]
        return [dict(r, cname=ledger.customers.get(r["cid"], {}).get("name", "") if r["cid"] else "") for r in rs]

    @app.route("/o/<token>/delete/<rid>", methods=["POST"])
    def owner_delete(token, rid):
        if not owner_ok(token): abort(404)
        if session.get("owner") != token: abort(403)
        try:
            ledger.delete_receipt(rid)
        except LedgerError as e:
            return render_owner(token, f"삭제 실패: {e}", False, 400)
        return render_owner(token, "🗑 삭제했습니다 (PC에서 복원 가능)")

    @app.route("/o/<token>")
    def owner(token):
        if not owner_ok(token): abort(404)
        return render_owner(token)

    @app.route("/o/<token>/login", methods=["POST"])
    def owner_login(token):
        if not owner_ok(token): abort(404)
        ip = request.remote_addr
        n, until = fails.get(ip, [0, 0])
        if time.time() < until:
            return render_owner(token, "잠시 후 다시 시도하세요 (5분 잠금)", False, 429)
        if ledger.check_owner_pin(request.form.get("pin", "")):
            fails.pop(ip, None); session.clear(); session.permanent = True; session["owner"] = token
            return redirect(url_for("owner", token=token))
        n += 1
        fails[ip] = [0, time.time() + 300] if n >= 5 else [n, 0]
        return render_owner(token, "PIN이 틀렸습니다", False, 403)

    @app.route("/o/<token>/logout")
    def owner_logout(token):
        session.clear()
        return redirect(url_for("owner", token=token))

    @app.route("/o/<token>/upload", methods=["POST"])
    def owner_upload(token):
        if not owner_ok(token): abort(404)
        if session.get("owner") != token: abort(403)
        f = request.files.get("photo")
        if not f: return render_owner(token, "사진을 먼저 찍어 주세요", False, 400)
        try:
            amt = request.form.get("amount", "").replace(",", "").strip() or None
            ledger.add_receipt(f.read(MAX_RECEIPT_BYTES + 1), date=request.form.get("date") or None, amount=amt,
                               memo=request.form.get("memo", ""), cid=request.form.get("cid") or None, source="web")
        except (LedgerError, ValueError) as e:
            return render_owner(token, f"등록 실패: {e}", False, 400)
        return render_owner(token, "✅ 영수증을 PC에 저장했습니다")

    @app.errorhandler(413)
    def too_big(e):
        return "사진이 너무 큽니다 (최대 10MB)", 413

    @app.after_request
    def nocache(r):
        r.headers["Cache-Control"] = "no-store"
        r.headers["X-Frame-Options"] = "DENY"
        return r

    @app.route("/")
    def index():
        return "달밥 손님 페이지입니다. 매장에서 받은 개인 QR 코드로 접속하세요.", 200

    @app.route("/c/<token>")
    def customer(token):
        c = ledger.by_token(token)
        if not c:
            abort(404)
        bal = ledger.balance(c["id"])
        price = int(ledger.settings.get("meal_price", 9000)) or 1
        return render_template_string(PAGE, c=c, bal=bal, rows=ledger.history(c["id"])[:200],
                                      kind=TYPE_KO, price=price, meals=max(bal, 0) // price)

    return app


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def start_server(ledger, port=8765):
    from waitress import serve
    app = create_app(ledger)
    th = threading.Thread(target=serve, args=(app,), kwargs={"host": "0.0.0.0", "port": port, "threads": 4},
                          daemon=True)
    th.start()
    return th


def owner_url(ledger):
    return f"http://{lan_ip()}:{ledger.settings.get('port', 8765)}/o/{ledger.owner_token()}"


def customer_url(ledger, c):
    return f"http://{lan_ip()}:{ledger.settings.get('port', 8765)}/c/{c['token']}"
