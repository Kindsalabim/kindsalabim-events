"""Login-Seite bei bestehender Sitzung: /admin/login leitet Eingeloggte ins Dashboard.
Hintergrund: Ein Lesezeichen auf /admin/login zeigte sonst immer das Formular und
wirkte wie „ausgeloggt", obwohl die 30-Tage-Sitzung noch gültig war (Laptop-Mysterium)."""
from auth import create_token


def test_login_seite_leitet_eingeloggte_ins_dashboard(admin):
    r = admin.get("/admin/login", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/dashboard"


def test_login_seite_ohne_cookie_zeigt_formular(client):
    r = client.get("/admin/login")
    assert r.status_code == 200
    assert "password" in r.text.lower()


def test_login_seite_mit_kaputtem_token_zeigt_formular(client):
    client.cookies.set("admin_token", "kein-echtes-jwt")
    r = client.get("/admin/login")
    assert r.status_code == 200
    assert "password" in r.text.lower()


def test_login_seite_mit_portal_token_zeigt_formular(client):
    # Dienstleister-Token (role != admin) darf nicht ins Admin-Dashboard leiten
    client.cookies.set("admin_token", create_token({"sub": "1", "role": "dienstleister"},
                                                   expires_minutes=60))
    r = client.get("/admin/login")
    assert r.status_code == 200
