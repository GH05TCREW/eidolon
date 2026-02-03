Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Test-Command {
    param([string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

$shellExe = if (Test-Command "pwsh") { "pwsh" } else { "powershell" }

if (-not (Test-Command "docker")) {
    Write-Error "docker is required but was not found on PATH."
    exit 1
}
if (-not (Test-Command "python")) {
    Write-Error "python is required but was not found on PATH."
    exit 1
}
if (-not (Test-Command "npm")) {
    Write-Error "npm is required but was not found on PATH."
    exit 1
}

Write-Host "Starting database containers..."
& docker compose up -d

$venvPath = Join-Path $repoRoot "venv"
$pythonExe = Join-Path $venvPath "Scripts\\python.exe"
if (-not (Test-Path $pythonExe)) {
    Write-Host "Creating virtual environment..."
    & python -m venv $venvPath
}

$needsInstall = $false
try {
    & $pythonExe -c "import fastapi, uvicorn, psycopg, neo4j" 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        $needsInstall = $true
    }
} catch {
    $needsInstall = $true
}
if ($needsInstall) {
    Write-Host "Installing Python dependencies..."
    & $pythonExe -m pip install --upgrade pip
    & $pythonExe -m pip install -e .
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to install Python dependencies. Check the output above."
        exit 1
    }
}

$uiDir = Join-Path $repoRoot "eidolon\\ui"
$nodeModules = Join-Path $uiDir "node_modules"
if (-not (Test-Path $nodeModules)) {
    Write-Host "Installing UI dependencies..."
    & npm install --prefix $uiDir
}

Write-Host "Starting API server..."
$apiCmd = "& `"$pythonExe`" -m uvicorn eidolon.api.app:app --reload --port 8080"
Start-Process -FilePath $shellExe -ArgumentList "-NoExit","-Command",$apiCmd -WorkingDirectory $repoRoot | Out-Null

Write-Host "Starting UI dev server..."
$uiCmd = "Set-Location `"$uiDir`"; npm run dev"
Start-Process -FilePath $shellExe -ArgumentList "-NoExit","-Command",$uiCmd -WorkingDirectory $uiDir | Out-Null

Write-Host "Done."
Write-Host "API: http://localhost:8080"
Write-Host "UI: http://localhost:5173"
