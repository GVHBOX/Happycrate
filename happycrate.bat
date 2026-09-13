@echo off
setlocal
cd /d "%~dp0"
if /i "%~1"=="dev" (
  start "happycrate-dev" /min ".venv\Scripts\python.exe" main.py
  goto :eof
)
if /i "%~1"=="web" (
  curl -s -o nul http://127.0.0.1:8123/index.html || start "hc-web" /min ".venv\Scripts\python.exe" -m http.server 8123 --directory web
  start "" http://127.0.0.1:8123/index.html
  goto :eof
)
start "" "%~dp0happycrate.exe"
