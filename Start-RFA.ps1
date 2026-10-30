$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$backendDir = Join-Path $root 'go-app'
$clientDir = Join-Path $root 'client'
$runtimeDir = Join-Path $backendDir '.runtime\desktop-launcher'
$logDir = Join-Path $runtimeDir 'logs'
$backendBinary = Join-Path $runtimeDir 'go-app-current.exe'
$iisAssembly = Join-Path $env:SystemRoot 'System32\inetsrv\Microsoft.Web.Administration.dll'
$goPath = 'C:\Program Files\Go\bin\go.exe'
$nodePath = 'C:\Program Files\nodejs\node.exe'
$viteEntry = Join-Path $clientDir 'node_modules\vite\bin\vite.js'
$script:sessionTag = '{0}-{1}' -f $PID, (Get-Date -Format 'yyyyMMdd-HHmmssfff')
$script:transcriptPath = Join-Path $runtimeDir "launcher-session-$($script:sessionTag).log"
$script:eventLogPath = Join-Path $logDir "launcher-events-$($script:sessionTag).log"
$script:backendProcess = $null
$script:frontendProcess = $null
$script:sitesManaged = $false

New-Item -ItemType Directory -Path $logDir -Force | Out-Null
Start-Transcript -Path $script:transcriptPath | Out-Null
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
if (-not (Test-Path $goPath)) { throw "Go executable not found: $goPath" }
if (-not (Test-Path $nodePath)) { throw "Node executable not found: $nodePath" }

function Write-LauncherEvent([string]$message) {
    try {
        $line = "$(Get-Date -Format o) $message`r`n"
        [System.IO.File]::AppendAllText(
            $script:eventLogPath, $line, [System.Text.UTF8Encoding]::new($false)
        )
    } catch { }
}

$form = New-Object System.Windows.Forms.Form
$form.Text = 'RFA | راه‌انداز سایت'
$form.StartPosition = 'CenterScreen'
$form.Size = New-Object System.Drawing.Size(590, 390)
$form.MinimumSize = $form.Size
$form.MaximizeBox = $false
$form.FormBorderStyle = 'FixedDialog'
$form.RightToLeft = 'Yes'
$form.RightToLeftLayout = $true
$form.Font = New-Object System.Drawing.Font('Segoe UI', 10)

$title = New-Object System.Windows.Forms.Label
$title.Text = 'راه‌انداز سایت RFA'
$title.Font = New-Object System.Drawing.Font('Segoe UI', 19, [System.Drawing.FontStyle]::Bold)
$title.Location = New-Object System.Drawing.Point(25, 22)
$title.Size = New-Object System.Drawing.Size(525, 42)
$title.TextAlign = 'MiddleCenter'
$form.Controls.Add($title)

$description = New-Object System.Windows.Forms.Label
$description.Text = 'نسخه‌ی روز فرانت‌اند و بک‌اند را اجرا می‌کند و سایت‌های RFA را در IIS بالا می‌آورد.'
$description.Location = New-Object System.Drawing.Point(35, 72)
$description.Size = New-Object System.Drawing.Size(505, 48)
$description.TextAlign = 'MiddleCenter'
$form.Controls.Add($description)

$status = New-Object System.Windows.Forms.Label
$status.Text = 'وضعیت: خاموش'
$status.Location = New-Object System.Drawing.Point(35, 126)
$status.Size = New-Object System.Drawing.Size(505, 32)
$status.TextAlign = 'MiddleCenter'
$status.ForeColor = [System.Drawing.Color]::DimGray
$form.Controls.Add($status)

function New-ActionButton([string]$text, [int]$x, [int]$y, [int]$width) {
    $button = New-Object System.Windows.Forms.Button
    $button.Text = $text
    $button.Location = New-Object System.Drawing.Point($x, $y)
    $button.Size = New-Object System.Drawing.Size($width, 44)
    $form.Controls.Add($button)
    return $button
}

$startButton = New-ActionButton 'شروع همه' 355 178 170
$restartButton = New-ActionButton 'ری‌استارت بک‌اند' 175 178 170
$openButton = New-ActionButton 'باز کردن سایت' 355 234 170
$stopButton = New-ActionButton 'خاموش کردن همه' 175 234 170
$logsButton = New-ActionButton 'پوشه‌ی لاگ‌ها' 240 292 170

function Test-Listening([int]$port) {
    # .NET Framework on Windows PowerShell may resolve localhost to IPv4 first,
    # while Vite's localhost listener is only on ::1. Probe both loopbacks.
    foreach ($address in @([System.Net.IPAddress]::IPv6Loopback, [System.Net.IPAddress]::Loopback)) {
        $client = [System.Net.Sockets.TcpClient]::new($address.AddressFamily)
        try {
            $connection = $client.BeginConnect($address, $port, $null, $null)
            if (-not $connection.AsyncWaitHandle.WaitOne(500)) { continue }
            $client.EndConnect($connection)
            if ($client.Connected) { return $true }
        } catch {
        } finally {
            $client.Close()
        }
    }
    return $false
}

function Get-PortOwner([int]$port) {
    $connection = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $connection) { return $null }
    return Get-CimInstance Win32_Process -Filter "ProcessId = $($connection.OwningProcess)" -ErrorAction SilentlyContinue
}

function Stop-ProcessTree([int]$processId) {
    if ($processId -le 0) { return }
    & "$env:SystemRoot\System32\taskkill.exe" /PID $processId /T /F | Out-Null
}

function Stop-ManagedProcess($process) {
    if ($null -eq $process) { return }
    try {
        $process.Refresh()
        if (-not $process.HasExited) {
            Stop-ProcessTree $process.Id
            $process.WaitForExit(5000) | Out-Null
        }
    } catch { }
}

function Get-RfaSites($manager) {
    $wantedHosts = @('rfa.systemgroup.net', 'rfa_back.systemgroup.net')
    $matches = @($manager.Sites | Where-Object {
        $site = $_
        @($site.Bindings | Where-Object { $wantedHosts -contains ([string]$_.Host).ToLowerInvariant() }).Count -gt 0
    })
    if ($matches.Count -ne 2) {
        throw "IIS باید دقیقاً دو سایت با bindingهای RFA و RFA_BACK داشته باشد؛ تعداد پیدا‌شده: $($matches.Count)."
    }
    return $matches
}

function Set-RfaSites([string]$action) {
    if (-not (Test-Path $iisAssembly)) { throw 'ابزار مدیریت IIS در این ویندوز پیدا نشد.' }
    Add-Type -Path $iisAssembly -ErrorAction SilentlyContinue
    $manager = New-Object Microsoft.Web.Administration.ServerManager
    try {
        $sites = Get-RfaSites $manager
        $appcmd = Join-Path $env:SystemRoot 'System32\inetsrv\appcmd.exe'
        $poolNames = @($sites | ForEach-Object { $_.Applications } |
            ForEach-Object { $_.ApplicationPoolName } | Where-Object { $_ } | Sort-Object -Unique)
        if ($action -eq 'stop') {
            foreach ($site in $sites) {
                if ([string]$site.State -ne 'Stopped') {
                    & $appcmd stop site $site.Name | Out-Null
                    if ($LASTEXITCODE -ne 0) { throw "IIS نتوانست سایت $($site.Name) را متوقف کند." }
                }
            }
            foreach ($poolName in $poolNames) {
                $pool = $manager.ApplicationPools[$poolName]
                if ($pool -and [string]$pool.State -ne 'Stopped') {
                    & $appcmd stop apppool $poolName | Out-Null
                    if ($LASTEXITCODE -ne 0) { throw "IIS نتوانست application pool $poolName را متوقف کند." }
                }
            }
        } elseif ($action -eq 'start') {
            foreach ($poolName in $poolNames) {
                $pool = $manager.ApplicationPools[$poolName]
                if ($pool -and [string]$pool.State -ne 'Started') {
                    & $appcmd start apppool $poolName | Out-Null
                    if ($LASTEXITCODE -ne 0) { throw "IIS نتوانست application pool $poolName را اجرا کند." }
                }
            }
            foreach ($site in $sites) {
                if ([string]$site.State -ne 'Started') {
                    & $appcmd start site $site.Name | Out-Null
                    if ($LASTEXITCODE -ne 0) { throw "IIS نتوانست سایت $($site.Name) را اجرا کند." }
                }
            }
        }
    } finally {
        $manager.Dispose()
    }
}

function Get-ExistingProjectPids {
    $result = @{ Backend = 0; Frontend = 0 }
    $backendOwner = Get-PortOwner 5000
    if ($backendOwner) {
        $expectedBackends = @(
            [IO.Path]::GetFullPath($backendBinary),
            [IO.Path]::GetFullPath((Join-Path $backendDir 'go-app.exe'))
        )
        $ownerPath = if ($backendOwner.ExecutablePath) {
            [IO.Path]::GetFullPath($backendOwner.ExecutablePath)
        } else { '' }
        if ($ownerPath -and ($expectedBackends -icontains $ownerPath)) {
            $result.Backend = [int]$backendOwner.ProcessId
        } else {
            throw "پورت ۵۰۰۰ در اختیار برنامه‌ای غیر از بک‌اند این پروژه است؛ آن را متوقف نکردم."
        }
    }
    $frontendOwner = Get-PortOwner 3000
    if ($frontendOwner) {
        $cmd = [string]$frontendOwner.CommandLine
        if ($frontendOwner.ExecutablePath -ieq $nodePath -and $cmd.Contains($clientDir) -and $cmd.Contains('vite')) {
            $result.Frontend = [int]$frontendOwner.ProcessId
        } else {
            throw "پورت ۳۰۰۰ در اختیار برنامه‌ای غیر از فرانت‌اند این پروژه است؛ آن را متوقف نکردم."
        }
    }
    return $result
}

function Build-Backend {
    $script:stagedBackendBinary = Join-Path $runtimeDir "go-app-staged-$PID.exe"
    Remove-Item -LiteralPath $script:stagedBackendBinary -Force -ErrorAction SilentlyContinue
    $build = Start-Process -FilePath $goPath -ArgumentList @('build', '-o', $script:stagedBackendBinary, '.') `
        -WorkingDirectory $backendDir -WindowStyle Hidden -PassThru -Wait `
        -RedirectStandardOutput (Join-Path $logDir 'build.out.log') `
        -RedirectStandardError (Join-Path $logDir 'build.err.log')
    if ($build.ExitCode -ne 0 -or -not (Test-Path $script:stagedBackendBinary)) {
        throw "ساخت بک‌اند ناموفق بود؛ فایل‌های build.err.log در پوشه‌ی لاگ را ببینید."
    }
}

function Install-BuiltBackend {
    if (-not $script:stagedBackendBinary -or -not (Test-Path $script:stagedBackendBinary)) {
        throw 'نسخه‌ی ساخته‌شده‌ی بک‌اند برای نصب پیدا نشد.'
    }
    if (Test-Path $backendBinary) {
        $backupBackendBinary = Join-Path $runtimeDir "go-app-backup-$PID.exe"
        Remove-Item -LiteralPath $backupBackendBinary -Force -ErrorAction SilentlyContinue
        [System.IO.File]::Move($backendBinary, $backupBackendBinary)
        try {
            [System.IO.File]::Move($script:stagedBackendBinary, $backendBinary)
        } catch {
            if ((Test-Path $backupBackendBinary) -and -not (Test-Path $backendBinary)) {
                [System.IO.File]::Move($backupBackendBinary, $backendBinary)
            }
            throw
        }
        Remove-Item -LiteralPath $backupBackendBinary -Force -ErrorAction SilentlyContinue
    } else {
        [System.IO.File]::Move($script:stagedBackendBinary, $backendBinary)
    }
    $script:stagedBackendBinary = $null
}

function Start-Backend {
    $previousPort = $env:PORT
    $env:PORT = '5000'
    try {
        $script:backendProcess = Start-Process -FilePath $backendBinary -WorkingDirectory $backendDir `
            -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $logDir 'backend.out.log') `
            -RedirectStandardError (Join-Path $logDir 'backend.err.log')
    } finally {
        $env:PORT = $previousPort
    }
}

function Start-Frontend {
    # Keep the site's configured public API hostname. Using localhost here
    # would make remote browsers call their own machine instead of the server.
    $previousApiBase = $env:VITE_API_BASE
    Remove-Item Env:VITE_API_BASE -ErrorAction SilentlyContinue
    try {
        $script:frontendProcess = Start-Process -FilePath $nodePath `
            -ArgumentList @($viteEntry, '--host', 'localhost', '--port', '3000', '--strictPort') `
            -WorkingDirectory $clientDir -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $logDir 'frontend.out.log') `
            -RedirectStandardError (Join-Path $logDir 'frontend.err.log')
    } finally {
        if ($null -ne $previousApiBase) { $env:VITE_API_BASE = $previousApiBase }
    }
}

function Stop-AllRfaServices {
    $readyTimer.Stop()
    if ($script:sitesManaged) {
        try {
            Set-RfaSites 'stop'
            $script:sitesManaged = $false
        } catch {
            $status.Text = 'وضعیت: خاموش‌کردن IIS ناموفق بود'
            $status.ForeColor = [System.Drawing.Color]::Firebrick
            [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'IIS متوقف نشد', 'OK', 'Error') | Out-Null
            return $false
        }
    }
    Stop-ManagedProcess $script:frontendProcess
    Stop-ManagedProcess $script:backendProcess
    $script:frontendProcess = $null
    $script:backendProcess = $null
    $status.Text = 'وضعیت: خاموش — سایت RFA از دسترس خارج است'
    $status.ForeColor = [System.Drawing.Color]::DimGray
    $startButton.Enabled = $true
    $restartButton.Enabled = $false
    $openButton.Enabled = $false
    $stopButton.Enabled = $false
    return $true
}

function Start-AllRfaServices {
    if ($script:backendProcess -or $script:frontendProcess) { return }
    if (-not (Test-Path (Join-Path $backendDir '.env'))) {
        [System.Windows.Forms.MessageBox]::Show('فایل go-app\.env پیدا نشد.', 'تنظیمات بک‌اند', 'OK', 'Error') | Out-Null
        return
    }
    if (-not (Test-Path $viteEntry)) {
        [System.Windows.Forms.MessageBox]::Show('وابستگی‌های فرانت‌اند نصب نیستند؛ ابتدا npm install را در client اجرا کنید.', 'فرانت‌اند آماده نیست', 'OK', 'Error') | Out-Null
        return
    }
    try {
        $existing = Get-ExistingProjectPids
        $status.Text = 'در حال ساخت نسخه‌ی تازه‌ی بک‌اند…'
        $status.ForeColor = [System.Drawing.Color]::DarkOrange
        $form.Refresh()
        Build-Backend

        $status.Text = 'در حال راه‌اندازی بک‌اند و فرانت‌اند…'
        $form.Refresh()
        Set-RfaSites 'stop'
        $script:sitesManaged = $true
        if ($existing.Backend) { Stop-ProcessTree $existing.Backend }
        if ($existing.Frontend) { Stop-ProcessTree $existing.Frontend }
        Start-Sleep -Milliseconds 500
        Install-BuiltBackend
        Start-Backend
        Start-Frontend
        $startButton.Enabled = -not $script:sitesManaged
        $restartButton.Enabled = $true
        $openButton.Enabled = $false
        $stopButton.Enabled = $true
        $status.Text = 'در حال آماده‌شدن سرویس‌ها…'
        $readyTimer.Start()
    } catch {
        Write-LauncherEvent "startup error: $($_.Exception.ToString())"
        $readyTimer.Stop()
        Stop-ManagedProcess $script:frontendProcess
        Stop-ManagedProcess $script:backendProcess
        $script:frontendProcess = $null
        $script:backendProcess = $null
        $status.Text = 'وضعیت: شروع ناموفق بود'
        $status.ForeColor = [System.Drawing.Color]::Firebrick
        $startButton.Enabled = $true
        $restartButton.Enabled = $false
        $openButton.Enabled = $false
        $stopButton.Enabled = [bool]$script:sitesManaged
        [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'خطا در راه‌اندازی RFA', 'OK', 'Error') | Out-Null
    }
}

$readyTimer = New-Object System.Windows.Forms.Timer
$readyTimer.Interval = 1000
$script:lastReadinessLog = Get-Date
$readyTimer.Add_Tick({
    $backendAlive = $script:backendProcess -and -not $script:backendProcess.HasExited
    $frontendAlive = $script:frontendProcess -and -not $script:frontendProcess.HasExited
    if (-not $backendAlive -or -not $frontendAlive) {
        $readyTimer.Stop()
        $status.Text = 'وضعیت: یکی از سرویس‌ها متوقف شد؛ لاگ‌ها را بررسی کنید.'
        $status.ForeColor = [System.Drawing.Color]::Firebrick
        $startButton.Enabled = $true
        return
    }
    if ((Test-Listening 5000) -and (Test-Listening 3000)) {
        try {
            # Both services have opened their listening sockets. Avoid an HTTP
            # probe here: on some Windows hosts the first localhost request can
            # stall even though Vite is ready, leaving the RFA IIS sites stopped.
            Set-RfaSites 'start'
            $readyTimer.Stop()
            $status.Text = 'وضعیت: سایت و بک‌اند آماده‌اند — RFA.SYSTEMGROUP.NET'
            $status.ForeColor = [System.Drawing.Color]::ForestGreen
            $openButton.Enabled = $true
            Start-Process 'http://rfa.systemgroup.net/dashboard'
        } catch {
            $detail = $_.Exception.ToString()
            Write-LauncherEvent "IIS start/readiness error: $detail"
            $readyTimer.Stop()
            $status.Text = 'خطا در فعال‌کردن IIS؛ جزئیات در لاگ ثبت شد.'
            $status.ForeColor = [System.Drawing.Color]::Firebrick
            $startButton.Enabled = $false
            $restartButton.Enabled = [bool]$script:backendProcess
            $openButton.Enabled = $false
            $stopButton.Enabled = $true
        }
    } elseif (((Get-Date) - $script:lastReadinessLog).TotalSeconds -ge 10) {
        Write-LauncherEvent "Still waiting for listeners (backend=$(Test-Listening 5000), frontend=$(Test-Listening 3000))."
        $script:lastReadinessLog = Get-Date
    }
})

$startButton.Add_Click({ Start-AllRfaServices })
$restartButton.Add_Click({
    if (-not $script:backendProcess) { return }
    $readyTimer.Stop()
    $restartStoppedServices = $false
    try {
        $status.Text = 'در حال ساخت و ری‌استارت بک‌اند…'
        $status.ForeColor = [System.Drawing.Color]::DarkOrange
        $form.Refresh()
        Build-Backend
        Set-RfaSites 'stop'
        $script:sitesManaged = $true
        Stop-ManagedProcess $script:backendProcess
        $script:backendProcess = $null
        $restartStoppedServices = $true
        Install-BuiltBackend
        Start-Backend
        $readyTimer.Start()
    } catch {
        Write-LauncherEvent "backend restart error: $($_.Exception.ToString())"
        $status.Text = 'وضعیت: ری‌استارت ناموفق بود'
        $status.ForeColor = [System.Drawing.Color]::Firebrick
        if ($restartStoppedServices -and -not $script:backendProcess) {
            try {
                Start-Backend
                $readyTimer.Start()
            } catch {
                Write-LauncherEvent "backend recovery after restart error: $($_.Exception.ToString())"
            }
        }
        $startButton.Enabled = -not [bool]$script:backendProcess
        $restartButton.Enabled = [bool]$script:backendProcess
        $stopButton.Enabled = $script:sitesManaged
        [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'خطا در ری‌استارت', 'OK', 'Error') | Out-Null
    }
})
$openButton.Add_Click({ Start-Process 'http://rfa.systemgroup.net/dashboard' })
$stopButton.Add_Click({ [void](Stop-AllRfaServices) })
$logsButton.Add_Click({ Start-Process explorer.exe -ArgumentList $logDir })

$restartButton.Enabled = $false
$openButton.Enabled = $false
$stopButton.Enabled = $false
$form.Add_Shown({ Start-AllRfaServices })
$form.Add_FormClosing({
    param($sender, $eventArgs)
    if (-not (Stop-AllRfaServices)) { $eventArgs.Cancel = $true }
})
try {
    [void]$form.ShowDialog()
} finally {
    try { Stop-Transcript | Out-Null } catch { }
}
