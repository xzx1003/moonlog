# Windows packaging script for moonlog
# Creates a ZIP package with moonlog.exe, LICENSE, README.md, config/, fixtures/

param(
    [string]$Version = ""
)

$ErrorActionPreference = "Stop"

# Get version from moon.mod if not provided
if (-not $Version) {
    $moonMod = Get-Content "moon.mod" | ConvertFrom-Json
    $Version = $moonMod.version
}

# Determine platform
$arch = if ([Environment]::Is64BitOperatingSystem) { "x86_64" } else { "x86" }
$platform = "windows-$arch"
$packageName = "moonlog-v$Version-$platform"

Write-Host "Packaging $packageName..."

# Check if binary exists
$binaryPath = "target\native\release\build\cmd\main\moonlog.exe"
if (-not (Test-Path $binaryPath)) {
    Write-Error "Binary not found at $binaryPath. Run build.ps1 first."
    exit 1
}

# Create package directory
$packageDir = "dist\$packageName"
if (Test-Path $packageDir) {
    Remove-Item -Recurse -Force $packageDir
}
New-Item -ItemType Directory -Path $packageDir -Force | Out-Null

# Copy files
Write-Host "Copying files..."
Copy-Item $binaryPath $packageDir
Copy-Item "LICENSE" $packageDir -ErrorAction SilentlyContinue
Copy-Item "README.md" $packageDir -ErrorAction SilentlyContinue

if (Test-Path "config") {
    Copy-Item "config" $packageDir -Recurse
}

if (Test-Path "fixtures") {
    Copy-Item "fixtures" $packageDir -Recurse
}

# Create ZIP
Write-Host "Creating ZIP archive..."
$zipPath = "dist\$packageName.zip"
if (Test-Path $zipPath) {
    Remove-Item $zipPath -Force
}

Compress-Archive -Path "$packageDir\*" -DestinationPath $zipPath

# Create SHA-256 checksum
Write-Host "Generating SHA-256 checksum..."
$hash = Get-FileHash $zipPath -Algorithm SHA256
$hashLine = "$($hash.Hash)  $packageName.zip"
$hashLine | Out-File "dist\$packageName.zip.sha256" -Encoding ASCII

Write-Host "`nPackage created successfully!"
Write-Host "  ZIP: $zipPath"
Write-Host "  SHA: dist\$packageName.zip.sha256"
Write-Host "`nTo verify:"
Write-Host "  Get-FileHash $zipPath -Algorithm SHA256"
Write-Host "`nTo extract:"
Write-Host "  Expand-Archive $zipPath -DestinationPath moonlog"

# Cleanup
Remove-Item -Recurse -Force $packageDir
