# run_main.ps1

# 1) Switch to the script’s folder so relative paths still work
$scriptDir = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
Set-Location $scriptDir

# 2) Launch your GUI via pythonw (no console) and immediately detach
Start-Process -FilePath "pythonw.exe" -ArgumentList "main.py"

# 3) Exit this PowerShell session (closes the console window)
exit
