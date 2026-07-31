"""Compilador de expresiones — espejo de cr_compile_expr() (Shunting-Yard).

El firmware compila cada expresión a RPN con un límite duro de 20 tokens de
salida y 20 niveles de pila de operadores. Si no compila, la instrucción
entera se descarta. Reproducir el conteo exacto es la única forma de saber
de antemano si una expresión larga va a entrar.
"""

from dataclasses import dataclass, field
from enum import IntEnum

from .cutil import c_strtof, cr_eq

_FUNCS = ("ABS", "INT", "SQR")


class Tok(IntEnum):
    NUM = 0
    VAR = 1
    ADD = 2
    SUB = 3
    MUL = 4
    DIV = 5
    NEG = 6
    ABS = 7
    INT = 8
    SQR = 9
    SENTINEL = 100


def _prec(t: int) -> int:
    if t in (Tok.ADD, Tok.SUB):
        return 1
    if t in (Tok.MUL, Tok.DIV):
        return 2
    if t == Tok.NEG:
        return 3
    if t >= Tok.ABS:
        return 4
    return 0


@dataclass
class ExprResult:
    ok: bool
    tokens: int = 0
    error: str = ""
    #: Identificadores referenciados, para poder rastrear usos en el IDE.
    refs: "list[str]" = field(default_factory=list)
    #: Nombre que rompió la compilación, si fue un identificador desconocido.
    unknown: str = ""


def compile_expr(
    expr: str,
    var_names: "list[str]",
    const_names: "list[str]",
    max_tokens: int,
    opstk_max: int,
) -> ExprResult:
    """Compila y devuelve el número de tokens RPN, o el motivo del fallo.

    Sigue paso a paso el bucle del firmware, incluida la condición de corte
    `while (*p && out < maxTok)`: cuando la salida llega al tope, el resto
    de la expresión se deja sin consumir y el drenaje final de la pila hace
    fallar la compilación.
    """
    op_stack: "list[int]" = []
    out = 0
    i = 0
    n = len(expr)
    prev_operand = False
    refs: "list[str]" = []

    while i < n and out < max_tokens:
        while i < n and expr[i].isspace():
            i += 1
        if i >= n:
            break

        ch = expr[i]

        # ── Literal numérico ────────────────────────────────────────────
        if ch.isdigit() or (ch == "." and i + 1 < n and expr[i + 1].isdigit()):
            if prev_operand:
                return ExprResult(False, error="dos operandos seguidos sin operador entre ellos")
            _, i = c_strtof(expr, i)
            out += 1
            prev_operand = True
            continue

        # ── Signo unario ────────────────────────────────────────────────
        if ch == "-" and not prev_operand:
            if len(op_stack) >= opstk_max:
                return ExprResult(False, error=f"demasiados operadores anidados (máx {opstk_max})")
            op_stack.append(Tok.NEG)
            i += 1
            continue
        if ch == "+" and not prev_operand:
            i += 1
            continue

        # ── Operador binario ────────────────────────────────────────────
        if ch in "+-*/":
            tok = {"+": Tok.ADD, "-": Tok.SUB, "*": Tok.MUL, "/": Tok.DIV}[ch]
            pr = _prec(tok)
            while op_stack and op_stack[-1] != Tok.SENTINEL and _prec(op_stack[-1]) >= pr:
                if out >= max_tokens:
                    return ExprResult(False, error=f"expresión demasiado larga (máx {max_tokens} tokens)")
                op_stack.pop()
                out += 1
            if len(op_stack) >= opstk_max:
                return ExprResult(False, error=f"demasiados operadores anidados (máx {opstk_max})")
            op_stack.append(tok)
            i += 1
            prev_operand = False
            continue

        # ── Paréntesis ──────────────────────────────────────────────────
        if ch == "(":
            if len(op_stack) >= opstk_max:
                return ExprResult(False, error=f"demasiados paréntesis anidados (máx {opstk_max})")
            op_stack.append(Tok.SENTINEL)
            i += 1
            prev_operand = False
            continue

        if ch == ")":
            while op_stack and op_stack[-1] != Tok.SENTINEL:
                if out >= max_tokens:
                    return ExprResult(False, error=f"expresión demasiado larga (máx {max_tokens} tokens)")
                op_stack.pop()
                out += 1
            if op_stack:
                op_stack.pop()
            if op_stack and Tok.ABS <= op_stack[-1] <= Tok.SQR:
                if out >= max_tokens:
                    return ExprResult(False, error=f"expresión demasiado larga (máx {max_tokens} tokens)")
                op_stack.pop()
                out += 1
            i += 1
            prev_operand = True
            continue

        # ── Identificador: función, variable o constante ────────────────
        if ch.isalpha() or ch == "_":
            name_chars: "list[str]" = []
            while i < n and (expr[i].isalnum() or expr[i] == "_") and len(name_chars) < 23:
                name_chars.append(expr[i])
                i += 1
            nm = "".join(name_chars)

            if any(cr_eq(nm, f) for f in _FUNCS):
                if len(op_stack) >= opstk_max:
                    return ExprResult(False, error=f"demasiadas funciones anidadas (máx {opstk_max})")
                op_stack.append({"ABS": Tok.ABS, "INT": Tok.INT, "SQR": Tok.SQR}[nm.upper()])
                prev_operand = False
                continue

            if prev_operand:
                return ExprResult(
                    False, error=f'"{nm}" viene pegado a otro operando, falta un operador'
                )

            known = any(cr_eq(nm, c) for c in const_names) or any(cr_eq(nm, v) for v in var_names)
            if not known:
                hint = ""
                if nm.upper() in ("SIN", "COS", "TAN", "LN", "LOG", "EXP", "MOD", "ATN", "PWR"):
                    hint = " — el Opta solo implementa Abs, Int y Sqr"
                return ExprResult(
                    False,
                    error=f'"{nm}" no está declarada con Public/Dim/Const antes de esta línea{hint}',
                    unknown=nm,
                )
            refs.append(nm)
            out += 1
            prev_operand = True
            continue

        return ExprResult(False, error=f'carácter no soportado en una expresión: "{ch}"')

    # ── Drenaje final de la pila de operadores ──────────────────────────
    while op_stack and out < max_tokens:
        if op_stack[-1] == Tok.SENTINEL:
            return ExprResult(False, error="paréntesis sin cerrar")
        op_stack.pop()
        out += 1
    if op_stack:
        return ExprResult(
            False,
            error=f"expresión demasiado larga: no entra en {max_tokens} tokens RPN",
            tokens=out,
        )
    if out == 0:
        return ExprResult(False, error="expresión vacía")
    return ExprResult(True, tokens=out, refs=refs)
