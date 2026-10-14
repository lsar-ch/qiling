# Build the Windows x64 NSIS installer: freeze sidecar + stage home + Tauri build.
# Usage (repo root): powershell -File scripts/package/build-windows.ps1
$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Res = Join-Path $Root "apps\desktop\src-tauri\resources"
$Python = Join-Path $Root ".venv\Scripts\python.exe"

Write-Host "== 1/4 build web"
Push-Location (Join-Path $Root "apps\web")
npm run build
Pop-Location

Write-Host "== 2/4 freeze ai-service (PyInstaller onedir)"
Push-Location (Join-Path $Root "services\ai-service")
& $Python -m PyInstaller ai-service.spec --noconfirm `
  --distpath (Join-Path $Root "build\sidecar\dist") `
  --workpath (Join-Path $Root "build\sidecar\work")
if ($LASTEXITCODE -ne 0) { exit 1 }
Pop-Location

Write-Host "== 3/4 stage src-tauri/resources"
$runtime = Join-Path $Res "runtime\ai-service"
$homeTemplate = Join-Path $Res "home-template"
if (Test-Path $runtime) { Remove-Item -Recurse -Force $runtime }
if (Test-Path $homeTemplate) { Remove-Item -Recurse -Force $homeTemplate }
New-Item -ItemType Directory -Force -Path (Join-Path $Res "runtime") | Out-Null

$sidecarSrc = Join-Path $Root "build\sidecar\dist\ai-service"
if (-not (Test-Path (Join-Path $sidecarSrc "ai-service.exe"))) {
    Write-Error "frozen sidecar missing: $sidecarSrc\ai-service.exe"
    exit 1
}
# robocopy handles the very long playwright paths inside the frozen tree.
robocopy $sidecarSrc $runtime /E /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { Write-Error "robocopy failed: $LASTEXITCODE"; exit 1 }
if (-not (Test-Path (Join-Path $runtime "ai-service.exe"))) {
    Write-Error "sidecar missing after copy: $runtime\ai-service.exe"
    exit 1
}

& $Python (Join-Path $Root "scripts\package\stage_home.py") $homeTemplate
if ($LASTEXITCODE -ne 0) { exit 1 }
if (-not (Test-Path (Join-Path $homeTemplate "config\settings.yaml"))) {
    Write-Error "home template missing settings.yaml"
    exit 1
}
Write-Host "resources staged"

Write-Host "== 4/4 Tauri build (x64 NSIS)"
Push-Location (Join-Path $Root "apps\desktop")
npm run tauri -- build --config src-tauri/tauri.release.json --target x86_64-pc-windows-msvc --bundles nsis
if ($LASTEXITCODE -ne 0) { exit 1 }
Pop-Location
