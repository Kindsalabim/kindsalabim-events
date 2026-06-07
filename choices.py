"""Gemeinsame Auswahllisten & Formatierungs-Helfer für Formulare/Templates."""

# Uhrzeiten 07:00–24:00 in 15-Minuten-Schritten (für Dropdowns)
ZEITEN = [f"{h:02d}:{m:02d}" for h in range(7, 24) for m in (0, 15, 30, 45)] + ["24:00"]


def de_date(d) -> str:
    """Datum als TT.MM.JJJJ; akzeptiert date-Objekt oder None."""
    return d.strftime("%d.%m.%Y") if d else ""
