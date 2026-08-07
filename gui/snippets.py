"""Plantillas de programa listas para insertar.

Ojo con la sangría: en este dialecto las asignaciones sueltas y las
declaraciones Public/Dim/Units tienen que ir pegadas al margen izquierdo,
porque el parser del equipo lee el nombre desde la columna 0. Las
asignaciones que van dentro de un «If … Then» son la excepción: su destino
se lee después del Then y sí toleran sangría. Todas las plantillas de acá
respetan esa regla.
"""

PROGRAMA_NUEVO = """'==============================================================
' <descripción del equipo>
' Arduino Opta / firmware OptaPakBus
'==============================================================

StationName=MiEstacion

'-- Config de red: cada .CR1 lleva la de su propio equipo --------
ServerHost=loggerip.ingproy.com
ServerPort=6786                  ' sin esta linea el equipo va al puerto de provision
PakBusAddress=1                  ' debe coincidir con el node_id del servidor

'-- Calibracion (solo literales numericos, sin expresiones) ------
Const Mult_1 = 1.0
Const Off_1  = 0.0

'-- Variables (siempre en la columna 0, sin sangria) -------------
Public Sensor_mA
Units Sensor_mA = mA
Public Valor
Public BattV

'==============================================================
'  TABLA DE DATOS — sin al menos una, el equipo NO ejecuta nada
'==============================================================
DataTable(Registro, True, 10080)
    DataInterval(0, 1, Min, 0)
    Sample(1, Valor, FP2)
    Sample(1, BattV, FP2)
EndTable

'==============================================================
'  PROGRAMA PRINCIPAL
'==============================================================
BeginProg
    Scan(10, Sec, 0, 0)

        AIChannel(Sensor_mA, 1)      ' canal I1 (A0)

' Las asignaciones sueltas van sin sangria:
Valor = Sensor_mA * Mult_1 + Off_1

    NextScan
EndProg
"""

SENSOR_4_20 = """'-- Sensor 4-20mA en el canal I<N> --------------------------------
' Escala: valor = mA * Mult + Off
'   Mult = (Max_ingenieria - Min_ingenieria) / 16
'   Off  = Min_ingenieria - 4 * Mult
Const Sensor_Mult = 1.0
Const Sensor_Off  = 0.0
Public Sensor_mA
Units Sensor_mA = mA
Public Sensor_val
"""

SENSOR_VOLTAJE = """'-- Entrada de voltaje 0-10V --------------------------------------
Public Volt_val
' Los dos ultimos argumentos son Mult y Offset, y solo se leen si hay
' 6 o mas argumentos. La escala se aplica sobre milivolts.
VoltSE(Volt_val, 1, mV5000, 1, 0, 0, 0.001, 0.0)
"""

RELE_HISTERESIS = """'-- Control de rele con banda muerta ------------------------------
Const Nivel_Bajo = 1.0
Const Nivel_Alto = 4.0
Public Nivel
Public DO1
PortSet(DO1, 0, 1)

If (Nivel < Nivel_Bajo) Then
    DO1 = 1
ElseIf (Nivel > Nivel_Alto) Then
    DO1 = 0
EndIf
"""

PLUVIOMETRO = """'-- Pluviometro de cangilones -------------------------------------
' Montaje: I2 excita el contacto con 3.3V y el borne de conteo (P1)
' lleva un pull-down de 10k al NEGATIVO. En reposo el nodo esta en 0V
' y cada volcada lo sube, asi que el flanco es de subida.
' El conteo se reinicia en cada scan: el valor son los pulsos del
' ultimo scan, no un acumulado. En la tabla va con Totalize.
' El Offset va en 0: se suma en CADA scan y rompe el Totalize.
Public Lluvia_mm
Units Lluvia_mm = mm
ExciteCh(2)
PulseCount(Lluvia_mm, 1, P1, 2, 0, 0.2, 0.0)
PulseEdge(Lluvia_mm, Rising)
"""

TABLA_DATOS = """DataTable(NombreTabla, True, 10080)
    DataInterval(0, 1, Min, 0)
    Average(1, Variable1, FP2)
    Maximum(1, Variable2, FP2)
    Minimum(1, Variable2, FP2)
    Sample(1, Variable3, FP2)
EndTable
"""

BLOQUE_IF = """If (Variable > Umbral) Then
    Salida = 1
ElseIf (Variable < Umbral) Then
    Salida = 0
Else
    Salida = 0
EndIf
"""

IF_UNA_LINEA = """' Un If con la asignacion en la misma linea NO lleva EndIf.
If (Variable > Umbral) Then Salida = 1
"""

BATERIA = """'-- Voltaje de alimentacion ---------------------------------------
' Battery(Var, N) indica en que borne esta cableado el divisor.
' Sin el segundo argumento usa el 8, que era el canal fijo hasta el
' firmware 1.6.8. El canal queda reservado.
Public BattV
Battery(BattV, 8)
"""

PLANTILLAS = [
    ("Programa nuevo completo", PROGRAMA_NUEVO),
    (None, None),
    ("Sensor 4-20mA", SENSOR_4_20),
    ("Entrada de voltaje", SENSOR_VOLTAJE),
    ("Voltaje de alimentación (BattV)", BATERIA),
    ("Pluviómetro (PulseCount)", PLUVIOMETRO),
    (None, None),
    ("Control de relé con histéresis", RELE_HISTERESIS),
    ("Bloque If / ElseIf / Else", BLOQUE_IF),
    ("If de una línea", IF_UNA_LINEA),
    (None, None),
    ("Tabla de datos", TABLA_DATOS),
]
