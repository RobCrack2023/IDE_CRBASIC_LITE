"""Autocompletado del editor: la lista tiene que quedarse mientras se escribe y
poder elegirse con teclado y mouse. Corre sin ventana (plataforma offscreen)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtWidgets = pytest.importorskip("PyQt5.QtWidgets")
from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtTest import QTest  # noqa: E402

from gui.editor import EditorCRBasic  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def editor():
    ed = EditorCRBasic()
    ed.resize(700, 300)
    ed.actualizar_diccionario([("Valor", "lectura del sensor"), ("Nivel_cm", "nivel del rio")])
    ed.show()
    ed.setFocus()
    QTest.qWaitForWindowActive(ed, 2000)
    yield ed
    ed.close()


def _destino(ed):
    """Con la lista abierta, Qt le manda las teclas a ella, no al editor."""
    p = QtWidgets.QApplication.activePopupWidget()
    return p if p is not None else ed


def _teclear(ed, texto):
    for ch in texto:
        QTest.keyClick(_destino(ed), ch)
        QtWidgets.QApplication.processEvents()


def _tecla(ed, tecla):
    QTest.keyClick(_destino(ed), tecla)
    QtWidgets.QApplication.processEvents()


def test_la_lista_sigue_abierta_mientras_se_completa_la_palabra(editor):
    _teclear(editor, "Da")
    assert editor.completer.popup().isVisible()
    for ch in "taTable":
        _teclear(editor, ch)
        assert editor.completer.popup().isVisible(), ch


def test_el_guion_bajo_no_cierra_la_lista(editor):
    _teclear(editor, "Nivel")
    assert editor.completer.popup().isVisible()
    _teclear(editor, "_")
    assert editor.completer.popup().isVisible()
    assert editor.completer.completionPrefix() == "Nivel_"


def test_con_una_sola_coincidencia_las_flechas_no_dejan_la_lista_sin_seleccion(editor):
    _teclear(editor, "DataT")          # una sola coincidencia: DataTable
    assert editor.completer.completionCount() == 1
    for tecla in (Qt.Key_Down, Qt.Key_Up, Qt.Key_Down):
        _tecla(editor, tecla)
        assert editor.completer.popup().currentIndex().isValid(), tecla
    _tecla(editor, Qt.Key_Return)
    assert editor.toPlainText() == "DataTable("


def test_enter_y_tab_insertan_la_opcion_resaltada(editor):
    _teclear(editor, "Sam")
    _tecla(editor, Qt.Key_Return)
    assert editor.toPlainText() == "Sample("


def test_se_elige_con_las_flechas_entre_varias_opciones(editor):
    _teclear(editor, "Da")             # DataInterval, DataTable, Day
    _tecla(editor, Qt.Key_Down)
    _tecla(editor, Qt.Key_Tab)
    assert editor.toPlainText() == "DataTable("


def test_se_elige_con_un_clic_del_mouse(editor):
    _teclear(editor, "Da")
    popup = editor.completer.popup()
    modelo = editor.completer.completionModel()
    rect = popup.visualRect(modelo.index(1, 0))
    QTest.mouseClick(popup.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
    QtWidgets.QApplication.processEvents()
    assert editor.toPlainText() == "DataTable("
    assert not popup.isVisible()
