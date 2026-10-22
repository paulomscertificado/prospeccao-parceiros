@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
rem Cria dados FICTICIOS para conhecer o sistema (apague depois em Configuracoes)
".venv\Scripts\python.exe" -m app.seed
echo.
pause
