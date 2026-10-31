# Windows build script for moonlog
# Auto-detects MSVC using vswhere, sets ASCII TEMP path, builds native target

$ErrorActionPreference = "Stop"

# Find Visual Studio Build Tools or Visual Studio using vswhere
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$msvcPath = $null

if (Test-Path $vswhere) {
    $vsPath = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    if ($vsPath) {
        $msvcPath = Join-Path $vsPath "VC\Tools\MSVC"
        if (Test-Path $msvcPath) {
            $msvcVersion = Get-ChildItem $msvcPath | Sort-Object Name -Descending | Select-Object -First 1
            $msvcBin = Join-Path $msvcPath "$msvcVersion\bin\Hostx64\x64"
            if (Test-Path $msvcBin) {
                $env:PATH = "$msvcBin;$env:PATH"
                Write-Host "Using MSVC from: $msvcBin"
            }
        }
    }
}

if (-not $msvcPath) {
    Write-Warning "MSVC not found via vswhere, trying common paths..."
    $commonPaths = @(
        "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC",
        "C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Tools\MSVC",
        "C:\Program Files\Microsoft Visual Studio\2022\Enterprise\VC\Tools\MSVC",
        "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Tools\MSVC"
    )
    foreach ($base in $commonPaths) {
        if (Test-Path $base) {
            $msvcVersion = Get-ChildItem $base | Sort-Object Name -Descending | Select-Object -First 1
            $msvcBin = Join-Path $base "$msvcVersion\bin\Hostx64\x64"
            if (Test-Path $msvcBin) {
                $env:PATH = "$msvcBin;$env:PATH"
                Write-Host "Using MSVC from: $msvcBin"
                break
            }
        }
    }
}

# Set ASCII TEMP directory to avoid Chinese path issues
$env:TEMP = "C:\Temp"
$env:TMP = "C:\Temp"
if (-not (Test-Path "C:\Temp")) {
    New-Item -ItemType Directory -Path "C:\Temp" -Force | Out-Null
}

# Add MoonBit to PATH
$moonBin = "$env:USERPROFILE\.moon\bin"
if (Test-Path $moonBin) {
    $env:PATH = "$moonBin;$env:PATH"
}

# Verify MoonBit is available
try {
    $moonVersion = & moon version --all 2>&1
    Write-Host "MoonBit version: $moonVersion"
} catch {
    Write-Error "MoonBit not found in PATH. Please install from https://cli.moonbitlang.cn"
    exit 1
}

# Build
Write-Host "`nBuilding moonlog (native target)..."
& moon build --target native
if ($LASTEXITCODE -ne 0) {
    Write-Error "Build failed"
    exit $LASTEXITCODE
}

Write-Host "`nBuild successful!"
Write-Host "Binary location: target\native\release\build\cmd\main\moonlog.exe"

# Optionally run tests
if ($args -contains "--test") {
    Write-Host "`nRunning tests..."
    & moon test --target native
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Tests failed"
        exit $LASTEXITCODE
    }
    Write-Host "All tests passed!"
}
