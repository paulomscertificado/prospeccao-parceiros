@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
if not exist ".venv\Scripts\python.exe" (
    echo O sistema ainda nao foi instalado.
    pause
    exit /b 1
)
echo Exportar os dados de uma AR (arquivo criptografado; LGPD)
echo.
set /p AR=Apelido da AR (ex.: grupo-certy): 
set /p ONDE=Onde? 1 = banco de TESTE (padrao), 2 = sistema da NUVEM: 
if "%ONDE%"=="2" (".venv\Scripts\python.exe" -W ignore exportar_ar.py %AR% --nuvem) else (".venv\Scripts\python.exe" -W ignore exportar_ar.py %AR%)
echo.
pause
