# Manual del subconjunto CRBasic — OptaPakBus

Este manual documenta **exactamente** el subconjunto del lenguaje CRBasic que
interpreta el firmware, tal como está implementado hoy en
[`parse_crbasic()`](OptaPakBus.ino:2270) y [`crbasic_execute_scan()`](OptaPakBus.ino:2735)
dentro de [OptaPakBus.ino](OptaPakBus.ino). No es un intérprete CRBasic
completo: es un parser línea-por-línea, escrito a mano, pensado para
programas cortos de monitoreo/control con sensores 4-20mA y voltaje.

> **Versión de referencia.** Calcado del firmware **v1.12.0**
> (`OptaPakBus.ino`, repo `OptaPakBus`): los límites de la §16 y la lista de
> palabras que reconoce `parse_crbasic()` salen de ahí, y las mismas reglas
> están implementadas en el motor de este IDE (`optabasic/limits.py`,
> `parser.py`, `lint.py`), con `FIRMWARE_VERSION` anotando contra qué versión
> está calcado. Este archivo es el original: el editor web del proyecto
> LoggerNet Alterno mantiene una copia sincronizada desde acá.

> **Nota:** la tabla "Funciones CRBasic soportadas" del README del firmware
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
- **Programa completo**: se almacena en un buffer de **16384 bytes**
  (`storedProg[]`, ampliado desde 8192 en v1.6.12); un `.CR1` más grande
  **se trunca**. Ese tamaño cuenta **comentarios incluidos**.

> **El truncamiento era silencioso hasta v1.6.10.** Lo que excedía el buffer
> se descartaba sin dejar rastro: la transferencia terminaba bien, el
> servidor daba el programa por cargado, y el equipo parseaba únicamente lo que
> había entrado. Con un encabezado de comentarios largo se puede perder el
> `BeginProg` **completo**, y entonces el equipo lee hardware con normalidad
> pero no ejecuta ni una línea de lógica: las variables calculadas quedan en
> `0` para siempre. Los síntomas en el log son indirectos — menos tablas de las
> escritas, `scan=60s` cuando el programa sí traía un `Scan(...)`, o una
> instrucción cortada al medio reportada como no reconocida.
>
> Desde v1.6.11 queda registrado, al recibir el archivo y otra vez al parsear:
>
> ```
> [CRBasic] .CR1 NO ENTRA: se descartan N bytes (buffer 16384)
> [CRBasic] AVISO: programa TRUNCADO a N bytes, falta el final
> ```
>
> **Verificá el tamaño en bytes antes de cargar un programa.** Y mantené la
> documentación extensa en un archivo aparte del repositorio, no dentro del
> `.CR1` — los comentarios ocupan buffer igual que el código.
- **Indentación**: es puramente cosmética para casi todas las instrucciones
  (el parser busca la palabra clave y el primer `(`/`=` sin importar los
  espacios previos) — **excepto** `Public`/`Dim` y `Units`, que deben
  escribirse **sin sangría** (columna 0). Si se indentan, el parser puede
  registrar una variable espuria o interpretar mal el nombre/unidad. En la
  práctica: declara variables, `Const` y `Units` fuera del bloque `Scan`, sin
  indentar.

> **Hasta v1.6.8 esto no era cierto para las asignaciones simples.** El nombre
> destino se recortaba de la línea **con la sangría incluida**, y como la
> búsqueda de variables compara exacto, `        Altura_cm` no coincidía con
> `Altura_cm`: la asignación se descartaba **entera y en silencio**, dejando la
> variable en su último valor (`0` si nunca se asignó). Afectaba al estilo
> normal de escritura, con las asignaciones indentadas dentro del `Scan`. Las
> asignaciones de una sola línea con `If ... Then` **no** estaban afectadas,
> porque esas se recortan del texto que sigue al `Then`, que sí venía limpio.
> De paso, la sangría se comía parte de los 23 caracteres disponibles para el
> nombre. Corregido en v1.6.9.

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
  propósito (`BeginProg`/`EndProg`/`NextScan`/`CallTable`, ver §2) **no**
  generan esta advertencia — son un no-op esperado, no un error.

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
- `Battery(Var)` **sí se ejecuta** (desde v1.6.8): lee el voltaje de
  alimentación real. Ver §7.

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
| `RouterUser=usuario` | Usuario admin del router Teltonika de **este** equipo, para las instrucciones `Modem*` (§20). Máx. 31 caracteres. Sin esta línea el firmware usa `admin`. Desde v1.6.18. |
| `RouterPass=clave` | Clave de ese usuario. Máx. 31 caracteres. **El firmware arranca con la clave vacía**: sin esta línea el login falla y las variables `Modem*` se quedan en 0. Desde v1.6.18. |
| `ModbusBaud=N` (1200-115200) | Velocidad del bus RS-485 de `ModbusRTU` (§25). Por defecto 9600. Desde v1.10.0. |
| `ModbusFormato=F` | Formato serie del bus RS-485: `8N1`, `8E1`, `8O1` u `8N2`. Por defecto `8N1`. Desde v1.10.0. |
| `ModbusTimeout=N` (50-2000) | Milisegundos que se espera la respuesta de un sensor Modbus. Por defecto 250. Desde v1.10.0. |
| `UTCOffset=N` (-14 a 14) | Horas respecto de UTC para la hora **local** que devuelven `ClockYYMMDD`/`ClockHHMM` (§21). Admite decimales: `-3`, `5.5`. **No cambia la hora de los registros**, que siempre se archivan en UTC. Desde v1.7.8. |

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

Para que el valor de una variable **sobreviva un reinicio** del equipo,
hay que nombrarla en `PreserveVariables` (§22). Sin eso, cada arranque la
deja en 0.

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
- La conversión es `mA = volts_del_terminal / SHUNT_OHM × 1000`, con
  `SHUNT_OHM = 260Ω` desde v1.6.10. Ese **no** es el valor del resistor
  físico: el shunt de 269Ω del esquema queda en paralelo con los ~7.8kΩ que
  presenta la entrada del Opta, y parte de la corriente del lazo se va por
  ahí. Hasta v1.6.9 se dividía por 270 y **todas las lecturas de 4-20mA
  salían un 3.85% bajas** en todo el rango — ver la nota de calibración al
  final de esta sección.

> **Recalibración de v1.6.10.** El error era de span, no de cero: crece con
> la corriente. Sobre un sensor escalado a 0-5 m son unos 15 cm en el fondo
> de escala; sobre el ultrasónico de la compuerta (`Mult = 29.375 cm/mA`),
> unos 14 cm a media escala y 23 cm cerca de 20 mA. **Los históricos
> anteriores a v1.6.10 arrastran ese sesgo**, y si algún equipo se calibró en
> terreno ajustando su `Offset` contra la lectura vieja, hay que rehacer esa
> calibración después de actualizar.

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

### `Battery` — voltaje de alimentación

```
Battery(Dest)       ' divisor cableado en A7 (I8) — valor por defecto
Battery(Dest, N)    ' divisor cableado en el canal N (1-8 → A0-A7 / I1-I8)
```

Lee la entrada analógica indicada y le aplica el **factor del divisor
resistivo** 2×10kΩ, devolviendo el voltaje de alimentación en vez del voltaje
del terminal. La conversión es `V = cuentas_ADC × 10.0 / 4095 × 3.351`
(fondo de escala ~33.5 V).

> Ojo: esta rama usa un fondo de escala de **10.0 V**, no el `OPTA_VREF=10.70`
> que usan `VoltSE`/`Units=mA`. El par `10.0` + `3.351` viene calibrado en
> conjunto contra el hardware real, así que no se pueden mezclar con el
> escalado de las otras instrucciones.

- `Dest` (arg 0): variable destino (debe estar declarada antes).
- `N` (arg 1, **extensión propia del Opta**): canal donde está cableado el
  divisor, `1`→A0 (I1) … `8`→A7 (I8). Hasta v1.6.7 el divisor estaba fijo en
  A7; ahora puede ir en cualquiera de las ocho entradas.
- Si se omite `N`, o si vale `0` (el argumento `Option` de un `Battery(Dest,0)`
  de CR1000 real), se usa **A7** — así los programas que ya existían siguen
  comportándose igual.
- El canal elegido queda **reservado**: no entra en la asignación automática,
  así que ninguna otra variable se lo puede llevar.
- `N` fuera del rango 1-8 se registra como advertencia de parseo (§1) y cae a
  A7.

> **Importante:** el factor `3.351` es del divisor **físico** del cableado, no
> del canal. Poner `Battery(Dest, 3)` sin haber cableado el divisor en I3 da
> una lectura 3.351× más alta que el voltaje real de esa entrada. A la inversa,
> un canal con divisor leído con `VoltSE`/`Units=mA` da un valor 3.351× bajo.

### Asignación automática de canales A0-A7

Al terminar de parsear el programa:

1. Los canales fijados **explícitamente** (`Battery(...,N)`, `AIChannel`,
   `VoltDiff`/`VoltSE` con `Chan` entre 1 y 8) quedan reservados y se excluyen
   del reparto automático.
2. *Fallback histórico:* la **primera** variable cuyo nombre contenga la
   subcadena `att` (mayúscula o minúscula, p. ej. `BattV`, `Batt_Volt`) y que
   no tenga ni canal ni instrucción de lectura se reserva **A7** como voltaje
   de alimentación, con prioridad sobre el reparto secuencial. Una variable
   que ya pasó por `Battery(...)` tiene canal, así que no entra acá. Si A7 ya
   está tomado, la asignación **no** ocurre y queda registrada en el log
   (`A7 ocupado, sin BattV`): en ese caso hay que declarar el canal
   explícitamente con `Battery(Dest, N)`.
3. El resto de variables que efectivamente leen hardware (tienen
   `VoltDiff`/`VoltSE` o `Units=mA`) y no tienen canal ya asignado reciben,
   en **orden de declaración**, el siguiente canal A0-A7 libre.
4. Variables declaradas pero sin ninguna instrucción de lectura (sensores
   "comentados" o no usados) **no consumen canal**: quedan con valor `0`
   permanente.

---

## 8. Salidas de relé — `PortSet`

```
PortSet(Rele, Valor)
```

- `Rele` (arg 0): número de relé físico, **1 a 4** (DO1-DO4). Va como número,
  no como variable.
- `Valor` (arg 1): cualquier expresión. El relé queda **cerrado** si el
  resultado supera `0.5`, y abierto si no.

Es una instrucción ejecutable como cualquier otra: corre en el punto del
programa donde está escrita, respeta los bloques `If`, y **el relé cambia solo
ahí**. Si el programa no vuelve a ejecutar esa línea, el relé se queda como
está.

> **Cargar un programa apaga los cuatro relés** (desde v1.10.1). Un relé solo
> lo mueve un `PortSet`, así que el que dejó encendido el programa anterior
> seguiría así, sin nadie que lo corte y sin el tiempo máximo de movimiento que
> tenía ese programa. Cada vez que se carga o recarga un programa (por
> FileDownload, `RunNow`, USB o al arrancar) el equipo pone los relés en
> reposo, y el programa nuevo parte de ahí. Reemplazar un programa con una
> compuerta en movimiento la **detiene**.

> **Los LED del frente siguen al relé** (desde v1.10.2). En el Opta los LED
> D0 a D3 son pines aparte del relé: antes de la 1.10.2 el relé cerraba y el LED
> quedaba apagado. Ahora cada `PortSet` (y cada escritura remota) mueve las dos
> cosas, y al cargar un programa se apagan juntos.

El patrón habitual es decidir con la lógica y aplicar al final del `Scan`, de
modo que en cada ciclo primero se decide todo y después se acciona:

```
If (Nivel < Niv_Bajo) Then Bomba = 1
If (Nivel > Niv_Alto) Then Bomba = 0
PortSet(1, Bomba)
```

También vale directo dentro de un `If`, en una línea o en bloque:

```
If (Moviendo = 1) Then PortSet(1, 1)
```

> **Cambio incompatible en v1.7.0.** Hasta v1.6.18 `PortSet` no era una
> instrucción sino una **declaración**: `PortSet(Variable, valor)` ligaba esa
> variable a un relé, el argumento de valor se ignoraba por completo, y el relé
> pasaba a seguir el valor de la variable en **cada scan**. El relé se elegía
> con un tercer argumento `N` o, si faltaba, mirando las tres primeras letras
> del nombre de la variable (`DO1`..`DO4`) — con lo cual `Bomba_DO1` caía en el
> relé 1 por descarte y no por decisión del programa.
>
> Ese modelo tenía tres efectos que ya no existen: cualquier asignación a la
> variable, en cualquier parte del programa, movía hardware; un `SetValues`
> remoto lo movía al instante y el programa lo pisaba en el scan siguiente; y
> el estado del relé se copiaba de vuelta a la variable.
>
> **Un `.CR1` escrito para el modelo viejo no acciona ningún relé en v1.7.0.**
> No da error de carga: el equipo registra la línea en el log y sigue
> corriendo, las variables cambian y los relés se quedan quietos. Al
> actualizar el firmware hay que migrar el programa.

### Migrar un programa del modelo viejo

| Antes (≤ v1.6.18) | Ahora (v1.7.0) |
|---|---|
| `PortSet(DO1, 0, 1)` + `If (x) Then DO1 = 1` | `If (x) Then DO1 = 1` + `PortSet(1, DO1)` |
| `PortSet(Bomba_DO1, 0)` + `Bomba_DO1 = 1` | `Bomba = 1` + `PortSet(1, Bomba)` |

La variable deja de ser especial: es una variable común que se archiva en las
tablas igual que antes, y el nombre puede ser cualquiera. Lo único que mueve
el relé es el `PortSet`.

### Accionar un relé desde la plataforma

Escribir la variable por `SetValues` (botón de la HMI, LoggerNet) ya **no**
mueve el relé directamente: el equipo escribe la variable y nada más. Para que
un mando remoto funcione, el `.CR1` tiene que llevar su `PortSet(N, Variable)`
dentro del `Scan` — el relé se mueve en el scan siguiente, no al instante.

A cambio desaparece el conflicto que había antes, donde un mando manual y un
programa con control automático se pisaban ciclo por medio sin que se notara
cuál iba ganando.

---

## 9. Contador de pulsos — `PulseCount`

```
PulseCount(Dest, Reps, Channel, PConfig, POption, Mult, Offset)
PulseEdge(Dest, Rising|Falling)   ' extensión propia, opcional
ExciteCh(N)                       ' extensión propia, alimenta el sensor
```

- `Dest` (arg 0): variable destino.
- `Channel` (arg 2): `P1`-`P8` o `1`-`8` → canal A0-A7 configurado como
  entrada con interrupción, con antirrebote de **50 ms** por software.
- `Mult`/`Offset` (args 5 y 6): `valor = pulsos_del_scan × Mult + Offset`.
  El conteo se resetea a 0 en cada scan (es decir, `valor` es "pulsos desde
  el último scan", no un acumulado total).
- `Reps` y `PConfig`/`POption` (args 1, 3, 4) se ignoran.
- El canal queda **reservado**: no se reparte a ninguna variable de medición.

### Cableado y flanco

El montaje del esquema IP-230 no usa pull-up: un canal analógico puesto como
**salida de excitación** (`ExciteCh`) entrega ~3.3 V al contacto del sensor, y
el canal de conteo lleva un **pull-down externo de 10kΩ al NEGATIVO** que fija
el reposo en 0 V. Cada cierre del contacto sube el nodo → el flanco que hay
que contar es el de **subida**.

Por eso el flanco por defecto es `RISING` (hasta v1.6.7 era `FALLING`, para un
montaje con pull-up que este hardware no usa). `PulseEdge(Dest, Falling)` lo
cambia si tu cableado es el inverso. Acepta `Rising`/`Subida`/`1` y
`Falling`/`Bajada`/`0`.

`ExciteCh(N)` pone el canal `N` (1-8 → A0-A7 / I1-I8) como salida digital en
alto de forma permanente. **Sin esta línea el sensor no tiene de dónde sacar
tensión y no genera ningún pulso.** No declares el mismo canal como `ExciteCh`
y como `Channel` de un `PulseCount`: la salida gana, el conteo queda muerto y
se registra el aviso en el log.

> **Verificá con multímetro** el nodo de la entrada de conteo con el contacto
> cerrado. Esos 3.3 V salen a través de la red divisora de la entrada del Opta,
> así que tienen impedancia de fuente alta; con el pull-down de 10kΩ colgando,
> el nodo puede quedar bastante por debajo de 3.3 V. Medí el circuito armado,
> no la salida en vacío.

### Ritmo máximo

El antirrebote de 50 ms topea el conteo en **20 pulsos/s**. Los equipos de
terreno están muy por debajo:

| Equipo | Ritmo máximo | Período |
|---|---|---|
| Pluviómetro de cangilones | 50 tips/min (0.83 Hz) | 1.2 s |
| Flujómetro Bermad DN125, 1 pulso/100 L | 29 tips/min (0.49 Hz) | 2.05 s |
| Flujómetro Bermad DN125, 1 pulso/1000 L | 3 tips/min (0.05 Hz) | 20.6 s |

### Cómo archivar el conteo (importante)

Como `Dest` vale "pulsos desde el último scan", con sensores tan lentos la
mayoría de los scans valen `0`. Un campo `Sample` archivaría casi siempre cero
y perderías el volumen: **hay que usar `Totalize`**, que suma todos los scans
del intervalo.

Con `Totalize`, el `Offset` de `PulseCount` tiene que ser **`0`**. Como
`valor = pulsos × Mult + Offset` se evalúa en todos los scans, un offset
distinto de cero se suma aunque no haya pulsos e infla el total; el parser lo
avisa en el log.

Si además querés un acumulado corriente dentro del programa:

```
Volumen_m3 = Volumen_m3 + Pulsos * 0.1
```

Ojo que eso vive en RAM y se pierde al reiniciar. No hace falta persistirlo: la
tabla histórica ya guarda los volúmenes por intervalo en flash y sobreviven al
corte, así que el acumulado se reconstruye sumándolos. Un total persistido, en
cambio, escondería los pulsos que ocurrieron mientras el equipo estuvo sin
energía detrás de un número que parece continuo.

### Ejemplo completo — flujómetro de 1 pulso/100 L

```
Public Pulsos, Volumen_m3
Units Volumen_m3 = m3

DataTable(Caudal, True, 8760)
    DataInterval(0, 1, Hour, 0)
    Totalize(1, Pulsos, FP2)      ' m3 de la hora (Mult ya convirtio)
    Sample(1, Volumen_m3, FP2)    ' acumulado corriente (se pierde al reiniciar)
EndTable

BeginProg
    Scan(10, Sec, 0, 0)
        ExciteCh(3)                              ' I3 alimenta el contacto
        PulseCount(Pulsos, 1, 4, 0, 0, 0.1, 0)   ' cuenta en I4, 0.1 m3/pulso
        Volumen_m3 = Volumen_m3 + Pulsos
    NextScan
EndProg
```

Con `Mult = 0.1`, `Pulsos` ya viene en m³ por scan, y el `Totalize` de la tabla
archiva los m³ de cada hora.

---

## 10. Instrucciones reconocidas pero sin ejecución real

```
BrHalf(...) | RealTime(...) | PanelTemp(...) | SW12(...)
```

Se identifica la instrucción y, si trae una variable destino como primer
argumento, esa variable se marca "sin canal propio" (no roba un A0-A7) — pero
**no se simula ninguna lectura**: la variable queda en `0` salvo que otra
parte del programa la asigne.

`Battery(...)` **ya no** está en esta lista: desde v1.6.8 lee hardware de
verdad y acepta el canal como segundo argumento (ver §7).

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
  se descarta. Hasta v1.6.8 había un caso que se colaba: si los 20 tokens se
  agotaban justo con un `)` que vaciaba la pila de operadores, el resto de la
  expresión se descartaba en silencio y la parte compilada se evaluaba igual
  (p. ej. `(A+B+...+K) * 999` perdía el `* 999`). Desde v1.6.9 se rechaza y
  queda en el log.
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
- **Si el equipo corre un firmware ≤v1.6.8, esta instrucción no funciona
  indentada** — que es como se escribe normalmente, dentro del `Scan`. El
  nombre destino se recortaba con la sangría incluida y no encontraba la
  variable, así que la línea se descartaba y el destino quedaba en `0`. Ver
  la nota de §1. No afectaba a las asignaciones dentro de un `If ... Then`.
- Toda variable que aparezca como destino de una asignación queda marcada
  `noAutoPin` (no participa de la asignación automática de canal, salvo que
  también tenga una instrucción `VoltDiff`/`VoltSE` real, en cuyo caso esa
  gana).
- Máximo **128 instrucciones totales** en todo el programa (`CR_MAX_STMTS=128`,
  eran 64 hasta v1.9.2 y 32 hasta v1.6.11), contando asignaciones **y** cada
  `If`/`ElseIf`/`Else`/`EndIf` como una instrucción cada uno. Se subió a 128 en
  v1.9.3 porque dos compuertas en un mismo Opta necesitan ~76: un lazo de
  compuerta gasta ~38 y no hay bucles ni subrutinas, así que el segundo es una
  copia del primero.

> **Este es el techo real de complejidad de un programa**, no el tamaño del
> archivo. El buffer de 16 KB da para mucho más texto del que 128 instrucciones
> pueden ocupar, así que lo que llena un `.CR1` son los comentarios, no la
> lógica. Antes de ampliar nada, medí contra este límite:
> `programa_compuerta.CR1` llenaba el buffer de 8 KB con un 63% de comentarios
> usando solo 2.7 KB de código real — pero ya gastaba 28 de sus 32
> instrucciones.

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
  - Cada intervalo arranca con el acumulador **vacío**. Hasta v1.6.7 se
    sembraba con el valor del scan que se acababa de archivar, así que ese
    scan se contaba dos veces y `Totalize` se iba hacia arriba en ~1/n_scans
    por intervalo (17% con 6 scans por intervalo, 3.3% con 30). `Average`
    tenía el mismo sesgo, con un término de más sobre el mismo divisor.
    **Los históricos anteriores a v1.6.8 arrastran ese error.**
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
| Tamaño del programa `.CR1` | 16384 bytes (**comentarios incluidos**) | `storedProg[]` |
| Longitud de línea | 127 caracteres | — |
| Argumentos por instrucción | 12, de hasta 31 caracteres c/u | — |
| Variables (`Public`+`Dim`) | 64 | `CR_MAX_VARS` |
| Constantes (`Const`) | 16 | `CR_MAX_CONSTS` |
| Tablas (`DataTable`) | 4 | `CR_MAX_TABLES` |
| Campos por tabla | 32 | `CR_MAX_FIELDS` |
| Instrucciones (asignaciones + If/ElseIf/Else/EndIf) | 128 | `CR_MAX_STMTS` |
| Tokens por expresión compilada | 20 | `CR_MAX_EXPR_TOKENS` |
| Profundidad de anidamiento `If` | 2 niveles | `CR_IF_MAX_DEPTH` |
| Nombres en `PreserveVariables` | 16 | `CR_MAX_PRESERVE` |
| Filtros `MedianRun` simultáneos | 4 | `CR_MAX_MEDIAN` |
| Ventana de `MedianRun` | 3 a 9, impar | `CR_MEDIAN_MAX_WIN` |
| `SetpointSchedule` simultáneos (uno por compuerta) | 4 | `CR_MAX_SCHED` |
| `RatingCurve` simultáneas | 4 | `CR_MAX_RATING` |
| `ModbusRTU` simultáneos | 4 | `CR_MAX_MODBUS` |
| Valores por lectura `ModbusRTU` | 32 | `CR_MODBUS_MAX_COUNT` |
| Entradas de la agenda `agenda.csv` | 200 en total | `CR_MAX_AGENDA` |
| Tamaño del `agenda.csv` | 8191 bytes | `AGENDA_BUF_BYTES` |
| Canales analógicos A0-A7 (medición + pulso + excitación) | 8 en total | — |
| Ritmo de conteo de `PulseCount` | 20 pulsos/s | `PULSE_DEBOUNCE_US` |
| Nombre de variable/tabla/campo | 23 caracteres | — |
| Nombre de constante | 19 caracteres | — |
| Nombre de estación (`StationName`) | 23 caracteres | — |
| Host (`ServerHost`) | 63 caracteres | — |

---

## 17. Fuera de alcance (no implementado)

- **SDI-12** (`SDI12Recorder`, etc.).
- **Puerto serie/COM** (`SerialOpen`, `SerialIn`, `SerialOut`, RS-232/RS-485
  genérico). Un sensor RS-485 **Modbus RTU** sí se lee, con `ModbusRTU` (§25);
  `ModbusMaster` de Campbell no existe con esa firma.
- Funciones matemáticas más allá de `Abs`/`Int`/`Sqr` (sin `Sin`, `Cos`,
  `Ln`, `Exp`, `Mod`, `ATN`, etc.). **Tampoco hay potencia (`^`)**: la curva de
  aforo `Q = a·h^b` de un río se calcula con `RatingCurve` (§26).
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

Ver [`ejemplos/programa_compuerta.CR1`](ejemplos/programa_compuerta.CR1) —
control de una compuerta con sensor ultrasónico 4-20mA, que usa:
`StationName`,
`ServerHost`/`ServerPort`/`PakBusAddress`, `Const`, `Public`/`Dim`, `Units`,
`AIChannel`, `PortSet` para accionar dos relés, expresiones aritméticas
completas, bloques `If`/`AND` de una línea encadenados, y una `DataTable`
con `Sample` a 1 registro/minuto.

Un ejemplo más simple, con `VoltSE`, `Average`/`Maximum`/`Minimum` y dos
tablas con distinta frecuencia, en
[`ejemplos/programa_opta.CR1`](ejemplos/programa_opta.CR1) (nota: ese archivo
es más antiguo y su encabezado cita límites desactualizados del parser — los
límites reales son los de la §16 de este manual).

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
- [ ] Si el divisor de alimentación está cableado en una entrada que **no**
      es I8/A7, declararlo con `Battery(Dest, N)` (§7). Hasta v1.6.7 el canal
      estaba fijo en A7 y no había forma de moverlo.
- [ ] Revisar los `Chan` explícitos (`VoltDiff`/`VoltSE`/`AIChannel`/
      `Battery`/`PulseCount`/`ExciteCh`): desde v1.6.8 un canal fijado a mano
      queda **reservado** y la asignación automática ya no se lo puede volver
      a entregar a otra variable. Si un programa dependía de ese solapamiento,
      las variables automáticas se corren un canal.
- [ ] Si hay un sensor de pulsos (pluviómetro, flujómetro), archivar el conteo
      con `Totalize`, nunca con `Sample` (§9). Si la excitación sale de un
      canal del Opta y no de una fuente externa, agregar el `ExciteCh(N)` —
      sin esa línea no cuenta nada.
- [ ] **Si el equipo viene de un firmware ≤v1.6.18 y usa relés**, migrar todos
      los `PortSet` a la forma `PortSet(N, Valor)` con `N` = 1-4 (§8). Los
      programas viejos cargan sin error y dejan los relés quietos: la falla es
      silenciosa y solo se nota en terreno.
- [ ] **Si el equipo viene de un firmware ≤v1.6.8**, revisar todas las
      asignaciones simples indentadas: hasta esa versión se descartaban en
      silencio y la variable quedaba en `0`. Revisá los históricos de esos
      equipos antes de darlos por buenos (§1).
- [ ] **Si el equipo viene de ≤v1.6.9 y usa sensores 4-20mA**, sus lecturas
      venían un 3.85% bajas. Al actualizar, rehacer cualquier calibración de
      terreno que se haya hecho ajustando `Offset` contra la lectura vieja
      (§6).
- [ ] Verificar que cada nombre de variable usado en `Sample`/`Average`/etc.
      esté realmente declarado (`Public`/`Dim`) — un typo deja un campo que
      siempre vale `0` (desde v1.6.3 esto y cualquier otra línea ignorada
      quedan logueados, ver checklist siguiente).
- [ ] Después de cargar un `.CR1` nuevo (o de un release ≥v1.6.3), revisar
      el `.HLOG` del equipo buscando `"[CRBasic]"` — cualquier línea con
      `"ignorada"` apunta a un número de línea exacto del programa que no
      se pudo interpretar (ver "Diagnóstico de errores de parseo" en §1).

---

## 20. Módem celular vía router Teltonika (extensión propia, desde v1.6.14)

```
ModemRSSI(Dest)     ' dBm
ModemRSRP(Dest)     ' dBm
ModemRSRQ(Dest)     ' dB
ModemSINR(Dest)     ' dB
ModemTemp(Dest)     ' °C, temperatura del módulo celular
ModemNetGen(Dest)   ' 2/3/4 según tecnología (2G/3G/4G)
```

Cada instrucción vincula `Dest` al último valor leído de un router Teltonika
(probado contra un RUT200) por su API REST local, sin depender de la nube
RMS de Teltonika. No consume ningún canal analógico (equivalente a
`noAutoPin`, igual que `BrHalf`/`PanelTemp`/`SW12` en §10, pero a diferencia
de esos **sí tiene ejecución real**).

- El equipo hace `POST /api/login` + `GET /api/modems/status` sobre HTTP
  plano cada 60s, contra el **gateway DHCP del Opta** (no una IP fija) — el
  router en modo LAN normalmente es ese gateway.
- El poll **solo corre si el `.CR1` cargado declara al menos una de estas
  instrucciones** — un Opta sin router (o con router pero `.CR1` que no las
  usa) no genera ningún tráfico nuevo.
- Usuario y clave del router se declaran **en el `.CR1` de cada equipo** con
  `RouterUser=` / `RouterPass=` (§3), por el mismo mecanismo que `ServerHost=`.
  Hasta v1.6.17 estaban hardcodeados en el firmware y eran los mismos para
  todos los equipos que corrían ese binario; desde v1.6.18 cada sitio puede
  tener su propia clave sin recompilar. El firmware arranca con el usuario
  `admin` y **la clave vacía**, así que un programa con `Modem*` pero sin
  `RouterPass=` no va a poder loguearse.

> **La clave queda en texto plano dentro del `.CR1`.** Ese archivo se puede
> descargar del equipo desde el visor de archivos del servidor, así que quien
> tenga acceso al servidor tiene la clave del router. Conviene que la del
> RUT200 no se reutilice en ningún otro lado, y no subir esos `.CR1` a un
> repositorio. El firmware sí tiene el cuidado de no escribirla en el log:
> registra `RouterPass: (definida)` y nada más.
- Campos de texto del router (operador, ICCID, IMEI) no se exponen como
  variable — BMP5 solo transporta `float`. Quedan solo en el log Serial del
  Opta.
- Si el router no responde (apagado, cable desconectado, o el Opta está en
  una LAN sin modem pero con estas instrucciones declaradas por error), la
  variable simplemente conserva su último valor conocido (`0` si nunca hubo
  lectura exitosa) — no genera error de parseo ni cuelga el equipo.

---

## 21. Reloj del programa en hora local (extensión propia, desde v1.7.8)

```
ClockYYMMDD(Dest)   ' fecha como AAMMDD — 251027 para el 27/10/2025
ClockHHMM(Dest)     ' hora  como HHMM   — 1435 para las 14:35
```

Las dos vinculan `Dest` al reloj del equipo y la refrescan **en cada scan**,
en hora local según `UTCOffset=` (§3). No se les asigna nada desde el
programa y no ocupan canal analógico.

Ambos valores caben exactos en un `float`, que es lo único que transporta
BMP5, y están pensados para comparar contra un horario de operación sin
hacer cuentas:

```
UTCOffset=-3

Public Hora_Hoy, Regar
ClockHHMM(Hora_Hoy)
If (Hora_Hoy >= 800) Then Regar = 1
If (Hora_Hoy >= 1800) Then Regar = 0
PortSet(1, Regar)
```

- **Valen `0` mientras el reloj no esté sincronizado.** Es deliberado: un
  programa que compare contra una fecha u hora programada no dispara con la
  hora equivocada durante el arranque, antes de que el equipo tome la hora
  del servidor. Conviene que la lógica trate el `0` como "todavía no sé qué
  hora es" y no como medianoche.
- **`UTCOffset=` solo afecta a estas dos instrucciones.** Los registros de
  las tablas se archivan siempre en UTC, así que cambiarla no mueve el
  histórico ni lo que ve el servidor.
- Sin `UTCOffset=`, ambas devuelven hora UTC. Si la lógica compara contra un
  horario de operación local, va a disparar corrida — el linter avisa de ese
  caso.

---

## 22. Consignas que sobreviven un reinicio — `PreserveVariables` (extensión propia, desde v1.8.0)

```
PreserveVariables Var1, Var2    ' solo esas (recomendado)
PreserveVariables               ' forma del CR1000: toda variable que escriba la plataforma
```

Guarda en la flash del equipo el valor de las variables que nombra y lo
restaura al arrancar. Es para lo que se fija **una vez** desde la
plataforma y tiene que seguir ahí después: la consigna de un lazo de
control, una banda muerta, un horario de operación.

**Sin esta línea, cada reinicio deja esas variables en 0.** En un sitio
alimentado por panel solar un corte no es raro, y un lazo que arranca con
objetivo 0 manda la maniobra equivocada en vez de quedarse quieto.

```
Public Nivel_cm, Consigna_cm, Banda_cm
PreserveVariables Consigna_cm, Banda_cm

AIChannel(Nivel_cm, 1)
```

- **La línea puede ir antes o después de los `Public`.** El equipo liga los
  nombres cuando termina de leer el programa, no cuando lee la línea. En un
  CR1000 va en la sección de declaraciones, y ahí también funciona.
- **Solo se guarda lo que escribe la plataforma, no lo que calcula el
  programa.** El volcado lo dispara la escritura remota. Una variable que el
  propio `.CR1` asigna en cada scan no se preserva: guardarla a cada vuelta
  desgastaría la flash sin ninguna necesidad. El linter avisa de ese caso.
- **Las variables que mide el equipo quedan fuera**, aunque se las nombre:
  un canal 4-20mA, `Battery`, `PulseCount`, las `Modem*` y las de reloj se
  vuelven a leer al arrancar, así que preservarlas solo serviría para
  entregarle a la lógica una medición vieja antes de la primera lectura real.
  El equipo lo registra en su log y sigue con el resto de la línea.
- **El valor se vuelca unos segundos después de la escritura**, no al
  instante. Así un grupo de valores que el HMI manda seguidos al tocar
  Guardar se escribe de una sola vez. El efecto lateral es útil: una
  variable de **orden** que el scan consume y pone en cero (`MoverCm`,
  `Parar`) se guarda ya consumida, así que un reinicio no repite la
  maniobra. Pero eso depende de que el programa la limpie, y conviene no
  apoyarse en ello: mejor nombrar solo las consignas.
- **Hasta 64 nombres**, el mismo tope que las variables declarables: todo lo
  que el programa puede declarar se puede preservar. Los que sobren quedan
  fuera y van al log.
- La forma sin argumentos existe para que un `.CR1` de un CR1000 real se
  cargue sin tocarlo. Alcanza también a las variables de orden, así que
  para un programa nuevo conviene la lista explícita.

> **Qué pasa al recargar el programa.** Reenviar el `.CR1` también deja
> todas las variables en 0, igual que un reinicio. El equipo restaura las
> preservadas **por nombre**, así que un ajuste al programa no se lleva las
> consignas; una variable que el programa nuevo ya no declara se ignora.

---

## 23. Mediana móvil sobre un sensor — `MedianRun` (extensión propia, desde v1.9.0)

```
MedianRun(Destino, Fuente, Ventana)   ' Ventana impar, de 3 a 9
```

Guarda las últimas N lecturas de `Fuente` y deja en `Destino` la del medio.
El dato crudo queda intacto en `Fuente`, así que se pueden archivar los dos
y comparar.

```
Public Nivel_mA, Nivel_filt
Units Nivel_mA = mA
AIChannel(Nivel_mA, 1)
MedianRun(Nivel_filt, Nivel_mA, 7)

DataTable(Registro, True, 10080)
    DataInterval(0, 1, Min, 0)
    Sample(1, Nivel_mA,   FP2)   ' crudo
    Sample(1, Nivel_filt, FP2)   ' filtrado
EndTable
```

**Por qué mediana y no promedio.** La mediana *descarta* el pico aislado en
vez de repartirlo. Un eco espurio de un ultrasónico mueve el promedio de las
9 muestras en una novena parte de su error; a la mediana no la mueve en
absoluto. Antes de decidir una maniobra de compuerta eso es lo que se quiere:
que un solo valor raro no mande a mover un motor.

- **Corre una vez por scan**, después de leer los sensores y **antes** de las
  asignaciones. El programa ya trabaja con el valor filtrado de ese mismo
  scan, no con el del anterior.
- **Nunca devuelve 0 mientras se llena la ventana.** Da la mediana de las
  muestras que haya, así que en el primer scan vale lo mismo que la lectura
  cruda. Un lazo de control que arrancara mirando un 0 mandaría justo la
  maniobra que el filtro viene a evitar.
- **El destino no consume canal analógico**: lo calcula el filtro, no un
  borne. Tampoco lo preserva `PreserveVariables` (§22), por la misma razón
  que no preserva una medición: al arrancar se vuelve a calcular.
- **Ventana par**: no hay valor central, así que el equipo baja a la impar
  anterior y lo anota en el log. La salida sigue siendo siempre una muestra
  real y no el promedio de dos.
- **Hasta 4 filtros** en un mismo programa.

> **El destino no puede recibir además una asignación del programa.** El
> filtro corre antes que los statements, así que la asignación lo pisaría y el
> valor quedaría sin filtrar, sin ningún aviso en tiempo de ejecución. El
> linter lo marca como error.

**Cuánta ventana, y por qué depende del scan.** La ventana se cuenta en
**muestras, no en tiempo**, así que el intervalo del `Scan` decide cuánto dura
en segundos. La regla es exacta: la mediana descarta una perturbación que
ocupe **hasta la mitad de la ventana**, y sigue a la señal apenas la pasa.

| Ventana | Descarta hasta | Con scan de 1 s | Con scan de 10 s |
|---|---|---|---|
| 3 | 1 muestra | 1 s | 10 s |
| 5 | 2 muestras | 2 s | 20 s |
| 9 | 4 muestras | 4 s | 40 s |

Con ventana 5, tres lecturas altas seguidas ya son mayoría y el valor del
medio es alto, así que el filtro sigue a la señal — y eso es lo correcto: tres
lecturas seguidas no son un pico, son el nivel. Elegir la ventana es elegir
cuánto tiene que durar algo para que el equipo se lo crea. Para dimensionarla
hace falta saber cuánto dura la perturbación real: si el eco espurio del
ultrasónico ensucia una sola lectura, 5 sobra; si puede ensuciar dos o tres
seguidas, hace falta 9.

El precio es el retraso: más ventana filtra mejor pero tarda más en seguir un
cambio real. Con scan de 1 s, una ventana de 9 demora unos 4 s en reflejar del
todo un escalón de nivel. Para una compuerta que se mueve despacio eso no
molesta; conviene ajustarlo en ensayo mirando el crudo y el filtrado juntos.

> **Al probarlo a mano, cuidado con el scan corto.** Con scan de 1 s una
> ventana de 5 sólo descarta perturbaciones de hasta 2 segundos, y nadie
> escribe un valor y lo vuelve a cambiar en menos de eso: todo lo que se
> escriba a mano dura más que la ventana, y el filtro parece no filtrar
> aunque esté funcionando bien. Para verlo hay que usar un scan largo, o
> comparar el crudo con el filtrado sobre la señal real del sensor.


---

## 24. Agenda de consignas — `SetpointSchedule` (extensión propia, desde v1.9.3)

```
SetpointSchedule(Consigna, Canal [, Agenda_N [, Agenda_Serie [, Modo]]])
```

Cambia una consigna según una **agenda de fecha y hora** guardada en el equipo.
Pensada para programar el nivel de un río que debe mantener una compuerta: dos
niveles por día durante semanas, sin escribir una escalera de `If`.

```
Public Consigna_cm, Agenda_N, Agenda_Serie
Units Consigna_cm = cm
PreserveVariables Consigna_cm
SetpointSchedule(Consigna_cm, 1, Agenda_N, Agenda_Serie)
```

**La agenda es un archivo, no código.** El servidor arma `USR:agenda.csv` y lo
manda al equipo; el `.CR1` gasta **una instrucción** y de 1 a 3 variables por
compuerta. Una escalera de `If` gastaba 3 variables y 2 instrucciones por
entrada y topaba en unas 12; la agenda admite **200 entradas** (un mes de dos
niveles por día en dos compuertas son unas 124).

Formato del archivo, una entrada por línea, con **decimal en punto**:

```
#AGENDA 2,47
261103,0810,1,45.0
261103,0810,2,38.0
261103,1430,1,52.5
```

- La primera línea es obligatoria: `#AGENDA <formato>,<serie>`. El formato es 2
  (todo en cm) o 3 (cada entrada con su unidad, desde v1.11.0). La **serie**
  la sube el servidor en cada cambio del calendario.
- Cada entrada del formato 2 es `AAMMDD,HHMM,canal,cm`. El **canal** es la
  compuerta (1 a 4). En el formato 3 lleva una columna más,
  `AAMMDD,HHMM,canal,valor,unidad`, con unidad `0` = cm de nivel y `1` = m³/s
  de caudal (ver «Programar en caudal», más abajo).
- Las líneas que empiezan con `#` y las vacías se ignoran. No hace falta que
  vengan ordenadas.
- **Una línea mala rechaza el archivo entero** y el equipo conserva la agenda
  anterior. Una agenda aplicada a medias es peor que una vieja, porque nadie se
  entera de que falta algo.

**Cuándo escribe la consigna.** El equipo toma la entrada **más reciente que ya
venció** para ese canal y escribe su nivel, pero **sólo cuando esa entrada
cambia**, no en cada scan. Por eso el ajuste manual del operador aguanta hasta
el próximo cambio programado: si la agenda escribiera siempre, la consigna que
el operador tocó desde el HMI volvería atrás en menos de un scan.

- **Corre sola durante los cortes de enlace.** La agenda vive en el equipo: no
  necesita al servidor para cambiar de nivel.
- **Sin reloj sincronizado no toca nada.** La consigna queda en su último valor.
  La hora es la **local** (`UTCOffset=`, §21), así que si la zona cambia de
  hora en invierno conviene que el servidor convierta las horas al generar el
  archivo.
- **Un reinicio con reloj sincronizado reaplica la agenda** y descarta el
  ajuste manual: es lo correcto, porque la agenda es la fuente de verdad.
- **Se persiste sólo si el valor cambia**, así dos entradas seguidas con el
  mismo nivel no gastan flash.
- **Una agenda nueva (otra serie) se reevalúa entera.** Si se corrige el nivel
  de un horario que ya pasó, la corrección se aplica. Reenviar la misma serie no
  toca nada, así un reenvío redundante no se come un ajuste manual.

**Argumentos.**

| Argumento | Qué es |
|---|---|
| `Consigna` | La variable que mueve la agenda: el nivel que el lazo mantiene. |
| `Canal` | La compuerta, **entero de 1 a 4, literal o `Const`**. Una variable no sirve: cambiaría de compuerta en pleno scan. Dos instrucciones no pueden compartirlo. |
| `Agenda_N` | Opcional, de solo lectura: cuántas entradas tiene cargadas **este canal**. |
| `Agenda_Serie` | Opcional, de solo lectura: la serie de la agenda cargada. El HMI la usa para ver si el equipo tiene la vigente sin leerle el archivo. |
| `Modo` | Opcional (v1.11.0): la variable donde el equipo deja la unidad de la consigna vigente, `0` = cm y `1` = m³/s. Se escribe **en el mismo instante** que la consigna. Sin ella, toda entrada se toma como cm. |

> **La consigna sí se preserva, a diferencia de una medición.** Con el reloj
> sin sincronizar el equipo no le escribe, y su último valor tiene que
> sobrevivir un reinicio. Por eso `PreserveVariables Consigna_cm` (§22) se
> acepta. Sin esa línea, un reinicio sin hora deja la consigna en 0 y el lazo
> trabaja con ese objetivo; el linter lo avisa. En cambio `Agenda_N` y
> `Agenda_Serie` salen del archivo en cada scan y **no** se preservan.

> **El programa no debe asignarle valor a la consigna en cada scan.** La agenda
> escribe antes de las asignaciones, así que esa asignación la pisa. Una
> asignación condicional (un override propio) es legítima y el linter sólo avisa.

**Dos compuertas en un equipo** llevan dos instrucciones, una por canal, cada
una con su propia consigna:

```
SetpointSchedule(Consigna1_cm, 1, Agenda_N1, Agenda_Serie)
SetpointSchedule(Consigna2_cm, 2, Agenda_N2)
```

Cada canal guarda por separado cuál fue su última entrada aplicada, así que el
cambio de una compuerta no afecta a la otra.

### Programar en caudal (m³/s) — desde v1.11.0

Cada entrada del calendario puede ser un **nivel en cm** o un **caudal en
m³/s**, a elección de quien programa. El servidor manda el valor con su unidad
(formato 3) y el equipo deja en `Modo` un `0` o un `1`. **La conversión no la
hace el servidor: la hace el programa del equipo**, que mide el nivel, calcula
el caudal con la curva de aforo (`RatingCurve`, §26) y compara según el modo.

```
Public Nivel_cm, Caudal_m3s, Consigna, Modo_Consigna, Error
Public Agenda_N, Agenda_Serie
PreserveVariables Consigna, Modo_Consigna
RatingCurve(Caudal_m3s, Nivel_cm, 0.015, 1.4991)
SetpointSchedule(Consigna, 1, Agenda_N, Agenda_Serie, Modo_Consigna)

    If (Modo_Consigna = 1) Then Error = Caudal_m3s - Consigna
    If (Modo_Consigna = 0) Then Error = Nivel_cm - Consigna
```

Con `Modo` en 1 la consigna son m³/s y el lazo compara contra `Caudal_m3s`; con
`Modo` en 0 son cm y compara contra `Nivel_cm`. Un calendario puede mezclar las
dos unidades. Hay que tener presente:

- **`Modo` se preserva igual que la consigna.** Si solo se preserva la consigna,
  tras un reinicio sin reloj sincronizado la consigna se recupera en m³/s pero el
  modo vuelve a 0 y un caudal se leería como centímetros. El linter lo avisa.
- **La banda muerta tiene unidad.** Una tolerancia de 1,5 cm no sirve para un
  caudal: en cada modo el lazo necesita su propia banda (en m³/s, del orden de
  la variación de caudal que produce 1,5 cm en la curva).
- **El ajuste manual del HMI no cambia el modo.** Si el operador escribe a mano
  la consigna mientras `Modo` vale 1, el número se interpreta como m³/s.


---

## 25. Sensores RS-485 Modbus RTU — `ModbusRTU` (extensión propia, desde v1.10.0)

```
ModbusBaud=9600
ModbusFormato=8N1
ModbusTimeout=250
ModbusRTU(Resultado, Primera_Var, Esclavo, Funcion, Inicio, Cantidad, Tipo, Intervalo_seg [, Mult [, Offset]])
```

El Opta hace de **maestro Modbus RTU** por su puerto RS-485 y deja lo que lee
en variables del programa. Es **solo lectura**: no escribe en el sensor.

```
ModbusBaud=9600
ModbusFormato=8N1
Public Res_Met
Public Viento, Direccion, Temp_aire, Humedad, Presion
Units Viento = m/s
Units Temp_aire = C

ModbusRTU(Res_Met, Viento, 1, 3, 0, 5, 0, 10)
```

Lee cinco valores `float32` desde el registro 0 del esclavo 1 (función 3,
registros de retención) cada 10 s, y los deja en `Viento`, `Direccion`,
`Temp_aire`, `Humedad` y `Presion`, en ese orden.

**Parámetros del bus** (directivas de configuración, como `ServerPort=`: no
gastan instrucciones y valen para todas las lecturas del programa):

| Directiva | Rango | Por defecto |
|---|---|---|
| `ModbusBaud=N` | 1200 a 115200 | 9600 |
| `ModbusFormato=F` | `8N1`, `8E1`, `8O1`, `8N2` | `8N1` |
| `ModbusTimeout=N` (ms) | 50 a 2000 | 250 |

Hay **un solo puerto**: todos los sensores del mismo cable tienen que hablar a
la misma velocidad y con el mismo formato. Un valor fuera de rango se registra
en el log y se usa el de por defecto.

**Argumentos de `ModbusRTU`.** `Esclavo` a `Offset` tienen que ser **números
literales o `Const`**, nunca variables: una variable movería la lectura de
sitio en pleno scan.

| Argumento | Qué es |
|---|---|
| `Resultado` | Variable donde queda el código de la lectura (ver abajo). |
| `Primera_Var` | Primera variable de datos. Las siguientes **declaradas a continuación** reciben los demás valores. |
| `Esclavo` | Dirección Modbus del sensor, 1 a 247. |
| `Funcion` | 1 bobinas, 2 entradas discretas, 3 registros de retención, 4 registros de entrada. |
| `Inicio` | Primer registro (o bit), 0 a 65535, tal como lo dice la tabla del sensor. |
| `Cantidad` | Cuántos **valores** leer, 1 a 32. Un `float32` ocupa dos registros pero es un solo valor. |
| `Tipo` | Cómo se interpretan los registros, 0 a 7 (tabla de abajo). |
| `Intervalo_seg` | Cada cuántos segundos leer, 1 a 86400. |
| `Mult`, `Offset` | Opcionales. Cada valor sale como `leído × Mult + Offset`. Por defecto 1 y 0. `Mult` no puede ser 0. |

| `Tipo` | Valor | Registros | Orden |
|---|---|---|---|
| 0 | `float32` | 2 | AB CD |
| 1 | `float32` | 2 | CD AB |
| 2 | `uint16` | 1 | — |
| 3 | `int16` | 1 | — |
| 4 | `uint32` | 2 | AB CD |
| 5 | `uint32` | 2 | CD AB |
| 6 | `int32` | 2 | AB CD |
| 7 | `int32` | 2 | CD AB |

Con las funciones 1 y 2 cada valor es **un bit** (0 o 1) y el `Tipo` se ignora.
«AB CD» es la palabra alta primero (lo habitual); «CD AB» la palabra baja
primero. Con el orden equivocado un `float` sale como un número enorme o `NAN`.

**Código de `Resultado`.**

| Valor | Significa |
|---|---|
| 0 | Lectura correcta. |
| 1 | El esclavo no contestó, o contestó un error Modbus. |
| 2 | La respuesta vino incompleta. |
| 3 | El puerto RS-485 no abrió. |

**Si la lectura falla, las variables de datos quedan en `NAN`**, nunca en el
último valor: un dato viejo parecería actual y se archivaría como si lo fuera.

> **Las variables no son un arreglo, son vecinas.** No hay arreglos en este
> CRBasic (§17): la lectura llena `Primera_Var` y las `Cantidad - 1` variables
> que están declaradas justo después. Si intercalas otra `Public` entre ellas, o
> las declaras en otro orden, cada valor termina en la variable equivocada y
> nada avisa. El IDE lista en un aviso exactamente cuáles va a llenar.

**Cuánto tarda y qué bloquea.** Cada transacción **detiene el ciclo** del
equipo mientras espera la respuesta, hasta `ModbusTimeout` ms si el sensor no
contesta. Para que eso no cueste un timeout en cada scan:

- se hace **una sola lectura por scan** como máximo, por turnos si hay varias;
- cada una se repite a su propio `Intervalo_seg`, no en cada scan;
- tras un fallo se **espacia**: el doble de espera cada vez, hasta 30 s (o el
  intervalo, si es mayor). Al primer éxito vuelve al ritmo normal.

Un Opta que además **acciona relés** (una compuerta) se frena ese tiempo cada
vez que el sensor no contesta. Para una compuerta conviene que el sensor RS-485
vaya en **otro Opta**; el IDE lo avisa cuando el programa tiene ambas cosas.

**Reglas.**

- Hasta **4** lecturas `ModbusRTU` por programa.
- Una variable no puede estar en dos lecturas, ni en una lectura y en otra
  instrucción (`SetpointSchedule`, `MedianRun`, un canal analógico...): se
  pisarían en cada scan.
- `Resultado` no puede ser una de las variables de datos.
- Las variables de una lectura **no se preservan** (`PreserveVariables`): el
  equipo las recalcula y preservarlas daría un valor viejo al arrancar.
- Una lectura **no gasta instrucciones** de las 128 (§16): es declarativa, como
  `MedianRun`. Gasta variables: una por valor más una por `Resultado`.
- Una asignación del programa a una variable de la lectura corre en cada scan
  y tapa lo leído; el linter lo avisa.

**Averiguar con qué formato contesta un sensor desconocido.** Por USB:

```
MODBUS SCAN <esclavo> <inicio> <registros> [<baud>]
```

Prueba `8N1`, `8E1`, `8N2` y `8O1` con las funciones 3 y 4, y devuelve los
primeros registros **crudos** de cada combinación que responde:

```
#D,MODBUS,OK,8N1,3,20,41B0 0000 42C8 0000 ...
#D,MODBUS,NO,8E1,3
#D,MODBUS,END
```

Con eso se decide `ModbusFormato`, `Funcion` y `Tipo`. Bloquea el equipo unos
2 s: no usarlo con una compuerta en movimiento.

**Lo que no hace.** No escribe en el sensor (funciones 5, 6 y 16), no habla
Modbus ASCII ni Modbus TCP, y no mezcla tipos de dato en una misma lectura: un
sensor con un `float` en el registro 0 y un entero en el registro 10 son dos
`ModbusRTU`.


---

## 26. Curva de aforo — `RatingCurve` (extensión propia, desde v1.11.0)

```
RatingCurve(Caudal, Nivel, a, b)
```

Calcula en cada scan `Caudal = a · Nivel^b`: la forma que ajusta una planilla
sobre la tabla de aforo de un río. El CRBasic del Opta **no tiene potencia**
(solo `Abs`, `Int` y `Sqr`), así que un exponente como 1,4991 no se puede
escribir con asignaciones; por eso existe esta instrucción.

```
Public Nivel_cm, Caudal_m3s
Units Nivel_cm = cm
Units Caudal_m3s = m3/s
RatingCurve(Caudal_m3s, Nivel_cm, 0.015, 1.4991)
```

Con la tabla de aforo de ejemplo (regla en cm, caudal en m³/s), 30 cm dan
2,457 m³/s y 60 cm dan 6,946 m³/s.

| Argumento | Qué es |
|---|---|
| `Caudal` | La variable donde queda el caudal. No puede ser la misma que `Nivel` ni recibir una asignación del programa: la curva corre antes y la asignación la pisaría. |
| `Nivel` | El nivel del río, en **la unidad con que se ajustó la curva** (cm si la regla de la tabla de aforo está en cm). |
| `a` | Coeficiente, mayor que 0 y hasta 1000000. **Número o `Const`, no una variable.** |
| `b` | Exponente, de 0,1 a 5. **Número o `Const`, no una variable.** |

**Cuándo corre.** Una vez por scan, después de las lecturas y de `MedianRun` y
**antes** de las asignaciones: el programa compara con el caudal de ese mismo
scan, calculado sobre el nivel ya filtrado. No gasta instrucciones (§16).

- **Nivel menor o igual a 0 da caudal 0.** La potencia de un negativo no existe
  y un aforo bajo cero no tiene sentido.
- **Un nivel `NAN` da `NAN`.** El caudal no puede ser más confiable que el nivel
  del que sale.
- **No se preserva.** Se recalcula en cada scan, así que `PreserveVariables` no
  lo acepta (igual que un sensor o una mediana).
- **Vale dentro del rango de la tabla de aforo.** Más allá del último punto
  medido es una extrapolación.
- **`a` y `b` son los de la curva ajustada.** Si la planilla redondeó el
  coeficiente (0,015 en vez de 0,01497), el caudal hereda ese error.

Junto con `SetpointSchedule` y su argumento `Modo` (§24) permite programar el
calendario en m³/s.
