<#
.SYNOPSIS
Back up the BountyFlow PostgreSQL database to a timestamped pg_dump custom-format file with a checksum.

.DESCRIPTION
Works against the docker compose Postgres service or a managed database reached through DATABASE_URL.
The custom format (-F c) is what pg_restore reads and is already zlib-compressed, so -Gzip usually buys very
little; it exists for pipelines that insist on .gz.

Writes, in -OutDir:
  bountyflow-<db>-<UTC timestamp>.dump[.gz]
  bountyflow-<db>-<UTC timestamp>.dump[.gz].sha256

See docs/runbooks/postgres-backup-restore.md.

.PARAMETER OutDir
Where to write the dump. Default: .\backups

.PARAMETER Docker
Run pg_dump inside the compose postgres service. This is the default when DATABASE_URL is not set.

.PARAMETER DatabaseUrl
Dump this database with the local pg_dump. A postgresql+psycopg:// prefix is normalised to postgresql://.
Defaults to $env:DATABASE_URL.

.PARAMETER Service
Compose service name used by -Docker. Default: postgres

.PARAMETER RetentionDays
After a successful run, delete this script's own older backups of the same database. 0 keeps everything.

.PARAMETER Gzip
gzip the dump afterwards (uses System.IO.Compression.GZipStream; no external gzip needed).

.PARAMETER NoCompress
Pass --compress=0 to pg_dump. Pair with -Gzip when a plain .gz is required downstream.

.EXAMPLE
powershell -ExecutionPolicy Bypass -File scripts/backup-db.ps1 -Docker -RetentionDays 14

.EXAMPLE
powershell -ExecutionPolicy Bypass -File scripts/backup-db.ps1 -DatabaseUrl "postgresql://bountyflow:...@db.example.com:5432/bountyflow" -Gzip
#>
[CmdletBinding()]
param(
    [string]$OutDir = ".\backups",
    [switch]$Docker,
    [string]$DatabaseUrl = $env:DATABASE_URL,
    [string]$Service = "postgres",
    [ValidateRange(0, 3650)]
    [int]$RetentionDays = 0,
    [switch]$Gzip,
    [switch]$NoCompress
)

$ErrorActionPreference = "Stop"

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

# --- Mode ---------------------------------------------------------------------------------------

$useDocker = $Docker.IsPresent -or [string]::IsNullOrWhiteSpace($DatabaseUrl)

if ($useDocker) {
    if (-not (Test-Command docker)) { throw "docker not found in PATH" }
    $pgUser = if ($env:POSTGRES_USER) { $env:POSTGRES_USER } else { "bountyflow" }
    $pgDb = if ($env:POSTGRES_DB) { $env:POSTGRES_DB } else { "bountyflow" }
    $label = $pgDb
}
else {
    if (-not (Test-Command pg_dump)) { throw "pg_dump not found in PATH (install the PostgreSQL client tools)" }
    $url = Get-NormalisedUrl -Url $DatabaseUrl
    $label = Get-DatabaseName -Url $url
    if ([string]::IsNullOrWhiteSpace($label)) { throw "could not read a database name out of the URL" }
}

# --- Dump ---------------------------------------------------------------------------------------

if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Path $OutDir -Force | Out-Null }
$outFull = (Resolve-Path $OutDir).Path
$stamp = [DateTime]::UtcNow.ToString("yyyyMMdd'T'HHmmss'Z'")
$target = Join-Path $outFull "bountyflow-$label-$stamp.dump"
$temp = "$target.partial"

$compressArgs = @()
if ($NoCompress) { $compressArgs = @("--compress=0") }

Write-Step "dumping $label to $target"
try {
    if ($useDocker) {
        # -T: no TTY, so the custom-format bytes reach the file unmodified.
        $dumpArgs = @(
            "compose", "exec", "-T", $Service,
            "pg_dump", "-U", $pgUser, "-d", $pgDb,
            "--format=custom", "--no-owner", "--no-privileges"
        ) + $compressArgs
        # cmd.exe does the redirection so the stream stays binary; PowerShell 5.1 pipelines would corrupt it.
        $quoted = ($dumpArgs | ForEach-Object { if ($_ -match '\s') { "`"$_`"" } else { $_ } }) -join ' '
        & cmd.exe /c "docker $quoted > `"$temp`""
        if ($LASTEXITCODE -ne 0) { throw "pg_dump failed with exit code $LASTEXITCODE" }
    }
    else {
        $dumpArgs = @(
            "--dbname=$url", "--format=custom", "--no-owner", "--no-privileges", "--file=$temp"
        ) + $compressArgs
        & pg_dump @dumpArgs
        if ($LASTEXITCODE -ne 0) { throw "pg_dump failed with exit code $LASTEXITCODE" }
    }

    if (-not (Test-Path $temp) -or (Get-Item $temp).Length -eq 0) {
        throw "the dump is empty - nothing was written"
    }
    Move-Item -Path $temp -Destination $target -Force
}
catch {
    # A failed dump must never be left behind looking like a usable backup.
    if (Test-Path $temp) { Remove-Item $temp -Force -ErrorAction SilentlyContinue }
    throw
}

# --- Compress and checksum ----------------------------------------------------------------------

if ($Gzip) {
    Write-Step "compressing"
    $gzPath = "$target.gz"
    $source = [System.IO.File]::OpenRead($target)
    try {
        $sink = [System.IO.File]::Create($gzPath)
        try {
            $gz = New-Object System.IO.Compression.GZipStream($sink, [System.IO.Compression.CompressionMode]::Compress)
            try { $source.CopyTo($gz) } finally { $gz.Dispose() }
        }
        finally { $sink.Dispose() }
    }
    finally { $source.Dispose() }
    Remove-Item $target -Force
    $target = $gzPath
}

$hash = (Get-FileHash -Path $target -Algorithm SHA256).Hash.ToLowerInvariant()
$checksumFile = "$target.sha256"
# sha256sum's own format, LF-terminated and without a BOM, so `sha256sum -c` reads it on Linux too.
$line = "$hash  $(Split-Path $target -Leaf)`n"
[System.IO.File]::WriteAllText($checksumFile, $line, (New-Object System.Text.UTF8Encoding($false)))

$size = (Get-Item $target).Length
Write-Step "wrote $target ($size bytes) and $checksumFile"

# --- Retention ----------------------------------------------------------------------------------

if ($RetentionDays -gt 0) {
    Write-Step "pruning backups of $label older than $RetentionDays days in $outFull"
    $cutoff = [DateTime]::UtcNow.AddDays(-$RetentionDays)
    # Only this script's own naming pattern is ever deleted.
    Get-ChildItem -Path $outFull -File -Filter "bountyflow-$label-*.dump*" |
        Where-Object { $_.LastWriteTimeUtc -lt $cutoff } |
        ForEach-Object {
            Write-Host "  removing $($_.Name)"
            Remove-Item $_.FullName -Force
        }
}

Write-Step "done"
