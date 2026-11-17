@echo off
rem Mo overlay thanh mot cua so doc rieng de LIVE Studio "Quay man hinh cua so".
rem - Uu tien Chrome (LIVE Studio liet ke duoc cua so Chrome), khong co thi dung Edge.
rem - Ho so trinh duyet rieng: cac tuy chon duoi day moi co tac dung du trinh duyet dang mo.
rem - Khong cho Windows lam "ngu" cua so khi bi che (hinh khong bi dung).
rem - Tu phat tieng, khong can bam vao trang.
rem - Cong go loi 9333 (chi may nay truy cap) de kiem tra am thanh, hinh ben trong cua so khi can.
rem Chay run.bat truoc de server dang chay. Doi cong: set OVERLAY_URL=http://localhost:<cong>/overlay

if not defined OVERLAY_URL set "OVERLAY_URL=http://localhost:3939/overlay"
set "BROWSER=msedge"
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "BROWSER=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" set "BROWSER=%LocalAppData%\Google\Chrome\Application\chrome.exe"

start "" "%BROWSER%" --app=%OVERLAY_URL% --window-size=608,1080 --user-data-dir="%TEMP%\tiktok-live-kit-overlay" --disable-backgrounding-occluded-windows --disable-renderer-backgrounding --disable-background-timer-throttling --autoplay-policy=no-user-gesture-required --remote-debugging-port=9333
