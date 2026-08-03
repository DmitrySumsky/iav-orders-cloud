@echo off
rem Обёртка для планировщика Windows: утренний отчёт без GitHub Actions.
rem Путь к python зафиксирован — в задании планировщика PATH может быть урезан.
setlocal
set PY=C:\Users\Lenovo\AppData\Local\Python\pythoncore-3.14-64\python.exe
if not exist "%PY%" set PY=python
cd /d "%~dp0.."
"%PY%" -u "%~dp0run_local.py" %*
exit /b %ERRORLEVEL%
