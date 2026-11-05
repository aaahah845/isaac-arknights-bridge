$baseDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $baseDir 'pc-game.pid'
if (Test-Path -LiteralPath $pidFile) {
    $gamePid = [int](Get-Content -LiteralPath $pidFile)
    $p = Get-Process -Id $gamePid -ErrorAction SilentlyContinue
    if ($p -and $p.ProcessName -eq 'Arknights') {
        $null=$p.CloseMainWindow()
        if (-not $p.WaitForExit(5000)) { Stop-Process -Id $gamePid -Force -ErrorAction Stop }
    }
}
