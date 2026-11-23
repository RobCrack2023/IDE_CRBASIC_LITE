"""Variables en vivo por USB: ver lo que el equipo tiene ahora, sin servidor.

Sirve para calibrar o revisar una estación cuando no se puede abrir el
dashboard (sin red, sin módem, o en terreno con el cable USB-C). Es solo
lectura: no escribe nada en el equipo.

Se puede abrir de dos formas:

- con un equipo ya conectado (desde el Rescate por USB), y entonces usa esa
  conexión;
- por su cuenta, y entonces trae su propio selector de puerto.

En modo «seleccionar» deja elegir una variable y devuelve su valor, que es lo
que usa la calibración para llenar los mA sin tipearlos.
"""

import math

from PyQt5.QtCore import Qt, QTimer, pyqtSlot
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from optabasic import usb_rescate as usb
from .usb_dialog import _Tarea, _texto_error

INTERVALO_MS = 1000


def formatear(valor: float) -> str:
    """Hasta 4 decimales y sin ceros finales, como lo muestra el servidor."""
    if math.isnan(valor):
        return "NAN"
    if math.isinf(valor):
        return "∞" if valor > 0 else "-∞"
    texto = f"{valor:.4f}".rstrip("0").rstrip(".")
    return texto if texto not in ("", "-") else "0"


class DialogoVariables(QDialog):
    def __init__(self, equipo=None, seleccionar=False, filtro="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Variables en vivo (USB)")
        self.setMinimumSize(560, 520)
        self.equipo = equipo
        self._propio = equipo is None          # abrió el puerto él mismo
        self.conservar = False                 # no cerrar el puerto al salir
        self._seleccionar = seleccionar
        self._tarea = None
        self._variables = []
        self._filas = {}                       # nombre -> fila de la tabla
        self.elegida = None                    # (nombre, valor) en modo seleccionar
        self.fallo_equipo = False              # la lectura falló: el cable ya no responde
        self._log_anterior = equipo.log if equipo is not None else None

        # ── Conexión (solo si no vino un equipo ya conectado) ───────────
        self.puertos = QComboBox()
        self.btn_actualizar = QPushButton("Actualizar")
        self.btn_actualizar.clicked.connect(self._llenar_puertos)
        self.btn_conectar = QPushButton("Conectar")
        self.btn_conectar.clicked.connect(self._conectar_o_desconectar)
        fila_con = QHBoxLayout()
        fila_con.addWidget(self.puertos, 1)
        fila_con.addWidget(self.btn_actualizar)
        fila_con.addWidget(self.btn_conectar)
        self._widgets_con = (self.puertos, self.btn_actualizar, self.btn_conectar)

        self.estado = QLabel("")
        self.estado.setWordWrap(True)

        self.buscar = QLineEdit(filtro)
        self.buscar.setPlaceholderText("Filtrar por nombre (ej: Rio, CM_, filt)")
        self.buscar.textChanged.connect(self._filtrar)
        self.auto = QCheckBox("Actualizar cada segundo")
        self.auto.setChecked(True)
        self.auto.stateChanged.connect(self._al_cambiar_auto)
        self.btn_leer = QPushButton("Leer ahora")
        self.btn_leer.clicked.connect(self._leer)
        fila_filtro = QHBoxLayout()
        fila_filtro.addWidget(self.buscar, 1)
        fila_filtro.addWidget(self.auto)
        fila_filtro.addWidget(self.btn_leer)

        self.tabla = QTableWidget(0, 3)
        self.tabla.setHorizontalHeaderLabels(["Variable", "Valor", "Unidad"])
        self.tabla.verticalHeader().hide()
        self.tabla.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabla.setSelectionMode(QAbstractItemView.SingleSelection)
        enc = self.tabla.horizontalHeader()
        enc.setSectionResizeMode(0, QHeaderView.Stretch)
        enc.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        enc.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tabla.itemSelectionChanged.connect(self._habilitar)
        self.tabla.itemDoubleClicked.connect(lambda *_: self._usar())

        self.btn_usar = QPushButton("Usar el valor seleccionado")
        self.btn_usar.clicked.connect(self._usar)
        self.btn_cerrar = QPushButton("Cerrar")
        self.btn_cerrar.clicked.connect(self.accept)
        fila_pie = QHBoxLayout()
        fila_pie.addStretch()
        if seleccionar:
            fila_pie.addWidget(self.btn_usar)
        fila_pie.addWidget(self.btn_cerrar)

        caja = QVBoxLayout(self)
        if self._propio:
            caja.addLayout(fila_con)
        caja.addWidget(self.estado)
        caja.addLayout(fila_filtro)
        caja.addWidget(self.tabla, 1)
        caja.addLayout(fila_pie)

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._leer)

        if self._propio:
            self._llenar_puertos()
            self.estado.setText("Conecta el cable USB-C, elige el puerto y presiona «Conectar».")
        else:
            self.estado.setText("Leyendo del equipo conectado…")
            QTimer.singleShot(0, self._leer)
        self._habilitar()

    # ── Conexión propia ─────────────────────────────────────────────────
    def _llenar_puertos(self):
        self.puertos.clear()
        for dev, desc in usb.listar_puertos():
            self.puertos.addItem(desc, dev)
        if self.puertos.count() == 0:
            self.estado.setText("No se ve ningún puerto USB. Conecta el cable y "
                                "presiona «Actualizar».")

    def _conectar_o_desconectar(self):
        if self.equipo is not None:
            self._soltar()
            self.estado.setText("Desconectado.")
            self._habilitar()
            return
        dev = self.puertos.currentData()
        if not dev:
            self.estado.setText("Elige un puerto de la lista.")
            return
        try:
            self.equipo = usb.abrir_puerto(dev)
        except usb.ErrorUSB as e:
            self.estado.setText(str(e))
            return
        self.estado.setText("Puerto abierto. Esperando respuesta del equipo…")
        self._habilitar()
        self._correr(lambda t: self.equipo.leer_tablas(), self._conectado, self._fallo_conexion)

    def _conectado(self, _tablas):
        info = self.equipo.info
        self.estado.setText(f"Conectado a «{info.estacion}» (firmware {info.firmware}).")
        self._habilitar()
        self._leer()

    def _fallo_conexion(self, mensaje):
        self._soltar()
        self.estado.setText("No se pudo conectar con el equipo: " + _texto_error(mensaje))
        self._habilitar()

    def _soltar(self):
        self.timer.stop()
        if self._tarea is not None and self._tarea.isRunning():
            self._tarea.cancelada = True
            self._tarea.wait(3000)
        if self.equipo is not None and self._propio and not self.conservar:
            self.equipo.cerrar()
        self.equipo = None

    # ── Lectura ─────────────────────────────────────────────────────────
    def _correr(self, funcion, al_terminar, al_fallar):
        tarea = _Tarea(funcion, self)
        tarea.al_terminar = al_terminar
        tarea.al_fallar = al_fallar
        self._tarea = tarea
        self.equipo.log = lambda _: None          # el log del equipo no se muestra aquí
        self.equipo.cancelar = lambda: tarea.cancelada
        tarea.terminada.connect(self._tarea_terminada)
        tarea.fallo.connect(self._tarea_fallo)
        tarea.start()

    @pyqtSlot(object)
    def _tarea_terminada(self, resultado):
        tarea = self.sender()
        tarea.wait()
        if tarea is self._tarea:
            tarea.al_terminar(resultado)

    @pyqtSlot(str)
    def _tarea_fallo(self, mensaje):
        tarea = self.sender()
        tarea.wait()
        if tarea is self._tarea and tarea.al_fallar:
            tarea.al_fallar(mensaje)

    def _leer(self):
        if self.equipo is None or (self._tarea is not None and self._tarea.isRunning()):
            return
        self._correr(lambda t: self.equipo.leer_variables(),
                     self._variables_leidas, self._fallo_lectura)

    def _fallo_lectura(self, mensaje):
        self.fallo_equipo = True
        self.auto.setChecked(False)
        self.estado.setText(_texto_error(mensaje))

    def _variables_leidas(self, variables):
        self._variables = variables
        nombres = [v.nombre for v in variables]
        if nombres != list(self._filas):
            self._reconstruir(variables)
        else:
            for v in variables:
                self.tabla.item(self._filas[v.nombre], 1).setText(formatear(v.valor))
        info = self.equipo.info
        if not variables:
            self.estado.setText("El equipo no tiene un programa con variables cargado.")
        else:
            self.estado.setText(f"«{info.estacion}» (firmware {info.firmware}): "
                                f"{len(variables)} variables.")
        if self.auto.isChecked():
            self.timer.start(INTERVALO_MS)
        self._habilitar()

    def _reconstruir(self, variables):
        elegida = self._nombre_seleccionado()
        self.tabla.setRowCount(len(variables))
        self._filas = {}
        for i, v in enumerate(variables):
            self._filas[v.nombre] = i
            for col, texto in enumerate((v.nombre, formatear(v.valor), v.unidad)):
                item = QTableWidgetItem(texto)
                if col == 1:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tabla.setItem(i, col, item)
        self._filtrar()
        if elegida in self._filas:
            self.tabla.selectRow(self._filas[elegida])

    def _filtrar(self, *_):
        texto = self.buscar.text().strip().lower()
        for nombre, fila in self._filas.items():
            self.tabla.setRowHidden(fila, bool(texto) and texto not in nombre.lower())

    def _al_cambiar_auto(self, estado):
        if estado:
            self._leer()
        else:
            self.timer.stop()

    # ── Selección ───────────────────────────────────────────────────────
    def _nombre_seleccionado(self):
        filas = self.tabla.selectionModel().selectedRows() if self.tabla.selectionModel() else []
        if not filas:
            return None
        item = self.tabla.item(filas[0].row(), 0)
        return item.text() if item else None

    def _valor_de(self, nombre):
        for v in self._variables:
            if v.nombre == nombre:
                return v.valor
        return None

    def _habilitar(self):
        conectado = self.equipo is not None
        if self._propio:
            self.puertos.setEnabled(not conectado)
            self.btn_actualizar.setEnabled(not conectado)
            self.btn_conectar.setText("Desconectar" if conectado else "Conectar")
        self.btn_leer.setEnabled(conectado)
        nombre = self._nombre_seleccionado()
        valor = self._valor_de(nombre) if nombre else None
        self.btn_usar.setEnabled(valor is not None and not math.isnan(valor)
                                 and not math.isinf(valor))

    def _usar(self):
        nombre = self._nombre_seleccionado()
        valor = self._valor_de(nombre) if nombre else None
        if not self._seleccionar or valor is None or math.isnan(valor) or math.isinf(valor):
            return
        self.elegida = (nombre, valor)
        self.accept()

    # ── Cierre ──────────────────────────────────────────────────────────
    def done(self, resultado):
        self.timer.stop()
        if self._tarea is not None and self._tarea.isRunning():
            self._tarea.cancelada = True
            self._tarea.wait(3000)
        if self.equipo is not None:
            if self._propio:
                if not self.conservar:
                    self.equipo.cerrar()
            else:
                self.equipo.log = self._log_anterior or (lambda _: None)
        super().done(resultado)
