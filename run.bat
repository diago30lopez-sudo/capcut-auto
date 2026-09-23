@echo off
cd /d "%~dp0"

:: Usar el Python de Windows que ya tiene Pillow instalado
set PYTHON_EXE=C:\Users\diago_dev\AppData\Local\Programs\Python\Python314\python.exe

if not exist "%PYTHON_EXE%" (
    echo No se encontro Python en la ruta esperada.
    echo Buscando en el PATH...
    set PYTHON_EXE=python
)

echo Ejecutando con: %PYTHON_EXE%
"%PYTHON_EXE%" -X utf8 "src\main.py"
pause
