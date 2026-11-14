@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo White label - Fase 1: ensaio de colocar a AR em cada linha (banco de TESTE, nada e gravado)
echo.
".venv\Scripts\python.exe" migrar_ar.py %*
echo.
pause
