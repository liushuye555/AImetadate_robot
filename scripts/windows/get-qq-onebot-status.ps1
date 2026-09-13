$ErrorActionPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)

$BotDir = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$DefaultNapcatDir = Join-Path $BotDir 'runtime\NapCat.Shell.Windows.Node'
$NapcatDir = $DefaultNapcatDir
if ($env:NAPCAT_DIR) { $NapcatDir = $env:NAPCAT_DIR }
$LauncherConfig = Join-Path $PSScriptRoot 'launcher.config.ps1'
if (Test-Path $LauncherConfig) { . $LauncherConfig }
if (-not (Test-Path $NapcatDir)) { $NapcatDir = $DefaultNapcatDir }

function Test-Port {
    param([int]$Port)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $task = $client.ConnectAsync('127.0.0.1', $Port)
        return $task.Wait(500) -and $client.Connected
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}

function Test-OwnedBot {
    return [bool](Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -and $_.CommandLine -like '*qq_onebot_whitelist.onebot*' -and $_.CommandLine -like "*$BotDir*"
    } | Select-Object -First 1)
}

function Get-LoginInfo {
    if (-not (Test-Port 3001)) { return $null }
    $socket = New-Object System.Net.WebSockets.ClientWebSocket
    $timeout = New-Object System.Threading.CancellationTokenSource(2000)
    try {
        [void]$socket.ConnectAsync([Uri]'ws://127.0.0.1:3001', $timeout.Token).GetAwaiter().GetResult()
        $request = [Text.Encoding]::UTF8.GetBytes('{"action":"get_login_info","params":{},"echo":"tray-status"}')
        $segment = New-Object ArraySegment[byte] -ArgumentList @(,$request)
        [void]$socket.SendAsync($segment, [Net.WebSockets.WebSocketMessageType]::Text, $true, $timeout.Token).GetAwaiter().GetResult()
        while ($socket.State -eq [Net.WebSockets.WebSocketState]::Open) {
            $buffer = New-Object byte[] 8192
            $response = New-Object Text.StringBuilder
            do {
                $receiveSegment = New-Object ArraySegment[byte] -ArgumentList @(,$buffer)
                $received = $socket.ReceiveAsync($receiveSegment, $timeout.Token).GetAwaiter().GetResult()
                [void]$response.Append([Text.Encoding]::UTF8.GetString($buffer, 0, $received.Count))
            } until ($received.EndOfMessage)
            $value = $response.ToString() | ConvertFrom-Json
            if ($value.echo -eq 'tray-status' -and $value.status -eq 'ok' -and $value.data) {
                return [pscustomobject]@{
                    user_id = [string]$value.data.user_id
                    nickname = [string]$value.data.nickname
                }
            }
        }
    } catch {
        return $null
    } finally {
        $socket.Dispose()
        $timeout.Dispose()
    }
    return $null
}

$napcat = Test-Port 6099
$onebot = Test-Port 3001
$login = if ($onebot) { @(Get-LoginInfo) | Select-Object -Last 1 } else { $null }
$qqNumber = ''
$qqNickname = ''
if ($login) {
    $qqNumber = [string]$login.user_id
    if (-not $qqNumber) { $qqNumber = [string]$login.userId }
    if (-not $qqNumber) { $qqNumber = [string]$login.uin }
    $qqNickname = [string]$login.nickname
    if (-not $qqNickname) { $qqNickname = [string]$login.nick }
}
[ordered]@{
    napcat = $napcat
    onebot = $onebot
    bot = Test-OwnedBot
    qqLoggedIn = [bool]$login
    qqNumber = $qqNumber
    qqNickname = $qqNickname
} | ConvertTo-Json -Compress
