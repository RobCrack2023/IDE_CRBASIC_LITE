"""Panel de referencia: qué hace cada instrucción y para qué es cada argumento."""

import unicodedata

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from optabasic.reference import CATEGORIAS, buscar, por_categoria


class PanelReferencia(QWidget):
    """Listado por categorías con la ficha completa de cada instrucción."""

    insertar_ejemplo = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.busqueda = QLineEdit()
        self.busqueda.setPlaceholderText(
            "Buscar…  (probá «relé», «promedio», «4-20», «pluviómetro»)"
        )
        self.busqueda.setClearButtonEnabled(True)
        self.busqueda.textChanged.connect(self._filtrar)

        self.arbol = QTreeWidget()
        self.arbol.setHeaderHidden(True)
        self.arbol.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.arbol.currentItemChanged.connect(self._al_seleccionar)
        self.arbol.setMinimumWidth(240)

        self.ficha = QTextBrowser()
        self.ficha.setOpenExternalLinks(False)

        self.btn_insertar = QPushButton("Insertar el ejemplo en el programa")
        self.btn_insertar.setEnabled(False)
        self.btn_insertar.clicked.connect(self._insertar)

        izquierda = QWidget()
        caja_izq = QVBoxLayout(izquierda)
        caja_izq.setContentsMargins(6, 6, 3, 6)
        caja_izq.setSpacing(6)
        caja_izq.addWidget(self.busqueda)
        caja_izq.addWidget(self.arbol)

        derecha = QWidget()
        caja_der = QVBoxLayout(derecha)
        caja_der.setContentsMargins(3, 6, 6, 6)
        caja_der.setSpacing(6)
        caja_der.addWidget(self.ficha)
        fila = QHBoxLayout()
        fila.addStretch(1)
        fila.addWidget(self.btn_insertar)
        caja_der.addLayout(fila)

        divisor = QSplitter(Qt.Horizontal)
        divisor.addWidget(izquierda)
        divisor.addWidget(derecha)
        divisor.setStretchFactor(0, 1)
        divisor.setStretchFactor(1, 2)

        caja = QVBoxLayout(self)
        caja.setContentsMargins(0, 0, 0, 0)
        caja.addWidget(divisor)

        self._poblar()
        self._mostrar_portada()

    # ── Árbol ───────────────────────────────────────────────────────────
    def _poblar(self) -> None:
        self.arbol.clear()
        negrita = QFont()
        negrita.setBold(True)
        for categoria in CATEGORIAS:
            padre = QTreeWidgetItem([categoria])
            padre.setFont(0, negrita)
            padre.setFlags(Qt.ItemIsEnabled)
            for instr in por_categoria(categoria):
                hijo = QTreeWidgetItem([instr.nombre])
                hijo.setData(0, Qt.UserRole, instr.nombre)
                hijo.setToolTip(0, instr.resumen)
                padre.addChild(hijo)
            self.arbol.addTopLevelItem(padre)
        self.arbol.expandAll()

    def _filtrar(self, texto: str) -> None:
        aguja = _plano(texto.strip())
        for i in range(self.arbol.topLevelItemCount()):
            padre = self.arbol.topLevelItem(i)
            visibles = 0
            for j in range(padre.childCount()):
                hijo = padre.child(j)
                instr = buscar(hijo.data(0, Qt.UserRole))
                if not aguja:
                    coincide = True
                else:
                    bolsa = _plano(" ".join([
                        instr.nombre, instr.resumen, instr.detalle,
                        instr.trampa, instr.categoria, instr.ejemplo,
                        " ".join(p.nombre + " " + p.descripcion for p in instr.parametros),
                    ]))
                    coincide = all(palabra in bolsa for palabra in aguja.split())
                hijo.setHidden(not coincide)
                visibles += int(coincide)
            padre.setHidden(visibles == 0)

    def _al_seleccionar(self, item, _anterior) -> None:
        nombre = item.data(0, Qt.UserRole) if item else None
        if not nombre:
            return
        self.mostrar(nombre)

    # ── Ficha ───────────────────────────────────────────────────────────
    def mostrar(self, nombre: str) -> bool:
        """Muestra la ficha de una instrucción. Devuelve si la encontró."""
        instr = buscar(nombre)
        if instr is None:
            return False

        self._actual = instr
        self.btn_insertar.setEnabled(bool(instr.ejemplo))

        partes = [
            _ESTILO,
            f"<h2>{instr.nombre}</h2>",
            f"<p class='resumen'>{instr.resumen}</p>",
            f"<pre class='firma'>{instr.firma}</pre>",
        ]
        if instr.detalle:
            partes.append(f"<p>{instr.detalle.replace(chr(10) * 2, '</p><p>')}</p>")

        if instr.parametros:
            partes.append("<h3>Argumentos</h3><table>")
            for p in instr.parametros:
                etiquetas = []
                if p.ignorado:
                    etiquetas.append("<span class='ign'>el Opta lo ignora</span>")
                if p.opcional:
                    etiquetas.append("<span class='opc'>opcional</span>")
                sufijo = (" " + " ".join(etiquetas)) if etiquetas else ""
                partes.append(
                    f"<tr><td class='par'>{p.nombre}</td>"
                    f"<td>{p.descripcion}{sufijo}</td></tr>"
                )
            partes.append("</table>")

        if instr.ejemplo:
            partes.append("<h3>Ejemplo</h3>")
            partes.append(f"<pre class='ej'>{_escapar(instr.ejemplo)}</pre>")

        if instr.trampa:
            texto = instr.trampa.replace(chr(10) * 2, "<br><br>")
            partes.append(
                f"<div class='trampa'><b>Ojo con esto</b><br>{texto}</div>"
            )

        self.ficha.setHtml("".join(partes))
        self.ficha.verticalScrollBar().setValue(0)

        # Dejar seleccionada la entrada correspondiente en el árbol.
        for i in range(self.arbol.topLevelItemCount()):
            padre = self.arbol.topLevelItem(i)
            for j in range(padre.childCount()):
                hijo = padre.child(j)
                if hijo.data(0, Qt.UserRole) == instr.nombre:
                    if self.arbol.currentItem() is not hijo:
                        self.arbol.blockSignals(True)
                        self.arbol.setCurrentItem(hijo)
                        self.arbol.blockSignals(False)
                    return True
        return True

    def _mostrar_portada(self) -> None:
        self.ficha.setHtml(
            _ESTILO
            + "<h2>Referencia de instrucciones</h2>"
            "<p class='resumen'>Elegí una instrucción de la lista, o buscá por lo "
            "que querés hacer.</p>"
            "<p>Este lenguaje es un subconjunto reducido del CRBasic de Campbell: "
            "el equipo acepta muchas instrucciones por compatibilidad pero solo "
            "usa parte de sus argumentos. Los que no usa están marcados en cada "
            "ficha, porque un argumento que no hace nada engaña más que uno que "
            "falta.</p>"
            "<h3>Atajos</h3>"
            "<table>"
            "<tr><td class='par'>F1</td><td>abre acá la ficha de la palabra "
            "donde esté el cursor</td></tr>"
            "<tr><td class='par'>Ctrl+Espacio</td><td>lista las instrucciones y "
            "variables que podés escribir</td></tr>"
            "<tr><td class='par'>(</td><td>al abrir un paréntesis aparece la ayuda "
            "que va siguiendo cada argumento</td></tr>"
            "</table>"
        )

    def _insertar(self) -> None:
        if getattr(self, "_actual", None) and self._actual.ejemplo:
            self.insertar_ejemplo.emit(self._actual.ejemplo + "\n")


def _plano(texto: str) -> str:
    """Minúsculas y sin tildes, para que «pluviometro» encuentre «pluviómetro».

    Quien escribe el programa está apurado y en el teclado de la máquina de
    la estación; exigirle la tilde exacta para encontrar una instrucción es
    una forma tonta de que no encuentre nada.
    """
    descompuesto = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")


def _escapar(texto: str) -> str:
    return texto.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


_ESTILO = """
<style>
  body   { font-family: 'Segoe UI', sans-serif; font-size: 10.5pt; color: #24292f; }
  h2     { margin: 2px 0 4px 0; font-size: 15pt; color: #0550ae; }
  h3     { margin: 16px 0 4px 0; font-size: 11pt; color: #57606a; }
  p      { margin: 6px 0; line-height: 145%; }
  .resumen { color: #57606a; font-size: 11pt; margin-bottom: 10px; }
  .firma { background: #f6f8fa; border: 1px solid #d8dee4; border-radius: 4px;
           padding: 8px; font-family: Consolas, monospace; font-size: 10pt;
           color: #0550ae; }
  .ej    { background: #f6f8fa; border-left: 3px solid #0969da; padding: 8px;
           font-family: Consolas, monospace; font-size: 10pt; }
  table  { border-collapse: collapse; margin: 4px 0; }
  td     { padding: 4px 10px 4px 0; vertical-align: top; line-height: 140%; }
  .par   { font-family: Consolas, monospace; color: #8250df; white-space: nowrap;
           font-weight: bold; }
  .ign   { color: #bc4c00; font-style: italic; }
  .opc   { color: #57606a; font-style: italic; }
  .trampa { background: #fff8c5; border-left: 4px solid #d4a72c; padding: 10px;
            margin-top: 16px; line-height: 145%; }
</style>
"""
