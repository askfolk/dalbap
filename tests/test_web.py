import pytest
from dalbap.ledger import Ledger
from dalbap.web import create_app


@pytest.fixture
def setup(tmp_path):
    L = Ledger(tmp_path)
    a = L.add_customer("홍길동"); b = L.add_customer("성춘향")
    L.deposit(a["id"], 100000, "계좌이체"); L.deduct(a["id"], 9000)
    L.deposit(b["id"], 777000)
    return L, a, b, create_app(L).test_client()


def test_own_page(setup):
    L, a, b, cl = setup
    r = cl.get(f"/c/{a['token']}")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "홍길동" in html and "91,000원" in html
    assert "성춘향" not in html and "777,000" not in html
    assert r.headers["Cache-Control"] == "no-store"


def test_bad_token_404(setup):
    L, a, b, cl = setup
    assert cl.get("/c/nope").status_code == 404
    assert cl.get("/c/").status_code == 404
    assert cl.get(f"/c/{a['token'][:-1]}").status_code == 404


def test_no_admin_or_listing(setup):
    L, a, b, cl = setup
    r = cl.get("/")
    assert "홍길동" not in r.get_data(as_text=True)
    for p in ("/admin", "/customers", "/api/customers"):
        assert cl.get(p).status_code == 404
    assert cl.post(f"/c/{a['token']}").status_code == 405


def test_real_server_over_http(setup):
    import socket, time, urllib.request
    from dalbap.web import start_server
    L, a, b, cl = setup
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    start_server(L, port)
    for _ in range(50):
        try:
            html = urllib.request.urlopen(f"http://127.0.0.1:{port}/c/{a['token']}", timeout=1).read().decode()
            break
        except OSError:
            time.sleep(0.1)
    assert "91,000원" in html
