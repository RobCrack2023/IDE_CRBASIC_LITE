"""Rescate por USB: hablar con el Opta por el puerto serie del cable USB-C.

Es el mismo protocolo de línea que usa `rescatar_registros.html` del repo
OptaPakBus, portado a Python. El equipo mezcla su log de depuración con las
respuestas; las respuestas son las líneas que empiezan con ``#D,``.

    TABLES                       INFO,... / TABLE,... / OK
    DUMP <tabla> <desde>         BEGIN / HDR / filas / END,<n>
    PROG BEGIN <n> <nombre>      PROG,READY,<chunk>
    PROG DATA <off> <hex>        PROG,ACK,<hasta>
    PROG END <firma>             PROG,OK,...
    ABORT                        cancela la operación en curso

Esta capa no depende de Qt ni de pyserial: recibe cualquier objeto con
``write(bytes)``, ``read(n)`` (que devuelve lo que haya o ``b""`` al vencer
su timeout) y ``close()``. Eso permite probarla con un equipo simulado.

Solo están las operaciones de datos y de programa. Cargar firmware y
restablecer de fábrica se dejaron en la página web a propósito: son las dos
que pueden dejar el equipo inutilizable y no se pueden probar sin hardware.
"""

import re
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

BAUDIOS = 115200
MAX_PROG_BYTES = 16384
CHUNK_PROG = 80

_FILA = re.compile(r"^\d{4}-\d{2}-\d{2} ")


class ErrorUSB(Exception):
    """El equipo contestó ERR, dejó de responder o no se pudo abrir el puerto."""


class Cancelado(ErrorUSB):
    pass


@dataclass
class InfoEquipo:
    estacion: str = ""
    firmware: str = ""
    epoch: int = 0
    programa: Optional[str] = None
    prog_bytes: int = 0
    prog_firma: str = ""
    almacenamiento_ok: Optional[int] = None


@dataclass
class Tabla:
    idx: int
    nombre: str
    n_campos: int
    intervalo: int
    primero: int
    ultimo: int
    cantidad: int

    @property
    def dias(self) -> float:
        return self.cantidad * self.intervalo / 86400 if self.intervalo > 0 else 0.0


@dataclass
class Volcado:
    encabezado: str = ""
    filas: "list[str]" = field(default_factory=list)
    informadas: int = -1          #: cuántas dijo el equipo en el END
    error: str = ""

    @property
    def completo(self) -> bool:
        return not self.error and self.informadas == len(self.filas)


def calcular_firma(datos: bytes) -> int:
    """Misma firma que calcSigFor() del equipo y que la que muestra LoggerNet."""
    sig = 0xAAAA
    for b in datos:
        j = sig
        sig = (sig << 1) & 0x1FF
        if sig >= 0x100:
            sig += 1
        sig = (((sig + (j >> 8) + b) & 0xFF) | (j << 8)) & 0xFFFF
    return sig


def listar_puertos() -> "list[tuple[str, str]]":
    """(dispositivo, descripción) de los puertos serie del computador."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return [(p.device, p.description or p.device) for p in list_ports.comports()]


def abrir_puerto(dispositivo: str) -> "EquipoUSB":
    """Abre el puerto real. El equipo solo habla con DTR en alto."""
    try:
        import serial
    except ImportError as e:
        raise ErrorUSB("Falta pyserial. Instalalo con:  pip install pyserial") from e
    try:
        puerto = serial.Serial(dispositivo, BAUDIOS, timeout=0.1, write_timeout=5)
        puerto.dtr = True
        puerto.rts = True
    except (serial.SerialException, OSError) as e:
        raise ErrorUSB(
            f"No se pudo abrir {dispositivo} ({e}). Cerrá el Monitor Serie del "
            "Arduino IDE u otro programa que use el USB, desenchufá y volvé a "
            "enchufar el cable."
        ) from e
    return EquipoUSB(puerto)


class EquipoUSB:
    """Conversación con el equipo sobre un puerto ya abierto."""

    def __init__(self, transporte, log: Callable[[str], None] = None,
                 cancelar: Callable[[], bool] = None):
        self.t = transporte
        self.log = log or (lambda _: None)
        self.cancelar = cancelar or (lambda: False)
        self._buf = b""
        #: Multiplica todos los timeouts; las pruebas lo bajan para no esperar.
        self.escala = 1.0
        self.info = InfoEquipo()
        self.tablas: "list[Tabla]" = []

    def cerrar(self) -> None:
        try:
            self.t.close()
        except Exception:
            pass

    # ── Línea a línea ───────────────────────────────────────────────────
    def _leer_d(self, hasta: float) -> Optional[str]:
        """Próxima línea ``#D,...`` sin el prefijo, o None si venció `hasta`."""
        while True:
            i = self._buf.find(b"\n")
            if i >= 0:
                linea = self._buf[:i].rstrip(b"\r").decode("utf-8", "replace")
                self._buf = self._buf[i + 1:]
                if linea.startswith("#D,"):
                    if not _FILA.match(linea[3:]):
                        self.log("< " + linea)
                    return linea[3:]
                if linea:
                    self.log(linea)           # log de depuración del equipo
                continue
            if time.monotonic() >= hasta:
                return None
            pendientes = getattr(self.t, "in_waiting", 0)
            nuevo = self.t.read(pendientes or 1)
            if nuevo:
                self._buf += nuevo

    def _enviar(self, comando: str) -> None:
        self.t.write((comando + "\n").encode("utf-8"))

    def pedir(self, comando: str, en_linea: Callable[[str], object],
              timeout: float) -> None:
        """Manda `comando` y entrega cada respuesta a `en_linea` hasta que
        devuelva True. El timeout cuenta desde la última línea recibida."""
        timeout *= self.escala
        self._enviar(comando)
        limite = time.monotonic() + timeout
        while True:
            if self.cancelar():
                self._cancelar_en_equipo()
                raise Cancelado("cancelado")
            linea = self._leer_d(min(limite, time.monotonic() + 0.2))
            if linea is None:
                if time.monotonic() >= limite:
                    raise ErrorUSB("timeout")
                continue
            limite = time.monotonic() + timeout
            if en_linea(linea) is True:
                return

    def _cancelar_en_equipo(self) -> None:
        try:
            self._enviar("ABORT")
        except Exception:
            pass

    # ── Tablas ──────────────────────────────────────────────────────────
    def leer_tablas(self) -> "list[Tabla]":
        """Pide INFO y TABLES. El equipo puede estar arrancando: reintenta."""
        ultimo = None
        for _ in range(3):
            tablas: "list[Tabla]" = []
            info = InfoEquipo()

            def en_linea(linea):
                p = linea.split(",")
                if p[0] == "INFO":
                    info.estacion = p[1] if len(p) > 1 else ""
                    info.firmware = p[2] if len(p) > 2 else ""
                    info.epoch = int(p[3]) if len(p) > 3 and p[3].isdigit() else 0
                    if len(p) > 4:
                        info.programa = p[4] or None
                        info.prog_bytes = int(p[5]) if len(p) > 5 and p[5].isdigit() else 0
                        info.prog_firma = p[6] if len(p) > 6 else ""
                    if len(p) > 7 and p[7].lstrip("-").isdigit():
                        info.almacenamiento_ok = int(p[7])
                elif p[0] == "TABLE":
                    tablas.append(Tabla(int(p[1]), p[2], int(p[3]), int(p[4]),
                                        int(p[5]), int(p[6]), int(p[7])))
                elif p[0] == "OK":
                    return True
                elif p[0] == "ERR":
                    raise ErrorUSB(",".join(p[1:]))
                return False

            try:
                self.pedir("TABLES", en_linea, 4.0)
            except Cancelado:
                raise
            except ErrorUSB as e:
                ultimo = e
                continue
            self.info, self.tablas = info, tablas
            return tablas
        raise ErrorUSB(
            "El equipo no responde a la consulta. Puede que el firmware sea "
            "anterior a 1.7.3 (sin rescate por USB) o que recién esté "
            f"arrancando: esperá 10 segundos y reintentá. ({ultimo})"
        )

    # ── Descarga ────────────────────────────────────────────────────────
    @staticmethod
    def desde_registro(tabla: Tabla, dias: int = 0, ultimos: int = 0) -> int:
        """Número de registro desde donde pedir; 0 es «todo»."""
        n = 0
        if dias > 0 and tabla.intervalo > 0:
            n = -(-dias * 86400 // tabla.intervalo)         # techo
        elif ultimos > 0:
            n = ultimos
        if n <= 0:
            return 0
        return max(tabla.primero, tabla.ultimo - n + 1)

    def volcar(self, tabla: Tabla, desde: int = 0, excel_es: bool = True,
               progreso: Callable[[int, int], None] = None) -> Volcado:
        """Descarga una tabla. `progreso(recibidas, total)`.

        Con `excel_es` el separador es «;» y la coma decimal; si no, «,» y
        punto. Si algo sale mal devuelve lo recibido y deja el motivo en
        `error`, igual que la página web: unas filas parciales valen más que
        nada.
        """
        v = Volcado()
        total = [1]
        sep = ";" if excel_es else ","

        def fila(partes):
            if not excel_es:
                return ",".join(partes)
            return ";".join(x.replace(".", ",") if i >= 2 else x
                            for i, x in enumerate(partes))

        def en_linea(linea):
            p = linea.split(",")
            if p[0] == "BEGIN":
                total[0] = max(1, int(p[5]) - int(p[4]) + 1)
            elif p[0] == "HDR":
                v.encabezado = sep.join(p[1:])
            elif p[0] == "END":
                v.informadas = int(p[1])
                return True
            elif p[0] == "ERR":
                v.error = ",".join(p[1:])
                return True
            elif _FILA.match(linea):
                v.filas.append(fila(p))
                if progreso and len(v.filas) % 200 == 0:
                    progreso(len(v.filas), total[0])
            return False

        try:
            self.pedir(f"DUMP {tabla.idx} {desde}", en_linea, 15.0)
        except Cancelado:
            v.error = "cancelado"
        except ErrorUSB as e:
            v.error = "el equipo dejó de responder" if str(e) == "timeout" else str(e)
        if progreso:
            progreso(len(v.filas), total[0])
        return v

    @staticmethod
    def csv(v: Volcado, excel_es: bool = True) -> str:
        """Texto del archivo: BOM para que Excel lo abra con acentos."""
        sep = "\r\n"
        return "﻿" + (v.encabezado + sep if v.encabezado else "") \
            + sep.join(v.filas) + sep

    # ── Programa ────────────────────────────────────────────────────────
    def cargar_programa(self, datos: bytes, nombre: str = "programa.CR1",
                        progreso: Callable[[int, int], None] = None) -> dict:
        """Reemplaza el programa del equipo. Devuelve el resumen del equipo.

        Si el programa nuevo cambia las columnas de una tabla, el historial
        de esa tabla se borra en el equipo: avisar antes al usuario.
        """
        if not datos:
            raise ErrorUSB("El archivo está vacío.")
        if len(datos) > MAX_PROG_BYTES:
            raise ErrorUSB(f"El programa pesa {len(datos)} bytes y el equipo "
                           f"admite hasta {MAX_PROG_BYTES}.")
        nombre = re.sub(r"[^A-Za-z0-9._-]+", "_", nombre) or "programa.CR1"
        chunk = [CHUNK_PROG]

        def listo(linea):
            p = linea.split(",")
            if p[0] == "PROG" and len(p) > 1 and p[1] == "READY":
                chunk[0] = min(CHUNK_PROG, int(p[2]) if len(p) > 2 and p[2].isdigit() else CHUNK_PROG)
                return True
            if p[0] == "ERR":
                raise ErrorUSB(",".join(p[1:]))
            return False

        try:
            self.pedir(f"PROG BEGIN {len(datos)} {nombre}", listo, 5.0)
            for off in range(0, len(datos), chunk[0]):
                parte = datos[off:off + chunk[0]]
                hasta = off + len(parte)
                self._enviar_bloque(off, parte, hasta)
                if progreso:
                    progreso(hasta, len(datos))

            res = {}

            def fin(linea):
                p = linea.split(",")
                if p[0] == "PROG" and len(p) > 1 and p[1] == "OK":
                    res.update(bytes=p[2], tablas=int(p[3]), variables=int(p[4]),
                               instrucciones=int(p[5]), problemas=int(p[6]),
                               firma=p[7] if len(p) > 7 else "")
                    return True
                if p[0] == "ERR":
                    raise ErrorUSB(",".join(p[1:]))
                return False

            self.pedir(f"PROG END {calcular_firma(datos)}", fin, 15.0)
        except ErrorUSB:
            self._cancelar_en_equipo()
            raise
        return res

    def leer_programa(self, progreso: Callable[[int, int], None] = None) -> bytes:
        """Trae el programa que corre en el equipo, byte por byte.

        Necesita firmware 1.9.2 o superior (comando PROG READ). El equipo
        manda el largo y la firma en cada trozo: si cambian a mitad de la
        lectura, o la firma final no coincide con lo recibido, se rechaza
        antes de entregar un programa corrupto o mezclado.
        """
        datos = bytearray()
        total = firma = None
        while total is None or len(datos) < total:
            trozo = self._leer_trozo(len(datos))
            off, tot, sig, bloque = trozo
            if total is None:
                total, firma = tot, sig
            elif (tot, sig) != (total, firma):
                raise ErrorUSB("El programa del equipo cambió mientras se leía. "
                               "Volvé a intentar.")
            if off != len(datos) or not bloque:
                raise ErrorUSB("El equipo contestó un trozo fuera de orden.")
            datos += bloque
            if progreso:
                progreso(len(datos), total)
        if len(datos) != total:
            raise ErrorUSB("El equipo mandó más bytes de los que declaró.")
        if calcular_firma(bytes(datos)) != firma:
            raise ErrorUSB("La firma del programa leído no coincide con la del "
                           "equipo: la lectura llegó dañada. Reintentá.")
        return bytes(datos)

    def _leer_trozo(self, off: int):
        """(offset, total, firma, bytes) de un PROG READ, con reintentos."""
        resultado = []

        def en_linea(linea):
            p = linea.split(",", 5)
            if p[0] == "PROG" and len(p) == 6 and p[1] == "DATA" and int(p[2]) == off:
                resultado.append((int(p[2]), int(p[3]), int(p[4]), bytes.fromhex(p[5])))
                return True
            if p[0] == "ERR":
                raise ErrorUSB(self._error_lectura(",".join(p[1:])))
            return False

        for _ in range(4):
            try:
                self.pedir(f"PROG READ {off}", en_linea, 3.0)
                return resultado[0]
            except Cancelado:
                raise
            except ErrorUSB as e:
                if str(e) != "timeout":
                    raise
        raise ErrorUSB("el equipo dejó de responder")

    @staticmethod
    def _error_lectura(motivo: str) -> str:
        if "uso: PROG" in motivo:
            return ("Este firmware no sabe entregar su programa por USB: hace "
                    "falta la versión 1.9.2 o superior.")
        return motivo

    def _enviar_bloque(self, off: int, parte: bytes, hasta: int) -> None:
        def ack(linea):
            p = linea.split(",")
            if p[0] == "PROG" and len(p) > 2 and p[1] == "ACK":
                return int(p[2]) >= hasta
            if p[0] == "ERR":
                raise ErrorUSB(",".join(p[1:]))
            return False

        for _ in range(4):
            try:
                self.pedir(f"PROG DATA {off} {parte.hex()}", ack, 3.0)
                return
            except Cancelado:
                raise
            except ErrorUSB as e:
                if str(e) != "timeout":
                    raise
        raise ErrorUSB("el equipo dejó de responder")
