# IDE OptaBasic

Editor y validador local de CRBasic-lite para Arduino Opta con firmware
OptaPakBus.

El parser del Opta es deliberadamente permisivo: descarta en silencio
cualquier línea que no entiende y sigue adelante. El único rastro queda en
el `.HLOG` del equipo, que hay que ir a buscar después de subir el
programa. Este IDE hace el camino inverso — te dice **antes de subir** qué
va a aceptar el equipo, qué va a descartar y, sobre todo, qué va a aceptar
sin hacer lo que vos esperás.

El validador no es una aproximación: es un port en Python de
`parse_crbasic()`, `cr_compile_expr()` y la asignación de canales del
firmware, con sus mismos truncados y sus mismas conversiones parciales.

> **Calcado sobre el firmware 1.6.12.** El comportamiento del equipo
> cambió bastante entre la 1.6.7 y la 1.6.12 —límites, calibración del
> shunt, instrucciones nuevas y dos bugs silenciosos corregidos—, así que
> un IDE desfasado avisa de cosas que ya no pasan y calla las que sí. La
> versión de referencia está en `optabasic/limits.py` como
> `FIRMWARE_VERSION`.

## Uso

Todo pasa por `run.bat`. Doble clic para abrir el IDE, o desde la consola:

```bat
run.bat
```

| Comando | Qué hace |
|---|---|
| `run.bat` | abre el IDE |
| `run.bat programa.CR1` | abre el IDE con ese archivo |
| `run.bat lint programa.CR1` | analiza por consola y sale |
| `run.bat test` | corre las pruebas |
| `run.bat setup` | instala las dependencias |
| `run.bat ayuda` | lista estas opciones |

También se le puede soltar un `.CR1` encima con el mouse. Si falta PyQt5,
la primera vez ofrece instalarlo.

El modo `lint` devuelve código de salida 1 cuando encuentra errores, así
que sirve tal cual para un hook de commit o para CI.

### Sin el lanzador

```bash
pip install -r requirements.txt
python main.py ejemplos/programa_compuerta.CR1
python cli.py ejemplos/programa_compuerta.CR1 --recursos --hardware --hlog
python -m pytest tests -q
```

## Asistente de sensores (Ctrl+M)

Sacar `Mult` y `Offset` a mano es donde más se equivoca quien arma la
estación, y el error no se nota: el equipo reporta números perfectamente
plausibles que están mal. El asistente los calcula, revisa que la
instalación sea eléctricamente viable y deja el código escrito.

**Sensores 4-20 mA.** Se cargan el rango del sensor y el resistor que está
puesto en el gabinete —el que se mide con el tester—. Hay dos cosas que el
asistente resuelve y que a mano se pasan por alto.

La primera: **la caída de tensión no es sobre el resistor sino sobre el
resistor en paralelo con la entrada del Opta**, que presenta unos 7,8 kΩ a
masa. Un R4 de 269 Ω se comporta como 260 Ω. Calcular con el valor del
tester da un error de span del 3,5%, que sobre un sensor de 0-5 m son más
de 15 cm en fondo de escala. Es exactamente el error que tenía el firmware
hasta que se calibró en terreno.

La segunda: **el firmware divide siempre por los 260 Ω que tiene fijos por
código** (`SHUNT_OHM`). Si el lazo real da otro valor efectivo, la
variable en mA no muestra los miliamperes reales. El valor de ingeniería
se corrige metiendo el factor en `Mult`, pero los umbrales de falla no:
quien copie el clásico `If (Sensor_mA < 3.5)` está comparando contra un
número que ya no significa 3,5 mA. El asistente genera los umbrales
corregidos.

También avisa de lo que no se puede arreglar con matemática: a 20 mA
sobre 600 Ω son 12 V y la entrada llega a 10,70 V, así que la lectura se
corta arriba y el sensor nunca marca el máximo. Y muestra la resolución
real que se consigue, en unidades de ingeniería por cuenta de ADC.

Alternativa exacta: leer con `VoltSE` en vez de `Units = mA`. Ahí el
shunt efectivo entra en el cálculo tal cual y no importa el valor que el
firmware traiga fijo. El asistente lo ofrece con una casilla.

**Contadores de pulsos.** El firmware tiene un antirrebote de 50 ms fijo
(`PULSE_DEBOUNCE_US`), pensado para el contacto de un pluviómetro. Eso
pone un techo de **20 pulsos por segundo**. Se cargan los pulsos por
unidad y el máximo que se espera medir, y el asistente dice si entra: un
caudalímetro de 450 pulsos/litro a 30 l/min necesita 225 Hz y no sirve —
con ese medidor el equipo solo puede leer hasta 2,67 l/min, todo lo demás
se cuenta de menos sin ningún aviso. Para los equipos que se usan en
terreno sobra: un pluviómetro de cangilones va a 0,8 Hz y un flujómetro
Bermad DN125 a caudal máximo, a 0,5 Hz.

**El divisor de entrada.** El contacto se alimenta desde la fuente del
gabinete:

```
+12 V ── 2,2 kΩ ── [contacto] ── I4 ── 10 kΩ ── NEGATIVO
```

Acá está el segundo error que el asistente evita: **la entrada del Opta
presenta unos 7,8 kΩ a masa y queda en paralelo con la resistencia de
abajo**. Un divisor de 10 kΩ/10 kΩ desde 12 V parece dar 6 V y en realidad
da 3,66. Y como el borne tiene que llegar a unos 7,4 V para que la
interrupción dispare —10,70 V a fondo de escala contra los 3,3 V del
micro—, con ese divisor no cuenta **ni un solo pulso**.

El asistente calcula la tensión real del borne, avisa si no llega al
umbral o si se pasa de los 10,70 V que admite la entrada, y da algo que a
mano no se mira: **hasta cuánto puede caer la fuente antes de que deje de
contar**. Con 2,2 kΩ el corte está en 11,3 V, que en una estación a
batería se alcanza; con 1,5 kΩ baja a 10,1 V.

`ExciteCh` queda como opción para cuando no hay fuente en el gabinete,
pero con una advertencia: entrega sus 3,3 V a través de la red divisora de
la entrada, con impedancia de fuente alta, y difícilmente cruce el umbral.
Conviene medir el nodo con el circuito armado.

Además fuerza `Offset = 0`, porque se suma en **cada scan**: con
`Totalize` en la tabla, cualquier otro valor acumula un total que nunca
ocurrió.

El código que genera pasa el propio linter con cero errores, y eso está
verificado en las pruebas.

## Ayuda mientras se escribe

El lenguaje lo escribe gente que instala sensores, no programadores, así
que la ayuda está pensada para no tener que acordarse de nada:

- **Al abrir un paréntesis** aparece un cartel con la firma de la
  instrucción y el argumento en el que estás, subrayado. Cambia solo a
  medida que escribís las comas.
- **Los argumentos que el equipo ignora salen marcados.** `PortSet` acepta
  un segundo argumento que no hace absolutamente nada; `VoltSE` acepta
  cuatro. Un argumento que no hace nada engaña más que uno que falta,
  porque parece que el programa está configurado y no lo está.
- **El autocompletado explica cada opción**: en vez de una lista de
  nombres pelados, cada entrada dice qué hace. Las variables del propio
  programa aparecen con su borne asignado — `Nivel_mA — 4-20mA en A0`.
- **F1 sobre cualquier palabra** abre su ficha completa.
- **Pestaña Referencia**: buscador por lo que querés hacer, no por el
  nombre de la instrucción. Anda sin tildes. Cada ficha tiene qué hace la
  instrucción, para qué sirve cada argumento, un ejemplo que se puede
  insertar de un clic, y las trampas conocidas de esa instrucción.

## Qué muestra

- **Problemas** — diagnósticos con doble clic para saltar a la línea. Los
  que vienen del firmware traen además el texto exacto que va a aparecer
  en el `.HLOG`.
- **Recursos** — cuánto queda de cada límite: bytes del programa,
  variables, constantes, tablas, campos e instrucciones.
- **Hardware** — qué variable quedó en cada canal A0-A7 y en cada relé
  DO1-DO4, después de simular la asignación automática del firmware.
- **Log del equipo** — previsión de las líneas que el Opta va a registrar
  como ignoradas.

`Equipo → Enviar al equipo` sube el `.CR1` a través de la API del backend
`loggernet_AlternoCampbell` (`POST /api/loggers/{id}/files/upload`), con
la opción de compilar y ejecutar en el acto. El Opta no acepta conexiones
entrantes —es él quien disca al servidor—, así que el envío pasa
necesariamente por ese backend.

## Trampas que detecta y el firmware no reporta

Todas verificadas contra `OptaPakBus.ino` 1.6.12.

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

Estaban en la versión anterior de este README. Se listan porque un equipo
que no se haya actualizado las sigue teniendo:

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

El bucle de extracción de líneas (2493) consume todos los saltos
consecutivos de una vez, así que **las líneas en blanco no incrementan el
contador**. El `L<n>` del `.HLOG` no coincide con el archivo en cuanto el
programa tiene una línea vacía, y todos las tienen. El IDE muestra los dos
números: el del archivo para el editor, el del firmware para cotejar
contra el log del equipo.

## Estructura

```
run.bat          lanzador unico: IDE, linter, pruebas e instalacion
main.py          punto de entrada del IDE
optabasic/       motor de análisis, sin dependencias de interfaz
  limits.py      los #define del firmware, en un solo lugar
  cutil.py       atof/atoi/strncpy con la semántica de C
  lexer.py       cr_strip_comment, cr_keyword, cr_paren, cr_args
  reference.py   catalogo de instrucciones en castellano llano
  sensors.py     escalas de 4-20 mA y de pulsos, con la matematica del firmware
  expr.py        cr_compile_expr (Shunting-Yard) y el conteo de tokens RPN
  parser.py      parse_crbasic() completo
  lint.py        las reglas propias del IDE
  model.py       Program, Var, Const, Table, Field, Stmt
  encoding.py    cp1252 / UTF-8 y fin de línea, sin corromper acentos
gui/             interfaz PyQt5
cli.py           linter de consola
tests/           110 pruebas ancladas al firmware
ejemplos/        los .CR1 reales del repo del firmware
```

## Pruebas

```bat
run.bat test
```

Cada prueba cita la línea de `OptaPakBus.ino` que fija el comportamiento.
Si el firmware cambia, estas son las que tienen que fallar primero.

## Nota sobre duplicación

El frontend web de `loggernet_AlternoCampbell` tiene su propio linter en
JavaScript (`frontend/src/optaCrbasicLint.js`) con el mismo propósito.
Son dos implementaciones independientes del mismo parser: si el firmware
cambia, hay que actualizar las dos. Diferencias conocidas del `.js` frente
al firmware, además de las trampas de la tabla de arriba:

- Trata la ausencia de `DataTable` como un aviso menor; es un error fatal.
- Supone que una palabra clave desconocida dentro de un `DataTable` agrega
  el campo como `Sample`. El firmware exige una de las cinco palabras
  reconocidas (2689), así que no agrega nada.
- Avisa que un `PortSet` sobre una variable que no se llama `DOn` no
  mapea ningún relé. Sí lo hace: `isRelay` se marca antes del chequeo del
  nombre (2768) y `relayIdx` queda en 0, o sea DO1.
