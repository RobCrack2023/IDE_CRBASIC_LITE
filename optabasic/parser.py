"""Port de parse_crbasic() (OptaPakBus.ino) a Python.

Reproduce el parser del firmware línea por línea, incluidos sus truncados,
sus conversiones parciales y el orden exacto en que evalúa las palabras
clave. Los diagnósticos con source=FIRMWARE llevan el mismo texto que el
equipo escribirá en su .HLOG, para poder cotejarlos uno a uno.

Las reglas adicionales del IDE — las que avisan de cosas que el firmware
acepta en silencio pero no hacen lo que el autor espera — están en lint.py.
"""

from dataclasses import dataclass, field

from . import limits as L
from .cutil import c_atof, c_atoi, cr_eq, rstrip_ctrl, stristr, strncpy
from .diagnostics import Diagnostic, DiagnosticList, Severity, Source
from .expr import compile_expr
from .lexer import (ParsedLine, SourceLine, args_of, keyword, paren,
                    parse_line, split_lines)
from .model import (
    Cond,
    CmpOp,
    Const,
    Field,
    Program,
    Stmt,
    StmtType,
    Table,
    Var,
)

_TYPE_SUFFIXES = ("AS", "FLOAT", "LONG", "STRING", "BOOLEAN")
_OUTPUT_KEYWORDS = {
    "SAMPLE": "Sample",
    "AVERAGE": "Average",
    "MAXIMUM": "Maximum",
    "MINIMUM": "Minimum",
    "TOTALIZE": "Totalize",
}
#: Battery salió de esta lista en v1.6.9: pasó de no-op a instrucción real.
_NOOP_KEYWORDS = ("BEGINPROG", "ENDPROG", "NEXTSCAN", "CALLTABLE")
_RECOGNIZED_UNSIMULATED = ("BRHALF", "REALTIME", "PANELTEMP", "SW12")
#: Telemetría del router Teltonika (RUT200) por su API REST local, v1.6.14.
#: A diferencia de _RECOGNIZED_UNSIMULATED, estas SÍ se ejecutan: la variable
#: se actualiza desde el poll HTTP cada 60 s y no consume canal analógico.
_MODEM_INSTR = ("MODEMRSSI", "MODEMRSRP", "MODEMRSRQ", "MODEMSINR",
                "MODEMTEMP", "MODEMNETGEN")
#: Reloj del programa (v1.7.8). La variable se refresca cada scan con la
#: fecha/hora LOCAL, según UTCOffset=; vale 0 hasta que el reloj sincroniza.
_CLOCK_INSTR = ("CLOCKYYMMDD", "CLOCKHHMM")
_COND_OPS = ((">=", CmpOp.GE), ("<=", CmpOp.LE), ("<>", CmpOp.NE),
             (">", CmpOp.GT), ("<", CmpOp.LT), ("=", CmpOp.EQ))


@dataclass
class ParseResult:
    program: Program
    diagnostics: DiagnosticList
    lines: "list[SourceLine]" = field(default_factory=list)
    parsed_lines: "list[ParsedLine]" = field(default_factory=list)
    #: Palabras clave vistas, para las reglas de lint.py.
    saw_begin_prog: bool = False
    saw_end_prog: bool = False
    #: Canales pedidos explícitamente (AIChannel/VoltDiff/Battery) por variable.
    explicit_pins: "dict[int, int]" = field(default_factory=dict)
    #: Variable con «att» en el nombre que se quedó sin el canal de batería
    #: porque A7 ya estaba tomado.
    att_sin_canal: str = ""


def parse(text: str, size_bytes: "int | None" = None) -> ParseResult:
    """Parsea el programa.

    `size_bytes` es el tamaño real del archivo tal como se va a subir al
    equipo. Importa porque el buffer del firmware son 8192 bytes y un .CR1
    en cp1252 no ocupa lo mismo que en UTF-8. Si no se indica, se estima
    en cp1252, que es lo que escribe el CRBasic Editor.
    """
    return _Parser(text, size_bytes).run()


class _Parser:
    def __init__(self, text: str, size_bytes: "int | None" = None):
        self.text = text
        self.prog = Program()
        if size_bytes is None:
            try:
                size_bytes = len(text.encode("cp1252"))
            except UnicodeEncodeError:
                size_bytes = len(text.encode("utf-8"))
        self.prog.size_bytes = size_bytes
        self.diags = DiagnosticList()
        self.result = ParseResult(program=self.prog, diagnostics=self.diags)
        self.in_table = False
        self.cur_tbl = -1
        self.line: SourceLine = None  # type: ignore[assignment]

    # ── Diagnóstico con el texto exacto del firmware ────────────────────
    def issue(self, reason: str, severity: Severity = Severity.ERROR, code: str = "",
              mensaje: str = "") -> None:
        """Registra lo mismo que el firmware escribirá en su .HLOG.

        `mensaje` permite contar qué pasa de verdad cuando el equipo
        registra la línea como «ignorada» pero igual aplica parte de ella.
        """
        self.diags.add(
            Diagnostic(
                line=self.line.file_no,
                fw_line=self.line.fw_no,
                severity=severity,
                message=mensaje or f"El Opta ignora esta línea: {reason}",
                source=Source.FIRMWARE,
                code=code or "fw",
                fragment=self.line.text.strip(),
                fw_reason=reason,
            )
        )

    def run(self) -> ParseResult:
        self.result.lines = split_lines(self.text)

        for src in self.result.lines:
            self.line = src
            pl = parse_line(src)
            self.result.parsed_lines.append(pl)
            if not pl.keyword:
                continue
            self.dispatch(pl)

        self.assign_channels()
        return self.result

    # ── Bucle principal: mismo orden de comparación que el firmware ─────
    def dispatch(self, pl: ParsedLine) -> None:
        kw = pl.keyword
        line = pl.src.text

        if cr_eq(kw, "CONST"):
            self.do_const(line)
        elif cr_eq(kw, "STATIONNAME") or kw.startswith("STATIONNAME="):
            self.do_directive_str(line, "StationName", L.MAX_STATION_NAME)
        elif cr_eq(kw, "SERVERHOST") or kw.startswith("SERVERHOST="):
            self.do_directive_str(line, "ServerHost", L.MAX_HOST_LEN)
        elif cr_eq(kw, "SERVERPORT") or kw.startswith("SERVERPORT="):
            self.do_directive_int(line, "ServerPort", 1, 65535)
        elif cr_eq(kw, "PAKBUSADDRESS") or kw.startswith("PAKBUSADDRESS="):
            self.do_directive_int(line, "PakBusAddress", 1, 4094)
        elif cr_eq(kw, "ROUTERUSER") or kw.startswith("ROUTERUSER="):
            self.do_directive_str(line, "RouterUser", L.MAX_ROUTER_CRED)
        elif cr_eq(kw, "ROUTERPASS") or kw.startswith("ROUTERPASS="):
            self.do_directive_str(line, "RouterPass", L.MAX_ROUTER_CRED)
        elif cr_eq(kw, "UTCOFFSET") or kw.startswith("UTCOFFSET="):
            self.do_utcoffset(line)
        elif cr_eq(kw, "PUBLIC") or cr_eq(kw, "DIM"):
            self.do_public(line, kw)
        elif cr_eq(kw, "UNITS"):
            self.do_units(line)
        elif cr_eq(kw, "SCAN"):
            self.do_scan(pl)
        elif cr_eq(kw, "DATATABLE"):
            self.do_datatable(pl)
        elif cr_eq(kw, "DATAINTERVAL"):
            self.do_datainterval(pl)
        elif (self.in_table and self.cur_tbl >= 0 and len(pl.args) >= 2
              and kw in _OUTPUT_KEYWORDS):
            self.do_field(pl)
        elif cr_eq(kw, "ENDTABLE"):
            self.in_table = False
            if self.cur_tbl >= 0:
                self.prog.tables[self.cur_tbl].end_line = self.line.file_no
            self.cur_tbl = -1
        elif cr_eq(kw, "VOLTDIFF") or cr_eq(kw, "VOLTSE"):
            self.do_volt(pl)
        elif cr_eq(kw, "AICHANNEL"):
            self.do_aichannel(pl)
        elif cr_eq(kw, "PORTSET"):
            self.do_portset(pl)
        elif cr_eq(kw, "PULSECOUNT"):
            self.do_pulsecount(pl)
        elif cr_eq(kw, "PULSEEDGE"):
            self.do_pulseedge(pl)
        elif cr_eq(kw, "EXCITECH"):
            self.do_excitech(pl)
        elif cr_eq(kw, "BATTERY"):
            self.do_battery(pl)
        elif kw in _MODEM_INSTR:
            self.do_modem(pl, kw)
        elif kw in _CLOCK_INSTR:
            self.do_clock(pl, kw)
        elif kw in _NOOP_KEYWORDS:
            if kw == "BEGINPROG":
                self.result.saw_begin_prog = True
            elif kw == "ENDPROG":
                self.result.saw_end_prog = True
            # no-op deliberado: el firmware no lo registra como error
        elif kw in _RECOGNIZED_UNSIMULATED:
            if pl.args:
                v = self.prog.find_var(pl.args[0])
                if v:
                    v.no_auto_pin = True
            self.issue("reconocida pero no simulada", Severity.WARNING, "fw-no-simulada")
        elif cr_eq(kw, "ELSEIF"):
            self.do_elseif(line)
        elif cr_eq(kw, "ELSE"):
            self.push_struct(StmtType.ELSE)
        elif cr_eq(kw, "ENDIF"):
            self.push_struct(StmtType.ENDIF)
        elif cr_eq(kw, "END"):
            after = line.lstrip()[3:]
            if cr_eq(keyword(after), "IF"):
                self.push_struct(StmtType.ENDIF)
            else:
                self.issue("instruccion no reconocida", code="fw-desconocida")
        else:
            self.do_statement_line(line, kw)

    # ── Const ───────────────────────────────────────────────────────────
    def do_const(self, line: str) -> None:
        eq = line.find("=")
        if eq < 0:
            self.issue("Const sin '='", code="fw-const")
            return
        if len(self.prog.consts) >= L.MAX_CONSTS:
            self.issue("demasiadas Const, max 16", code="fw-const-limite")
            return
        # El firmware salta la indentación antes del offset fijo, así que
        # Const SÍ tolera sangría (a diferencia de Public/Dim/Units).
        stripped = line.lstrip()
        skipped = len(line) - len(stripped)
        vs = skipped + 5
        while vs < len(line) and line[vs].isspace():
            vs += 1
        name = strncpy(rstrip_ctrl(line[vs:eq]), L.MAX_CONST_NAME)
        if not name:
            self.issue("Const sin nombre", code="fw-const")
            return
        raw_value = line[eq + 1:].strip()
        self.prog.consts.append(
            Const(
                name=name,
                value=c_atof(line[eq + 1:]),
                decl_line=self.line.file_no,
                raw_value=raw_value,
                name_truncated=len(rstrip_ctrl(line[vs:eq])) > L.MAX_CONST_NAME,
            )
        )

    # ── Directivas de red ───────────────────────────────────────────────
    def do_directive_str(self, line: str, which: str, maxlen: int) -> None:
        eq = line.find("=")
        if eq < 0:
            self.issue(f"{which} sin '='", code="fw-directiva")
            return
        value = strncpy(line[eq + 1:].strip(), maxlen)
        net = self.prog.network
        if which == "StationName":
            net.station_name, net.station_line = value, self.line.file_no
        elif which == "RouterUser":
            net.router_user, net.router_user_line = value, self.line.file_no
        elif which == "RouterPass":
            net.router_pass, net.router_pass_line = value, self.line.file_no
        else:
            net.server_host, net.host_line = value, self.line.file_no

    def do_directive_int(self, line: str, which: str, lo: int, hi: int) -> None:
        eq = line.find("=")
        if eq < 0:
            self.issue(f"{which} sin '='", code="fw-directiva")
            return
        v = c_atoi(line[eq + 1:])
        net = self.prog.network
        if not (lo <= v <= hi):
            self.issue(f"{which} fuera de rango {lo}-{hi}", code="fw-directiva-rango")
            if which == "ServerPort":
                net.port_line = self.line.file_no
            else:
                net.address_line = self.line.file_no
            return
        if which == "ServerPort":
            net.server_port, net.port_line = v, self.line.file_no
        else:
            net.pakbus_address, net.address_line = v, self.line.file_no

    # ── Public / Dim ────────────────────────────────────────────────────
    def do_public(self, line: str, kw: str) -> None:
        # Réplica exacta: el firmware avanza desde la COLUMNA 0 hasta el
        # primer espacio. Si la línea está indentada, ese bucle no avanza
        # nada y "Public" termina registrado como nombre de variable.
        vp = 0
        while vp < len(line) and not line[vp].isspace():
            vp += 1
        while vp < len(line) and line[vp].isspace():
            vp += 1
        tmp = line[vp:][:119]

        dropped = False
        for tok in tmp.replace(",", " ").replace("\t", " ").split():
            if any(cr_eq(tok, s) for s in _TYPE_SUFFIXES):
                continue
            vn = strncpy(tok, L.MAX_VAR_NAME)
            arr = vn.find("(")
            if arr >= 0:
                vn = vn[:arr]
            if not vn:
                continue
            if len(self.prog.vars) >= L.MAX_VARS:
                dropped = True
                continue
            self.prog.vars.append(
                Var(
                    name=vn,
                    decl_line=self.line.file_no,
                    decl_kw="Dim" if cr_eq(kw, "DIM") else "Public",
                    name_truncated=len(tok.split("(")[0]) > L.MAX_VAR_NAME,
                )
            )
        if dropped:
            self.issue("limite de variables (64) alcanzado", code="fw-vars-limite")

    # ── Units ───────────────────────────────────────────────────────────
    def do_units(self, line: str) -> None:
        eq = line.find("=")
        if eq < 0:
            self.issue("Units sin '='", code="fw-units")
            return
        # Offset fijo line+5: con sangría toma un nombre corrido.
        vs = 5
        while vs < len(line) and line[vs].isspace():
            vs += 1
        name = strncpy(rstrip_ctrl(line[vs:eq]), L.MAX_VAR_NAME) if eq > vs else ""
        unit = strncpy(line[eq + 1:].lstrip(), L.MAX_UNITS_LEN)
        v = self.prog.find_var(name)
        if v is None:
            self.issue("Units: variable no declarada", code="fw-units-var")
            return
        v.units = unit
        v.units_line = self.line.file_no
        if cr_eq(unit, "mA"):
            v.is4_20mA = True

    # ── Scan ────────────────────────────────────────────────────────────
    def do_scan(self, pl: ParsedLine) -> None:
        if len(pl.args) < 2:
            self.issue("Scan: faltan argumentos", code="fw-scan")
            return
        ms = _to_sec(c_atoi(pl.args[0]), pl.args[1]) * 1000
        self.prog.scan_interval_ms = max(ms, L.MIN_SCAN_MS)
        self.prog.scan_line = self.line.file_no

    # ── DataTable / DataInterval / campos ───────────────────────────────
    def do_datatable(self, pl: ParsedLine) -> None:
        if not pl.args:
            self.issue("DataTable sin nombre", code="fw-tabla")
            return
        if len(self.prog.tables) >= L.MAX_TABLES:
            self.issue("demasiadas DataTable, max 4", code="fw-tabla-limite")
            return
        sz = c_atoi(pl.args[2]) if len(pl.args) >= 3 else L.DEFAULT_TABLE_SIZE_OMITTED
        self.prog.tables.append(
            Table(
                name=strncpy(pl.args[0], L.MAX_TABLE_NAME),
                size=sz if sz > 0 else L.DEFAULT_TABLE_SIZE,
                decl_line=self.line.file_no,
                name_truncated=len(pl.args[0]) > L.MAX_TABLE_NAME,
            )
        )
        self.cur_tbl = len(self.prog.tables) - 1
        self.in_table = True

    def do_datainterval(self, pl: ParsedLine) -> None:
        if not self.in_table or self.cur_tbl < 0:
            self.issue("DataInterval fuera de un DataTable", code="fw-intervalo")
            return
        if len(pl.args) < 3:
            self.issue("DataInterval: faltan argumentos", code="fw-intervalo")
            return
        tbl = self.prog.tables[self.cur_tbl]
        tbl.interval_sec = _to_sec(c_atoi(pl.args[1]), pl.args[2])
        tbl.interval_line = self.line.file_no

    def do_field(self, pl: ParsedLine) -> None:
        tbl = self.prog.tables[self.cur_tbl]
        if len(tbl.fields) >= L.MAX_FIELDS:
            self.issue("demasiados campos, max 32", code="fw-campos-limite")
            return
        name = strncpy(pl.args[1], L.MAX_FIELD_NAME)
        resolved = self.prog.find_var(pl.args[1]) is not None
        tbl.fields.append(
            Field(
                name=name,
                processing=_OUTPUT_KEYWORDS[pl.keyword],
                type_code=_type_code(pl.args[2]) if len(pl.args) >= 3 else 9,
                type_name=pl.args[2] if len(pl.args) >= 3 else "",
                line=self.line.file_no,
                resolved=resolved,
            )
        )
        if not resolved:
            self.issue("campo: variable no declarada", Severity.WARNING, "fw-campo-var")

    # ── Entradas analógicas ─────────────────────────────────────────────
    def do_volt(self, pl: ParsedLine) -> None:
        if len(pl.args) < 4:
            self.issue("VoltDiff/VoltSE: faltan argumentos", code="fw-volt")
            return
        v = self.prog.find_var(pl.args[0])
        if v is None:
            self.issue("VoltDiff/VoltSE: var no declarada", code="fw-volt-var")
            return
        v.has_volt_instr = True
        v.hw_instr_lines.append(self.line.file_no)
        ch = c_atoi(pl.args[3])
        if 1 <= ch <= 8:
            v.pin = ch - 1
            self.result.explicit_pins[self.prog.var_index(v.name)] = ch - 1
        if len(pl.args) >= 6:
            v.mult = c_atof(pl.args[-2])
            v.offset = c_atof(pl.args[-1])

    def do_aichannel(self, pl: ParsedLine) -> None:
        if len(pl.args) < 2:
            self.issue("AIChannel: faltan argumentos", code="fw-aichannel")
            return
        v = self.prog.find_var(pl.args[0])
        if v is None:
            self.issue("AIChannel: var no declarada", code="fw-aichannel-var")
            return
        ch = c_atoi(pl.args[1])
        if 1 <= ch <= 8:
            v.pin = ch - 1
            v.hw_instr_lines.append(self.line.file_no)
            self.result.explicit_pins[self.prog.var_index(v.name)] = ch - 1
        else:
            self.issue("AIChannel: canal fuera de rango 1-8", code="fw-aichannel-rango")

    # ── Relés ───────────────────────────────────────────────────────────
    def do_portset(self, pl: ParsedLine, base: "Stmt | None" = None) -> None:
        """PortSet(Rele, Valor) — instrucción ejecutable desde v1.7.0.

        `base` viene con la condición ya parseada cuando la llamada sale de un
        If de una línea; es None para un PortSet suelto.

        Hasta v1.6.18 esto no era una instrucción: ligaba una variable a un
        relé, el argumento de valor se ignoraba, y el relé seguía el valor de
        esa variable en cada scan.
        """
        if len(pl.args) < 2:
            self.issue("PortSet: faltan argumentos (rele, valor)", code="fw-portset")
            return
        rele_txt = pl.args[0].strip()
        if not rele_txt[:1].isdigit():
            # Casi siempre es un programa anterior a v1.7.0. El síntoma —el
            # relé quieto— no lleva a la causa solo, así que se nombra.
            viejo = self.prog.find_var(rele_txt) is not None
            self.issue(
                "PortSet: 1er arg no es el numero de rele",
                code="fw-portset-forma-vieja" if viejo else "fw-portset-rele",
                mensaje=(
                    f"El primer argumento de PortSet es el relé (1-4), no una variable. "
                    f"«{rele_txt}» es la forma anterior a v1.7.0: el equipo registra la "
                    f"línea y no mueve ningún relé. Escribí PortSet(N, {rele_txt})."
                ) if viejo else (
                    f"«{rele_txt}» no es un número de relé. PortSet(N, Valor) con N de 1 a 4."
                ),
            )
            return
        r = c_atoi(rele_txt)
        if not (1 <= r <= L.N_RELAYS):
            self.issue("PortSet: rele fuera de rango 1-4", code="fw-portset-rango")
            return

        expr_text = pl.args[1]
        res = self.compile(expr_text)
        if not res.ok:
            self.issue("PortSet: valor invalido", code="fw-portset-valor")
            return
        if len(self.prog.stmts) >= L.MAX_STMTS:
            self.issue(f"limite de instrucciones ({L.MAX_STMTS})", code="fw-stmts-limite")
            return
        self.mark_reads(res.refs)
        st = base if base is not None else Stmt(line=self.line.file_no, type=StmtType.ASSIGN)
        st.type = StmtType.PORTSET
        st.relay = r - 1
        st.expr_tokens = res.tokens
        st.expr_text = expr_text.strip()
        self.prog.stmts.append(st)

    # ── Reloj del programa ──────────────────────────────────────────────
    def do_utcoffset(self, line: str) -> None:
        """UTCOffset=N — horas respecto de UTC, admite decimales."""
        eq = line.find("=")
        if eq < 0:
            self.issue("UTCOffset sin '='", code="fw-utcoffset")
            return
        v = c_atof(line[eq + 1:])
        net = self.prog.network
        net.utc_offset_line = self.line.file_no
        if not (-14.0 <= v <= 14.0):
            self.issue("UTCOffset fuera de rango -14..14", code="fw-utcoffset-rango")
            return
        net.utc_offset = v

    def do_clock(self, pl: ParsedLine, kw: str) -> None:
        """ClockYYMMDD(Dest) / ClockHHMM(Dest) — el firmware refresca Dest."""
        if not pl.args:
            self.issue("Clock*: falta argumento (Dest)", code="fw-clock")
            return
        v = self.prog.find_var(pl.args[0])
        if v is None:
            self.issue("Clock*: var no declarada", code="fw-clock-var")
            return
        v.clock_field = kw
        v.no_auto_pin = True
        v.hw_instr_lines.append(self.line.file_no)

    # ── Telemetría del router ───────────────────────────────────────────
    def do_modem(self, pl: ParsedLine, kw: str) -> None:
        """Modem*(Dest) — la variable la actualiza el poll al RUT200."""
        if not pl.args:
            self.issue(f"{kw}: faltan argumentos", code="fw-modem")
            return
        v = self.prog.find_var(pl.args[0])
        if v is None:
            self.issue(f"{kw}: var no declarada", code="fw-modem-var")
            return
        v.modem_field = kw
        v.no_auto_pin = True
        v.hw_instr_lines.append(self.line.file_no)

    # ── Contador de pulsos ──────────────────────────────────────────────
    def do_pulsecount(self, pl: ParsedLine) -> None:
        if not pl.args:
            self.issue("PulseCount: faltan argumentos", code="fw-pulse")
            return
        v = self.prog.find_var(pl.args[0])
        if v is None:
            self.issue("PulseCount: var no declarada", code="fw-pulse-var")
            return
        v.no_auto_pin = True
        v.is_pulse_count = True
        v.hw_instr_lines.append(self.line.file_no)
        ch = 0
        if len(pl.args) >= 3:
            cs = pl.args[2]
            ch = c_atoi(cs[1:]) - 1 if cs[:1] in ("P", "p") else c_atoi(cs) - 1
        if ch < 0 or ch > 7:
            ch = 0
        v.pulse_pin = ch
        v.pulse_mult = c_atof(pl.args[5]) if len(pl.args) >= 6 else 1.0
        v.pulse_offset = c_atof(pl.args[6]) if len(pl.args) >= 7 else 0.0
        if v.pulse_offset != 0.0:
            self.issue("PulseCount: Offset!=0 rompe Totalize",
                       Severity.WARNING, "fw-pulse-offset")

    def do_pulseedge(self, pl: ParsedLine) -> None:
        """PulseEdge(Dest, Rising|Falling) — extensión propia del Opta."""
        if len(pl.args) < 2:
            self.issue("PulseEdge: faltan argumentos", code="fw-pulseedge")
            return
        v = self.prog.find_var(pl.args[0])
        if v is None:
            self.issue("PulseEdge: var no declarada", code="fw-pulseedge-var")
            return
        e = pl.args[1]
        if any(cr_eq(e, x) for x in ("RISING", "SUBIDA", "1")):
            v.pulse_edge = "RISING"
        elif any(cr_eq(e, x) for x in ("FALLING", "BAJADA", "0")):
            v.pulse_edge = "FALLING"
        else:
            self.issue("PulseEdge: use Rising o Falling", code="fw-pulseedge-valor")
            return
        v.pulse_edge_line = self.line.file_no

    def do_excitech(self, pl: ParsedLine) -> None:
        """ExciteCh(N) — pone un canal como salida en alto para excitar
        el contacto de un sensor de pulsos. El canal queda reservado."""
        if not pl.args:
            self.issue("ExciteCh: faltan argumentos", code="fw-excitech")
            return
        ch = c_atoi(pl.args[0])
        if not (1 <= ch <= 8):
            self.issue("ExciteCh: canal fuera de rango 1-8", code="fw-excitech-rango")
            return
        self.prog.excite_channels[ch - 1] = self.line.file_no

    def do_battery(self, pl: ParsedLine) -> None:
        """Battery(Dest [, N]) — desde v1.6.9 lee de verdad la alimentación.

        Sin N, o con el «Option» 0 de un CR1000 real, usa A7. Un canal
        fuera de rango se registra y cae también en A7.
        """
        if not pl.args:
            return  # Battery() sin argumentos sigue siendo un no-op
        v = self.prog.find_var(pl.args[0])
        if v is None:
            self.issue("Battery: var no declarada", code="fw-battery-var")
            return
        ch = c_atoi(pl.args[1]) if len(pl.args) >= 2 else 0
        if ch == 0:
            ch = 8
        elif not (1 <= ch <= 8):
            self.issue("Battery: canal fuera de rango 1-8", code="fw-battery-rango")
            ch = 8
        v.is_batt_v = True
        v.no_auto_pin = True
        v.pin = ch - 1
        v.hw_instr_lines.append(self.line.file_no)
        self.result.explicit_pins[self.prog.var_index(v.name)] = ch - 1

    # ── Estructura de bloques If ────────────────────────────────────────
    def push_struct(self, st_type: StmtType) -> None:
        if len(self.prog.stmts) >= L.MAX_STMTS:
            self.issue(f"limite de instrucciones ({L.MAX_STMTS})", code="fw-stmts-limite")
            return
        self.prog.stmts.append(Stmt(type=st_type, line=self.line.file_no))

    def do_elseif(self, line: str) -> None:
        if len(self.prog.stmts) >= L.MAX_STMTS:
            self.issue(f"ElseIf: cond invalida o limite({L.MAX_STMTS})", code="fw-stmts-limite")
            return
        st = Stmt(type=StmtType.ELSEIF, line=self.line.file_no)
        if not self.parse_block_cond(line, st):
            self.issue(f"ElseIf: cond invalida o limite({L.MAX_STMTS})", code="fw-elseif")
            return
        self.prog.stmts.append(st)

    def do_statement_line(self, line: str, kw: str) -> None:
        """Rama final: bloque If, If de una línea, o asignación simple."""
        if cr_eq(kw, "IF"):
            tp = stristr(line, " Then")
            if tp < 0:
                self.issue("If sin 'Then'", code="fw-if-then")
                return
            body = line[tp + 5:].lstrip()
            # Un PortSet como cuerpo no lleva '=', así que hay que mirarlo
            # antes o se confunde con la apertura de un bloque If.
            if not body or ("=" not in body and not cr_eq(keyword(body), "PORTSET")):
                # Apertura de bloque If
                st = Stmt(type=StmtType.IF, line=self.line.file_no)
                ok = False
                if len(self.prog.stmts) < L.MAX_STMTS:
                    if self.parse_block_cond(line, st):
                        self.prog.stmts.append(st)
                        ok = True
                if not ok:
                    self.issue(f"If: cond invalida o limite({L.MAX_STMTS})", code="fw-if-cond")
                return
        self.try_parse_stmt(line, kw)

    # ── cr_try_parse_stmt() ─────────────────────────────────────────────
    def try_parse_stmt(self, line: str, kw: str) -> None:
        if cr_eq(kw, "IF"):
            self._try_parse_if(line)
            return

        # Desde v1.6.8 se salta la indentación ANTES de recortar el nombre
        # destino. Hasta esa versión toda asignación simple indentada —el
        # estilo normal dentro de un Scan— se descartaba en silencio.
        ls = line.lstrip()
        eq = ls.find("=")
        if eq <= 0:
            self.issue("instruccion no reconocida", code="fw-desconocida")
            return
        dst = rstrip_ctrl(strncpy(ls[:eq], L.MAX_VAR_NAME))
        if not dst or dst[-1] in "<>":
            self.issue("instruccion no reconocida", code="fw-desconocida")
            return
        v = self.prog.find_var(dst)
        if v is None:
            self.issue("asignacion a variable no declarada", code="fw-asign-var")
            return

        expr_text = ls[eq + 1:]
        res = self.compile(expr_text)
        # El firmware marca noAutoPin ANTES de validar la expresión: aunque
        # la asignación se descarte, la variable ya perdió su canal.
        v.no_auto_pin = True
        v.assigned_lines.append(self.line.file_no)
        if not res.ok:
            self.issue("expresion invalida", code="fw-expr")
            return
        if len(self.prog.stmts) >= L.MAX_STMTS:
            self.issue(f"limite de instrucciones ({L.MAX_STMTS})", code="fw-stmts-limite")
            return
        self.mark_reads(res.refs)
        self.prog.stmts.append(
            Stmt(
                type=StmtType.ASSIGN,
                line=self.line.file_no,
                dest_var=self.prog.var_index(dst),
                expr_tokens=res.tokens,
                expr_text=expr_text.strip(),
            )
        )

    def _try_parse_if(self, line: str) -> None:
        tp = stristr(line, " Then")
        if tp < 0:
            self.issue("If sin 'Then'", code="fw-if-then")
            return
        body = line[tp + 5:].lstrip()
        if not body:
            self.issue("If Then sin instruccion", code="fw-if-vacio")
            return

        cond_start = len(line) - len(line.lstrip()) + 2  # indentación + "If"
        while cond_start < len(line) and line[cond_start].isspace():
            cond_start += 1
        cond_buf = line[cond_start:tp][:63]

        st = Stmt(type=StmtType.ASSIGN, line=self.line.file_no)
        if not self.parse_cond_pair(cond_buf, st, second_msg="If: 2da condicion AND/OR invalida"):
            return

        # El cuerpo puede ser un PortSet, que no lleva '=' y si no se mira
        # antes cae en el error de "no es asignacion", que no dice nada.
        if cr_eq(keyword(body), "PORTSET"):
            content = paren(body)
            if content is None:
                self.issue("If Then PortSet: faltan parentesis", code="fw-if-portset")
                return
            body_args, body_raw, _ = args_of(content)
            self.do_portset(
                ParsedLine(src=self.line, keyword="PORTSET", has_paren=True,
                           args=body_args, raw_args=body_raw),
                base=st,
            )
            return

        eq = body.find("=")
        if eq < 0:
            self.issue("If Then: no es asignacion ni PortSet", code="fw-if-asign")
            return
        dst = rstrip_ctrl(strncpy(body[:eq], L.MAX_VAR_NAME))
        v = self.prog.find_var(dst)
        if v is None:
            self.issue("If Then: var no declarada", code="fw-if-var")
            return
        expr_text = body[eq + 1:]
        res = self.compile(expr_text)
        if not res.ok:
            self.issue("If Then: expresion invalida", code="fw-if-expr")
            return
        if len(self.prog.stmts) >= L.MAX_STMTS:
            self.issue(f"limite de instrucciones ({L.MAX_STMTS})", code="fw-stmts-limite")
            return
        st.dest_var = self.prog.var_index(dst)
        st.expr_tokens = res.tokens
        st.expr_text = expr_text.strip()
        self.mark_reads(res.refs)
        self.prog.stmts.append(st)
        v.no_auto_pin = True
        v.assigned_lines.append(self.line.file_no)

    # ── Condiciones ─────────────────────────────────────────────────────
    def parse_block_cond(self, line: str, st: Stmt) -> bool:
        tp = stristr(line, " Then")
        if tp < 0:
            return False
        i = 0
        while i < len(line) and line[i].isspace():
            i += 1
        while i < len(line) and not line[i].isspace():
            i += 1
        while i < len(line) and line[i].isspace():
            i += 1
        cl = tp - i
        if cl <= 0 or cl > 63:
            return False
        return self.parse_cond_pair(line[i:tp], st, quiet=True)

    def parse_cond_pair(self, cond_buf: str, st: Stmt, *, quiet: bool = False,
                        second_msg: str = "") -> bool:
        and_pos = stristr(cond_buf, " AND ")
        or_pos = stristr(cond_buf, " OR ")
        join = and_pos if and_pos >= 0 else or_pos
        if join >= 0:
            cond1 = cond_buf[:join][:39]
            cond2 = cond_buf[join + (5 if and_pos >= 0 else 4):][:39]
        else:
            cond1, cond2 = cond_buf[:39], None

        c1 = self.parse_cond(cond1)
        if c1 is None:
            if not quiet:
                self.issue("If: condicion mal formada", code="fw-cond")
            return False
        st.cond = c1
        if cond2 is not None:
            c2 = self.parse_cond(cond2)
            if c2 is None:
                if not quiet:
                    self.issue(second_msg or "If: condicion mal formada", code="fw-cond2")
                return False
            st.cond2 = c2
            st.join_and = and_pos >= 0
        return True

    def parse_cond(self, cond: str) -> "Cond | None":
        s = rstrip_ctrl(cond[:39]).lstrip()
        if len(s) >= 2 and s[0] == "(" and s[-1] == ")":
            s = s[1:-1]
        for sym, op in _COND_OPS:
            pos = s.find(sym)
            if pos < 0:
                continue
            left = strncpy(s[:pos], L.MAX_VAR_NAME)
            li, _ = self.resolve_operand(left)
            if li < 0:
                return None
            ri, rc = self.resolve_operand(s[pos + len(sym):])
            if ri == -2:
                return None
            if li >= 0:
                self.prog.vars[li].read_lines.append(self.line.file_no)
            if ri >= 0:
                self.prog.vars[ri].read_lines.append(self.line.file_no)
            return Cond(left_var=li, op=op, right_var=ri, right_const=rc, text=s.strip())
        return None

    def resolve_operand(self, tok: str) -> "tuple[int, float]":
        """cr_resolve_operand(). Devuelve (idx_var, valor); -1 = constante,
        -2 = no se pudo resolver."""
        t = rstrip_ctrl(strncpy(tok, L.MAX_VAR_NAME)).lstrip()
        if not t:
            return -2, 0.0
        idx = self.prog.var_index(t)
        if idx >= 0:
            return idx, 0.0
        c = self.prog.find_const(t)
        if c is not None:
            return -1, c.value
        if t[0].isdigit() or t[0] in "-+.":
            return -1, c_atof(t)
        return -2, 0.0

    # ── Expresiones ─────────────────────────────────────────────────────
    def compile(self, expr_text: str):
        return compile_expr(
            expr_text,
            [v.name for v in self.prog.vars],
            [c.name for c in self.prog.consts],
            L.MAX_EXPR_TOKENS,
            L.OPSTK_MAX,
        )

    def mark_reads(self, refs: "list[str]") -> None:
        for name in refs:
            v = self.prog.find_var(name)
            if v is not None:
                v.read_lines.append(self.line.file_no)

    # ── Asignación dinámica de canales A0-A7 ────────────────────────────
    def assign_channels(self) -> None:
        """Réplica del pase final de parse_crbasic().

        Desde v1.6.9 los canales ya comprometidos —Battery(...,N),
        AIChannel, VoltDiff/VoltSE con Chan, PulseCount y ExciteCh— se
        marcan como ocupados antes del reparto secuencial, así que ya no
        se pueden entregar dos veces. Hasta v1.6.8 used[] arrancaba vacío
        y el reparto automático pisaba los canales fijados a mano.
        """
        for v in self.prog.vars:
            if v.has_volt_instr:
                v.no_auto_pin = False

        used = [False] * 8
        for v in self.prog.vars:
            if 0 <= v.pin < 8:
                used[v.pin] = True
            if v.is_pulse_count and 0 <= v.pulse_pin < 8:
                used[v.pulse_pin] = True
        for ch in self.prog.excite_channels:
            used[ch] = True

        # Reserva histórica: nombre con «att» sin canal ni instrucción de
        # lectura → A7. Desde v1.6.9 solo si nadie tomó ese canal.
        for v in self.prog.vars:
            if v.no_auto_pin or v.pin >= 0 or v.is4_20mA or v.has_volt_instr:
                continue
            if "att" in v.name or "ATT" in v.name or "Att" in v.name:
                if used[7]:
                    self.result.att_sin_canal = v.name
                else:
                    v.pin = 7
                    v.is_batt_v = True
                    used[7] = True
                break

        next_pin = 0
        for v in self.prog.vars:
            if v.no_auto_pin or v.pin >= 0:
                continue
            if not v.has_volt_instr and not v.is4_20mA:
                continue
            while next_pin < 8 and used[next_pin]:
                next_pin += 1
            if next_pin >= 8:
                break
            v.pin = next_pin
            used[next_pin] = True
            next_pin += 1


def _to_sec(val: int, unit: str) -> int:
    """cr_to_sec(): las 3 primeras letras de la unidad, case-insensitive."""
    u = unit.upper()[:7]
    if u.startswith("MIN"):
        return val * 60
    if u.startswith("HOU"):
        return val * 3600
    if u.startswith("DAY"):
        return val * 86400
    return val


def _type_code(t: str) -> int:
    """cr_type(): reconocido como metadato; todo se transmite como IEEE4B."""
    u = t.upper()[:8]
    return {"FP2": 7, "UINT2": 2, "INT2": 5, "INT4": 6, "LONG": 6}.get(u, 9)
