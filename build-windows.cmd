@echo off
setlocal
cd /d "%~dp0"
py -3 -c "import sys; assert sys.version_info >= (3,12), 'Python 3.12 or newer required'"
if errorlevel 1 goto :fail
py -3 -m venv .build-venv
if errorlevel 1 goto :fail
".build-venv\Scripts\python.exe" -m pip install -r requirements-build.txt
if errorlevel 1 goto :fail
".build-venv\Scripts\python.exe" -m unittest discover -s tests -v
if errorlevel 1 goto :fail
".build-venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onedir --windowed --name FurqanReception run.py
if errorlevel 1 goto :fail
echo.
echo Build complete: dist\FurqanReception\FurqanReception.exe
echo Copy the entire dist\FurqanReception folder to the reception PC.
echo Complete the Windows and thermal-printer acceptance checklist before real use.
pause
exit /b 0
:fail
echo.
echo Build failed. Read the error above. No successful build is claimed.
pause
exit /b 1
