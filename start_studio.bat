@echo off
setlocal enabledelayedexpansion
title Marketing Studio - Easy Start
color 0B

echo ============================================================
echo   Marketing Studio  -  easy start
echo   krea2 :8190   h3 :8188   dashboard :8126
echo ============================================================
echo.

REM --- krea2 (image gen, 8190) ---
netstat -ano | findstr /R ":8190.*LISTENING" >nul 2>&1
if %errorlevel%==0 (
  echo   [ok]    krea2 is already running on :8190
) else (
  echo   [start] krea2 (image) on :8190 ...
  start "krea2 :8190" cmd /c "D:\anime-h3\run_krea2_gpu.bat"
)

REM --- h3 (video, 8188) ---
netstat -ano | findstr /R ":8188.*LISTENING" >nul 2>&1
if %errorlevel%==0 (
  echo   [ok]    h3 is already running on :8188
) else (
  echo   [start] h3 (video) on :8188 ...
  start "h3 :8188" cmd /c "D:\anime-h3\run_h3.bat"
)

REM --- dashboard (8126) ---
netstat -ano | findstr /R ":8126.*LISTENING" >nul 2>&1
if %errorlevel%==0 (
  echo   [ok]    dashboard is already running on :8126
) else (
  echo   [start] dashboard on :8126 ...
  start "dashboard :8126" cmd /c ""C:\Users\Chad\PycharmProjects\MarketingStudio\.venv\Scripts\python.exe" studio.py --port 8126"
)

REM --- LM Studio (LLM, 1234) - warn only, started separately ---
netstat -ano | findstr /R ":1234.*LISTENING" >nul 2>&1
if %errorlevel%==0 (
  echo   [ok]    LM Studio is running on :1234
) else (
  echo   [warn]  LM Studio not detected on :1234 - start it for script generation
)

echo.
echo   Waiting for services to come up (first ComfyUI boot can take a minute)...
timeout /t 45 /nobreak >nul

echo.
echo   ---- status ----
for %%p in (8188 8190 8126) do (
  netstat -ano | findstr /R ":%%p.*LISTENING" >nul 2>&1
  if !errorlevel!==0 (
    echo   [up]   :%%p
  ) else (
    echo   [down] :%%p
  )
)

echo.
echo   Opening the dashboard in your browser...
start "" "http://127.0.0.1:8126"
echo.
echo   Done. This window will stay open; close it when you want to leave it.
pause >nul
