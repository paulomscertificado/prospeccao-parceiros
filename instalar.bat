@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo  Instalando a Prospeccao de Parceiros (so precisa fazer 1 vez)
echo ============================================================
echo.
python --version >nul 2>&1
if errorlevel 1 (
    echo O Python nao foi encontrado.
    echo Instale o Python em https://www.python.org/downloads/
    echo e marque a opcao "Add Python to PATH" durante a instalacao.
    echo.
    pause
    exit /b 1
)
echo [1/3] Preparando a pasta do sistema...
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    if errorlevel 1 goto erro
)
echo.
echo [2/3] Instalando as bibliotecas (pode demorar alguns minutos)...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install --upgrade -r requirements-dev.txt
if errorlevel 1 goto erro
echo.
echo [3/3] Criando o arquivo de configuracao...
if not exist ".env" copy ".env.example" ".env" >nul
echo.
echo Tudo pronto! Agora e so dar dois cliques em "iniciar.bat".
echo.
pause
exit /b 0
:erro
echo.
echo Algo deu errado na instalacao. Confira sua internet e rode este arquivo de novo.
echo.
pause
exit /b 1
