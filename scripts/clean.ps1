# Kill leftover HermesProxy processes
Get-CimInstance Win32_Process |
Where-Object { $_.CommandLine -like '*D:\HermesProxy\HermesProxy.py*' } |
ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

# Kill leftover Agent processes
Get-CimInstance Win32_Process |
Where-Object { $_.CommandLine -like '*D:\HermesProxy\EtherCATAnalyzerAgent\main.py*' } |
ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

# Confirm port 5000 is free
Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue