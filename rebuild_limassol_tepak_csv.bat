@echo off
setlocal
cd /d "%~dp0"

set "UV_EXE=%USERPROFILE%\.local\bin\uv.exe"
if not exist "%UV_EXE%" set "UV_EXE=uv"

"%UV_EXE%" run --python 3.14 python "%~dp0rebuild_limassol_tepak_csv.py"

pause
