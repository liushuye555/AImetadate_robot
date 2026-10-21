function Get-QQOneBotRecoveryTaskName {
    param([Parameter(Mandatory=$true)][string]$BotDir)
    $root = [IO.Path]::GetFullPath($BotDir).TrimEnd('\', '/').ToLowerInvariant()
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $digest = $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($root)) }
    finally { $sha.Dispose() }
    $suffix = ([BitConverter]::ToString($digest) -replace '-', '').Substring(0, 12)
    return "QQOneBotManager-$suffix"
}
