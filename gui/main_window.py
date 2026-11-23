"""Ventana principal del IDE."""

import os
import re

from PyQt5.QtCore import QSettings, Qt, QTimer
from PyQt5.QtGui import QKeySequence, QTextCursor
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from optabasic import __version__, analyze, limits as L
from optabasic.encoding import (
    aplicar_fin_de_linea,
    codificar,
    decodificar,
    detectar_fin_de_linea,
)

from . import tema
from .cinta import Cinta
from .deploy import DialogoEnvio
from .usb_dialog import DialogoUSB
from .editor import EditorCRBasic
from .highlighter import Paleta
from .panels import PanelHardware, PanelHlog, PanelProblemas, PanelRecursos
from .reference_panel import PanelReferencia
from .sensor_wizard import AsistenteSensor
from .snippets import PLANTILLAS, PROGRAMA_NUEVO

RETARDO_ANALISIS_MS = 350



def _num_const(valor: float) -> str:
    """Número de una constante: sin ceros de relleno ni notación científica."""
    texto = f"{valor:.5f}".rstrip("0").rstrip(".")
    return texto if texto not in ("", "-") else "0.0"

class VentanaPrincipal(QMainWindow):
    def __init__(self):
        super().__init__()
        self.ruta: "str | None" = None
        self.codificacion = "cp1252"
        self.fin_linea = "\r\n"
        self.resultado = None
        self.oscuro = False
        self._acciones = {}        # nombre sin & ni «…» -> QAction, para la cinta

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
        caja.setSpacing(0)
        self.caja_central = caja
        caja.addWidget(self.divisor, 1)
        self.setCentralWidget(central)

        self._crear_acciones()
        self._crear_cinta()
        self._crear_barra_estado()

        self.temporizador = QTimer(self)
        self.temporizador.setSingleShot(True)
        self.temporizador.timeout.connect(self.analizar)

        self.editor.setPlainText(PROGRAMA_NUEVO)
        self.analizar()
        self.editor.document().setModified(False)
        self._actualizar_titulo()
        self._aplicar_tema(QSettings("OptaBasic", "IDE").value("oscuro", False,
                                                               type=bool))

    # ── Menús y acciones ────────────────────────────────────────────────
    def _accion(self, texto, slot, atajo=None, estado=None):
        a = QAction(texto, self)
        a.triggered.connect(slot)
        self._acciones[texto.replace("&", "").replace("…", "").strip()] = a
        # En la ventana misma, para que el atajo ande aunque el menú esté oculto.
        self.addAction(a)
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
        insertar.addAction(self._accion(
            "&Asistente de sensores…", self.abrir_asistente, "Ctrl+M",
            "Calcula Mult y Offset de un sensor 4-20 mA o de un contador de pulsos"))
        insertar.addSeparator()
        self._llenar_plantillas(insertar)

        equipo = barra.addMenu("&Equipo")
        equipo.addAction(self._accion("&Validar programa", self.analizar, "F5"))
        equipo.addSeparator()
        equipo.addAction(self._accion("&Enviar al equipo…", self.enviar, "F9"))
        equipo.addAction(self._accion(
            "Rescate por &USB…", self.abrir_usb, "Ctrl+U",
            "Bajar los registros, cargar el programa o un firmware nuevo y "
            "restablecer el equipo por cable USB-C"))
        equipo.addAction(self._accion(
            "Variables en vi&vo (USB)…", self.abrir_variables, "Ctrl+Shift+U",
            "Ver los valores que tiene el equipo ahora por cable USB-C, sin "
            "servidor (solo lectura)"))

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

    def _llenar_plantillas(self, menu):
        for titulo, cuerpo in PLANTILLAS:
            if titulo is None:
                menu.addSeparator()
                continue
            menu.addAction(
                self._accion(titulo, lambda _=False, t=cuerpo: self._insertar(t))
            )

    def _crear_cinta(self):
        """Cinta de opciones: agrupa las acciones que ya existen."""
        cinta = Cinta(self._acciones)

        inicio = cinta.pagina("Inicio")
        g = inicio.grupo("Archivo")
        for n in ("Nuevo", "Abrir", "Guardar", "Guardar como"):
            g.agregar(cinta.boton(n))
        g = inicio.grupo("Edición")
        g.agregar_columna([cinta.boton(n, grande=False)
                           for n in ("Deshacer", "Rehacer")])
        g.agregar_columna([cinta.boton(n, grande=False)
                           for n in ("Cortar", "Copiar", "Pegar")])
        g = inicio.grupo("Programa")
        g.agregar(cinta.boton("Validar programa"))
        g.agregar(cinta.boton("Autocompletar"))

        insertar = cinta.pagina("Insertar")
        g = insertar.grupo("Sensores")
        g.agregar(cinta.boton("Asistente de sensores"))
        g = insertar.grupo("Plantillas")
        self.menu_plantillas = QMenu(self)
        self._llenar_plantillas(self.menu_plantillas)
        g.agregar(cinta.boton("Plantillas", menu=self.menu_plantillas))

        equipo = cinta.pagina("Equipo")
        g = equipo.grupo("Programa")
        g.agregar(cinta.boton("Validar programa"))
        g.agregar(cinta.boton("Enviar al equipo"))
        g = equipo.grupo("Cable USB")
        g.agregar(cinta.boton("Rescate por USB"))
        g.agregar(cinta.boton("Variables en vivo (USB)"))

        vista = cinta.pagina("Vista")
        g = vista.grupo("Aspecto")
        g.agregar(cinta.boton("Alternar tema oscuro"))
        g = vista.grupo("Paneles")
        for n in ("Ir a problemas", "Ir a recursos", "Ir a hardware",
                  "Ir al log del equipo", "Ir a la referencia"):
            g.agregar(cinta.boton(n))

        ayuda = cinta.pagina("Ayuda")
        g = ayuda.grupo("Ayuda")
        for n in ("Referencia de instrucciones",
                  "Ayuda de la palabra bajo el cursor",
                  "Límites del dialecto", "Acerca de"):
            g.agregar(cinta.boton(n))

        self.cinta = cinta
        self.caja_central.insertWidget(0, cinta)
        self.menuBar().setVisible(False)       # la cinta ocupa su lugar

    def _aplicar_tema(self, oscuro: bool):
        self.oscuro = oscuro
        tema.aplicar(QApplication.instance(), oscuro)
        self.editor.aplicar_paleta(Paleta.OSCURA if oscuro else Paleta.CLARA)
        self.cinta.repintar_iconos(oscuro)
        self._acciones["Alternar tema oscuro"].setText(
            "Tema claro" if oscuro else "Tema oscuro")
        self.analizar()

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
            if v.is_pulse_count:
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
            self._padre(), "Guardar programa", self.ruta or "programa.CR1",
            "Programas CRBasic (*.CR1);;Todos (*)"
        )
        if not ruta:
            return False
        self.ruta = ruta
        return self.guardar()

    # ── Envío al equipo ─────────────────────────────────────────────────
    def enviar(self):
        listo = self._programa_para_enviar()
        if listo is not None:
            DialogoEnvio(listo[0], listo[1], self).exec_()

    def abrir_usb(self):
        """Rescate por USB: bajar registros y cargar el programa del editor."""
        def programa():
            listo = self._programa_para_enviar()
            return listo if listo is not None else (None, None)
        DialogoUSB(programa, self.abrir_desde_equipo, self).exec_()

    def abrir_variables(self):
        """Variables en vivo por USB (solo lectura), con su propia conexión."""
        from .variables_dialog import DialogoVariables
        DialogoVariables(parent=self).exec_()

    def abrir_desde_equipo(self, datos: bytes, nombre: str) -> bool:
        """Pone en el editor el programa que se leyó del equipo. Devuelve
        False si el usuario prefirió conservar lo que tenía abierto."""
        if not self._confirmar_descarte():
            return False
        texto, enc = decodificar(datos)
        self.ruta = None                     # no es un archivo de disco todavía
        self.codificacion = enc
        self.fin_linea = detectar_fin_de_linea(texto)
        self.lbl_codificacion.setText(enc)
        self.editor.setPlainText(texto)
        self.editor.document().setModified(True)   # pide guardar al salir
        self.analizar()
        self._actualizar_titulo()
        self.statusBar().showMessage(
            f"Programa del equipo ({nombre}, {len(datos)} bytes) abierto en el "
            "editor: guardalo para conservarlo.", 8000)
        return True

    def _padre(self):
        """Ventana sobre la que abrir avisos: la modal que esté arriba (el
        diálogo del USB, por ejemplo) y si no, la principal. Con la principal
        de padre un aviso podía quedar tapado por el diálogo."""
        return QApplication.activeModalWidget() or self

    def _programa_para_enviar(self):
        """Deja el programa listo para mandarlo al equipo y devuelve
        (bytes, nombre), o None si no se puede o el usuario desistió.

        Antes de enviar, por servidor o por USB, el programa tiene que estar
        sin errores y guardado en disco: así lo que llega al equipo es
        exactamente un archivo que existe y que se revisó. El equipo en
        cambio acepta un programa con errores y descarta en silencio las
        líneas malas, de ahí que acá no se pueda enviar «de todos modos».
        """
        padre = self._padre()
        self.analizar()
        c = self.resultado.diagnostics.counts()
        if c["error"]:
            QMessageBox.critical(
                padre, "No se puede enviar",
                f"El programa tiene {c['error']} error(es) y no se envía así: el "
                "equipo descartaría en silencio las líneas afectadas.\n\n"
                "Corregilos (están marcados en la pestaña Problemas) y volvé a "
                "intentar.",
            )
            self.tabs.setCurrentIndex(0)
            return None

        if self.ruta is None or self.editor.document().isModified():
            if self.ruta is None:
                motivo = "El programa todavía no está guardado en un archivo."
            else:
                motivo = "El programa tiene cambios sin guardar."
            r = QMessageBox.question(
                padre, "Guardar antes de enviar",
                f"{motivo} Hay que guardarlo antes de enviarlo, para que lo que "
                "llega al equipo sea el archivo que quedó en el disco.\n\n"
                "¿Guardarlo ahora?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
            )
            if r != QMessageBox.Yes or not self.guardar():
                return None

        datos = self.bytes_a_enviar()
        if len(datos) > L.MAX_PROG_BYTES:
            QMessageBox.critical(
                padre, "El programa no entra",
                f"El archivo ocupa {len(datos)} bytes y el equipo solo almacena "
                f"{L.MAX_PROG_BYTES}. Lo que exceda no se guarda: acortá comentarios "
                "o dividí el programa antes de enviarlo.",
            )
            return None

        return datos, os.path.basename(self.ruta)

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

    def abrir_asistente(self):
        """Ofrece los bornes que todavía están libres en el programa actual."""
        ocupados = set()
        for v in self.resultado.program.vars:
            if v.pin >= 0:
                ocupados.add(v.pin + 1)
            if v.is_pulse_count and v.pulse_pin >= 0:
                ocupados.add(v.pulse_pin + 1)
        libres = [c for c in range(1, L.N_ANALOG + 1) if c not in ocupados]

        dialogo = AsistenteSensor(
            canales_libres=libres,
            scan_seg=self.resultado.program.scan_seconds,
            parent=self,
        )
        dialogo.insertar.connect(self._insertar_bloque)
        dialogo.aplicar.connect(self._aplicar_constantes)
        dialogo.exec_()

    def _aplicar_constantes(self, valores: dict):
        """Cambia el valor de `Const NOMBRE = x` en el programa abierto.

        Respeta el comentario de la línea. Las constantes que el programa no
        tiene se insertan donde está el cursor, para que no se pierdan.
        """
        patron = re.compile(r"^(\s*Const\s+)(\w+)(\s*=\s*)(-?[\d.]+)(.*)$", re.I)
        por_nombre = {n.lower(): (n, v) for n, v in valores.items()}
        cambiadas = []
        cur = self.editor.textCursor()
        cur.beginEditBlock()
        bloque = self.editor.document().begin()
        while bloque.isValid():
            m = patron.match(bloque.text())
            if m and m.group(2).lower() in por_nombre:
                nombre, valor = por_nombre.pop(m.group(2).lower())
                texto = f"{m.group(1)}{m.group(2)}{m.group(3)}{_num_const(valor)}{m.group(5)}"
                c = QTextCursor(bloque)
                c.select(QTextCursor.LineUnderCursor)
                c.insertText(texto)
                cambiadas.append(nombre)
            bloque = bloque.next()
        cur.endEditBlock()
        if por_nombre:
            lineas = [f"Const {n} = {_num_const(v)}" for n, v in por_nombre.values()]
            self._insertar_bloque(chr(10).join(lineas) + chr(10))
        self.analizar()
        partes = []
        if cambiadas:
            partes.append("Actualicé " + ", ".join(cambiadas))
        if por_nombre:
            partes.append("Agregué " + ", ".join(n for n, _ in por_nombre.values())
                          + " (no estaban en el programa)")
        self.statusBar().showMessage(". ".join(partes) + ".", 8000)

    def _insertar_bloque(self, texto: str):
        """Inserta el código del asistente al principio de una línea nueva."""
        cursor = self.editor.textCursor()
        cursor.movePosition(cursor.EndOfBlock)
        prefijo = "" if not cursor.block().text().strip() else "\n"
        cursor.insertText(prefijo + "\n" + texto)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()
        self.analizar()

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
        self.editor.forzar_completado()

    def alternar_tema(self):
        self._aplicar_tema(not self.oscuro)
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
            f"<b>IDE OptaBasic</b> — versión {__version__}<br><br>"
            "Editor y validador de CRBasic-lite para Arduino Opta con firmware "
            "OptaPakBus.<br><br>"
            "El validador es un port en Python del parser embebido en el firmware "
            "(parse_crbasic / cr_compile_expr), así que reproduce exactamente qué "
            "líneas va a aceptar el equipo y cuáles va a descartar sin avisar.<br><br>"
            "Desarrollado por <b>Ingeniería y Proyecto Ltda.</b>",
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
