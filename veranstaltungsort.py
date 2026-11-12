"""Wohin das Team fährt: Name + Anschrift des Veranstaltungsorts fürs Briefing.

Die Checkliste fragt erst die Firmendaten (cl_firma_name/cl_strasse/cl_plz_ort) und
dann den Veranstaltungsort: Haken „gleich wie Firmendaten" oder eigene Angaben
(cl_ort_*). Hintergrund (Aykut 12.11.2026): Eine Agentur bucht für Toys"R"Us, im
Briefing stand die Agentur über der Adresse, Dienstleister wussten nicht, wohin.

cl_ort_gleich ist bei älteren Events leer (None). Dort waren die cl_*-Felder schon
immer die Veranstaltungsanschrift, also gelten sie weiter.
"""


def _s(x) -> str:
    s = x if isinstance(x, str) else ("" if x is None else str(x))
    return "" if s.strip().lower() == "none" else s.strip()


def eigener_ort(ev) -> bool:
    """True, wenn ein vom Firmensitz abweichender Veranstaltungsort angegeben ist."""
    return getattr(ev, "cl_ort_gleich", None) is False and any(
        _s(getattr(ev, f, "")) for f in ("cl_ort_name", "cl_ort_strasse", "cl_ort_plz_ort"))


def anschrift(ev) -> tuple:
    """(Name, Straße, PLZ & Ort) des Veranstaltungsorts. Den Auftraggeber als Namen
    nur bei Privatkunden (Name an der Klingel); bei Firmen ist er oft eine Agentur."""
    if eigener_ort(ev):
        name, strasse, plz_ort = (_s(getattr(ev, f, "")) for f in
                                  ("cl_ort_name", "cl_ort_strasse", "cl_ort_plz_ort"))
    else:
        name, strasse, plz_ort = (_s(getattr(ev, f, "")) for f in
                                  ("cl_firma_name", "cl_strasse", "cl_plz_ort"))
    if not name and getattr(ev, "privatkunde", False):
        name = _s(getattr(ev, "kunde_firma", ""))
    if not strasse and not plz_ort:
        plz_ort = _s(getattr(ev, "veranstaltungsort", ""))
    return name, strasse, plz_ort
