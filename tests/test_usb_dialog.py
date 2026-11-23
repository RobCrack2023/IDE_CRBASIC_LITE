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


# ── Firmware y restablecer de fábrica ───────────────────────────────────
from PyQt5.QtWidgets import QMessageBox  # noqa: E402

from tests.test_usb_firmware import EquipoConFirmware, imagen  # noqa: E402


@pytest.fixture
def dialogo_fw(app, monkeypatch, tmp_path):
    """Un diálogo conectado a un equipo con firmware, con todas las ventanas
    emergentes simuladas: guarda lo que se le mostró y contesta lo que se le diga."""
    falso = EquipoConFirmware()
    d = DialogoUSB(lambda: (None, None), None)
    d.equipo = EquipoUSB(falso)
    d.equipo.escala = 0.05
    d._correr(lambda t: d.equipo.leer_tablas(), d._tablas_leidas)
    esperar(app, lambda: not d._ocupado() and d.equipo.info.estacion)

    class Pantalla:
        respuestas = []        # lo que contesta cada question(), en orden
        preguntas = []
        avisos = []
        archivo = ""

    monkeypatch.setattr("gui.usb_dialog.QFileDialog.getOpenFileName",
                        lambda *a, **k: (Pantalla.archivo, ""))

    def pregunta(parent, titulo, texto, *a):
        Pantalla.preguntas.append((titulo, texto))
        return Pantalla.respuestas.pop(0)

    monkeypatch.setattr("gui.usb_dialog.QMessageBox.question", pregunta)
    for nombre in ("warning", "information"):
        monkeypatch.setattr(f"gui.usb_dialog.QMessageBox.{nombre}",
                            lambda parent, titulo, texto, *a: Pantalla.avisos.append((titulo, texto)))
    Pantalla.respuestas, Pantalla.preguntas, Pantalla.avisos = [], [], []
    return d, falso, Pantalla, tmp_path


def _bin(tmp_path, datos, nombre="OptaPakBus.ino.bin"):
    ruta = tmp_path / nombre
    ruta.write_bytes(datos)
    return str(ruta)


def test_los_botones_de_firmware_y_restablecer_siguen_la_conexion(app):
    d = DialogoUSB(lambda: (None, None), None)
    assert not d.btn_firmware.isEnabled() and not d.btn_formatear.isEnabled()


def test_cargar_e_instalar_el_firmware_de_punta_a_punta(app, dialogo_fw):
    d, falso, pantalla, tmp = dialogo_fw
    datos = imagen("1.11.1")
    pantalla.archivo = _bin(tmp, datos)
    pantalla.respuestas = [QMessageBox.Yes, QMessageBox.Yes]     # cargar, instalar
    d._cargar_firmware()
    esperar(app, lambda: falso.reiniciado and d.equipo is None, 15)
    assert bytes(falso.fw) == datos
    # la primera pregunta ya dice versión y tamaño; no pide escribir ningún nombre
    titulo, texto = pantalla.preguntas[0]
    assert "1.11.1" in texto and "Estacion1" in texto and str(len(datos)) in texto
    assert pantalla.avisos and "reiniciando" in pantalla.avisos[-1][1]


def test_si_no_se_confirma_la_instalacion_se_aborta_y_el_equipo_sigue_igual(app, dialogo_fw):
    d, falso, pantalla, tmp = dialogo_fw
    pantalla.archivo = _bin(tmp, imagen("1.11.1"))
    pantalla.respuestas = [QMessageBox.Yes, QMessageBox.No]
    d._cargar_firmware()
    esperar(app, lambda: len(pantalla.preguntas) == 2 and not d._ocupado())
    assert "ABORT" in falso.comandos
    assert not falso.reiniciado
    assert d.equipo is not None, "sigue conectado: no se instaló nada"


def test_cancelar_la_primera_pregunta_no_manda_nada(app, dialogo_fw):
    d, falso, pantalla, tmp = dialogo_fw
    pantalla.archivo = _bin(tmp, imagen())
    pantalla.respuestas = [QMessageBox.No]
    d._cargar_firmware()
    assert not any(c.startswith("FW") for c in falso.comandos)


def test_un_archivo_que_no_es_firmware_se_rechaza_con_aviso(app, dialogo_fw):
    d, falso, pantalla, tmp = dialogo_fw
    pantalla.archivo = _bin(tmp, imagen(), "OptaPakBus.ino.with_bootloader.bin")
    d._cargar_firmware()
    assert pantalla.avisos and "with_bootloader" in pantalla.avisos[0][1]
    assert not pantalla.preguntas
    assert not any(c.startswith("FW") for c in falso.comandos)


def test_misma_version_o_anterior_se_avisa_en_la_pregunta(app, dialogo_fw):
    d, falso, pantalla, tmp = dialogo_fw          # el equipo tiene 1.11.0
    pantalla.archivo = _bin(tmp, imagen("1.9.0"))
    pantalla.respuestas = [QMessageBox.No]
    d._cargar_firmware()
    assert "ANTERIOR" in pantalla.preguntas[0][1]


def test_restablecer_no_pide_el_nombre_y_manda_el_de_la_estacion(app, dialogo_fw):
    d, falso, pantalla, tmp = dialogo_fw
    pantalla.respuestas = [QMessageBox.Yes]
    d._restablecer()
    esperar(app, lambda: falso.formateado == "Estacion1" and d.equipo is None, 15)
    assert "BORRAR TODO" in pantalla.preguntas[0][1]
    assert any("restablecido" in a[1] for a in pantalla.avisos)


def test_restablecer_sin_confirmar_no_manda_nada(app, dialogo_fw):
    d, falso, pantalla, tmp = dialogo_fw
    pantalla.respuestas = [QMessageBox.No]
    d._restablecer()
    assert not any(c.startswith("FORMAT") for c in falso.comandos)
    assert d.equipo is not None


def test_borrado_parcial_se_informa_como_aviso(app, dialogo_fw):
    d, falso, pantalla, tmp = dialogo_fw
    falso.format_parcial = True
    pantalla.respuestas = [QMessageBox.Yes]
    d._restablecer()
    esperar(app, lambda: pantalla.avisos and d.equipo is None, 15)
    assert "parcial" in pantalla.avisos[-1][1]
