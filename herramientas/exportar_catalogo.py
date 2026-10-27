#!/usr/bin/env python3
"""Exporta el catálogo de instrucciones a JSON, para el editor web.

El editor de `.CR1` del proyecto LoggerNet Alterno muestra la misma ayuda que
el panel de referencia de este IDE, pero corre en el navegador. En vez de
mantener dos copias del texto —que es como el linter y el manual se
desfasaron del firmware más de una vez— el catálogo se genera desde acá.

    python herramientas/exportar_catalogo.py \
        ../loggernet_AlternoCampbell/frontend/src/catalogoCrbasic.json

Sin argumento escribe en la salida estándar, para poder revisar el resultado
antes de pisar nada.
"""

import json
import os
import sys
from dataclasses import asdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from optabasic import limits as L  # noqa: E402
from optabasic.reference import CATALOGO, CATEGORIAS  # noqa: E402


def exportar() -> dict:
    """El catálogo completo, tal cual lo consume el editor web."""
    return {
        # Contra qué firmware está calcado lo que se exporta. El editor lo
        # muestra para que se note de un vistazo si quedó viejo.
        "firmware": L.FIRMWARE_VERSION,
        "generadoPor": "ide_optabasic/herramientas/exportar_catalogo.py",
        "categorias": CATEGORIAS,
        "instrucciones": [
            {
                "nombre": i.nombre,
                "firma": i.firma,
                "resumen": i.resumen,
                "categoria": i.categoria,
                "detalle": i.detalle,
                "ejemplo": i.ejemplo,
                "trampa": i.trampa,
                "usaParentesis": i.usa_parentesis,
                "firmaPartes": i.firma_partes(),
                "parametros": [asdict(p) for p in i.parametros],
            }
            for i in CATALOGO
        ],
    }


def main() -> int:
    datos = exportar()
    texto = json.dumps(datos, ensure_ascii=False, indent=2) + "\n"

    if len(sys.argv) < 2:
        sys.stdout.write(texto)
        return 0

    destino = sys.argv[1]
    with open(destino, "w", encoding="utf-8", newline="\n") as f:
        f.write(texto)
    print(
        f"{len(datos['instrucciones'])} instrucciones "
        f"(firmware {datos['firmware']}) → {destino}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
