param(
    [int]$Port = 8080
)

$ErrorActionPreference = "Stop"
$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$dashboardRoot = Join-Path $projectRoot "apps\dashboard"
$demoUrl = "http://127.0.0.1:$Port/"

Write-Host "Iniciando a demo sintetica em $demoUrl"
Write-Host "Pressione Ctrl+C nesta janela para encerrar."
Start-Process $demoUrl
python -m http.server $Port --bind 127.0.0.1 --directory $dashboardRoot
