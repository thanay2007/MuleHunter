<#
.SYNOPSIS
    Chakravyuh task runner for Windows (PowerShell equivalent of the Makefile).

.DESCRIPTION
    Kept deliberately in sync with the Makefile. Use this on Windows, where
    GNU make is usually not installed.

.EXAMPLE
    .\run.ps1 setup      # install backend + frontend dependencies
    .\run.ps1 data       # generate the synthetic transaction dataset (~2s)
    .\run.ps1 train      # train the detection tiers (~4 min)
    .\run.ps1 bench      # run the 200-incident benchmark (~45 min, optional)
    .\run.ps1 all        # data + train, everything the demo needs
    .\run.ps1 test       # run the backend test suite
    .\run.ps1 dev        # start backend and frontend together
    .\run.ps1 demo       # check artifacts, boot both, wait for the API, open the browser
#>
param(
    [Parameter(Position = 0)]
    [ValidateSet('setup', 'data', 'train', 'bench', 'all', 'test', 'dev', 'demo',
                 'backend', 'frontend', 'clean')]
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

    'bench' {
        Invoke-In $backend { python -m app.eval.harness }
    }

    'all' {
        # Everything the demo needs, in order. The benchmark is deliberately
        # excluded -- it takes 45 minutes and the console runs without it.
        Invoke-In $backend {
            python -m app.simulator.generator
            python -m app.detect.train
        }
        Write-Host 'Ready. Run: .\run.ps1 dev' -ForegroundColor Green
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

    'demo' {
        # One command for the stage. Checks the artifacts exist, starts the
        # backend, waits until it actually answers, then starts the frontend
        # and opens the browser. Fumbling with two terminals in front of judges
        # is a bad way to spend the first thirty seconds.
        $missing = @()
        foreach ($artifact in @(
            (Join-Path $backend 'data\transactions.parquet'),
            (Join-Path $backend 'data\accounts.parquet'),
            (Join-Path $backend 'models\gbdt.txt')
        )) {
            if (-not (Test-Path $artifact)) { $missing += $artifact }
        }
        if ($missing.Count -gt 0) {
            Write-Host 'Missing build artifacts:' -ForegroundColor Yellow
            $missing | ForEach-Object { Write-Host "  $_" }
            Write-Host 'Run this first:  .\run.ps1 all' -ForegroundColor Yellow
            exit 1
        }

        Write-Host 'Starting backend...' -ForegroundColor Cyan
        Start-Process powershell -ArgumentList @(
            '-NoExit', '-Command',
            "Set-Location '$backend'; uvicorn app.main:app --reload --port 8000"
        )

        # The backend warms the S1 incident context on startup, so this is a
        # real wait rather than a token one.
        Write-Host 'Waiting for the API...' -NoNewline
        $ready = $false
        foreach ($attempt in 1..60) {
            try {
                $response = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/health' `
                    -UseBasicParsing -TimeoutSec 2
                if ($response.StatusCode -eq 200) { $ready = $true; break }
            } catch {
                Start-Sleep -Seconds 1
                Write-Host '.' -NoNewline
            }
        }
        Write-Host ''
        if (-not $ready) {
            Write-Host 'The API never answered. Check the backend window.' -ForegroundColor Red
            exit 1
        }
        Write-Host 'API ready.' -ForegroundColor Green

        Start-Process powershell -ArgumentList @(
            '-NoExit', '-Command',
            "Set-Location '$frontend'; npm run dev"
        )
        Start-Sleep -Seconds 4
        Start-Process 'http://localhost:5173'
        Write-Host 'Demo is up: http://localhost:5173' -ForegroundColor Green
        Write-Host 'Beat sheet: DEMO_SCRIPT.md' -ForegroundColor Green
    }

    'clean' {
        foreach ($d in @((Join-Path $backend 'data'), (Join-Path $backend 'models'))) {
            if (Test-Path $d) { Remove-Item -Recurse -Force $d -Confirm:$false }
        }
        Write-Host 'Generated data and models removed.' -ForegroundColor Green
    }
}