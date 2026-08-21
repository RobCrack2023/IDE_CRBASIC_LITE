"""Paneles inferiores: problemas, recursos, hardware y log previsto."""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from optabasic import limits as L
from optabasic.diagnostics import Severity, Source

_ICONO = {"error": "⛔", "warning": "⚠", "info": "ℹ"}
_COLOR = {"error": "#cf222e", "warning": "#9a6700", "info": "#0969da"}


class PanelProblemas(QWidget):
    """Lista de diagnósticos. Doble clic salta a la línea."""

    ir_a_linea = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._diagnosticos = []

        self.chk_errores = QCheckBox("Errores")
        self.chk_avisos = QCheckBox("Avisos")
        self.chk_notas = QCheckBox("Notas")
        for chk in (self.chk_errores, self.chk_avisos, self.chk_notas):
            chk.setChecked(True)
            chk.stateChanged.connect(self._repoblar)

        self.resumen = QLabel("Sin analizar")
        self.resumen.setStyleSheet("color: #6e7781;")

        barra = QHBoxLayout()
        barra.setContentsMargins(8, 6, 8, 4)
        barra.addWidget(self.chk_errores)
        barra.addWidget(self.chk_avisos)
        barra.addWidget(self.chk_notas)
        barra.addStretch(1)
        barra.addWidget(self.resumen)

        self.arbol = QTreeWidget()
        self.arbol.setHeaderLabels(["", "Línea", "Mensaje"])
        self.arbol.setRootIsDecorated(False)
        self.arbol.setAlternatingRowColors(True)
        self.arbol.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.arbol.setWordWrap(True)
        cab = self.arbol.header()
        cab.setSectionResizeMode(0, QHeaderView.Fixed)
        cab.setSectionResizeMode(1, QHeaderView.Fixed)
        cab.setSectionResizeMode(2, QHeaderView.Stretch)
        self.arbol.setColumnWidth(0, 34)
        self.arbol.setColumnWidth(1, 64)
        self.arbol.itemDoubleClicked.connect(self._al_doble_clic)
        self.arbol.currentItemChanged.connect(self._al_seleccionar)

        self.detalle = QLabel(
            "Elegí un problema para ver la explicación completa. "
            "Doble clic salta a la línea."
        )
        self.detalle.setWordWrap(True)
        self.detalle.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.detalle.setStyleSheet(
            "padding: 8px 12px; background: #f6f8fa; border-top: 1px solid #d8dee4;"
            " color: #24292f;"
        )
        self.detalle.setMinimumHeight(56)

        caja = QVBoxLayout(self)
        caja.setContentsMargins(0, 0, 0, 0)
        caja.setSpacing(0)
        caja.addLayout(barra)
        caja.addWidget(self.arbol, 1)
        caja.addWidget(self.detalle)

    def actualizar(self, resultado) -> None:
        self._diagnosticos = list(resultado.diagnostics)
        c = resultado.diagnostics.counts()
        self.resumen.setText(
            f"{c['error']} errores · {c['warning']} avisos · {c['info']} notas"
        )
        self._repoblar()

    def _repoblar(self) -> None:
        visibles = set()
        if self.chk_errores.isChecked():
            visibles.add("error")
        if self.chk_avisos.isChecked():
            visibles.add("warning")
        if self.chk_notas.isChecked():
            visibles.add("info")

        self.arbol.clear()
        for d in self._diagnosticos:
            sev = d.severity.value
            if sev not in visibles:
                continue
            item = QTreeWidgetItem([_ICONO[sev], str(d.line), d.message])
            item.setForeground(0, QColor(_COLOR[sev]))
            item.setTextAlignment(1, Qt.AlignRight | Qt.AlignTop)
            item.setData(0, Qt.UserRole, d.line)
            item.setData(1, Qt.UserRole, d)
            if d.source is Source.FIRMWARE:
                item.setToolTip(
                    2,
                    f"En el .HLOG del equipo aparecerá como:\n{d.hlog_line()}\n\n"
                    f"(el firmware numera sin contar las líneas en blanco: "
                    f"L{d.fw_line})",
                )
            else:
                item.setToolTip(2, f"{d.message}\n\nRegla: {d.code}")
            self.arbol.addTopLevelItem(item)

        if self.arbol.topLevelItemCount() == 0:
            vacio = QTreeWidgetItem(["", "", "Ningún problema con los filtros activos."])
            vacio.setForeground(2, QColor("#6e7781"))
            self.arbol.addTopLevelItem(vacio)

    def _al_seleccionar(self, item, _anterior):
        d = item.data(1, Qt.UserRole) if item else None
        if d is None:
            self.detalle.setText("Doble clic en un problema para saltar a su línea.")
            return
        texto = f"<b>Línea {d.line}</b> — {d.message}"
        if d.source is Source.FIRMWARE:
            texto += (f"<br><br><i>En el .HLOG del equipo: "
                      f"L{d.fw_line} ignorada ({d.fw_reason})</i>")
        else:
            texto += f"<br><br><i>Regla: {d.code}</i>"
        self.detalle.setText(texto)

    def _al_doble_clic(self, item, _columna):
        linea = item.data(0, Qt.UserRole)
        if linea:
            self.ir_a_linea.emit(int(linea))


class _Medidor(QWidget):
    """Una barra «usado / total» con su etiqueta."""

    def __init__(self, titulo: str, total: int, parent=None):
        super().__init__(parent)
        self.total = total
        self.titulo = QLabel(titulo)
        self.titulo.setMinimumWidth(150)
        self.barra = QProgressBar()
        self.barra.setMaximum(total)
        self.barra.setTextVisible(False)
        self.barra.setFixedHeight(10)
        self.valor = QLabel("0")
        self.valor.setMinimumWidth(90)
        self.valor.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        caja = QHBoxLayout(self)
        caja.setContentsMargins(10, 2, 10, 2)
        caja.addWidget(self.titulo)
        caja.addWidget(self.barra, 1)
        caja.addWidget(self.valor)

    def fijar(self, usado: int, sufijo: str = "") -> None:
        self.barra.setValue(min(usado, self.total))
        self.valor.setText(f"{usado} / {self.total}{sufijo}")
        proporcion = usado / self.total if self.total else 0
        color = "#1a7f37" if proporcion < 0.75 else "#9a6700" if proporcion <= 1 else "#cf222e"
        if usado > self.total:
            color = "#cf222e"
        self.barra.setStyleSheet(
            "QProgressBar { background: #e9ecef; border: none; border-radius: 5px; }"
            f"QProgressBar::chunk {{ background: {color}; border-radius: 5px; }}"
        )
        self.valor.setStyleSheet(f"color: {color}; font-weight: 600;")


class PanelRecursos(QWidget):
    """Cuánto queda de cada límite del firmware."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.medidores = {
            "bytes": _Medidor("Programa (bytes)", L.MAX_PROG_BYTES),
            "vars": _Medidor("Variables", L.MAX_VARS),
            "consts": _Medidor("Constantes", L.MAX_CONSTS),
            "tablas": _Medidor("Tablas de datos", L.MAX_TABLES),
            "stmts": _Medidor("Instrucciones", L.MAX_STMTS),
        }
        self.nota = QLabel(
            "Cada If, ElseIf, Else y EndIf cuenta como una instrucción. Al pasarse "
            "de un límite el equipo descarta lo que sobra sin avisar."
        )
        self.nota.setWordWrap(True)
        self.nota.setStyleSheet("color: #6e7781; padding: 8px 12px;")

        self.campos = QVBoxLayout()
        self.campos.setContentsMargins(0, 0, 0, 0)
        self.campos.setSpacing(0)

        caja = QVBoxLayout(self)
        caja.setContentsMargins(0, 8, 0, 0)
        caja.setSpacing(0)
        for m in self.medidores.values():
            caja.addWidget(m)
        caja.addLayout(self.campos)
        caja.addWidget(self.nota)
        caja.addStretch(1)

        self._medidores_campos: "list[_Medidor]" = []

    def actualizar(self, resultado) -> None:
        p = resultado.program
        self.medidores["bytes"].fijar(p.size_bytes)
        self.medidores["vars"].fijar(len(p.vars))
        self.medidores["consts"].fijar(len(p.consts))
        self.medidores["tablas"].fijar(len(p.tables))
        self.medidores["stmts"].fijar(len(p.stmts))

        for m in self._medidores_campos:
            self.campos.removeWidget(m)
            m.deleteLater()
        self._medidores_campos = []
        for t in p.tables:
            m = _Medidor(f"    campos de {t.name}", L.MAX_FIELDS)
            m.fijar(t.n_fields)
            self.campos.addWidget(m)
            self._medidores_campos.append(m)


class PanelHardware(QWidget):
    """Mapa resultante de canales analógicos y relés."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cabecera = QLabel()
        self.cabecera.setStyleSheet("padding: 8px 12px; color: #6e7781;")

        self.tabla = QTreeWidget()
        self.tabla.setHeaderLabels(["Canal", "Variable", "Tipo", "Unidad", "Escala"])
        self.tabla.setRootIsDecorated(False)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.setEditTriggers(QAbstractItemView.NoEditTriggers)
        cab = self.tabla.header()
        for columna in (0, 2, 3):
            cab.setSectionResizeMode(columna, QHeaderView.ResizeToContents)
        cab.setSectionResizeMode(1, QHeaderView.Interactive)
        cab.setSectionResizeMode(4, QHeaderView.Stretch)
        self.tabla.setColumnWidth(1, 240)

        caja = QVBoxLayout(self)
        caja.setContentsMargins(0, 0, 0, 0)
        caja.setSpacing(0)
        caja.addWidget(self.cabecera)
        caja.addWidget(self.tabla)

    def actualizar(self, resultado) -> None:
        p = resultado.program
        self.cabecera.setText(
            f"Scan cada {p.scan_seconds:g}s · "
            f"{'programa activo' if p.parsed else 'SIN DataTable: el equipo no ejecuta este programa'}"
        )
        self.tabla.clear()

        analog = p.analog_map()
        pulsos = p.pulse_map()
        for i in range(L.N_ANALOG):
            v, pu = analog[i], pulsos[i]
            ocupantes = [x for x in (v, pu) if x is not None]
            if not ocupantes:
                item = QTreeWidgetItem([f"A{i}", "—", "libre", "", ""])
                item.setForeground(1, QColor("#8c959f"))
            elif len(ocupantes) > 1:
                item = QTreeWidgetItem([
                    f"A{i}", " + ".join(x.name for x in ocupantes),
                    "COLISIÓN", "", "dos variables en el mismo canal",
                ])
                for col in range(5):
                    item.setForeground(col, QColor("#cf222e"))
                item.setFont(2, _negrita())
            else:
                x = ocupantes[0]
                escala = ""
                if x.is_pulse_count:
                    escala = f"×{x.pulse_mult:g} {x.pulse_offset:+g}"
                elif x.has_volt_instr:
                    escala = f"mV ×{x.mult:g} {x.offset:+g}"
                elif x.is_batt_v:
                    escala = f"÷{L.OPTA_BATT_FACTOR}"
                item = QTreeWidgetItem([f"A{i}", x.name, x.kind, x.units, escala])
            self.tabla.addTopLevelItem(item)

        for i, stmts in enumerate(p.relay_map()):
            if not stmts:
                item = QTreeWidgetItem([f"DO{i + 1}", "—", "libre", "", ""])
                item.setForeground(1, QColor("#8c959f"))
            else:
                # Puede haber más de un PortSet sobre el mismo relé: el
                # programa es libre de accionarlo desde varias ramas.
                fuente = ", ".join(st.expr_text for st in stmts)
                lineas = ", ".join(f"L{st.line}" for st in stmts)
                item = QTreeWidgetItem([f"DO{i + 1}", fuente, "Relé", "",
                                        f"PortSet en {lineas}: cierra si > 0.5"])
            self.tabla.addTopLevelItem(item)

        sin_canal = [v for v in p.vars if not v.reads_hardware]
        if sin_canal:
            item = QTreeWidgetItem([
                "—", ", ".join(v.name for v in sin_canal), "Calculadas", "",
                "no ocupan canal",
            ])
            item.setForeground(0, QColor("#8c959f"))
            self.tabla.addTopLevelItem(item)


class PanelHlog(QPlainTextEdit):
    """Previsión de lo que el equipo escribirá en su .HLOG."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        fuente = QFont("Consolas", 10)
        fuente.setStyleHint(QFont.Monospace)
        self.setFont(fuente)

    def actualizar(self, resultado) -> None:
        lineas = [d.hlog_line() for d in resultado.diagnostics
                  if d.source is Source.FIRMWARE]
        if lineas:
            cabecera = (
                "Estas son las líneas que el equipo va a registrar en su .HLOG al\n"
                "cargar el programa. El número L<n> es el del firmware, que no\n"
                "cuenta las líneas en blanco — por eso no coincide con el editor.\n"
                + "─" * 72 + "\n"
            )
            self.setPlainText(cabecera + "\n".join(lineas))
        else:
            self.setPlainText(
                "El equipo no va a descartar ninguna línea de este programa.\n\n"
                "Los avisos del panel de Problemas que no aparecen acá son cosas que\n"
                "el firmware acepta en silencio: no quedan registradas en el .HLOG."
            )


def _negrita() -> QFont:
    f = QFont()
    f.setBold(True)
    return f
