@echo off
cd /d "%~dp0"
set OPENCV_LOG_LEVEL=SILENT
python main.py
if errorlevel 1 pause
