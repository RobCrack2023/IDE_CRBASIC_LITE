"""El diálogo de USB tiene que tocar la interfaz solo desde el hilo de la ventana.

Cuando una señal se conecta a una lambda, Qt la corre en el hilo que emite;
tocar un widget desde el hilo de la conversación con el equipo tira el
programa. Estas pruebas fallan si algo de eso vuelve.
"""

import os
import sys
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

QtWidgets = pytest.importorskip("PyQt5.QtWidgets")

from gui.usb_dialog import DialogoUSB  # noqa: E402
from optabasic.usb_rescate import EquipoUSB  # noqa: E402
from tests.test_usb_rescate import PROGRAMA, EquipoFalso  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def esperar(app, condicion, segundos=10):
    t = time.time()
    while not condicion() and time.time() - t < segundos:
        app.processEvents()
        time.sleep(0.005)
    assert condicion()


def dialogo_conectado(app, abrir):
    d = DialogoUSB(lambda: (None, None), abrir)
    falso = EquipoFalso()
    falso.guardado = PROGRAMA
    d.equipo = EquipoUSB(falso)
    d.equipo.escala = 0.05
    d._correr(lambda t: d.equipo.leer_tablas(), d._tablas_leidas)
    esperar(app, lambda: d.tabla.count() == 1 and not d._ocupado())
    return d


def test_traer_el_programa_abre_el_editor_en_el_hilo_de_la_ventana(app):
    hilo_ventana = threading.current_thread()
    visto = {}

    def abrir(datos, nombre):
        visto["hilo"] = threading.current_thread()
        visto["datos"] = datos
        return True

    d = dialogo_conectado(app, abrir)
    d._traer_programa()
    esperar(app, lambda: "datos" in visto)
    assert visto["hilo"] is hilo_ventana
    assert visto["datos"] == PROGRAMA


def test_el_log_del_equipo_no_toca_el_widget_desde_otro_hilo(app):
    hilos = []
    d = dialogo_conectado(app, lambda *a: True)
    original = d.registro.appendPlainText

    def espiar(texto):
        hilos.append(threading.current_thread())
        original(texto)

    d.registro.appendPlainText = espiar
    d._traer_programa()
    esperar(app, lambda: d.equipo is None)        # al terminar cierra el diálogo
    assert hilos, "el equipo falso mete log de depuración: debería haber líneas"
    assert all(h is threading.main_thread() for h in hilos)


def test_un_fallo_tambien_vuelve_al_hilo_de_la_ventana(app):
    hilos = []
    d = dialogo_conectado(app, lambda *a: True)
    d.equipo.t.guardado = b""                     # sin programa: el equipo da ERR
    original = d.estado.setText
    d.estado.setText = lambda t: (hilos.append(threading.current_thread()), original(t))
    d._traer_programa()
    esperar(app, lambda: not d._ocupado() and "No se pudo leer" in d.estado.text())
    assert all(h is threading.main_thread() for h in hilos)


class EquipoMudo:
    """Un puerto que abre bien pero donde el equipo no contesta nada, como un
    Opta sin red ocupado buscando DHCP."""

    def __init__(self):
        self.cerrado = False

    def write(self, datos):
        pass

    def read(self, n=1):
        time.sleep(0.002)
        return b""

    def close(self):
        self.cerrado = True


def test_equipo_que_no_contesta_avisa_y_vuelve_a_conectar(app, monkeypatch):
    mudo = EquipoMudo()

    def abrir(dev):
        e = EquipoUSB(mudo)
        e.escala = 0.02          # no esperar los 12 s de verdad
        return e

    avisos = []
    monkeypatch.setattr("gui.usb_dialog.usb.abrir_puerto", abrir)
    monkeypatch.setattr("gui.usb_dialog.QMessageBox.warning",
                        lambda *a: avisos.append(a[1:3]))
    d = DialogoUSB(lambda: (None, None), None)
    d.puertos.clear()
    d.puertos.addItem("USB de prueba", "COM99")
    d._conectar_o_desconectar()
    esperar(app, lambda: bool(avisos))
    # lo que ve quien opera: una ventana con el motivo y el botón en «Conectar»
    titulo, texto = avisos[0]
    assert titulo == "No se pudo conectar"
    assert "red" in texto and "no respond" in texto
    esperar(app, lambda: d.equipo is None)
    assert d.btn_conectar.text() == "Conectar"
    assert d.btn_conectar.isEnabled()
    assert d.puertos.isEnabled()
    assert mudo.cerrado, "tiene que soltar el puerto para poder reintentar"
    assert d.estado.text() == "No se pudo conectar con el equipo."
