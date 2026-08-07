"""Catálogo de instrucciones, en castellano llano.

Este dialecto lo escribe gente que instala sensores, no programadores, así
que cada instrucción explica qué hace, para qué sirve cada argumento y
—sobre todo— cuáles de esos argumentos el Opta acepta pero después ignora.
Un argumento que no hace nada es peor que uno que falta: parece que el
programa está configurado y no lo está.

Toda la información está verificada contra parse_crbasic() en
OptaPakBus.ino; el campo `trampa` es lo que el equipo no avisa por su
cuenta.
"""

from dataclasses import dataclass, field


@dataclass
class Param:
    nombre: str
    descripcion: str
    #: El Opta lo acepta por compatibilidad con CR1000 pero no lo usa.
    ignorado: bool = False
    opcional: bool = False


@dataclass
class Instr:
    nombre: str
    firma: str
    resumen: str
    categoria: str
    detalle: str = ""
    parametros: "list[Param]" = field(default_factory=list)
    ejemplo: str = ""
    trampa: str = ""

    @property
    def usa_parentesis(self) -> bool:
        return "(" in self.firma

    def firma_partes(self) -> "list[str]":
        """La firma troceada en argumentos, para resaltar el activo."""
        if not self.usa_parentesis:
            return []
        dentro = self.firma[self.firma.find("(") + 1 : self.firma.rfind(")")]
        return [p.strip() for p in dentro.split(",")] if dentro.strip() else []


_MULT_OFFSET = (
    "Convierte la lectura a la unidad que te interesa: "
    "valor = lectura × Mult + Offset. Para un sensor de 4-20 mA que mide de "
    "MIN a MAX, Mult = (MAX − MIN) / 16 y Offset = MIN − 4 × Mult."
)

CATALOGO: "list[Instr]" = [
    # ── Declaraciones ────────────────────────────────────────────────
    Instr(
        nombre="Public",
        firma="Public Nombre1, Nombre2",
        resumen="Crea variables visibles desde la plataforma",
        categoria="Declaraciones",
        detalle=(
            "Reserva un espacio con nombre donde guardar un número. Todas las "
            "variables del Opta son decimales, no hace falta elegir tipo.\n\n"
            "Se pueden declarar varias en la misma línea separadas por comas. "
            "Todas aparecen en la tabla Public de la plataforma, así que desde "
            "ahí se pueden leer y también escribir para mandarle órdenes al "
            "equipo."
        ),
        ejemplo="Public Nivel, Caudal\nPublic MoverCm",
        trampa=(
            "Tiene que ir pegada al margen izquierdo. Si la indentás, el equipo "
            "registra una variable llamada «Public» y puede perder el nombre "
            "real. En el Opta, Dim hace exactamente lo mismo que Public: no "
            "existen las variables privadas."
        ),
    ),
    Instr(
        nombre="Dim",
        firma="Dim Nombre1, Nombre2",
        resumen="Igual que Public en este equipo",
        categoria="Declaraciones",
        detalle=(
            "En un CR1000 de verdad, Dim crea una variable interna que no se "
            "publica. En el Opta no hay esa distinción: Dim y Public hacen lo "
            "mismo y las dos terminan visibles en la plataforma.\n\n"
            "Conviene usar Dim igual, para las variables de cálculo intermedio: "
            "deja más claro qué es un dato de verdad y qué es una cuenta auxiliar."
        ),
        ejemplo="Dim Auxiliar\nDim Objetivo_cm",
        trampa="Misma regla que Public: sin sangría, en la columna 0.",
    ),
    Instr(
        nombre="Const",
        firma="Const Nombre = valor",
        resumen="Un número fijo con nombre, para la calibración",
        categoria="Declaraciones",
        detalle=(
            "Le pone nombre a un número que no cambia nunca: un factor de "
            "calibración, un umbral de alarma, el rango de un sensor.\n\n"
            "La ventaja es que si mañana hay que recalibrar, se toca un solo "
            "lugar arriba del programa en vez de buscar el número suelto en el "
            "medio de las cuentas."
        ),
        ejemplo="Const Nivel_Mult = 0.3125\nConst Nivel_Alto = 4.2",
        trampa=(
            "Solo admite un número escrito directamente. «Const B = A * 2» no "
            "funciona: el equipo lee lo que puede del principio del texto y la "
            "constante termina valiendo 0. Si el valor sale de una cuenta, "
            "hacé la cuenta con la calculadora y escribí el resultado, dejando "
            "la fórmula en un comentario."
        ),
    ),
    Instr(
        nombre="Units",
        firma="Units Variable = unidad",
        resumen="Le pone unidad a una variable; con mA además activa el sensor",
        categoria="Declaraciones",
        detalle=(
            "Indica en qué unidad está la variable. El texto viaja a la "
            "plataforma y aparece en los gráficos.\n\n"
            "En el Opta tiene un efecto extra que no existe en un CR1000: si la "
            "unidad es exactamente «mA», la variable queda marcada como entrada "
            "de 4-20 mA y el equipo le asigna un canal físico automáticamente, "
            "sin necesidad de ninguna otra instrucción."
        ),
        ejemplo="Public Nivel_mA\nUnits Nivel_mA = mA",
        trampa=(
            "Sin sangría, en la columna 0. Y ojo: si a una variable con "
            "Units = mA además le asignás un valor con un cálculo, pierde el "
            "canal y queda en 0 para siempre. La variable del sensor y la del "
            "cálculo tienen que ser distintas."
        ),
    ),

    # ── Configuración del equipo ─────────────────────────────────────
    Instr(
        nombre="StationName",
        firma="StationName=Nombre",
        resumen="Nombre con el que el equipo se presenta",
        categoria="Configuración del equipo",
        detalle=(
            "El nombre que reporta el equipo cuando se conecta al servidor. "
            "Máximo 23 caracteres, sin espacios."
        ),
        ejemplo="StationName=Compuerta_1",
    ),
    Instr(
        nombre="ServerHost",
        firma="ServerHost=dominio_o_ip",
        resumen="A qué servidor se conecta el equipo",
        categoria="Configuración del equipo",
        detalle=(
            "Dominio o dirección IP del servidor. Gracias a esta línea el mismo "
            "firmware sirve para todos los equipos: cada uno lleva su "
            "configuración de red en su propio programa. Máximo 63 caracteres."
        ),
        ejemplo="ServerHost=loggerip.ingproy.com",
    ),
    Instr(
        nombre="ServerPort",
        firma="ServerPort=numero",
        resumen="Puerto del servidor; su presencia da por provisionado al equipo",
        categoria="Configuración del equipo",
        detalle=(
            "El puerto donde escucha el servidor para este equipo, entre 1 y "
            "65535.\n\n"
            "Es la línea más importante de las cuatro: que exista es lo que "
            "marca al equipo como «ya provisionado»."
        ),
        ejemplo="ServerPort=6786",
        trampa=(
            "Sin esta línea el equipo se considera sin provisionar y se conecta "
            "al puerto de provisión (4789) en vez del operativo, así que los "
            "datos no llegan a donde esperás."
        ),
    ),
    Instr(
        nombre="PakBusAddress",
        firma="PakBusAddress=numero",
        resumen="Número de identificación del equipo en la red",
        categoria="Configuración del equipo",
        detalle=(
            "La dirección PakBus de este equipo, entre 1 y 4094. Tiene que "
            "coincidir exactamente con el node_id que tiene cargado el logger "
            "en el servidor, o no se van a reconocer."
        ),
        ejemplo="PakBusAddress=1",
    ),
    Instr(
        nombre="Scan",
        firma="Scan(Intervalo, Unidad, Buffers, MaxScans)",
        resumen="Cada cuánto el equipo lee los sensores y ejecuta el programa",
        categoria="Configuración del equipo",
        detalle=(
            "Marca el pulso de todo el programa. En cada scan el equipo lee las "
            "entradas, hace las cuentas, mueve los relés y actualiza los "
            "acumuladores de las tablas."
        ),
        parametros=[
            Param("Intervalo", "Cada cuánto, en la unidad del argumento siguiente."),
            Param("Unidad", "Sec, Min, Hour o Day. Alcanza con las 3 primeras letras."),
            Param("Buffers", "Solo por compatibilidad con CR1000.", ignorado=True),
            Param("MaxScans", "Solo por compatibilidad con CR1000.", ignorado=True),
        ],
        ejemplo="Scan(10, Sec, 0, 0)",
        trampa=(
            "El mínimo real es 1 segundo: cualquier valor menor se sube a 1. "
            "«Msec» NO se reconoce y se toma como segundos, así que "
            "Scan(500, Msec) no son medio segundo sino 500 segundos. Si falta "
            "la instrucción, el intervalo es de 60 segundos."
        ),
    ),

    # ── Entradas ─────────────────────────────────────────────────────
    Instr(
        nombre="AIChannel",
        firma="AIChannel(Variable, Canal)",
        resumen="Fija a mano en qué borne físico está conectado un sensor",
        categoria="Entradas",
        detalle=(
            "Es la forma más segura de mapear un sensor: dice explícitamente "
            "que tal variable se lee de tal borne, sin depender del orden en "
            "que estén declaradas las variables.\n\n"
            "Sirve tanto para sensores de 4-20 mA como de voltaje. Es una "
            "instrucción propia del Opta, no existe en un CR1000."
        ),
        parametros=[
            Param("Variable", "La variable donde se guarda la lectura. Tiene que estar declarada antes."),
            Param("Canal", "El borne, de 1 a 8. El 1 es I1 (A0), el 8 es I8 (A7)."),
        ],
        ejemplo="Public Nivel_mA\nUnits Nivel_mA = mA\nAIChannel(Nivel_mA, 1)",
        trampa=(
            "Fijar un canal a mano NO lo reserva: el reparto automático puede "
            "volver a entregarlo a otra variable y las dos terminan leyendo el "
            "mismo borne. Si usás AIChannel para uno, usalo para todos."
        ),
    ),
    Instr(
        nombre="VoltSE",
        firma="VoltSE(Destino, Reps, Rango, Canal, Estab, Integ, Mult, Offset)",
        resumen="Lee una entrada de voltaje respecto a masa",
        categoria="Entradas",
        detalle=(
            "Mide el voltaje de un borne de entrada. El Opta acepta la "
            "instrucción completa de un CR1000 para que los programas sean "
            "portables, pero solo usa cuatro de sus argumentos.\n\n"
            "El escalado se aplica sobre milivolts, no sobre volts, para poder "
            "reutilizar sin tocar nada las constantes de un programa CR1000 "
            "original."
        ),
        parametros=[
            Param("Destino", "La variable donde se guarda la lectura."),
            Param("Reps", "Cuántos canales seguidos leer. En el Opta siempre 1."),
            Param("Rango", "Rango del CR1000 (mV5000, etc.).", ignorado=True),
            Param("Canal", "El borne, de 1 a 8. Si no es un número válido, se asigna automáticamente."),
            Param("Estab", "Tiempo de estabilización.", ignorado=True),
            Param("Integ", "Integración (_60Hz, etc.).", ignorado=True),
            Param("Mult", _MULT_OFFSET),
            Param("Offset", "El valor que se suma después de multiplicar."),
        ],
        ejemplo="Public Temp\nVoltSE(Temp, 1, mV5000, 1, 0, 0, 0.1, 0.0)",
        trampa=(
            "Mult y Offset son SIEMPRE los dos últimos argumentos, pero el "
            "equipo solo los lee si escribís 6 argumentos o más. Con menos "
            "quedan en 1.0 y 0.0 y la lectura sale sin escalar, sin ningún aviso."
        ),
    ),
    Instr(
        nombre="VoltDiff",
        firma="VoltDiff(Destino, Reps, Rango, Canal, RevDif, Estab, Integ, Mult, Offset)",
        resumen="Lee una entrada de voltaje diferencial",
        categoria="Entradas",
        detalle=(
            "En un CR1000 mide la diferencia entre dos bornes. El Opta la trata "
            "igual que VoltSE, porque su hardware de entrada es siempre "
            "respecto a masa. Se acepta para que los programas de un CR1000 se "
            "puedan reutilizar sin reescribirlos."
        ),
        parametros=[
            Param("Destino", "La variable donde se guarda la lectura."),
            Param("Reps", "Cuántos canales seguidos leer. En el Opta siempre 1."),
            Param("Rango", "Rango del CR1000.", ignorado=True),
            Param("Canal", "El borne, de 1 a 8."),
            Param("RevDif", "Medición con polaridad invertida.", ignorado=True),
            Param("Estab", "Tiempo de estabilización.", ignorado=True),
            Param("Integ", "Integración.", ignorado=True),
            Param("Mult", _MULT_OFFSET),
            Param("Offset", "El valor que se suma después de multiplicar."),
        ],
        ejemplo="Public Presion\nVoltDiff(Presion, 1, mV5000, 2, False, 0, 0, 0.2, -5.0)",
        trampa="Misma regla que VoltSE: sin 6 argumentos o más, Mult y Offset se ignoran.",
    ),
    Instr(
        nombre="PulseCount",
        firma="PulseCount(Destino, Reps, Canal, Config, Opcion, Mult, Offset)",
        resumen="Cuenta pulsos de un contacto seco, como un pluviómetro",
        categoria="Entradas",
        detalle=(
            "Cuenta cuántas veces se cerró un contacto desde el scan anterior. "
            "El uso típico es el pluviómetro de cangilones: cada volcada es un "
            "pulso, y con Mult se convierte a milímetros.\n\n"
            "El contador se pone en cero en cada scan, así que la variable "
            "guarda los pulsos DEL ÚLTIMO SCAN, no un total acumulado. Para "
            "tener el acumulado usá Totalize en la tabla de datos."
        ),
        parametros=[
            Param("Destino", "La variable donde se guarda el conteo ya escalado."),
            Param("Reps", "Siempre 1 en el Opta.", ignorado=True),
            Param("Canal", "El borne, de P1 a P8 (o de 1 a 8)."),
            Param("Config", "Tipo de entrada del CR1000.", ignorado=True),
            Param("Opcion", "Opción de conteo del CR1000.", ignorado=True),
            Param("Mult", "Cuánto vale cada pulso. Un pluviómetro de 0,2 mm por volcada lleva 0.2."),
            Param("Offset", "Se suma en CADA scan, así que acá va 0 salvo que sepas muy bien lo que hacés."),
        ],
        ejemplo="Public Lluvia_mm\nPulseCount(Lluvia_mm, 1, P1, 2, 0, 0.2, 0.0)",
        trampa=(
            "No cuenta más de 20 pulsos por segundo. El firmware tiene un "
            "antirrebote fijo de 50 ms, pensado para el contacto de un "
            "pluviómetro; un caudalímetro de turbina, que suele dar cientos de "
            "pulsos por segundo, se cuenta muy por debajo de lo real y sin "
            "ningún aviso. El asistente de sensores (Ctrl+M) hace esa "
            "verificación con los datos del sensor.\n\n"
            "El contacto necesita alimentación y referencia. Lo habitual es "
            "tomarla de la fuente del gabinete con un divisor:\n\n"
            "    +12 V ── 2,2 kΩ ── [contacto] ── borne ── 10 kΩ ── NEGATIVO\n\n"
            "Con el contacto cerrado el borne queda cerca de 8 V y abierto en "
            "0 V, así que el pulso llega como flanco de subida, que es el que "
            "el equipo cuenta por defecto.\n\n"
            "Ojo con dimensionar el divisor a ojo: la entrada del Opta "
            "presenta unos 7,8 kΩ a masa y queda en paralelo con la "
            "resistencia de abajo. Un divisor de 10 kΩ/10 kΩ desde 12 V "
            "parece dar 6 V y en realidad da 3,66, que no alcanza para que el "
            "contador dispare. El asistente de sensores hace esa cuenta.\n\n"
            "El Offset se suma en cada scan, no una sola vez. Con Totalize en "
            "la tabla, un Offset distinto de 0 acumula un total que nunca "
            "ocurrió.\n\n"
            "El canal de pulsos no queda reservado, así que puede chocar con un "
            "sensor analógico en el mismo borne. Y si el canal que escribís no "
            "es válido, el equipo usa el P1 sin avisar."
        ),
    ),

    # ── Salidas ──────────────────────────────────────────────────────
    Instr(
        nombre="PortSet",
        firma="PortSet(Variable, Valor, Rele)",
        resumen="Conecta una variable con un relé físico",
        categoria="Salidas",
        detalle=(
            "Declara que tal variable maneja tal relé. A partir de ahí, en cada "
            "scan el relé sigue el valor de la variable: mayor que 0,5 cierra, "
            "menor abre.\n\n"
            "Con eso el programa controla el relé con su propia lógica, por "
            "ejemplo «If (Nivel < Minimo) Then Bomba = 1». También se puede "
            "accionar a mano desde la plataforma escribiendo la variable."
        ),
        parametros=[
            Param("Variable", "La variable que va a manejar el relé."),
            Param("Valor", "En el Opta no hace nada: no fija el estado inicial ni acciona el relé.", ignorado=True),
            Param("Rele", "Cuál de los 4 relés, de 1 a 4.", opcional=True),
        ],
        ejemplo="Public Bomba\nPortSet(Bomba, 0, 1)",
        trampa=(
            "El segundo argumento no hace absolutamente nada, aunque parezca "
            "que fija el estado. Lo que mueve el relé es el valor de la "
            "variable en cada scan.\n\n"
            "Si omitís el tercer argumento, el equipo deduce el relé del nombre "
            "de la variable: tiene que empezar con DO seguido del número "
            "(DO1 a DO4). Con cualquier otro nombre y sin tercer argumento, "
            "queda pegado al relé 1 por descarte. Conviene indicarlo siempre."
        ),
    ),

    # ── Tablas de datos ──────────────────────────────────────────────
    Instr(
        nombre="DataTable",
        firma="DataTable(Nombre, Disparador, Tamaño)",
        resumen="Abre una tabla donde se guarda el histórico",
        categoria="Tablas de datos",
        detalle=(
            "Define qué se archiva y cada cuánto. Se cierra con EndTable, y "
            "entre las dos van el DataInterval y la lista de campos.\n\n"
            "Se pueden tener hasta 4 tablas, por ejemplo una con promedios "
            "cada minuto y otra con máximos y mínimos diarios."
        ),
        parametros=[
            Param("Nombre", "Cómo se va a llamar la tabla en la plataforma. Máximo 23 caracteres."),
            Param("Disparador", "En el Opta no hace nada: la tabla siempre está activa.", ignorado=True),
            Param("Tamaño", "Cuántos registros guarda antes de pisar los más viejos. Con -1 usa 50000.", opcional=True),
        ],
        ejemplo=(
            "DataTable(Registro, True, 10080)\n"
            "    DataInterval(0, 1, Min, 0)\n"
            "    Average(1, Nivel, FP2)\n"
            "EndTable"
        ),
        trampa=(
            "Es obligatoria: si el programa no define NINGUNA tabla, el equipo "
            "lo descarta entero y vuelve a su esquema fijo de fábrica. No "
            "ejecuta ni las cuentas ni los relés, y no avisa nada."
        ),
    ),
    Instr(
        nombre="DataInterval",
        firma="DataInterval(Desde, Intervalo, Unidad, Saltos)",
        resumen="Cada cuánto la tabla guarda un registro",
        categoria="Tablas de datos",
        detalle=(
            "Va adentro de un bloque DataTable. Marca cada cuánto se cierra un "
            "registro y se escribe en la memoria.\n\n"
            "Entre un archivado y el siguiente, el equipo va acumulando: si el "
            "campo es Average junta el promedio de todos los scans de ese "
            "período, si es Maximum se queda con el mayor, y así."
        ),
        parametros=[
            Param("Desde", "Alineación con el reloj del CR1000.", ignorado=True),
            Param("Intervalo", "Cada cuánto se guarda, en la unidad siguiente."),
            Param("Unidad", "Sec, Min, Hour o Day."),
            Param("Saltos", "Manejo de intervalos perdidos del CR1000.", ignorado=True),
        ],
        ejemplo="DataInterval(0, 5, Min, 0)",
        trampa=(
            "Si falta, el intervalo queda en 0 y la tabla NO guarda ni un solo "
            "registro. La tabla existe, aparece en la plataforma y está siempre "
            "vacía."
        ),
    ),
    Instr(
        nombre="Sample",
        firma="Sample(Reps, Variable, Tipo)",
        resumen="Guarda el valor del momento exacto en que se archiva",
        categoria="Tablas de datos",
        detalle=(
            "Toma una foto: guarda cuánto valía la variable justo cuando tocó "
            "archivar, ignorando todo lo que pasó en el medio.\n\n"
            "Es lo que corresponde para estados y contadores —posición de una "
            "compuerta, si una bomba está andando, una alarma— donde promediar "
            "no tendría sentido."
        ),
        parametros=[
            Param("Reps", "Siempre 1: el Opta no maneja arreglos."),
            Param("Variable", "Qué variable guardar. Tiene que estar declarada."),
            Param("Tipo", "FP2, INT4, etc. Se acepta pero no cambia nada: todo se transmite igual.", opcional=True, ignorado=True),
        ],
        ejemplo="Sample(1, Nivel, FP2)",
        trampa=(
            "Si el nombre de la variable tiene un error de tipeo, el campo se "
            "crea igual y archiva 0 para siempre. El equipo lo anota en su log "
            "pero la tabla parece normal."
        ),
    ),
    Instr(
        nombre="Average",
        firma="Average(Reps, Variable, Tipo)",
        resumen="Guarda el promedio del período",
        categoria="Tablas de datos",
        detalle=(
            "Promedia todas las lecturas tomadas entre un archivado y el "
            "siguiente. Es lo adecuado para mediciones que fluctúan —nivel, "
            "caudal, temperatura— porque suaviza el ruido del sensor."
        ),
        parametros=[
            Param("Reps", "Siempre 1."),
            Param("Variable", "Qué variable promediar."),
            Param("Tipo", "Se acepta pero no cambia nada.", opcional=True, ignorado=True),
        ],
        ejemplo="Average(1, Caudal, FP2)",
    ),
    Instr(
        nombre="Maximum",
        firma="Maximum(Reps, Variable, Tipo)",
        resumen="Guarda el valor más alto del período",
        categoria="Tablas de datos",
        detalle=(
            "Se queda con la lectura más alta entre un archivado y el "
            "siguiente. Con un intervalo diario da el pico del día."
        ),
        parametros=[
            Param("Reps", "Siempre 1."),
            Param("Variable", "Qué variable vigilar."),
            Param("Tipo", "Se acepta pero no cambia nada.", opcional=True, ignorado=True),
        ],
        ejemplo="Maximum(1, Nivel, FP2)",
    ),
    Instr(
        nombre="Minimum",
        firma="Minimum(Reps, Variable, Tipo)",
        resumen="Guarda el valor más bajo del período",
        categoria="Tablas de datos",
        detalle="Igual que Maximum pero con el valor más bajo del período.",
        parametros=[
            Param("Reps", "Siempre 1."),
            Param("Variable", "Qué variable vigilar."),
            Param("Tipo", "Se acepta pero no cambia nada.", opcional=True, ignorado=True),
        ],
        ejemplo="Minimum(1, Nivel, FP2)",
    ),
    Instr(
        nombre="Totalize",
        firma="Totalize(Reps, Variable, Tipo)",
        resumen="Suma todo lo del período",
        categoria="Tablas de datos",
        detalle=(
            "Suma todas las lecturas del período. Es lo que hay que usar con "
            "un pluviómetro: PulseCount da los milímetros de cada scan y "
            "Totalize los acumula para dar el total del período."
        ),
        parametros=[
            Param("Reps", "Siempre 1."),
            Param("Variable", "Qué variable acumular."),
            Param("Tipo", "Se acepta pero no cambia nada.", opcional=True, ignorado=True),
        ],
        ejemplo="Totalize(1, Lluvia_mm, FP2)",
    ),
    Instr(
        nombre="EndTable",
        firma="EndTable",
        resumen="Cierra el bloque DataTable",
        categoria="Tablas de datos",
        detalle="Marca dónde termina la lista de campos de la tabla.",
        ejemplo="EndTable",
        trampa=(
            "Si falta, todo lo que siga en el archivo se sigue interpretando "
            "como campos de esa tabla."
        ),
    ),

    # ── Estructura y control ─────────────────────────────────────────
    Instr(
        nombre="If",
        firma="If (condicion) Then accion",
        resumen="Hace algo solo si se cumple una condición",
        categoria="Estructura y control",
        detalle=(
            "Tiene dos formas.\n\n"
            "En UNA LÍNEA, con la acción a continuación del Then. Esta forma NO "
            "lleva EndIf:\n"
            "    If (Nivel > 4.0) Then Bomba = 0\n\n"
            "En BLOQUE, cuando después del Then no va nada más. Ahí sí necesita "
            "su EndIf y puede llevar ElseIf y Else:\n"
            "    If (Nivel > 4.0) Then\n"
            "        Bomba = 0\n"
            "        Alarma = 1\n"
            "    EndIf\n\n"
            "La comparación puede ser <, >, <=, >=, = o <>, y del lado "
            "izquierdo siempre tiene que haber una variable. Se pueden unir dos "
            "comparaciones con AND o con OR."
        ),
        ejemplo="If (Nivel < Nivel_Bajo) AND (Bomba = 0) Then Bomba = 1",
        trampa=(
            "Si a un If de una línea le agregás un EndIf, ese EndIf queda "
            "suelto y las líneas de abajo dejan de estar condicionadas, sin "
            "ningún error.\n\n"
            "Como mucho dos comparaciones, y con un solo conector: ni tres "
            "condiciones ni AND y OR mezclados. El equipo se queda con las dos "
            "primeras y descarta el resto en silencio."
        ),
    ),
    Instr(
        nombre="ElseIf",
        firma="ElseIf (condicion) Then",
        resumen="Otra condición a probar si la anterior no se cumplió",
        categoria="Estructura y control",
        detalle=(
            "Solo dentro de un If de bloque. Se prueba únicamente si ninguna de "
            "las ramas anteriores se cumplió."
        ),
        ejemplo=(
            "If (Nivel < 1.0) Then\n"
            "    Bomba = 1\n"
            "ElseIf (Nivel > 4.0) Then\n"
            "    Bomba = 0\n"
            "EndIf"
        ),
        trampa=(
            "Va en UNA sola palabra. Escrito «Else If» separado, el equipo lo "
            "toma como un Else común, tira la condición y esa rama se ejecuta "
            "siempre."
        ),
    ),
    Instr(
        nombre="Else",
        firma="Else",
        resumen="Qué hacer si no se cumplió ninguna condición anterior",
        categoria="Estructura y control",
        ejemplo="Else\n    Alarma = 0",
        trampa="Lo que escribas en la misma línea después de Else se descarta.",
    ),
    Instr(
        nombre="EndIf",
        firma="EndIf",
        resumen="Cierra un If de bloque",
        categoria="Estructura y control",
        detalle="Se acepta junto (EndIf) o separado (End If).",
        ejemplo="EndIf",
        trampa="No va después de un If de una sola línea.",
    ),
    Instr(
        nombre="BeginProg",
        firma="BeginProg",
        resumen="Marca dónde empieza el programa (decorativo en el Opta)",
        categoria="Estructura y control",
        detalle=(
            "El Opta la ignora, pero conviene escribirla igual: mantiene el "
            "archivo legible y compatible con un CR1000 de verdad."
        ),
        ejemplo="BeginProg",
    ),
    Instr(
        nombre="EndProg",
        firma="EndProg",
        resumen="Marca el final del programa (decorativo en el Opta)",
        categoria="Estructura y control",
        ejemplo="EndProg",
    ),
    Instr(
        nombre="NextScan",
        firma="NextScan",
        resumen="Cierra el bloque Scan (decorativo en el Opta)",
        categoria="Estructura y control",
        ejemplo="NextScan",
    ),
    Instr(
        nombre="CallTable",
        firma="CallTable Nombre",
        resumen="Innecesaria: el archivado es automático",
        categoria="Estructura y control",
        detalle=(
            "En un CR1000 hay que llamarla para que la tabla grabe. En el Opta "
            "el archivado lo gobierna solo el DataInterval de cada tabla, así "
            "que esta línea no hace falta. Se puede dejar por costumbre."
        ),
        ejemplo="CallTable Registro",
    ),

    # ── Funciones de cálculo ─────────────────────────────────────────
    Instr(
        nombre="Abs",
        firma="Abs(numero)",
        resumen="Valor absoluto: convierte los negativos en positivos",
        categoria="Funciones de cálculo",
        detalle=(
            "Devuelve el número sin signo. Sirve para comparar diferencias sin "
            "importar hacia qué lado: Abs(Actual - Objetivo) da lo lejos que "
            "estás del objetivo, se haya pasado o no."
        ),
        parametros=[Param("numero", "Una variable, una constante o una cuenta.")],
        ejemplo="Distancia = Abs(Actual - Objetivo)",
    ),
    Instr(
        nombre="Int",
        firma="Int(numero)",
        resumen="Descarta los decimales",
        categoria="Funciones de cálculo",
        detalle="Se queda con la parte entera: Int(3.9) da 3 e Int(-3.9) da -3.",
        parametros=[Param("numero", "Una variable, una constante o una cuenta.")],
        ejemplo="Vueltas = Int(Pulsos / 100)",
    ),
    Instr(
        nombre="Sqr",
        firma="Sqr(numero)",
        resumen="Raíz cuadrada",
        categoria="Funciones de cálculo",
        detalle=(
            "Raíz cuadrada del número. Con un número negativo devuelve 0 en vez "
            "de dar error. Se usa sobre todo con vertederos y caudales, donde "
            "el caudal va con la raíz de la altura."
        ),
        parametros=[Param("numero", "Una variable, una constante o una cuenta.")],
        ejemplo="Caudal = 1.84 * Ancho * Sqr(Altura)",
        trampa=(
            "Abs, Int y Sqr son las TRES únicas funciones que existen. No hay "
            "Sin, Cos, Ln, Exp ni Mod: si la fórmula las necesita, hay que "
            "resolverlas con una tabla de valores y comparaciones If."
        ),
    ),

    # ── Reconocidas pero sin efecto ──────────────────────────────────
    Instr(
        nombre="Battery",
        firma="Battery(Variable, Canal)",
        resumen="Mide el voltaje de alimentación en el borne que le indiques",
        categoria="Entradas",
        detalle=(
            "Lee la tensión de alimentación a través del divisor resistivo, "
            "aplicando el factor 3,351 que le corresponde.\n\n"
            "Hasta el firmware 1.6.8 esta instrucción no hacía nada y el "
            "divisor tenía que estar sí o sí en el borne 8. Desde la 1.6.9 "
            "podés indicar en cuál está cableado. El canal queda reservado: no "
            "se lo reparte a ninguna otra variable.\n\n"
            "Sigue funcionando el atajo viejo: una variable con «att» en el "
            "nombre —BattV, Batt_Volt— que no tenga Units = mA ni VoltSE toma "
            "el borne 8 sola. Pero solo si ese borne está libre."
        ),
        parametros=[
            Param("Variable", "La variable donde se guarda el voltaje."),
            Param("Canal", "El borne donde está el divisor, de 1 a 8. Sin este argumento usa el 8.", opcional=True),
        ],
        ejemplo="Public BattV\nBattery(BattV, 8)",
        trampa=(
            "Un canal fuera del rango 1-8 se registra en el log y cae al 8 "
            "igual. Y si usás el atajo del nombre con «att» pero el borne 8 ya "
            "está ocupado por otra cosa, la variable se queda sin canal y vale "
            "0: ahí hay que declararla con Battery(Variable, N)."
        ),
    ),
    Instr(
        nombre="ExciteCh",
        firma="ExciteCh(Canal)",
        resumen="Alimenta un contacto desde el propio Opta, cuando no hay fuente",
        categoria="Entradas",
        detalle=(
            "Convierte un borne de entrada en una salida fija en alto, de unos "
            "3,3 V, para usarla como fuente del contacto de un sensor de "
            "pulsos.\n\n"
            "**Solo hace falta si no hay una fuente en el gabinete.** Lo normal "
            "es alimentar el contacto desde los 12 V con un divisor —ver "
            "PulseCount—, y en ese caso esta instrucción no va.\n\n"
            "El canal queda reservado y no se lo reparte a ninguna medición. Es "
            "una instrucción propia del Opta, no existe en un CR1000."
        ),
        parametros=[Param("Canal", "El borne que pasa a ser salida, de 1 a 8.")],
        ejemplo="ExciteCh(2)\nPulseCount(Lluvia_mm, 1, P1, 2, 0, 0.2, 0.0)",
        trampa=(
            "Esos 3,3 V salen a través de la red divisora de la entrada, con "
            "impedancia de fuente alta, y el contador necesita alrededor de "
            "7,4 V en el borne para disparar. Con un pull-down colgando puede "
            "no llegar nunca. Medilo con el circuito armado antes de darlo por "
            "bueno; si no llega, alimentá el contacto desde la fuente.\n\n"
            "Tampoco pongas la excitación en el mismo borne que el conteo: la "
            "salida gana y el contador no ve ningún flanco."
        ),
    ),
    Instr(
        nombre="PulseEdge",
        firma="PulseEdge(Variable, Flanco)",
        resumen="Elige si el contador cuenta al subir o al bajar la señal",
        categoria="Entradas",
        detalle=(
            "Indica en qué momento del pulso hay que contar. Por defecto es "
            "Rising, que es lo que corresponde al montaje con excitación y "
            "pull-down al negativo: el nodo está en 0 V y sube con cada pulso.\n\n"
            "Se usa Falling en el montaje inverso, con pull-up: el nodo está "
            "en alto en reposo y el contacto lo lleva a masa.\n\n"
            "Acepta Rising o Falling, y también Subida o Bajada. Es una "
            "instrucción propia del Opta."
        ),
        parametros=[
            Param("Variable", "La variable del PulseCount cuyo flanco se cambia."),
            Param("Flanco", "Rising o Falling (también valen Subida y Bajada)."),
        ],
        ejemplo="PulseCount(Lluvia_mm, 1, P1, 2, 0, 0.2, 0.0)\nPulseEdge(Lluvia_mm, Rising)",
        trampa=(
            "Hasta el firmware 1.6.8 el flanco era Falling y no se podía "
            "cambiar. Si tenés un montaje viejo con pull-up, ahora hay que "
            "escribir PulseEdge(Variable, Falling) explícitamente o el contador "
            "no va a contar lo mismo que antes."
        ),
    ),
    Instr(
        nombre="PanelTemp",
        firma="PanelTemp(Variable, Integ)",
        resumen="No hace nada: el Opta no tiene sensor de temperatura interno",
        categoria="Reconocidas sin efecto",
        detalle="Se reconoce para no romper programas de CR1000, pero la variable queda en 0.",
        parametros=[
            Param("Variable", "Queda en 0.", ignorado=True),
            Param("Integ", "Sin efecto.", ignorado=True),
        ],
        ejemplo="PanelTemp(Temp_Interna, 0)",
    ),
    Instr(
        nombre="BrHalf",
        firma="BrHalf(Destino, Reps, Rango, Canal, Exc, Estab, Integ, Mult, Offset)",
        resumen="No hace nada: no hay puente resistivo en el Opta",
        categoria="Reconocidas sin efecto",
        detalle="Se reconoce para no romper programas de CR1000, pero la variable queda en 0.",
        ejemplo="BrHalf(Sensor, 1, mV2500, 1, 1, 0, 0, 1.0, 0.0)",
    ),
    Instr(
        nombre="SW12",
        firma="SW12(Estado)",
        resumen="No hace nada: el Opta no tiene salida de 12V conmutada",
        categoria="Reconocidas sin efecto",
        detalle="Para cortar la alimentación de un sensor usá un relé con PortSet.",
        ejemplo="SW12(1)",
    ),
    Instr(
        nombre="RealTime",
        firma="RealTime(Destino)",
        resumen="No hace nada: no hay funciones de fecha y hora",
        categoria="Reconocidas sin efecto",
        detalle=(
            "El equipo tiene reloj y le pone fecha y hora a cada registro "
            "archivado, pero el programa no puede consultarla ni tomar "
            "decisiones según la hora."
        ),
        ejemplo="RealTime(Hora)",
    ),
]

_POR_NOMBRE = {i.nombre.upper(): i for i in CATALOGO}

CATEGORIAS = [
    "Declaraciones",
    "Configuración del equipo",
    "Entradas",
    "Salidas",
    "Tablas de datos",
    "Estructura y control",
    "Funciones de cálculo",
    "Reconocidas sin efecto",
]


def buscar(nombre: str) -> "Instr | None":
    return _POR_NOMBRE.get((nombre or "").upper())


def por_categoria(categoria: str) -> "list[Instr]":
    return [i for i in CATALOGO if i.categoria == categoria]


def nombres() -> "list[str]":
    return [i.nombre for i in CATALOGO]


def contexto_llamada(linea: str, columna: int) -> "tuple[str, int] | None":
    """Qué instrucción se está escribiendo y en qué argumento está el cursor.

    Recorre la línea hasta la posición del cursor llevando una pila de
    paréntesis abiertos. Devuelve (nombre, índice_de_argumento) del
    paréntesis más interno que siga abierto, o None si el cursor no está
    dentro de una llamada.
    """
    pila: "list[list]" = []   # [nombre, n_comas]
    en_cadena = False
    i = 0
    tope = min(columna, len(linea))

    while i < tope:
        ch = linea[i]
        if ch == '"':
            en_cadena = not en_cadena
            i += 1
            continue
        if en_cadena:
            i += 1
            continue
        if ch == "'":
            return None            # a partir de acá es comentario
        if ch == "(":
            j = i - 1
            while j >= 0 and linea[j] in " \t":
                j -= 1
            fin = j + 1
            while j >= 0 and (linea[j].isalnum() or linea[j] == "_"):
                j -= 1
            pila.append([linea[j + 1 : fin], 0])
        elif ch == ")":
            if pila:
                pila.pop()
        elif ch == "," and pila:
            pila[-1][1] += 1
        i += 1

    if not pila or not pila[-1][0]:
        return None
    return pila[-1][0], pila[-1][1]
