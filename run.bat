@echo off
REM Runs the app from source (for testing before/instead of building the .exe).
call .venv\Scripts\activate.bat
python -m app.main
