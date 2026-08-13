<#
.SYNOPSIS
    Chakravyuh task runner for Windows (PowerShell equivalent of the Makefile).

.DESCRIPTION
    Kept deliberately in sync with the Makefile. Use this on Windows, where
    GNU make is usually not installed.

.EXAMPLE
    .\run.ps1 setup      # install backend + frontend dependencies
    .\run.ps1 data       # generate the synthetic transaction dataset
    .\run.ps1 train      # train the detectors
    .\run.ps1 test       # run the backend test suite
    .\run.ps1 dev        # start backend and frontend together
#>
param(
    [Parameter(Position = 0)]
    [ValidateSet('setup', 'data', 'train', 'test', 'dev', 'backend', 'frontend', 'clean')]
    [string]$Task = 'dev'
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'

function Invoke-In([string]$dir, [scriptblock]$block) {
    Push-Location $dir
    try { & $block } finally { Pop-Location }
}

switch ($Task) {
    'setup' {
        Write-Host 'Installing backend dependencies...' -ForegroundColor Cyan
        Invoke-In $backend { pip install -r requirements.txt }
        Write-Host 'Installing frontend dependencies...' -ForegroundColor Cyan
        Invoke-In $frontend { npm install }
        Write-Host 'Setup complete.' -ForegroundColor Green
    }

    'data' {
        Invoke-In $backend { python -m app.simulator.generator }
    }

    'train' {
        Invoke-In $backend { python -m app.detect.train }
    }

    'test' {
        Invoke-In $backend { pytest }
    }

    'backend' {
        Invoke-In $backend { uvicorn app.main:app --reload --port 8000 }
    }

    'frontend' {
        Invoke-In $frontend { npm run dev }
    }

    'dev' {
        # Backend in its own window so both logs stay readable.
        Write-Host 'Starting backend on http://127.0.0.1:8000 ...' -ForegroundColor Cyan
        Start-Process powershell -ArgumentList @(
            '-NoExit', '-Command',
            "Set-Location '$backend'; uvicorn app.main:app --reload --port 8000"
        )
        Start-Sleep -Seconds 2
        Write-Host 'Starting frontend on http://127.0.0.1:5173 ...' -ForegroundColor Cyan
        Invoke-In $frontend { npm run dev }
    }

    'clean' {
        foreach ($d in @((Join-Path $backend 'data'), (Join-Path $backend 'models'))) {
            if (Test-Path $d) { Remove-Item -Recurse -Force $d -Confirm:$false }
        }
        Write-Host 'Generated data and models removed.' -ForegroundColor Green
    }
}