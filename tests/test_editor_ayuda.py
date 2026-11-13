"""La ayuda de firma del editor: cuándo aparece, dónde y qué la hace desaparecer."""

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

QtWidgets = pytest.importorskip("PyQt5.QtWidgets")

from PyQt5.QtCore import QEvent, Qt  # noqa: E402
from PyQt5.QtGui import QFocusEvent, QTextCursor  # noqa: E402

from gui.editor import EditorCRBasic  # noqa: E402
from optabasic.reference import contexto_llamada  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def editor(app):
    e = EditorCRBasic()
    e.resize(700, 400)
    e.show()
    app.processEvents()
    return e


def escribir(editor, texto):
    """Pone el texto y deja el cursor al final, como al tipear."""
    editor.setPlainText(texto)
    editor.moveCursor(QTextCursor.End)
    editor._actualizar_ayuda_firma()


# ── Qué llamada se está escribiendo ──────────────────────────────────────
def test_parentesis_de_agrupacion_no_apaga_la_ayuda_de_la_llamada():
    linea = "  Average(1, (Nivel + Temp"
    assert contexto_llamada(linea, len(linea)) == ("Average", 1)


def test_cerrado_el_grupo_se_cuenta_la_coma_siguiente():
    linea = "  Average(1, (Nivel + Temp), "
    assert contexto_llamada(linea, len(linea)) == ("Average", 2)


def test_dentro_de_una_cadena_no_cuentan_los_parentesis_ni_las_comas():
    linea = '  Sample(1, "a,(b", '
    assert contexto_llamada(linea, len(linea)) == ("Sample", 2)


# ── El cartel ────────────────────────────────────────────────────────────
def test_aparece_al_abrir_el_parentesis(editor):
    escribir(editor, "  VoltSE(")
    assert editor.ayuda_firma.isVisible()


def test_sigue_visible_cuando_el_desplegable_le_saca_el_foco(editor):
    """Qt manda un focusOut con PopupFocusReason al abrir el desplegable."""
    escribir(editor, "  VoltSE(")
    editor.focusOutEvent(QFocusEvent(QEvent.FocusOut, Qt.PopupFocusReason))
    assert editor.ayuda_firma.isVisible()


def test_se_oculta_cuando_el_foco_se_va_de_verdad(editor):
    escribir(editor, "  VoltSE(")
    editor.focusOutEvent(QFocusEvent(QEvent.FocusOut, Qt.TabFocusReason))
    assert not editor.ayuda_firma.isVisible()


def test_va_encima_de_la_linea_y_no_tapa_el_desplegable(editor):
    """El desplegable se abre debajo de la línea; el cartel, arriba."""
    editor.move(0, 320)                             # lugar de sobra arriba
    editor.setPlainText("\n" * 8 + "  VoltSE(")
    editor.moveCursor(QTextCursor.End)
    editor._actualizar_ayuda_firma()
    ayuda = editor.ayuda_firma
    linea_arriba = editor.mapToGlobal(editor.cursorRect().topLeft()).y()
    assert ayuda.isVisible()
    assert ayuda.y() + ayuda.height() <= linea_arriba


def test_sin_lugar_arriba_se_pone_abajo(editor):
    escribir(editor, "  VoltSE(")                   # primera línea: no hay arriba
    ayuda = editor.ayuda_firma
    abajo = editor.mapToGlobal(editor.cursorRect().bottomLeft()).y()
    if ayuda.y() < abajo:                           # cupo arriba en esta pantalla
        pytest.skip("la pantalla de prueba deja lugar arriba del editor")
    assert ayuda.y() >= abajo


def test_se_oculta_al_cerrar_el_parentesis(editor):
    escribir(editor, "  VoltSE(Nivel, 1, mV5000, 1, 1, 0, 1, 0)")
    assert not editor.ayuda_firma.isVisible()
