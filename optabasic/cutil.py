"""Equivalentes en Python de las funciones de C que usa el parser.

El objetivo de este módulo es que el resto del port se lea igual que el
código del firmware: mismas semánticas de truncado, de conversión numérica
parcial y de comparación case-insensitive. Cualquier diferencia acá se
propaga como un falso positivo (o peor, un falso negativo) en el linter.
"""

import re

_ATOF_RE = re.compile(r"^\s*[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_ATOI_RE = re.compile(r"^\s*[+-]?\d+")
# Sin signo ni espacios: strtof() dentro de cr_compile_expr ya llega
# posicionado sobre el primer dígito.
_NUM_RE = re.compile(r"(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")


def c_atof(s: str) -> float:
    """atof(): convierte el prefijo numérico y devuelve 0.0 si no hay ninguno.

    Ésta es la razón por la que `Const B = A * 2` no falla ruidosamente:
    atof("A * 2") devuelve 0.0 y la constante queda valiendo cero.
    """
    m = _ATOF_RE.match(s)
    if not m:
        return 0.0
    try:
        return float(m.group(0))
    except ValueError:
        return 0.0


def c_atoi(s: str) -> int:
    """atoi(): igual que c_atof pero entero, 0 si no hay prefijo numérico."""
    m = _ATOI_RE.match(s)
    if not m:
        return 0
    try:
        return int(m.group(0))
    except ValueError:
        return 0


def c_strtof(s: str, pos: int) -> "tuple[float, int]":
    """strtof(p, &p): devuelve (valor, nueva_posición)."""
    m = _NUM_RE.match(s, pos)
    if not m:
        return 0.0, pos
    try:
        return float(m.group(0)), m.end()
    except ValueError:
        return 0.0, m.end()


def cr_eq(a: str, b: str) -> bool:
    """cr_eq(): comparación completa sin distinguir mayúsculas."""
    return a.upper() == b.upper()


def stristr(hay: str, needle: str) -> int:
    """cr_stristr(): índice de la primera aparición case-insensitive, o -1."""
    if not needle or len(needle) > len(hay):
        return -1
    return hay.upper().find(needle.upper())


def strncpy(s: str, n: int) -> str:
    """strncpy(dst, src, n) sobre un buffer de n+1: trunca a n caracteres."""
    return s[:n]


def rstrip_ctrl(s: str) -> str:
    """Recorta los caracteres <= ' ' del final, como hace el firmware."""
    n = len(s)
    while n > 0 and s[n - 1] <= " ":
        n -= 1
    return s[:n]


def is_c_space(ch: str) -> bool:
    return ch in " \t\n\r\v\f"
