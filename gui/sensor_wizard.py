"""Asistente de sensores: calcula la escala y escribe el código.

La cuenta de Mult y Offset es donde más se equivoca quien arma la estación,
y el error no se nota: el equipo reporta números plausibles pero mal. Acá
se cargan los datos de la hoja del sensor y la resistencia que está puesta
en el gabinete, y el asistente saca los números, revisa que la instalación
sea eléctricamente viable y deja el código listo para insertar.
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from optabasic.limits import N_ANALOG
from optabasic.sensors import (
    AVISO,
    ERROR,
    SHUNT_NOMINAL,
    calcular_4_20,
    calcular_pulsos,
)

_ICONO = {ERROR: "⛔", AVISO: "⚠", "nota": "ℹ"}
_COLOR = {ERROR: "#cf222e", AVISO: "#9a6700", "nota": "#0969da"}

#: Resistencias que se ven en campo. 270 Ω es la que el firmware da por
#: sentada; 250 Ω es la clásica de 4-20 mA a 1-5 V.
RESISTENCIAS = [
    ("270 Ω — la que asume el firmware", 270.0),
    ("250 Ω — la estándar de 1-5 V", 250.0),
    ("220 Ω", 220.0),
    ("150 Ω", 150.0),
    ("100 Ω", 100.0),
    ("500 Ω", 500.0),
    ("Otra…", 0.0),
]


class _Resultado(QWidget):
    """Panel común: avisos arriba, datos calculados y código abajo."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.avisos = QLabel()
        self.avisos.setWordWrap(True)
        self.avisos.setTextFormat(Qt.RichText)

        self.datos = QLabel()
        self.datos.setWordWrap(True)
        self.datos.setTextFormat(Qt.RichText)
        self.datos.setStyleSheet(
            "background: #f6f8fa; border: 1px solid #d8dee4; border-radius: 4px;"
            " padding: 8px;"
        )

        self.codigo = QPlainTextEdit()
        self.codigo.setReadOnly(True)
        fuente = QFont("Consolas", 9)
        fuente.setStyleHint(QFont.Monospace)
        self.codigo.setFont(fuente)
        self.codigo.setMinimumHeight(190)

        caja = QVBoxLayout(self)
        caja.setContentsMargins(0, 0, 0, 0)
        caja.addWidget(self.datos)
        caja.addWidget(self.avisos)
        caja.addWidget(QLabel("Código que se va a insertar:"))
        caja.addWidget(self.codigo, 1)

    def mostrar(self, escala) -> None:
        filas = "".join(
            f"<tr><td style='color:#57606a; padding-right:12px'>{k}</td>"
            f"<td><b>{v}</b></td></tr>"
            for k, v in escala.datos
        )
        cabeza = (
            f"<tr><td style='color:#57606a; padding-right:12px'>Mult</td>"
            f"<td><b style='color:#0550ae'>{escala.mult:.8g}</b></td></tr>"
            f"<tr><td style='color:#57606a; padding-right:12px'>Offset</td>"
            f"<td><b style='color:#0550ae'>{escala.offset:.6g}</b></td></tr>"
        )
        self.datos.setText(f"<table>{cabeza}{filas}</table>")

        if escala.avisos:
            partes = [
                f"<p style='margin:4px 0; color:{_COLOR[n]}'>"
                f"{_ICONO[n]} {t}</p>"
                for n, t in escala.avisos
            ]
            self.avisos.setText("".join(partes))
            self.avisos.show()
        else:
            self.avisos.hide()

        self.codigo.setPlainText(escala.codigo)


class AsistenteSensor(QDialog):
    """Calculadora de escalas para 4-20 mA y para contadores de pulsos."""

    insertar = pyqtSignal(str)

    def __init__(self, canales_libres=None, scan_seg: float = 10.0, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Asistente de sensores")
        self.setMinimumSize(720, 700)
        self.scan_seg = scan_seg
        self.libres = canales_libres or list(range(1, N_ANALOG + 1))

        self.tabs = QTabWidget()
        self.tabs.addTab(self._pestania_corriente(), "Sensor 4-20 mA")
        self.tabs.addTab(self._pestania_pulsos(), "Contador de pulsos")
        self.tabs.currentChanged.connect(self._recalcular)

        botones = QDialogButtonBox(QDialogButtonBox.Close)
        self.btn_insertar = botones.addButton("Insertar en el programa",
                                              QDialogButtonBox.AcceptRole)
        self.btn_insertar.clicked.connect(self._insertar)
        botones.rejected.connect(self.reject)

        caja = QVBoxLayout(self)
        caja.addWidget(self.tabs)
        caja.addWidget(botones)

        self._recalcular()

    # ── Pestaña 4-20 mA ─────────────────────────────────────────────────
    def _pestania_corriente(self) -> QWidget:
        self.c_nombre = QLineEdit("Nivel")
        self.c_unidad = QLineEdit("m")
        self.c_min = self._spin(-100000, 100000, 0.0, 3)
        self.c_max = self._spin(-100000, 100000, 5.0, 3)
        self.c_imin = self._spin(0, 100, 4.0, 2, " mA")
        self.c_imax = self._spin(0, 100, 20.0, 2, " mA")

        self.c_resistencia = QComboBox()
        for etiqueta, _ in RESISTENCIAS:
            self.c_resistencia.addItem(etiqueta)
        self.c_resistencia.currentIndexChanged.connect(self._al_cambiar_resistencia)

        self.c_ohm = self._spin(1, 10000, SHUNT_NOMINAL, 1, " Ω")
        self.c_ohm.setEnabled(False)

        self.c_canal = QSpinBox()
        self.c_canal.setRange(1, N_ANALOG)
        self.c_canal.setPrefix("I")
        if self.libres:
            self.c_canal.setValue(self.libres[0])

        self.c_voltse = QCheckBox(
            "Leer como voltaje con VoltSE (exacto con cualquier resistencia)")
        self.c_voltse.setToolTip(
            "Con Units = mA el firmware divide por los 270 Ω que trae fijos.\n"
            "Con VoltSE la resistencia real entra en la cuenta de forma exacta."
        )

        grupo_sensor = QGroupBox("Lo que dice la hoja de datos del sensor")
        f1 = QFormLayout(grupo_sensor)
        f1.addRow("Nombre de la variable", self.c_nombre)
        f1.addRow("Unidad de medida", self.c_unidad)
        fila_rango = QHBoxLayout()
        fila_rango.addWidget(self.c_min)
        fila_rango.addWidget(QLabel("hasta"))
        fila_rango.addWidget(self.c_max)
        f1.addRow("Rango que mide", fila_rango)
        fila_ma = QHBoxLayout()
        fila_ma.addWidget(self.c_imin)
        fila_ma.addWidget(QLabel("hasta"))
        fila_ma.addWidget(self.c_imax)
        f1.addRow("Corriente que entrega", fila_ma)

        grupo_gab = QGroupBox("Lo que hay en el gabinete")
        f2 = QFormLayout(grupo_gab)
        f2.addRow("Resistencia del lazo", self.c_resistencia)
        f2.addRow("", self.c_ohm)
        f2.addRow("Borne de entrada", self.c_canal)
        f2.addRow("", self.c_voltse)

        self.c_resultado = _Resultado()

        for w in (self.c_nombre, self.c_unidad):
            w.textChanged.connect(self._recalcular)
        for w in (self.c_min, self.c_max, self.c_imin, self.c_imax, self.c_ohm):
            w.valueChanged.connect(self._recalcular)
        self.c_canal.valueChanged.connect(self._recalcular)
        self.c_voltse.stateChanged.connect(self._recalcular)

        pagina = QWidget()
        caja = QVBoxLayout(pagina)
        fila = QHBoxLayout()
        fila.addWidget(grupo_sensor, 1)
        fila.addWidget(grupo_gab, 1)
        caja.addLayout(fila)
        caja.addWidget(self.c_resultado, 1)
        return pagina

    def _al_cambiar_resistencia(self, indice: int) -> None:
        _, valor = RESISTENCIAS[indice]
        if valor:
            self.c_ohm.setValue(valor)
            self.c_ohm.setEnabled(False)
        else:
            self.c_ohm.setEnabled(True)
            self.c_ohm.setFocus()
        self._recalcular()

    # ── Pestaña de pulsos ───────────────────────────────────────────────
    def _pestania_pulsos(self) -> QWidget:
        self.p_nombre = QLineEdit("Lluvia_mm")
        self.p_unidad = QLineEdit("mm")

        self.p_modo = QComboBox()
        self.p_modo.addItem("Cuánto vale cada pulso  (pluviómetro)")
        self.p_modo.addItem("Cuántos pulsos por unidad  (caudalímetro)")
        self.p_modo.currentIndexChanged.connect(self._al_cambiar_modo_pulso)

        self.p_valor = self._spin(0.000001, 1000000, 0.2, 6)
        self.p_canal = QSpinBox()
        self.p_canal.setRange(1, N_ANALOG)
        self.p_canal.setPrefix("P")

        self.p_verificar = QCheckBox("Comprobar si el ritmo esperado entra en el equipo")
        self.p_verificar.stateChanged.connect(self._recalcular)
        self.p_maximo = self._spin(0, 1000000, 0.0, 3)
        self.p_maximo.setEnabled(False)
        self.p_por_minuto = QComboBox()
        self.p_por_minuto.addItems(["por minuto", "por segundo"])
        self.p_por_minuto.setEnabled(False)

        grupo = QGroupBox("Datos del sensor")
        f = QFormLayout(grupo)
        f.addRow("Nombre de la variable", self.p_nombre)
        f.addRow("Unidad de medida", self.p_unidad)
        f.addRow("Dato de fábrica", self.p_modo)
        f.addRow("Valor", self.p_valor)
        f.addRow("Borne de entrada", self.p_canal)

        grupo_lim = QGroupBox("Comprobación de alcance")
        fl = QFormLayout(grupo_lim)
        fl.addRow(self.p_verificar)
        fila = QHBoxLayout()
        fila.addWidget(self.p_maximo)
        fila.addWidget(self.p_por_minuto)
        fl.addRow("Máximo a medir", fila)
        aclaracion = QLabel(
            "El equipo tiene un antirrebote de 50 ms fijo por firmware, pensado "
            "para contactos secos: no puede contar más de 20 pulsos por segundo."
        )
        aclaracion.setWordWrap(True)
        aclaracion.setStyleSheet("color: #57606a;")
        fl.addRow(aclaracion)

        self.p_resultado = _Resultado()

        for w in (self.p_nombre, self.p_unidad):
            w.textChanged.connect(self._recalcular)
        for w in (self.p_valor, self.p_maximo):
            w.valueChanged.connect(self._recalcular)
        self.p_canal.valueChanged.connect(self._recalcular)
        self.p_por_minuto.currentIndexChanged.connect(self._recalcular)

        pagina = QWidget()
        caja = QVBoxLayout(pagina)
        fila_sup = QHBoxLayout()
        fila_sup.addWidget(grupo, 1)
        fila_sup.addWidget(grupo_lim, 1)
        caja.addLayout(fila_sup)
        caja.addWidget(self.p_resultado, 1)
        return pagina

    def _al_cambiar_modo_pulso(self, indice: int) -> None:
        if indice == 0:
            self.p_valor.setValue(0.2)
            self.p_valor.setSuffix("")
        else:
            self.p_valor.setValue(450.0)
            self.p_valor.setSuffix(" pulsos")
        self._recalcular()

    # ── Cálculo ─────────────────────────────────────────────────────────
    def _spin(self, minimo, maximo, valor, decimales, sufijo="") -> QDoubleSpinBox:
        s = QDoubleSpinBox()
        s.setRange(minimo, maximo)
        s.setDecimals(decimales)
        s.setValue(valor)
        s.setSuffix(sufijo)
        s.setMinimumWidth(110)
        return s

    def _recalcular(self, *_):
        if self.tabs.currentIndex() == 0:
            self._escala = calcular_4_20(
                nombre=self.c_nombre.text(),
                valor_min=self.c_min.value(),
                valor_max=self.c_max.value(),
                unidad=self.c_unidad.text().strip(),
                canal=self.c_canal.value(),
                i_min=self.c_imin.value(),
                i_max=self.c_imax.value(),
                shunt=self.c_ohm.value(),
                modo="voltse" if self.c_voltse.isChecked() else "mA",
            )
            self.c_resultado.mostrar(self._escala)
        else:
            self.p_maximo.setEnabled(self.p_verificar.isChecked())
            self.p_por_minuto.setEnabled(self.p_verificar.isChecked())
            self._escala = calcular_pulsos(
                nombre=self.p_nombre.text(),
                canal=self.p_canal.value(),
                unidad_por_pulso=self.p_valor.value(),
                unidad=self.p_unidad.text().strip(),
                modo="por_pulso" if self.p_modo.currentIndex() == 0 else "por_unidad",
                caudal_max=self.p_maximo.value() if self.p_verificar.isChecked() else 0.0,
                por_segundo=self.p_por_minuto.currentIndex() == 1,
                scan_seg=self.scan_seg,
            )
            self.p_resultado.mostrar(self._escala)

        self.btn_insertar.setEnabled(not self._escala.hay_errores)
        self.btn_insertar.setToolTip(
            "Corregí los errores marcados antes de insertar el código."
            if self._escala.hay_errores else ""
        )

    def _insertar(self):
        if self._escala and not self._escala.hay_errores:
            self.insertar.emit(self._escala.codigo)
            self.accept()
