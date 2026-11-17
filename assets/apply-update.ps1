param([Parameter(Mandatory=$true)][string]$ConfigFile)
$ErrorActionPreference = 'Stop'
$updateConfig = Get-Content -LiteralPath $ConfigFile -Raw | ConvertFrom-Json
$targetPath = [IO.Path]::GetFullPath($updateConfig.target).TrimEnd('\')
$stagePath = [IO.Path]::GetFullPath($updateConfig.stage).TrimEnd('\')
$parentPath = [IO.Path]::GetDirectoryName($targetPath)
$backupPath = $targetPath + '.previous-' + [Guid]::NewGuid().ToString('N')
$logPath = [IO.Path]::ChangeExtension($ConfigFile, '.log')
$movedOld = $false
$movedNew = $false
try {
    # Every recursive directory move has an absolute, sibling-only target.
    if ([IO.Path]::GetDirectoryName($stagePath) -ne $parentPath -or
        [IO.Path]::GetDirectoryName($backupPath) -ne $parentPath -or
        -not [IO.Path]::GetFileName($stagePath).StartsWith('.echo-stage-') -or
        $targetPath -eq [IO.Path]::GetPathRoot($targetPath) -or
        -not (Test-Path -LiteralPath (Join-Path $stagePath 'Echo.exe'))) { throw 'Invalid update paths' }
    foreach ($updatePath in @($targetPath, $stagePath)) {
        if ((Get-Item -LiteralPath $updatePath).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse point rejected' }
    }
    $runningEcho = Get-Process -Id ([int]$updateConfig.parent_id) -ErrorAction SilentlyContinue
    if ($runningEcho) { $runningEcho | Wait-Process -Timeout 60 }
    [IO.Directory]::Move($targetPath, $backupPath)
    $movedOld = $true
    [IO.Directory]::Move($stagePath, $targetPath)
    $movedNew = $true
    if ($null -eq $updateConfig.restart -or $updateConfig.restart) {
        Start-Process -FilePath (Join-Path $targetPath 'Echo.exe') -WorkingDirectory $targetPath -WindowStyle Hidden
    }
    'Update applied. Previous version: ' + $backupPath | Set-Content -LiteralPath $logPath -Encoding UTF8
} catch {
    if ($movedNew) {
        # Move the failed new directory back to its exact verified staging path.
        [IO.Directory]::Move($targetPath, $stagePath)
    }
    if ($movedOld) { [IO.Directory]::Move($backupPath, $targetPath) }
    'Update failed; prior version retained. ' + $_.Exception.Message | Set-Content -LiteralPath $logPath -Encoding UTF8
}
