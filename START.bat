@echo off
setlocal enabledelayedexpansion
title Flood Hapi
cd /d "%~dp0"
set "BASEDIR=%~dp0"

echo.
echo  ============================================
echo     Flood Hapi - Egyptian Flood Intelligence
echo  ============================================
echo.

REM ── Check files exist (not running from inside zip) ──
if not exist "!BASEDIR!app.py" goto :not_extracted

REM ── Find Python 3.13 specifically, then fall back ──
echo  [1/5] Looking for Python...

REM Prefer py launcher targeting 3.13 (avoids 3.14 which lacks wheels)
where py >nul 2>&1 && py -3.13 --version >nul 2>&1 && set "PYTHON=py -3.13" && goto :python_verified

REM Try explicit 3.13 paths
if exist "!LOCALAPPDATA!\Programs\Python\Python313\python.exe" set "PYTHON=!LOCALAPPDATA!\Programs\Python\Python313\python.exe" && goto :python_verified
if exist "!PROGRAMFILES!\Python313\python.exe" set "PYTHON=!PROGRAMFILES!\Python313\python.exe" && goto :python_verified

REM Try 3.12 and 3.11 (also have wheels)
where py >nul 2>&1 && py -3.12 --version >nul 2>&1 && set "PYTHON=py -3.12" && goto :python_verified
where py >nul 2>&1 && py -3.11 --version >nul 2>&1 && set "PYTHON=py -3.11" && goto :python_verified
if exist "!LOCALAPPDATA!\Programs\Python\Python312\python.exe" set "PYTHON=!LOCALAPPDATA!\Programs\Python\Python312\python.exe" && goto :python_verified
if exist "!LOCALAPPDATA!\Programs\Python\Python311\python.exe" set "PYTHON=!LOCALAPPDATA!\Programs\Python\Python311\python.exe" && goto :python_verified
if exist "!PROGRAMFILES!\Python312\python.exe" set "PYTHON=!PROGRAMFILES!\Python312\python.exe" && goto :python_verified
if exist "!PROGRAMFILES!\Python311\python.exe" set "PYTHON=!PROGRAMFILES!\Python311\python.exe" && goto :python_verified

REM Last resort: whatever "python" is on PATH (needs version check)
where python >nul 2>&1 && set "PYTHON=python" && goto :python_check_version

goto :no_python

:python_check_version
echo        Found: !PYTHON!
REM Only check version for generic "python" — might be 3.14+
python -c "import sys; exit(0 if sys.version_info < (3,14) else 1)" 2>nul
if errorlevel 1 goto :python_too_new
goto :venv_check

:python_verified
echo        Found: !PYTHON!

:venv_check
REM ── Create venv if needed ──
if exist "venv\Scripts\python.exe" goto :venv_ok
echo.
echo  [2/5] Creating virtual environment (first run only)...
!PYTHON! -m venv venv
if exist "venv\Scripts\python.exe" goto :venv_ok
echo  [!] Failed to create virtual environment.
goto :fail

:venv_ok
echo  [2/5] Virtual environment OK.

REM ── Install deps if needed ──
"venv\Scripts\python.exe" -c "import flask" >nul 2>&1 && goto :deps_ok
echo.
echo  [3/5] Installing dependencies (first run only, takes 1-2 min)...
"venv\Scripts\pip.exe" install --only-binary :all: -r requirements.txt
if errorlevel 1 goto :deps_fail
echo        Done.
goto :deps_done

:deps_ok
echo  [3/5] Dependencies OK.

:deps_done

REM ── Desktop shortcut ──
echo  [4/5] Checking desktop shortcut...
powershell -Command "$d=[Environment]::GetFolderPath('Desktop'); if(-not(Test-Path \"$d\Flood Hapi.lnk\")){$w=New-Object -ComObject WScript.Shell;$s=$w.CreateShortcut(\"$d\Flood Hapi.lnk\");$s.TargetPath='!BASEDIR!launch.vbs';$s.WorkingDirectory='!BASEDIR!';$s.IconLocation='!BASEDIR!hapi.ico';$s.Description='Flood Hapi';$s.Save();echo '       Created.'}else{echo '       OK.'}" 2>nul

REM ── Launch ──
echo  [5/5] Starting server...
echo.
echo  ============================================
echo     Flood Hapi is running!
echo     http://localhost:5000
echo.
echo     Keep this window open.
echo     Press Ctrl+C to stop the server.
echo  ============================================
echo.

start "" http://localhost:5000
"venv\Scripts\python.exe" app.py
goto :stopped

REM ── Error handlers ──

:not_extracted
echo  [!] ERROR: app.py not found!
echo.
echo  You need to EXTRACT the zip first.
echo  Right-click the zip ^> "Extract All"
echo  Then open the extracted folder and
echo  double-click START.bat
echo.
goto :fail

:python_too_new
echo.
echo  [!] Your Python version is too new (3.14+).
echo      Some dependencies don't have installers
echo      for Python 3.14 yet.
echo.
echo  Please install Python 3.13 from:
echo  https://www.python.org/downloads/release/python-3131/
echo.
echo  (You can keep 3.14 installed too - they work side by side)
echo.
set /p "DOINSTALL=  Download and install Python 3.13 now? (Y/N): "
if /i "!DOINSTALL!"=="Y" goto :install_python
goto :fail

:no_python
echo  [!] Python is not installed.
echo.
echo  Flood Hapi needs Python to run.
echo.
set /p "DOPYTHON=  Install Python automatically? (Y/N): "
if /i "!DOPYTHON!"=="Y" goto :install_python
echo.
echo  Please install Python from https://python.org
echo  IMPORTANT: Tick "Add Python to PATH"
echo.
goto :fail

:install_python
echo.
echo  [*] Downloading Python 3.13.1...
powershell -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.13.1/python-3.13.1-amd64.exe' -OutFile '!TEMP!\python_installer.exe'"
if not exist "!TEMP!\python_installer.exe" echo  [!] Download failed. && goto :fail
echo  [*] Installing... (click Yes if you see a UAC prompt)
"!TEMP!\python_installer.exe" /passive InstallAllUsers=0 PrependPath=1 Include_test=0 Include_launcher=1
del "!TEMP!\python_installer.exe" 2>nul
set "PATH=!LOCALAPPDATA!\Programs\Python\Python313;!LOCALAPPDATA!\Programs\Python\Python313\Scripts;!PATH!"
echo.
echo  [+] Python 3.13 installed.
echo      Deleting old venv to use new Python...
rmdir /s /q venv 2>nul
REM Re-find python
where py >nul 2>&1 && py -3.13 --version >nul 2>&1 && set "PYTHON=py -3.13" && goto :python_verified
if exist "!LOCALAPPDATA!\Programs\Python\Python313\python.exe" set "PYTHON=!LOCALAPPDATA!\Programs\Python\Python313\python.exe" && goto :python_verified
where python >nul 2>&1 && set "PYTHON=python" && goto :python_check_version
echo  [!] Python installed but not found yet.
echo      Close this window and run START.bat again.
goto :fail

:deps_fail
echo.
echo  [!] Dependency install failed.
echo.
echo  This usually means your Python version is too new
echo  and pre-built packages aren't available yet.
echo.
echo  Fix: Install Python 3.13 from https://python.org
echo  Then delete the "venv" folder and run START.bat again.
echo.
goto :fail

:stopped
echo.
echo  Server stopped.
echo.
pause
goto :eof

:fail
echo.
pause
goto :eof
