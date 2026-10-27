@echo off
REM Cria e publica um vídeo novo do Turibenção
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python main.py %*
