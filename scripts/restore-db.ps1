<#
.SYNOPSIS
Restore a BountyFlow pg_dump custom-format backup with pg_restore.

.DESCRIPTION
This overwrites data. It asks for confirmation, and it refuses a target database whose name does not look like a
BountyFlow database unless -Force is given. The checksum file next to the dump is verified when present.

See docs/runbooks/postgres-backup-restore.md and docs/runbooks/restore-drill.md.

.PARAMETER File
The .dump or .dump.gz written by scripts/backup-db.ps1 or scripts/backup-db.sh.

.PARAMETER Docker
Restore into the compose postgres service. This is the default when DATABASE_URL is not set.

.PARAMETER DatabaseUrl
Restore into this database with the local pg_restore. A postgresql+psycopg:// prefix is normalised to
postgresql://. Defaults to $env:DATABASE_URL.

.PARAMETER Service
Compose service name used by -Docker. Default: postgres

.PARAMETER Database
Target database for -Docker. Default: $env:POSTGRES_DB, else bountyflow.

.PARAMETER Jobs
pg_restore --jobs=N. Only with -DatabaseUrl: a parallel restore needs a seekable file, which a dump piped into
the container is not.

.PARAMETER NoClean
Do not drop existing objects first; restore into an empty database as-is.

.PARAMETER Force
Skip the confirmation prompt and the database-name check.

.EXAMPLE
powershell -ExecutionPolicy Bypass -File scripts/restore-db.ps1 -File .\backups\bountyflow-bountyflow-20260929T031500Z.dump

.EXAMPLE
powershell -ExecutionPolicy Bypass -File scripts/restore-db.ps1 -File .\backups\latest.dump.gz -DatabaseUrl "postgresql://bountyflow:...@127.0.0.1:5432/bountyflow_restore" -Jobs 4 -Force
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$File,
    [switch]$Docker,
    [string]$DatabaseUrl = $env:DATABASE_URL,
    [string]$Service = "postgres",
    [string]$Database,
    [ValidateRange(1, 32)]
    [int]$Jobs = 1,
    [switch]$NoClean,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

# A BountyFlow database: bountyflow, bountyflow_test, bountyflow_restore_20260929, ...
$ExpectedDbPattern = '^bountyflow(_[a-z0-9_]+)?$'

function Write-Step { param([string]$Message) Write-Host "==> $Message" }

function Get-NormalisedUrl {
    param([string]$Url)
    return $Url -replace '^postgresql\+psycopg://', 'postgresql://'
}

function Get-DatabaseName {
    param([string]$Url)
    $withoutQuery = ($Url -split '\?')[0]
    return ($withoutQuery -split '/')[-1]
}

function Test-Command {
    param([string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

if (-not (Test-Path $File)) { throw "no such file: $File" }
$File = (Resolve-Path $File).Path

# --- Mode ---------------------------------------------------------------------------------------

$useDocker = $Docker.IsPresent -or [string]::IsNullOrWhiteSpace($DatabaseUrl)

if ($useDocker) {
    if (-not (Test-Command docker)) { throw "docker not found in PATH" }
    $pgUser = if ($env:POSTGRES_USER) { $env:POSTGRES_USER } else { "bountyflow" }
    if ([string]::IsNullOrWhiteSpace($Database)) {
        $Database = if ($env:POSTGRES_DB) { $env:POSTGRES_DB } else { "bountyflow" }
    }
    $targetDb = $Database
    $where = "compose service '$Service'"
    if ($Jobs -gt 1) {
        throw "-Jobs needs a seekable file: use -DatabaseUrl postgresql://...@127.0.0.1:5432/$targetDb instead, or docker compose cp the dump into the container and run pg_restore there"
    }
}
else {
    if (-not (Test-Command pg_restore)) { throw "pg_restore not found in PATH (install the PostgreSQL client tools)" }
    $url = Get-NormalisedUrl -Url $DatabaseUrl
    $targetDb = Get-DatabaseName -Url $url
    if ([string]::IsNullOrWhiteSpace($targetDb)) { throw "could not read a database name out of the URL" }
    # Never print the URL: it carries the password.
    $where = "the database in DATABASE_URL"
}

# --- Checks -------------------------------------------------------------------------------------

if ($targetDb -notmatch $ExpectedDbPattern) {
    if (-not $Force) {
        throw "target database '$targetDb' does not match $ExpectedDbPattern - pass -Force if that is really the target"
    }
    Write-Warning "'$targetDb' does not look like a BountyFlow database; -Force was given"
}

$checksumFile = "$File.sha256"
if (Test-Path $checksumFile) {
    Write-Step "verifying $checksumFile"
    $recorded = ((Get-Content -Path $checksumFile -TotalCount 1) -split '\s+')[0]
    $actual = (Get-FileHash -Path $File -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($recorded.ToLowerInvariant() -ne $actual) {
        throw "checksum mismatch - do not restore this file"
    }
}
else {
    Write-Step "no checksum file next to the dump; continuing unverified"
}

# gzip-compressed dumps are expanded first: pg_restore needs a custom-format archive, not a gzip stream.
$source = $File
$tempFile = $null
if ($File.EndsWith(".gz", [StringComparison]::OrdinalIgnoreCase)) {
    $tempFile = Join-Path ([System.IO.Path]::GetTempPath()) ("bountyflow-restore-" + [Guid]::NewGuid().ToString("N") + ".dump")
    Write-Step "expanding $File"
    $inStream = [System.IO.File]::OpenRead($File)
    try {
        $gz = New-Object System.IO.Compression.GZipStream($inStream, [System.IO.Compression.CompressionMode]::Decompress)
        try {
            $outStream = [System.IO.File]::Create($tempFile)
            try { $gz.CopyTo($outStream) } finally { $outStream.Dispose() }
        }
        finally { $gz.Dispose() }
    }
    finally { $inStream.Dispose() }
    $source = $tempFile
}

try {
    if (-not $Force) {
        $mode = if ($NoClean) { "restore into the database as-is" } else { "drop existing objects, then restore" }
        Write-Host ""
        Write-Host "  Restore target : $targetDb ($where)"
        Write-Host "  Backup file    : $File"
        Write-Host "  Mode           : $mode"
        Write-Host ""
        Write-Host "  This replaces the data in '$targetDb'. Anything written since the backup is lost."
        Write-Host ""
        $answer = Read-Host "Type the database name ($targetDb) to continue"
        if ($answer -ne $targetDb) { throw "aborted" }
    }

    # --- Restore ---------------------------------------------------------------------------------

    $restoreArgs = @("--no-owner", "--no-privileges", "--exit-on-error", "--verbose")
    if (-not $NoClean) { $restoreArgs += @("--clean", "--if-exists") }
    if ($Jobs -gt 1) { $restoreArgs += "--jobs=$Jobs" }

    Write-Step "restoring into $targetDb"
    if ($useDocker) {
        # -T: no TTY, so the custom-format bytes reach pg_restore unmodified. cmd.exe does the redirection
        # because PowerShell 5.1 pipelines would corrupt the binary stream.
        $execArgs = @("compose", "exec", "-T", $Service, "pg_restore", "-U", $pgUser, "--dbname=$targetDb") + $restoreArgs
        $quoted = ($execArgs | ForEach-Object { if ($_ -match '\s') { "`"$_`"" } else { $_ } }) -join ' '
        & cmd.exe /c "docker $quoted < `"$source`""
        if ($LASTEXITCODE -ne 0) { throw "pg_restore failed with exit code $LASTEXITCODE" }
    }
    else {
        & pg_restore "--dbname=$url" @restoreArgs $source
        if ($LASTEXITCODE -ne 0) { throw "pg_restore failed with exit code $LASTEXITCODE" }
    }
}
finally {
    if ($tempFile -and (Test-Path $tempFile)) { Remove-Item $tempFile -Force -ErrorAction SilentlyContinue }
}

Write-Step "restore finished - now verify: alembic current, and the row counts in docs/runbooks/restore-drill.md"
