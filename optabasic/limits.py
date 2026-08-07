"""Límites del intérprete CRBasic del firmware OptaPakBus.

Portados uno a uno desde los #define de OptaPakBus.ino. Si el firmware
cambia un límite, se cambia acá y todo el IDE queda consistente.
"""

#: Versión del firmware contra la que está calcado este motor.
FIRMWARE_VERSION = "1.6.12"

# ── Buffers y tamaños del parser (OptaPakBus.ino) ────────────────────────
MAX_PROG_BYTES = 16384     # storedProg[16384] — 8192 hasta v1.6.11
MAX_LINE_LEN = 127         # line[128], truncado silencioso
MAX_ARGS = 12              # args[12][32]
MAX_ARG_LEN = 31           # 31 chars + '\0'

# ── Capacidades declaradas (#define CR_MAX_*) ───────────────────────────
MAX_VARS = 64              # CR_MAX_VARS
MAX_CONSTS = 16            # CR_MAX_CONSTS
MAX_TABLES = 4             # CR_MAX_TABLES
MAX_FIELDS = 32            # CR_MAX_FIELDS
MAX_STMTS = 64             # CR_MAX_STMTS — 32 hasta v1.6.11
MAX_EXPR_TOKENS = 20       # CR_MAX_EXPR_TOKENS
OPSTK_MAX = 20             # CR_OPSTK_MAX
IF_MAX_DEPTH = 2           # CR_IF_MAX_DEPTH

# ── Longitudes de nombre (strncpy del firmware) ─────────────────────────
MAX_VAR_NAME = 23
MAX_CONST_NAME = 19
MAX_TABLE_NAME = 23
MAX_FIELD_NAME = 23
MAX_STATION_NAME = 23
MAX_HOST_LEN = 63
MAX_UNITS_LEN = 15

# ── Valores por defecto ──────────────────────────────────────────────────
DEFAULT_TABLE_SIZE = 50000     # CR_DEFAULT_TABLE_SIZE (cuando Size <= 0)
DEFAULT_TABLE_SIZE_OMITTED = 1440   # cuando falta el argumento Size
DEFAULT_SCAN_MS = 60000        # sin Scan() en el programa
MIN_SCAN_MS = 1000             # piso forzado por el firmware

# ── Hardware del Opta (constantes ADC de OptaPakBus.ino) ────────────────
N_ANALOG = 8               # A0-A7
N_RELAYS = 4               # DO1-DO4
OPTA_VREF = 10.70          # V a fondo de escala de la entrada analógica
OPTA_BATT_FACTOR = 3.351   # divisor resistivo del canal de alimentación

#: Shunt EFECTIVO de las entradas 4-20mA (SHUNT_OHM). Era 270.0 hasta
#: v1.6.10. No es el valor del resistor físico: la entrada analógica del
#: Opta presenta ~7.8 kΩ a masa y queda en paralelo con él, así que la
#: caída de tensión corresponde al paralelo de los dos. Medido en terreno
#: sobre un lazo real: R4 de 269 Ω nominales da 260.0 Ω efectivos.
SHUNT_OHM = 260.0

#: Impedancia de entrada del canal analógico, deducida de esa medición:
#: 1/(1/260 − 1/269) ≈ 7.8 kΩ. Es la que hay que poner en paralelo con el
#: resistor físico para saber cuánto va a medir el equipo de verdad.
ZIN_OHM = 7800.0

ADC_MAX = 4095             # resolución 12 bits

#: Antirrebote del contador de pulsos (PULSE_DEBOUNCE_US), en milisegundos.
PULSE_DEBOUNCE_MS = 50.0
