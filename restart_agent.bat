@echo off
echo ============================================
echo   Resume Sync Agent - Restart
echo ============================================

:: Kill the running agent (pythonw = background, python = foreground)
echo Stopping agent...
taskkill /IM pythonw.exe /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq ResumeSyncAgent" /F >nul 2>&1
timeout /t 2 /nobreak >nul

:: Start the agent again in the background
echo Starting agent...
start "" pythonw "%~dp0main.py"

echo Agent restarted. Check logs:
echo   type "%~dp0sync_agent.log"
echo ============================================