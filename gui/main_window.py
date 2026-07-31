"""Ventana principal del IDE."""

import os

from PyQt5.QtCore import QSettings, Qt, QTimer
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from optabasic import analyze, limits as L
from optabasic.encoding import (
    aplicar_fin_de_linea,
    codificar,
    decodificar,
    detectar_fin_de_linea,
)

from .deploy import DialogoEnvio
from .editor import EditorCRBasic
from .highlighter import Paleta
from .panels import PanelHardware, PanelHlog, PanelProblemas, PanelRecursos
from .reference_panel import PanelReferencia
from .snippets import PLANTILLAS, PROGRAMA_NUEVO

RETARDO_ANALISIS_MS = 350


class VentanaPrincipal(QMainWindow):
    def __init__(self):
        super().__init__()
        self.ruta: "str | None" = None
        self.codificacion = "cp1252"
        self.fin_linea = "\r\n"
        self.resultado = None
        self.oscuro = False

        self.setWindowTitle("IDE OptaBasic")
        self.resize(1180, 820)

        self.editor = EditorCRBasic()
        self.editor.textChanged.connect(self._programar_analisis)
        self.editor.cursor_movido.connect(self._mostrar_posicion)
        self.editor.ayuda_pedida.connect(self.mostrar_ayuda_de)

        self.panel_problemas = PanelProblemas()
        self.panel_problemas.ir_a_linea.connect(self.editor.ir_a_linea)
        self.panel_recursos = PanelRecursos()
        self.panel_hardware = PanelHardware()
        self.panel_hlog = PanelHlog()
        self.panel_referencia = PanelReferencia()
        self.panel_referencia.insertar_ejemplo.connect(self._insertar)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self.panel_problemas, "Problemas")
        self.tabs.addTab(self.panel_recursos, "Recursos")
        self.tabs.addTab(self.panel_hardware, "Hardware")
        self.tabs.addTab(self.panel_hlog, "Log del equipo")
        self.tabs.addTab(self.panel_referencia, "Referencia")
        self.IDX_REFERENCIA = 4

        self.divisor = QSplitter(Qt.Vertical)
        self.divisor.addWidget(self.editor)
        self.divisor.addWidget(self.tabs)
        self.divisor.setStretchFactor(0, 3)
        self.divisor.setStretchFactor(1, 1)
        self.divisor.setSizes([560, 260])
        self.tabs.currentChanged.connect(self._al_cambiar_pestania)

        central = QWidget()
        caja = QVBoxLayout(central)
        caja.setContentsMargins(0, 0, 0, 0)
        caja.addWidget(self.divisor)
        self.setCentralWidget(central)

        self._crear_acciones()
        self._crear_barra_estado()

        self.temporizador = QTimer(self)
        self.temporizador.setSingleShot(True)
        self.temporizador.timeout.connect(self.analizar)

        self.editor.setPlainText(PROGRAMA_NUEVO)
        self.analizar()
        self.editor.document().setModified(False)
        self._actualizar_titulo()

    # ── Menús y acciones ────────────────────────────────────────────────
    def _accion(self, texto, slot, atajo=None, estado=None):
        a = QAction(texto, self)
        a.triggered.connect(slot)
        if atajo:
            a.setShortcut(QKeySequence(atajo))
        if estado:
            a.setStatusTip(estado)
        return a

    def _crear_acciones(self):
        barra = self.menuBar()

        archivo = barra.addMenu("&Archivo")
        archivo.addAction(self._accion("&Nuevo", self.nuevo, "Ctrl+N"))
        archivo.addAction(self._accion("&Abrir…", self.abrir, "Ctrl+O"))
        archivo.addSeparator()
        archivo.addAction(self._accion("&Guardar", self.guardar, "Ctrl+S"))
        archivo.addAction(self._accion("Guardar &como…", self.guardar_como, "Ctrl+Shift+S"))
        archivo.addSeparator()
        archivo.addAction(self._accion("&Salir", self.close, "Alt+F4"))

        editar = barra.addMenu("&Editar")
        editar.addAction(self._accion("Des&hacer", self.editor.undo, "Ctrl+Z"))
        editar.addAction(self._accion("&Rehacer", self.editor.redo, "Ctrl+Y"))
        editar.addSeparator()
        editar.addAction(self._accion("Cor&tar", self.editor.cut, "Ctrl+X"))
        editar.addAction(self._accion("&Copiar", self.editor.copy, "Ctrl+C"))
        editar.addAction(self._accion("&Pegar", self.editor.paste, "Ctrl+V"))
        editar.addSeparator()
        editar.addAction(self._accion("Autocompletar", self._forzar_completado, "Ctrl+Space"))

        insertar = barra.addMenu("&Insertar")
        for titulo, cuerpo in PLANTILLAS:
            if titulo is None:
                insertar.addSeparator()
                continue
            insertar.addAction(
                self._accion(titulo, lambda _=False, t=cuerpo: self._insertar(t))
            )

        equipo = barra.addMenu("&Equipo")
        equipo.addAction(self._accion("&Validar programa", self.analizar, "F5"))
        equipo.addSeparator()
        equipo.addAction(self._accion("&Enviar al equipo…", self.enviar, "F9"))

        ver = barra.addMenu("&Ver")
        ver.addAction(self._accion("Alternar tema &oscuro", self.alternar_tema, "Ctrl+D"))
        ver.addSeparator()
        ver.addAction(self._accion("Ir a &problemas", lambda: self.tabs.setCurrentIndex(0), "Ctrl+1"))
        ver.addAction(self._accion("Ir a &recursos", lambda: self.tabs.setCurrentIndex(1), "Ctrl+2"))
        ver.addAction(self._accion("Ir a &hardware", lambda: self.tabs.setCurrentIndex(2), "Ctrl+3"))
        ver.addAction(self._accion("Ir al &log del equipo", lambda: self.tabs.setCurrentIndex(3), "Ctrl+4"))
        ver.addAction(self._accion("Ir a la r&eferencia", self.abrir_referencia, "Ctrl+5"))

        ayuda = barra.addMenu("A&yuda")
        ayuda.addAction(self._accion(
            "&Referencia de instrucciones", self.abrir_referencia))
        ayuda.addAction(self._accion(
            "Ayuda de la palabra bajo el cursor",
            lambda: self.mostrar_ayuda_de(self.editor.palabra_bajo_cursor()), "F1"))
        ayuda.addSeparator()
        ayuda.addAction(self._accion("&Límites del dialecto", self.mostrar_limites))
        ayuda.addAction(self._accion("&Acerca de", self.acerca_de))

    def _crear_barra_estado(self):
        self.lbl_posicion = QLabel("L1, C1")
        self.lbl_tamano = QLabel()
        self.lbl_diagnosticos = QLabel()
        self.lbl_codificacion = QLabel(self.codificacion)
        for w in (self.lbl_diagnosticos, self.lbl_tamano, self.lbl_codificacion,
                  self.lbl_posicion):
            self.statusBar().addPermanentWidget(w)
        self.statusBar().showMessage("Listo")

    # ── Análisis ────────────────────────────────────────────────────────
    def _programar_analisis(self):
        self.temporizador.start(RETARDO_ANALISIS_MS)
        self._actualizar_titulo()

    def bytes_a_enviar(self) -> bytes:
        """El archivo exacto que se va a guardar y subir al equipo."""
        texto = aplicar_fin_de_linea(self.editor.toPlainText(), self.fin_linea)
        return codificar(texto, self.codificacion)

    def analizar(self):
        texto = self.editor.toPlainText()
        self.resultado = analyze(texto, size_bytes=len(self.bytes_a_enviar()))

        self.panel_problemas.actualizar(self.resultado)
        self.panel_recursos.actualizar(self.resultado)
        self.panel_hardware.actualizar(self.resultado)
        self.panel_hlog.actualizar(self.resultado)
        self.editor.marcar_diagnosticos(self.resultado.diagnostics)

        self.editor.actualizar_diccionario(self._declarados())

        c = self.resultado.diagnostics.counts()
        self.lbl_diagnosticos.setText(
            f"⛔ {c['error']}   ⚠ {c['warning']}   ℹ {c['info']}"
        )
        color = "#cf222e" if c["error"] else "#9a6700" if c["warning"] else "#1a7f37"
        self.lbl_diagnosticos.setStyleSheet(f"color: {color}; font-weight: 600;")

        usado = self.resultado.program.size_bytes
        self.lbl_tamano.setText(f"{usado} / {L.MAX_PROG_BYTES} bytes")
        self.lbl_tamano.setStyleSheet(
            "color: #cf222e; font-weight: 600;" if usado > L.MAX_PROG_BYTES else ""
        )

    def _declarados(self) -> "list[tuple[str, str]]":
        """Variables y constantes del programa, con qué es cada una.

        Sirve para que el desplegable diga «Nivel_mA — sensor 4-20mA en A0»
        en vez de solo el nombre: quien escribe el programa no tiene por qué
        recordar qué borne le tocó a cada variable.
        """
        salida = []
        for v in self.resultado.program.vars:
            if v.is_relay:
                detalle = f"relé DO{v.relay_idx + 1}"
            elif v.is_pulse_count:
                detalle = f"contador de pulsos en A{v.pulse_pin}"
            elif v.pin >= 0:
                detalle = f"{v.kind.lower()} en A{v.pin}"
            elif v.assigned_lines:
                detalle = "variable calculada"
            else:
                detalle = "variable"
            salida.append((v.name, detalle))
        for c in self.resultado.program.consts:
            salida.append((c.name, f"constante = {c.value:g}"))
        return salida

    def _mostrar_posicion(self, linea, columna):
        aviso = "  ⚠ pasa de 127" if columna > L.MAX_LINE_LEN else ""
        self.lbl_posicion.setText(f"L{linea}, C{columna}{aviso}")

    # ── Archivos ────────────────────────────────────────────────────────
    def _confirmar_descarte(self) -> bool:
        if not self.editor.document().isModified():
            return True
        r = QMessageBox.question(
            self, "Cambios sin guardar",
            "El programa tiene cambios sin guardar. ¿Querés guardarlos?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if r == QMessageBox.Save:
            return self.guardar()
        return r == QMessageBox.Discard

    def nuevo(self):
        if not self._confirmar_descarte():
            return
        self.ruta = None
        self.codificacion = "cp1252"
        self.editor.setPlainText(PROGRAMA_NUEVO)
        self.editor.document().setModified(False)
        self.analizar()
        self._actualizar_titulo()

    def abrir(self):
        if not self._confirmar_descarte():
            return
        ruta, _ = QFileDialog.getOpenFileName(
            self, "Abrir programa", "", "Programas CRBasic (*.CR1 *.cr1 *.CR1X);;Todos (*)"
        )
        if not ruta:
            return
        with open(ruta, "rb") as fh:
            texto, enc = decodificar(fh.read())
        self.ruta = ruta
        self.codificacion = enc
        self.fin_linea = detectar_fin_de_linea(texto)
        self.lbl_codificacion.setText(enc)
        self.editor.setPlainText(texto)
        self.editor.document().setModified(False)
        self.analizar()
        self._actualizar_titulo()
        self.statusBar().showMessage(f"Abierto {ruta} ({enc})", 5000)

    def guardar(self) -> bool:
        if not self.ruta:
            return self.guardar_como()
        datos = self.bytes_a_enviar()
        with open(self.ruta, "wb") as fh:
            fh.write(datos)
        self.editor.document().setModified(False)
        self._actualizar_titulo()
        self.statusBar().showMessage(f"Guardado {self.ruta} ({len(datos)} bytes)", 5000)
        return True

    def guardar_como(self) -> bool:
        ruta, _ = QFileDialog.getSaveFileName(
            self, "Guardar programa", self.ruta or "programa.CR1",
            "Programas CRBasic (*.CR1);;Todos (*)"
        )
        if not ruta:
            return False
        self.ruta = ruta
        return self.guardar()

    # ── Envío al equipo ─────────────────────────────────────────────────
    def enviar(self):
        self.analizar()
        c = self.resultado.diagnostics.counts()
        if c["error"]:
            r = QMessageBox.warning(
                self, "El programa tiene errores",
                f"El análisis encontró {c['error']} errores. El equipo va a aceptar "
                "el archivo igual, pero va a descartar en silencio las líneas "
                "afectadas.\n\n¿Enviar de todos modos?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if r != QMessageBox.Yes:
                self.tabs.setCurrentIndex(0)
                return

        datos = self.bytes_a_enviar()
        if len(datos) > L.MAX_PROG_BYTES:
            QMessageBox.critical(
                self, "El programa no entra",
                f"El archivo ocupa {len(datos)} bytes y el equipo solo almacena "
                f"{L.MAX_PROG_BYTES}. Lo que exceda no se guarda: acortá comentarios "
                "o dividí el programa antes de enviarlo.",
            )
            return

        nombre = os.path.basename(self.ruta) if self.ruta else "programa.CR1"
        DialogoEnvio(datos, nombre, self).exec_()

    # ── Varios ──────────────────────────────────────────────────────────
    def _insertar(self, texto: str):
        cursor = self.editor.textCursor()
        cursor.insertText(texto)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()

    def _al_cambiar_pestania(self, indice: int):
        """La referencia necesita espacio; los otros paneles no tanto."""
        arriba, abajo = self.divisor.sizes()
        if indice == self.IDX_REFERENCIA and abajo < 400:
            total = arriba + abajo
            objetivo = min(460, int(total * 0.62))
            self.divisor.setSizes([total - objetivo, objetivo])

    def abrir_referencia(self):
        self.tabs.setCurrentIndex(self.IDX_REFERENCIA)

    def mostrar_ayuda_de(self, palabra: str):
        """F1: abre la ficha de la instrucción donde está el cursor."""
        if palabra and self.panel_referencia.mostrar(palabra):
            self.abrir_referencia()
            return
        self.abrir_referencia()
        self.panel_referencia.busqueda.setText(palabra or "")
        self.panel_referencia.busqueda.setFocus()
        if palabra:
            self.statusBar().showMessage(
                f"«{palabra}» no es una instrucción del Opta — te dejo la búsqueda "
                "abierta por si es otra cosa.", 6000)

    def _forzar_completado(self):
        self.editor.setFocus()

    def alternar_tema(self):
        self.oscuro = not self.oscuro
        paleta = Paleta.OSCURA if self.oscuro else Paleta.CLARA
        self.editor.aplicar_paleta(paleta)
        QSettings("OptaBasic", "IDE").setValue("oscuro", self.oscuro)

    def _actualizar_titulo(self):
        nombre = os.path.basename(self.ruta) if self.ruta else "sin título"
        marca = "• " if self.editor.document().isModified() else ""
        self.setWindowTitle(f"{marca}{nombre} — IDE OptaBasic")

    def mostrar_limites(self):
        QMessageBox.information(
            self, "Límites del dialecto",
            f"Programa: {L.MAX_PROG_BYTES} bytes\n"
            f"Línea: {L.MAX_LINE_LEN} caracteres\n"
            f"Argumentos: {L.MAX_ARGS}, de {L.MAX_ARG_LEN} caracteres cada uno\n"
            f"Variables: {L.MAX_VARS}   Constantes: {L.MAX_CONSTS}\n"
            f"Tablas: {L.MAX_TABLES}   Campos por tabla: {L.MAX_FIELDS}\n"
            f"Instrucciones: {L.MAX_STMTS}   Tokens por expresión: {L.MAX_EXPR_TOKENS}\n"
            f"Anidamiento de If: {L.IF_MAX_DEPTH} niveles\n\n"
            "Funciones disponibles: Abs, Int y Sqr. No hay Sin, Cos, Ln, Exp ni Mod.\n"
            "Tampoco hay bucles, subrutinas, arreglos ni cadenas de texto.",
        )

    def acerca_de(self):
        QMessageBox.about(
            self, "Acerca de",
            "<b>IDE OptaBasic</b><br><br>"
            "Editor y validador de CRBasic-lite para Arduino Opta con firmware "
            "OptaPakBus.<br><br>"
            "El validador es un port en Python del parser embebido en el firmware "
            "(parse_crbasic / cr_compile_expr), así que reproduce exactamente qué "
            "líneas va a aceptar el equipo y cuáles va a descartar sin avisar.",
        )

    def closeEvent(self, evento):
        if self._confirmar_descarte():
            evento.accept()
        else:
            evento.ignore()


def main():
    import sys

    app = QApplication(sys.argv)
    app.setApplicationName("IDE OptaBasic")
    ventana = VentanaPrincipal()
    ventana.show()
    sys.exit(app.exec_())
