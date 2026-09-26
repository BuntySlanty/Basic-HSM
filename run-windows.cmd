@echo off
setlocal
cd /d "%~dp0"
py -3 run.py
if errorlevel 1 (
  echo Could not start Reception. Check Python 3.12+ with Tcl/Tk is installed.
  pause
)
