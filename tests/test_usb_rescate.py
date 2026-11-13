"""Pruebas del rescate por USB contra un equipo simulado.

El simulador habla el mismo protocolo de línea que el firmware (ver
usb_rescate.py) e intercala log de depuración con las respuestas, que es lo
que hace el equipo de verdad por el mismo puerto.
"""

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from optabasic.usb_rescate import (  # noqa: E402
    ErrorUSB,
    EquipoUSB,
    Tabla,
    calcular_firma,
)


class EquipoFalso:
    """Transporte en memoria: write() recibe comandos, read() entrega lo
    que el equipo contestaría."""

    def __init__(self, filas=10, silencioso=False, rechaza_prog=False):
        self.salida = bytearray()
        self.comandos = []
        self.filas = filas
        self.silencioso = silencioso
        self.rechaza_prog = rechaza_prog
        self.prog = bytearray()
        self.perder_primer_ack = False
        self.guardado = b""             # lo que el equipo tiene instalado
        self.firmware_viejo = False     # sin PROG READ, como antes de 1.9.2
        self.corromper = False

    @property
    def in_waiting(self):
        return len(self.salida)

    def close(self):
        pass

    def read(self, n):
        if not self.salida:
            time.sleep(0.001)
            return b""
        out = bytes(self.salida[:n])
        del self.salida[:n]
        return out

    def _d(self, texto):
        # Siempre con un poco de log de depuración alrededor.
        self.salida += b"[12:00:01] sensor leido\r\n"
        self.salida += f"#D,{texto}\r\n".encode()

    def write(self, datos):
        for linea in datos.decode().splitlines():
            self.comandos.append(linea)
            self._atender(linea)

    def _atender(self, linea):
        if self.silencioso:
            return
        p = linea.split()
        if p[0] == "TABLES":
            self._d("INFO,Estacion1,1.9.1,1760000000,CPU:prog.CR1,320,1234,1")
            self._d("TABLE,0,Datos,3,60,1,10,10")
            self._d("OK")
        elif p[0] == "DUMP":
            idx, desde = int(p[1]), int(p[2])
            if idx != 0:
                self._d("ERR,tabla inexistente")
                return
            ini = desde or 1
            self._d(f"BEGIN,0,Datos,3,{ini},{self.filas}")
            self._d("HDR,TIMESTAMP,RECORD,Nivel,Temp")
            for r in range(ini, self.filas + 1):
                self._d(f"2026-11-13 12:{r:02d}:00,{r},{r}.5,20.25")
            self._d(f"END,{self.filas - ini + 1}")
        elif p[0] == "PROG" and p[1] == "READ":
            if self.firmware_viejo:
                self._d("ERR,uso: PROG BEGIN|DATA|END")
                return
            if not self.guardado:
                self._d("ERR,sin programa guardado")
                return
            off = int(p[2])
            if off >= len(self.guardado):
                self._d("ERR,offset fuera de rango")
                return
            bloque = bytearray(self.guardado[off:off + 64])
            if self.corromper and off == 64:
                bloque[0] ^= 0xFF
            self._d(f"PROG,DATA,{off},{len(self.guardado)},"
                    f"{calcular_firma(self.guardado)},{bloque.hex()}")
        elif p[0] == "PROG" and p[1] == "BEGIN":
            if self.rechaza_prog:
                self._d("ERR,programa demasiado largo")
                return
            self.prog = bytearray()
            self._d("PROG,READY,80")
        elif p[0] == "PROG" and p[1] == "DATA":
            off, hexa = int(p[2]), p[3]
            if self.perder_primer_ack:
                self.perder_primer_ack = False
                return                      # el equipo no contesta
            assert off == len(self.prog), "bloque fuera de orden"
            self.prog += bytes.fromhex(hexa)
            self._d(f"PROG,ACK,{len(self.prog)}")
        elif p[0] == "PROG" and p[1] == "END":
            if int(p[2]) != calcular_firma(bytes(self.prog)):
                self._d("ERR,firma no coincide")
            else:
                self._d(f"PROG,OK,{len(self.prog)},1,2,5,0,{p[2]}")
        elif p[0] == "ABORT":
            self._d("ERR,cancelado")


def equipo(**kw):
    falso = EquipoFalso(**kw)
    e = EquipoUSB(falso)
    e.escala = 0.02
    return e, falso


def test_la_firma_distingue_contenidos():
    assert calcular_firma(b"") == 0xAAAA
    assert calcular_firma(b"abc") != calcular_firma(b"abd")


def test_lee_info_y_tablas_ignorando_el_log_de_depuracion():
    e, _ = equipo()
    tablas = e.leer_tablas()
    assert e.info.estacion == "Estacion1"
    assert e.info.firmware == "1.9.1"
    assert e.info.programa == "CPU:prog.CR1"
    assert e.info.almacenamiento_ok == 1
    assert len(tablas) == 1 and tablas[0].nombre == "Datos"
    assert tablas[0].cantidad == 10


def test_equipo_mudo_da_error_claro():
    e, _ = equipo(silencioso=True)
    with pytest.raises(ErrorUSB, match="no responde"):
        e.leer_tablas()


def test_descarga_completa_en_formato_excel_es():
    e, _ = equipo()
    t = e.leer_tablas()[0]
    v = e.volcar(t, 0, excel_es=True)
    assert v.completo and len(v.filas) == 10
    assert v.encabezado == "TIMESTAMP;RECORD;Nivel;Temp"
    assert v.filas[0] == "2026-11-13 12:01:00;1;1,5;20,25"
    assert e.csv(v).startswith("﻿TIMESTAMP;RECORD")


def test_descarga_estandar_deja_el_punto_decimal():
    e, _ = equipo()
    v = e.volcar(e.leer_tablas()[0], 0, excel_es=False)
    assert v.filas[0] == "2026-11-13 12:01:00,1,1.5,20.25"


def test_descarga_desde_un_registro():
    e, falso = equipo()
    t = e.leer_tablas()[0]
    v = e.volcar(t, 8)
    assert len(v.filas) == 3 and v.completo
    assert "DUMP 0 8" in falso.comandos


def test_tabla_inexistente_es_error_del_equipo():
    e, _ = equipo()
    v = e.volcar(Tabla(9, "X", 1, 60, 1, 1, 1))
    assert "inexistente" in v.error and not v.completo


def test_fila_perdida_se_detecta():
    e, _ = equipo()
    v = e.volcar(e.leer_tablas()[0])
    v.filas.pop()
    assert not v.completo


def test_desde_registro_por_dias_y_por_cantidad():
    t = Tabla(0, "D", 2, 3600, 1, 1000, 1000)      # un registro por hora
    assert EquipoUSB.desde_registro(t) == 0
    assert EquipoUSB.desde_registro(t, dias=1) == 1000 - 24 + 1
    assert EquipoUSB.desde_registro(t, ultimos=50) == 951
    assert EquipoUSB.desde_registro(t, ultimos=5000) == 1      # no baja del primero


def test_carga_de_programa_llega_entero_y_con_firma_valida():
    e, falso = equipo()
    datos = b"Public Nivel\r\n" * 40                # 560 bytes: varios bloques
    avances = []
    res = e.cargar_programa(datos, "mi prog.CR1", lambda a, b: avances.append((a, b)))
    assert bytes(falso.prog) == datos
    assert res["tablas"] == 1 and res["problemas"] == 0
    assert "PROG BEGIN 560 mi_prog.CR1" in falso.comandos
    assert avances[-1] == (560, 560)


def test_carga_reintenta_un_bloque_sin_respuesta():
    e, falso = equipo()
    falso.perder_primer_ack = True
    datos = b"x" * 200
    e.cargar_programa(datos)
    assert bytes(falso.prog) == datos


def test_carga_rechazada_por_el_equipo_aborta():
    e, falso = equipo(rechaza_prog=True)
    with pytest.raises(ErrorUSB, match="demasiado largo"):
        e.cargar_programa(b"x" * 100)
    assert "ABORT" in falso.comandos


def test_programa_vacio_o_enorme_ni_se_manda():
    e, falso = equipo()
    with pytest.raises(ErrorUSB):
        e.cargar_programa(b"")
    with pytest.raises(ErrorUSB, match="16384"):
        e.cargar_programa(b"x" * 20000)
    assert falso.comandos == []


def test_cancelar_manda_abort():
    falso = EquipoFalso(filas=10)
    e = EquipoUSB(falso, cancelar=lambda: True)
    e.escala = 0.02
    v = e.volcar(Tabla(0, "Datos", 3, 60, 1, 10, 10))
    assert v.error == "cancelado"
    assert "ABORT" in falso.comandos


# ── Leer el programa del equipo ──────────────────────────────────────────
PROGRAMA = (b"Public Nivel\r\nDataTable(T,True,100)\r\n  Sample(1,Nivel,FP2)\r\n"
            b"EndTable\r\n") * 6              # 6 trozos de 64 bytes o mas


def test_lee_el_programa_del_equipo_identico_byte_a_byte():
    e, falso = equipo()
    falso.guardado = PROGRAMA
    avances = []
    assert e.leer_programa(lambda a, b: avances.append((a, b))) == PROGRAMA
    assert avances[-1] == (len(PROGRAMA), len(PROGRAMA))
    assert len(avances) > 2                       # vino en varios trozos


def test_lectura_reintenta_un_trozo_sin_respuesta():
    e, falso = equipo()
    falso.guardado = PROGRAMA
    original = falso._atender
    perdidos = []

    def atender(linea):
        if linea == "PROG READ 64" and not perdidos:
            perdidos.append(linea)                # el primero no se contesta
            return
        original(linea)

    falso._atender = atender
    assert e.leer_programa() == PROGRAMA


def test_lectura_sin_programa_guardado():
    e, _ = equipo()
    with pytest.raises(ErrorUSB, match="sin programa"):
        e.leer_programa()


def test_lectura_con_firmware_viejo_explica_que_version_hace_falta():
    e, falso = equipo()
    falso.guardado = PROGRAMA
    falso.firmware_viejo = True
    with pytest.raises(ErrorUSB, match="1.9.2"):
        e.leer_programa()


def test_lectura_danada_se_rechaza_por_la_firma():
    e, falso = equipo()
    falso.guardado = PROGRAMA
    falso.corromper = True
    with pytest.raises(ErrorUSB, match="firma"):
        e.leer_programa()


def test_cargar_y_leer_de_vuelta_es_identico():
    e, falso = equipo()
    datos = PROGRAMA[:300]
    e.cargar_programa(datos, "p.CR1")
    falso.guardado = bytes(falso.prog)            # lo que el equipo guardo
    assert e.leer_programa() == datos
