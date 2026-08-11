$root = Split-Path -Parent $PSScriptRoot

$python = Join-Path $root ".venv\Scripts\python.exe"
$proxy = Join-Path $root "HermesProxy.py"
$agent = Join-Path $PSScriptRoot "main.py"

Write-Host "Starting Delta LLM Proxy..."

Start-Process powershell.exe -WindowStyle Hidden -ArgumentList `
    "-NoProfile", `
    "-Command", `
    "& `"$python`" `"$proxy`""

Write-Host "Waiting for proxy..."

$ready = $false

for ($i = 0; $i -lt 20; $i++) {
    try {
        Invoke-RestMethod "http://127.0.0.1:5000/health" | Out-Null
        Write-Host "Proxy ready."
        $ready = $true
        break
    }
    catch {
        Start-Sleep -Seconds 1
    }
}

if (-not $ready) {
    throw "Proxy did not become healthy within the expected wait period."
}

Write-Host "Starting EtherCAT Analyzer Agent..."
& $python $agent
