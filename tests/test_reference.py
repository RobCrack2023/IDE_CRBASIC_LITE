"""Pruebas del catálogo de ayuda y de la detección del argumento activo."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from optabasic.reference import (  # noqa: E402
    CATALOGO,
    CATEGORIAS,
    buscar,
    contexto_llamada,
)


def test_toda_instruccion_tiene_categoria_conocida():
    for instr in CATALOGO:
        assert instr.categoria in CATEGORIAS, instr.nombre


def test_toda_instruccion_tiene_resumen_y_ejemplo():
    for instr in CATALOGO:
        assert instr.resumen, instr.nombre
        assert instr.ejemplo, instr.nombre


def test_los_parametros_coinciden_con_la_firma():
    """Si la ficha documenta argumentos, tiene que haber uno por cada hueco."""
    for instr in CATALOGO:
        if not instr.parametros:
            continue
        assert len(instr.parametros) == len(instr.firma_partes()), instr.nombre


def test_busqueda_sin_distinguir_mayusculas():
    assert buscar("voltse").nombre == "VoltSE"
    assert buscar("PORTSET").nombre == "PortSet"
    assert buscar("noexiste") is None


def test_argumentos_ignorados_estan_marcados():
    """Los que el firmware descarta tienen que salir señalados en la ficha."""
    portset = buscar("PortSet")
    assert portset.parametros[1].ignorado          # Valor no hace nada
    datatable = buscar("DataTable")
    assert datatable.parametros[1].ignorado        # Disparador no hace nada
    scan = buscar("Scan")
    assert scan.parametros[2].ignorado and scan.parametros[3].ignorado


# ── Detección del argumento donde está el cursor ─────────────────────────
def test_contexto_argumento_por_comas():
    linea = "VoltSE(Temp, 1, mV5000, 1)"
    assert contexto_llamada(linea, 7) == ("VoltSE", 0)
    assert contexto_llamada(linea, 13) == ("VoltSE", 1)
    assert contexto_llamada(linea, 17) == ("VoltSE", 2)


def test_contexto_fuera_de_la_llamada():
    assert contexto_llamada("Nivel = 3", 9) is None
    assert contexto_llamada("VoltSE(Temp, 1)", 15) is None   # después del cierre


def test_contexto_con_parentesis_anidados():
    linea = "Nivel = Abs(Sqr(X) - 1)"
    assert contexto_llamada(linea, 16) == ("Sqr", 0)
    assert contexto_llamada(linea, 21) == ("Abs", 0)


def test_contexto_ignora_comentarios_y_cadenas():
    assert contexto_llamada("Nivel = 1  ' ver Sample(1, X", 27) is None
    assert contexto_llamada('StationName="a(b"', 17) is None


def test_contexto_con_indentacion_y_espacios():
    assert contexto_llamada("    PortSet (DO1, 0, 1)", 20) == ("PortSet", 2)


def test_indice_mas_alla_de_la_firma():
    """Escribir de más tiene que poder detectarse para poder avisarlo."""
    linea = "AIChannel(X, 1, 2, 3)"
    nombre, indice = contexto_llamada(linea, 20)
    assert nombre == "AIChannel"
    assert indice >= len(buscar("AIChannel").firma_partes())
