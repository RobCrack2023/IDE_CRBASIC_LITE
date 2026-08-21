"""Envío del programa al equipo a través del servidor LoggerNet alterno.

El Opta no acepta conexiones entrantes: es él quien disca al servidor. Por
eso el IDE no habla PakBus directamente, sino que usa la API del backend
(loggernet_AlternoCampbell), que ya mantiene la sesión con cada logger:

    POST /api/auth/login                          → token
    GET  /api/loggers                             → lista de equipos
    POST /api/loggers/{id}/files/upload?run_now=  → FileDownload + FileControl
"""

import requests
from PyQt5.QtCore import QObject, QSettings, QThread, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)


class ErrorLoggerNet(Exception):
    pass


class ClienteLoggerNet:
    """Cliente mínimo de la API del servidor."""

    def __init__(self, base_url: str, timeout: int = 30):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.token = ""

    def _cabeceras(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def _revisar(self, r, que: str):
        if r.status_code == 401:
            raise ErrorLoggerNet("Usuario o contraseña incorrectos, o la sesión venció.")
        if r.status_code == 403:
            raise ErrorLoggerNet("La cuenta no tiene permiso sobre ese equipo.")
        if not r.ok:
            detalle = ""
            try:
                detalle = r.json().get("detail", "")
            except Exception:
                detalle = r.text[:200]
            raise ErrorLoggerNet(f"{que}: HTTP {r.status_code}. {detalle}")

    def login(self, usuario: str, clave: str) -> str:
        try:
            r = requests.post(
                f"{self.base}/api/auth/login",
                data={"username": usuario, "password": clave},
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise ErrorLoggerNet(f"No se pudo llegar al servidor {self.base}: {e}") from e
        self._revisar(r, "Login")
        self.token = r.json().get("access_token", "")
        if not self.token:
            raise ErrorLoggerNet("El servidor no devolvió un token de acceso.")
        return self.token

    def loggers(self) -> "list[dict]":
        r = requests.get(f"{self.base}/api/loggers", headers=self._cabeceras(),
                         timeout=self.timeout)
        self._revisar(r, "Listar equipos")
        return r.json()

    def subir_programa(self, logger_id: int, nombre: str, contenido: bytes,
                       run_now: bool = True) -> dict:
        r = requests.post(
            f"{self.base}/api/loggers/{logger_id}/files/upload",
            params={"run_now": str(run_now).lower()},
            files={"file": (nombre, contenido, "application/octet-stream")},
            headers=self._cabeceras(),
            timeout=max(self.timeout, 120),
        )
        self._revisar(r, "Subir programa")
        return r.json()


class _Tarea(QObject):
    """Ejecuta una llamada de red fuera del hilo de la interfaz."""

    listo = pyqtSignal(object)
    fallo = pyqtSignal(str)

    def __init__(self, funcion):
        super().__init__()
        self.funcion = funcion

    def correr(self):
        try:
            self.listo.emit(self.funcion())
        except ErrorLoggerNet as e:
            self.fallo.emit(str(e))
        except Exception as e:  # red caída, DNS, timeout…
            self.fallo.emit(f"{type(e).__name__}: {e}")


class DialogoEnvio(QDialog):
    """Conectarse al servidor, elegir el equipo y subir el .CR1."""

    def __init__(self, contenido: bytes, nombre_archivo: str, parent=None):
        super().__init__(parent)
        self.contenido = contenido
        self.setWindowTitle("Enviar programa al equipo")
        self.setMinimumWidth(520)
        self.cliente: "ClienteLoggerNet | None" = None
        self._hilo: "QThread | None" = None
        self._tarea: "_Tarea | None" = None

        ajustes = QSettings("OptaBasic", "IDE")
        self.txt_url = QLineEdit(ajustes.value("servidor", "http://localhost:8000"))
        self.txt_usuario = QLineEdit(ajustes.value("usuario", ""))
        self.txt_clave = QLineEdit()
        self.txt_clave.setEchoMode(QLineEdit.Password)
        self.txt_clave.returnPressed.connect(self._conectar)

        self.btn_conectar = QPushButton("Conectar")
        self.btn_conectar.clicked.connect(self._conectar)

        self.cmb_logger = QComboBox()
        self.cmb_logger.setEnabled(False)
        self.chk_todos = QCheckBox("Mostrar equipos que no son Opta")
        self.chk_todos.setEnabled(False)
        self.chk_todos.stateChanged.connect(self._poblar_loggers)

        self.txt_nombre = QLineEdit(nombre_archivo)
        self.chk_run = QCheckBox("Compilar y ejecutar al subir (FileControl RunNow)")
        self.chk_run.setChecked(True)

        self.estado = QPlainTextEdit()
        self.estado.setReadOnly(True)
        self.estado.setFixedHeight(110)
        self.estado.setPlainText(
            f"{len(contenido)} bytes a enviar.\n"
            "Conectate al servidor para elegir el equipo de destino."
        )

        form = QFormLayout()
        fila_srv = QHBoxLayout()
        fila_srv.addWidget(self.txt_url, 1)
        fila_srv.addWidget(self.btn_conectar)
        form.addRow("Servidor", fila_srv)
        form.addRow("Usuario", self.txt_usuario)
        form.addRow("Contraseña", self.txt_clave)
        form.addRow("Equipo", self.cmb_logger)
        form.addRow("", self.chk_todos)
        form.addRow("Nombre destino", self.txt_nombre)
        form.addRow("", self.chk_run)

        self.botones = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.btn_enviar = self.botones.addButton("Enviar", QDialogButtonBox.AcceptRole)
        self.btn_enviar.setEnabled(False)
        self.botones.accepted.connect(self._enviar)
        self.botones.rejected.connect(self.reject)

        aviso = QLabel(
            "El archivo se guarda como CPU:&lt;nombre&gt; y, si marcás la casilla, el "
            "equipo lo compila y lo pone a correr de inmediato, reemplazando al "
            "programa actual."
        )
        aviso.setWordWrap(True)
        aviso.setStyleSheet("color: #9a6700;")

        caja = QVBoxLayout(self)
        caja.addLayout(form)
        caja.addWidget(aviso)
        caja.addWidget(self.estado)
        caja.addWidget(self.botones)

    # ── Utilidades ──────────────────────────────────────────────────────
    def _log(self, texto: str) -> None:
        self.estado.appendPlainText(texto)

    def _lanzar(self, funcion, al_terminar) -> None:
        self._bloquear(True)
        self._hilo = QThread(self)
        self._tarea = _Tarea(funcion)
        self._tarea.moveToThread(self._hilo)
        self._hilo.started.connect(self._tarea.correr)
        self._tarea.listo.connect(al_terminar)
        self._tarea.listo.connect(self._terminar_hilo)
        self._tarea.fallo.connect(self._al_fallar)
        self._tarea.fallo.connect(self._terminar_hilo)
        self._hilo.start()

    def _terminar_hilo(self, *_):
        if self._hilo is not None:
            self._hilo.quit()
            self._hilo.wait()
            self._hilo = None
            self._tarea = None
        self._bloquear(False)

    def _bloquear(self, ocupado: bool) -> None:
        self.btn_conectar.setEnabled(not ocupado)
        self.btn_enviar.setEnabled(not ocupado and self.cmb_logger.count() > 0)
        self.setCursor(Qt.WaitCursor if ocupado else Qt.ArrowCursor)

    def _al_fallar(self, mensaje: str) -> None:
        self._log(f"✖ {mensaje}")

    # ── Conexión ────────────────────────────────────────────────────────
    def _conectar(self) -> None:
        url = self.txt_url.text().strip()
        usuario = self.txt_usuario.text().strip()
        clave = self.txt_clave.text()
        if not url or not usuario:
            QMessageBox.warning(self, "Faltan datos",
                                "Indicá la dirección del servidor y el usuario.")
            return

        ajustes = QSettings("OptaBasic", "IDE")
        ajustes.setValue("servidor", url)
        ajustes.setValue("usuario", usuario)

        self.cliente = ClienteLoggerNet(url)
        self._log(f"Conectando a {url}…")

        def trabajo():
            self.cliente.login(usuario, clave)
            return self.cliente.loggers()

        self._lanzar(trabajo, self._al_conectar)

    def _al_conectar(self, loggers) -> None:
        self._todos = loggers
        self._log(f"✔ Conectado. {len(loggers)} equipos disponibles.")
        self.chk_todos.setEnabled(True)
        self.cmb_logger.setEnabled(True)
        self._poblar_loggers()

    def _poblar_loggers(self) -> None:
        if not hasattr(self, "_todos"):
            return
        mostrar_todos = self.chk_todos.isChecked()
        self.cmb_logger.clear()
        for lg in self._todos:
            if lg.get("is_archived"):
                continue
            es_opta = str(lg.get("model", "")).lower() == "opta"
            if not es_opta and not mostrar_todos:
                continue
            etiqueta = (f"{lg['name']}  ·  {lg.get('model', '?')}  ·  "
                        f"node {lg.get('node_id')}  ·  {lg.get('host', '')}")
            self.cmb_logger.addItem(etiqueta, lg["id"])
        if self.cmb_logger.count() == 0:
            self._log("No hay equipos Opta cargados. Marcá la casilla para ver el resto.")
        self.btn_enviar.setEnabled(self.cmb_logger.count() > 0)

    # ── Envío ───────────────────────────────────────────────────────────
    def _enviar(self) -> None:
        if self.cliente is None or self.cmb_logger.count() == 0:
            return
        logger_id = self.cmb_logger.currentData()
        nombre = self.txt_nombre.text().strip() or "programa.CR1"
        run_now = self.chk_run.isChecked()

        confirmar = QMessageBox.question(
            self,
            "Confirmar envío",
            f"Se va a subir «{nombre}» ({len(self.contenido)} bytes) a:\n\n"
            f"{self.cmb_logger.currentText()}\n\n"
            + ("El equipo lo compilará y lo pondrá a correr de inmediato, "
               "reemplazando el programa que esté ejecutando.\n\n" if run_now else "")
            + "¿Continuar?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirmar != QMessageBox.Yes:
            return

        self._log(f"Subiendo «{nombre}» ({len(self.contenido)} bytes)…")
        self._lanzar(
            lambda: self.cliente.subir_programa(logger_id, nombre, self.contenido, run_now),
            self._al_enviar,
        )

    def _al_enviar(self, respuesta: dict) -> None:
        self._log(
            f"✔ Enviado como {respuesta.get('filename')} "
            f"({respuesta.get('size')} bytes). "
            f"FileDownload={respuesta.get('download_resp')}, "
            f"RunNow={respuesta.get('run_resp')}"
        )
        # El equipo puede cortar la conexión justo al aplicar el programa, si
        # este le cambia la configuración de red. No es un fallo —el programa ya
        # está cargado— pero conviene decirlo, porque el equipo queda unos
        # segundos sin responder y desde afuera parece que algo salió mal.
        aviso = ""
        if respuesta.get("reconnecting"):
            aviso = (
                "\n\nEl equipo reinició su conexión al aplicarlo, así que no "
                "alcanzó a confirmar el arranque. Es lo esperado cuando el "
                "programa cambia ServerHost, ServerPort o PakBusAddress: vuelve "
                "a llamar solo en unos segundos. No hace falta subirlo de nuevo."
            )
            self._log("  El equipo esta reconectando — el programa ya quedo cargado.")
        QMessageBox.information(
            self,
            "Programa enviado",
            f"El programa quedó cargado como {respuesta.get('filename')}."
            + aviso
            + "\n\nConviene revisar el .HLOG del equipo para ver si descartó "
              "alguna línea.",
        )

    def reject(self):
        self._terminar_hilo()
        super().reject()
