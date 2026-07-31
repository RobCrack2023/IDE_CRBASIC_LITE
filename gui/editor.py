"""Editor de código: numeración, marcas de diagnóstico y autocompletado."""

from PyQt5.QtCore import QRect, QSize, QStringListModel, Qt, pyqtSignal
from PyQt5.QtGui import (
    QColor,
    QFont,
    QPainter,
    QTextCursor,
    QTextFormat,
)
from PyQt5.QtWidgets import (
    QCompleter,
    QFrame,
    QLabel,
    QPlainTextEdit,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

SEPARADOR = "  —  "   # entre el nombre y su descripción en el autocompletado

from optabasic.limits import MAX_LINE_LEN
from optabasic.reference import buscar, contexto_llamada

from .highlighter import (
    DECLARACION,
    DIRECTIVAS,
    ESTRUCTURA,
    FUNCIONES,
    INSTRUCCIONES,
    LITERALES,
    CRBasicHighlighter,
    Paleta,
)

_PALABRAS_BASE = sorted(
    set(ESTRUCTURA + DECLARACION + INSTRUCCIONES + DIRECTIVAS + FUNCIONES + LITERALES)
)


class _Margen(QWidget):
    """Franja izquierda con los números de línea."""

    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.ancho_margen(), 0)

    def paintEvent(self, evento):
        self.editor.pintar_margen(evento)


class AyudaDeFirma(QFrame):
    """Cartel flotante que explica el argumento que se está escribiendo.

    Aparece solo al abrir un paréntesis y se mueve de argumento a medida
    que se escriben las comas. Está pensado para que no haya que
    acordarse del orden de nueve argumentos ni de cuáles el equipo ignora.
    """

    def __init__(self, parent=None):
        super().__init__(parent, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setFrameShape(QFrame.StyledPanel)
        self.etiqueta = QLabel(self)
        self.etiqueta.setTextFormat(Qt.RichText)
        self.etiqueta.setWordWrap(True)
        self.etiqueta.setMaximumWidth(560)
        caja = QVBoxLayout(self)
        caja.setContentsMargins(10, 8, 10, 8)
        caja.addWidget(self.etiqueta)
        self.setStyleSheet(
            "QFrame { background: #fffbe6; border: 1px solid #d4a72c;"
            " border-radius: 4px; }"
            "QLabel { background: transparent; color: #24292f; }"
        )
        self.hide()

    def mostrar(self, instr, indice: int, punto) -> None:
        partes = instr.firma_partes()
        if not partes:
            self.hide()
            return

        resaltados = []
        for i, parte in enumerate(partes):
            if i == indice:
                resaltados.append(f"<b><u>{parte}</u></b>")
            else:
                resaltados.append(f"<span style='color:#57606a'>{parte}</span>")
        firma = f"<b>{instr.nombre}</b>(" + ", ".join(resaltados) + ")"

        lineas = [firma]
        if 0 <= indice < len(instr.parametros):
            p = instr.parametros[indice]
            marca = ""
            if p.ignorado:
                marca = ("<span style='color:#bc4c00'> · el Opta lo acepta pero "
                         "no lo usa</span>")
            elif p.opcional:
                marca = "<span style='color:#57606a'> · opcional</span>"
            lineas.append(f"<b>{p.nombre}</b>: {p.descripcion}{marca}")
        elif indice >= len(partes):
            lineas.append(
                f"<span style='color:#bc4c00'>Esta instrucción recibe "
                f"{len(partes)} argumentos; los de más se descartan.</span>"
            )
        else:
            lineas.append(f"<span style='color:#57606a'>{instr.resumen}</span>")

        self.etiqueta.setText("<br>".join(lineas))
        self.adjustSize()
        self.move(punto)
        self.show()


class EditorCRBasic(QPlainTextEdit):
    """QPlainTextEdit con lo mínimo que hace falta para escribir CRBasic."""

    cursor_movido = pyqtSignal(int, int)   # línea, columna
    ayuda_pedida = pyqtSignal(str)         # F1 sobre una palabra

    def __init__(self, parent=None):
        super().__init__(parent)
        self.colores = Paleta.CLARA
        self.margen = _Margen(self)
        self.highlighter = CRBasicHighlighter(self.document(), self.colores)
        self._marcas: "dict[int, str]" = {}     # línea (1-based) → severidad
        self._mensajes: "dict[int, list[str]]" = {}

        fuente = QFont("Consolas", 11)
        fuente.setStyleHint(QFont.Monospace)
        fuente.setFixedPitch(True)
        self.setFont(fuente)
        self.setTabStopWidth(4 * self.fontMetrics().width(" "))
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setMouseTracking(True)

        self.completer = QCompleter(self)
        self.completer.setWidget(self)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.setCompletionMode(QCompleter.PopupCompletion)
        self.completer.activated[str].connect(self._insertar_completado)
        self.ayuda_firma = AyudaDeFirma(self)
        self.actualizar_diccionario([])

        self.blockCountChanged.connect(self._ajustar_margen)
        self.updateRequest.connect(self._refrescar_margen)
        self.cursorPositionChanged.connect(self._al_mover_cursor)
        self._ajustar_margen()
        self.aplicar_paleta(self.colores)

    # ── Paleta ──────────────────────────────────────────────────────────
    def aplicar_paleta(self, colores: dict) -> None:
        self.colores = colores
        self.setStyleSheet(
            f"QPlainTextEdit {{ background: {colores['fondo']}; color: {colores['texto']};"
            f" border: none; selection-background-color: #3d7eff;"
            f" selection-color: white; }}"
        )
        self.highlighter.cambiar_paleta(colores)
        self._repintar_marcas()

    # ── Margen de números ───────────────────────────────────────────────
    def ancho_margen(self) -> int:
        digitos = max(2, len(str(max(1, self.blockCount()))))
        return 14 + self.fontMetrics().width("9") * digitos

    def _ajustar_margen(self, _=0):
        self.setViewportMargins(self.ancho_margen(), 0, 0, 0)

    def _refrescar_margen(self, rect, dy):
        if dy:
            self.margen.scroll(0, dy)
        else:
            self.margen.update(0, rect.y(), self.margen.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._ajustar_margen()

    def resizeEvent(self, evento):
        super().resizeEvent(evento)
        cr = self.contentsRect()
        self.margen.setGeometry(QRect(cr.left(), cr.top(), self.ancho_margen(), cr.height()))

    def pintar_margen(self, evento):
        c = self.colores
        pintor = QPainter(self.margen)
        pintor.fillRect(evento.rect(), QColor(c["margen"]))

        bloque = self.firstVisibleBlock()
        numero = bloque.blockNumber()
        top = self.blockBoundingGeometry(bloque).translated(self.contentOffset()).top()
        bottom = top + self.blockBoundingRect(bloque).height()
        actual = self.textCursor().blockNumber()

        while bloque.isValid() and top <= evento.rect().bottom():
            if bloque.isVisible() and bottom >= evento.rect().top():
                linea = numero + 1
                sev = self._marcas.get(linea)
                if sev:
                    pintor.setPen(QColor({"error": "#cf222e", "warning": "#bf8700",
                                          "info": "#0969da"}[sev]))
                    pintor.drawText(0, int(top), 12, self.fontMetrics().height(),
                                    Qt.AlignCenter, "●")
                pintor.setPen(QColor(c["numero_actual"] if numero == actual else c["numeros"]))
                pintor.drawText(0, int(top), self.margen.width() - 6,
                                self.fontMetrics().height(), Qt.AlignRight, str(linea))
            bloque = bloque.next()
            top = bottom
            bottom = top + self.blockBoundingRect(bloque).height()
            numero += 1

    # ── Marcas de diagnóstico ───────────────────────────────────────────
    def marcar_diagnosticos(self, diagnosticos) -> None:
        self._marcas.clear()
        self._mensajes.clear()
        orden = {"error": 0, "warning": 1, "info": 2}
        for d in diagnosticos:
            sev = d.severity.value
            previo = self._marcas.get(d.line)
            if previo is None or orden[sev] < orden[previo]:
                self._marcas[d.line] = sev
            self._mensajes.setdefault(d.line, []).append(f"{sev.upper()}: {d.message}")
        self._repintar_marcas()

    def _repintar_marcas(self) -> None:
        c = self.colores
        extras = []

        # Fondo de la línea del cursor.
        sel = QTextEdit.ExtraSelection()
        sel.format.setBackground(QColor(c["linea_actual"]))
        sel.format.setProperty(QTextFormat.FullWidthSelection, True)
        sel.cursor = self.textCursor()
        sel.cursor.clearSelection()
        extras.append(sel)

        color_por_sev = {"error": c["error"], "warning": c["aviso"], "info": c["nota"]}
        doc = self.document()
        for linea, sev in self._marcas.items():
            bloque = doc.findBlockByNumber(linea - 1)
            if not bloque.isValid():
                continue
            marca = QTextEdit.ExtraSelection()
            marca.format.setBackground(QColor(color_por_sev[sev]))
            marca.format.setProperty(QTextFormat.FullWidthSelection, True)
            marca.cursor = QTextCursor(bloque)
            marca.cursor.clearSelection()
            extras.append(marca)

        self.setExtraSelections(extras)
        self.margen.update()

    def event(self, evento):
        # Tooltip con los diagnósticos de la línea bajo el puntero.
        if evento.type() == evento.ToolTip:
            cursor = self.cursorForPosition(evento.pos())
            mensajes = self._mensajes.get(cursor.blockNumber() + 1)
            if mensajes:
                self.setToolTip("\n\n".join(mensajes))
            else:
                self.setToolTip("")
        return super().event(evento)

    # ── Autocompletado ──────────────────────────────────────────────────
    def actualizar_diccionario(self, declarados: "list[tuple[str, str]]") -> None:
        """`declarados` son pares (nombre, descripción) del programa actual.

        Cada entrada del desplegable lleva su explicación al lado: quien
        escribe el programa no tiene por qué saber de memoria qué hace
        Totalize ni cuál es la diferencia con Average.
        """
        entradas = []
        for nombre in _PALABRAS_BASE:
            instr = buscar(nombre)
            entradas.append(f"{nombre}{SEPARADOR}{instr.resumen}" if instr else nombre)
        for nombre, descripcion in declarados:
            entradas.append(f"{nombre}{SEPARADOR}{descripcion}" if descripcion else nombre)
        self.completer.setModel(QStringListModel(sorted(set(entradas)), self))

    def _prefijo_actual(self) -> str:
        cursor = self.textCursor()
        cursor.select(QTextCursor.WordUnderCursor)
        return cursor.selectedText()

    def _insertar_completado(self, texto: str) -> None:
        nombre = texto.split(SEPARADOR)[0]
        cursor = self.textCursor()
        cursor.select(QTextCursor.WordUnderCursor)
        cursor.insertText(nombre)
        instr = buscar(nombre)
        if instr is not None and instr.usa_parentesis:
            cursor.insertText("(")
        self.setTextCursor(cursor)
        self._actualizar_ayuda_firma()

    def keyPressEvent(self, evento):
        popup = self.completer.popup()
        if popup.isVisible() and evento.key() in (
            Qt.Key_Enter, Qt.Key_Return, Qt.Key_Escape, Qt.Key_Tab, Qt.Key_Backtab
        ):
            evento.ignore()
            return

        if evento.key() == Qt.Key_F1:
            self.ayuda_pedida.emit(self.palabra_bajo_cursor())
            return
        if evento.key() == Qt.Key_Escape and self.ayuda_firma.isVisible():
            self.ayuda_firma.hide()
            return

        # Ctrl+Espacio fuerza el popup.
        forzar = evento.key() == Qt.Key_Space and evento.modifiers() & Qt.ControlModifier
        if forzar:
            evento.accept()
        else:
            if evento.key() in (Qt.Key_Return, Qt.Key_Enter):
                self._autoindentar()
                return
            super().keyPressEvent(evento)

        prefijo = self._prefijo_actual()
        if not forzar and (len(prefijo) < 2 or not prefijo[-1:].isalnum()):
            popup.hide()
            return
        if prefijo != self.completer.completionPrefix():
            self.completer.setCompletionPrefix(prefijo)
            popup.setCurrentIndex(self.completer.completionModel().index(0, 0))
        if self.completer.completionCount() == 0:
            popup.hide()
            return
        rect = self.cursorRect()
        rect.setWidth(popup.sizeHintForColumn(0)
                      + popup.verticalScrollBar().sizeHint().width() + 20)
        self.completer.complete(rect)

    def _autoindentar(self) -> None:
        """Enter conserva la sangría de la línea anterior."""
        cursor = self.textCursor()
        texto = cursor.block().text()
        sangria = texto[: len(texto) - len(texto.lstrip())]
        cursor.insertText("\n" + sangria)
        self.setTextCursor(cursor)

    def _al_mover_cursor(self):
        self._repintar_marcas()
        self._actualizar_ayuda_firma()
        cursor = self.textCursor()
        self.cursor_movido.emit(cursor.blockNumber() + 1, cursor.columnNumber() + 1)

    # ── Ayuda de firma ──────────────────────────────────────────────────
    def _actualizar_ayuda_firma(self) -> None:
        cursor = self.textCursor()
        contexto = contexto_llamada(cursor.block().text(), cursor.columnNumber())
        if contexto is None:
            self.ayuda_firma.hide()
            return
        nombre, indice = contexto
        instr = buscar(nombre)
        if instr is None or not instr.usa_parentesis:
            self.ayuda_firma.hide()
            return
        rect = self.cursorRect()
        punto = self.mapToGlobal(rect.bottomLeft())
        punto.setY(punto.y() + 6)
        self.ayuda_firma.mostrar(instr, indice, punto)

    def focusOutEvent(self, evento):
        self.ayuda_firma.hide()
        super().focusOutEvent(evento)

    def palabra_bajo_cursor(self) -> str:
        cursor = self.textCursor()
        cursor.select(QTextCursor.WordUnderCursor)
        return cursor.selectedText()

    # ── Navegación ──────────────────────────────────────────────────────
    def ir_a_linea(self, linea: int) -> None:
        bloque = self.document().findBlockByNumber(max(0, linea - 1))
        if not bloque.isValid():
            return
        cursor = QTextCursor(bloque)
        self.setTextCursor(cursor)
        self.centerCursor()
        self.setFocus()

    def paintEvent(self, evento):
        super().paintEvent(evento)
        # Guía vertical en el límite de 127 caracteres que trunca el firmware.
        x = int(self.fontMetrics().width("0") * MAX_LINE_LEN
                + self.contentOffset().x() + self.document().documentMargin())
        if 0 < x < self.viewport().width():
            pintor = QPainter(self.viewport())
            pintor.setPen(QColor(self.colores["numeros"]))
            pintor.setOpacity(0.35)
            pintor.drawLine(x, 0, x, self.viewport().height())
