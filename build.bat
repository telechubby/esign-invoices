@echo off
REM Run this on the Windows machine, from the project folder.
setlocal

if not exist .venv (
    py -3 -m venv .venv
)
call .venv\Scripts\activate.bat

pip install -r requirements.txt
python -m pytest tests -q
if errorlevel 1 (
    echo Tests failed - not building. Fix the failures above first.
    exit /b 1
)

pyinstaller build.spec

echo.
echo Build finished. The app is in dist\EsignInvoices\EsignInvoices.exe
