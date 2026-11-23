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
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from optabasic.limits import N_ANALOG
from . import tema
from optabasic.sensors import (
    AVISO,
    ERROR,
    SHUNT_NOMINAL,
    calcular_4_20,
    calcular_calibracion,
    calcular_pulsos,
    calcular_ultrasonico,
)

_ICONO = {ERROR: "⛔", AVISO: "⚠", "nota": "ℹ"}

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
        self.datos.setObjectName("tarjeta")        # lo estila gui/tema.py

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
        c = tema.actual()
        filas = "".join(
            f"<tr><td style='color:{c['suave']}; padding-right:12px'>{k}</td>"
            f"<td><b>{v}</b></td></tr>"
            for k, v in escala.datos
        )
        cabeza = (
            f"<tr><td style='color:{c['suave']}; padding-right:12px'>Mult</td>"
            f"<td><b style='color:{c['acento']}'>{escala.mult:.8g}</b></td></tr>"
            f"<tr><td style='color:{c['suave']}; padding-right:12px'>Offset</td>"
            f"<td><b style='color:{c['acento']}'>{escala.offset:.6g}</b></td></tr>"
        )
        self.datos.setText(f"<table>{cabeza}{filas}</table>")

        if escala.avisos:
            partes = [
                f"<p style='margin:4px 0; color:{tema.color_aviso(n)}'>"
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
    #: Valores de constantes ya declaradas en el programa (calibración).
    aplicar = pyqtSignal(dict)

    def __init__(self, canales_libres=None, scan_seg: float = 10.0, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Asistente de sensores")
        self.setMinimumSize(720, 700)
        self.scan_seg = scan_seg
        self._equipo_usb = None            # conexión USB que se reutiliza al leer mA
        self.libres = canales_libres or list(range(1, N_ANALOG + 1))

        self.tabs = QTabWidget()
        self.tabs.addTab(self._pestania_corriente(), "Sensor 4-20 mA")
        self.tabs.addTab(self._pestania_ultrasonico(), "Ultrasónico (nivel)")
        self.tabs.addTab(self._pestania_pulsos(), "Contador de pulsos")
        self.tabs.addTab(self._pestania_calibracion(), "Calibrar con 2 puntos")
        self.tabs.currentChanged.connect(self._recalcular)

        botones = QDialogButtonBox(QDialogButtonBox.Close)
        self.btn_insertar = botones.addButton("Insertar en el programa",
                                              QDialogButtonBox.AcceptRole)
        self.btn_insertar.clicked.connect(self._insertar)
        botones.rejected.connect(self.reject)
        botones.button(QDialogButtonBox.Close).setText("Cerrar")

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

    # ── Pestaña de ultrasónico ──────────────────────────────────────────
    def _pestania_ultrasonico(self) -> QWidget:
        self.u_nombre = QLineEdit("Nivel")
        self.u_unidad = QLineEdit("cm")
        self.u_d4 = self._spin(0, 100000, 30.0, 2)
        self.u_d20 = self._spin(0, 100000, 500.0, 2)
        self.u_altura = self._spin(0, 100000, 500.0, 2)
        self.u_ciega = self._spin(0, 100000, 0.0, 2)

        self.u_resistencia = QComboBox()
        for etiqueta, _ in RESISTENCIAS:
            self.u_resistencia.addItem(etiqueta)
        self.u_resistencia.currentIndexChanged.connect(self._al_cambiar_resistencia_u)
        self.u_ohm = self._spin(1, 10000, SHUNT_NOMINAL, 1, " Ω")
        self.u_ohm.setEnabled(False)

        self.u_canal = QSpinBox()
        self.u_canal.setRange(1, N_ANALOG)
        self.u_canal.setPrefix("I")
        if self.libres:
            self.u_canal.setValue(self.libres[0])
        self.u_voltse = QCheckBox(
            "Leer como voltaje con VoltSE (exacto con cualquier resistencia)")

        grupo_sensor = QGroupBox("Lo que dice la hoja de datos del sensor")
        f1 = QFormLayout(grupo_sensor)
        f1.addRow("Nombre del nivel", self.u_nombre)
        f1.addRow("Unidad de medida", self.u_unidad)
        f1.addRow("Distancia a 4 mA", self.u_d4)
        f1.addRow("Distancia a 20 mA", self.u_d20)
        f1.addRow("Zona ciega", self.u_ciega)

        grupo_inst = QGroupBox("Lo que hay en la instalación")
        f2 = QFormLayout(grupo_inst)
        f2.addRow("Altura de montaje", self.u_altura)
        f2.addRow("Resistencia del lazo", self.u_resistencia)
        f2.addRow("", self.u_ohm)
        f2.addRow("Borne de entrada", self.u_canal)
        f2.addRow("", self.u_voltse)
        ayuda = QLabel("Altura de montaje: distancia de la cara del sensor al "
                       "fondo (el cero del nivel).")
        ayuda.setWordWrap(True)
        f2.addRow(ayuda)

        self.u_resultado = _Resultado()

        for w in (self.u_nombre, self.u_unidad):
            w.textChanged.connect(self._recalcular)
        for w in (self.u_d4, self.u_d20, self.u_altura, self.u_ciega, self.u_ohm):
            w.valueChanged.connect(self._recalcular)
        self.u_canal.valueChanged.connect(self._recalcular)
        self.u_voltse.stateChanged.connect(self._recalcular)

        pagina = QWidget()
        caja = QVBoxLayout(pagina)
        fila = QHBoxLayout()
        fila.addWidget(grupo_sensor, 1)
        fila.addWidget(grupo_inst, 1)
        caja.addLayout(fila)
        caja.addWidget(self.u_resultado, 1)
        return pagina

    def _al_cambiar_resistencia_u(self, indice: int) -> None:
        _, valor = RESISTENCIAS[indice]
        if valor:
            self.u_ohm.setValue(valor)
            self.u_ohm.setEnabled(False)
        else:
            self.u_ohm.setEnabled(True)
            self.u_ohm.setFocus()
        self._recalcular()

    # ── Pestaña de calibración con medidas de terreno ───────────────────
    def _pestania_calibracion(self) -> QWidget:
        self.k_prefijo = QLineEdit("Rio")
        self.k_prefijo.setToolTip("Rio da Rio_Mult, Rio_Off y Cero_Rio; CM da CM_Mult y CM_Off.")
        self.k_d1 = self._spin(0, 100000, 100.0, 1, " cm")
        self.k_m1 = self._spin(0, 30, 6.9, 3, " mA")
        self.k_d2 = self._spin(0, 100000, 300.0, 1, " cm")
        self.k_m2 = self._spin(0, 30, 15.2, 3, " mA")

        self.k_ver = QCheckBox("Agregar un tercer punto para comprobar la recta")
        self.k_d3 = self._spin(0, 100000, 200.0, 1, " cm")
        self.k_m3 = self._spin(0, 30, 11.0, 3, " mA")
        self.k_cero = QCheckBox("Calcular el cero de la regla (solo el RIKA del río)")
        self.k_nivel = self._spin(-100000, 100000, 50.0, 1, " cm")
        self.k_mnivel = self._spin(0, 30, 10.0, 3, " mA")
        for w in (self.k_d3, self.k_m3, self.k_nivel, self.k_mnivel):
            w.setEnabled(False)
        self.k_ver.stateChanged.connect(
            lambda s: [w.setEnabled(bool(s)) for w in (self.k_d3, self.k_m3)])
        self.k_cero.stateChanged.connect(
            lambda s: [w.setEnabled(bool(s)) for w in (self.k_nivel, self.k_mnivel)])

        ayuda = QLabel(
            "Pon un blanco plano frente al RIKA a una distancia medida con huincha "
            "(desde la cara del sensor) y anota los mA que muestra el equipo "
            "(<b>CM_filt</b> o <b>Rio_filt</b> en el HMI). Repítelo lejos. "
            "Mientras más separados los puntos, mejor.")
        ayuda.setWordWrap(True)

        g1 = QGroupBox("Puntos medidos")
        f1 = QFormLayout(g1)
        self.k_ohm = self._spin(1, 10000, 269.0, 1, " Ω")
        self.k_ohm.setToolTip(
            "La resistencia física del lazo 4-20 mA de ESTE sensor. Con 269 Ω "
            "el equipo muestra los mA reales; con otra, los muestra escalados.")
        self.k_ohm.valueChanged.connect(self._recalcular)
        f1.addRow("Constantes con el prefijo", self.k_prefijo)
        f1.addRow("Resistencia del lazo", self.k_ohm)
        f1.addRow("Punto 1: distancia real", self.k_d1)
        f1.addRow("Punto 1: lo que lee", self._con_lectura(self.k_m1))
        f1.addRow("Punto 2: distancia real", self.k_d2)
        f1.addRow("Punto 2: lo que lee", self._con_lectura(self.k_m2))

        g2 = QGroupBox("Opcional")
        f2 = QFormLayout(g2)
        f2.addRow(self.k_ver)
        f2.addRow("Punto 3: distancia real", self.k_d3)
        f2.addRow("Punto 3: lo que lee", self._con_lectura(self.k_m3))
        f2.addRow(self.k_cero)
        f2.addRow("Nivel que marca la regla", self.k_nivel)
        f2.addRow("Lo que lee el RIKA ahora", self._con_lectura(self.k_mnivel))

        self.k_resultado = _Resultado()
        self.k_resultado.codigo.setMinimumHeight(90)

        self.k_prefijo.textChanged.connect(self._recalcular)
        for w in (self.k_d1, self.k_m1, self.k_d2, self.k_m2, self.k_d3, self.k_m3,
                  self.k_nivel, self.k_mnivel):
            w.valueChanged.connect(self._recalcular)
        self.k_ver.stateChanged.connect(self._recalcular)
        self.k_cero.stateChanged.connect(self._recalcular)

        pagina = QWidget()
        caja = QVBoxLayout(pagina)
        caja.addWidget(ayuda)
        fila = QHBoxLayout()
        fila.addWidget(g1, 1)
        fila.addWidget(g2, 1)
        caja.addLayout(fila)
        caja.addWidget(self.k_resultado, 1)
        return pagina

    def _con_lectura(self, spin) -> QWidget:
        """El campo de mA con un botón que lo llena leyendo el equipo por USB."""
        boton = QPushButton("Leer del equipo")
        boton.setToolTip(
            "Conecta por USB y toma el valor de CM_filt o Rio_filt (firmware 1.12.0 "
            "o posterior). Se puede escribir a mano si no hay cable.")
        boton.clicked.connect(lambda _=False, s=spin: self._leer_del_equipo(s))
        w = QWidget()
        fila = QHBoxLayout(w)
        fila.setContentsMargins(0, 0, 0, 0)
        fila.addWidget(spin, 1)
        fila.addWidget(boton)
        return w

    def _leer_del_equipo(self, spin) -> None:
        """Abre las variables en vivo para elegir una; la conexión se conserva
        mientras el asistente siga abierto, así el segundo punto no reconecta."""
        from .variables_dialog import DialogoVariables
        d = DialogoVariables(equipo=self._equipo_usb, seleccionar=True,
                             filtro="filt", parent=self)
        d.conservar = True
        d.exec_()
        if d.fallo_equipo:
            self._cerrar_usb()
        elif self._equipo_usb is None and d.equipo is not None:
            self._equipo_usb = d.equipo
        if d.elegida is not None:
            spin.setValue(d.elegida[1])

    def _cerrar_usb(self) -> None:
        if self._equipo_usb is not None:
            self._equipo_usb.cerrar()
        self._equipo_usb = None

    def done(self, resultado) -> None:
        self._cerrar_usb()
        super().done(resultado)

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
        f.addRow("Borne de conteo", self.p_canal)
        f.addRow(self.p_verificar)
        fila = QHBoxLayout()
        fila.addWidget(self.p_maximo)
        fila.addWidget(self.p_por_minuto)
        f.addRow("Máximo a medir", fila)

        # ── Circuito de entrada ─────────────────────────────────────────
        self.p_alimentacion = QComboBox()
        self.p_alimentacion.addItem("Fuente externa con divisor  (lo habitual)")
        self.p_alimentacion.addItem("Excitación desde un borne del Opta (ExciteCh)")
        self.p_alimentacion.currentIndexChanged.connect(self._al_cambiar_alimentacion)

        self.p_fuente = self._spin(1, 48, 12.0, 1, " V")
        self.p_arriba = self._spin(0.1, 1000, 2.2, 2, " kΩ")
        self.p_abajo = self._spin(0.1, 1000, 10.0, 2, " kΩ")
        self.p_excitacion = QSpinBox()
        self.p_excitacion.setRange(1, N_ANALOG)
        self.p_excitacion.setPrefix("I")
        self.p_excitacion.setValue(2)
        self.p_excitacion.setEnabled(False)

        grupo_cir = QGroupBox("Circuito de entrada")
        fc = QFormLayout(grupo_cir)
        fc.addRow("Alimentación", self.p_alimentacion)
        fc.addRow("Tensión de la fuente", self.p_fuente)
        fc.addRow("Resistencia al positivo", self.p_arriba)
        fc.addRow("Resistencia al negativo", self.p_abajo)
        fc.addRow("Borne de excitación", self.p_excitacion)
        self.p_esquema = QLabel()
        self.p_esquema.setWordWrap(True)
        self.p_esquema.setObjectName("tarjeta")
        self.p_esquema.setStyleSheet("font-family: Consolas, monospace;")
        fc.addRow(self.p_esquema)

        self.p_resultado = _Resultado()

        for w in (self.p_nombre, self.p_unidad):
            w.textChanged.connect(self._recalcular)
        for w in (self.p_valor, self.p_maximo, self.p_fuente, self.p_arriba,
                  self.p_abajo):
            w.valueChanged.connect(self._recalcular)
        for w in (self.p_canal, self.p_excitacion):
            w.valueChanged.connect(self._recalcular)
        self.p_por_minuto.currentIndexChanged.connect(self._recalcular)

        pagina = QWidget()
        caja = QVBoxLayout(pagina)
        fila_sup = QHBoxLayout()
        fila_sup.addWidget(grupo, 1)
        fila_sup.addWidget(grupo_cir, 1)
        caja.addLayout(fila_sup)
        caja.addWidget(self.p_resultado, 1)
        return pagina

    def _al_cambiar_alimentacion(self, indice: int) -> None:
        externa = indice == 0
        for w in (self.p_fuente, self.p_arriba, self.p_abajo):
            w.setEnabled(externa)
        self.p_excitacion.setEnabled(not externa)
        self._recalcular()

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
        elif self.tabs.currentIndex() == 1:
            self._escala = calcular_ultrasonico(
                nombre=self.u_nombre.text(),
                dist_4ma=self.u_d4.value(),
                dist_20ma=self.u_d20.value(),
                altura=self.u_altura.value(),
                zona_ciega=self.u_ciega.value(),
                unidad=self.u_unidad.text().strip(),
                canal=self.u_canal.value(),
                shunt=self.u_ohm.value(),
                modo="voltse" if self.u_voltse.isChecked() else "mA",
            )
            self.u_resultado.mostrar(self._escala)
        elif self.tabs.currentIndex() == 3:
            self._escala = calcular_calibracion(
                dist1=self.k_d1.value(), ma1=self.k_m1.value(),
                dist2=self.k_d2.value(), ma2=self.k_m2.value(),
                prefijo=self.k_prefijo.text(),
                shunt=self.k_ohm.value(),
                dist3=self.k_d3.value() if self.k_ver.isChecked() else None,
                ma3=self.k_m3.value() if self.k_ver.isChecked() else None,
                nivel_real=self.k_nivel.value() if self.k_cero.isChecked() else None,
                ma_nivel=self.k_mnivel.value() if self.k_cero.isChecked() else None,
            )
            self.k_resultado.mostrar(self._escala)
        else:
            self.p_maximo.setEnabled(self.p_verificar.isChecked())
            self.p_por_minuto.setEnabled(self.p_verificar.isChecked())
            externa = self.p_alimentacion.currentIndex() == 0
            self._escala = calcular_pulsos(
                nombre=self.p_nombre.text(),
                canal=self.p_canal.value(),
                unidad_por_pulso=self.p_valor.value(),
                unidad=self.p_unidad.text().strip(),
                modo="por_pulso" if self.p_modo.currentIndex() == 0 else "por_unidad",
                caudal_max=self.p_maximo.value() if self.p_verificar.isChecked() else 0.0,
                por_segundo=self.p_por_minuto.currentIndex() == 1,
                scan_seg=self.scan_seg,
                alimentacion="externa" if externa else "opta",
                v_fuente=self.p_fuente.value(),
                r_arriba=self.p_arriba.value() * 1000.0,
                r_abajo=self.p_abajo.value() * 1000.0,
                canal_excitacion=self.p_excitacion.value(),
            )
            if externa:
                self.p_esquema.setText(
                    f"+{self.p_fuente.value():g}V ── {self.p_arriba.value():g}kΩ ── "
                    f"[contacto] ── I{self.p_canal.value()} ── "
                    f"{self.p_abajo.value():g}kΩ ── NEGATIVO"
                )
            else:
                self.p_esquema.setText(
                    f"I{self.p_excitacion.value()} (3,3 V) ── [contacto] ── "
                    f"I{self.p_canal.value()} ── 10kΩ ── NEGATIVO"
                )
            self.p_resultado.mostrar(self._escala)

        calibrando = self.tabs.currentIndex() == 3
        self.btn_insertar.setText(
            "Aplicar a las constantes del programa" if calibrando
            else "Insertar en el programa")
        self.btn_insertar.setEnabled(not self._escala.hay_errores)
        self.btn_insertar.setToolTip(
            "Corregí los errores marcados antes de insertar el código."
            if self._escala.hay_errores else
            "Cambia el valor de esas constantes si el programa ya las tiene; "
            "las que falten se insertan donde está el cursor." if calibrando else ""
        )

    def _insertar(self):
        if self._escala and not self._escala.hay_errores:
            if self.tabs.currentIndex() == 3:
                self.aplicar.emit(dict(self._escala.constantes))
            else:
                self.insertar.emit(self._escala.codigo)
            self.accept()
