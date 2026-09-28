$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$resultPath = 'D:\lxt\data\docker-hyperv-service.json'
try {
    $features = @('Microsoft-Hyper-V-All', 'Microsoft-Hyper-V-Management-PowerShell', 'Containers') | ForEach-Object {
        $feature = Get-WindowsOptionalFeature -Online -FeatureName $_
        @{Name=$feature.FeatureName; State=$feature.State.ToString()}
    }
    Set-Service -Name 'com.docker.service' -StartupType Automatic
    Start-Service -Name 'com.docker.service'
    $service = Get-Service -Name 'com.docker.service'
    @{Status=$service.Status.ToString(); Features=$features; Success=$true} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $resultPath -Encoding UTF8
    exit 0
} catch {
    @{Success=$false; Error=$_.Exception.Message} | ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding UTF8
    exit 1
}
