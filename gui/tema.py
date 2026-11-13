"""Aspecto «Office moderno»: hoja de estilo clara y oscura, e íconos de glifo.

Una sola hoja de estilo para toda la aplicación, generada desde una paleta
chica. Así el diálogo del asistente, la cinta y los paneles quedan iguales
sin que cada widget lleve sus colores a cuestas (los que lo hacían, como el
detalle del panel de problemas, ahora se estilan por nombre de objeto desde
acá, para que el tema oscuro los alcance).

Los íconos salen de la fuente de íconos de Windows («Segoe Fluent Icons» en
Windows 11, «Segoe MDL2 Assets» en Windows 10), que ya está instalada: no
hace falta empaquetar imágenes dentro del .exe. Si la fuente no existe
(otro sistema), los botones quedan con su texto y nada más.
"""

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap

#: Colores del tema. «acento» es el azul de las aplicaciones de Office.
CLARO = {
    "app": "#f3f3f3", "superficie": "#ffffff", "borde": "#d1d1d1",
    "borde_campo": "#8a8a8a", "texto": "#242424", "suave": "#616161",
    "acento": "#0f6cbd", "acento_hover": "#115ea3", "acento_texto": "#ffffff",
    "seleccion": "#cfe4fa", "hover": "#e8e8e8", "presionado": "#dcdcdc",
    "deshabilitado": "#a6a6a6", "tarjeta": "#f7f7f7", "cinta": "#ffffff",
}
OSCURO = {
    "app": "#1f1f1f", "superficie": "#292929", "borde": "#3d3d3d",
    "borde_campo": "#8c8c8c", "texto": "#f0f0f0", "suave": "#adadad",
    "acento": "#479ef5", "acento_hover": "#62abf5", "acento_texto": "#0a0a0a",
    "seleccion": "#0f3a63", "hover": "#383838", "presionado": "#454545",
    "deshabilitado": "#6b6b6b", "tarjeta": "#242424", "cinta": "#2b2b2b",
}

_FUENTES_ICONOS = ("Segoe Fluent Icons", "Segoe MDL2 Assets")

#: Glifos de la fuente de íconos de Windows, por nombre de acción.
GLIFOS = {
    "Nuevo": "", "Abrir": "", "Guardar": "",
    "Guardar como": "", "Deshacer": "", "Rehacer": "",
    "Cortar": "", "Copiar": "", "Pegar": "",
    "Autocompletar": "", "Asistente de sensores": "",
    "Plantillas": "", "Validar programa": "",
    "Enviar al equipo": "", "Rescate por USB": "",
    "Alternar tema oscuro": "", "Ir a problemas": "",
    "Ir a recursos": "", "Ir a hardware": "",
    "Ir al log del equipo": "", "Ir a la referencia": "",
    "Referencia de instrucciones": "",
    "Ayuda de la palabra bajo el cursor": "",
    "Límites del dialecto": "", "Acerca de": "",
}


def fuente_de_iconos() -> "str | None":
    """Nombre de la fuente de íconos disponible, o None."""
    familias = set(QFontDatabase().families())
    return next((f for f in _FUENTES_ICONOS if f in familias), None)


def icono(glifo: str, color: str, tamano: int = 32) -> QIcon:
    """Ícono dibujado con la fuente de glifos; vacío si no hay fuente."""
    familia = fuente_de_iconos()
    if not familia or not glifo:
        return QIcon()
    pix = QPixmap(tamano, tamano)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.TextAntialiasing)
    fuente = QFont(familia)
    fuente.setPixelSize(int(tamano * 0.78))
    p.setFont(fuente)
    p.setPen(QColor(color))
    p.drawText(QRectF(0, 0, tamano, tamano), Qt.AlignCenter, glifo)
    p.end()
    return QIcon(pix)


def _flecha_combo(color: str) -> str:
    """Ruta de un PNG con una flechita hacia abajo, para el desplegable.

    La hoja de estilo no puede dibujar la flecha, y sin ella un QComboBox
    estilado no se ve como desplegable. Se escribe en la carpeta temporal.
    """
    import os
    import tempfile

    ruta = os.path.join(tempfile.gettempdir(), f"optabasic_flecha_{color[1:]}.png")
    if not os.path.exists(ruta):
        pix = QPixmap(12, 12)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        lapiz = p.pen()
        lapiz.setColor(QColor(color))
        lapiz.setWidthF(1.6)
        lapiz.setCapStyle(Qt.RoundCap)
        lapiz.setJoinStyle(Qt.RoundJoin)
        p.setPen(lapiz)
        p.drawPolyline(QPointF(2.5, 4.2), QPointF(6, 7.8), QPointF(9.5, 4.2))
        p.end()
        pix.save(ruta, "PNG")
    return ruta.replace("\\", "/")


def hoja_de_estilo(oscuro: bool) -> str:
    c = OSCURO if oscuro else CLARO
    flecha = _flecha_combo(c["suave"])
    return f"""
* {{ font-family: "Segoe UI Variable Text", "Segoe UI", sans-serif; }}
QWidget {{ font-size: 9pt; color: {c['texto']}; }}
QMainWindow, QDialog {{ background: {c['app']}; }}
QToolTip {{ background: {c['superficie']}; color: {c['texto']};
            border: 1px solid {c['borde']}; padding: 4px 6px; }}
QLabel {{ background: transparent; }}

QMenuBar {{ background: {c['app']}; }}
QMenuBar::item {{ padding: 5px 10px; background: transparent; border-radius: 4px; }}
QMenuBar::item:selected {{ background: {c['hover']}; }}
QMenu {{ background: {c['superficie']}; border: 1px solid {c['borde']};
         border-radius: 6px; padding: 4px; }}
QMenu::item {{ padding: 6px 28px 6px 12px; border-radius: 4px; }}
QMenu::item:selected {{ background: {c['hover']}; color: {c['texto']}; }}
QMenu::separator {{ height: 1px; background: {c['borde']}; margin: 4px 8px; }}

/* ── Cinta de opciones ───────────────────────────────────────────── */
#cintaPestanas::pane {{ border: none; border-top: 1px solid {c['borde']};
                        background: {c['cinta']}; }}
#cintaPestanas > QTabBar {{ background: {c['app']}; }}
#cintaPestanas QTabBar::tab {{ background: transparent; color: {c['suave']};
    padding: 6px 14px; margin: 0 2px; border: none; border-radius: 4px; }}
#cintaPestanas QTabBar::tab:hover {{ background: {c['hover']}; color: {c['texto']}; }}
#cintaPestanas QTabBar::tab:selected {{ color: {c['acento']}; font-weight: 600;
    border-bottom: 2px solid {c['acento']}; border-radius: 0; }}
#cintaPagina {{ background: {c['cinta']}; }}
#cintaTitulo {{ color: {c['suave']}; font-size: 8pt; }}
#cintaSeparador {{ background: {c['borde']}; }}
QToolButton#cintaBoton {{ background: transparent; border: 1px solid transparent;
    border-radius: 4px; padding: 4px 6px; color: {c['texto']}; }}
QToolButton#cintaBoton:hover {{ background: {c['hover']}; }}
QToolButton#cintaBoton:pressed {{ background: {c['presionado']}; }}
QToolButton#cintaBoton:checked {{ background: {c['seleccion']};
    border-color: {c['acento']}; }}
QToolButton#cintaBoton:disabled {{ color: {c['deshabilitado']}; }}
QToolButton#cintaBoton::menu-indicator {{ image: none; }}

/* ── Pestañas de los paneles ─────────────────────────────────────── */
QTabWidget::pane {{ border: none; border-top: 1px solid {c['borde']};
                    background: {c['superficie']}; }}
QTabBar::tab {{ background: transparent; color: {c['suave']};
                padding: 7px 14px; border: none; border-bottom: 2px solid transparent; }}
QTabBar::tab:hover {{ color: {c['texto']}; background: {c['hover']}; }}
QTabBar::tab:selected {{ color: {c['acento']}; font-weight: 600;
                         border-bottom: 2px solid {c['acento']}; }}

/* ── Botones y campos ────────────────────────────────────────────── */
QPushButton {{ background: {c['superficie']}; border: 1px solid {c['borde_campo']};
               border-radius: 4px; padding: 5px 14px; min-height: 18px; }}
QPushButton:hover {{ background: {c['hover']}; }}
QPushButton:pressed {{ background: {c['presionado']}; }}
QPushButton:default, QPushButton[primario="true"] {{
    background: {c['acento']}; color: {c['acento_texto']}; border-color: {c['acento']}; }}
QPushButton:default:hover, QPushButton[primario="true"]:hover {{
    background: {c['acento_hover']}; border-color: {c['acento_hover']}; }}
QPushButton:disabled {{ color: {c['deshabilitado']}; border-color: {c['borde']};
                        background: {c['app']}; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {c['superficie']}; border: 1px solid {c['borde_campo']};
    border-radius: 4px; padding: 4px 8px; min-height: 18px;
    selection-background-color: {c['acento']}; selection-color: {c['acento_texto']}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border: 1px solid {c['acento']}; border-bottom: 2px solid {c['acento']}; }}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{
    background: {c['app']}; color: {c['deshabilitado']}; border-color: {c['borde']}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url({flecha}); width: 12px; height: 12px; }}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; border: none; }}
QComboBox QAbstractItemView {{ background: {c['superficie']}; border: 1px solid {c['borde']};
    selection-background-color: {c['seleccion']}; selection-color: {c['texto']};
    outline: none; }}
QGroupBox {{ background: transparent; border: 1px solid {c['borde']};
             border-radius: 6px; margin-top: 14px; padding: 10px 8px 8px 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px;
                    color: {c['suave']}; font-weight: 600; }}
QProgressBar {{ background: {c['borde']}; border: none; border-radius: 4px;
                text-align: center; min-height: 8px; }}
QProgressBar::chunk {{ background: {c['acento']}; border-radius: 4px; }}

/* ── Listas, tablas y texto ──────────────────────────────────────── */
QPlainTextEdit, QTextEdit, QListView, QTreeView, QTableView {{
    background: {c['superficie']}; border: none; alternate-background-color: {c['tarjeta']};
    selection-background-color: {c['seleccion']}; selection-color: {c['texto']}; }}
QHeaderView::section {{ background: {c['tarjeta']}; color: {c['suave']}; border: none;
                        border-bottom: 1px solid {c['borde']}; padding: 5px 8px; }}
QTableView {{ gridline-color: {c['borde']}; }}
QDialog QPlainTextEdit {{ border: 1px solid {c['borde']}; border-radius: 4px; }}
#tarjeta {{ background: {c['tarjeta']}; border: 1px solid {c['borde']};
            border-radius: 6px; padding: 8px; }}
#detalle {{ background: {c['tarjeta']}; border-top: 1px solid {c['borde']};
            padding: 8px 12px; }}

/* ── Barras y divisores ──────────────────────────────────────────── */
QStatusBar {{ background: {c['app']}; border-top: 1px solid {c['borde']}; color: {c['suave']}; }}
QStatusBar QLabel {{ color: {c['suave']}; padding: 0 6px; }}
QSplitter::handle {{ background: {c['borde']}; }}
QSplitter::handle:vertical {{ height: 1px; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 0; }}
QScrollBar::handle {{ background: {c['borde_campo']}; border-radius: 4px; min-height: 28px; min-width: 28px;
                      margin: 2px; }}
QScrollBar::handle:hover {{ background: {c['suave']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
"""


#: Colores de los avisos (error, aviso, nota) en cada tema: los de siempre
#: en el claro y unos más luminosos en el oscuro, que si no no se leen.
_AVISOS = {
    False: {"error": "#cf222e", "aviso": "#9a6700", "nota": "#0969da"},
    True: {"error": "#ff7b72", "aviso": "#d29922", "nota": "#58a6ff"},
}


def actual() -> dict:
    """Paleta del tema que está aplicado en este momento."""
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance()
    return OSCURO if app is not None and app.property("oscuro") else CLARO


def color_aviso(nivel: str) -> str:
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance()
    oscuro = bool(app is not None and app.property("oscuro"))
    return _AVISOS[oscuro][nivel]


def aplicar(app, oscuro: bool) -> None:
    app.setProperty("oscuro", oscuro)
    app.setStyle("Fusion")
    app.setStyleSheet(hoja_de_estilo(oscuro))
