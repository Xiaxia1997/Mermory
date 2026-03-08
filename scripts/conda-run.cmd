@echo off
setlocal

set "CONDA_BAT=C:\Users\Administrator\miniconda3\condabin\conda.bat"
if not exist "%CONDA_BAT%" (
  echo Conda not found: %CONDA_BAT%
  exit /b 1
)
set "ENV_NAME=base"

if /i "%~1"=="-n" (
  if "%~2"=="" (
    echo Missing env name after -n
    exit /b 1
  )
  set "ENV_NAME=%~2"
  shift
  shift
)

if "%~1"=="" (
  call "%CONDA_BAT%" activate "%ENV_NAME%" >nul
  if errorlevel 1 exit /b %errorlevel%
  python -V
  exit /b %errorlevel%
)

call "%CONDA_BAT%" activate "%ENV_NAME%" >nul
if errorlevel 1 exit /b %errorlevel%
%*
exit /b %errorlevel%
