# 出 Windows x64 NSIS 安装包：冻结 sidecar + home 模板 + Tauri build。
# 用法（仓库根目录）：powershell -File scripts/package/build-windows.ps1
$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Res = Join-Path $Root "apps\desktop\src-tauri\resources"
$Python = Join-Path $Root ".venv\Scripts\python.exe"

Write-Host "== 1/4 主界面构建"
Push-Location (Join-Path $Root "apps\web")
npm run build
Pop-Location

Write-Host "== 2/4 冻结 ai-service（PyInstaller onedir）"
Push-Location (Join-Path $Root "services\ai-service")
& $Python -m PyInstaller ai-service.spec --noconfirm `
  --distpath (Join-Path $Root "build\sidecar\dist") `
  --workpath (Join-Path $Root "build\sidecar\work")
if ($LASTEXITCODE -ne 0) { exit 1 }
Pop-Location

Write-Host "== 3/4 组装 src-tauri/resources"
$runtime = Join-Path $Res "runtime\ai-service"
$home = Join-Path $Res "home-template"
if (Test-Path $runtime) { Remove-Item -Recurse -Force $runtime }
if (Test-Path $home) { Remove-Item -Recurse -Force $home }
New-Item -ItemType Directory -Force -Path (Join-Path $Res "runtime") | Out-Null
Copy-Item -Recurse (Join-Path $Root "build\sidecar\dist\ai-service") $runtime
& $Python (Join-Path $Root "scripts\package\stage_home.py") $home
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "== 4/4 Tauri 构建（x64 NSIS）"
Push-Location (Join-Path $Root "apps\desktop")
npm run tauri -- build --config src-tauri/tauri.release.json --target x86_64-pc-windows-msvc --bundles nsis
Pop-Location
