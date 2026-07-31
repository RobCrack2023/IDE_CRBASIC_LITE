"""Lectura y escritura de .CR1 respetando su codificación original.

El CRBasic Editor de Campbell guarda en Windows-1252, así que un archivo
con acentos leído como UTF-8 se llena de U+FFFD y esa basura termina
subida al equipo. Acá se detecta la codificación real y se conserva al
guardar.
"""

CODIFICACIONES = ("utf-8-sig", "utf-8", "cp1252", "latin-1")


def leer(path: str) -> "tuple[str, str]":
    """Devuelve (texto, codificación_detectada)."""
    with open(path, "rb") as fh:
        data = fh.read()
    return decodificar(data)


def decodificar(data: bytes) -> "tuple[str, str]":
    for enc in CODIFICACIONES:
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    # latin-1 nunca falla, pero por las dudas.
    return data.decode("latin-1", errors="replace"), "latin-1"


def detectar_fin_de_linea(texto: str) -> str:
    """Devuelve el salto de línea predominante del archivo original.

    Los editores de texto de Qt normalizan todo a '\\n' al cargar, así que
    hay que acordarse del original para no reescribir el archivo entero
    con otro fin de línea al guardar. Al firmware le da igual (consume
    '\\n' y '\\r' por igual), pero a git y al autor no.
    """
    return "\r\n" if texto.count("\r\n") > texto.count("\n") - texto.count("\r\n") else "\n"


def aplicar_fin_de_linea(texto: str, eol: str) -> str:
    normalizado = texto.replace("\r\n", "\n").replace("\r", "\n")
    return normalizado.replace("\n", eol) if eol != "\n" else normalizado


def escribir(path: str, texto: str, encoding: str = "cp1252") -> None:
    """Guarda con la codificación original; cae a UTF-8 si algún carácter
    no entra en ella (por ejemplo un símbolo pegado desde el navegador)."""
    with open(path, "wb") as fh:
        fh.write(codificar(texto, encoding))


def codificar(texto: str, encoding: str = "cp1252") -> bytes:
    try:
        return texto.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return texto.encode("utf-8")
