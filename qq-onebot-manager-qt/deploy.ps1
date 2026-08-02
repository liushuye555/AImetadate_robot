$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Exe = Join-Path $PSScriptRoot 'build\qq-onebot-manager-qt.exe'
$QtBin = 'C:\Qt\6.11.1\mingw_64\bin'

if (-not (Test-Path -LiteralPath $Exe)) {
    throw "未找到构建产物，请先在 Qt Creator 或命令行构建: $Exe"
}

& "$QtBin\windeployqt.exe" --release --no-translations --no-opengl-sw $Exe
Write-Host "部署完成，可直接运行: $Exe"
