"""Estructuras del programa parseado — espejo de CRVar/CRConst/CRTable/CRStmt."""

from dataclasses import dataclass, field
from enum import IntEnum

from .cutil import cr_eq
from .limits import DEFAULT_SCAN_MS


class StmtType(IntEnum):
    ASSIGN = 0
    IF = 1
    ELSEIF = 2
    ELSE = 3
    ENDIF = 4


class CmpOp(IntEnum):
    LT = 0
    GT = 1
    LE = 2
    GE = 3
    EQ = 4
    NE = 5

    @property
    def symbol(self) -> str:
        return {0: "<", 1: ">", 2: "<=", 3: ">=", 4: "=", 5: "<>"}[int(self)]


@dataclass
class Var:
    """CRVar. Todo es float; no hay distinción entre Public y Dim."""

    name: str
    units: str = ""
    value: float = 0.0
    pin: int = -1               # canal analógico A0-A7, -1 = sin asignar
    is4_20mA: bool = False
    is_relay: bool = False
    relay_idx: int = 0
    mult: float = 1.0
    offset: float = 0.0
    has_volt_instr: bool = False
    is_batt_v: bool = False
    no_auto_pin: bool = False
    is_pulse_count: bool = False
    pulse_pin: int = -1
    pulse_mult: float = 1.0
    pulse_offset: float = 0.0
    #: Flanco que cuenta la interrupción. Desde v1.6.9 el default es RISING
    #: (canal con pull-down al negativo, excitado por ExciteCh); antes era
    #: FALLING. Se cambia con PulseEdge().
    pulse_edge: str = "RISING"
    pulse_edge_line: int = 0

    # ── Metadatos del IDE (no existen en el firmware) ────────────────────
    decl_line: int = 0          # línea de archivo del Public/Dim
    decl_kw: str = "Public"
    units_line: int = 0
    assigned_lines: "list[int]" = field(default_factory=list)
    read_lines: "list[int]" = field(default_factory=list)
    hw_instr_lines: "list[int]" = field(default_factory=list)
    name_truncated: bool = False

    @property
    def reads_hardware(self) -> bool:
        """¿La variable toma su valor de una entrada física?"""
        return self.pin >= 0 or self.is_pulse_count

    @property
    def channel_label(self) -> str:
        if self.is_pulse_count and self.pulse_pin >= 0:
            return f"A{self.pulse_pin} (pulsos)"
        if self.pin >= 0:
            return f"A{self.pin}"
        return "—"

    @property
    def kind(self) -> str:
        if self.is_relay:
            return "Relé"
        if self.is_pulse_count:
            return "Pulsos"
        if self.is_batt_v:
            return "Alimentación"
        if self.is4_20mA:
            return "4-20mA"
        if self.has_volt_instr:
            return "Voltaje"
        return "Calculada"


@dataclass
class Const:
    name: str
    value: float
    decl_line: int = 0
    #: Texto crudo a la derecha del '='. Si no es un literal, atof() lo
    #: interpreta parcialmente y la constante vale otra cosa.
    raw_value: str = ""
    name_truncated: bool = False


@dataclass
class Field:
    name: str
    processing: str          # Sample / Average / Maximum / Minimum / Totalize
    type_code: int = 9       # siempre se transmite IEEE4B, el tipo es metadato
    type_name: str = ""
    line: int = 0
    resolved: bool = True    # False = la variable no existe → archiva 0


@dataclass
class Table:
    name: str
    size: int = 0
    interval_sec: int = 0
    fields: "list[Field]" = field(default_factory=list)
    decl_line: int = 0
    end_line: int = 0
    interval_line: int = 0
    name_truncated: bool = False

    @property
    def n_fields(self) -> int:
        return len(self.fields)


@dataclass
class Cond:
    """Una comparación «Var <op> Var|Const»."""

    left_var: int            # índice en program.vars
    op: CmpOp
    right_var: int = -1      # >= 0 si el lado derecho es variable
    right_const: float = 0.0
    text: str = ""


@dataclass
class Stmt:
    """CRStmt: asignación o marca de estructura de un bloque If."""

    type: StmtType
    line: int = 0
    dest_var: int = -1
    expr_tokens: int = 0
    expr_text: str = ""
    cond: "Cond | None" = None
    cond2: "Cond | None" = None
    join_and: bool = False


@dataclass
class Network:
    """Directivas propias del Opta que configuran el equipo."""

    station_name: str = ""
    station_line: int = 0
    server_host: str = ""
    host_line: int = 0
    server_port: "int | None" = None
    port_line: int = 0
    pakbus_address: "int | None" = None
    address_line: int = 0

    @property
    def provisioned(self) -> bool:
        """Sin ServerPort= el equipo se conecta al puerto de provisión."""
        return self.server_port is not None


@dataclass
class Program:
    vars: "list[Var]" = field(default_factory=list)
    consts: "list[Const]" = field(default_factory=list)
    tables: "list[Table]" = field(default_factory=list)
    stmts: "list[Stmt]" = field(default_factory=list)
    network: Network = field(default_factory=Network)
    scan_interval_ms: int = DEFAULT_SCAN_MS
    scan_line: int = 0
    size_bytes: int = 0
    #: Canales declarados con ExciteCh: {índice 0-7 → línea del archivo}.
    #: Quedan como salida en alto (~3.3 V) y reservados.
    excite_channels: "dict[int, int]" = field(default_factory=dict)

    def find_var(self, name: str) -> "Var | None":
        """cr_find_var(): primera coincidencia case-insensitive."""
        for v in self.vars:
            if cr_eq(v.name, name):
                return v
        return None

    def var_index(self, name: str) -> int:
        for i, v in enumerate(self.vars):
            if cr_eq(v.name, name):
                return i
        return -1

    def find_const(self, name: str) -> "Const | None":
        for c in self.consts:
            if cr_eq(c.name, name):
                return c
        return None

    @property
    def parsed(self) -> bool:
        """crParsed: sin ninguna DataTable el firmware NO ejecuta el programa."""
        return len(self.tables) > 0

    @property
    def scan_seconds(self) -> float:
        return self.scan_interval_ms / 1000.0

    def analog_map(self) -> "list[Var | None]":
        """Qué variable quedó en cada canal A0-A7 tras la asignación."""
        slots: "list[Var | None]" = [None] * 8
        for v in self.vars:
            if v.pin >= 0 and v.pin < 8 and slots[v.pin] is None:
                slots[v.pin] = v
        return slots

    def relay_map(self) -> "list[Var | None]":
        """Qué variable controla cada relé DO1-DO4."""
        slots: "list[Var | None]" = [None] * 4
        for v in self.vars:
            if v.is_relay and 0 <= v.relay_idx < 4 and slots[v.relay_idx] is None:
                slots[v.relay_idx] = v
        return slots

    def pulse_map(self) -> "list[Var | None]":
        """Qué variable cuenta pulsos en cada canal."""
        slots: "list[Var | None]" = [None] * 8
        for v in self.vars:
            if v.is_pulse_count and 0 <= v.pulse_pin < 8 and slots[v.pulse_pin] is None:
                slots[v.pulse_pin] = v
        return slots
