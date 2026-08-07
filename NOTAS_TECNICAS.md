# Notas técnicas

Detalle de cómo funciona el validador y qué cosas del firmware justifica
cada regla. Para el uso normal alcanza con el [README](README.md).

El motor de análisis es un port en Python de `parse_crbasic()`,
`cr_compile_expr()` y la asignación de canales de `OptaPakBus.ino`, con
sus mismos truncados y sus mismas conversiones parciales. No es una
aproximación al comportamiento del equipo: es el mismo algoritmo.

> **Calcado sobre el firmware 1.6.12.** El comportamiento cambió bastante
> entre la 1.6.7 y la 1.6.12 —límites, calibración del shunt,
> instrucciones nuevas y varios bugs silenciosos corregidos—, así que un
> IDE desfasado avisa de cosas que ya no pasan y calla las que sí. La
> versión de referencia está en `optabasic/limits.py` como
> `FIRMWARE_VERSION`.

## Trampas que detecta y el firmware no reporta

| Qué pasa | Por qué |
|---|---|
| **Sin `DataTable` el programa no se ejecuta** | `crParsed = (crTableCount > 0)`; en `loop()` el equipo cae al esquema fijo AI1-AI4/DI1-DI4/DO1-DO4/BattV e ignora todo el `.CR1` |
| **`Units=mA` + asignación = variable sin canal** | `noAutoPin` solo se revierte para `hasVoltInstr` |
| **`Msec` se interpreta como segundos** | `cr_to_sec()` solo conoce MIN/HOU/DAY; `Scan(500, Msec)` son 500 s |
| **`att` en el nombre + `Units=mA` pierde el canal de alimentación** | la rama de batería excluye `is4_20mA`; hay que declararlo con `Battery(Var, N)` |
| **`att` cuando el borne 8 ya está tomado** | la variable se queda sin canal en vez de pisarlo, y vale 0 |
| **`VoltDiff`/`VoltSE` con menos de 6 argumentos ignora Mult/Offset** | solo los lee con `nArgs >= 6` |
| **Tabla sin `DataInterval` nunca archiva** | `if (tbl->intervalSec > 0)` |
| **`PortSet` sin `N` y con un nombre que no es `DOn`** | queda en el relé 1 por descarte: `isRelay` se marca antes del chequeo del nombre |
| **`PulseCount` no cuenta más de 20 pulsos/s** | antirrebote de 50 ms fijo; un caudalímetro de turbina se cuenta muy por debajo de lo real |
| **El `Offset` de `PulseCount` se suma en cada scan** | `value = cnt * mult + offset`; con `Totalize` inventa un acumulado |
| **`ExciteCh` sobre el borne de conteo** | la salida gana y el contador no ve ningún flanco |
| **El divisor del contador se calcula sin la entrada en paralelo** | los ~7,8 kΩ de la entrada bajan la tensión del borne; un 10k/10k desde 12 V da 3,66 V y no 6, y así no dispara nunca |
| **El shunt de 4-20 mA está fijo en 260 Ω** | `SHUNT_OHM`; con otro lazo la variable en mA no muestra los miliamperes reales |
| **`Public`/`Dim`/`Units` con sangría** | offsets fijos desde la columna 0. `Const` sí tolera sangría |
| **Truncados silenciosos** | línea a 127 caracteres, programa a 16384 bytes, argumento a 31, nombre de variable a 23 |

### Corregidas en el firmware — el IDE ya no las reporta

Se listan porque un equipo que no se haya actualizado las sigue teniendo:

- **Una asignación suelta indentada se descartaba** (hasta 1.6.7). El
  destino se leía desde la columna 0 y `cr_find_var()` compara exacto, así
  que `"        Altura_cm"` no coincidía con nada. Las que van dentro de
  un `If … Then` no estaban afectadas, por eso pasó inadvertido.
- **Un canal fijado a mano se podía repartir dos veces** (hasta 1.6.8).
  `used[]` arrancaba vacío y el reparto automático pisaba los canales de
  `AIChannel`, `VoltSE` y `PulseCount`.
- **Una expresión que agotaba los 20 tokens se truncaba en silencio**
  (hasta 1.6.7) si el último token era un `)` que vaciaba la pila.
- **Un `.CR1` más grande que el buffer se truncaba sin dejar rastro**
  (hasta 1.6.10).
- **`Totalize` y `Average` venían sesgados hacia arriba** (hasta 1.6.8):
  el acumulador se reiniciaba sembrado con el scan recién archivado, que
  quedaba contado dos veces. Los históricos viejos lo arrastran.

### Los números de línea del `.HLOG` vienen corridos

El bucle de extracción de líneas del firmware consume todos los saltos
consecutivos de una vez, así que **las líneas en blanco no incrementan el
contador**. El `L<n>` del `.HLOG` no coincide con el archivo en cuanto el
programa tiene una línea vacía, y todos las tienen. El IDE muestra los dos
números: el del archivo para el editor, el del firmware para cotejar
contra el log del equipo.

## La matemática del asistente de sensores

### Sensores 4-20 mA

Dos cosas que a mano se pasan por alto.

**La caída de tensión no es sobre el resistor** sino sobre el resistor en
paralelo con la entrada del Opta, que presenta unos 7,8 kΩ a masa. Un R4
de 269 Ω se comporta como 260 Ω. Calcular con el valor del tester da un
error de span del 3,5%, que sobre un sensor de 0-5 m son más de 15 cm en
fondo de escala. Es exactamente el error que tenía el firmware hasta que
se calibró en terreno.

**El firmware divide siempre por los 260 Ω que tiene fijos por código**
(`SHUNT_OHM`). Si el lazo real da otro valor efectivo, la variable en mA
no muestra los miliamperes reales. El valor de ingeniería se corrige
metiendo el factor en `Mult`, pero los umbrales de falla no: quien copie
el clásico `If (Sensor_mA < 3.5)` está comparando contra un número que ya
no significa 3,5 mA. El asistente genera los umbrales corregidos.

También avisa de lo que no se arregla con matemática: a 20 mA sobre 600 Ω
son 12 V y la entrada llega a 10,70 V, así que la lectura se corta arriba
y el sensor nunca marca el máximo.

Alternativa exacta: leer con `VoltSE` en vez de `Units = mA`. Ahí el shunt
efectivo entra en el cálculo tal cual y no importa el valor que el
firmware traiga fijo.

### Contadores de pulsos

El antirrebote de 50 ms (`PULSE_DEBOUNCE_US`) pone un techo de **20 pulsos
por segundo**. Un caudalímetro de 450 pulsos/litro a 30 l/min necesita
225 Hz y no sirve: con ese medidor el equipo solo llega a 2,67 l/min y
todo lo demás se cuenta de menos sin ningún aviso. Para los equipos de
terreno sobra —un pluviómetro de cangilones va a 0,8 Hz y un flujómetro
Bermad DN125 a caudal máximo, a 0,5 Hz.

El contacto se alimenta desde la fuente del gabinete:

```
+12 V ── 2,2 kΩ ── [contacto] ── I4 ── 10 kΩ ── NEGATIVO
```

Acá aparece la misma trampa que con el shunt: **la entrada queda en
paralelo con la resistencia de abajo**. Un divisor de 10 kΩ/10 kΩ desde
12 V parece dar 6 V y da 3,66. Y como el borne tiene que llegar a unos
7,4 V para que la interrupción dispare —10,70 V a fondo de escala contra
los 3,3 V del micro—, con ese divisor no cuenta ni un solo pulso.

El asistente calcula la tensión real del borne, avisa si no llega al
umbral o si se pasa de los 10,70 V que admite la entrada, y da algo que a
mano no se mira: **hasta cuánto puede caer la fuente antes de que deje de
contar**. Con 2,2 kΩ el corte está en 11,3 V, que en una estación a
batería se alcanza; con 1,5 kΩ baja a 10,1 V.

El umbral de 7,4 V es deducido, no una hoja de datos del Opta. Conviene
confirmarlo con multímetro sobre el circuito armado.

`ExciteCh` queda como opción para cuando no hay fuente en el gabinete,
con una advertencia: entrega sus 3,3 V a través de la red divisora de la
entrada, con impedancia de fuente alta, y difícilmente cruce el umbral.

## Envío al equipo

El Opta no acepta conexiones entrantes: es él quien disca al servidor. Por
eso el IDE no habla PakBus directamente, sino que usa la API del backend
`loggernet_AlternoCampbell`:

```
POST /api/auth/login                          → token
GET  /api/loggers                             → lista de equipos
POST /api/loggers/{id}/files/upload?run_now=  → FileDownload + FileControl
```

## Estructura

```
run.bat          lanzador unico: IDE, linter, pruebas e instalacion
main.py          punto de entrada del IDE
optabasic/       motor de análisis, sin dependencias de interfaz
  limits.py      los #define del firmware, en un solo lugar
  cutil.py       atof/atoi/strncpy con la semántica de C
  lexer.py       cr_strip_comment, cr_keyword, cr_paren, cr_args
  expr.py        cr_compile_expr (Shunting-Yard) y el conteo de tokens RPN
  parser.py      parse_crbasic() completo
  lint.py        las reglas propias del IDE
  model.py       Program, Var, Const, Table, Field, Stmt
  reference.py   catálogo de instrucciones en castellano llano
  sensors.py     escalas de 4-20 mA y de pulsos
  encoding.py    cp1252 / UTF-8 y fin de línea, sin corromper acentos
gui/             interfaz PyQt5
cli.py           linter de consola
tests/           118 pruebas ancladas al firmware
```

Los programas `.CR1` no se versionan: llevan la configuración de red real
de cada equipo. Para las pruebas que contrastan contra programas de
terreno, copiar los del repo del firmware a una carpeta `ejemplos/`; si no
están, esas pruebas se saltean solas.

## Pruebas

```bat
run.bat test
```

Cada prueba cita la línea de `OptaPakBus.ino` que fija el comportamiento.
Si el firmware cambia, estas son las que tienen que fallar primero.

## Nota sobre duplicación

El frontend web de `loggernet_AlternoCampbell` tiene su propio linter en
JavaScript (`frontend/src/optaCrbasicLint.js`) con el mismo propósito. Son
dos implementaciones independientes del mismo parser: si el firmware
cambia, hay que actualizar las dos. Diferencias conocidas del `.js` frente
al firmware, además de las trampas de la tabla de arriba:

- Trata la ausencia de `DataTable` como un aviso menor; es un error fatal.
- Supone que una palabra clave desconocida dentro de un `DataTable` agrega
  el campo como `Sample`. El firmware exige una de las cinco palabras
  reconocidas, así que no agrega nada.
- Avisa que un `PortSet` sobre una variable que no se llama `DOn` no mapea
  ningún relé. Sí lo hace: `isRelay` se marca antes del chequeo del nombre
  y `relayIdx` queda en 0, o sea DO1.
