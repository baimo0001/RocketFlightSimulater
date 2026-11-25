param([string]$Python)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskPython = $Python
if (-not $taskPython) {
    $taskPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
}
if (-not (Test-Path -LiteralPath $taskPython -PathType Leaf)) {
    throw 'Python environment is missing. See docs/DEVELOPMENT.md for setup.'
}
$env:MPLBACKEND = 'TkAgg'
& $taskPython -m PyInstaller --noconfirm --onedir --windowed --name NebulaRocket --exclude-module torch --exclude-module tensorflow --exclude-module pandas --exclude-module IPython --exclude-module pytest --exclude-module sympy --exclude-module numba --exclude-module cv2 --exclude-module PyQt5 --exclude-module PyQt6 --exclude-module PySide2 --exclude-module PySide6 --add-data 'examples;examples' --add-data 'docs;docs' app.py
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }
Copy-Item -LiteralPath 'README.md' -Destination 'dist/NebulaRocket/使用说明.md' -Force
Copy-Item -LiteralPath 'docs' -Destination 'dist/NebulaRocket/docs' -Recurse -Force
Copy-Item -LiteralPath 'examples' -Destination 'dist/NebulaRocket/examples' -Recurse -Force
