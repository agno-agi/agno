@echo off
rem Overlay'i ayri bir pencerede acar, LIVE Studio "Pencere yakalama" ile alabilsin.
rem - Chrome tercih edilir (LIVE Studio Chrome pencerelerini listeler), yoksa Edge kullanilir.
rem - Ayri tarayici profili: asagidaki secenekler tarayici zaten acik olsa bile gecerli olur.
rem - Pencere ortuldugunde Windows'un pencereyi "uyutmasi" engellenir (goruntu donmaz).
rem - Ses kendiliginden calar, sayfaya tiklamak gerekmez.
rem - 9333 hata ayiklama portu (yalnizca bu bilgisayardan erisilir): gerektiginde pencere icindeki sesi/goruntuyu denetlemek icin.
rem Once run.bat calistirin ki sunucu acik olsun. Port degistirmek icin: set OVERLAY_URL=http://localhost:<port>/overlay

if not defined OVERLAY_URL set "OVERLAY_URL=http://localhost:3939/overlay"
set "BROWSER=msedge"
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "BROWSER=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" set "BROWSER=%LocalAppData%\Google\Chrome\Application\chrome.exe"

start "" "%BROWSER%" --app=%OVERLAY_URL% --window-size=608,1080 --user-data-dir="%TEMP%\tiktok-live-kit-overlay" --disable-backgrounding-occluded-windows --disable-renderer-backgrounding --disable-background-timer-throttling --autoplay-policy=no-user-gesture-required --remote-debugging-port=9333
