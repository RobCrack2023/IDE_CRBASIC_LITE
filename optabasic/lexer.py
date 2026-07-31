"""Extracción y troceo de líneas, calcado del firmware.

Las funciones de acá son espejo de cr_strip_comment(), cr_keyword(),
cr_paren() y cr_args() en OptaPakBus.ino.
"""

from dataclasses import dataclass, field

from .cutil import rstrip_ctrl
from .limits import MAX_ARG_LEN, MAX_ARGS, MAX_LINE_LEN


@dataclass
class SourceLine:
    """Una línea tal como la ve el parser del firmware."""

    #: Número de línea real en el archivo (1-based) — para el editor.
    file_no: int
    #: Número que usará el firmware en el .HLOG (no cuenta líneas vacías).
    fw_no: int
    #: Texto ya truncado a 127 caracteres, sin comentario ni espacios finales.
    text: str
    #: Texto original completo de la línea, sin tocar.
    raw: str
    #: True si la línea original superaba los 127 caracteres.
    truncated: bool = False


@dataclass
class ParsedLine:
    """Resultado de trocear una SourceLine en keyword + argumentos."""

    src: SourceLine
    keyword: str
    has_paren: bool
    args: "list[str]" = field(default_factory=list)
    #: Argumentos antes del truncado a 31 caracteres, para poder avisarlo.
    raw_args: "list[str]" = field(default_factory=list)
    #: True si el firmware descartó argumentos por pasarse de 12.
    args_overflow: bool = False


def split_lines(text: str) -> "list[SourceLine]":
    """Recorre el programa igual que el bucle de parse_crbasic().

    El firmware consume TODOS los '\\n'/'\\r' consecutivos como un solo
    separador, así que una línea en blanco no incrementa crParseLineNo.
    Por eso el número de línea del .HLOG queda corrido respecto al archivo
    en cuanto el programa tiene líneas vacías — y todos las tienen. Acá se
    llevan los dos contadores para poder mostrar ambos.
    """
    out: "list[SourceLine]" = []
    n = len(text)
    p = 0
    fw_no = 0
    file_no = 1

    while p < n:
        le = p
        while le < n and text[le] not in "\n\r":
            le += 1
        raw = text[p:le]
        truncated = len(raw) > MAX_LINE_LEN
        line = raw[:MAX_LINE_LEN]

        # Consumir el bloque de saltos de línea, contando cuántas líneas
        # de archivo representa realmente.
        nl_start = le
        while le < n and text[le] in "\n\r":
            le += 1
        newlines = _count_file_lines(text[nl_start:le])

        fw_no += 1
        out.append(
            SourceLine(
                file_no=file_no,
                fw_no=fw_no,
                text=rstrip_ctrl(strip_comment(line)),
                raw=raw,
                truncated=truncated,
            )
        )
        file_no += newlines
        p = le

    return out


def _count_file_lines(sep: str) -> int:
    """Cuántas líneas de archivo representa un bloque de separadores."""
    count = 0
    i = 0
    while i < len(sep):
        if sep[i] == "\r" and i + 1 < len(sep) and sep[i + 1] == "\n":
            i += 2
        else:
            i += 1
        count += 1
    return max(count, 1)


def strip_comment(line: str) -> str:
    """cr_strip_comment(): corta en el primer «'» fuera de comillas."""
    in_str = False
    for i, ch in enumerate(line):
        if ch == '"':
            in_str = not in_str
        if not in_str and ch == "'":
            return line[:i]
    return line


def keyword(line: str) -> str:
    """cr_keyword(): primer token en mayúsculas, hasta '(' o espacio.

    Trunca a 23 caracteres, igual que el buffer kw[24] del firmware.
    """
    p = 0
    while p < len(line) and line[p] in " \t":
        p += 1
    kw = []
    while p < len(line) and line[p] not in "( \t" and len(kw) < 23:
        kw.append(line[p].upper())
        p += 1
    return "".join(kw)


def paren(line: str) -> "str | None":
    """cr_paren(): contenido entre el primer '(' y el ÚLTIMO ')'."""
    s = line.find("(")
    if s < 0:
        return None
    e = line.rfind(")")
    if e >= s + 1:
        return line[s + 1 : e]
    return line[s + 1 :]


def args_of(content: str) -> "tuple[list[str], list[str], bool]":
    """cr_args(): trocea por comas respetando paréntesis anidados.

    Devuelve (args_truncados, args_completos, hubo_overflow). Un ')' sin su
    '(' corta el argumento ahí mismo, igual que el firmware. Cada argumento
    se trunca a 31 caracteres y se aceptan como máximo 12.
    """
    args: "list[str]" = []
    raw_args: "list[str]" = []
    p = 0
    n = len(content)
    overflow = False

    while p < n:
        if len(args) >= MAX_ARGS:
            # El firmware corta el while y descarta el resto en silencio.
            overflow = bool(content[p:].strip())
            break
        while p < n and content[p] in " \t":
            p += 1
        if p >= n:
            break
        buf: "list[str]" = []
        full: "list[str]" = []
        depth = 0
        while p < n:
            c = content[p]
            if c == "," and depth == 0:
                break
            if c == "(":
                depth += 1
            elif c == ")":
                if depth > 0:
                    depth -= 1
                else:
                    break  # ')' huérfano: corta el argumento acá
            if len(buf) < MAX_ARG_LEN:
                buf.append(c)
            full.append(c)
            p += 1
        arg = rstrip_ctrl("".join(buf))
        if arg:
            args.append(arg)
            raw_args.append(rstrip_ctrl("".join(full)))
        if p < n and content[p] in ",)":
            p += 1

    return args, raw_args, overflow


def parse_line(src: SourceLine) -> ParsedLine:
    """Trocea una SourceLine igual que hace el cuerpo de parse_crbasic()."""
    kw = keyword(src.text)
    content = paren(src.text)
    if content is None:
        return ParsedLine(src=src, keyword=kw, has_paren=False)
    args, raw_args, overflow = args_of(content)
    return ParsedLine(
        src=src,
        keyword=kw,
        has_paren=True,
        args=args,
        raw_args=raw_args,
        args_overflow=overflow,
    )
