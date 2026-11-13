"""Punto de entrada del IDE OptaBasic.

    python main.py
    python main.py programa.CR1
"""

import sys
import time

#: Tiempo mínimo que se ve el splash, en segundos.
SPLASH_MIN_SEG = 4.0


def _crear_splash():
    """Pantalla de inicio dibujada en código, sin archivos de imagen.

    El .exe es un solo archivo sin 'datas', así que no se puede apoyar en
    una imagen externa.
    """
    from PyQt5.QtCore import QRectF, Qt
    from PyQt5.QtGui import QColor, QFont, QPainter, QPixmap
    from PyQt5.QtWidgets import QSplashScreen

    from optabasic import __version__

    ancho, alto = 520, 300
    pix = QPixmap(ancho, alto)
    pix.fill(QColor("#1f2328"))
    p = QPainter(pix)
    p.setRenderHint(QPainter.TextAntialiasing)

    p.fillRect(0, 0, 8, alto, QColor("#0969da"))          # franja lateral

    def texto(y, h, contenido, fuente, color):
        p.setFont(fuente)
        p.setPen(QColor(color))
        p.drawText(QRectF(36, y, ancho - 60, h),
                   Qt.AlignLeft | Qt.AlignVCenter, contenido)

    texto(52, 56, "IDE OptaBasic", QFont("Segoe UI", 28, QFont.Bold), "#ffffff")
    texto(110, 28, "Editor y verificador de programas CRBasic para el Opta",
          QFont("Segoe UI", 10), "#9da7b3")
    texto(150, 30, f"Versión {__version__}", QFont("Segoe UI", 14, QFont.DemiBold),
          "#58a6ff")
    texto(182, 24, "Motor calcado sobre el firmware OptaPakBus de la misma versión",
          QFont("Segoe UI", 9), "#9da7b3")
    p.fillRect(36, 218, ancho - 72, 1, QColor("#30363d"))   # separador
    texto(228, 28, "Ingeniería y Proyecto Ltda.", QFont("Segoe UI", 11, QFont.DemiBold),
          "#ffffff")
    texto(262, 24, "Cargando…", QFont("Segoe UI", 9), "#6e7781")
    p.end()

    return QSplashScreen(pix, Qt.WindowStaysOnTopHint)


def main() -> int:
    try:
        from PyQt5.QtWidgets import QApplication
    except ImportError:
        print("Falta PyQt5. Instalalo con:  pip install PyQt5", file=sys.stderr)
        return 1

    app = QApplication(sys.argv)
    app.setApplicationName("IDE OptaBasic")
    app.setOrganizationName("OptaBasic")

    # El splash sale antes de cargar la ventana: es lo que tarda en un .exe
    # de un solo archivo, y sin esto no se ve nada por varios segundos.
    inicio = time.monotonic()
    splash = _crear_splash()
    splash.show()
    app.processEvents()

    from gui.main_window import VentanaPrincipal
    from optabasic.encoding import leer

    ventana = VentanaPrincipal()

    if len(sys.argv) > 1:
        ruta = sys.argv[1]
        try:
            texto, enc = leer(ruta)
        except OSError as e:
            print(f"No se pudo abrir {ruta}: {e}", file=sys.stderr)
        else:
            ventana.ruta = ruta
            ventana.codificacion = enc
            ventana.lbl_codificacion.setText(enc)
            ventana.editor.setPlainText(texto)
            ventana.editor.document().setModified(False)
            ventana.analizar()
            ventana._actualizar_titulo()

    # Que se alcance a leer aunque la carga haya sido instantánea.
    while time.monotonic() - inicio < SPLASH_MIN_SEG:
        app.processEvents()
        time.sleep(0.02)
    ventana.show()
    splash.finish(ventana)
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
