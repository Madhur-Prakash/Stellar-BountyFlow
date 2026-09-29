<#
.SYNOPSIS
  Build and deploy the BountyFlow attestations Soroban contract to Stellar Testnet.

.DESCRIPTION
    1. stellar contract build --package attestations (optimized wasm)
    2. ensure the deployer identity exists (generate + friendbot fund)
    3. read the attester key from the root .env (STELLAR_ATTESTER_SECRET); when it is missing, generate a new
       keypair, write it to .env and fund it with Friendbot. The attester secret never leaves .env.
    4. upload wasm, deploy the contract with the attester as its constructor argument
    5. sanity-check version(), attester() and total()
    6. write ATTESTATION_CONTRACT_ID to .env and contracts/deployments/attestations-<network>.json

  Environment overrides:
    STELLAR_SOURCE_ACCOUNT  deployer identity (default bountyflow-deployer)
    STELLAR_NETWORK         network name      (default testnet)

  Only public data is written to the deployment record.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts/deploy-attestations.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$RootDir = Split-Path -Parent $PSScriptRoot
$ContractsDir = Join-Path $RootDir 'contracts'
$BackendDir = Join-Path $RootDir 'backend'
$DeployDir = Join-Path $ContractsDir 'deployments'
$EnvFile = Join-Path $RootDir '.env'
$Wasm = Join-Path $ContractsDir 'target\wasm32v1-none\release\attestations.wasm'

function EnvOr([string]$name, [string]$default) {
  $v = [Environment]::GetEnvironmentVariable($name)
  if ([string]::IsNullOrEmpty($v)) { return $default } else { return $v }
}

$Network = EnvOr 'STELLAR_NETWORK' 'testnet'
$Source = EnvOr 'STELLAR_SOURCE_ACCOUNT' 'bountyflow-deployer'
$OutJson = Join-Path $DeployDir "attestations-$Network.json"

function Log([string]$msg) { Write-Host "==> $msg" }

# BountyFlow's own STELLAR_NETWORK_PASSPHRASE (exported by a shell that sourced .env) would make the CLI ignore
# --network and ask for an RPC URL; the CLI's named network already carries both.
Remove-Item Env:STELLAR_NETWORK_PASSPHRASE -ErrorAction SilentlyContinue
Remove-Item Env:STELLAR_RPC_URL -ErrorAction SilentlyContinue

if (-not (Get-Command stellar -ErrorAction SilentlyContinue)) { throw 'stellar CLI not found in PATH' }
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'uv not found in PATH (used to derive the attester address)' }

# Invoke the stellar CLI. Returns an object with Out (stdout lines), Err (stderr text) and Code. Native stderr is
# merged and split by type so PowerShell 5.1 does not turn CLI progress output into terminating errors. It runs in
# contracts/, because the CLI also reads a .env in its working directory and the root .env uses BountyFlow's names.
function Invoke-Stellar([string[]]$CliArgs) {
  $prev = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  Push-Location $ContractsDir
  try {
    $all = & stellar @CliArgs 2>&1
    $code = $LASTEXITCODE
  } finally {
    Pop-Location
    $ErrorActionPreference = $prev
  }
  $out = @($all | Where-Object { $_ -isnot [System.Management.Automation.ErrorRecord] } | ForEach-Object { "$_".Trim() } | Where-Object { $_ -ne '' })
  $err = (@($all | Where-Object { $_ -is [System.Management.Automation.ErrorRecord] } | ForEach-Object { $_.ToString() }) -join "`n")
  return [pscustomobject]@{ Out = $out; Err = $err; Code = $code }
}

# Invoke with one retry (friendbot / RPC hiccups); throws on second failure.
function Invoke-StellarChecked([string[]]$CliArgs) {
  $r = Invoke-Stellar $CliArgs
  if ($r.Code -ne 0) {
    Write-Host $r.Err
    Log "command failed, retrying once in 5s: stellar $($CliArgs -join ' ')"
    Start-Sleep -Seconds 5
    $r = Invoke-Stellar $CliArgs
    if ($r.Code -ne 0) {
      Write-Host $r.Err
      throw "stellar $($CliArgs -join ' ') failed with exit code $($r.Code)"
    }
  }
  if ($r.Err) { Write-Host $r.Err }
  return $r
}

function LastLine($r) { if ($r.Out.Count -gt 0) { return $r.Out[-1] } else { return '' } }

function TxHashFrom([string]$text) {
  $m = [regex]::Match($text, '(?i)tx/([0-9a-f]{64})|transaction hash is ([0-9a-f]{64})')
  if (-not $m.Success) { return $null }
  if ($m.Groups[1].Success) { return $m.Groups[1].Value } else { return $m.Groups[2].Value }
}

function Ensure-Identity([string]$name) {
  $r = Invoke-Stellar @('keys', 'address', $name)
  if ($r.Code -eq 0) {
    Log "identity '$name' exists: $(LastLine $r)"
    [void](Invoke-Stellar @('keys', 'fund', $name, '--network', $Network))  # tolerate "already funded"
  } else {
    Log "generating + funding identity '$name' on $Network"
    [void](Invoke-StellarChecked @('keys', 'generate', $name, '--network', $Network, '--fund'))
  }
  return (LastLine (Invoke-StellarChecked @('keys', 'address', $name)))
}

# Reads KEY=value from .env (first match, no quotes).
function Read-DotEnv([string]$key) {
  if (-not (Test-Path $EnvFile)) { return $null }
  foreach ($line in Get-Content -Encoding UTF8 $EnvFile) {
    if ($line -match "^\s*$key=(.*)$") { return $Matches[1].Trim() }
  }
  return $null
}

# Sets KEY=value in .env, replacing an existing line or appending one.
function Write-DotEnv([string]$key, [string]$value) {
  $lines = if (Test-Path $EnvFile) { @(Get-Content -Encoding UTF8 $EnvFile) } else { @() }
  $found = $false
  $lines = @($lines | ForEach-Object {
      if ($_ -match "^\s*$key=") { $found = $true; "$key=$value" } else { $_ }
    })
  if (-not $found) { $lines += "$key=$value" }
  [System.IO.File]::WriteAllText($EnvFile, (($lines -join "`n") + "`n"), (New-Object System.Text.UTF8Encoding $false))
}

function Invoke-Python([string]$code, [string]$stdin = '') {
  Push-Location $BackendDir
  try {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $out = $stdin | & uv run --quiet python -c $code 2>$null
    $ErrorActionPreference = $prev
  } finally {
    Pop-Location
  }
  return ("$out").Trim()
}

# 1. Build -------------------------------------------------------------------
Log 'building contract wasm (stellar contract build --package attestations, optimized)'
[void](Invoke-StellarChecked @('contract', 'build', '--package', 'attestations'))
if (-not (Test-Path $Wasm)) { throw "wasm not found at $Wasm" }
Log "wasm: $Wasm ($((Get-Item $Wasm).Length) bytes)"

# 2. Deployer -----------------------------------------------------------------
$DeployerAddress = Ensure-Identity $Source
Log "deployer: $DeployerAddress"

# 3. Attester (secret stays in .env) ------------------------------------------
$AttesterSecret = Read-DotEnv 'STELLAR_ATTESTER_SECRET'
if ([string]::IsNullOrEmpty($AttesterSecret)) {
  Log 'STELLAR_ATTESTER_SECRET is not set: generating an attester keypair into .env'
  $AttesterSecret = Invoke-Python 'from stellar_sdk import Keypair; print(Keypair.random().secret)'
  if (-not $AttesterSecret.StartsWith('S')) { throw 'could not generate an attester key' }
  Write-DotEnv 'STELLAR_ATTESTER_SECRET' $AttesterSecret
}
# The secret is passed on stdin, never on a command line (PowerShell may prefix piped text with a BOM).
$AttesterAddress = Invoke-Python 'import sys; from stellar_sdk import Keypair; print(Keypair.from_secret(sys.stdin.read().strip().strip(chr(0xFEFF)).strip()).public_key)' $AttesterSecret
if (-not $AttesterAddress.StartsWith('G')) { throw 'STELLAR_ATTESTER_SECRET in .env is not a valid Stellar secret key' }
Log "attester: $AttesterAddress"
if ($Network -eq 'testnet') {
  try {
    [void](Invoke-WebRequest -UseBasicParsing -Uri "https://friendbot.stellar.org/?addr=$AttesterAddress" -TimeoutSec 60)
    Log 'attester funded with Friendbot'
  } catch {
    Log 'attester already funded (or Friendbot unavailable)'
  }
}

# 4. Upload + deploy ---------------------------------------------------------
Log 'uploading wasm'
$r = Invoke-StellarChecked @('contract', 'upload', '--wasm', $Wasm, '--source-account', $Source, '--network', $Network)
$WasmHash = LastLine $r
$UploadTx = TxHashFrom $r.Err
Log "wasm hash: $WasmHash (upload tx: $(if ($UploadTx) { $UploadTx } else { 'none - wasm already on ledger' }))"

Log 'deploying contract (constructor: attester)'
$r = Invoke-StellarChecked @('contract', 'deploy', '--wasm-hash', $WasmHash, '--source-account', $Source, '--network', $Network, '--alias', 'attestations', '--', '--attester', $AttesterAddress)
$ContractId = LastLine $r
$DeployTx = TxHashFrom $r.Err
if (-not $ContractId.StartsWith('C')) { throw "unexpected deploy output: $ContractId" }
Log "contract id: $ContractId (deploy tx: $DeployTx)"

# 5. Sanity check -----------------------------------------------------------
function View([string]$fn) {
  return LastLine (Invoke-StellarChecked @('contract', 'invoke', '--id', $ContractId, '--source-account', $Source, '--network', $Network, '--send', 'no', '--', $fn))
}
$Version = View 'version'
$OnchainAttester = (View 'attester').Trim('"')
$Total = (View 'total').Trim('"')
Log "on-chain version(): $Version, attester(): $OnchainAttester, total(): $Total"
if ($OnchainAttester -ne $AttesterAddress) { throw 'attester() does not match the configured attester' }

# 6. Record ------------------------------------------------------------------
Write-DotEnv 'ATTESTATION_CONTRACT_ID' $ContractId
Log 'wrote ATTESTATION_CONTRACT_ID to .env'

$record = [ordered]@{
  network          = $Network
  contract_id      = $ContractId
  attester_address = $AttesterAddress
  wasm_hash        = $WasmHash
  upload_tx        = $UploadTx
  deploy_tx        = $DeployTx
  deployed_at      = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
  deployer_address = $DeployerAddress
  contract_version = [int]$Version
  explorer_url     = "https://stellar.expert/explorer/$Network/contract/$ContractId"
  smoke_test       = [ordered]@{
    version  = [int]$Version
    attester = $OnchainAttester
    total    = [int]$Total
  }
}
New-Item -ItemType Directory -Force -Path $DeployDir | Out-Null
$json = $record | ConvertTo-Json -Depth 6
[System.IO.File]::WriteAllText($OutJson, $json + "`n", (New-Object System.Text.UTF8Encoding $false))
Log "wrote $OutJson"
Write-Output $json
