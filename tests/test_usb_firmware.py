"""Cargar firmware y restablecer de fábrica por USB, contra un equipo simulado.

El simulador valida igual que usb_cmd_fw() y usb_cmd_format() del firmware:
tamaño en FW BEGIN, offsets en orden, tabla de vectores en el primer trozo,
CRC releído en FW END, APPLY solo si está verificado y FORMAT solo con el
nombre de la estación.
"""

import base64
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from optabasic.usb_rescate import (  # noqa: E402
    Cancelado,
    ErrorUSB,
    EquipoUSB,
    analizar_firmware,
    crc32,
    version_tupla,
)
from tests.test_usb_rescate import EquipoFalso  # noqa: E402


def imagen(version="1.11.1", largo=70000, sp=0x20020000, rv=0x08040001, marca=True):
    """Un .bin con la forma de un firmware del Opta."""
    cuerpo = bytearray((i * 7 + 3) & 0xFF for i in range(largo))
    cuerpo[0:4] = sp.to_bytes(4, "little")
    cuerpo[4:8] = rv.to_bytes(4, "little")
    if marca:
        m = f"OPTAPAKBUS-FW:{version};".encode()
        cuerpo[1000:1000 + len(m)] = m
    return bytes(cuerpo)


class EquipoConFirmware(EquipoFalso):
    ESTACION = "Estacion1"

    def __init__(self, version="1.11.0", **kw):
        super().__init__(**kw)
        self.version = version
        self.fw = None            # bytearray mientras hay una carga en curso
        self.fw_total = 0
        self.fw_crc = 0
        self.fw_verificado = False
        self.reiniciado = False
        self.formateado = None
        self.perder_primer_ack_fw = False
        self.format_parcial = False

    def _atender(self, linea):
        p = linea.split()
        if p[0] == "TABLES":
            self._d(f"INFO,{self.ESTACION},{self.version},1760000000,,0,,1")
            self._d("OK")
        elif p[0] == "FW":
            self._fw(p)
        elif p[0] == "FORMAT":
            if len(p) < 2 or p[1] != self.ESTACION:
                self._d(f"ERR,el nombre de estacion no coincide (equipo: {self.ESTACION})")
            else:
                self.formateado = p[1]
                self._d("FORMAT,PARCIAL,1,0" if self.format_parcial else "FORMAT,OK,1,1")
        elif p[0] == "ABORT":
            self.fw = None
            self.fw_verificado = False
            self._d("OK")
        else:
            super()._atender(linea)

    def _fw(self, p):
        sub = p[1]
        if sub == "BEGIN":
            total, crc = int(p[2]), int(p[3])
            if total < 65536 or total > 1966080:
                self._d(f"ERR,tamano de firmware invalido ({total} bytes)")
                return
            self.fw, self.fw_total, self.fw_crc = bytearray(), total, crc
            self.fw_verificado = False
            self._d("FW,READY,144")
        elif sub == "DATA":
            if self.fw is None:
                self._d("ERR,sin FW BEGIN")
                return
            off = int(p[2])
            if off < len(self.fw):                  # reenvío
                self._d(f"FW,ACK,{len(self.fw)}")
                return
            if off != len(self.fw):
                self._d(f"ERR,offset esperado {len(self.fw)}")
                return
            if self.perder_primer_ack_fw:
                self.perder_primer_ack_fw = False   # lo recibe pero no avisa
                self.fw += base64.b64decode(p[3])
                return
            datos = base64.b64decode(p[3])
            if off == 0:
                sp = int.from_bytes(datos[0:4], "little")
                rv = int.from_bytes(datos[4:8], "little")
                if not (0x20000000 <= sp < 0x30000000 and rv & 1 and 0x08000000 <= rv < 0x08200000):
                    self.fw = None
                    self._d("ERR,el archivo no parece un firmware del Opta")
                    return
            self.fw += datos
            self._d(f"FW,ACK,{len(self.fw)}")
        elif sub == "END":
            if self.fw is None:
                self._d("ERR,sin FW BEGIN")
            elif len(self.fw) != self.fw_total:
                self._d(f"ERR,incompleto {len(self.fw)} de {self.fw_total} bytes")
            elif crc32(bytes(self.fw)) != self.fw_crc:
                self.fw = None
                self._d("ERR,verificacion fallida")
            else:
                self.fw_verificado = True
                self._d(f"FW,VERIFIED,{self.fw_crc}")
        elif sub == "APPLY":
            if self.fw is None or not self.fw_verificado:
                self._d("ERR,firmware sin verificar")
            else:
                self.reiniciado = True
                self._d("FW,REBOOTING")


def conectado(**kw):
    falso = EquipoConFirmware(**kw)
    e = EquipoUSB(falso)
    e.escala = 0.02
    e.leer_tablas()
    return e, falso


# ── Revisar el archivo ──────────────────────────────────────────────────
def test_analiza_un_firmware_valido():
    datos = imagen("1.11.1")
    info = analizar_firmware(datos, "OptaPakBus.ino.bin")
    assert info.version == "1.11.1"
    assert info.tamano == len(datos)
    assert info.crc == crc32(datos)


@pytest.mark.parametrize("datos,nombre,texto", [
    (imagen(), "OptaPakBus.ino.with_bootloader.bin", "with_bootloader"),
    (imagen(largo=1000), "x.bin", "tamaño"),
    (imagen(sp=0x1000), "x.bin", "no parece un firmware"),
    (imagen(rv=0x08040000), "x.bin", "no parece un firmware"),       # Reset handler par
    (imagen(marca=False), "x.bin", "no es un firmware de OptaPakBus"),
], ids=["with_bootloader", "muy_chico", "sp_fuera_de_ram", "reset_par", "sin_marca"])
def test_rechaza_lo_que_no_es_un_firmware_de_optapakbus(datos, nombre, texto):
    with pytest.raises(ErrorUSB, match=texto):
        analizar_firmware(datos, nombre)


def test_comparar_versiones():
    assert version_tupla("1.11.1") > version_tupla("1.9.9")
    assert version_tupla("1.7.5") <= version_tupla("1.7.5")
    assert version_tupla("") == ()


# ── Cargar firmware ─────────────────────────────────────────────────────
def test_carga_el_firmware_entero_y_lo_deja_verificado_sin_instalar():
    e, falso = conectado()
    datos = imagen()
    avance = []
    e.cargar_firmware(datos, lambda hecho, total: avance.append((hecho, total)))
    assert bytes(falso.fw) == datos
    assert falso.fw_verificado
    assert avance[-1] == (len(datos), len(datos))
    assert not any(c.startswith("FW APPLY") for c in falso.comandos), \
        "cargar no instala: eso lo decide quien opera, después"
    assert not falso.reiniciado


def test_instalar_despues_de_cargar_reinicia_el_equipo():
    e, falso = conectado()
    e.cargar_firmware(imagen())
    e.instalar_firmware()
    assert falso.reiniciado


def test_instalar_sin_haber_cargado_lo_rechaza_el_equipo():
    e, falso = conectado()
    with pytest.raises(ErrorUSB, match="sin verificar"):
        e.instalar_firmware()
    assert not falso.reiniciado


def test_un_ack_perdido_se_reenvia_y_el_firmware_llega_identico():
    e, falso = conectado()
    falso.perder_primer_ack_fw = True
    datos = imagen()
    e.cargar_firmware(datos)
    assert bytes(falso.fw) == datos


def test_un_firmware_invalido_ni_se_manda():
    e, falso = conectado()
    with pytest.raises(ErrorUSB, match="no es un firmware de OptaPakBus"):
        e.cargar_firmware(imagen(marca=False))
    assert not any(c.startswith("FW") for c in falso.comandos)


def test_firmware_del_equipo_anterior_a_1_7_5_explica_que_hace_falta():
    e, falso = conectado(version="1.7.0")
    with pytest.raises(ErrorUSB, match="1.7.5"):
        e.cargar_firmware(imagen())
    assert not any(c.startswith("FW") for c in falso.comandos)


def test_si_falla_a_mitad_manda_abort_y_el_equipo_queda_como_estaba(monkeypatch):
    e, falso = conectado()
    original = falso._fw

    def falla_al_tercer_trozo(p):
        if p[1] == "DATA" and int(p[2]) >= 144 * 2:
            falso._d("ERR,escritura en flash (0 de 144 bytes)")
            return
        original(p)

    monkeypatch.setattr(falso, "_fw", falla_al_tercer_trozo)
    with pytest.raises(ErrorUSB, match="escritura en flash"):
        e.cargar_firmware(imagen())
    assert "ABORT" in falso.comandos
    assert not falso.reiniciado


def test_cancelar_a_mitad_manda_abort():
    e, falso = conectado()
    n = []

    def cancelar():
        n.append(1)
        return len(n) > 30          # unos cuantos trozos y se arrepiente

    e.cancelar = cancelar
    with pytest.raises(Cancelado):
        e.cargar_firmware(imagen())
    assert "ABORT" in falso.comandos
    assert not falso.reiniciado


# ── Restablecer de fábrica ──────────────────────────────────────────────
def test_restablecer_manda_el_nombre_de_la_estacion_sin_pedirlo():
    e, falso = conectado()
    res = e.restablecer()
    assert falso.formateado == "Estacion1"
    assert "FORMAT Estacion1" in falso.comandos
    assert res == {"estado": "OK", "datos": True, "ota": True}


def test_restablecer_parcial_se_informa():
    e, falso = conectado()
    falso.format_parcial = True
    res = e.restablecer()
    assert res["estado"] == "PARCIAL"
    assert res["datos"] is True and res["ota"] is False


def test_restablecer_con_firmware_anterior_a_1_7_6():
    e, falso = conectado(version="1.7.5")
    with pytest.raises(ErrorUSB, match="1.7.6"):
        e.restablecer()
    assert not any(c.startswith("FORMAT") for c in falso.comandos)


def test_restablecer_sin_conocer_el_nombre_no_manda_nada():
    falso = EquipoFalso()
    e = EquipoUSB(falso)
    e.escala = 0.02          # sin leer_tablas: el nombre de la estación es desconocido
    with pytest.raises(ErrorUSB, match="nombre de la estación"):
        e.restablecer()
    assert not any(c.startswith("FORMAT") for c in falso.comandos)


def test_nombre_de_estacion_con_espacios_no_se_puede_confirmar():
    e, falso = conectado()
    e.info.estacion = "Banco Rio"
    with pytest.raises(ErrorUSB, match="espacios"):
        e.restablecer()
    assert not any(c.startswith("FORMAT") for c in falso.comandos)


def test_el_error_del_equipo_al_restablecer_se_propaga(monkeypatch):
    e, falso = conectado()
    e.info.estacion = "OtroNombre"          # no coincide con el del equipo
    with pytest.raises(ErrorUSB, match="no coincide"):
        e.restablecer()
