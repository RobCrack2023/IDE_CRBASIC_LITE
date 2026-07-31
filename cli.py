"""Linter de línea de comandos para programas .CR1 del Opta.

    python cli.py programa.CR1
    python cli.py programa.CR1 --recursos --hardware
    python cli.py programa.CR1 --hlog        # cómo se verá en el log del equipo
"""

import argparse
import sys

from optabasic import analyze, limits as L
from optabasic.diagnostics import Severity, Source
from optabasic.encoding import codificar, leer

_COLOR = {"error": "\033[91m", "warning": "\033[93m", "info": "\033[96m"}
_RESET = "\033[0m"
_ETIQUETA = {"error": "ERROR", "warning": "aviso", "info": "nota "}


def _color(txt: str, sev: str, usar: bool) -> str:
    return f"{_COLOR[sev]}{txt}{_RESET}" if usar else txt


def _barra(usado: int, total: int, ancho: int = 24) -> str:
    llenos = min(ancho, round(ancho * usado / total)) if total else 0
    return "█" * llenos + "·" * (ancho - llenos)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Linter de CRBasic-lite para Arduino Opta")
    ap.add_argument("archivo", help="programa .CR1 a analizar")
    ap.add_argument("--recursos", action="store_true", help="mostrar uso de límites")
    ap.add_argument("--hardware", action="store_true", help="mostrar mapa de canales")
    ap.add_argument("--hlog", action="store_true",
                    help="mostrar las líneas tal como saldrán en el .HLOG del equipo")
    ap.add_argument("--sin-color", action="store_true")
    ap.add_argument("--solo-errores", action="store_true")
    args = ap.parse_args(argv)

    usar_color = not args.sin_color and sys.stdout.isatty()

    try:
        texto, enc = leer(args.archivo)
    except OSError as e:
        print(f"No se pudo abrir {args.archivo}: {e}", file=sys.stderr)
        return 2

    # El tamaño que importa es el del archivo que se sube al equipo.
    r = analyze(texto, size_bytes=len(codificar(texto, "cp1252")))
    prog = r.program

    print(f"{args.archivo} ({enc}, {prog.size_bytes} bytes)\n")

    for d in r.diagnostics:
        if args.solo_errores and d.severity is not Severity.ERROR:
            continue
        etiqueta = _color(_ETIQUETA[d.severity.value], d.severity.value, usar_color)
        print(f"  L{d.line:<4} {etiqueta}  {d.message}")
        if d.source is Source.FIRMWARE:
            print(f"         └─ en el .HLOG del equipo: L{d.fw_line} ({d.fw_reason})")

    c = r.diagnostics.counts()
    print(f"\n  {c['error']} errores, {c['warning']} avisos, {c['info']} notas")

    if not prog.parsed:
        print("\n  ⚠ Sin DataTable el equipo NO ejecuta este programa.")

    if args.recursos:
        print("\nRecursos")
        for etiqueta, usado, total in [
            ("Programa (bytes)", prog.size_bytes, L.MAX_PROG_BYTES),
            ("Variables", len(prog.vars), L.MAX_VARS),
            ("Constantes", len(prog.consts), L.MAX_CONSTS),
            ("Tablas", len(prog.tables), L.MAX_TABLES),
            ("Instrucciones", len(prog.stmts), L.MAX_STMTS),
        ]:
            print(f"  {etiqueta:<18} {_barra(usado, total)} {usado}/{total}")
        for t in prog.tables:
            print(f"  {'  campos ' + t.name:<18} {_barra(t.n_fields, L.MAX_FIELDS)} "
                  f"{t.n_fields}/{L.MAX_FIELDS}")

    if args.hardware:
        print(f"\nHardware   (scan cada {prog.scan_seconds:g}s)")
        for i, v in enumerate(prog.analog_map()):
            pulso = prog.pulse_map()[i]
            if v is None and pulso is None:
                print(f"  A{i}  libre")
            elif pulso is not None and v is not None:
                print(f"  A{i}  ⚠ {v.name} ({v.kind}) + {pulso.name} (pulsos)")
            elif pulso is not None:
                print(f"  A{i}  {pulso.name} (pulsos)")
            else:
                print(f"  A{i}  {v.name} ({v.kind}){' [' + v.units + ']' if v.units else ''}")
        for i, v in enumerate(prog.relay_map()):
            print(f"  DO{i + 1} {v.name if v else 'libre'}")

    if args.hlog:
        print("\nLo que va a aparecer en el .HLOG del equipo")
        hubo = False
        for d in r.diagnostics:
            if d.source is Source.FIRMWARE:
                print(f"  {d.hlog_line()}")
                hubo = True
        if not hubo:
            print("  (ninguna línea ignorada)")

    return 1 if c["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
