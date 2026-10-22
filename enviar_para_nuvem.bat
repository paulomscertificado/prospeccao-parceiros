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
rem Gera as variaveis da Vercel e copia o banco deste computador para o banco da nuvem
".venv\Scripts\python.exe" -W ignore enviar_para_nuvem.py
echo.
pause
