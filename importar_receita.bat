@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
rem Importa a base de CNPJs da Receita Federal (so escritorios de contabilidade)
".venv\Scripts\python.exe" importar_receita.py
echo.
pause
