@echo off
rem ===================================================================
rem  IDE OptaBasic - lanzador unico
rem
rem    run.bat                     abre el IDE
rem    run.bat programa.CR1        abre el IDE con ese archivo
rem    run.bat lint programa.CR1   analiza por consola, sin abrir el IDE
rem    run.bat test                corre las pruebas
rem    run.bat setup               instala las dependencias
rem    run.bat ayuda               esta ayuda
rem
rem  Tambien se le puede soltar un .CR1 encima con el mouse.
rem  Sin acentos a proposito: la consola de Windows los rompe segun
rem  la pagina de codigos activa.
rem ===================================================================

setlocal
pushd "%~dp0"
set "CODIGO=0"

rem ---- Localizar el interprete de Python ----------------------------
set "PY="
where py >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if not defined PY (
    where python >nul 2>&1
    if not errorlevel 1 set "PY=python"
)
if not defined PY goto :sin_python

rem ---- Elegir que hacer segun el primer argumento -------------------
if /i "%~1"=="test"   goto :test
if /i "%~1"=="lint"   goto :lint
if /i "%~1"=="setup"  goto :setup
if /i "%~1"=="exe"    goto :exe
if /i "%~1"=="icono"  goto :icono
if /i "%~1"=="ayuda"  goto :ayuda
if /i "%~1"=="-h"     goto :ayuda
if /i "%~1"=="--help" goto :ayuda
if /i "%~1"=="/?"     goto :ayuda
goto :ide


rem ===================================================================
:ide
call :comprobar_pyqt
if errorlevel 1 goto :fin

if "%~1"=="" (
    echo Abriendo el IDE...
    %PY% main.py
    set "CODIGO=%ERRORLEVEL%"
    goto :fin
)
if not exist "%~1" (
    echo.
    echo   No existe el archivo "%~1".
    echo   Escribi "run.bat ayuda" para ver las opciones.
    echo.
    set "CODIGO=1"
    goto :fin
)
echo Abriendo "%~1"...
%PY% main.py "%~1"
set "CODIGO=%ERRORLEVEL%"
goto :fin


rem ===================================================================
:lint
if "%~2"=="" (
    echo.
    echo   Falta el archivo a analizar.
    echo     run.bat lint programa.CR1
    echo.
    set "CODIGO=1"
    goto :fin
)
if not exist "%~2" (
    echo.
    echo   No existe el archivo "%~2".
    echo.
    set "CODIGO=1"
    goto :fin
)
%PY% cli.py "%~2" --recursos --hardware --hlog
set "CODIGO=%ERRORLEVEL%"
goto :fin


rem ===================================================================
:test
%PY% -c "import pytest" >nul 2>&1
if errorlevel 1 (
    echo.
    echo   Falta pytest. Instalalo con:  run.bat setup
    echo.
    set "CODIGO=1"
    goto :fin
)
%PY% -m pytest tests -q
set "CODIGO=%ERRORLEVEL%"
goto :fin


rem ===================================================================
:setup
echo Instalando dependencias desde requirements.txt...
echo.
%PY% -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo   Fallo la instalacion. Proba abrir esta consola como
    echo   administrador, o usar un entorno virtual.
    set "CODIGO=1"
    goto :fin
)
echo.
echo   Listo. Ahora podes correr "run.bat" para abrir el IDE.
goto :fin


rem ===================================================================
:exe
call :comprobar_pyqt
if errorlevel 1 goto :fin

%PY% -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo Falta PyInstaller, que es lo que arma el ejecutable. Instalando...
    %PY% -m pip install pyinstaller
    if errorlevel 1 (
        echo.
        echo   Fallo la instalacion de PyInstaller.
        set "CODIGO=1"
        goto :fin
    )
)

if not exist icono.ico (
    echo Generando el icono...
    %PY% herramientas\generar_icono.py
)

echo.
echo Compilando. Tarda un par de minutos la primera vez...
echo.
%PY% -m PyInstaller IDE_OptaBasic.spec --noconfirm --clean
if errorlevel 1 (
    echo.
    echo   Fallo la compilacion. Mirá los mensajes de arriba.
    set "CODIGO=1"
    goto :fin
)
echo.
echo   Listo: dist\IDE_OptaBasic.exe
echo   Ese archivo solo ya es el programa completo: se puede copiar a
echo   otra maquina sin instalar Python ni nada mas.
goto :fin


rem ===================================================================
:icono
%PY% herramientas\generar_icono.py
set "CODIGO=%ERRORLEVEL%"
goto :fin


rem ===================================================================
:ayuda
echo.
echo   IDE OptaBasic - editor y validador de CRBasic-lite para Arduino Opta
echo.
echo     run.bat                     abre el IDE
echo     run.bat programa.CR1        abre el IDE con ese archivo
echo     run.bat lint programa.CR1   analiza por consola y sale
echo     run.bat test                corre las pruebas
echo     run.bat setup               instala las dependencias
echo     run.bat exe                 arma dist\IDE_OptaBasic.exe
echo     run.bat ayuda               esta ayuda
echo.
echo   Tambien podes soltar un archivo .CR1 encima de run.bat.
echo.
goto :fin


rem ===================================================================
rem  Comprobacion de PyQt5, que es lo unico imprescindible para el IDE
rem ===================================================================
:comprobar_pyqt
%PY% -c "import PyQt5" >nul 2>&1
if not errorlevel 1 exit /b 0
echo.
echo   Falta PyQt5, que es lo que dibuja la interfaz.
echo.
set "RESP="
set /p "RESP=  Lo instalo ahora? [S/N] "
if /i not "%RESP%"=="S" (
    echo.
    echo   Sin PyQt5 no se puede abrir el IDE. Igual podes usar el
    echo   analizador de consola:  run.bat lint programa.CR1
    echo.
    exit /b 1
)
%PY% -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo   Fallo la instalacion de dependencias.
    exit /b 1
)
exit /b 0


rem ===================================================================
:sin_python
echo.
echo   No encontre Python en el PATH.
echo.
echo   Instalalo desde https://www.python.org/downloads/ y acordate de
echo   marcar "Add python.exe to PATH" durante la instalacion.
echo.
set "CODIGO=1"
goto :fin


rem ===================================================================
:fin
popd
rem Pausar solo si se abrio con doble clic (cmd /c), no si se llamo
rem desde una consola que el usuario ya tenia abierta.
echo %CMDCMDLINE% | find /i "/c" >nul
if not errorlevel 1 pause
exit /b %CODIGO%
