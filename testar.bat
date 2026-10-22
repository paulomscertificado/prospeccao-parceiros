@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
rem Testes automaticos (usam uma pasta temporaria, nao mexem nos seus dados)
".venv\Scripts\python.exe" -m pytest -q testes
echo.
pause
