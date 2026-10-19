<#
.SYNOPSIS
Deploys the .NET and Python MCP servers to one Azure Container Apps environment.

.DESCRIPTION
Run `az login` (and `az account set --subscription <id>` if needed) first. The script is
idempotent: re-running rebuilds both images and rolls out new revisions, keeping the existing
MCP_AUTH_TOKEN. Images are built remotely with `az acr build`, so Docker is not required.

Both apps share one bearer token (stored as a Container Apps secret) so the loop clients can
switch between servers by changing only MCP_SERVER_URL.

.EXAMPLE
./deploy/deploy-mcp.ps1
./deploy/deploy-mcp.ps1 -Location westus3 -WriteLocalConfig
#>
[CmdletBinding()]
param(
    [string]$ResourceGroup = "rg-who-runs-the-loop",
    [string]$Location = "eastus2",
    [string]$EnvironmentName = "cae-who-runs-the-loop",
    [string]$RegistryName = "",
    [string]$DotnetAppName = "policy-mcp-dotnet",
    [string]$PythonAppName = "policy-mcp-python",
    [ValidateRange(0, 10)][int]$MinReplicas = 0,
    # Writes MCP_SERVER_URL/MCP_AUTH_TOKEN to the git-ignored client configs:
    # dotnet/loop/appsettings.development.json (.NET server) and python/.env (Python server).
    [switch]$WriteLocalConfig
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$secretName = "mcp-auth-token"

function Invoke-Az {
    $output = & az @args
    if ($LASTEXITCODE -ne 0) { throw "az $($args[0..2] -join ' ') failed (exit $LASTEXITCODE)." }
    return $output
}

function Test-AzResource {
    & az @args --only-show-errors -o none 2>$null
    return $LASTEXITCODE -eq 0
}

$subscriptionId = Invoke-Az account show --query id -o tsv
if (-not $subscriptionId) { throw "Run 'az login' first." }
Write-Host "Subscription: $(Invoke-Az account show --query name -o tsv) ($subscriptionId)"

Invoke-Az extension add --name containerapp --upgrade --only-show-errors -o none
foreach ($namespace in "Microsoft.App", "Microsoft.OperationalInsights", "Microsoft.ContainerRegistry") {
    Invoke-Az provider register --namespace $namespace --wait -o none
}

if (-not $RegistryName) {
    # ACR names are global and alphanumeric; derive a stable suffix from subscription + resource group.
    $hash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData(
        [Text.Encoding]::UTF8.GetBytes("$subscriptionId/$ResourceGroup"))).Substring(0, 8).ToLowerInvariant()
    $RegistryName = "whorunsloop$hash"
}

Write-Host "Resource group $ResourceGroup ($Location)"
Invoke-Az group create -n $ResourceGroup -l $Location -o none

Write-Host "Container registry $RegistryName"
if (-not (Test-AzResource acr show -n $RegistryName -g $ResourceGroup)) {
    Invoke-Az acr create -n $RegistryName -g $ResourceGroup -l $Location --sku Basic --admin-enabled false -o none
}
$registryServer = Invoke-Az acr show -n $RegistryName -g $ResourceGroup --query loginServer -o tsv

$tag = Get-Date -Format "yyyyMMddHHmmss"
$images = @{
    $DotnetAppName = @{ Image = "$registryServer/policy-mcp-dotnet:$tag"; Context = Join-Path $root "dotnet/mcp_server" }
    $PythonAppName = @{ Image = "$registryServer/policy-mcp-python:$tag"; Context = Join-Path $root "python/mcp_server" }
}
foreach ($app in $DotnetAppName, $PythonAppName) {
    $repository = $images[$app].Image.Substring($registryServer.Length + 1)
    Write-Host "Building $repository in ACR"
    Invoke-Az acr build -r $RegistryName -t $repository --platform linux/amd64 --no-logs $images[$app].Context -o none
}

Write-Host "Container Apps environment $EnvironmentName"
if (-not (Test-AzResource containerapp env show -n $EnvironmentName -g $ResourceGroup)) {
    Invoke-Az containerapp env create -n $EnvironmentName -g $ResourceGroup -l $Location -o none
}
$defaultDomain = Invoke-Az containerapp env show -n $EnvironmentName -g $ResourceGroup --query properties.defaultDomain -o tsv

# Reuse the token from an existing app so redeploys don't break configured clients.
$token = $null
foreach ($app in $DotnetAppName, $PythonAppName) {
    if (Test-AzResource containerapp show -n $app -g $ResourceGroup) {
        $token = & az containerapp secret show -n $app -g $ResourceGroup --secret-name $secretName --query value -o tsv 2>$null
        if ($LASTEXITCODE -eq 0 -and $token) { break }
        $token = $null
    }
}
if (-not $token) {
    $token = [Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(32)).TrimEnd("=").Replace("+", "-").Replace("/", "_")
}

$urls = @{}
foreach ($app in $DotnetAppName, $PythonAppName) {
    $fqdn = "$app.$defaultDomain"
    $environmentVariables = @("MCP_HOST=0.0.0.0", "PORT=8000", "MCP_PUBLIC_HOST=$fqdn", "MCP_AUTH_TOKEN=secretref:$secretName")
    Write-Host "Deploying $app"
    if (Test-AzResource containerapp show -n $app -g $ResourceGroup) {
        Invoke-Az containerapp secret set -n $app -g $ResourceGroup --secrets "$secretName=$token" -o none
        Invoke-Az containerapp update -n $app -g $ResourceGroup --image $images[$app].Image `
            --set-env-vars @environmentVariables --min-replicas $MinReplicas --max-replicas 2 -o none
    }
    else {
        Invoke-Az containerapp create -n $app -g $ResourceGroup --environment $EnvironmentName `
            --image $images[$app].Image --registry-server $registryServer --registry-identity system `
            --ingress external --target-port 8000 --transport auto `
            --cpu 0.25 --memory 0.5Gi --min-replicas $MinReplicas --max-replicas 2 `
            --secrets "$secretName=$token" --env-vars @environmentVariables -o none
    }
    $actual = Invoke-Az containerapp show -n $app -g $ResourceGroup --query properties.configuration.ingress.fqdn -o tsv
    if ($actual -ne $fqdn) { throw "$app FQDN '$actual' does not match MCP_PUBLIC_HOST '$fqdn'." }
    $urls[$app] = "https://$fqdn/mcp"
}

Write-Host "`nVerifying endpoints"
foreach ($app in $DotnetAppName, $PythonAppName) {
    $healthUrl = $urls[$app] -replace "/mcp$", "/healthz"
    $healthy = $false
    for ($attempt = 1; $attempt -le 12 -and -not $healthy; $attempt++) {
        try { $healthy = (Invoke-RestMethod $healthUrl -TimeoutSec 20).status -eq "ok" } catch { Start-Sleep -Seconds 10 }
    }
    $initialize = @{ jsonrpc = "2.0"; id = 1; method = "initialize"; params = @{
        protocolVersion = "2025-11-25"; capabilities = @{}; clientInfo = @{ name = "deploy-check"; version = "1.0" } } } | ConvertTo-Json -Depth 5
    $status = try {
        (Invoke-WebRequest $urls[$app] -Method Post -Body $initialize -ContentType "application/json" -TimeoutSec 30 `
            -Headers @{ Authorization = "Bearer $token"; Accept = "application/json, text/event-stream" }).StatusCode
    } catch { $_.Exception.Response.StatusCode.value__ }
    Write-Host ("  {0,-20} healthz={1} mcp initialize={2}" -f $app, $(if ($healthy) { "ok" } else { "FAILED" }), $status)
}

if ($WriteLocalConfig) {
    $dotnetSettings = Join-Path $root "dotnet/loop/appsettings.development.json"
    $settings = if (Test-Path $dotnetSettings) { Get-Content $dotnetSettings -Raw | ConvertFrom-Json -AsHashtable } else { @{} }
    $settings["MCP_SERVER_URL"] = $urls[$DotnetAppName]
    $settings["MCP_AUTH_TOKEN"] = $token
    $settings | ConvertTo-Json | Set-Content $dotnetSettings -Encoding utf8

    $pythonEnv = Join-Path $root "python/.env"
    $lines = if (Test-Path $pythonEnv) { @(Get-Content $pythonEnv | Where-Object { $_ -notmatch "^(MCP_SERVER_URL|MCP_AUTH_TOKEN)=" }) } else { @() }
    $lines + "MCP_SERVER_URL=$($urls[$PythonAppName])" + "MCP_AUTH_TOKEN=$token" | Set-Content $pythonEnv -Encoding utf8
    Write-Host "`nUpdated MCP_SERVER_URL and MCP_AUTH_TOKEN in dotnet/loop/appsettings.development.json and python/.env (both git-ignored)."
}

Write-Host "`n.NET MCP server:   $($urls[$DotnetAppName])"
Write-Host "Python MCP server: $($urls[$PythonAppName])"
Write-Host "Read the shared token with:"
Write-Host "  az containerapp secret show -n $DotnetAppName -g $ResourceGroup --secret-name $secretName --query value -o tsv"
