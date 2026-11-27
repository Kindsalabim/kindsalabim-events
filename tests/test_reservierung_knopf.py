"""„Neue Reservierung“ als Knopf oben rechts wie „Neues Event“ (Aykut 26.11.2026)."""


def test_knopf_oben_oeffnet_formular(admin):
    h = admin.get("/admin/reservierungen").text
    knopf = h.index('href="#neue-reservierung" class="btn-primary')
    assert knopf < h.index('<details id="neue-reservierung"')
    assert "+ Neue Reservierung</summary>" not in h
