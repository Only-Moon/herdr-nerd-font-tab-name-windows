@echo off
REM Windows wrapper for herdr-nerd-font-tab-name
REM This allows the plugin to be invoked as a bare command from herdr hooks

set "PLUGIN_ROOT=%~dp0.."

REM Find python - try multiple locations
set "PYTHON_CMD="

REM 1. Try python in PATH
where python >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    set "PYTHON_CMD=python"
    goto :run_python
)

REM 2. Try py launcher in PATH
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    set "PYTHON_CMD=py"
    goto :run_python
)

REM 3. Try common Windows Python install locations
if exist "%LOCALAPPDATA%\Programs\Python\Python3*\python.exe" (
    for /f "delims=" %%i in ('dir /b "%LOCALAPPDATA%\Programs\Python\Python3*\python.exe" 2^>nul') do (
        set "PYTHON_CMD=%%i"
        goto :run_python
    )
)

REM 4. Try Scoop shims
if exist "%USERPROFILE%\scoop\shims\python.exe" (
    set "PYTHON_CMD=%USERPROFILE%\scoop\shims\python.exe"
    goto :run_python
)

REM 5. Try Scoop apps
if exist "%USERPROFILE%\scoop\apps\python\current\python.exe" (
    set "PYTHON_CMD=%USERPROFILE%\scoop\apps\python\current\python.exe"
    goto :run_python
)

REM 6. Try system-wide install
if exist "C:\Program Files\Python3*\python.exe" (
    for /f "delims=" %%i in ('dir /b "C:\Program Files\Python3*\python.exe" 2^>nul') do (
        set "PYTHON_CMD=%%i"
        goto :run_python
    )
)
if exist "C:\Program Files (x86)\Python3*\python.exe" (
    for /f "delims=" %%i in ('dir /b "C:\Program Files (x86)\Python3*\python.exe" 2^>nul') do (
        set "PYTHON_CMD=%%i"
        goto :run_python
    )
)

echo Python not found in PATH or standard locations
exit /b 1

:run_python
REM Pass all arguments through to the Python entrypoint
set "PYTHONPATH=%PLUGIN_ROOT%\lib"
"%PYTHON_CMD%" -m nftn.cli %*