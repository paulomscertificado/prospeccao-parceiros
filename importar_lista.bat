@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
if not exist ".venv\Scripts\python.exe" (
    echo O sistema ainda nao foi instalado.
    echo De dois cliques no "instalar.bat" primeiro.
    echo.
    pause
    exit /b 1
)
rem Importa a lista de empresas da CNPJa (.xlsx) no banco da nuvem. Pode arrastar o arquivo em cima deste .bat.
".venv\Scripts\python.exe" -W ignore importar_lista.py %1
echo.
pause
