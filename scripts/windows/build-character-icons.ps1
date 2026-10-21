param(
    [string]$PortraitPath = '',
    [string]$RasterExporterPath = '',
    [ValidateSet('light', 'dark')]
    [string]$Variant = 'light'
)
$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$IconDir = Join-Path $RepoRoot 'qq-onebot-manager-qt\resources\icons'
$BadgeDir = Join-Path $IconDir 'badges'
if (-not $PortraitPath) {
    $PortraitPath = Join-Path $IconDir $(if ($Variant -eq 'dark') { 'app-portrait-black.png' } else { 'app-portrait.png' })
}
if ($Variant -eq 'dark') {
    $DarkMascotPath = Join-Path $IconDir 'mascot-black.png'
    $IconDir = Join-Path $IconDir 'dark'
    New-Item -ItemType Directory -Path $IconDir -Force | Out-Null
    Copy-Item -LiteralPath $DarkMascotPath -Destination (Join-Path $IconDir 'mascot.png')
}
Add-Type -AssemblyName System.Drawing

# Package the generated illustration at icon sizes, preserving its alpha.
function ConvertTo-IconPng([System.Drawing.Image]$Image, [int]$Size) {
    $bitmap = New-Object System.Drawing.Bitmap($Size, $Size, ([System.Drawing.Imaging.PixelFormat]::Format32bppArgb))
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $stream = New-Object IO.MemoryStream
    try {
        $graphics.Clear([System.Drawing.Color]::Transparent)
        $graphics.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
        $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
        $graphics.DrawImage($Image, 0, 0, $Size, $Size)
        $bitmap.Save($stream, [System.Drawing.Imaging.ImageFormat]::Png)
        return ,$stream.ToArray()
    } finally {
        $stream.Dispose()
        $graphics.Dispose()
        $bitmap.Dispose()
    }
}
$portrait = [System.Drawing.Image]::FromFile((Resolve-Path -LiteralPath $PortraitPath).Path)
try {
    $masterPng = ConvertTo-IconPng $portrait 512
    $smallPng = ConvertTo-IconPng $portrait 192
    $masterBase64 = [Convert]::ToBase64String($masterPng)
    $smallBase64 = [Convert]::ToBase64String($smallPng)
    $appSvg = @"
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="64" height="64" viewBox="0 0 64 64">
  <image x="0" y="0" width="64" height="64" xlink:href="data:image/png;base64,$masterBase64"/>
</svg>
"@
    [IO.File]::WriteAllText((Join-Path $IconDir 'app.svg'), $appSvg, [Text.UTF8Encoding]::new($false))
    $badgeFiles = Get-ChildItem -LiteralPath $BadgeDir -Filter '*.svg' -File
    foreach ($badgeFile in $badgeFiles) {
        $badgeSource = [IO.File]::ReadAllText($badgeFile.FullName)
        $match = [regex]::Match($badgeSource, '(?s)<svg\b[^>]*>(.*?)</svg>')
        if (-not $match.Success) { throw "Invalid badge SVG: $($badgeFile.FullName)" }
        $badgeMarkup = $match.Groups[1].Value.Trim()
        $intrinsicSize = if ($badgeFile.Name.StartsWith('card-')) { 36 } elseif ($badgeFile.Name.StartsWith('action-')) { 28 } else { 32 }
        $svg = @"
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="$intrinsicSize" height="$intrinsicSize" viewBox="0 0 64 64">
  <image x="0" y="0" width="60" height="60" xlink:href="data:image/png;base64,$smallBase64"/>
  <circle cx="50" cy="50" r="13" fill="#fff7ef" stroke="#7189be" stroke-width="1.3"/>
  <g transform="translate(37.5 37.5) scale(0.78)" fill="none" stroke="#66739a" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
    $badgeMarkup
  </g>
</svg>
"@
        [IO.File]::WriteAllText((Join-Path $IconDir $badgeFile.Name), $svg, [Text.UTF8Encoding]::new($false))
    }
    # Windows ICO directory with eight PNG frames (modern Windows supports alpha).
    $sizes = @(16, 20, 24, 32, 48, 64, 128, 256)
    $frames = @{}
    foreach ($size in $sizes) { $frames[$size] = ConvertTo-IconPng $portrait $size }
    $icoStream = New-Object IO.MemoryStream
    $writer = New-Object IO.BinaryWriter($icoStream)
    try {
        $writer.Write([uint16]0)
        $writer.Write([uint16]1)
        $writer.Write([uint16]$sizes.Count)
        $offset = 6 + 16 * $sizes.Count
        foreach ($size in $sizes) {
            $dimension = if ($size -eq 256) { 0 } else { $size }
            $writer.Write([byte]$dimension)
            $writer.Write([byte]$dimension)
            $writer.Write([byte]0)
            $writer.Write([byte]0)
            $writer.Write([uint16]1)
            $writer.Write([uint16]32)
            $writer.Write([uint32]$frames[$size].Length)
            $writer.Write([uint32]$offset)
            $offset += $frames[$size].Length
        }
        foreach ($size in $sizes) { $writer.Write([byte[]]$frames[$size]) }
        $writer.Flush()
        $icoBytes = $icoStream.ToArray()
        [IO.File]::WriteAllBytes((Join-Path $IconDir 'app.ico'), $icoBytes)
        # New filename ensures shortcuts do not reuse the previous cat icon cache.
        [IO.File]::WriteAllBytes((Join-Path $IconDir 'app-character.ico'), $icoBytes)
    } finally {
        $writer.Dispose()
        $icoStream.Dispose()
    }
} finally {
    $portrait.Dispose()
}
if (-not $RasterExporterPath) {
    $candidates = @(
        (Join-Path $RepoRoot 'qq-onebot-manager-qt\build\icon-assets-generator.exe'),
        (Join-Path $RepoRoot 'qq-onebot-manager-qt\build\icon-refresh\icon-assets-generator.exe')
    )
    $RasterExporterPath = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $RasterExporterPath) {
    throw 'Build the CMake icon-assets-generator target, then rerun with -RasterExporterPath to export the runtime PNG icons.'
}
& $RasterExporterPath $IconDir
if ($LASTEXITCODE -ne 0) { throw 'Smooth runtime icon export failed.' }
Write-Host "Updated $Variant portrait branding, 13 illustrated function icons, runtime PNGs, and Windows ICO files."
