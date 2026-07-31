# Manual del subconjunto CRBasic — OptaPakBus

Este manual documenta **exactamente** el subconjunto del lenguaje CRBasic que
interpreta el firmware, tal como está implementado hoy en
[`parse_crbasic()`](OptaPakBus.ino:2270) y [`crbasic_execute_scan()`](OptaPakBus.ino:2735)
dentro de [OptaPakBus.ino](OptaPakBus.ino). No es un intérprete CRBasic
completo: es un parser línea-por-línea, escrito a mano, pensado para
programas cortos de monitoreo/control con sensores 4-20mA y voltaje.

> **Nota:** la tabla "Funciones CRBasic soportadas" del [README.md](README.md)
> quedó desactualizada frente al código actual (por ejemplo, ya no es cierto
> que "múltiples operadores" o "`If`/`EndIf` multilínea" no se reconozcan).
> Este documento refleja el estado real del parser a partir del commit
> `10e793c` en adelante.

---

## 1. Sintaxis general

- **Case-insensitive**: palabras clave, nombres de variables y constantes no
  distinguen mayúsculas/minúsculas (`Public`, `PUBLIC`, `public` son iguales).
- **Comentarios**: todo lo que sigue a un apóstrofo `'` fuera de comillas se
  descarta hasta el fin de línea.
- **Una instrucción por línea.** No existe continuación de línea (`_` al
  final) ni separador `:` para varias instrucciones en la misma línea.
- **Límite de línea: 127 caracteres.** Lo que exceda se trunca silenciosamente.
- **Argumentos de instrucciones** (dentro de paréntesis): máximo **12
  argumentos**, cada uno de hasta **31 caracteres**. Los paréntesis pueden
  anidarse dentro de un argumento (p. ej. una expresión), pero un `)` sin su
  `(` correspondiente corta el argumento ahí mismo.
- **Programa completo**: se almacena en un buffer de **8192 bytes**
  (`storedProg[8192]`); un `.CR1` más grande no se acepta completo.
- **Indentación**: es puramente cosmética para casi todas las instrucciones
  (el parser busca la palabra clave y el primer `(`/`=` sin importar los
  espacios previos) — **excepto** `Public`/`Dim` y `Units`, que deben
  escribirse **sin sangría** (columna 0). Si se indentan, el parser puede
  registrar una variable espuria o interpretar mal el nombre/unidad. En la
  práctica: declara variables, `Const` y `Units` fuera del bloque `Scan`, sin
  indentar.

### Diagnóstico de errores de parseo (desde v1.6.3)

Cada vez que una línea del `.CR1` no se puede interpretar (palabra clave
desconocida, argumentos inválidos, variable no declarada, límite de
variables/constantes/tablas/campos/instrucciones excedido, expresión
inválida, condición mal formada, etc.), el parser deja una línea en el log
persistente del equipo (`.HLOG`, ver [README.md](README.md)) con este
formato:

```
[YYYY-MM-DD HH:MM:SS UTC] [CRBasic] L<línea> ignorada (<motivo>): <fragmento de la línea>
```

- `<línea>` es el número de línea del `.CR1` (1-based) — abrí el archivo en
  un editor de texto y andá directo ahí.
- `<motivo>` es una descripción corta y abreviada (el mensaje completo
  puede recortarse si la línea es muy larga — el log tiene 120 caracteres
  por renglón, compartidos con la fecha).
- Esto corre **solo durante el parseo** (arranque o carga de un `.CR1`
  nuevo) — nunca durante el `Scan()`, así que no afecta en nada el tiempo de
  ejecución del programa, sin importar cuántos errores tenga.
- Las instrucciones de estructura de CR1000 real que este firmware ignora a
  propósito (`BeginProg`/`EndProg`/`NextScan`/`CallTable`/`Battery(...)`,
  ver §2) **no** generan esta advertencia — son un no-op esperado, no un
  error.

---

## 2. Estructura de un programa `.CR1`

El parser **no entiende de bloques** `BeginProg`/`Scan(...)`/`NextScan`/
`EndProg`, ni `CallTable`: son palabras clave que **no coinciden con ningún
caso reconocido** y por lo tanto se ignoran silenciosamente (no producen
error, simplemente no hacen nada). Se recomienda **seguir escribiéndolas**
igual que en un programa CR1000 real, por legibilidad y portabilidad, pero
funcionalmente:

- `Scan(N, Unit, ...)` **si se reconoce** — es la única línea de ese bloque
  con efecto real: fija el intervalo de muestreo (ver §11).
- `BeginProg`, `EndProg`, `NextScan` → no-op total.
- `CallTable NombreTabla` → no-op. El archivado de cada tabla es
  **automático**, gobernado por su propio `DataInterval` (ver §15) — **no
  hace falta** invocar `CallTable` para que se grabe un registro.
- `Battery(Var)` → no-op (no reconocida; ver §10 para el equivalente real).

Todas las demás instrucciones (`Public`, `Dim`, `Const`, `Units`,
`DataTable`/`EndTable`, asignaciones, `If`) se leen **en el orden del
archivo**, sin importar si están "dentro" o "fuera" del bloque `Scan` en el
texto.

---

## 3. Directivas de identidad y red (extensiones propias del Opta)

No forman parte del estándar CRBasic de Campbell; son directivas que este
firmware añadió para configurar cada equipo desde su propio `.CR1` (un mismo
firmware sirve para varios equipos):

| Directiva | Efecto |
|---|---|
| `StationName=Nombre` | Nombre de estación reportado en `Hello`/`GetSettings`. Máx. 23 caracteres. |
| `ServerHost=host_o_ip` | Host/IP del servidor LoggerNet destino. Máx. 63 caracteres. |
| `ServerPort=N` (1-65535) | Puerto TCP operativo. **Su sola presencia marca al equipo como "provisionado"**; sin esta línea, el equipo se conecta al puerto de provisión (4789) en vez del operativo. |
| `PakBusAddress=N` (1-4094) | Dirección PakBus de este logger (debe coincidir con el `node_id` configurado en el servidor). |

Se aceptan con o sin espacio antes del `=` (`ServerPort=6787` o
`ServerPort = 6787`). Cambiar cualquiera de estos valores respecto al que
tenía el equipo dispara una reevaluación de la conexión de red en el
siguiente ciclo de `loop()`.

---

## 4. Declaración de variables — `Public` / `Dim`

```
Public VarA, VarB, VarC
Dim Interno1, Interno2 As Float
```

- `Public` y `Dim` son **funcionalmente idénticos** en este firmware: ambas
  crean una variable float de 64 posibles (`CR_MAX_VARS=64`) y **ambas
  terminan expuestas** en la tabla `Public` que se envía por PakBus. A
  diferencia de un CR1000 real, **no existe variable "privada"** — no hay
  ninguna distinción interna entre `Public` y `Dim`.
- Se pueden declarar varias variables separadas por coma o espacio en la
  misma línea.
- Sufijos de tipo reconocidos y **descartados** (no tienen efecto — todo es
  internamente `float`): `As`, `Float`, `Long`, `String`, `Boolean`. Cualquier
  otro nombre de tipo (`Integer`, `Double`, etc.) **no se reconoce** como
  palabra clave de tipo y terminaría registrado como si fuera el nombre de
  otra variable.
- **Arreglos**: `Public Temp(4)` se acepta sintácticamente, pero el `(4)` se
  descarta — `Temp` queda como una variable escalar única. No hay indexación
  de arreglos en ninguna parte del parser (ni en declaraciones ni en
  expresiones).
- Nombre máximo: 23 caracteres.

---

## 5. Constantes — `Const`

```
Const Dist_Mult = 29.375
Const Dist_Off  = -87.5
```

- Solo acepta un **literal numérico** (entero, decimal, negativo o notación
  científica) a la derecha del `=`. **No admite expresiones** (`Const B = A*2`
  no funciona — el "valor" se parsea con `atof()` sobre el texto tras `=`,
  así que solo tomaría lo que `atof` logre interpretar del inicio).
- Usable luego en cualquier expresión (`Var = Var2 * MiConst`) y en
  condiciones (`If (Var > MiConst) Then ...`).
- Máximo **16 constantes** (`CR_MAX_CONSTS`). Nombre máximo: 19 caracteres.

---

## 6. Unidades — `Units`

```
Units Dist_mA = mA
```

- Asigna el string de unidad a una variable ya declarada (se usa tal cual en
  el `.TDF` que ve la plataforma).
- **Efecto especial**: si la unidad es literalmente `mA` (case-insensitive),
  la variable queda marcada como canal de **4-20mA** (`is4_20mA=true`) y
  entra en la asignación automática de canales analógicos (§7), **sin
  necesitar** una instrucción `VoltDiff`/`VoltSE` explícita. Esto es una
  extensión propia del Opta — en un CR1000 real, declarar `Units=mA` no basta
  para leer hardware.
- Debe escribirse sin indentación (ver nota de §1).

---

## 7. Entradas analógicas

### `VoltDiff` / `VoltSE`

```
VoltDiff(Dest, Reps, Range, Chan, RevDiff, SettlingTime, Integ, Mult, Offset)
VoltSE  (Dest, Reps, Range, Chan, SettlingTime, Integ, Mult, Offset)
```

Se acepta la sintaxis completa de un CR1000 real, pero **solo se usan**
algunos de los argumentos:

- `Dest` (arg 0): variable destino (debe existir).
- `Chan` (arg 3): si es un número entre 1 y 8, fija explícitamente el canal
  analógico A0-A7 (`1`→A0 … `8`→A7). Si no es un número válido en ese rango,
  el canal se asigna automáticamente (ver más abajo).
- **Los dos últimos argumentos siempre son `Mult`/`Offset`** (se leen como
  `args[nArgs-2]` y `args[nArgs-1]`), sin importar cuántos argumentos
  intermedios (`RevDiff`, `SettlingTime`, `Integ`, `Range`, etc.) se hayan
  incluido — esos se ignoran por completo.
- `Reps` siempre debe ser `1`: no hay soporte de arreglos/multiplexado.
- El escalado se aplica sobre el voltaje leído expresado en **milivolts
  equivalentes**: `valor = volts_leidos × 1000 × Mult + Offset`. Esto permite
  reusar tal cual las constantes `Mult`/`Offset` calibradas para un rango
  `mV...` de un programa CR1000 original.

### `AIChannel` (extensión propia, no estándar)

```
AIChannel(Dest, N)
```

Asigna explícitamente la variable `Dest` al canal analógico `N` (1-8 →
A0-A7), sin depender del orden de declaración ni de `VoltDiff`/`VoltSE`.
Funciona tanto para variables `mA` como de voltaje.

### Asignación automática de canales A0-A7

Al terminar de parsear el programa:

1. Cualquier variable cuyo nombre contenga la subcadena `att` (mayúscula o
   minúscula, p. ej. `BattV`, `Batt_Volt`) y que no tenga ya canal asignado
   se reserva el canal **A7** como voltaje de alimentación (factor divisor
   `3.351`), con prioridad sobre el resto.
2. El resto de variables que efectivamente leen hardware (tienen
   `VoltDiff`/`VoltSE` o `Units=mA`) y no tienen canal ya asignado reciben,
   en **orden de declaración**, el siguiente canal A0-A7 libre.
3. Variables declaradas pero sin ninguna instrucción de lectura (sensores
   "comentados" o no usados) **no consumen canal**: quedan con valor `0`
   permanente.

---

## 8. Salidas de relé — `PortSet`

```
PortSet(Dest, val)          ' relé inferido del nombre DOx
PortSet(Dest, val, N)       ' relé N (1-4) explícito
```

- `Dest` (arg 0): variable que representa el relé (debe existir).
- `val` (arg 1): **se ignora por completo** — no fija ni el estado inicial ni
  ninguna acción; el estado real del relé sale del valor de `Dest` en cada
  scan (`relayState = Dest > 0.5`).
- Si se pasa un tercer argumento `N` (1-4), fuerza ese relé físico
  explícitamente. Si no, y el nombre de `Dest` empieza con `DO` seguido de un
  dígito (`DO1`.. `DO4`), el relé se infiere de ese dígito.
- El programa puede escribir la variable de relé con lógica propia
  (`If (Moviendo=1) Then DO1=1`) y eso **sí** mueve el GPIO real en el mismo
  scan — no hace falta pasar por `SetValues` externo.

---

## 9. Contador de pulsos — `PulseCount`

```
PulseCount(Dest, Reps, Channel, PConfig, POption, Mult, Offset)
```

- `Dest` (arg 0): variable destino.
- `Channel` (arg 2): `P1`-`P8` o `1`-`8` → canal A0-A7 configurado como
  entrada con interrupción por **flanco de bajada** (`FALLING`), con
  antirrebote de **50 ms** por software — pensado para contacto seco (p. ej.
  pluviómetro de cangilones). Requiere **pull-up externo** de ~10kΩ a 3.3V
  (el pull-up interno del STM32 no llega al terminal por el divisor 0-10V
  del hardware del Opta).
- `Mult`/`Offset` (args 5 y 6): `valor = pulsos_del_scan × Mult + Offset`.
  El conteo se resetea a 0 en cada scan (es decir, `valor` es "pulsos desde
  el último scan", no un acumulado total).
- `Reps` y `PConfig`/`POption` (args 1, 3, 4) se ignoran — el tipo de flanco
  y demás opciones son siempre las fijas arriba descritas.

---

## 10. Instrucciones reconocidas pero sin ejecución real

```
BrHalf(...) | RealTime(...) | PanelTemp(...) | SW12(...)
```

Se identifica la instrucción y, si trae una variable destino como primer
argumento, esa variable se marca "sin canal propio" (no roba un A0-A7) — pero
**no se simula ninguna lectura**: la variable queda en `0` salvo que otra
parte del programa la asigne. `Battery(Var)` ni siquiera se reconoce como
palabra clave (usar el patrón `att` en el nombre + `VoltDiff`/`Units=mA`, o
directamente una variable llamada con `att`, para obtener `BattV` real — ver
§7).

---

## 11. Intervalo de muestreo — `Scan`

```
Scan(2, Sec, 0, 0)
```

- Solo se usan los dos primeros argumentos: valor numérico + unidad
  (`Sec`/`Min`/`Hour`/`Day`, primeras 3 letras case-insensitive). El resto
  (`ScanBuffers`, `MaxScanRate` en un CR1000 real) se ignora.
- Resultado mínimo forzado: **1000 ms** (no se puede escanear más rápido que
  1 vez por segundo).
- Si no hay ningún `Scan(...)` en el programa, el intervalo por defecto es
  **60 segundos**.

---

## 12. Expresiones aritméticas

El compilador de expresiones (`cr_compile_expr`, Shunting-Yard → RPN) soporta:

- Operadores binarios `+ - * /` con precedencia estándar (`*`/`/` antes que
  `+`/`-`).
- Paréntesis anidados.
- Negación unaria (`-X`, `-(A+B)`).
- Funciones de un solo argumento: **`Abs(...)`, `Int(...)`, `Sqr(...)`**
  (ninguna otra función matemática está implementada: no hay `Sin`, `Cos`,
  `Ln`, `Exp`, `Mod`, etc.).
- Literales numéricos (enteros, decimales, notación científica vía
  `strtof`).
- Referencias a cualquier variable (`Public`/`Dim`) o constante (`Const`) ya
  declarada, por nombre.
- División por cero devuelve `0` en vez de `inf`/`NaN` (protección explícita).
- Máximo **20 tokens** por expresión compilada (`CR_MAX_EXPR_TOKENS`) y pila
  de operadores de hasta 20 niveles — una expresión demasiado larga o con
  demasiados paréntesis anidados simplemente **no compila** y la asignación
  se descarta.
- Cualquier expresión que el compilador no reconozca (dos operandos
  seguidos, identificador no declarado, paréntesis desbalanceados, etc.)
  hace que **toda la instrucción se descarte**. Desde v1.6.3 esto queda
  registrado en el `.HLOG` como `"expresion invalida"` con el número de
  línea (ver "Diagnóstico de errores de parseo" en §1) — antes no había
  ningún rastro más allá del log serial en el momento.

---

## 13. Asignaciones

```
Altura_cm = Dist_Cerrada_cm - (Dist_mA * Dist_Mult + Dist_Off)
```

- `Destino = expresión`, donde `Destino` debe ser una variable ya declarada
  (`Public`/`Dim`). Si no existe, la línea se ignora (registrado en el
  `.HLOG` como `"asignacion a variable no declarada"`, ver §1).
- Toda variable que aparezca como destino de una asignación queda marcada
  `noAutoPin` (no participa de la asignación automática de canal, salvo que
  también tenga una instrucción `VoltDiff`/`VoltSE` real, en cuyo caso esa
  gana).
- Máximo **32 instrucciones totales** en todo el programa
  (`CR_MAX_STMTS=32`), contando asignaciones **y** cada `If`/`ElseIf`/`Else`/
  `EndIf` como una instrucción cada uno.

---

## 14. Condicionales — `If`

### Forma de una línea (no necesita `EndIf`)

```
If (Dist_mA < SensorMin_mA) Then SensorFalla = 1
If (Moviendo = 0) AND (MoverCm <> 0) Then ObjetivoAltura_cm = Altura_cm + MoverCm
```

- Sintaxis de la condición: `[(]Var <op> Var|Const[)]`, con
  `<op>` ∈ `{ < , > , <= , >= , = , <> }`.
- **El lado izquierdo de la condición debe ser una variable** (no una
  constante ni un literal); el lado derecho puede ser variable o constante/
  literal.
- Se pueden combinar **hasta 2 condiciones** con `AND` u `OR` (no ambos a la
  vez, no más de dos condiciones, no paréntesis lógicos anidados).
- Tras `Then` va **una sola asignación** (`Var = expr`). Si hay más de una
  instrucción tras `Then`, o ninguna, la línea se reinterpreta como
  apertura de bloque (ver abajo) o se descarta.
- **Regla importante**: si la línea `If ... Then Var=expr` incluye la
  asignación en la misma línea, **no debe cerrarse con `EndIf`** — es la
  forma de una sola línea. Si se le agrega un `EndIf` después, ese `EndIf`
  queda suelto (no revierte nada) y las líneas intermedias **no** quedan
  condicionadas por el `If`. Esta regla es la misma que en un CR1000 real.

### Forma de bloque multilínea (`If ... Then` / `ElseIf` / `Else` / `EndIf`)

```
If (Nivel < Niv_Bajo) Then
    Alarma = 1
    Bomba_DO1 = 1
ElseIf (Nivel > Niv_Alto) Then
    Bomba_DO1 = 0
Else
    Alarma = 0
EndIf
```

- Se abre con una línea `If (cond) Then` que **no** tiene nada más después
  de `Then` (o no tiene `=` en lo que sigue).
- `ElseIf` debe escribirse como **una sola palabra** (`ElseIf`, no
  `Else If`) — si se escribe en dos palabras, el parser la interpreta como
  un `Else` incondicional y descarta el resto de la línea.
- `EndIf` acepta tanto `EndIf` (una palabra) como `End If` (dos palabras).
- **Anidamiento máximo: 2 niveles** (`CR_IF_MAX_DEPTH=2`) — un `If` dentro de
  otro `If` funciona; un tercer nivel no se evalúa correctamente.
- Dentro de un bloque activo se pueden mezclar asignaciones simples y
  condicionales de una línea (`If...Then Var=expr`) — estas últimas
  respetan **tanto** su propia condición **como** la del bloque que las
  contiene (se combinan con AND implícito).
- Cada rama sin condición cumplida simplemente no ejecuta sus asignaciones
  ese scan (la variable conserva su valor anterior).

---

## 15. Tablas de datos — `DataTable`

```
DataTable(Registro, True, 10080)
    DataInterval(0, 1, Min, 0)
    Sample(1, Altura_cm, FP2)
    Average(1, Caudal, FP2)
    Maximum(1, Presion, FP2)
    Minimum(1, Presion, FP2)
    Totalize(1, Lluvia_mm, FP2)
EndTable
```

- `DataTable(Nombre, TrigVar, Size)`:
  - `Nombre`: nombre de la tabla (máx. 23 caracteres).
  - `TrigVar` (segundo argumento, normalmente una condición booleana en un
    CR1000 real): **se ignora por completo** — la tabla siempre está
    "activa"; el único control de cuándo se archiva un registro es el
    intervalo (`DataInterval`).
  - `Size`: cantidad de registros del ring de almacenamiento. Si es `<= 0`
    (el `-1` = "automático" de un CR1000 real), se usa una capacidad fija de
    **50000 registros** (`CR_DEFAULT_TABLE_SIZE`). Si se omite el argumento,
    el valor por defecto es `1440`.
- `DataInterval(TimeInto, Interval, Unit, Lapses)`: solo se usan `Interval` y
  `Unit` (segundo y tercer argumento) para calcular el intervalo de
  archivado en segundos. `TimeInto` y `Lapses` se ignoran.
- Procesamiento de campo — `Sample`/`Average`/`Maximum`/`Minimum`/`Totalize`,
  todas con la forma `Proc(Reps, NombreVar, Tipo)`:
  - `Reps` (arg 0) debe ser `1` (sin soporte de arreglos).
  - `NombreVar` (arg 1): nombre de una variable `Public`/`Dim`. Si hay un
    typo, el campo queda "huérfano" y se archiva siempre como `0` — el
    campo **se agrega igual** (no se bloquea, para no correr el orden de
    columnas de la tabla), pero desde v1.6.3 queda registrado en el
    `.HLOG` como `"campo: variable no declarada"` (ver §1).
  - `Tipo` (arg 2, opcional): `FP2`/`UINT2`/`INT2`/`INT4`/`LONG` se
    reconocen y se guardan como metadato, **pero no cambian el formato real
    transmitido**: todo campo se codifica siempre como `IEEE4B` (float de 4
    bytes) en el `.TDF` y en el archivo de histórico.
  - `Average`: promedio aritmético de los valores muestreados entre
    archivados.
  - `Maximum`/`Minimum`: extremo entre archivados.
  - `Totalize`: suma acumulada entre archivados.
  - `Sample` (y cualquier palabra clave no reconocida): último valor
    instantáneo al momento de archivar.
- Máximo **4 tablas** (`CR_MAX_TABLES`) de hasta **32 campos** cada una
  (`CR_MAX_FIELDS`).
- Cada tabla definida se persiste en su propio archivo en LittleFS
  (`tblN.dat`) — ver la sección "Almacenamiento de tablas" del
  [README.md](README.md) para el formato binario y la política de
  compactación.
- Además de las tablas declaradas, siempre existe automáticamente una tabla
  **`Public`** (tabla 1) con **todas** las variables `Public`/`Dim`
  declaradas, en vivo (sin historial, 1 solo registro que se sobreescribe).

---

## 16. Límites de capacidad (resumen)

| Recurso | Límite | Constante |
|---|---|---|
| Tamaño del programa `.CR1` | 8192 bytes | `storedProg[8192]` |
| Longitud de línea | 127 caracteres | — |
| Argumentos por instrucción | 12, de hasta 31 caracteres c/u | — |
| Variables (`Public`+`Dim`) | 64 | `CR_MAX_VARS` |
| Constantes (`Const`) | 16 | `CR_MAX_CONSTS` |
| Tablas (`DataTable`) | 4 | `CR_MAX_TABLES` |
| Campos por tabla | 32 | `CR_MAX_FIELDS` |
| Instrucciones (asignaciones + If/ElseIf/Else/EndIf) | 32 | `CR_MAX_STMTS` |
| Tokens por expresión compilada | 20 | `CR_MAX_EXPR_TOKENS` |
| Profundidad de anidamiento `If` | 2 niveles | `CR_IF_MAX_DEPTH` |
| Nombre de variable/tabla/campo | 23 caracteres | — |
| Nombre de constante | 19 caracteres | — |
| Nombre de estación (`StationName`) | 23 caracteres | — |
| Host (`ServerHost`) | 63 caracteres | — |

---

## 17. Fuera de alcance (no implementado)

- **SDI-12** (`SDI12Recorder`, etc.).
- **Puerto serie/COM** (`SerialOpen`, `SerialIn`, `SerialOut`, RS-232/RS-485).
- Funciones matemáticas más allá de `Abs`/`Int`/`Sqr` (sin `Sin`, `Cos`,
  `Ln`, `Exp`, `Mod`, `ATN`, etc.).
- Arreglos indexados en expresiones o declaraciones (`Temp(1)`, `rTime(4)`).
- Funciones de tiempo (`IfTime`, `TimeIsBetween`, `Status.*`, etc.).
- Cadenas de texto y operaciones sobre `String` (el tipo se acepta como
  sufijo pero toda variable es internamente `float`).
- `Const` con expresiones (`Const B = A * 2`).
- Más de 2 condiciones combinadas con `AND`/`OR` en un mismo `If`.
- Más de 2 niveles de anidamiento de `If`.
- Subrutinas (`Sub`/`CallTable` con parámetros, `GoSub`), bucles
  (`For`/`Next`, `Do`/`Loop`).
- Alarmas/`Alias`, `SlowSequence`, multiplexores `AM16/32`, etc.

---

## 18. Ejemplo completo comentado

Ver [`programa_compuerta.CR1`](programa_compuerta.CR1) — control de una
compuerta con sensor ultrasónico 4-20mA, que usa: `StationName`,
`ServerHost`/`ServerPort`/`PakBusAddress`, `Const`, `Public`/`Dim`, `Units`,
`AIChannel`, `PortSet` con relé explícito, expresiones aritméticas
completas, bloques `If`/`AND` de una línea encadenados, y una `DataTable`
con `Sample` a 1 registro/minuto.

Un ejemplo más simple, con `VoltSE`, `Average`/`Maximum`/`Minimum` y dos
tablas con distinta frecuencia, en [`programa_opta.CR1`](programa_opta.CR1)
(nota: este archivo es más antiguo y su encabezado cita límites desactualizados
del parser — los límites reales son los de la §16 de este manual).

---

## 19. Checklist rápido al migrar/adaptar un programa CR1000 real

- [ ] Quitar/ignorar `Sub`, `For`/`Next`, `GoSub`, `SlowSequence` — no existen.
- [ ] Reemplazar cualquier función matemática que no sea `Abs`/`Int`/`Sqr`
      por su equivalente precalculado o por lógica de `If`.
- [ ] `Const` solo con literales — mover cálculos a comentarios (como hace
      `programa_compuerta.CR1`) y escribir el resultado numérico final.
- [ ] Revisar que ningún `If` combine más de 2 condiciones ni anide más de 2
      niveles — aplanar con variables intermedias si hace falta.
- [ ] `ElseIf` siempre como una sola palabra.
- [ ] No indentar `Public`/`Dim`/`Units`.
- [ ] `CallTable` puede dejarse por legibilidad, pero no es necesario — el
      archivado es automático por `DataInterval`.
- [ ] Verificar que cada nombre de variable usado en `Sample`/`Average`/etc.
      esté realmente declarado (`Public`/`Dim`) — un typo deja un campo que
      siempre vale `0` (desde v1.6.3 esto y cualquier otra línea ignorada
      quedan logueados, ver checklist siguiente).
- [ ] Después de cargar un `.CR1` nuevo (o de un release ≥v1.6.3), revisar
      el `.HLOG` del equipo buscando `"[CRBasic]"` — cualquier línea con
      `"ignorada"` apunta a un número de línea exacto del programa que no
      se pudo interpretar (ver "Diagnóstico de errores de parseo" en §1).
