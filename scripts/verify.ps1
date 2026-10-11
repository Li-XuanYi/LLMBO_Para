param(
    [string]$PythonExe = "C:\Users\aa133\AppData\Local\Programs\Python\Python312\python.exe"
)

$ErrorActionPreference = "Continue"
$workspace = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$stamp = [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ")
$runId = "{0}_{1}" -f $stamp, [Guid]::NewGuid().ToString('N').Substring(0,8)
$logDir = Join-Path $workspace (Join-Path "runs\verification" $runId)
New-Item -ItemType Directory -Path $logDir -ErrorAction Stop | Out-Null
$oldPythonPath = $env:PYTHONPATH
$oldThreads = @{}
$threadNames = @("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS")
foreach ($name in $threadNames) {
    $oldThreads[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
    [Environment]::SetEnvironmentVariable($name, "1", "Process")
}
$env:PYTHONPATH = Join-Path $workspace "src"
$overall = 0
$summary = [ordered]@{verification_directory=$logDir; workspace=$workspace; python=$PythonExe}
Start-Transcript -Path (Join-Path $logDir "transcript.txt") | Out-Null
try {
    @("workspace=$workspace", "python=$PythonExe", "PYTHONPATH=$env:PYTHONPATH",
      "OPENBLAS_NUM_THREADS=1", "MKL_NUM_THREADS=1", "OMP_NUM_THREADS=1") |
        Set-Content (Join-Path $logDir "command-and-environment.txt") -Encoding utf8
    & $PythonExe --version 2>&1 | Tee-Object -FilePath (Join-Path $logDir "python-version.txt")
    & $PythonExe -m pip freeze 2>&1 | Set-Content (Join-Path $logDir "python-packages.txt") -Encoding utf8
    if ($LASTEXITCODE -ne 0) { $overall = 1 }

    "test: $PythonExe -X utf8 -B -m unittest discover -s $workspace\tests -v" |
        Add-Content (Join-Path $logDir "command-and-environment.txt") -Encoding utf8
    & $PythonExe -X utf8 -B -m unittest discover -s (Join-Path $workspace "tests") -v 2>&1 |
        Tee-Object -FilePath (Join-Path $logDir "tests.txt")
    $summary.test_exit_code = $LASTEXITCODE
    if ($summary.test_exit_code -ne 0) { $overall = 1 }

    "preflight: $PythonExe -X utf8 -B -m llmbo_para preflight $workspace\configs\research-template.json --output $workspace\runs\preflight" |
        Add-Content (Join-Path $logDir "command-and-environment.txt") -Encoding utf8
    $preflightText = & $PythonExe -X utf8 -B -m llmbo_para preflight (Join-Path $workspace "configs\research-template.json") --output (Join-Path $workspace "runs\preflight") 2>&1
    $summary.preflight_exit_code = $LASTEXITCODE
    $preflightText | Tee-Object -FilePath (Join-Path $logDir "expected-incomplete-config.txt")
    $preflightReport = ($preflightText -join [Environment]::NewLine) | ConvertFrom-Json -ErrorAction Stop
    $summary.preflight_directory = $preflightReport.run_directory
    if ($summary.preflight_exit_code -ne 2 -or $preflightReport.ready -or $preflightReport.errors.Count -eq 0 -or
        $preflightReport.battery_simulations_made -ne 0 -or $preflightReport.paid_api_calls_made -ne 0) { $overall = 1 }

    "demo: $PythonExe -X utf8 -B -m llmbo_para demo --output $workspace\runs\synthetic --budget 5" |
        Add-Content (Join-Path $logDir "command-and-environment.txt") -Encoding utf8
    $demoText = & $PythonExe -X utf8 -B -m llmbo_para demo --output (Join-Path $workspace "runs\synthetic") --budget 5 2>&1
    $summary.demo_exit_code = $LASTEXITCODE
    $demoText | Tee-Object -FilePath (Join-Path $logDir "demo.txt")
    if ($summary.demo_exit_code -ne 0) { $overall = 1 }
    else {
        $demoReport = ($demoText -join [Environment]::NewLine) | ConvertFrom-Json -ErrorAction Stop
        $summary.demo_directory = $demoReport.run_directory
        "status: $PythonExe -X utf8 -B -m llmbo_para status $($demoReport.run_directory)" |
            Add-Content (Join-Path $logDir "command-and-environment.txt") -Encoding utf8
        & $PythonExe -X utf8 -B -m llmbo_para status $demoReport.run_directory 2>&1 |
            Tee-Object -FilePath (Join-Path $logDir "status.txt")
        $summary.status_exit_code = $LASTEXITCODE
        if ($summary.status_exit_code -ne 0) { $overall = 1 }
        "audit: $PythonExe -X utf8 -B -m llmbo_para audit-run $($demoReport.run_directory) --deep --output $workspace\runs\result-audits" |
            Add-Content (Join-Path $logDir "command-and-environment.txt") -Encoding utf8
        $auditText = & $PythonExe -X utf8 -B -m llmbo_para audit-run $demoReport.run_directory --deep --output (Join-Path $workspace "runs\result-audits") 2>&1
        $summary.audit_exit_code = $LASTEXITCODE
        $auditText | Tee-Object -FilePath (Join-Path $logDir "deep-audit.txt")
        if ($summary.audit_exit_code -ne 0) { $overall = 1 }
        else {
            $auditReport = ($auditText -join [Environment]::NewLine) | ConvertFrom-Json -ErrorAction Stop
            $summary.result_audit_directory = $auditReport.audit_directory
        }
    }
    Get-ChildItem -LiteralPath (Join-Path $workspace "src"), (Join-Path $workspace "configs"), (Join-Path $workspace "tests"), (Join-Path $workspace "scripts"), (Join-Path $workspace "docs"), (Join-Path $workspace "README.md"), (Join-Path $workspace "pyproject.toml"), (Join-Path $workspace "requirements-py312.lock"), (Join-Path $workspace ".gitignore") -Recurse -File |
        Where-Object { $_.FullName -notmatch '[\\/]__pycache__[\\/]' } | Get-FileHash -Algorithm SHA256 |
        ForEach-Object { "$($_.Hash.ToLower())  $($_.Path)" } |
        Set-Content (Join-Path $logDir "source-sha256.txt") -Encoding utf8
}
catch {
    $overall = 1
    $_ | Out-String | Set-Content (Join-Path $logDir "verification-error.txt") -Encoding utf8
    Write-Output $_
}
finally {
    $summary.overall_exit_code = $overall
    $summary | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $logDir "verification-summary.json") -Encoding utf8
    Write-Output "verification_log=$logDir"
    Stop-Transcript | Out-Null
    $env:PYTHONPATH = $oldPythonPath
    foreach ($name in $threadNames) {
        [Environment]::SetEnvironmentVariable($name, $oldThreads[$name], "Process")
    }
}
exit $overall
