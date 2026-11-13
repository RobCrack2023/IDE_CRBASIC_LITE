"""Antes de enviar un programa (servidor o USB) tiene que estar sin errores y
guardado en disco. No hay «enviar de todos modos»."""

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

QtWidgets = pytest.importorskip("PyQt5.QtWidgets")

from PyQt5.QtCore import QSettings  # noqa: E402
from PyQt5.QtWidgets import QFileDialog, QMessageBox  # noqa: E402

from gui.snippets import PROGRAMA_NUEVO  # noqa: E402

CON_ERRORES = PROGRAMA_NUEVO + "\nDataTable(Otra,True,10)\n"


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class Avisos:
    """Registra qué avisos se mostraron y contesta lo que se le indique."""

    def __init__(self, monkeypatch, responde=QMessageBox.Yes, ruta_guardar=""):
        self.criticos = []
        self.preguntas = []
        self.pidio_ruta = 0
        monkeypatch.setattr(QMessageBox, "critical", staticmethod(
            lambda padre, titulo, texto, *a, **k: self.criticos.append(titulo)))
        monkeypatch.setattr(QMessageBox, "question", staticmethod(
            lambda padre, titulo, texto, *a, **k:
            (self.preguntas.append(titulo), responde)[1]))

        def ruta(*a, **k):
            self.pidio_ruta += 1
            return ruta_guardar, ""
        monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(ruta))


@pytest.fixture
def ventana(app, tmp_path):
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    from gui.main_window import VentanaPrincipal
    return VentanaPrincipal()


def test_con_errores_no_se_envia_ni_se_ofrece_enviar_igual(ventana, monkeypatch, tmp_path):
    avisos = Avisos(monkeypatch)
    ventana.editor.setPlainText(CON_ERRORES)
    assert ventana._programa_para_enviar() is None
    assert avisos.criticos == ["No se puede enviar"]
    assert avisos.preguntas == []                 # ni siquiera pregunta por guardar
    assert avisos.pidio_ruta == 0


def test_sin_guardar_obliga_a_guardar_y_envia_lo_guardado(ventana, monkeypatch, tmp_path):
    destino = str(tmp_path / "prog.CR1")
    avisos = Avisos(monkeypatch, ruta_guardar=destino)
    listo = ventana._programa_para_enviar()
    assert avisos.preguntas == ["Guardar antes de enviar"]
    assert listo is not None
    datos, nombre = listo
    assert nombre == "prog.CR1"
    with open(destino, "rb") as f:
        assert f.read() == datos                  # lo enviado es lo del disco
    assert not ventana.editor.document().isModified()


def test_si_no_quiere_guardar_no_se_envia(ventana, monkeypatch):
    avisos = Avisos(monkeypatch, responde=QMessageBox.No)
    assert ventana._programa_para_enviar() is None
    assert avisos.pidio_ruta == 0


def test_si_cancela_el_guardar_como_no_se_envia(ventana, monkeypatch):
    Avisos(monkeypatch, ruta_guardar="")          # el usuario cierra el diálogo
    assert ventana._programa_para_enviar() is None


def test_cambios_sin_guardar_en_un_archivo_existente_tambien_obligan(ventana, monkeypatch, tmp_path):
    destino = str(tmp_path / "prog.CR1")
    Avisos(monkeypatch, ruta_guardar=destino)
    assert ventana._programa_para_enviar() is not None      # primer envío: lo guarda
    ventana.editor.appendPlainText("' un comentario nuevo")
    avisos = Avisos(monkeypatch)
    listo = ventana._programa_para_enviar()
    assert avisos.preguntas == ["Guardar antes de enviar"]
    assert avisos.pidio_ruta == 0                 # ya tiene ruta: no pide dónde
    with open(destino, "rb") as f:
        assert f.read() == listo[0]


def test_programa_guardado_y_limpio_se_envia_sin_preguntar(ventana, monkeypatch, tmp_path):
    destino = str(tmp_path / "prog.CR1")
    Avisos(monkeypatch, ruta_guardar=destino)
    ventana._programa_para_enviar()               # lo deja guardado
    avisos = Avisos(monkeypatch)
    assert ventana._programa_para_enviar() is not None
    assert avisos.preguntas == [] and avisos.criticos == []
