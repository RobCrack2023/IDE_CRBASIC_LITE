"""Reglas propias del IDE: lo que el firmware acepta pero no hace.

El parser del Opta es deliberadamente permisivo — descarta en silencio lo
que no entiende y sigue. Estas reglas cubren el otro caso, más peligroso:
programas que el firmware acepta sin una sola queja y que aun así no hacen
lo que el autor cree. Cada regla está anclada a una línea concreta de
OptaPakBus.ino, anotada en su comentario.
"""

import re

from . import limits as L
from .cutil import cr_eq
from .diagnostics import Severity
from .lexer import keyword
from .model import StmtType
from .parser import ParseResult

_LITERAL_RE = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")

#: Instrucciones que realmente consumen los argumentos entre paréntesis.
#: El firmware trocea TODA línea que tenga un '(', incluidas las condiciones
#: de un If, pero solo estas miran el resultado — avisar de un argumento
#: truncado en un «If (A > B) Then …» sería un falso positivo.
_CON_ARGUMENTOS = {
    "SCAN", "DATATABLE", "DATAINTERVAL", "SAMPLE", "AVERAGE", "MAXIMUM",
    "MINIMUM", "TOTALIZE", "VOLTDIFF", "VOLTSE", "AICHANNEL", "PORTSET",
    "PULSECOUNT", "PULSEEDGE", "EXCITECH", "BRHALF", "REALTIME", "PANELTEMP",
    "SW12", "BATTERY",
}

#: Instrucciones de CRBasic real que el Opta no implementa (manual §17).
_FUERA_DE_ALCANCE = {
    "SDI12RECORDER": "SDI-12 no está implementado",
    "SERIALOPEN": "el puerto serie no está implementado",
    "SERIALIN": "el puerto serie no está implementado",
    "SERIALOUT": "el puerto serie no está implementado",
    "SERIALINRECORD": "el puerto serie no está implementado",
    "SERIALCLOSE": "el puerto serie no está implementado",
    "FOR": "no hay bucles For/Next — desenrollar el bucle a mano",
    "NEXT": "no hay bucles For/Next",
    "WHILE": "no hay bucles While/Wend",
    "WEND": "no hay bucles While/Wend",
    "DO": "no hay bucles Do/Loop",
    "LOOP": "no hay bucles Do/Loop",
    "SUB": "no hay subrutinas (Sub/GoSub)",
    "ENDSUB": "no hay subrutinas (Sub/GoSub)",
    "GOSUB": "no hay subrutinas (Sub/GoSub)",
    "RETURN": "no hay subrutinas (Sub/GoSub)",
    "IFTIME": "no hay funciones de tiempo (IfTime/TimeIsBetween)",
    "TIMEISBETWEEN": "no hay funciones de tiempo (IfTime/TimeIsBetween)",
    "REALTIME2": "no hay funciones de tiempo",
    "ALIAS": "Alias no está implementado",
    "SLOWSEQUENCE": "SlowSequence no está implementado",
    "ENDSEQUENCE": "SlowSequence no está implementado",
    "SELECTCASE": "no hay Select Case — usar If/ElseIf",
    "CASE": "no hay Select Case — usar If/ElseIf",
    "DATALOGGER": "instrucción no reconocida por el Opta",
    "TABLEFILE": "TableFile no está implementado",
    "STATIONNAMESET": "usar la directiva StationName=",
}


def lint(result: ParseResult) -> ParseResult:
    """Agrega los diagnósticos propios del IDE al resultado del parseo."""
    _estructura(result)
    _lexico(result)
    _declaraciones(result)
    _hardware(result)
    _tablas(result)
    _condiciones(result)
    _red(result)
    _preserve(result)
    _mediana(result)
    _agenda(result)
    return result


# ─────────────────────────────────────────────────────────────────────────
#  SetpointSchedule (v1.9.3)
# ─────────────────────────────────────────────────────────────────────────
def _agenda(result: ParseResult) -> None:
    prog, diags = result.program, result.diagnostics

    for sc in prog.schedules:
        dst = prog.find_var(sc.dest)
        if dst is None:
            continue

        # Sin PreserveVariables la consigna arranca en 0 tras un reinicio. Si
        # el reloj todavia no sincronizo —un corte de luz con el enlace caido es
        # justo el caso— el equipo no toca la consigna, y el lazo de control
        # trabaja con objetivo 0 hasta que haya hora. En una compuerta eso es
        # una maniobra equivocada.
        # La forma sin argumentos tambien la cubre: el firmware la marca como
        # preservada la primera vez que la agenda le cambia el valor.
        if not (dst.preserve or prog.preserve_all):
            diags.warning(
                sc.line,
                f"«{dst.name}» tiene agenda pero no esta en PreserveVariables. "
                "Si el equipo reinicia sin reloj sincronizado, la consigna "
                "arranca en 0 y el lazo trabaja con ese objetivo hasta que "
                f"llegue la hora. Agrega «PreserveVariables {dst.name}».",
                code="agenda-sin-preserve",
            )

        # El equipo escribe la consigna antes de los statements. Una asignacion
        # incondicional del programa la pisa en cada scan y la agenda no sirve
        # de nada; una condicional (un override propio) si es legitima, asi que
        # solo se avisa, no se rechaza.
        if dst.assigned_lines:
            diags.warning(
                dst.assigned_lines[0],
                f"«{dst.name}» la mueve la agenda (SetpointSchedule, linea "
                f"{sc.line}) y ademas el programa le asigna un valor. Si la "
                "asignacion corre en cada scan, pisa a la agenda en el scan "
                "siguiente a cada cambio.",
                code="agenda-consigna-asignada",
            )

        # Agenda_N y Agenda_Serie las escribe el equipo en cada scan: lo que
        # el programa les asigne se pierde.
        for nombre in (sc.n_var, sc.serie_var):
            v = prog.find_var(nombre) if nombre else None
            if v is not None and v.assigned_lines:
                diags.warning(
                    v.assigned_lines[0],
                    f"«{v.name}» la escribe el equipo en cada scan "
                    "(SetpointSchedule) y es de solo lectura: lo que le asigne "
                    "el programa se pierde.",
                    code="agenda-info-asignada",
                )


# ─────────────────────────────────────────────────────────────────────────
#  MedianRun (v1.9.0)
# ─────────────────────────────────────────────────────────────────────────
def _mediana(result: ParseResult) -> None:
    prog, diags = result.program, result.diagnostics

    for m in prog.medians:
        dst = prog.find_var(m.dest)
        src = prog.find_var(m.src)

        # El filtro escribe el destino en cada scan, ANTES de los statements.
        # Si el programa tambien le asigna, la asignacion gana y el filtro no
        # sirve de nada: el sintoma es un valor sin filtrar, sin ningun aviso.
        if dst is not None and dst.assigned_lines:
            diags.error(
                dst.assigned_lines[0],
                f"«{dst.name}» recibe la mediana de «{m.src}», pero el programa "
                "tambien le asigna un valor. El filtro corre antes que las "
                "asignaciones, asi que la asignacion lo pisa y el valor queda "
                "sin filtrar. Usa otra variable para el calculo.",
                code="mediana-destino-asignado",
            )

        # Filtrar algo que no sale de un sensor casi siempre es un dedazo en
        # el orden de los argumentos: MedianRun(destino, fuente, ventana).
        # El predicado es is_written y no preserve_pointless: la pregunta es
        # «¿alguien le escribe a la fuente?». Filtrar la consigna que mueve una
        # agenda es legitimo (MedianRun(Suavizada, Consigna_cm, 5)): con
        # preserve_pointless la consigna daria false y el aviso saltaria como
        # falso positivo, «va a filtrar un 0 constante».
        if src is not None and not src.is_written and not src.assigned_lines:
            diags.warning(
                m.line,
                f"«{m.src}» no lee ninguna entrada ni recibe asignaciones, asi "
                f"que la mediana va a filtrar un 0 constante. ¿Estan dados "
                f"vuelta los argumentos? Van MedianRun(destino, fuente, ventana).",
                code="mediana-fuente-sin-lectura",
            )


# ─────────────────────────────────────────────────────────────────────────
#  PreserveVariables (v1.8.0)
# ─────────────────────────────────────────────────────────────────────────
def _preserve(result: ParseResult) -> None:
    prog, diags = result.program, result.diagnostics
    if not prog.preserve_enabled:
        return

    # La forma sin argumentos tambien alcanza a las variables de ORDEN
    # (MoverCm, Parar). El firmware vuelca recien 3 s despues de la escritura,
    # asi que una orden que el scan ya puso en cero se guarda consumida; pero
    # eso depende de que el programa la limpie, y conviene no depender de eso.
    if prog.preserve_all:
        diags.info(
            prog.preserve_line,
            "PreserveVariables sin argumentos preserva TODA variable que "
            "escriba la plataforma, incluidas las de orden como MoverCm o "
            "Parar. Es la forma del CR1000 y el Opta la acepta, pero conviene "
            "nombrar solo las consignas: PreserveVariables Consigna, Banda.",
            code="preserve-sin-lista",
        )

    # El volcado lo dispara la escritura de la PLATAFORMA. Un valor que el
    # propio programa calcula cambia en cada scan y el firmware no lo guarda:
    # guardar a 1 Hz desgastaria la flash, asi que no lo hace.
    for v in prog.vars:
        if v.preserve and v.assigned_lines:
            diags.warning(
                v.assigned_lines[0],
                f"«{v.name}» esta en PreserveVariables pero el programa le "
                "asigna un valor. El Opta solo vuelca a flash cuando la "
                "consigna la escribe la plataforma, no cuando la calcula el "
                "programa: lo que quede guardado va a ser el ultimo valor "
                "escrito desde afuera, no el calculado.",
                code="preserve-calculada",
            )


# ─────────────────────────────────────────────────────────────────────────
#  Estructura del programa
# ─────────────────────────────────────────────────────────────────────────
def _estructura(result: ParseResult) -> None:
    prog, diags = result.program, result.diagnostics

    # crParsed = (crTableCount > 0) — OptaPakBus.ino:2967 — y en loop():2405
    # `if (crParsed) crbasic_execute_scan(); else read_sensors();`
    if not prog.tables:
        diags.error(
            1,
            "El programa no define ninguna DataTable, así que el Opta NO lo va a "
            "ejecutar: sin tablas cae al esquema fijo AI1-AI4/DI1-DI4/DO1-DO4/BattV "
            "e ignora por completo variables, If, relés y canales. Agregá al menos "
            "un bloque DataTable(...)/EndTable.",
            code="sin-datatable",
        )

    if prog.size_bytes > L.MAX_PROG_BYTES:
        diags.error(
            1,
            f"El programa ocupa {prog.size_bytes} bytes y el buffer del equipo es de "
            f"{L.MAX_PROG_BYTES}: lo que exceda no se va a almacenar y el archivo "
            "quedará cortado a la mitad de una línea.",
            code="programa-muy-grande",
        )

    if prog.scan_line == 0:
        diags.warning(
            1,
            "No hay ningún Scan(...) válido — el intervalo de muestreo será de 60 "
            "segundos por defecto.",
            code="sin-scan",
        )

    if not result.saw_begin_prog or not result.saw_end_prog:
        diags.info(
            1,
            "Falta BeginProg/EndProg. El Opta los ignora, pero conviene escribirlos "
            "para que el mismo .CR1 se lea igual en un CR1000 real.",
            code="sin-beginprog",
        )

    # ── Balance y profundidad de bloques If ─────────────────────────────
    stack: "list[int]" = []
    for st in prog.stmts:
        if st.type is StmtType.IF:
            if len(stack) >= L.IF_MAX_DEPTH:
                diags.error(
                    st.line,
                    f"Tercer nivel de If anidado: el equipo solo evalúa "
                    f"{L.IF_MAX_DEPTH} niveles, así que este If NO comprueba su "
                    "condición y su cuerpo se ejecuta siempre que los niveles "
                    "superiores sean verdaderos. Aplanalo con una variable "
                    "intermedia.",
                    code="if-muy-anidado",
                )
            stack.append(st.line)
        elif st.type is StmtType.ENDIF:
            if not stack:
                diags.error(
                    st.line,
                    "EndIf sin un If de bloque abierto. Ojo con la trampa clásica: "
                    "un «If (cond) Then Var=expr» de una sola línea NO lleva EndIf; "
                    "si se lo agregás, las líneas de abajo quedan sin condicionar.",
                    code="endif-suelto",
                )
            else:
                stack.pop()
        elif st.type in (StmtType.ELSEIF, StmtType.ELSE) and not stack:
            diags.error(
                st.line,
                f"{'ElseIf' if st.type is StmtType.ELSEIF else 'Else'} sin un If de "
                "bloque abierto.",
                code="else-suelto",
            )
    for line_no in stack:
        result.diagnostics.error(
            line_no, "Este If de bloque nunca se cierra con EndIf.", code="if-sin-endif"
        )

    n_stmts = len(prog.stmts)
    if n_stmts > L.MAX_STMTS * 0.85 and n_stmts <= L.MAX_STMTS:
        diags.info(
            1,
            f"{n_stmts} de {L.MAX_STMTS} instrucciones usadas (cada If, ElseIf, Else "
            "y EndIf cuenta como una). Al pasarte, el equipo descarta las siguientes "
            "sin avisar.",
            code="stmts-al-limite",
        )


# ─────────────────────────────────────────────────────────────────────────
#  Truncados silenciosos del lexer
# ─────────────────────────────────────────────────────────────────────────
def _lexico(result: ParseResult) -> None:
    diags = result.diagnostics

    for pl in result.parsed_lines:
        src = pl.src
        if src.truncated:
            diags.error(
                src.file_no,
                f"La línea tiene {len(src.raw)} caracteres y el equipo la corta en "
                f"{L.MAX_LINE_LEN}: se pierde «{src.raw[L.MAX_LINE_LEN:][:30]}…». "
                "Partila en dos líneas.",
                code="linea-larga",
            )
        if pl.keyword in _CON_ARGUMENTOS:
            if pl.args_overflow:
                diags.warning(
                    src.file_no,
                    f"Más de {L.MAX_ARGS} argumentos: el equipo descarta los que sobran.",
                    code="demasiados-args",
                )
            for got, full in zip(pl.args, pl.raw_args):
                if len(full) > L.MAX_ARG_LEN:
                    diags.error(
                        src.file_no,
                        f"El argumento «{full[:40]}» tiene {len(full)} caracteres y se "
                        f"corta en {L.MAX_ARG_LEN}, quedando «{got}» — que probablemente "
                        "no coincida con ningún nombre declarado.",
                        code="arg-truncado",
                    )

        # Unidad de tiempo no reconocida. cr_to_sec() (OptaPakBus.ino:2051)
        # solo mira MIN/HOU/DAY: cualquier otra cosa, incluida «Msec», cae
        # al `return val` final y se interpreta como SEGUNDOS.
        if pl.keyword == "SCAN" and len(pl.args) >= 2:
            _revisar_unidad(result, src.file_no, pl.args[1], "Scan")
        elif pl.keyword == "DATAINTERVAL" and len(pl.args) >= 3:
            _revisar_unidad(result, src.file_no, pl.args[2], "DataInterval")

        # Instrucciones de CRBasic real que el Opta no implementa: el
        # firmware solo dice "instruccion no reconocida", sin explicar nada.
        motivo = _FUERA_DE_ALCANCE.get(pl.keyword)
        if motivo:
            _explicar(result, src.file_no, motivo)


def _revisar_unidad(result: ParseResult, line_no: int, unidad: str, instr: str) -> None:
    u = unidad.upper()
    if u.startswith(("SEC", "MIN", "HOU", "DAY")):
        return
    extra = (" El Opta no puede escanear más rápido que una vez por segundo."
             if u.startswith("MSEC") else "")
    result.diagnostics.warning(
        line_no,
        f"{instr}: la unidad «{unidad}» no es Sec, Min, Hour ni Day, así que el equipo "
        f"la toma como SEGUNDOS.{extra}",
        code="unidad-no-reconocida",
    )


def _explicar(result: ParseResult, line_no: int, motivo: str) -> None:
    """Enriquece el diagnóstico genérico del firmware con el motivo real."""
    for d in result.diagnostics.items:
        if d.line == line_no and d.code in ("fw-desconocida", "fw-expr", "fw-asign-var"):
            d.message = f"El Opta ignora esta línea: {motivo}."
            return
    result.diagnostics.error(line_no, f"El Opta ignora esta línea: {motivo}.",
                             code="fuera-de-alcance")


# ─────────────────────────────────────────────────────────────────────────
#  Declaraciones
# ─────────────────────────────────────────────────────────────────────────
def _declaraciones(result: ParseResult) -> None:
    prog, diags = result.program, result.diagnostics

    # Public/Dim/Units con sangría: el firmware usa offsets fijos desde la
    # columna 0 (OptaPakBus.ino:2598 y :2631).
    for pl in result.parsed_lines:
        kw = pl.keyword
        if not pl.src.raw[:1] or not pl.src.raw[0].isspace():
            continue
        if cr_eq(kw, "PUBLIC") or cr_eq(kw, "DIM"):
            nombre = "Dim" if cr_eq(kw, "DIM") else "Public"
            diags.error(
                pl.src.file_no,
                f"{nombre} con sangría: el equipo arranca a leer desde la columna 0, "
                f"así que registra «{nombre}» como si fuera una variable más y puede "
                "perder el nombre real. Escribilo pegado al margen izquierdo, fuera "
                "del bloque Scan.",
                code="declaracion-indentada",
            )
        elif cr_eq(kw, "UNITS"):
            diags.error(
                pl.src.file_no,
                "Units con sangría: el equipo lee el nombre de la variable a partir "
                "del carácter 6 de la línea, así que con espacios adelante toma un "
                "nombre corrido y descarta la instrucción. Escribilo en la columna 0.",
                code="declaracion-indentada",
            )

    # Nombres truncados: strncpy() sin terminador (OptaPakBus.ino:2607).
    for v in prog.vars:
        if v.name_truncated:
            diags.error(
                v.decl_line,
                f"El nombre de variable supera los {L.MAX_VAR_NAME} caracteres y se "
                f"corta en «{v.name}». Toda referencia al nombre completo dejará de "
                "coincidir.",
                code="nombre-truncado",
            )
    for c in prog.consts:
        if c.name_truncated:
            diags.error(
                c.decl_line,
                f"El nombre de constante supera los {L.MAX_CONST_NAME} caracteres y "
                f"se corta en «{c.name}».",
                code="nombre-truncado",
            )
        if c.raw_value and not _LITERAL_RE.match(c.raw_value):
            diags.error(
                c.decl_line,
                f"Const «{c.name}»: el valor debe ser un número literal. «{c.raw_value}» "
                f"se lee con atof() y queda valiendo {c.value:g}. No se admiten "
                "expresiones ni referencias a otras constantes.",
                code="const-no-literal",
            )

    # Arreglos declarados: el «(N)» se descarta y queda un escalar.
    for pl in result.parsed_lines:
        if not (cr_eq(pl.keyword, "PUBLIC") or cr_eq(pl.keyword, "DIM")):
            continue
        for m in re.finditer(r"(\w+)\s*\(\s*\d+\s*\)", pl.src.text):
            diags.warning(
                pl.src.file_no,
                f"«{m.group(0)}»: el Opta descarta la dimensión y deja «{m.group(1)}» "
                "como una variable escalar. No hay arreglos ni indexación.",
                code="arreglo-descartado",
            )

    # Nombres repetidos: cr_find_var() siempre devuelve el primero.
    vistos: "dict[str, int]" = {}
    for v in prog.vars:
        clave = v.name.upper()
        if clave in vistos:
            diags.warning(
                v.decl_line,
                f"«{v.name}» ya estaba declarada en la línea {vistos[clave]}. El equipo "
                "siempre usa la primera, así que esta segunda queda inalcanzable.",
                code="variable-duplicada",
            )
        else:
            vistos[clave] = v.decl_line

    # Variables que nunca reciben un valor. El predicado es is_written: cubre el
    # canal analógico, el contador de pulsos, la batería, el router, el reloj,
    # VoltSE/VoltDiff, el destino de un MedianRun y la consigna de un
    # SetpointSchedule. Enumerar los casos a mano se desincroniza — con
    # MedianRun pasó: el destino de un filtro quedaba anunciado como que "va a
    # valer 0 siempre" cuando en realidad el equipo lo escribe antes de cada
    # statement.
    #
    # NO usar preserve_pointless acá. Contesta otra pregunta —«¿preservarla es
    # inútil?», la que decide si PreserveVariables rechaza el nombre— y para la
    # consigna de una agenda las dos respuestas son opuestas: le escribe el
    # equipo, así que no está muerta, pero preservarla es imprescindible porque
    # con el reloj sin sincronizar el equipo no le escribe y su último valor
    # tiene que sobrevivir un reinicio.
    for v in prog.vars:
        if v.is_written or v.assigned_lines:
            continue
        if v.name.upper() in ("PUBLIC", "DIM", "UNITS"):
            continue  # ya avisado como declaración indentada
        diags.info(
            v.decl_line,
            f"«{v.name}» no lee ninguna entrada ni recibe asignaciones: va a valer 0 "
            "siempre. Sirve igual como variable de comando por SetValues.",
            code="variable-muerta",
        )


# ─────────────────────────────────────────────────────────────────────────
#  Mapeo de hardware
# ─────────────────────────────────────────────────────────────────────────
def _hardware(result: ParseResult) -> None:
    prog, diags = result.program, result.diagnostics

    # Units=mA + destino de asignación → la variable pierde su canal.
    # La reconciliación de OptaPakBus.ino:2917 solo rescata hasVoltInstr.
    for v in prog.vars:
        if v.is4_20mA and v.no_auto_pin and not v.has_volt_instr and v.pin < 0:
            diags.error(
                v.assigned_lines[0] if v.assigned_lines else v.decl_line,
                f"«{v.name}» está declarada como 4-20mA pero además es destino de una "
                "asignación, y eso le quita el canal analógico: el equipo nunca la va "
                "a leer del sensor y va a quedar en 0. Agregale AIChannel("
                f"{v.name}, N) con N=1-8, o usá otra variable para el cálculo.",
                code="units-ma-sin-canal",
            )

    # Se agotaron los A0-A7 (break silencioso en OptaPakBus.ino:2942).
    sin_canal = [
        v for v in prog.vars
        if v.pin < 0 and not v.is_pulse_count
        and (v.is4_20mA or v.has_volt_instr) and not v.no_auto_pin
    ]
    for v in sin_canal:
        diags.error(
            v.decl_line,
            f"«{v.name}» pide un canal analógico pero ya no quedan libres: el Opta "
            f"solo tiene {L.N_ANALOG} (A0-A7) y la asignación automática corta sin "
            "avisar. La variable va a quedar en 0.",
            code="sin-canales-libres",
        )

    # Colisiones de canal. used[] arranca en false y NUNCA se marca para los
    # canales explícitos ni para los de PulseCount (OptaPakBus.ino:2920),
    # así que un canal pedido a mano se puede volver a repartir.
    # Desde v1.6.9 los canales comprometidos quedan reservados, así que el
    # reparto automático ya no puede pisarlos. Lo que sí puede seguir
    # chocando es lo que el propio programa fija dos veces a mano, y ahí hay
    # que distinguir: dos mediciones del mismo borne es un patrón legítimo
    # (lo usa programa_diagnostico.CR1), pero mezclar conteo de pulsos o
    # excitación con una medición no puede funcionar.
    ocupantes: "dict[int, list[tuple[str, str, int]]]" = {}
    for v in prog.vars:
        if v.pin >= 0:
            ocupantes.setdefault(v.pin, []).append((v.name, "medición", v.decl_line))
        if v.is_pulse_count and v.pulse_pin >= 0:
            ocupantes.setdefault(v.pulse_pin, []).append(
                (v.name, "conteo de pulsos", v.decl_line))
    for canal, linea in prog.excite_channels.items():
        ocupantes.setdefault(canal, []).append(("ExciteCh", "excitación", linea))

    for canal, lista in sorted(ocupantes.items()):
        if len(lista) < 2:
            continue
        detalle = ", ".join(f"«{n}» ({t})" for n, t, _ in lista)
        tipos = {t for _, t, _ in lista}
        linea = lista[-1][2]

        if "excitación" in tipos and "conteo de pulsos" in tipos:
            diags.error(
                linea,
                f"El canal A{canal} está declarado como excitación y además como "
                "contador de pulsos. La salida gana y el conteo nunca ve un flanco: "
                "el equipo lo registra y deja esa variable sin contar. La excitación "
                "va en un canal y el conteo en otro.",
                code="excitacion-y-conteo",
            )
        elif "excitación" in tipos:
            diags.error(
                linea,
                f"El canal A{canal} está declarado como excitación con ExciteCh y "
                f"además mide algo: {detalle}. El borne queda forzado a 3,3 V, así "
                "que esa medición no significa nada.",
                code="excitacion-y-medicion",
            )
        elif "conteo de pulsos" in tipos and "medición" in tipos:
            diags.error(
                linea,
                f"El canal A{canal} lo usan a la vez {detalle}. Un borne no puede "
                "contar pulsos y medir una señal analógica al mismo tiempo.",
                code="colision-canal",
            )
        else:
            diags.info(
                linea,
                f"{detalle} leen las dos el canal A{canal}. Está bien si es a "
                "propósito —por ejemplo el lazo en mA y el mismo nodo en volts, como "
                "hace el programa de diagnóstico—, porque las dos lo piden "
                "explícitamente.",
                code="canal-compartido",
            )

    # Una variable con «att» que se quedó sin el canal de alimentación.
    if result.att_sin_canal:
        v = prog.find_var(result.att_sin_canal)
        diags.warning(
            v.decl_line if v else 1,
            f"«{result.att_sin_canal}» tiene «att» en el nombre, pero A7 ya está "
            "ocupado, así que no recibe el canal de alimentación y va a quedar en 0. "
            f"Si el divisor está cableado en otro borne, declaralo con "
            f"Battery({result.att_sin_canal}, N).",
            code="att-sin-canal",
        )

    for v in prog.vars:
        # El truco «att» exige que la variable NO sea mA ni VoltDiff
        # (OptaPakBus.ino:2924).
        tiene_att = "att" in v.name or "ATT" in v.name or "Att" in v.name
        if tiene_att and not v.is_batt_v and (v.is4_20mA or v.has_volt_instr):
            diags.warning(
                v.decl_line,
                f"«{v.name}» tiene «att» en el nombre, pero como también tiene "
                "Units=mA o VoltDiff/VoltSE queda excluida del truco del nombre: no "
                "se le aplica el divisor 3.351 y no va a reportar el voltaje real de "
                f"alimentación. Declaralo explícito con Battery({v.name}, N), que es "
                "lo que corresponde desde el firmware 1.6.9.",
                code="att-con-lectura",
            )
        # Nombre con pinta de relé pero sin ningún PortSet que lo accione.
        # Es la trampa de la migración a v1.7.0: el programa viejo asignaba
        # DO1 = 1 y el relé se movía solo; ahora eso no acciona nada y el
        # síntoma —el relé quieto— no lleva a la causa.
        if (len(v.name) >= 3 and v.name[:2].upper() == "DO"
                and v.name[2].isdigit() and "1" <= v.name[2] <= "4"):
            n = int(v.name[2])
            if not prog.relay_map()[n - 1]:
                diags.warning(
                    v.decl_line,
                    f"«{v.name}» parece manejar el relé {n} pero ningún PortSet lo "
                    "acciona: desde v1.7.0 el nombre de la variable no mueve "
                    f"hardware. Agregá PortSet({n}, {v.name}) dentro del Scan.",
                    code="rele-sin-portset",
                )

    # Reloj sin zona horaria: devuelve UTC, no la hora local. Si el programa
    # compara contra un horario de operación, dispara corrido.
    relojes = [v for v in prog.vars if v.clock_field]
    if relojes and prog.network.utc_offset is None:
        diags.warning(
            relojes[0].decl_line,
            "El programa usa ClockYYMMDD/ClockHHMM pero no define UTCOffset=: "
            "esas variables traen hora UTC, no la local. Si la lógica compara "
            "contra un horario de operación, va a disparar corrida.",
            code="reloj-sin-utcoffset",
        )
    elif prog.network.utc_offset is not None and not relojes:
        diags.info(
            prog.network.utc_offset_line,
            "UTCOffset= está definida pero ninguna instrucción "
            "ClockYYMMDD/ClockHHMM la usa. No afecta la hora de los registros, "
            "que siempre se archivan en UTC.",
            code="utcoffset-sin-reloj",
        )

    # VoltDiff/VoltSE con menos de 6 argumentos: Mult y Offset se descartan
    # (OptaPakBus.ino:2732) y el escalado queda en 1.0/0.0.
    for pl in result.parsed_lines:
        if cr_eq(pl.keyword, "VOLTDIFF") or cr_eq(pl.keyword, "VOLTSE"):
            if 4 <= len(pl.args) < 6:
                diags.warning(
                    pl.src.file_no,
                    f"{pl.keyword.title()} con {len(pl.args)} argumentos: el equipo solo "
                    "lee Mult y Offset si hay 6 o más, así que acá quedan en 1.0 y 0.0 "
                    "y el valor sale sin escalar. Escribí la instrucción completa.",
                    code="volt-sin-escala",
                )
        elif cr_eq(pl.keyword, "PULSECOUNT") and len(pl.args) >= 3:
            cs = pl.args[2]
            if not re.match(r"^[Pp]?[1-8]$", cs):
                diags.warning(
                    pl.src.file_no,
                    f"PulseCount: el canal «{cs}» no es válido y el equipo cae a A0 sin "
                    "avisar. Usá P1 a P8.",
                    code="pulse-canal-invalido",
                )
            if len(pl.args) < 6:
                diags.info(
                    pl.src.file_no,
                    "PulseCount sin Mult/Offset (argumentos 6 y 7): el valor será el "
                    "conteo crudo de pulsos desde el scan anterior.",
                    code="pulse-sin-escala",
                )


# ─────────────────────────────────────────────────────────────────────────
#  Tablas de datos
# ─────────────────────────────────────────────────────────────────────────
def _tablas(result: ParseResult) -> None:
    prog, diags = result.program, result.diagnostics

    for t in prog.tables:
        # crbasic_execute_scan() solo archiva `if (tbl->intervalSec > 0)`
        # (OptaPakBus.ino:3168).
        if t.interval_sec == 0:
            diags.error(
                t.decl_line,
                f"La tabla «{t.name}» no tiene DataInterval, así que su intervalo es 0 "
                "y el equipo NO va a archivar ni un solo registro. Agregá "
                "DataInterval(0, N, Min, 0) dentro del bloque.",
                code="tabla-sin-intervalo",
            )
        elif t.interval_sec < prog.scan_seconds:
            diags.warning(
                t.interval_line or t.decl_line,
                f"La tabla «{t.name}» archiva cada {t.interval_sec}s pero el Scan corre "
                f"cada {prog.scan_seconds:g}s: no puede haber más de un registro por "
                "scan, así que el intervalo real será el del Scan.",
                code="intervalo-menor-que-scan",
            )
        if not t.fields:
            diags.warning(
                t.decl_line,
                f"La tabla «{t.name}» no declara ningún campo: no se archiva nada.",
                code="tabla-sin-campos",
            )
        if t.end_line == 0:
            diags.error(
                t.decl_line,
                f"La tabla «{t.name}» nunca se cierra con EndTable: todo lo que siga "
                "se va a interpretar como campos de esta tabla.",
                code="tabla-sin-endtable",
            )
        if t.name_truncated:
            diags.error(
                t.decl_line,
                f"El nombre de tabla supera los {L.MAX_TABLE_NAME} caracteres y se "
                f"corta en «{t.name}».",
                code="nombre-truncado",
            )

    # Reps distinto de 1 en un campo: no hay soporte de arreglos.
    for pl in result.parsed_lines:
        if pl.keyword in ("SAMPLE", "AVERAGE", "MAXIMUM", "MINIMUM", "TOTALIZE"):
            if len(pl.args) >= 2 and pl.args[0].strip() != "1":
                diags.warning(
                    pl.src.file_no,
                    f"{pl.keyword.title()}: reps = «{pl.args[0]}». El Opta no maneja "
                    "arreglos y siempre archiva un solo valor; poné 1.",
                    code="reps-distinto-1",
                )


# ─────────────────────────────────────────────────────────────────────────
#  Condiciones
# ─────────────────────────────────────────────────────────────────────────
def _condiciones(result: ParseResult) -> None:
    diags = result.diagnostics

    for pl in result.parsed_lines:
        texto = pl.src.text
        kw = pl.keyword
        if not (cr_eq(kw, "IF") or cr_eq(kw, "ELSEIF")):
            if cr_eq(kw, "ELSE"):
                cola = texto.lstrip()[4:].strip()
                if cola:
                    if cr_eq(keyword(cola), "IF"):
                        diags.error(
                            pl.src.file_no,
                            "«Else If» en dos palabras: el equipo lo toma como un Else "
                            "incondicional y tira la condición, así que esta rama se "
                            "ejecuta siempre. Escribí «ElseIf» junto.",
                            code="else-if-separado",
                        )
                    else:
                        diags.warning(
                            pl.src.file_no,
                            f"El equipo descarta lo que sigue a Else en la misma línea: "
                            f"«{cola}».",
                            code="else-con-cola",
                        )
            continue

        then_pos = texto.upper().find(" THEN")
        if then_pos < 0:
            continue
        inicio = len(texto) - len(texto.lstrip())
        inicio += 2 if cr_eq(kw, "IF") else 6
        cond = texto[inicio:then_pos].strip()

        n_and = len(re.findall(r"\sAND\s", cond, re.IGNORECASE))
        n_or = len(re.findall(r"\sOR\s", cond, re.IGNORECASE))

        if n_and and n_or:
            diags.error(
                pl.src.file_no,
                "AND y OR mezclados en la misma condición: el equipo se queda con el "
                "primer AND, mete la segunda comparación como si fuera un número y "
                "descarta el resto en silencio. Partilo con una variable intermedia.",
                code="and-or-mezclados",
            )
        elif n_and + n_or > 1:
            diags.error(
                pl.src.file_no,
                f"{n_and + n_or + 1} condiciones en un mismo If: el equipo solo evalúa "
                "las dos primeras y descarta el resto sin avisar. Aplanalo con una "
                "variable intermedia.",
                code="demasiadas-condiciones",
            )

        if len(cond) > 63:
            diags.error(
                pl.src.file_no,
                f"La condición tiene {len(cond)} caracteres y el equipo la corta en 63: "
                "va a quedar mal formada y la línea entera se descarta.",
                code="condicion-larga",
            )
        else:
            for parte in re.split(r"\s+(?:AND|OR)\s+", cond, flags=re.IGNORECASE):
                if len(parte) > 39:
                    diags.error(
                        pl.src.file_no,
                        f"La comparación «{parte[:45]}…» tiene {len(parte)} caracteres y "
                        "el equipo la corta en 39.",
                        code="condicion-larga",
                    )


# ─────────────────────────────────────────────────────────────────────────
#  Configuración de red
# ─────────────────────────────────────────────────────────────────────────
def _red(result: ParseResult) -> None:
    net, diags = result.program.network, result.diagnostics

    if not net.provisioned:
        diags.warning(
            1,
            "Falta la directiva ServerPort=. Su sola presencia marca al equipo como "
            "provisionado; sin ella se va a conectar al puerto de provisión (4789) en "
            "vez del operativo.",
            code="sin-serverport",
        )
    elif net.server_port == 4789:
        diags.warning(
            net.port_line,
            "ServerPort=4789 es el puerto de provisión, no uno operativo.",
            code="puerto-de-provision",
        )
    if not net.server_host:
        diags.warning(
            1,
            "Falta ServerHost= — el equipo va a usar el host que tenga compilado por "
            "defecto en el firmware.",
            code="sin-serverhost",
        )
    if net.pakbus_address is None:
        diags.warning(
            1,
            "Falta PakBusAddress= — tiene que coincidir con el node_id del logger "
            "configurado en el servidor.",
            code="sin-pakbusaddress",
        )
    if not net.station_name:
        diags.info(
            1,
            "Falta StationName= — el equipo reportará el nombre por defecto del "
            "firmware.",
            code="sin-stationname",
        )


def analyze(text: str, size_bytes: "int | None" = None) -> ParseResult:
    """Parsea y aplica todas las reglas. Punto de entrada del IDE."""
    from .parser import parse

    return lint(parse(text, size_bytes))
