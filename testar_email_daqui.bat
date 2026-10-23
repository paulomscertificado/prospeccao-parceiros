@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
rem Testa o e-mail de envio (o mesmo salvo no site) a partir deste computador
".venv\Scripts\python.exe" -W ignore testar_email_daqui.py
echo.
pause
