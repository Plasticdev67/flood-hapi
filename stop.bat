@echo off
REM Stops the EA Flood Risk Tool server
taskkill /f /im python.exe /fi "WINDOWTITLE eq *app.py*" >nul 2>&1
FOR /F "tokens=5" %%P IN ('netstat -aon ^| findstr :5000 ^| findstr LISTENING') DO (
    taskkill /F /PID %%P >nul 2>&1
)
echo Flood Risk Tool server stopped.
timeout /t 2 >nul
