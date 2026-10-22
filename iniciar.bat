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
title Prospeccao de Parceiros - deixe esta janela aberta
".venv\Scripts\python.exe" iniciar.py
echo.
pause
