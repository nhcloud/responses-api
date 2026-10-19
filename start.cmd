@echo off
setlocal
set "selection=both"
set "check=0"
:parse
if "%~1"=="" goto prerequisites
if "%~1"=="--check" (
    set "check=1"
    shift
    goto parse
)
if not "%~1"=="dotnet" if not "%~1"=="python" if not "%~1"=="both" (
    echo Usage: start.cmd [dotnet^|python^|both] [--check]
    exit /b 1
)
set "selection=%~1"
shift
goto parse
:prerequisites
if "%selection%"=="dotnet" goto dotnet_check
set "python=%~dp0python\.venv\Scripts\python.exe"
if not exist "%python%" set "python=%~dp0.venv\Scripts\python.exe"
if not exist "%python%" (
    echo Missing Python virtual environment. Follow the README Python Setup steps first.
    exit /b 1
)
if "%selection%"=="python" goto ready
:dotnet_check
where dotnet >nul 2>&1
if errorlevel 1 (
    echo Missing dotnet. Install the .NET 10 SDK first.
    exit /b 1
)
:ready
if not defined DOTNET_ENVIRONMENT set "DOTNET_ENVIRONMENT=Development"
if "%check%"=="1" (
    echo Prerequisites found. Ready to open selected demo terminals: %selection%.
    exit /b 0
)
if not "%selection%"=="dotnet" (
    start "Python demo" /D "%~dp0" "%ComSpec%" /k ""%python%" "%~dp0python\loop\loop_demo.py""
    if errorlevel 1 exit /b 1
)
if not "%selection%"=="python" (
    start ".NET demo" /D "%~dp0" "%ComSpec%" /k dotnet run --project dotnet\loop
    if errorlevel 1 exit /b 1
)
echo Opened selected demo terminals: %selection%. Select 5 in each menu to exit its demo.