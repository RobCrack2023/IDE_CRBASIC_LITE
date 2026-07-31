"""Diagnósticos del análisis de un programa .CR1."""

from dataclasses import dataclass, field
from enum import Enum


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

    @property
    def rank(self) -> int:
        return {"error": 0, "warning": 1, "info": 2}[self.value]


class Source(str, Enum):
    #: Reproduce literalmente lo que el firmware escribirá en el .HLOG.
    FIRMWARE = "firmware"
    #: Regla propia del IDE: el firmware no avisa nada, pero el programa
    #: no va a hacer lo que el autor espera.
    LINT = "lint"


@dataclass
class Diagnostic:
    #: Línea real del archivo (1-based) — la que hay que abrir en el editor.
    line: int
    severity: Severity
    message: str
    source: Source = Source.LINT
    #: Regla que lo generó, p. ej. "units-ma-sin-canal".
    code: str = ""
    #: Número de línea tal como lo reportará el .HLOG del equipo. Difiere
    #: del real porque el firmware no cuenta las líneas en blanco.
    fw_line: int = 0
    #: Texto de la línea, recortado como lo recorta el log (24 caracteres).
    fragment: str = ""
    #: Motivo textual exacto del firmware, cuando source == FIRMWARE.
    fw_reason: str = ""

    def hlog_line(self) -> str:
        """Reconstruye la línea tal como aparecerá en el .HLOG del equipo."""
        if self.source is not Source.FIRMWARE:
            return ""
        return f"[CRBasic] L{self.fw_line} ignorada ({self.fw_reason}): {self.fragment[:24]}"

    def __str__(self) -> str:
        return f"{self.line}: {self.severity.value}: {self.message}"


@dataclass
class DiagnosticList:
    items: "list[Diagnostic]" = field(default_factory=list)

    def add(self, diag: Diagnostic) -> None:
        self.items.append(diag)

    def error(self, line: int, message: str, code: str = "", **kw) -> None:
        self.add(Diagnostic(line, Severity.ERROR, message, code=code, **kw))

    def warning(self, line: int, message: str, code: str = "", **kw) -> None:
        self.add(Diagnostic(line, Severity.WARNING, message, code=code, **kw))

    def info(self, line: int, message: str, code: str = "", **kw) -> None:
        self.add(Diagnostic(line, Severity.INFO, message, code=code, **kw))

    def sorted(self) -> "list[Diagnostic]":
        return sorted(self.items, key=lambda d: (d.line, d.severity.rank))

    def counts(self) -> "dict[str, int]":
        out = {"error": 0, "warning": 0, "info": 0}
        for d in self.items:
            out[d.severity.value] += 1
        return out

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self):
        return iter(self.sorted())
