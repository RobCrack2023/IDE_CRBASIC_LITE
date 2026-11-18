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
    #: PortSet(Rele, Valor). Desde v1.7.0 es una instrucción ejecutable: el
    #: relé cambia en el punto del programa donde está escrita la línea, y
    #: solo ahí. Antes era una declaración que ligaba una variable a un relé.
    PORTSET = 5


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
    mult: float = 1.0
    offset: float = 0.0
    has_volt_instr: bool = False
    is_batt_v: bool = False
    no_auto_pin: bool = False
    is_pulse_count: bool = False
    #: Campo de telemetría del router Teltonika (v1.6.14). La variable se
    #: actualiza sola desde el poll HTTP al RUT200, sin consumir canal.
    modem_field: str = ""
    #: Reloj del programa (v1.7.8): "CLOCKYYMMDD" o "CLOCKHHMM". La variable
    #: se refresca sola cada scan con la fecha/hora local; no ocupa canal.
    clock_field: str = ""
    #: Su valor sobrevive un reinicio (v1.8.0, PreserveVariables). Lo vuelca
    #: a flash el firmware cuando la PLATAFORMA escribe la variable, no
    #: cuando el programa la calcula.
    preserve: bool = False
    #: Su valor lo calcula un filtro de mediana movil (v1.9.0, MedianRun).
    is_median: bool = False
    #: La consigna la mueve la agenda (v1.9.3, SetpointSchedule). El equipo le
    #: escribe, pero SOLO cuando vence una entrada.
    is_scheduled: bool = False
    #: Agenda_N / Agenda_Serie de un SetpointSchedule: de solo lectura.
    is_sched_info: bool = False
    #: La llena una lectura Modbus RTU (v1.10.0, ModbusRTU): el valor, o el
    #: Resultado de la lectura.
    is_modbus: bool = False

    @property
    def preserve_pointless(self) -> bool:
        """cr_var_preserve_pointless(): el equipo la recalcula en cada scan
        SIN CONDICIONES, asi que preservarla es inutil.

        Un canal analogico, la bateria, el router, el reloj, un contador de
        pulsos, una mediana o las dos lecturas de la agenda. Preservarla no
        sirve: al arrancar le daria a la logica una medicion vieja antes de
        la primera lectura real.

        La consigna de un SetpointSchedule NO entra aca aunque el equipo le
        escriba: solo cambia cuando vence una entrada, y con el reloj sin
        sincronizar no se toca, asi que su ultimo valor tiene que sobrevivir
        un reinicio. Es la pregunta que decide si PreserveVariables la acepta.
        """
        return (self.pin >= 0 or self.is_batt_v or bool(self.modem_field)
                or bool(self.clock_field) or self.is_pulse_count or self.is_median
                or self.has_volt_instr or self.is_sched_info or self.is_modbus)

    @property
    def is_written(self) -> bool:
        """El equipo le asigna valor en algun momento.

        Es preserve_pointless MAS la consigna de la agenda. Es la pregunta de
        la regla de variable muerta: una consigna con agenda no esta muerta
        aunque el programa nunca la asigne. El invariante es que
        preserve_pointless es un subconjunto de is_written; el unico miembro
        donde difieren es el destino de SetpointSchedule, que depende del
        reloj y no se recalcula en cada scan.
        """
        return self.preserve_pointless or self.is_scheduled
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
        if self.clock_field:
            return "Reloj"
        if self.modem_field:
            return "Módem"
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
class Median:
    """CRMedian: un filtro de mediana movil declarado con MedianRun."""

    dest: str
    src: str
    window: int
    line: int = 0


@dataclass
class Schedule:
    """CRSchedule: una consigna ligada a un canal de la agenda (v1.9.3)."""

    dest: str
    canal: int
    n_var: str = ""        # Agenda_N, opcional
    serie_var: str = ""    # Agenda_Serie, opcional
    line: int = 0


@dataclass
class Modbus:
    """CRModbus: una lectura Modbus RTU declarada con ModbusRTU (v1.10.0)."""

    result: str            # variable con el codigo de resultado
    first: str             # Primera_Var: primera variable de datos
    first_idx: int         # su indice en Program.vars (las demas son las siguientes)
    slave: int
    fn: int                # 1, 2, 3 o 4
    start: int
    count: int             # valores (variables), no registros
    type: int              # 0..7
    interval_s: float
    mult: float = 1.0
    offset: float = 0.0
    line: int = 0

    @property
    def registers_per_value(self) -> int:
        """Registros que ocupa cada valor: los tipos de 32 bits usan dos."""
        if self.fn <= 2:
            return 1
        return 2 if (self.type <= 1 or self.type >= 4) else 1


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
    #: PORTSET: relé accionado, 0-3 (DO1-DO4). -1 en los demás tipos.
    relay: int = -1
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
    #: Credenciales del router Teltonika de ESTE equipo (v1.6.18). El firmware
    #: arranca con usuario "admin" y clave vacía, así que sin RouterPass= el
    #: login falla y las variables Modem* se quedan en 0.
    router_user: str = ""
    router_user_line: int = 0
    router_pass: str = ""
    router_pass_line: int = 0
    #: Horas respecto de UTC para la hora local de ClockYYMMDD/ClockHHMM
    #: (v1.7.8). No afecta la hora de los registros, siempre en UTC.
    utc_offset: "float | None" = None
    utc_offset_line: int = 0
    #: Parametros del bus RS-485 para ModbusRTU (v1.10.0). Valen para todas las
    #: lecturas del programa; el firmware repone 9600, 8N1 y 250 ms en cada
    #: parseo, y estos campos quedan en None si el programa no los declara.
    modbus_baud: "int | None" = None
    modbus_baud_line: int = 0
    modbus_format: "str | None" = None
    modbus_format_line: int = 0
    modbus_timeout: "int | None" = None
    modbus_timeout_line: int = 0

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
    #: PreserveVariables (v1.8.0). La forma sin argumentos preserva toda
    #: variable que escriba la plataforma; la forma con lista, solo esas.
    preserve_all: bool = False
    #: {nombre pedido -> linea del archivo}, tal como se escribio.
    preserve_names: "dict[str, int]" = field(default_factory=dict)
    preserve_line: int = 0
    #: Filtros MedianRun declarados, en orden (v1.9.0).
    medians: "list[Median]" = field(default_factory=list)
    #: SetpointSchedule declarados, en orden (v1.9.3).
    schedules: "list[Schedule]" = field(default_factory=list)
    #: ModbusRTU declarados, en orden (v1.10.0).
    modbus: "list[Modbus]" = field(default_factory=list)

    @property
    def preserve_enabled(self) -> bool:
        """crPreserveEnabled: cualquiera de las dos formas."""
        return self.preserve_all or bool(self.preserve_names)

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

    def relay_map(self) -> "list[list[Stmt]]":
        """Qué PortSet acciona cada relé DO1-DO4.

        Puede haber más de uno por relé: el programa es libre de accionarlo
        desde varias ramas de un If. La lista vacía significa que ese relé no
        se toca, y entonces se queda como lo dejó el programa anterior.
        """
        slots: "list[list[Stmt]]" = [[] for _ in range(4)]
        for st in self.stmts:
            if st.type == StmtType.PORTSET and 0 <= st.relay < 4:
                slots[st.relay].append(st)
        return slots

    def pulse_map(self) -> "list[Var | None]":
        """Qué variable cuenta pulsos en cada canal."""
        slots: "list[Var | None]" = [None] * 8
        for v in self.vars:
            if v.is_pulse_count and 0 <= v.pulse_pin < 8 and slots[v.pulse_pin] is None:
                slots[v.pulse_pin] = v
        return slots
