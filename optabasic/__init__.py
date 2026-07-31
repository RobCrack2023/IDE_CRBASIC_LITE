"""Motor de análisis de CRBasic-lite para Arduino Opta.

Port en Python del parser embebido en el firmware OptaPakBus
(parse_crbasic / cr_compile_expr / crbasic_execute_scan), más una capa de
reglas propias que avisan de lo que el equipo acepta en silencio.

Uso típico:

    from optabasic import analyze
    resultado = analyze(open('programa.CR1', encoding='latin-1').read())
    for d in resultado.diagnostics:
        print(d)
"""

from .diagnostics import Diagnostic, DiagnosticList, Severity, Source
from .lint import analyze, lint
from .model import Const, Field, Network, Program, Stmt, StmtType, Table, Var
from .parser import ParseResult, parse

__all__ = [
    "analyze",
    "lint",
    "parse",
    "ParseResult",
    "Program",
    "Var",
    "Const",
    "Table",
    "Field",
    "Stmt",
    "StmtType",
    "Network",
    "Diagnostic",
    "DiagnosticList",
    "Severity",
    "Source",
]

__version__ = "1.0.0"
