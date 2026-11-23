"""Diálogo de variables en vivo contra un equipo simulado."""

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

pytest.importorskip("PyQt5")
from PyQt5.QtWidgets import QApplication  # noqa: E402

from gui.sensor_wizard import AsistenteSensor  # noqa: E402
from gui.variables_dialog import DialogoVariables, formatear  # noqa: E402
from optabasic.usb_rescate import EquipoUSB  # noqa: E402
from tests.test_usb_variables import EquipoConVariables  # noqa: E402

app = QApplication.instance() or QApplication([])


def esperar(condicion, segundos=5.0):
    t = time.time()
    while not condicion() and time.time() - t < segundos:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    return condicion()


def equipo_conectado(**kw):
    falso = EquipoConVariables(**kw)
    e = EquipoUSB(falso)
    e.escala = 0.05
    e.leer_tablas()
    return e, falso


def abrir(equipo, **kw):
    d = DialogoVariables(equipo=equipo, **kw)
    d.auto.setChecked(False)               # una sola lectura, sin timer
    d.show()
    assert esperar(lambda: d.tabla.rowCount() > 0)
    return d


def test_formatear_valores():
    assert formatear(7.40) == "7.4"
    assert formatear(-12.5) == "-12.5"
    assert formatear(float("nan")) == "NAN"
    assert formatear(0.0) == "0"


def test_muestra_las_variables_del_equipo_conectado():
    e, falso = equipo_conectado()
    d = abrir(e)
    assert d.tabla.rowCount() == 5
    assert d.tabla.item(0, 0).text() == "Rio_filt"
    assert d.tabla.item(0, 1).text() == "7.4"
    assert d.tabla.item(1, 2).text() == "cm"
    assert d.tabla.item(2, 1).text() == "NAN"
    d.done(0)


def test_filtro_oculta_las_que_no_coinciden():
    e, _ = equipo_conectado()
    d = abrir(e)
    d.buscar.setText("rio")
    ocultas = [d.tabla.isRowHidden(i) for i in range(d.tabla.rowCount())]
    assert ocultas == [False, False, False, True, True]
    d.done(0)


def test_actualiza_en_su_lugar_sin_perder_la_seleccion():
    e, falso = equipo_conectado()
    d = abrir(e)
    d.tabla.selectRow(1)
    falso.vars[1] = ("Nivel_rio", "cm", "33.3")
    d._leer()
    assert esperar(lambda: d.tabla.item(1, 1).text() == "33.3")
    assert d._nombre_seleccionado() == "Nivel_rio"
    d.done(0)


def test_modo_seleccionar_devuelve_el_valor_y_no_toma_nan():
    e, _ = equipo_conectado()
    d = abrir(e, seleccionar=True)
    d.tabla.selectRow(2)                    # Q_rio = NAN
    assert not d.btn_usar.isEnabled()
    d.tabla.selectRow(0)
    assert d.btn_usar.isEnabled()
    d._usar()
    assert d.elegida == ("Rio_filt", pytest.approx(7.4))


def test_firmware_viejo_avisa_y_marca_el_fallo():
    e, _ = equipo_conectado(version="1.11.1")
    d = DialogoVariables(equipo=e)
    d.auto.setChecked(False)
    d.show()
    assert esperar(lambda: d.fallo_equipo)
    assert "1.12.0" in d.estado.text()
    d.done(0)


def test_la_calibracion_tiene_un_boton_leer_por_cada_campo_de_mA():
    w = AsistenteSensor()
    botones = [b for b in w.findChildren(type(w.btn_insertar)) if b.text() == "Leer del equipo"]
    assert len(botones) == 4
