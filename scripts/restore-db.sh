#!/usr/bin/env bash
# Restore a BountyFlow pg_dump custom-format backup with pg_restore.
#
# Usage:
#   scripts/restore-db.sh --file backups/bountyflow-bountyflow-20260929T031500Z.dump [options]
#
# This overwrites data. It asks for confirmation, and it refuses a target database whose name does not look like
# a BountyFlow database unless --force is given. See docs/runbooks/postgres-backup-restore.md and
# docs/runbooks/restore-drill.md.

set -euo pipefail

FILE=""
MODE=""
URL_ARG=""
SERVICE="postgres"
TARGET_DB=""
FORCE=0
JOBS=1
KEEP_CLEAN=1

# A BountyFlow database: bountyflow, bountyflow_test, bountyflow_restore_20260929, ...
EXPECTED_DB_PATTERN='^bountyflow(_[a-z0-9_]+)?$'

usage() {
  cat <<'USAGE'
Restore a BountyFlow backup (pg_restore, custom format).

Usage: scripts/restore-db.sh --file FILE [options]

  --file FILE           The .dump or .dump.gz written by scripts/backup-db.sh (required)
  --docker              Restore into the compose postgres service (default when DATABASE_URL is unset)
  --database-url URL    Restore into this database with the local pg_restore
  --service NAME        Compose service name used by --docker (default: postgres)
  --database NAME       Target database for --docker (default: $POSTGRES_DB, else bountyflow)
  --jobs N              pg_restore --jobs=N (parallel restore; incompatible with a single transaction)
  --no-clean            Do not drop existing objects first; restore into an empty database as-is
  --force               Skip the confirmation prompt and the database-name check
  -h, --help            Show this help

Environment:
  DATABASE_URL          SQLAlchemy or libpq URL. A postgresql+psycopg:// prefix is normalised to postgresql://
  POSTGRES_USER         Role used by --docker (default: bountyflow)
  POSTGRES_DB           Database used by --docker (default: bountyflow)
  PGPASSWORD            Passed through to pg_restore when --database-url carries no password

Safety:
  * The target database name must match ^bountyflow(_[a-z0-9_]+)?$ unless --force is given.
  * Without --force you must type the database name to confirm.
  * The checksum file next to the dump is verified when it is present.
USAGE
}

die() { printf 'error: %s\n' "$*" >&2; exit 1; }
log() { printf '==> %s\n' "$*" >&2; }

while [ $# -gt 0 ]; do
  case "$1" in
    --file) FILE="${2:?--file needs a path}"; shift 2 ;;
    --docker) MODE="docker"; shift ;;
    --database-url) MODE="url"; URL_ARG="${2:?--database-url needs a URL}"; shift 2 ;;
    --service) SERVICE="${2:?--service needs a name}"; shift 2 ;;
    --database) TARGET_DB="${2:?--database needs a name}"; shift 2 ;;
    --jobs) JOBS="${2:?--jobs needs a number}"; shift 2 ;;
    --no-clean) KEEP_CLEAN=0; shift ;;
    --force) FORCE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
done

[ -n "$FILE" ] || { usage >&2; die "--file is required"; }
[ -f "$FILE" ] || die "no such file: $FILE"
case "$JOBS" in ''|*[!0-9]*) die "--jobs must be a whole number" ;; esac
[ "$JOBS" -ge 1 ] || die "--jobs must be at least 1"

normalise_url() { printf '%s' "$1" | sed 's|^postgresql+psycopg://|postgresql://|'; }
db_name_from_url() { printf '%s' "$1" | sed 's|?.*$||; s|.*/||'; }

if [ -z "$MODE" ]; then
  if [ -n "${DATABASE_URL:-}" ]; then MODE="url"; URL_ARG="$DATABASE_URL"; else MODE="docker"; fi
fi

case "$MODE" in
  docker)
    command -v docker >/dev/null 2>&1 || die "docker not found in PATH"
    PG_USER="${POSTGRES_USER:-bountyflow}"
    [ -n "$TARGET_DB" ] || TARGET_DB="${POSTGRES_DB:-bountyflow}"
    WHERE="compose service '$SERVICE'"
    ;;
  url)
    command -v pg_restore >/dev/null 2>&1 || die "pg_restore not found in PATH"
    URL="$(normalise_url "$URL_ARG")"
    TARGET_DB="$(db_name_from_url "$URL")"
    [ -n "$TARGET_DB" ] || die "could not read a database name out of the URL"
    # Never print the URL: it carries the password.
    WHERE="the database in DATABASE_URL"
    ;;
esac

# --- Checks -------------------------------------------------------------------------------------

if ! printf '%s' "$TARGET_DB" | grep -Eq "$EXPECTED_DB_PATTERN"; then
  [ "$FORCE" -eq 1 ] || die "target database '$TARGET_DB' does not match $EXPECTED_DB_PATTERN — pass --force if that is really the target"
  log "WARNING: '$TARGET_DB' does not look like a BountyFlow database; --force was given"
fi

CHECKSUM="$FILE.sha256"
if [ -f "$CHECKSUM" ]; then
  log "verifying $CHECKSUM"
  if command -v sha256sum >/dev/null 2>&1; then
    ( cd "$(dirname "$FILE")" && sha256sum -c "$(basename "$CHECKSUM")" ) >/dev/null \
      || die "checksum mismatch — do not restore this file"
  elif command -v shasum >/dev/null 2>&1; then
    ( cd "$(dirname "$FILE")" && shasum -a 256 -c "$(basename "$CHECKSUM")" ) >/dev/null \
      || die "checksum mismatch — do not restore this file"
  else
    log "no sha256sum or shasum available; skipping checksum verification"
  fi
else
  log "no checksum file next to the dump; continuing unverified"
fi

# gzip-compressed dumps are expanded to a temporary file: pg_restore needs to seek in a custom-format archive.
SOURCE="$FILE"
CLEANUP=""
case "$FILE" in
  *.gz)
    command -v gzip >/dev/null 2>&1 || die "gzip not found in PATH"
    SOURCE="$(mktemp -t bountyflow-restore.XXXXXX)"
    CLEANUP="$SOURCE"
    trap 'rm -f "$CLEANUP"' EXIT
    log "expanding $FILE"
    gzip -dc "$FILE" >"$SOURCE"
    ;;
esac

if [ "$FORCE" -ne 1 ]; then
  cat >&2 <<EOF

  Restore target : $TARGET_DB ($WHERE)
  Backup file    : $FILE
  Mode           : $([ "$KEEP_CLEAN" -eq 1 ] && echo 'drop existing objects, then restore' || echo 'restore into the database as-is')

  This replaces the data in '$TARGET_DB'. Anything written since the backup is lost.

EOF
  printf "Type the database name (%s) to continue: " "$TARGET_DB" >&2
  read -r answer
  [ "$answer" = "$TARGET_DB" ] || die "aborted"
fi

# --- Restore ------------------------------------------------------------------------------------

ARGS=(--no-owner --no-privileges --exit-on-error --verbose)
if [ "$KEEP_CLEAN" -eq 1 ]; then ARGS+=(--clean --if-exists); fi
if [ "$JOBS" -gt 1 ]; then ARGS+=("--jobs=$JOBS"); fi

log "restoring into $TARGET_DB"
if [ "$MODE" = "docker" ]; then
  # pg_restore reads a custom-format archive from stdin fine, but a parallel restore needs to seek in a real
  # file. Copy the dump into the container for --jobs, or restore over the published port instead.
  if [ "$JOBS" -gt 1 ]; then
    die "--jobs needs a seekable file: use --database-url postgresql://…@127.0.0.1:5432/$TARGET_DB instead, or docker compose cp the dump into the container and run pg_restore there"
  fi
  docker compose exec -T "$SERVICE" \
    pg_restore -U "$PG_USER" --dbname="$TARGET_DB" "${ARGS[@]}" <"$SOURCE"
else
  pg_restore --dbname="$URL" "${ARGS[@]}" "$SOURCE"
fi

log "restore finished — now verify: alembic current, and the row counts in docs/runbooks/restore-drill.md"
