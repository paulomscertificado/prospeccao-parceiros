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
rem Volta uma copia de seguranca para o banco da nuvem (so em emergencia)
".venv\Scripts\python.exe" -W ignore restaurar_backup.py
echo.
pause
