<#
.SYNOPSIS
  Build and deploy the BountyFlow bounty_escrow Soroban contract to Stellar Testnet.

.DESCRIPTION
  Mirrors scripts/deploy-contract.sh for Windows PowerShell 5.1+ / PowerShell 7.
    1. stellar contract build (optimized wasm)
    2. ensure deployer + arbiter identities exist (generate + friendbot fund)
    3. upload wasm, deploy contract, look up the native XLM SAC id
    4. sanity-check version()
    5. optional smoke flow (create_escrow -> get_escrow -> release)
    6. write contracts/deployments/<network>.json

  Environment overrides:
    STELLAR_SOURCE_ACCOUNT  deployer identity (default bountyflow-deployer)
    ARBITER_IDENTITY        arbiter identity  (default bountyflow-arbiter)
    SMOKE_REQUESTER         smoke requester   (default bountyflow-demo-requester)
    STELLAR_NETWORK         network name      (default testnet)
    RUN_SMOKE_TEST          1 to run the smoke flow (or pass -SmokeTest)

  Secret keys stay in the local Stellar CLI key store; only public data is written.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts/deploy-contract.ps1 -SmokeTest
#>
[CmdletBinding()]
param(
  [switch]$SmokeTest
)

$ErrorActionPreference = 'Stop'

$RootDir = Split-Path -Parent $PSScriptRoot
$ContractsDir = Join-Path $RootDir 'contracts'
$DeployDir = Join-Path $ContractsDir 'deployments'
$Wasm = Join-Path $ContractsDir 'target\wasm32v1-none\release\bounty_escrow.wasm'

function EnvOr([string]$name, [string]$default) {
  $v = [Environment]::GetEnvironmentVariable($name)
  if ([string]::IsNullOrEmpty($v)) { return $default } else { return $v }
}

$Network = EnvOr 'STELLAR_NETWORK' 'testnet'
$Source = EnvOr 'STELLAR_SOURCE_ACCOUNT' 'bountyflow-deployer'
$Arbiter = EnvOr 'ARBITER_IDENTITY' 'bountyflow-arbiter'
$Requester = EnvOr 'SMOKE_REQUESTER' 'bountyflow-demo-requester'
if ((EnvOr 'RUN_SMOKE_TEST' '0') -eq '1') { $SmokeTest = $true }
$OutJson = Join-Path $DeployDir "$Network.json"

function Log([string]$msg) { Write-Host "==> $msg" }

if (-not (Get-Command stellar -ErrorAction SilentlyContinue)) {
  throw 'stellar CLI not found in PATH'
}

# Invoke the stellar CLI. Returns an object with Out (stdout lines), Err (stderr
# text) and Code. Native stderr is merged and split by type so PowerShell 5.1
# does not turn CLI progress output into terminating errors.
function Invoke-Stellar([string[]]$CliArgs) {
  $prev = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try {
    $all = & stellar @CliArgs 2>&1
    $code = $LASTEXITCODE
  } finally {
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

# 1. Build -------------------------------------------------------------------
Log 'building contract wasm (stellar contract build, optimized)'
Push-Location $ContractsDir
try {
  [void](Invoke-StellarChecked @('contract', 'build', '--package', 'bounty_escrow'))
} finally {
  Pop-Location
}
if (-not (Test-Path $Wasm)) { throw "wasm not found at $Wasm" }
Log "wasm: $Wasm ($((Get-Item $Wasm).Length) bytes)"

# 2. Identities --------------------------------------------------------------
$DeployerAddress = Ensure-Identity $Source
$ArbiterAddress = Ensure-Identity $Arbiter
Log "deployer: $DeployerAddress"
Log "arbiter:  $ArbiterAddress"

# 3. Upload + deploy ---------------------------------------------------------
Log 'uploading wasm'
$r = Invoke-StellarChecked @('contract', 'upload', '--wasm', $Wasm, '--source-account', $Source, '--network', $Network)
$WasmHash = LastLine $r
$UploadTx = TxHashFrom $r.Err
Log "wasm hash: $WasmHash (upload tx: $(if ($UploadTx) { $UploadTx } else { 'none - wasm already on ledger' }))"

Log 'deploying contract'
$r = Invoke-StellarChecked @('contract', 'deploy', '--wasm-hash', $WasmHash, '--source-account', $Source, '--network', $Network, '--alias', 'bounty_escrow')
$ContractId = LastLine $r
$DeployTx = TxHashFrom $r.Err
if (-not $ContractId.StartsWith('C')) { throw "unexpected deploy output: $ContractId" }
Log "contract id: $ContractId (deploy tx: $DeployTx)"

$NativeSacId = LastLine (Invoke-StellarChecked @('contract', 'id', 'asset', '--asset', 'native', '--network', $Network))
Log "native XLM SAC id: $NativeSacId"

# 4. Sanity check -----------------------------------------------------------
$Version = LastLine (Invoke-StellarChecked @('contract', 'invoke', '--id', $ContractId, '--source-account', $Source, '--network', $Network, '--', 'version'))
Log "on-chain version(): $Version"

$record = [ordered]@{
  network                  = $Network
  contract_id              = $ContractId
  native_asset_contract_id = $NativeSacId
  arbiter_address          = $ArbiterAddress
  wasm_hash                = $WasmHash
  upload_tx                = $UploadTx
  deploy_tx                = $DeployTx
  deployed_at              = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
  deployer_address         = $DeployerAddress
  contract_version         = [int]$Version
  explorer_url             = "https://stellar.expert/explorer/$Network/contract/$ContractId"
}

# 5. Optional smoke flow ----------------------------------------------------
if ($SmokeTest) {
  $RequesterAddress = Ensure-Identity $Requester
  $bytes = New-Object byte[] 32
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  $BountyId = -join ($bytes | ForEach-Object { $_.ToString('x2') })
  $Deadline = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() + 7 * 24 * 3600
  $Reward = 10000000  # 1 XLM (7 decimals)

  Log "smoke: create_escrow bounty_id=$BountyId (1 position, 1 XLM deposit)"
  $r = Invoke-StellarChecked @('contract', 'invoke', '--id', $ContractId, '--source-account', $Requester, '--network', $Network, '--',
    'create_escrow', '--requester', $RequesterAddress, '--bounty_id', $BountyId, '--token', $NativeSacId,
    '--reward_per_position', "$Reward", '--positions', '1', '--arbiter', $ArbiterAddress,
    '--deadline', "$Deadline", '--initial_deposit', "$Reward")
  $CreateTx = TxHashFrom $r.Err

  $created = LastLine (Invoke-StellarChecked @('contract', 'invoke', '--id', $ContractId, '--source-account', $Requester, '--network', $Network, '--', 'get_escrow', '--bounty_id', $BountyId))
  Log "smoke: get_escrow -> $created"

  Log "smoke: release to $DeployerAddress"
  $r = Invoke-StellarChecked @('contract', 'invoke', '--id', $ContractId, '--source-account', $Requester, '--network', $Network, '--',
    'release', '--requester', $RequesterAddress, '--bounty_id', $BountyId, '--contributor', $DeployerAddress)
  $ReleaseTx = TxHashFrom $r.Err
  $released = LastLine $r

  $record['smoke_test'] = [ordered]@{
    requester_address    = $RequesterAddress
    contributor_address  = $DeployerAddress
    bounty_id            = $BountyId
    reward_per_position  = $Reward
    positions            = 1
    deadline             = $Deadline
    create_escrow_tx     = $CreateTx
    escrow_after_create  = ($created | ConvertFrom-Json)
    release_tx           = $ReleaseTx
    escrow_after_release = ($released | ConvertFrom-Json)
  }
}

# 6. Write deployment record ------------------------------------------------
New-Item -ItemType Directory -Force -Path $DeployDir | Out-Null
$json = $record | ConvertTo-Json -Depth 6
[System.IO.File]::WriteAllText($OutJson, $json + "`n", (New-Object System.Text.UTF8Encoding $false))
Log "wrote $OutJson"
Write-Output $json
