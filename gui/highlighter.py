"""Resaltado de sintaxis de CRBasic-lite."""

import re

from PyQt5.QtCore import QRegExp, Qt
from PyQt5.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat

# ── Vocabulario reconocido por el firmware ───────────────────────────────
ESTRUCTURA = [
    "BeginProg", "EndProg", "Scan", "NextScan", "CallTable",
    "DataTable", "EndTable", "DataInterval",
    "If", "Then", "Else", "ElseIf", "EndIf", "End", "And", "Or",
]
DECLARACION = ["Public", "Dim", "Const", "Units", "As"]
INSTRUCCIONES = [
    "VoltDiff", "VoltSE", "AIChannel", "PortSet", "PulseCount",
    "PulseEdge", "ExciteCh", "Battery",
    "Sample", "Average", "Maximum", "Minimum", "Totalize",
    "BrHalf", "RealTime", "PanelTemp", "SW12",
]
DIRECTIVAS = ["StationName", "ServerHost", "ServerPort", "PakBusAddress"]
FUNCIONES = ["Abs", "Int", "Sqr"]
LITERALES = [
    "True", "False", "Sec", "Min", "Hour", "Day", "Msec",
    "Rising", "Falling", "Subida", "Bajada",
    "FP2", "UINT2", "INT2", "INT4", "Long", "Float", "String", "Boolean",
]
#: Instrucciones de CRBasic real que el Opta NO implementa: se marcan en
#: rojo tachado para que salten a la vista antes de subir el programa.
NO_SOPORTADO = [
    "SDI12Recorder", "SerialOpen", "SerialIn", "SerialOut", "SerialClose",
    "SerialInRecord", "For", "Next", "While", "Wend", "Do", "Loop", "Sub",
    "EndSub", "GoSub", "Return", "IfTime", "TimeIsBetween", "Alias",
    "SlowSequence", "EndSequence", "Select", "Case", "TableFile",
    "Sin", "Cos", "Tan", "Ln", "Log", "Exp", "Mod", "ATN", "PWR",
]


def _fmt(color: str, *, negrita=False, cursiva=False, tachado=False) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if negrita:
        f.setFontWeight(QFont.Bold)
    f.setFontItalic(cursiva)
    f.setFontStrikeOut(tachado)
    return f


class Paleta:
    """Colores del editor, en variante clara y oscura."""

    CLARA = {
        "fondo": "#fdfdfd", "texto": "#1f2328", "linea_actual": "#f2f6fc",
        "margen": "#f0f2f5", "numeros": "#9aa2ad", "numero_actual": "#1f2328",
        "estructura": "#0a53be", "declaracion": "#8250df", "instruccion": "#0550ae",
        "directiva": "#0f6b3d", "funcion": "#953800", "literal": "#0a3069",
        "numero": "#0550ae", "comentario": "#6e7781", "cadena": "#0a3069",
        "operador": "#cf222e", "no_soportado": "#cf222e",
        "error": "#ffdcdc", "aviso": "#fff3ce", "nota": "#e3f1ff",
    }
    OSCURA = {
        "fondo": "#1b1f24", "texto": "#e6edf3", "linea_actual": "#22272e",
        "margen": "#21262d", "numeros": "#6e7681", "numero_actual": "#e6edf3",
        "estructura": "#79c0ff", "declaracion": "#d2a8ff", "instruccion": "#79c0ff",
        "directiva": "#7ee787", "funcion": "#ffa657", "literal": "#a5d6ff",
        "numero": "#79c0ff", "comentario": "#8b949e", "cadena": "#a5d6ff",
        "operador": "#ff7b72", "no_soportado": "#ff7b72",
        "error": "#4a2226", "aviso": "#42361a", "nota": "#1b3247",
    }


class CRBasicHighlighter(QSyntaxHighlighter):
    def __init__(self, documento, colores=None):
        super().__init__(documento)
        self.colores = colores or Paleta.CLARA
        self._construir_reglas()

    def cambiar_paleta(self, colores: dict) -> None:
        self.colores = colores
        self._construir_reglas()
        self.rehighlight()

    def _construir_reglas(self) -> None:
        c = self.colores
        self.reglas = []

        def palabras(lista, formato):
            patron = r"\b(" + "|".join(re.escape(p) for p in lista) + r")\b"
            rx = QRegExp(patron)
            rx.setCaseSensitivity(Qt.CaseInsensitive)
            self.reglas.append((rx, formato))

        palabras(NO_SOPORTADO, _fmt(c["no_soportado"], negrita=True, tachado=True))
        palabras(ESTRUCTURA, _fmt(c["estructura"], negrita=True))
        palabras(DECLARACION, _fmt(c["declaracion"], negrita=True))
        palabras(INSTRUCCIONES, _fmt(c["instruccion"]))
        palabras(DIRECTIVAS, _fmt(c["directiva"], negrita=True))
        palabras(FUNCIONES, _fmt(c["funcion"]))
        palabras(LITERALES, _fmt(c["literal"]))

        self.reglas.append((QRegExp(r"\b\d+\.?\d*([eE][+-]?\d+)?\b"), _fmt(c["numero"])))
        self.reglas.append((QRegExp(r"[+\-*/=<>]"), _fmt(c["operador"])))
        self.reglas.append((QRegExp(r'"[^"]*"'), _fmt(c["cadena"])))

        self.fmt_comentario = _fmt(c["comentario"], cursiva=True)

    def highlightBlock(self, texto: str) -> None:
        for rx, formato in self.reglas:
            i = rx.indexIn(texto)
            while i >= 0:
                largo = rx.matchedLength()
                if largo <= 0:
                    break
                self.setFormat(i, largo, formato)
                i = rx.indexIn(texto, i + largo)

        # El comentario gana sobre todo lo demás, igual que en el parser:
        # cr_strip_comment() corta en el primer «'» fuera de comillas.
        en_cadena = False
        for i, ch in enumerate(texto):
            if ch == '"':
                en_cadena = not en_cadena
            elif ch == "'" and not en_cadena:
                self.setFormat(i, len(texto) - i, self.fmt_comentario)
                break
