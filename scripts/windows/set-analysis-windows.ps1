$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$BotDir = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path

function Invoke-Settings {
    param([string[]]$Arguments)

    Push-Location $BotDir
    try {
        $output = & uv run python -m qq_onebot_whitelist.settings --config config.yaml @Arguments 2>&1 | Out-String
        if ($LASTEXITCODE -ne 0) { throw $output.Trim() }
        return $output.Trim()
    } finally {
        Pop-Location
    }
}

function Show-Error {
    param([string]$Message)
    [System.Windows.Forms.MessageBox]::Show(
        $Message,
        'Analysis windows',
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error
    ) | Out-Null
}

$form = New-Object System.Windows.Forms.Form
$form.Text = 'Set analysis windows'
$form.StartPosition = 'CenterScreen'
$form.ClientSize = New-Object System.Drawing.Size(420, 300)
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.MinimizeBox = $false

$label = New-Object System.Windows.Forms.Label
$label.Text = 'Enter one HH:MM-HH:MM window per line:'
$label.AutoSize = $true
$label.Location = New-Object System.Drawing.Point(12, 15)
$form.Controls.Add($label)

$textBox = New-Object System.Windows.Forms.TextBox
$textBox.Multiline = $true
$textBox.ScrollBars = 'Vertical'
$textBox.AcceptsReturn = $true
$textBox.Location = New-Object System.Drawing.Point(15, 40)
$textBox.Size = New-Object System.Drawing.Size(390, 205)
$form.Controls.Add($textBox)

$saveButton = New-Object System.Windows.Forms.Button
$saveButton.Text = 'Save'
$saveButton.Location = New-Object System.Drawing.Point(165, 260)
$saveButton.Size = New-Object System.Drawing.Size(75, 28)
$form.Controls.Add($saveButton)

$allDayButton = New-Object System.Windows.Forms.Button
$allDayButton.Text = 'All day'
$allDayButton.Location = New-Object System.Drawing.Point(245, 260)
$allDayButton.Size = New-Object System.Drawing.Size(75, 28)
$form.Controls.Add($allDayButton)

$cancelButton = New-Object System.Windows.Forms.Button
$cancelButton.Text = 'Cancel'
$cancelButton.Location = New-Object System.Drawing.Point(325, 260)
$cancelButton.Size = New-Object System.Drawing.Size(75, 28)
$cancelButton.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
$form.CancelButton = $cancelButton
$form.Controls.Add($cancelButton)

$saveButton.Add_Click({
    try {
        $windows = @($textBox.Lines | ForEach-Object { $_.Trim() } | Where-Object { $_ })
        if ($windows.Count -eq 0) { throw 'Enter at least one window or click All day.' }
        Invoke-Settings -Arguments @('--set', ($windows -join ',')) | Out-Null
        $form.Close()
    } catch {
        Show-Error $_.Exception.Message
    }
})

$allDayButton.Add_Click({
    try {
        Invoke-Settings -Arguments @('--all-day') | Out-Null
        $form.Close()
    } catch {
        Show-Error $_.Exception.Message
    }
})

try {
    $current = Invoke-Settings -Arguments @('--get', '--json')
    $windows = @($current | ConvertFrom-Json)
    $textBox.Lines = $windows
    [void]$form.ShowDialog()
} catch {
    Show-Error $_.Exception.Message
} finally {
    $form.Dispose()
}
