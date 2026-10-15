@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
    py pasafile.py --open
    goto :end
)
where python >nul 2>nul
if %errorlevel%==0 (
    python pasafile.py --open
    goto :end
)
echo.
echo  Python non trovato. Installa Python 3 da https://www.python.org/downloads/
echo  Spunta "Add Python to PATH" durante l'installazione.
echo.
pause
:end
