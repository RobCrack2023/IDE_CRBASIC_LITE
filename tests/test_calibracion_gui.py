"""El asistente de sensores calibra con 2 puntos y actualiza las Const del programa."""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

pytest.importorskip("PyQt5")
from PyQt5.QtWidgets import QApplication  # noqa: E402

from gui.sensor_wizard import AsistenteSensor  # noqa: E402

app = QApplication.instance() or QApplication([])


def test_la_pestania_de_calibracion_calcula_y_emite_las_constantes():
    d = AsistenteSensor()
    d.tabs.setCurrentIndex(3)
    d.k_d1.setValue(100.0)
    d.k_m1.setValue(6.93)
    d.k_d2.setValue(300.0)
    d.k_m2.setValue(15.18)
    d._recalcular()
    assert d.btn_insertar.isEnabled()
    assert "Aplicar" in d.btn_insertar.text()
    recibido = []
    d.aplicar.connect(recibido.append)
    d._insertar()
    assert set(recibido[0]) == {"Rio_Mult", "Rio_Off"}
    assert recibido[0]["Rio_Mult"] == pytest.approx(24.24, abs=0.01)


def test_con_error_no_se_puede_aplicar():
    d = AsistenteSensor()
    d.tabs.setCurrentIndex(3)
    d.k_m1.setValue(7.0)
    d.k_m2.setValue(7.0)
    d._recalcular()
    assert not d.btn_insertar.isEnabled()


def test_las_otras_pestanias_siguen_insertando_codigo():
    d = AsistenteSensor()
    d.tabs.setCurrentIndex(0)
    d._recalcular()
    assert d.btn_insertar.text() == "Insertar en el programa"
