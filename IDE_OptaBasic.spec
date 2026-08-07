# -*- mode: python ; coding: utf-8 -*-
"""Receta de PyInstaller para generar el ejecutable de Windows.

Se arma un solo .exe para poder pasarlo por pendrive o por mail sin
carpetas ni instalador. A cambio, el arranque es un poco mas lento que
una instalacion normal: Windows tiene que descomprimirlo en un temporal
la primera vez.

    run.bat exe

El IDE no lee ningun archivo de datos externo (las plantillas y el
catalogo de instrucciones son modulos de Python), asi que no hace falta
declarar 'datas'.
"""

# PyQt5 trae muchisimos modulos que este programa no usa. Sacarlos baja el
# tamano del ejecutable a menos de la mitad. Si alguna vez algo falla al
# arrancar con un ImportError de Qt, el culpable esta en esta lista.
QT_SIN_USO = [
    "PyQt5.QtWebEngineWidgets", "PyQt5.QtWebEngineCore", "PyQt5.QtWebEngine",
    "PyQt5.QtWebChannel", "PyQt5.QtWebSockets", "PyQt5.QtQml", "PyQt5.QtQuick",
    "PyQt5.QtQuickWidgets", "PyQt5.QtMultimedia", "PyQt5.QtMultimediaWidgets",
    "PyQt5.QtBluetooth", "PyQt5.QtNfc", "PyQt5.QtPositioning",
    "PyQt5.QtLocation", "PyQt5.QtSensors", "PyQt5.QtSerialPort",
    "PyQt5.QtSql", "PyQt5.QtTest", "PyQt5.QtHelp", "PyQt5.QtDesigner",
    "PyQt5.QtOpenGL", "PyQt5.QtXml", "PyQt5.QtXmlPatterns",
    "PyQt5.QtDBus", "PyQt5.QtNetworkAuth", "PyQt5.QtRemoteObjects",
    "PyQt5.QtTextToSpeech", "PyQt5.QtX11Extras", "PyQt5.QtWinExtras",
]

# Bibliotecas cientificas y de interfaz que no forman parte del proyecto,
# pero que PyInstaller arrastraria si estan instaladas en el sistema.
OTRAS_SIN_USO = [
    "tkinter", "matplotlib", "numpy", "pandas", "scipy", "PIL", "IPython",
    "notebook", "pytest", "setuptools", "pip", "sqlalchemy", "flask",
    "PyQt6", "PySide2", "PySide6",
]


a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=QT_SIN_USO + OTRAS_SIN_USO,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="IDE_OptaBasic",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX suele disparar falsos positivos de antivirus
    runtime_tmpdir=None,
    console=False,      # es una aplicacion de ventana, sin consola detras
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="icono.ico",
)
