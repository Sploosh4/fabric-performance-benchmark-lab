@echo off
echo Start as administrator once. Leave this broker window open during sessions.
python "%~dp0benchmark.py" broker
echo Broker exited with code %errorlevel%.
pause
