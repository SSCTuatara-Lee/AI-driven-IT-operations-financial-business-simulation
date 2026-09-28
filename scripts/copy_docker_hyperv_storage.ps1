$ErrorActionPreference = 'Stop'
$resultPath = 'D:\lxt\data\docker-hyperv-storage.json'
try {
    $workspacePath = [IO.Path]::GetFullPath('D:\lxt')
    $sourceFolder = [IO.Path]::GetFullPath('C:\ProgramData\DockerDesktop\vm-data')
    $destinationFolder = [IO.Path]::GetFullPath('D:\lxt\.tools\docker-data\hyper-v')
    $savedFolder = [IO.Path]::GetFullPath('D:\lxt\.tools\docker-data\unused-new-hyperv-disk')
    foreach ($targetPath in @($destinationFolder, $savedFolder)) {
        if (-not $targetPath.StartsWith($workspacePath + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Destination is outside the workspace.' }
    }
    $vm = Get-VM -Name 'DockerDesktopVM'
    if ($vm.State.ToString() -eq 'Running') { Stop-VM -Name 'DockerDesktopVM' -Confirm:$false; $vm = Get-VM -Name 'DockerDesktopVM' }
    if ($vm.State.ToString() -ne 'Off') { throw 'VM must be stopped before copying disk data.' }
    $destinationFile = Join-Path $destinationFolder 'DockerDesktop.vhdx'
    $currentFile = [IO.Path]::GetFullPath((Get-VMHardDiskDrive -VMName 'DockerDesktopVM').Path)
    if ($currentFile -ne $destinationFile) { throw 'Unexpected VM disk path.' }
    if (Test-Path -LiteralPath (Join-Path $savedFolder 'DockerDesktop.vhdx')) { throw 'Backup already exists; refusing to overwrite.' }
    New-Item -ItemType Directory -Path $savedFolder -Force | Out-Null
    # Copy one exact file with Windows backup privileges. No ACLs are weakened,
    # no source files are removed, and the current target is backed up first.
    & robocopy.exe $destinationFolder $savedFolder 'DockerDesktop.vhdx' /B /COPY:DAT /R:0 /W:0 /J /NP /LOG:D:\lxt\data\docker-new-disk-backup.log
    if ($LASTEXITCODE -ge 8) { throw "Destination backup failed: $LASTEXITCODE" }
    & robocopy.exe $sourceFolder $destinationFolder 'DockerDesktop.vhdx' /B /COPY:DAT /IS /IT /R:0 /W:0 /J /NP /LOG:D:\lxt\data\docker-disk-copy.log
    if ($LASTEXITCODE -ge 8) { throw "Original disk copy failed: $LASTEXITCODE" }
    $sourceSize = (Get-Item -LiteralPath (Join-Path $sourceFolder 'DockerDesktop.vhdx')).Length
    $destinationSize = (Get-Item -LiteralPath $destinationFile).Length
    if ($sourceSize -ne $destinationSize) { throw 'Copied disk size mismatch.' }
    @{Success=$true; VM='DockerDesktopVM'; Disk=$destinationFile; Source=(Join-Path $sourceFolder 'DockerDesktop.vhdx'); DiskBytes=$destinationSize; OriginalDiskRetained=$true; SavedNewDisk=(Join-Path $savedFolder 'DockerDesktop.vhdx'); CopyMethod='Windows backup privilege; source ACL unchanged'} | ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding UTF8
    exit 0
} catch {
    @{Success=$false; Error=$_.Exception.Message; Line=$_.InvocationInfo.ScriptLineNumber} | ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding UTF8
    exit 1
}
