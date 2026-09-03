"""Migrations-Helfer: Spaltendefinitionen für PostgreSQL.

Hintergrund: Die Tests laufen gegen SQLite, der Postgres-Zweig von
`add_column` wird dort NIE ausgeführt. Ein Fehler darin fällt deshalb erst
produktiv auf – am 03.09.2026 hat ein pauschales replace("DEFAULT 0", …) aus
„FLOAT DEFAULT 0" ein ungültiges „FLOAT DEFAULT false" gemacht, das ALTER
scheiterte still und die Spalte fehlte danach live. Diese Tests prüfen die
Umschreibung deshalb direkt.
"""
from main import pg_typedef


def test_boolean_default_wird_umgeschrieben():
    assert pg_typedef("BOOLEAN DEFAULT 0") == "BOOLEAN DEFAULT false"


def test_zahlen_defaults_bleiben_unangetastet():
    """Der eigentliche Vorfall: FLOAT DEFAULT 0 darf NICHT zu false werden."""
    assert pg_typedef("FLOAT DEFAULT 0") == "FLOAT DEFAULT 0"
    assert pg_typedef("INTEGER DEFAULT 0") == "INTEGER DEFAULT 0"


def test_uebrige_typen_bleiben_gleich():
    for t in ("VARCHAR", "DATE", "INTEGER", "TEXT", "VARCHAR DEFAULT 'inhaber'",
              "VARCHAR DEFAULT 'beide'"):
        assert pg_typedef(t) == t


def test_alle_verwendeten_typedefs_bleiben_gueltig():
    """Kein Aufruf in run_migrations darf durch die Umschreibung kaputtgehen:
    'false' ist nur für BOOLEAN-Spalten ein zulässiger Default."""
    import inspect
    import re

    import main
    quelle = inspect.getsource(main.run_migrations)
    typedefs = re.findall(r'add_column\(\s*"[^"]+",\s*"[^"]+",\s*"([^"]+)"', quelle)
    assert typedefs, "keine add_column-Aufrufe gefunden – Test ins Leere gelaufen"
    for t in typedefs:
        ergebnis = pg_typedef(t)
        if "false" in ergebnis:
            assert ergebnis.upper().startswith("BOOLEAN"), (
                f"'{t}' wurde zu '{ergebnis}' – 'false' ist nur bei BOOLEAN gültig")
