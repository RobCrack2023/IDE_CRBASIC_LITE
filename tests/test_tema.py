"""Cinta de opciones y tema: que los botones hagan lo que el atajo, y que el
tema oscuro se recuerde.

Los ajustes se redirigen a una carpeta temporal para no pisar los del usuario.
"""

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

QtWidgets = pytest.importorskip("PyQt5.QtWidgets")

from PyQt5.QtCore import QSettings, Qt  # noqa: E402
from PyQt5.QtTest import QTest  # noqa: E402
from PyQt5.QtWidgets import QToolButton  # noqa: E402

from gui import tema  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def ventana(app, tmp_path):
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    from gui.main_window import VentanaPrincipal
    v = VentanaPrincipal()
    v.show()
    app.processEvents()
    return v


def test_la_cinta_tiene_sus_cinco_pestanas(ventana):
    nombres = [ventana.cinta.tabText(i) for i in range(ventana.cinta.count())]
    assert nombres == ["Inicio", "Insertar", "Equipo", "Vista", "Ayuda"]


def test_los_botones_de_la_cinta_usan_las_acciones_de_la_ventana(ventana):
    """Un botón y su atajo tienen que ser la misma acción."""
    acciones = set(ventana._acciones.values())
    botones = [b for b in ventana.cinta.findChildren(QToolButton)
               if b.defaultAction() is not None]
    assert botones
    assert all(b.defaultAction() in acciones for b in botones)


def test_el_atajo_anda_con_el_menu_oculto(ventana, app):
    assert not ventana.menuBar().isVisible()
    antes = ventana.oscuro
    QTest.keyClick(ventana, Qt.Key_D, Qt.ControlModifier)
    app.processEvents()
    assert ventana.oscuro is not antes


def test_el_tema_oscuro_se_recuerda(ventana, app):
    from gui.main_window import VentanaPrincipal
    if not ventana.oscuro:
        ventana.alternar_tema()
    otra = VentanaPrincipal()
    assert otra.oscuro is True
    otra.alternar_tema()                       # vuelve a claro y lo guarda
    assert VentanaPrincipal().oscuro is False


def test_el_tema_se_aplica_a_toda_la_aplicacion(app):
    tema.aplicar(app, True)
    assert tema.CLARO["superficie"] not in app.styleSheet()
    assert tema.OSCURO["superficie"] in app.styleSheet()
    assert tema.actual() is tema.OSCURO
    tema.aplicar(app, False)
    assert tema.actual() is tema.CLARO


def test_los_colores_de_aviso_se_leen_en_los_dos_temas(app):
    tema.aplicar(app, False)
    claro = tema.color_aviso("aviso")
    tema.aplicar(app, True)
    assert tema.color_aviso("aviso") != claro
    tema.aplicar(app, False)
