"""Cálculo de escalas para sensores, con la matemática real del firmware.

Sacar Mult y Offset a mano es donde más se equivoca la gente, y un error
acá no se nota: el equipo reporta números perfectamente plausibles que
están mal. Peor todavía con 4-20 mA, porque el firmware tiene el valor de
la resistencia shunt fijo en 270 Ω y una instalación con otra resistencia
mide desviado sin que nada lo indique.

Todas las constantes vienen de OptaPakBus.ino:

    read_mA(pin)    v = adc * 10.70 / 4095;  return (v / 270) * 1000
    read_volts(pin) return adc * 10.70 / 4095
    VoltSE/VoltDiff valor = volts * 1000 * Mult + Offset   (o sea, sobre mV)
    PulseCount      valor = pulsos_del_scan * Mult + Offset
"""

from dataclasses import dataclass, field

# ── Hardware del Opta (OptaPakBus.ino:1201-1250) ─────────────────────────
VREF = 10.70                #: tensión de fondo de escala de la entrada
ADC_MAX = 4095              #: 12 bits
MV_POR_CUENTA = VREF * 1000.0 / ADC_MAX     #: ≈ 2.613 mV por cuenta de ADC

#: El valor que el firmware tiene fijo por código (SHUNT_OHM). Desde
#: v1.6.10 es 260, no 270: es el shunt EFECTIVO, medido en terreno, no el
#: resistor físico.
SHUNT_NOMINAL = 260.0

#: Impedancia de entrada del canal analógico. Queda en paralelo con el
#: resistor del lazo, así que la caída de tensión que mide el equipo
#: corresponde al paralelo de los dos y no al resistor solo. Deducida de la
#: misma medición de terreno: 1/(1/260 − 1/269) ≈ 7.8 kΩ.
ZIN = 7800.0

# ── PulseCount (OptaPakBus.ino:445-460) ──────────────────────────────────
DEBOUNCE_MS = 50.0
TASA_MAX_HZ = 1000.0 / DEBOUNCE_MS          #: 20 pulsos por segundo


def shunt_efectivo(resistor_fisico: float) -> float:
    """El shunt real que ve el lazo: el resistor en paralelo con la entrada.

    Un resistor de 269 Ω medido con tester se comporta como 260 Ω, porque
    la entrada analógica del Opta presenta ~7.8 kΩ a masa y se lleva parte
    de la corriente. Ignorar esto da un error de span del 3,5% con los
    valores habituales — que es exactamente el error que tenía el firmware
    antes de la calibración de terreno.
    """
    if resistor_fisico <= 0:
        return 0.0
    return resistor_fisico * ZIN / (resistor_fisico + ZIN)

ERROR, AVISO, NOTA = "error", "aviso", "nota"


@dataclass
class Escala:
    """Resultado de un cálculo: los números, el código y las advertencias."""

    mult: float
    offset: float
    codigo: str = ""
    avisos: "list[tuple[str, str]]" = field(default_factory=list)
    datos: "list[tuple[str, str]]" = field(default_factory=list)

    def avisar(self, nivel: str, texto: str) -> None:
        self.avisos.append((nivel, texto))

    @property
    def hay_errores(self) -> bool:
        return any(n == ERROR for n, _ in self.avisos)


def _num(valor: float, decimales: int = 6) -> str:
    """Número legible: sin ceros de relleno pero sin notación científica."""
    if valor == 0:
        return "0.0"
    texto = f"{valor:.{decimales}f}".rstrip("0").rstrip(".")
    return texto if texto not in ("", "-") else "0.0"


# ═════════════════════════════════════════════════════════════════════════
#  Sensores de corriente 4-20 mA
# ═════════════════════════════════════════════════════════════════════════
def calcular_4_20(
    nombre: str,
    valor_min: float,
    valor_max: float,
    unidad: str = "",
    canal: int = 1,
    i_min: float = 4.0,
    i_max: float = 20.0,
    shunt: float = 269.0,
    modo: str = "mA",
) -> Escala:
    """Calcula Mult y Offset para un sensor de corriente.

    `shunt` es el resistor FÍSICO del lazo, el que se mide con el tester.
    Adentro se calcula el valor efectivo poniéndolo en paralelo con la
    impedancia de entrada del Opta, que es lo que el equipo mide en
    realidad.

    `modo` elige cómo lo lee el equipo:

    - "mA": la variable lleva Units = mA y el firmware la convierte él
      mismo, dividiendo siempre por los 260 Ω que tiene fijos por código.
      Si el lazo real da otro valor efectivo, la diferencia se compensa
      dentro de Mult.
    - "voltse": se lee como voltaje con VoltSE y toda la conversión va en
      Mult. Es exacto con cualquier resistor y no depende del valor que el
      firmware traiga fijo.
    """
    nombre = (nombre or "Sensor").strip() or "Sensor"
    span_valor = valor_max - valor_min
    span_i = i_max - i_min

    if span_i <= 0:
        e = Escala(1.0, 0.0)
        e.avisar(ERROR, "El rango de corriente está al revés o es cero: "
                        "la corriente máxima tiene que ser mayor que la mínima.")
        return e
    if shunt <= 0:
        e = Escala(1.0, 0.0)
        e.avisar(ERROR, "La resistencia shunt tiene que ser mayor que cero.")
        return e

    resistor = shunt
    shunt = shunt_efectivo(resistor)

    # El Offset sale igual en los dos modos, porque en ambos la recta pasa
    # por (i_min, valor_min).
    offset = valor_min - i_min * span_valor / span_i
    if modo == "voltse":
        mult = span_valor / (span_i * shunt)
    else:
        mult = span_valor * SHUNT_NOMINAL / (span_i * shunt)

    esc = Escala(mult, offset)

    # ── Comprobaciones eléctricas ───────────────────────────────────────
    v_min = i_min * shunt / 1000.0
    v_max = i_max * shunt / 1000.0
    esc.datos.append((
        "Shunt efectivo",
        f"{shunt:.1f} Ω  (el resistor de {resistor:g} Ω en paralelo con los "
        f"{ZIN / 1000:g} kΩ de la entrada)",
    ))
    esc.datos.append(("Tensión sobre la resistencia",
                      f"{v_min:.2f} V a {i_min:g} mA  →  {v_max:.2f} V a {i_max:g} mA"))

    if v_max > VREF:
        esc.avisar(
            ERROR,
            f"Con {shunt:g} Ω, {i_max:g} mA dan {v_max:.2f} V y la entrada del Opta "
            f"llega hasta {VREF:g} V: la lectura se corta arriba y el sensor nunca "
            f"va a marcar el máximo. Usá una resistencia de "
            f"{int(VREF * 1000 / i_max / 10) * 10} Ω o menos.",
        )
    elif v_max > VREF * 0.93:
        esc.avisar(
            AVISO,
            f"{v_max:.2f} V a fondo de escala queda muy cerca del techo de "
            f"{VREF:g} V: sin margen para sobrecorrientes del sensor.",
        )

    # ── Resolución que se consigue ──────────────────────────────────────
    ma_por_cuenta = MV_POR_CUENTA / shunt
    paso = ma_por_cuenta * span_valor / span_i
    cuentas = (v_max - v_min) * 1000.0 / MV_POR_CUENTA
    esc.datos.append(("Resolución",
                      f"{paso:.4g} {unidad or 'unidades'} por cuenta de ADC "
                      f"({cuentas:.0f} pasos en todo el rango)"))
    if cuentas < 200:
        esc.avisar(
            AVISO,
            f"Solo {cuentas:.0f} pasos de ADC en todo el rango: la lectura va a "
            "verse escalonada. Con una resistencia más grande se gana resolución.",
        )

    # ── El shunt fijo del firmware ──────────────────────────────────────
    if abs(shunt - SHUNT_NOMINAL) > 0.5:
        factor = shunt / SHUNT_NOMINAL
        if modo == "mA":
            esc.avisar(
                AVISO,
                f"El firmware divide siempre por {SHUNT_NOMINAL:g} Ω y tu lazo da "
                f"{shunt:.1f} Ω efectivos, así que la variable «{nombre}_mA» NO va a "
                f"mostrar los miliamperes reales sino {factor:.3f} veces "
                f"({i_max:g} mA reales se ven como {i_max * factor:.2f}). El valor de "
                "ingeniería sale bien igual porque la diferencia va compensada en "
                "Mult, pero ojo con los umbrales de falla: usá los que genera el "
                "asistente, no 3.5 y 20.5.",
            )
        else:
            esc.avisar(
                NOTA,
                f"Con VoltSE los {shunt:.1f} Ω efectivos entran en la cuenta de forma "
                f"exacta; no importa que el firmware traiga {SHUNT_NOMINAL:g} fijos.",
            )
    elif modo == "mA":
        esc.avisar(
            NOTA,
            f"El lazo da {shunt:.1f} Ω efectivos, prácticamente los "
            f"{SHUNT_NOMINAL:g} que el firmware tiene calibrados, así que "
            f"«{nombre}_mA» va a mostrar los miliamperes reales.",
        )

    esc.codigo = _codigo_4_20(nombre, esc, unidad, canal, i_min, i_max,
                              shunt, resistor, modo, valor_min, valor_max)
    return esc


def _codigo_4_20(nombre, esc, unidad, canal, i_min, i_max, shunt, resistor,
                 modo, valor_min, valor_max) -> str:
    factor = shunt / SHUNT_NOMINAL
    u = f" {unidad}" if unidad else ""
    cabecera = [
        f"'-- Sensor {nombre}: {_num(valor_min, 3)} a {_num(valor_max, 3)}{u}",
        f"'   Lazo de {i_min:g}-{i_max:g} mA sobre un resistor de {resistor:g} ohm",
        f"'   ({shunt:.1f} ohm efectivos con la entrada del Opta en paralelo).",
    ]

    if modo == "voltse":
        cabecera.append("'   Se lee como voltaje: la resistencia entra exacta en Mult.")
        return "\n".join(cabecera + [
            f"Public {nombre}",
            f"Units {nombre} = {unidad}" if unidad else "",
            f"VoltSE({nombre}, 1, mV5000, {canal}, 0, 0, "
            f"{_num(esc.mult, 8)}, {_num(esc.offset, 4)})",
            "",
        ]).replace("\n\n\n", "\n\n")

    # Umbrales de falla, corregidos por la resistencia real.
    falla_baja = 3.5 * factor
    falla_alta = (i_max + 0.5) * factor
    cabecera.append(
        "'   Los umbrales de falla estan corregidos por la resistencia real."
        if abs(factor - 1.0) > 0.002 else
        "'   Por debajo de Min_mA o por encima de Max_mA: sensor con falla."
    )
    lineas = cabecera + [
        f"Const {nombre}_Mult = {_num(esc.mult, 8)}",
        f"Const {nombre}_Off  = {_num(esc.offset, 4)}",
        f"Const {nombre}_Min_mA = {_num(falla_baja, 3)}",
        f"Const {nombre}_Max_mA = {_num(falla_alta, 3)}",
        "",
        f"Public {nombre}_mA",
        f"Units {nombre}_mA = mA",
        f"Public {nombre}",
        f"Public {nombre}_Falla",
        "",
        f"AIChannel({nombre}_mA, {canal})",
        "",
        "' La cuenta va SIN sangria: el equipo lee el destino desde la columna 0.",
        f"{nombre} = {nombre}_mA * {nombre}_Mult + {nombre}_Off",
        f"If ({nombre}_mA < {nombre}_Min_mA) Then {nombre}_Falla = 1",
        f"If ({nombre}_mA > {nombre}_Max_mA) Then {nombre}_Falla = 1",
        f"If ({nombre}_mA >= {nombre}_Min_mA) AND ({nombre}_mA <= {nombre}_Max_mA) "
        f"Then {nombre}_Falla = 0",
        "",
    ]
    return "\n".join(l for l in lineas if l is not None)


# ═════════════════════════════════════════════════════════════════════════
#  Contadores de pulsos
# ═════════════════════════════════════════════════════════════════════════
def calcular_pulsos(
    nombre: str,
    canal: int = 1,
    unidad_por_pulso: float = 0.2,
    unidad: str = "mm",
    modo: str = "por_pulso",
    caudal_max: float = 0.0,
    por_segundo: bool = False,
    scan_seg: float = 10.0,
    canal_excitacion: int = 0,
) -> Escala:
    """Calcula Mult para un contador de pulsos y revisa que sea viable.

    `modo` = "por_pulso" cuando se conoce cuánto vale cada pulso (un
    pluviómetro de 0,2 mm por volcada), o "por_unidad" cuando el dato de
    fábrica viene al revés (un caudalímetro de 450 pulsos por litro).

    `caudal_max` es el máximo que se espera medir, en unidad por segundo si
    `por_segundo`, o en unidad por minuto si no. Sirve para avisar si el
    antirrebote de 50 ms del firmware lo deja fuera de alcance.
    """
    nombre = (nombre or "Pulsos").strip() or "Pulsos"
    if not canal_excitacion:
        # Por defecto, el canal de al lado del de conteo.
        canal_excitacion = canal + 1 if canal < 8 else canal - 1

    if modo == "por_unidad":
        if unidad_por_pulso <= 0:
            e = Escala(1.0, 0.0)
            e.avisar(ERROR, "Los pulsos por unidad tienen que ser mayores que cero.")
            return e
        mult = 1.0 / unidad_por_pulso
        detalle = f"{_num(unidad_por_pulso, 4)} pulsos por {unidad or 'unidad'}"
    else:
        if unidad_por_pulso <= 0:
            e = Escala(1.0, 0.0)
            e.avisar(ERROR, "El valor de cada pulso tiene que ser mayor que cero.")
            return e
        mult = unidad_por_pulso
        detalle = f"{_num(unidad_por_pulso, 4)} {unidad or 'unidades'} por pulso"

    esc = Escala(mult, 0.0)
    esc.datos.append(("Cada pulso vale", f"{_num(mult, 6)} {unidad or 'unidades'}"))

    # ── El techo que impone el antirrebote ──────────────────────────────
    max_por_seg = TASA_MAX_HZ * mult
    esc.datos.append((
        "Máximo que puede contar",
        f"{TASA_MAX_HZ:g} pulsos/s = {_num(max_por_seg, 4)} "
        f"{unidad or 'unidades'}/s ({_num(max_por_seg * 60, 4)} por minuto)",
    ))

    if caudal_max > 0:
        por_seg = caudal_max if por_segundo else caudal_max / 60.0
        hz = por_seg / mult if mult else 0.0
        esc.datos.append(("Ritmo esperado a fondo de escala", f"{hz:.1f} pulsos/s"))
        if hz > TASA_MAX_HZ:
            esc.avisar(
                ERROR,
                f"A fondo de escala este sensor da {hz:.0f} pulsos por segundo y el "
                f"Opta no puede contar más de {TASA_MAX_HZ:g}: tiene un antirrebote "
                f"de {DEBOUNCE_MS:g} ms fijo por firmware, pensado para contactos "
                f"secos. Todo lo que pase de {_num(max_por_seg * 60, 3)} "
                f"{unidad or 'unidades'} por minuto se va a contar de menos, sin "
                "ningún aviso. Para este caudal hace falta un sensor de menos "
                "pulsos por unidad, o una salida de 4-20 mA.",
            )
        elif hz > TASA_MAX_HZ * 0.5:
            esc.avisar(
                AVISO,
                f"A fondo de escala llega a {hz:.0f} pulsos/s, más de la mitad del "
                f"techo de {TASA_MAX_HZ:g}. Queda poco margen si el caudal se pasa "
                "de lo previsto.",
            )

    # ── Advertencias que valen siempre ──────────────────────────────────
    esc.avisar(
        AVISO,
        f"El contacto necesita alimentación y referencia: un canal declarado con "
        f"ExciteCh({canal_excitacion}) queda en ~3,3 V y excita el contacto, y el "
        f"borne de conteo lleva un pull-down de 10 kΩ al NEGATIVO. En reposo el nodo "
        f"está en 0 V y cada pulso lo sube, así que el flanco es de subida (RISING, "
        f"que es el que el equipo usa por defecto). Sin la excitación no hay fuente y "
        f"no se genera ningún pulso.",
    )
    esc.avisar(
        AVISO,
        f"El contador se pone en cero en cada scan, así que «{nombre}» tiene los "
        f"pulsos de los últimos {scan_seg:g} segundos, no un acumulado. En la tabla "
        "de datos usá Totalize; con Sample solo guardarías el último scan y "
        "perderías el resto.",
    )
    esc.avisar(
        NOTA,
        "El Offset va en 0 a propósito: se suma en cada scan, así que cualquier "
        "otro valor le inventa un total que nunca ocurrió.",
    )
    esc.avisar(
        NOTA,
        f"El canal de pulsos comparte los bornes con las entradas analógicas y el "
        f"equipo no lo reserva. Si además usás sensores analógicos, asignales el "
        f"canal a mano con AIChannel para que ninguno caiga en A{canal - 1}.",
    )

    esc.codigo = "\n".join([
        f"'-- Contador de pulsos {nombre}: {detalle}",
        f"'   Conteo en P{canal}, con pull-down de 10k al NEGATIVO.",
        f"'   La excitacion de I{canal_excitacion} alimenta el contacto (~3.3 V):",
        f"'   en reposo el nodo esta en 0 V y cada pulso lo sube (flanco RISING).",
        f"'   Tope del equipo: {TASA_MAX_HZ:g} pulsos/s por el antirrebote de "
        f"{DEBOUNCE_MS:g} ms.",
        f"Public {nombre}",
        f"Units {nombre} = {unidad}" if unidad else "",
        f"ExciteCh({canal_excitacion})",
        f"PulseCount({nombre}, 1, P{canal}, 2, 0, {_num(mult, 8)}, 0.0)",
        f"PulseEdge({nombre}, Rising)",
        "",
        "' En la tabla, acumulado del periodo:",
        f"'     Totalize(1, {nombre}, FP2)",
        "",
    ])
    return esc
