$root = Split-Path -Parent $PSScriptRoot

$python = Join-Path $root ".venv\Scripts\python.exe"
$proxy = Join-Path $root "HermesProxy.py"
$agent = Join-Path $PSScriptRoot "main.py"
$proxyProcess = $null
$agentExitCode = 0

try {
    Write-Host "Starting Delta LLM Proxy..."

    $proxyProcess = Start-Process `
        -FilePath $python `
        -ArgumentList "`"$proxy`"" `
        -WindowStyle Hidden `
        -PassThru

    Write-Host "Waiting for proxy..."

    $ready = $false

    for ($i = 0; $i -lt 20; $i++) {
        if ($proxyProcess.HasExited) {
            throw "Proxy exited before becoming ready."
        }

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
    $agentExitCode = $LASTEXITCODE
}
finally {
    if ($null -ne $proxyProcess -and -not $proxyProcess.HasExited) {
        Write-Host "Stopping Delta LLM Proxy..."
        & taskkill.exe /PID $proxyProcess.Id /T /F | Out-Null
    }
}

exit $agentExitCode
