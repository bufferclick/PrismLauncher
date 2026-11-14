@echo off
rem HorizonPort launcher for Windows: run the toolkit from anywhere.
rem   porting\bin\horizonport.cmd doctor
setlocal
set "ROOT=%~dp0..\.."
set "PYTHONPATH=%ROOT%;%PYTHONPATH%"
python -m porting.horizonport %*
exit /b %ERRORLEVEL%
