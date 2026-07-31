"""Punto de entrada del IDE OptaBasic.

    python main.py
    python main.py programa.CR1
"""

import sys


def main() -> int:
    try:
        from PyQt5.QtWidgets import QApplication
    except ImportError:
        print("Falta PyQt5. Instalalo con:  pip install PyQt5", file=sys.stderr)
        return 1

    from gui.main_window import VentanaPrincipal
    from optabasic.encoding import leer

    app = QApplication(sys.argv)
    app.setApplicationName("IDE OptaBasic")
    app.setOrganizationName("OptaBasic")

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

    ventana.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
