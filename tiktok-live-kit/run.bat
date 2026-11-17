@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

echo =======================================
echo        TIKTOK LIVE KIT
echo =======================================

where node >nul 2>&1
if errorlevel 1 (
  echo [HATA] Node.js 20 veya uzeri kurulu degil: https://nodejs.org/
  pause
  exit /b 1
)

rem eksik kutuphane varsa (ornegin kit guncellenince 3D tema icin three) yeniden kurulur
set "NEED_INSTALL="
if not exist "node_modules\ws\package.json" set "NEED_INSTALL=1"
if not exist "node_modules\three\package.json" set "NEED_INSTALL=1"
if defined NEED_INSTALL (
  echo [1/2] Kutuphaneler kuruluyor...
  where pnpm >nul 2>&1
  if errorlevel 1 (
    call npm install --no-audit --no-fund
  ) else (
    call pnpm install --frozen-lockfile
  )
  if errorlevel 1 (
    echo [HATA] Kutuphane kurulumu basarisiz.
    pause
    exit /b 1
  )
) else (
  echo [1/2] Kutuphaneler hazir.
)

powershell -NoProfile -Command "try { $h = Invoke-RestMethod -Uri 'http://127.0.0.1:3939/api/health' -TimeoutSec 2; if ($h.app -eq 'tiktok-live-kit') { exit 0 } } catch {}; exit 1" >nul 2>&1
if not errorlevel 1 (
  echo [2/2] Sunucu zaten calisiyor.
  goto :open
)

echo [2/2] Sunucu baslatiliyor...
start "TikTok Live Kit" cmd /k "node src\server.js"
for /l %%i in (1,1,20) do (
  powershell -NoProfile -Command "try { Invoke-RestMethod -Uri 'http://127.0.0.1:3939/api/health' -TimeoutSec 1 | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
  if not errorlevel 1 goto :open
  ping 127.0.0.1 -n 2 >nul
)
echo [HATA] Sunucu 20 saniyede acilmadi. "TikTok Live Kit" penceresine bakin.
pause
exit /b 1

:open
start "" "http://localhost:3939/"
echo.
echo Kontrol paneli: http://localhost:3939/
echo OBS icin overlay:  http://localhost:3939/overlay  (1080 x 1920)
exit /b 0
