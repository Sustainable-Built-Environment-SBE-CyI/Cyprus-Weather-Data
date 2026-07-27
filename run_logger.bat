@echo off
setlocal
cd /d "%~dp0"

set "UV_EXE=%USERPROFILE%\.local\bin\uv.exe"
if not exist "%UV_EXE%" set "UV_EXE=uv"

"%UV_EXE%" run --python 3.14 python "%~dp0cyprus_weather_logger.py"

exit /b %ERRORLEVEL%
