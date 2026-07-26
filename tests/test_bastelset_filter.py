"""Bastel-Recherche: nur echte Bastelsets kuratieren, kein loses Material."""
from types import SimpleNamespace

from bakerross_service import _ist_bastelset


def _p(name):
    return SimpleNamespace(name=name)


def test_material_wird_aussortiert():
    assert not _ist_bastelset(_p("Halloween-Sticker"))
    assert not _ist_bastelset(_p("Glitzeraufkleber Herbst"))
    assert not _ist_bastelset(_p("Stempel-Set Tiere"))
    assert not _ist_bastelset(_p("Buntstifte 12er-Pack"))
    assert not _ist_bastelset(_p("Wackelaugen selbstklebend"))
    assert not _ist_bastelset(_p("Konfetti bunt"))


def test_bastelsets_bleiben_drin():
    assert _ist_bastelset(_p("Igel-Bastelsets aus Holz"))
    assert _ist_bastelset(_p("Laternen-Bastelsets"))
    assert _ist_bastelset(_p("Kratzbilder Einhorn"))
    assert _ist_bastelset(_p("Fensterbilder Weihnachten"))


def test_bastelset_ausnahme_schlaegt_materialwort():
    # "Bastelset" im Namen gewinnt gegen das Materialwort
    assert _ist_bastelset(_p("Sticker-Mosaik-Bastelsets"))
    assert _ist_bastelset(_p("Stiftehalter-Bastelsets"))
    assert _ist_bastelset(_p("Perlen-Bastelsets Meerjungfrau"))
