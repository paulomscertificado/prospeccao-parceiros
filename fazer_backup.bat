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
rem Copia de seguranca do banco da nuvem para dados\backups
".venv\Scripts\python.exe" -W ignore fazer_backup.py
echo.
pause
