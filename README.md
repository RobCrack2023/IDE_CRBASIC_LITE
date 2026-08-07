# IDE OptaBasic

Un programa para Windows que te ayuda a escribir los programas de las
estaciones Opta PLC, y te avisa de los errores **antes** de subirlos
al equipo.

## El problema que resuelve

Las estaciones Opta se programan con un archivo de texto `.CR1`, en un
lenguaje parecido al de los dataloggers CR1000. El equipo es muy
tolerante: si una línea no la entiende, la saltea y sigue andando como si
nada.

Eso suena cómodo pero es la peor parte. La estación arranca, se conecta,
manda datos... y resulta que la mitad del programa nunca se ejecutó. No
hay ningún cartel, ningún error: los números que llegan a la plataforma
son perfectamente creíbles y están mal.

Este IDE lee tu programa **igual que lo lee el equipo** y te muestra qué
va a pasar de verdad: qué líneas se van a ignorar, qué sensor se quedó sin
canal, qué cuenta va a dar cero. Todo en la pantalla, antes de subir nada.

## Instalación

Necesitás Python instalado. Después, una sola vez:

```bat
run.bat setup
```

## Cómo se usa

Doble clic en `run.bat` y se abre el editor. También podés arrastrarle un
archivo `.CR1` encima.

Desde la consola:

| Comando | Qué hace |
|---|---|
| `run.bat` | abre el editor |
| `run.bat programa.CR1` | abre el editor con ese archivo |
| `run.bat lint programa.CR1` | lo revisa y muestra el resultado en la consola |
| `run.bat setup` | instala lo que hace falta |
| `run.bat ayuda` | lista estas opciones |

## Un recorrido rápido

**1. Escribí el programa.** Si empezás de cero, el menú *Insertar* tiene
plantillas armadas: un programa completo, un sensor, un control de relé,
una tabla de datos.

**2. Mirá el panel de abajo mientras escribís.** Se actualiza solo:

- **Problemas** — todo lo que está mal o va a comportarse raro. Doble clic
  en un renglón y el cursor salta a esa línea.
- **Recursos** — cuánto espacio te queda. El equipo tiene topes de
  variables, tablas e instrucciones, y cuando te pasás descarta lo que
  sobra sin avisar.
- **Hardware** — qué sensor quedó en cada borne y qué variable maneja cada
  relé. Es la parte que no se ve leyendo el código.
- **Log del equipo** — lo que la estación va a anotar en su registro
  cuando cargue el programa.

**3. Si tenés un sensor, usá el asistente** (menú *Insertar*, o `Ctrl+M`).
Le cargás lo que dice la hoja de datos y qué resistencia hay en el
gabinete, y él saca las cuentas y escribe el código. Está explicado más
abajo.

**4. Subilo al equipo** con *Equipo → Enviar al equipo*. Se conecta al
servidor, elegís la estación de la lista y el programa queda cargado y
corriendo.

## El asistente de sensores

Es la parte más útil si armás estaciones.

Los sensores no entregan metros ni litros: entregan corriente o pulsos.
Para convertir eso a algo con sentido hay que calcular dos números
—`Mult` y `Offset`— y ahí es donde más se equivoca todo el mundo. Lo peor
es que un error acá no se nota: la estación reporta valores razonables que
simplemente no son los reales.

El asistente los calcula por vos, para dos tipos de sensor:

**Sensores de 4-20 mA** (nivel, presión, caudal). Le decís qué mide el
sensor —por ejemplo de 0 a 5 metros— y qué resistencia hay puesta en el
gabinete. Te da los números, te muestra qué resolución vas a conseguir, y
te avisa si la instalación directamente no puede funcionar: por ejemplo,
si con esa resistencia la señal se pasa de lo que la entrada aguanta y el
sensor nunca va a marcar el máximo.

**Contadores de pulsos** (pluviómetros, caudalímetros). Le decís cuánto
vale cada pulso y cuánto esperás medir como máximo, y te dice si el equipo
le da: no puede contar más de 20 pulsos por segundo. También te dibuja el
circuito de entrada y calcula si la tensión llega para que el contador
dispare, algo que es fácil de errar por medio voltio.

En los dos casos el código sale escrito y listo para insertar. Si algo no
va a funcionar, el botón de insertar queda deshabilitado.

## Ayuda mientras escribís

El lenguaje lo usa gente que instala sensores, no programadores, así que
la ayuda está pensada para no tener que acordarse de nada:

- **Al abrir un paréntesis** aparece un cartel que te dice qué va en cada
  lugar, y va siguiendo el dato que estás escribiendo.
- **Los datos que el equipo ignora aparecen marcados.** Varias
  instrucciones aceptan valores que después no usan para nada. Uno los
  escribe pensando que configuró algo y no configuró nada.
- **Ctrl+Espacio** lista lo que podés escribir, con una explicación al
  lado de cada opción. Tus propias variables aparecen con el borne que les
  tocó.
- **F1** sobre cualquier palabra abre su ficha completa.
- **La pestaña Referencia** tiene todas las instrucciones explicadas, con
  ejemplos que se insertan de un clic. Buscá por lo que querés hacer
  —"pluviómetro", "relé", "promedio"— y no por el nombre. Anda sin tildes.

## Atajos

| Tecla | Qué hace |
|---|---|
| `F5` | revisa el programa |
| `F9` | lo envía al equipo |
| `F1` | ayuda de la palabra donde está el cursor |
| `Ctrl+M` | asistente de sensores |
| `Ctrl+Espacio` | lista de instrucciones y variables |
| `Ctrl+S` | guardar |

## Para el que quiera el detalle

Cómo funciona el validador por dentro, qué comportamiento del equipo
justifica cada aviso y la matemática completa de los sensores están en
[NOTAS_TECNICAS.md](NOTAS_TECNICAS.md).

Resumen: el validador no adivina ni aproxima. Es el mismo algoritmo que
usa el firmware del equipo, reescrito en Python, con sus mismos límites y
sus mismas rarezas. Está calcado sobre la versión 1.6.12; si el firmware
cambia, hay que actualizarlo.
