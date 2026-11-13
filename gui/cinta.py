"""Cinta de opciones al estilo de Office.

No define acciones propias: agrupa en pestañas las que ya existen en la
ventana (las mismas de los menús y los atajos), así que un botón de la cinta
y su atajo de teclado siempre hacen lo mismo.

Doble clic en una pestaña pliega la cinta para dejar más lugar al editor, y
otro doble clic la despliega, igual que en Office.
"""

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import tema


def _limpio(texto: str) -> str:
    return texto.replace("&", "").replace("…", "").strip()


class Cinta(QTabWidget):
    ALTO = 96

    def __init__(self, acciones: dict, parent=None):
        """`acciones` es {nombre sin & ni «…»: QAction} de la ventana."""
        super().__init__(parent)
        self.setObjectName("cintaPestanas")
        self.setDocumentMode(True)
        self.acciones = acciones
        self._botones = []               # (boton, nombre) para repintar íconos
        self._plegada = False
        self.tabBarDoubleClicked.connect(self._alternar_pliegue)
        self.tabBar().setExpanding(False)

    # ── Armado ──────────────────────────────────────────────────────────
    def pagina(self, titulo: str) -> "_Pagina":
        p = _Pagina(self)
        self.addTab(p, titulo)
        return p

    def boton(self, nombre: str, grande: bool = True, menu: QMenu = None,
              texto: str = None) -> QToolButton:
        """Botón de la acción `nombre`, o de un menú desplegable si `menu`."""
        b = QToolButton()
        b.setObjectName("cintaBoton")
        b.setAutoRaise(True)
        if menu is not None:
            b.setText(texto or nombre)
            b.setMenu(menu)
            b.setPopupMode(QToolButton.InstantPopup)
        else:
            a = self.acciones[nombre]
            b.setDefaultAction(a)
            b.setText(_limpio(a.text()))
            b.setToolTip(self._ayuda(a))
        if grande:
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setIconSize(QSize(30, 30))
            b.setMinimumWidth(66)
            b.setFixedHeight(self.ALTO - 24)
        else:
            b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            b.setIconSize(QSize(16, 16))
            b.setMinimumWidth(96)
        self._botones.append((b, nombre))
        self.repintar_iconos()
        return b

    @staticmethod
    def _ayuda(accion) -> str:
        atajo = accion.shortcut().toString()
        tip = accion.statusTip()
        titulo = _limpio(accion.text()) + (f"  ({atajo})" if atajo else "")
        return f"{titulo}\n{tip}" if tip else titulo

    # ── Tema ────────────────────────────────────────────────────────────
    def repintar_iconos(self, oscuro: bool = None) -> None:
        if oscuro is not None:
            self._oscuro = oscuro
        color = tema.OSCURO["acento"] if getattr(self, "_oscuro", False) \
            else tema.CLARO["acento"]
        for boton, nombre in self._botones:
            ic = tema.icono(tema.GLIFOS.get(nombre, ""), color)
            if not ic.isNull():
                boton.setIcon(ic)

    # ── Pliegue ─────────────────────────────────────────────────────────
    def _alternar_pliegue(self, _indice: int) -> None:
        self._plegada = not self._plegada
        self._ajustar_alto()

    def _ajustar_alto(self) -> None:
        barra = self.tabBar().sizeHint().height()
        self.setFixedHeight(barra + 2 if self._plegada else barra + self.ALTO + 8)

    def showEvent(self, evento):
        super().showEvent(evento)
        self._ajustar_alto()


class _Pagina(QWidget):
    """Una pestaña de la cinta: grupos de botones con su título abajo."""

    def __init__(self, cinta: Cinta):
        super().__init__()
        self.cinta = cinta
        self.setObjectName("cintaPagina")
        self._fila = QHBoxLayout(self)
        self._fila.setContentsMargins(8, 4, 8, 2)
        self._fila.setSpacing(0)
        self._fila.addStretch(1)

    def grupo(self, titulo: str) -> "_Grupo":
        if self._fila.count() > 1:
            sep = QFrame()
            sep.setObjectName("cintaSeparador")
            sep.setFixedWidth(1)
            self._fila.insertWidget(self._fila.count() - 1, sep)
        g = _Grupo(titulo)
        self._fila.insertWidget(self._fila.count() - 1, g)
        return g


class _Grupo(QWidget):
    def __init__(self, titulo: str):
        super().__init__()
        caja = QVBoxLayout(self)
        caja.setContentsMargins(8, 0, 8, 0)
        caja.setSpacing(2)
        self.botones = QHBoxLayout()
        self.botones.setSpacing(2)
        caja.addLayout(self.botones, 1)
        etiqueta = QLabel(titulo)
        etiqueta.setObjectName("cintaTitulo")
        etiqueta.setAlignment(Qt.AlignCenter)
        caja.addWidget(etiqueta)

    def agregar(self, boton: QToolButton) -> None:
        self.botones.addWidget(boton)

    def agregar_columna(self, botones: "list[QToolButton]") -> None:
        """Botones chicos apilados, como el Cortar/Copiar/Pegar de Office."""
        col = QWidget()
        g = QGridLayout(col)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(0)
        for i, b in enumerate(botones):
            g.addWidget(b, i, 0)
        self.botones.addWidget(col)
