@echo off
REM Agenda o Turibenção para rodar sozinho no Windows.
REM Padrão: segunda, quarta e sexta às 18:00. Mude /D e /ST se quiser.
cd /d "%~dp0"
schtasks /Create /TN "Turibencao Automatico" /TR "\"%~dp0rodar.bat\"" /SC WEEKLY /D MON,WED,FRI /ST 18:00 /F
echo.
echo Pronto! Para ver ou apagar: abra o "Agendador de Tarefas" do Windows.
pause
