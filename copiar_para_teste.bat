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
rem Copiar os dados para o banco de TESTE (o sistema de verdade nao e tocado)
".venv\Scripts\python.exe" -W ignore copiar_para_teste.py
echo.
pause
