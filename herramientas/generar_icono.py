"""Genera icono.ico para el ejecutable.

Se dibuja por codigo en vez de guardar un binario suelto en el repo, asi
queda claro de donde salio y se puede retocar. El .ico se arma a mano
juntando PNGs: el formato es una cabecera corta seguida de las imagenes,
y Windows acepta PNG adentro desde Vista.

    python herramientas/generar_icono.py
"""

import os
import struct
import sys

from PyQt5.QtCore import QBuffer, QByteArray, QPointF, QRectF, Qt
from PyQt5.QtGui import (
    QBrush,
    QColor,
    QFont,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PyQt5.QtWidgets import QApplication

TAMANOS = [16, 24, 32, 48, 64, 128, 256]
DESTINO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "icono.ico")


def dibujar(lado: int) -> QImage:
    """Un cuadrado redondeado azul con una senal de pulsos encima.

    La onda cuadrada es lo que mejor representa lo que hace el programa y
    sigue siendo legible en 16 pixeles, donde un texto ya no se lee.
    """
    img = QImage(lado, lado, QImage.Format_ARGB32)
    img.fill(Qt.transparent)

    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)

    # Fondo: cuadrado redondeado con un degrade suave.
    margen = lado * 0.04
    radio = lado * 0.22
    fondo = QLinearGradient(0, 0, 0, lado)
    fondo.setColorAt(0.0, QColor("#1f6feb"))
    fondo.setColorAt(1.0, QColor("#0a3a86"))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(fondo))
    p.drawRoundedRect(QRectF(margen, margen, lado - 2 * margen, lado - 2 * margen),
                      radio, radio)

    # Senal de pulsos: dos flancos, que es lo que cuenta el equipo.
    trazo = max(1.0, lado * 0.085)
    p.setPen(QPen(QColor("#ffffff"), trazo, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)

    alto = lado * 0.20          # nivel alto de la onda
    bajo = lado * 0.66          # nivel bajo
    x0 = lado * 0.20
    x1 = lado * 0.80
    ancho = x1 - x0

    onda = QPainterPath()
    onda.moveTo(QPointF(x0, bajo))
    onda.lineTo(QPointF(x0 + ancho * 0.22, bajo))
    onda.lineTo(QPointF(x0 + ancho * 0.22, alto))
    onda.lineTo(QPointF(x0 + ancho * 0.55, alto))
    onda.lineTo(QPointF(x0 + ancho * 0.55, bajo))
    onda.lineTo(QPointF(x0 + ancho * 0.78, bajo))
    onda.lineTo(QPointF(x0 + ancho * 0.78, alto))
    onda.lineTo(QPointF(x1, alto))
    p.drawPath(onda)

    # Base: la linea del cero, mas fina.
    if lado >= 32:
        p.setPen(QPen(QColor(255, 255, 255, 110), max(1.0, trazo * 0.5),
                      Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(x0, lado * 0.82), QPointF(x1, lado * 0.82))

    p.end()
    return img


def png_de(img: QImage) -> bytes:
    datos = QByteArray()
    buf = QBuffer(datos)
    buf.open(QBuffer.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(datos)


def armar_ico(imagenes: "list[bytes]", lados: "list[int]") -> bytes:
    """ICONDIR + una ICONDIRENTRY por imagen + los PNG concatenados."""
    n = len(imagenes)
    cabecera = struct.pack("<HHH", 0, 1, n)          # reservado, tipo=icono, cantidad
    entradas = b""
    desplazamiento = 6 + 16 * n
    for lado, png in zip(lados, imagenes):
        entradas += struct.pack(
            "<BBBBHHII",
            0 if lado >= 256 else lado,   # ancho (0 significa 256)
            0 if lado >= 256 else lado,   # alto
            0,                            # colores de la paleta
            0,                            # reservado
            1,                            # planos
            32,                           # bits por pixel
            len(png),
            desplazamiento,
        )
        desplazamiento += len(png)
    return cabecera + entradas + b"".join(imagenes)


def main() -> int:
    app = QApplication(sys.argv)   # noqa: F841 - QPainter necesita una QApplication
    pngs = [png_de(dibujar(lado)) for lado in TAMANOS]
    with open(DESTINO, "wb") as fh:
        fh.write(armar_ico(pngs, TAMANOS))
    print(f"{DESTINO}  ({os.path.getsize(DESTINO)} bytes, "
          f"{len(TAMANOS)} tamanos: {', '.join(str(t) for t in TAMANOS)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
