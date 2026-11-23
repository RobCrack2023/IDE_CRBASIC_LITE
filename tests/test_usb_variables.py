"""Variables en vivo por USB (comando VARS, solo lectura), contra un equipo simulado."""

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from optabasic.usb_rescate import ErrorUSB, EquipoUSB  # noqa: E402
from tests.test_usb_rescate import EquipoFalso  # noqa: E402


class EquipoConVariables(EquipoFalso):
    def __init__(self, version="1.12.0", **kw):
        super().__init__(**kw)
        self.version = version
        self.vars = [("Rio_filt", "", "7.4"), ("Nivel_rio", "cm", "-12.5"),
                     ("Q_rio", "m3/s", "NAN"), ("Gigante", "", "OVF"),
                     ("Moviendo", "", "0")]
        self.sin_programa = False

    def _atender(self, linea):
        p = linea.split()
        if p[0] == "TABLES":
            self._d(f"INFO,Estacion1,{self.version},1760000000,,0,,1")
            self._d("OK")
        elif p[0] == "VARS":
            if self.sin_programa:
                self._d("VARS,0")
                self._d("OK")
                return
            self._d(f"VARS,{len(self.vars)}")
            for n, u, v in self.vars:
                self._d(f"VAR,{n},{u},{v}")
            self._d("OK")
        else:
            super()._atender(linea)


def conectado(**kw):
    falso = EquipoConVariables(**kw)
    e = EquipoUSB(falso)
    e.escala = 0.02
    e.leer_tablas()
    return e, falso


def test_lee_todas_las_variables_con_su_unidad():
    e, falso = conectado()
    v = e.leer_variables()
    assert [x.nombre for x in v] == ["Rio_filt", "Nivel_rio", "Q_rio", "Gigante", "Moviendo"]
    assert v[0].valor == pytest.approx(7.4) and v[0].unidad == ""
    assert v[1].valor == pytest.approx(-12.5) and v[1].unidad == "cm"
    assert "VARS" in falso.comandos


def test_nan_y_desborde_se_traducen():
    e, _ = conectado()
    v = {x.nombre: x.valor for x in e.leer_variables()}
    assert math.isnan(v["Q_rio"])
    assert v["Gigante"] == float("inf")


def test_equipo_sin_programa_devuelve_lista_vacia():
    e, falso = conectado()
    falso.sin_programa = True
    assert e.leer_variables() == []


def test_firmware_anterior_a_1_12_0_explica_que_hace_falta():
    e, falso = conectado(version="1.11.1")
    with pytest.raises(ErrorUSB, match="1.12.0"):
        e.leer_variables()
    assert "VARS" not in falso.comandos
