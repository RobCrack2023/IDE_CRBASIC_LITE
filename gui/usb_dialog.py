"""Rescate por USB: bajar los registros del equipo y cargarle el programa.

Es lo mismo que hace la página `rescatar_registros.html` del repo OptaPakBus,
pero adentro del IDE: se usa cuando el equipo no tiene red (o el módem no
anda) y hay que ir a la estación con un cable USB-C.

También carga un firmware nuevo (.bin) y restablece el equipo de fábrica.

Toda la conversación con el equipo corre en un hilo aparte para que la
ventana no se congele durante una descarga larga.
"""

import os
import re
import time

from PyQt5.QtCore import QSettings, QThread, QTimer, pyqtSignal, pyqtSlot
from PyQt5.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
)

from optabasic import usb_rescate as usb


TEXTO_SIN_RESPUESTA = (
    "El puerto USB se abrió pero el equipo no respondió.\n\n"
    "Qué revisar:\n"
    "• Sin cable de red o sin red: un equipo con firmware anterior a la 1.11.1 "
    "puede pasar más de un minuto buscando red sin atender el USB, y reiniciarse. "
    "Espera uno o dos minutos y vuelve a conectar.\n"
    "• Si lo acabas de encender, espera unos 20 segundos.\n"
    "• Cierra el Monitor Serie del Arduino IDE u otro programa que use el puerto.\n"
    "• Un firmware anterior a la 1.7.3 no tiene rescate por USB.\n\n"
    "Detalle: {detalle}"
)


def _texto_error(mensaje: str) -> str:
    """«timeout» es lo que ve la capa de protocolo; a quien opera hay que decirle
    qué pasó."""
    if mensaje == "timeout":
        return "El equipo no respondió (se agotó el tiempo de espera)."
    return mensaje


class _Tarea(QThread):
    """Corre una función en un hilo y avisa cómo terminó."""

    avance = pyqtSignal(int, int)
    linea = pyqtSignal(str)
    terminada = pyqtSignal(object)        # el resultado
    fallo = pyqtSignal(str)

    def __init__(self, funcion, parent=None):
        super().__init__(parent)
        self._funcion = funcion
        self.cancelada = False

    def run(self):
        try:
            self.terminada.emit(self._funcion(self))
        except usb.ErrorUSB as e:
            self.fallo.emit(str(e))
        except Exception as e:                       # no dejar morir el hilo mudo
            self.fallo.emit(f"{type(e).__name__}: {e}")


class DialogoUSB(QDialog):
    def __init__(self, datos_programa, abrir_en_editor=None, parent=None):
        """`datos_programa()` devuelve (bytes, nombre) del programa del editor;
        `abrir_en_editor(bytes, nombre)` pone en el editor el que trae el equipo."""
        super().__init__(parent)
        self._abrir_en_editor = abrir_en_editor
        self.setWindowTitle("Rescate por USB")
        self.setMinimumSize(640, 760)
        self._datos_programa = datos_programa
        self.equipo = None
        self._tarea = None
        self._ajustes = QSettings()
        self._resumen = None

        # ── Conexión ────────────────────────────────────────────────────
        self.puertos = QComboBox()
        self.btn_actualizar = QPushButton("Actualizar")
        self.btn_actualizar.clicked.connect(self._llenar_puertos)
        self.btn_conectar = QPushButton("Conectar")
        self.btn_conectar.clicked.connect(self._conectar_o_desconectar)
        self.estado = QLabel("Conectá el cable USB-C y elegí el puerto.")
        self.estado.setWordWrap(True)

        g_con = QGroupBox("1. Conectar")
        f = QVBoxLayout(g_con)
        fila = QHBoxLayout()
        fila.addWidget(self.puertos, 1)
        fila.addWidget(self.btn_actualizar)
        fila.addWidget(self.btn_conectar)
        f.addLayout(fila)
        f.addWidget(self.estado)
        self.btn_vars = QPushButton("Ver las variables en vivo…")
        self.btn_vars.setToolTip(
            "Los valores que el equipo tiene ahora, sin servidor. Solo lectura; "
            "hace falta el firmware 1.12.0 o posterior.")
        self.btn_vars.clicked.connect(self._ver_variables)
        f.addWidget(self.btn_vars)

        # ── Descarga ────────────────────────────────────────────────────
        self.tabla = QComboBox()
        self.tabla.currentIndexChanged.connect(self._info_tabla)
        self.info_tabla = QLabel()
        self.info_tabla.setWordWrap(True)
        self.r_todo = QRadioButton("Todo lo que hay guardado")
        self.r_dias = QRadioButton("Solo los últimos")
        self.r_regs = QRadioButton("Solo los últimos")
        self.r_todo.setChecked(True)
        grupo = QButtonGroup(self)
        for r in (self.r_todo, self.r_dias, self.r_regs):
            grupo.addButton(r)
        self.n_dias = QSpinBox()
        self.n_dias.setRange(1, 100000)
        self.n_dias.setValue(7)
        self.n_dias.setSuffix(" días")
        self.n_regs = QSpinBox()
        self.n_regs.setRange(1, 10000000)
        self.n_regs.setValue(1000)
        self.n_regs.setSuffix(" registros")
        self.formato = QComboBox()
        self.formato.addItem("Excel en español (separador «;» y coma decimal)", True)
        self.formato.addItem("Estándar (separador «,» y punto decimal)", False)

        self.btn_descargar = QPushButton("Descargar CSV…")
        self.btn_descargar.clicked.connect(self._descargar)
        self.btn_cancelar = QPushButton("Cancelar")
        self.btn_cancelar.clicked.connect(self._cancelar)
        self.btn_cancelar.setEnabled(False)
        self.barra = QProgressBar()
        self.barra.setTextVisible(True)

        g_des = QGroupBox("2. Descargar registros")
        d = QFormLayout(g_des)
        d.addRow("Tabla", self.tabla)
        d.addRow(self.info_tabla)
        fr = QHBoxLayout()
        fr.addWidget(self.r_dias)
        fr.addWidget(self.n_dias)
        fr.addStretch()
        d.addRow(self.r_todo)
        d.addRow(fr)
        fr2 = QHBoxLayout()
        fr2.addWidget(self.r_regs)
        fr2.addWidget(self.n_regs)
        fr2.addStretch()
        d.addRow(fr2)
        d.addRow("Formato", self.formato)
        fb = QHBoxLayout()
        fb.addWidget(self.btn_descargar)
        fb.addWidget(self.btn_cancelar)
        fb.addStretch()
        d.addRow(fb)
        d.addRow(self.barra)

        # ── Programa ────────────────────────────────────────────────────
        self.lbl_programa = QLabel("Programa instalado: —")
        self.lbl_programa.setWordWrap(True)
        self.btn_programa = QPushButton("Cargar el programa del editor al equipo")
        self.btn_programa.clicked.connect(self._cargar_programa)
        self.btn_traer = QPushButton("Traer el programa del equipo al editor")
        self.btn_traer.clicked.connect(self._traer_programa)
        aviso = QLabel(
            "Reemplaza el programa actual. Si el nuevo cambia las columnas de "
            "una tabla, el historial de esa tabla se borra en el equipo: "
            "<b>descargá los registros antes</b>.")
        aviso.setWordWrap(True)
        g_prog = QGroupBox("3. Programa del equipo")
        p = QVBoxLayout(g_prog)
        p.addWidget(self.lbl_programa)
        p.addWidget(aviso)
        fila_prog = QHBoxLayout()
        fila_prog.addWidget(self.btn_traer)
        fila_prog.addWidget(self.btn_programa)
        p.addLayout(fila_prog)

        # ── Firmware y restablecer ──────────────────────────────────────
        self.lbl_firmware = QLabel("Firmware instalado: —")
        self.btn_firmware = QPushButton("Cargar firmware (.bin)…")
        self.btn_firmware.clicked.connect(self._cargar_firmware)
        self.btn_formatear = QPushButton("Restablecer de fábrica…")
        self.btn_formatear.clicked.connect(self._restablecer)
        aviso_fw = QLabel(
            "<b>Cargar firmware:</b> usá el archivo <i>OptaPakBus.ino.bin</i> (no el "
            "«with_bootloader»). El equipo se reinicia al instalarlo y tarda cerca "
            "de un minuto; no desconectes el cable ni la energía.<br>"
            "<b>Restablecer:</b> borra el programa, las tablas, los registros y el "
            "log. El firmware no se toca. Si vas a cambiar de firmware, restablecé "
            "primero y cargá el firmware después, no al revés. "
            "<b>Descargá los registros antes.</b>")
        aviso_fw.setWordWrap(True)
        g_fw = QGroupBox("4. Firmware y restablecer de fábrica")
        pf = QVBoxLayout(g_fw)
        pf.addWidget(self.lbl_firmware)
        pf.addWidget(aviso_fw)
        fila_fw = QHBoxLayout()
        fila_fw.addWidget(self.btn_formatear)
        fila_fw.addWidget(self.btn_firmware)
        pf.addLayout(fila_fw)

        self.registro = QPlainTextEdit()
        self.registro.setReadOnly(True)
        self.registro.setMaximumBlockCount(500)
        self.registro.setMaximumHeight(110)
        self.registro.setPlaceholderText("Detalle técnico: lo que dice el equipo.")

        caja = QVBoxLayout(self)
        caja.addWidget(g_con)
        caja.addWidget(g_des)
        caja.addWidget(g_prog)
        caja.addWidget(g_fw)
        caja.addWidget(self.registro)

        self._llenar_puertos()
        self._habilitar()

    # ── Estado de la interfaz ───────────────────────────────────────────
    def _ocupado(self) -> bool:
        return self._tarea is not None and self._tarea.isRunning()

    def _habilitar(self):
        conectado = self.equipo is not None
        libre = conectado and not self._ocupado()
        self.puertos.setEnabled(not conectado)
        self.btn_actualizar.setEnabled(not conectado)
        self.btn_conectar.setText("Desconectar" if conectado else "Conectar")
        self.btn_conectar.setEnabled(not self._ocupado())
        hay_tablas = conectado and bool(self.equipo.tablas)
        self.btn_descargar.setEnabled(libre and hay_tablas)
        self.btn_programa.setEnabled(libre)
        self.btn_traer.setEnabled(libre and self._abrir_en_editor is not None
                                  and self.equipo.info.programa is not None)
        self.btn_firmware.setEnabled(libre)
        self.btn_formatear.setEnabled(libre)
        self.btn_vars.setEnabled(libre)
        self.btn_cancelar.setEnabled(self._ocupado())

    @pyqtSlot(str)
    def _log(self, texto: str):
        self.registro.appendPlainText(texto)

    def _llenar_puertos(self):
        self.puertos.clear()
        lista = usb.listar_puertos()
        for dev, desc in lista:
            self.puertos.addItem(f"{desc}", dev)
        ultimo = self._ajustes.value("usb/puerto", "")
        i = self.puertos.findData(ultimo)
        if i >= 0:
            self.puertos.setCurrentIndex(i)
        if not lista:
            self.estado.setText("No se ve ningún puerto USB. Conectá el cable y "
                                "presioná «Actualizar».")

    # ── Conexión ────────────────────────────────────────────────────────
    def _conectar_o_desconectar(self):
        if self.equipo is not None:
            self._desconectar()
            self.estado.setText("Desconectado.")
            return
        dev = self.puertos.currentData()
        if not dev:
            self.estado.setText("Elegí un puerto de la lista.")
            return
        try:
            self.equipo = usb.abrir_puerto(dev)
        except usb.ErrorUSB as e:
            self.estado.setText(str(e))
            return
        self._ajustes.setValue("usb/puerto", dev)
        self.estado.setText("Puerto abierto. Esperando respuesta del equipo…")
        self._habilitar()
        self._correr(lambda t: self.equipo.leer_tablas(), self._tablas_leidas,
                     self._conexion_fallo)

    def _conexion_fallo(self, mensaje: str):
        """El puerto abrió pero el equipo no contestó (o contestó con error).

        Antes el diálogo se quedaba en «Conectado» con el botón «Desconectar» y
        el motivo en una línea chica de arriba: quien conecta un equipo sin red
        creía que andaba. Ahora se cierra el puerto, vuelve el botón «Conectar»
        y sale una ventana, que no se puede pasar por alto.
        """
        self._log(mensaje)
        self._desconectar()
        self.estado.setText("No se pudo conectar con el equipo.")
        QMessageBox.warning(self, "No se pudo conectar", TEXTO_SIN_RESPUESTA.format(detalle=mensaje))

    def _desconectar(self):
        if self._ocupado():
            self._tarea.cancelada = True
            self._tarea.wait(3000)
        if self.equipo is not None:
            self.equipo.cerrar()
        self.equipo = None
        self.tabla.clear()
        self.info_tabla.clear()
        self.lbl_programa.setText("Programa instalado: —")
        self.lbl_firmware.setText("Firmware instalado: —")
        self.barra.setMaximum(1)
        self.barra.setValue(0)
        self._habilitar()

    def _tablas_leidas(self, tablas):
        info = self.equipo.info
        self.estado.setText(f"Conectado a «{info.estacion}» (firmware {info.firmware}).")
        if self._resumen:
            self.estado.setText(self._resumen)
            self._resumen = None
        self.tabla.clear()
        for t in tablas:
            self.tabla.addItem(f"{t.nombre} — {t.cantidad} registros", t)
        if not tablas:
            self.estado.setText(
                f"Equipo conectado («{info.estacion}»), pero no tiene tablas "
                "de datos guardadas. Igual se le puede cargar un programa.")
        if info.almacenamiento_ok == 0:
            self._log("ATENCIÓN: el almacenamiento del equipo no está disponible; "
                      "no guarda programa ni registros.")
        if info.programa is None:
            txt = "Programa instalado: ninguno."
        else:
            txt = (f"Programa instalado: {info.programa.replace('CPU:', '')} — "
                   f"{info.prog_bytes} bytes, firma {info.prog_firma}.")
        self.lbl_programa.setText(txt)
        self.lbl_firmware.setText(f"Firmware instalado: {info.firmware or 'desconocido'}.")
        self._info_tabla()
        self._habilitar()

    def _info_tabla(self, *_):
        t = self.tabla.currentData()
        if not t:
            self.info_tabla.clear()
            return
        txt = f"{t.cantidad} registros guardados (números {t.primero} a {t.ultimo})"
        if t.intervalo > 0:
            cada = f"{t.intervalo // 60} min" if t.intervalo >= 60 and t.intervalo % 60 == 0 \
                else f"{t.intervalo} s"
            txt += f", uno cada {cada}, unos {t.dias:.1f} días de datos"
        self.info_tabla.setText(txt + ".")

    # ── Tareas en segundo plano ─────────────────────────────────────────
    def _correr(self, funcion, al_terminar, al_fallar=None):
        # OJO con los hilos: una señal conectada a una lambda corre la lambda
        # en el hilo que emite, y tocar un widget desde ahí tira el programa
        # («Cannot queue arguments of type QTextBlock»). Por eso todo vuelve
        # por métodos del diálogo, que Qt entrega en el hilo de la ventana, y
        # el log del equipo también viaja por una señal.
        tarea = _Tarea(funcion, self)
        tarea.al_terminar = al_terminar
        tarea.al_fallar = al_fallar
        self._tarea = tarea
        tarea.avance.connect(self._avance)
        tarea.linea.connect(self._log)
        tarea.terminada.connect(self._tarea_terminada)
        tarea.fallo.connect(self._tarea_fallo)
        self.equipo.log = tarea.linea.emit
        self.equipo.cancelar = lambda: tarea.cancelada
        self.barra.setValue(0)
        self._habilitar()
        tarea.start()
        self._habilitar()

    def _avance(self, hecho, total):
        self.barra.setMaximum(max(total, 1))
        self.barra.setValue(hecho)
        self.barra.setFormat(f"{hecho} de {total}")

    @pyqtSlot(object)
    def _tarea_terminada(self, resultado):
        tarea = self.sender()
        tarea.wait()
        self._habilitar()
        tarea.al_terminar(resultado)
        self._habilitar()

    @pyqtSlot(str)
    def _tarea_fallo(self, mensaje):
        tarea = self.sender()
        tarea.wait()
        self._habilitar()
        if tarea.al_fallar:
            tarea.al_fallar(mensaje)
        else:
            self.estado.setText(mensaje)
            self._log(mensaje)
        self._habilitar()

    def _cancelar(self):
        if self._ocupado():
            self._tarea.cancelada = True
            self.estado.setText("Cancelando…")

    # ── Descarga ────────────────────────────────────────────────────────
    def _descargar(self):
        t = self.tabla.currentData()
        if not t:
            return
        excel_es = bool(self.formato.currentData())
        if self.r_dias.isChecked():
            desde = usb.EquipoUSB.desde_registro(t, dias=self.n_dias.value())
        elif self.r_regs.isChecked():
            desde = usb.EquipoUSB.desde_registro(t, ultimos=self.n_regs.value())
        else:
            desde = 0

        seguro = lambda s: re.sub(r"[^A-Za-z0-9_-]+", "_", s or "datos")
        sello = time.strftime("%Y%m%d_%H%M")
        sugerido = f"{seguro(self.equipo.info.estacion)}_{seguro(t.nombre)}_{sello}.csv"
        carpeta = self._ajustes.value("usb/carpeta", "")
        ruta, _ = QFileDialog.getSaveFileName(
            self, "Guardar los registros", os.path.join(carpeta, sugerido),
            "CSV (*.csv)")
        if not ruta:
            return
        self._ajustes.setValue("usb/carpeta", os.path.dirname(ruta))
        self.estado.setText("Pidiendo datos al equipo…")

        def trabajo(tarea):
            return self.equipo.volcar(
                t, desde, excel_es, lambda a, b: tarea.avance.emit(a, b))

        self._correr(trabajo, lambda v: self._guardar(v, ruta, excel_es))

    def _guardar(self, v, ruta, excel_es):
        if not v.filas:
            self.estado.setText("No llegaron registros"
                                + (f": {v.error}." if v.error else "."))
            return
        with open(ruta, "w", encoding="utf-8", newline="") as f:
            f.write(usb.EquipoUSB.csv(v, excel_es))
        n = len(v.filas)
        if v.error == "cancelado":
            self.estado.setText(f"Cancelado. Se guardaron {n} registros en {ruta}.")
        elif v.error:
            self.estado.setText(
                f"No se pudo completar: {v.error}. Se guardaron {n} registros "
                f"en {ruta}.")
        elif not v.completo:
            self.estado.setText(
                f"Atención: el equipo informó {v.informadas} registros y llegaron "
                f"{n}. Repetí la descarga. (Se guardó lo recibido en {ruta}.)")
        else:
            self.estado.setText(f"Listo: {n} registros guardados en {ruta}.")
        self._log(f"archivo: {ruta} ({n} filas)")

    # ── Programa ────────────────────────────────────────────────────────
    def _cargar_programa(self):
        datos, nombre = self._datos_programa()
        if datos is None:
            return                                   # el IDE ya explicó por qué
        r = QMessageBox.question(
            self, "Reemplazar el programa",
            f"Se va a REEMPLAZAR el programa del equipo por «{nombre}» "
            f"({len(datos)} bytes, firma {usb.calcular_firma(datos)}).\n\n"
            "Si el programa nuevo cambia las columnas de alguna tabla, el "
            "historial de esa tabla se borra.\n¿Ya descargó los registros que "
            "necesita?\n\n¿Continuar?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        self.estado.setText("Enviando el programa…")

        def trabajo(tarea):
            return self.equipo.cargar_programa(
                datos, nombre, lambda a, b: tarea.avance.emit(a, b))

        self._correr(trabajo, self._programa_cargado,
                     lambda m: self._programa_fallo(m))

    def _traer_programa(self):
        self.estado.setText("Leyendo el programa del equipo…")
        nombre = (self.equipo.info.programa or "programa.CR1").replace("CPU:", "")

        def trabajo(tarea):
            return self.equipo.leer_programa(lambda a, b: tarea.avance.emit(a, b))

        def listo(datos):
            if self._abrir_en_editor(datos, nombre):
                self.estado.setText(
                    f"Programa «{nombre}» ({len(datos)} bytes) abierto en el "
                    "editor. Guardalo para conservarlo.")
                self.accept()
            else:
                self.estado.setText("Lectura lista, pero no se abrió: el editor "
                                    "tiene cambios sin guardar.")

        self._correr(trabajo, listo,
                     lambda m: (self.estado.setText(f"No se pudo leer el programa: {m}"),
                                self._log(m)))

    def _programa_fallo(self, mensaje):
        self.estado.setText(f"No se pudo cargar el programa: {mensaje}")
        self._log(mensaje)

    def _programa_cargado(self, res):
        msg = (f"Programa cargado: {res['tablas']} tabla(s), {res['variables']} "
               f"variable(s), {res['instrucciones']} instrucción(es).")
        if res["tablas"] == 0:
            msg += " ATENCIÓN: el equipo no encontró ninguna tabla de datos."
        if res["problemas"] > 0:
            msg += (f" Hay {res['problemas']} línea(s) que el equipo ignoró: "
                    "revisá el programa en el IDE.")
        self.estado.setText(msg)
        self._log(f"programa cargado, firma {res['firma']}")
        # El equipo puede reconectarse un instante: refrescar tablas y programa
        # sin congelar la ventana, y sin pisar este mensaje.
        self._resumen = msg
        QTimer.singleShot(1200, self._refrescar)

    # ── Variables en vivo ───────────────────────────────────────────────
    def _ver_variables(self):
        from .variables_dialog import DialogoVariables      # evita el import circular
        DialogoVariables(self.equipo, parent=self).exec_()
        self._habilitar()

    # ── Firmware ────────────────────────────────────────────────────────
    def _cargar_firmware(self):
        """Elegir el .bin, revisarlo, cargarlo, verificarlo e instalarlo.

        Dos confirmaciones, porque es lo único que puede dejar el equipo sin
        arrancar: antes de empezar (cargar no cambia nada) y antes de instalar
        (desde ahí no hay marcha atrás ni cancelación).
        """
        carpeta = self._ajustes.value("usb/carpeta_firmware", "")
        ruta, _ = QFileDialog.getOpenFileName(
            self, "Firmware compilado (OptaPakBus.ino.bin)", carpeta, "Firmware (*.bin)")
        if not ruta:
            return
        self._ajustes.setValue("usb/carpeta_firmware", os.path.dirname(ruta))
        try:
            with open(ruta, "rb") as f:
                datos = f.read()
            nuevo = usb.analizar_firmware(datos, os.path.basename(ruta))
        except (OSError, usb.ErrorUSB) as e:
            QMessageBox.warning(self, "Ese archivo no sirve", str(e))
            return

        instalado = self.equipo.info.firmware or ""
        cmp = (usb.version_tupla(nuevo.version) > usb.version_tupla(instalado)) \
            - (usb.version_tupla(nuevo.version) < usb.version_tupla(instalado))
        nota = ""
        if instalado and cmp == 0:
            nota = "\n\nATENCIÓN: es la MISMA versión que ya tiene el equipo."
        elif instalado and cmp < 0:
            nota = "\n\nATENCIÓN: es una versión ANTERIOR a la instalada."
        r = QMessageBox.question(
            self, "Cargar firmware",
            f"Se va a cargar el firmware {nuevo.version} ({nuevo.tamano} bytes, "
            f"CRC {nuevo.crc:08X}) en «{self.equipo.info.estacion}».\n"
            f"Instalado ahora: {instalado or 'desconocido'}.{nota}\n\n"
            "Durante la carga NO desconectes el cable ni la energía. Todavía no "
            "se instala: antes se verifica lo que llegó.\n\n¿Continuar?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        self.estado.setText(f"Enviando el firmware {nuevo.version}…")

        def trabajo(tarea):
            self.equipo.cargar_firmware(datos, lambda a, b: tarea.avance.emit(a, b))
            return nuevo

        self._correr(trabajo, self._firmware_cargado, self._firmware_fallo)

    def _firmware_fallo(self, mensaje):
        mensaje = _texto_error(mensaje)
        self._log(mensaje)
        self.estado.setText("No se pudo cargar el firmware.")
        QMessageBox.warning(
            self, "No se pudo cargar el firmware",
            f"{mensaje}\n\nEl equipo sigue con su firmware actual.")

    def _firmware_cargado(self, nuevo):
        self.estado.setText(f"Firmware {nuevo.version} cargado y verificado en el equipo.")
        r = QMessageBox.question(
            self, "Instalar el firmware",
            f"El firmware {nuevo.version} quedó cargado y verificado.\n\n"
            "¿Instalarlo ahora? El equipo se reiniciará y tarda cerca de un minuto. "
            "Desde aquí ya no se puede cancelar ni volver atrás: no desconectes el "
            "cable ni la energía.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r != QMessageBox.Yes:
            self.equipo._cancelar_en_equipo()
            self.estado.setText("Instalación cancelada: el equipo sigue con su firmware actual.")
            return
        self.estado.setText("Instalando el firmware…")
        # Se arranca fuera de este callback: sigue corriendo dentro de la tarea anterior.
        QTimer.singleShot(0, lambda: self._correr(
            lambda t: self.equipo.instalar_firmware(),
            lambda _: self._reiniciando(
                f"Instalando el firmware {nuevo.version}. El equipo se está reiniciando: "
                "espera cerca de un minuto y conecta de nuevo para comprobar la versión."),
            self._firmware_fallo_instalar))

    def _firmware_fallo_instalar(self, mensaje):
        mensaje = _texto_error(mensaje)
        self._log(mensaje)
        self.estado.setText("No se pudo iniciar la instalación.")
        QMessageBox.warning(self, "No se pudo instalar", mensaje)

    def _reiniciando(self, texto):
        """El equipo acaba de reiniciarse solo: soltar el puerto y explicarlo."""
        self._desconectar()
        self.estado.setText(texto)
        self._log(texto)
        QMessageBox.information(self, "Equipo reiniciándose", texto)

    # ── Restablecer de fábrica ──────────────────────────────────────────
    def _restablecer(self):
        """FORMAT. No se pide escribir el nombre de la estación: el cable USB es
        local y la ventana ya muestra con qué equipo se habla. El nombre se le
        manda al equipo solo, porque el firmware lo exige como confirmación."""
        nombre = self.equipo.info.estacion
        r = QMessageBox.question(
            self, "Restablecer de fábrica",
            f"Se va a BORRAR TODO lo guardado en «{nombre}»:\n"
            "programa, tablas, registros y log.\n\n"
            "El firmware no se toca. Esta acción no se puede deshacer.\n"
            "¿Ya descargaste los registros que necesitas?\n\n¿Continuar?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        self.estado.setText("Borrando… (puede tardar unos segundos)")
        self.barra.setMaximum(0)          # barra «ocupado»: no hay porcentaje
        self._correr(lambda t: self.equipo.restablecer(), self._restablecido,
                     self._restablecer_fallo)

    def _restablecer_fallo(self, mensaje):
        mensaje = _texto_error(mensaje)
        self.barra.setMaximum(1)
        self.barra.setValue(0)
        self._log(mensaje)
        self.estado.setText("No se pudo restablecer el equipo.")
        QMessageBox.warning(self, "No se pudo restablecer", mensaje)

    def _restablecido(self, res):
        self.barra.setMaximum(1)
        self.barra.setValue(0)
        if res.get("estado") == "OK":
            self._reiniciando(
                "Equipo restablecido. Se está reiniciando: espera unos 30 segundos y "
                "conecta de nuevo. Después puedes cargarle el firmware o un programa.")
            return
        self._log(f"restablecer: {res}")
        self._desconectar()
        texto = (f"El borrado fue parcial (datos: {'ok' if res.get('datos') else 'falló'}, "
                 f"partición de actualización: {'ok' if res.get('ota') else 'falló'}). "
                 "Si persiste, usa QSPIFormat desde el Arduino IDE.")
        self.estado.setText(texto)
        QMessageBox.warning(self, "Borrado parcial", texto)

    def _refrescar(self):
        if self.equipo is not None and not self._ocupado():
            self._correr(lambda t: self.equipo.leer_tablas(), self._tablas_leidas)

    def done(self, resultado):
        self._desconectar()
        super().done(resultado)
