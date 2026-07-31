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

Todas verificadas contra `OptaPakBus.ino`; entre paréntesis, la línea.

| Qué pasa | Por qué |
|---|---|
| **Sin `DataTable` el programa no se ejecuta** | `crParsed = (crTableCount > 0)` (2967); en `loop()` (4405) el equipo cae al esquema fijo AI1-AI4/DI1-DI4/DO1-DO4/BattV e ignora todo el `.CR1` |
| **Una asignación suelta indentada se descarta** | el destino se lee desde la columna 0 (2452) y `cr_find_var()` compara el nombre exacto (506). Las que van dentro de un `If … Then` se salvan porque su destino sale del texto posterior al `Then` |
| **`Units=mA` + asignación = variable sin canal** | `noAutoPin` solo se revierte para `hasVoltInstr` (2917) |
| **Un canal pedido a mano se puede repartir dos veces** | `used[]` arranca vacío y nunca marca los canales explícitos ni los de `PulseCount` (2920) |
| **`Msec` se interpreta como segundos** | `cr_to_sec()` solo conoce MIN/HOU/DAY (2051); `Scan(500, Msec)` son 500 s |
| **`att` en el nombre + `Units=mA` pierde el A7** | la rama de batería excluye `is4_20mA` (2924) |
| **`VoltDiff`/`VoltSE` con menos de 6 argumentos ignora Mult/Offset** | (2732) |
| **Tabla sin `DataInterval` nunca archiva** | `if (tbl->intervalSec > 0)` (3168) |
| **`Public`/`Dim`/`Units` con sangría** | offsets fijos desde la columna 0 (2598, 2631). `Const` sí tolera sangría (2510) |
| **Truncados silenciosos** | línea a 127 caracteres, programa a 8192 bytes, argumento a 31, nombre de variable a 23 |

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
  expr.py        cr_compile_expr (Shunting-Yard) y el conteo de tokens RPN
  parser.py      parse_crbasic() completo
  lint.py        las reglas propias del IDE
  model.py       Program, Var, Const, Table, Field, Stmt
  encoding.py    cp1252 / UTF-8 y fin de línea, sin corromper acentos
gui/             interfaz PyQt5
cli.py           linter de consola
tests/           55 pruebas ancladas al firmware
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
