param(
  [string]$EnvName = "base",
  [string]$Command = "python -V"
)

$ErrorActionPreference = "Stop"
$condaBat = "C:\Users\Administrator\miniconda3\condabin\conda.bat"

if (-not (Test-Path $condaBat)) {
  throw "Conda not found: $condaBat"
}

$cmdline = "`"$condaBat`" activate `"$EnvName`" && $Command"
& cmd.exe /c $cmdline
exit $LASTEXITCODE
