#!/usr/bin/env bash
# Back up the BountyFlow PostgreSQL database to a timestamped pg_dump custom-format file with a checksum.
#
# Usage:
#   scripts/backup-db.sh [options]
#
# Works against the docker compose Postgres service or a managed database reached through DATABASE_URL.
# The custom format (-F c) is what pg_restore reads and is already zlib-compressed, so --gzip usually buys very
# little; it exists for pipelines that insist on .gz. See docs/runbooks/postgres-backup-restore.md.

set -euo pipefail

OUT_DIR="./backups"
MODE=""
URL_ARG=""
SERVICE="postgres"
RETENTION_DAYS=0
GZIP=0
COMPRESS=()

usage() {
  cat <<'USAGE'
Back up the BountyFlow database (pg_dump custom format + sha256 checksum).

Usage: scripts/backup-db.sh [options]

  --out-dir DIR         Where to write the dump (default: ./backups)
  --docker              Run pg_dump inside the compose postgres service (default when DATABASE_URL is unset)
  --database-url URL    Dump this database with the local pg_dump (a managed service, for example)
  --service NAME        Compose service name used by --docker (default: postgres)
  --retention-days N    After a successful run, delete this script's own older backups (default: 0 = keep all)
  --gzip                gzip the dump afterwards
  --no-compress         pg_dump --compress=0; pair with --gzip when a plain .gz is required downstream
  -h, --help            Show this help

Environment:
  DATABASE_URL          SQLAlchemy or libpq URL. A postgresql+psycopg:// prefix is normalised to postgresql://
  POSTGRES_USER         Role used by --docker (default: bountyflow)
  POSTGRES_DB           Database used by --docker (default: bountyflow)
  PGPASSWORD            Passed through to pg_dump when --database-url carries no password

Writes, in --out-dir:
  bountyflow-<db>-<UTC timestamp>.dump[.gz]
  bountyflow-<db>-<UTC timestamp>.dump[.gz].sha256    verify with: sha256sum -c <file>.sha256
USAGE
}

die() { printf 'error: %s\n' "$*" >&2; exit 1; }
log() { printf '==> %s\n' "$*" >&2; }

while [ $# -gt 0 ]; do
  case "$1" in
    --out-dir) OUT_DIR="${2:?--out-dir needs a directory}"; shift 2 ;;
    --docker) MODE="docker"; shift ;;
    --database-url) MODE="url"; URL_ARG="${2:?--database-url needs a URL}"; shift 2 ;;
    --service) SERVICE="${2:?--service needs a name}"; shift 2 ;;
    --retention-days) RETENTION_DAYS="${2:?--retention-days needs a number}"; shift 2 ;;
    --gzip) GZIP=1; shift ;;
    --no-compress) COMPRESS=(--compress=0); shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
done

case "$RETENTION_DAYS" in
  ''|*[!0-9]*) die "--retention-days must be a whole number" ;;
esac

# libpq does not understand SQLAlchemy's driver suffix.
normalise_url() { printf '%s' "$1" | sed 's|^postgresql+psycopg://|postgresql://|'; }
# Database name: the last path segment, without any ?query.
db_name_from_url() { printf '%s' "$1" | sed 's|?.*$||; s|.*/||'; }

if [ -z "$MODE" ]; then
  if [ -n "${DATABASE_URL:-}" ]; then MODE="url"; URL_ARG="$DATABASE_URL"; else MODE="docker"; fi
fi

case "$MODE" in
  docker)
    command -v docker >/dev/null 2>&1 || die "docker not found in PATH"
    PG_USER="${POSTGRES_USER:-bountyflow}"
    PG_DB="${POSTGRES_DB:-bountyflow}"
    LABEL="$PG_DB"
    ;;
  url)
    command -v pg_dump >/dev/null 2>&1 || die "pg_dump not found in PATH (install the PostgreSQL client tools)"
    URL="$(normalise_url "$URL_ARG")"
    LABEL="$(db_name_from_url "$URL")"
    [ -n "$LABEL" ] || die "could not read a database name out of the URL"
    ;;
esac

mkdir -p "$OUT_DIR"
OUT_DIR="${OUT_DIR%/}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TARGET="$OUT_DIR/bountyflow-${LABEL}-${STAMP}.dump"
TMP="$TARGET.partial"
# A failed dump must never be left behind looking like a usable backup.
trap 'rm -f "$TMP"' EXIT

log "dumping $LABEL to $TARGET"
if [ "$MODE" = "docker" ]; then
  # -T: no TTY, so the custom-format bytes reach the file unmodified.
  docker compose exec -T "$SERVICE" \
    pg_dump -U "$PG_USER" -d "$PG_DB" --format=custom --no-owner --no-privileges "${COMPRESS[@]}" >"$TMP"
else
  pg_dump --dbname="$URL" --format=custom --no-owner --no-privileges "${COMPRESS[@]}" --file="$TMP"
fi

[ -s "$TMP" ] || die "the dump is empty — nothing was written"
mv "$TMP" "$TARGET"
trap - EXIT

if [ "$GZIP" -eq 1 ]; then
  command -v gzip >/dev/null 2>&1 || die "gzip not found in PATH"
  log "compressing"
  gzip -f "$TARGET"
  TARGET="$TARGET.gz"
fi

checksum_file="$TARGET.sha256"
if command -v sha256sum >/dev/null 2>&1; then
  ( cd "$(dirname "$TARGET")" && sha256sum "$(basename "$TARGET")" >"$(basename "$checksum_file")" )
elif command -v shasum >/dev/null 2>&1; then
  ( cd "$(dirname "$TARGET")" && shasum -a 256 "$(basename "$TARGET")" >"$(basename "$checksum_file")" )
else
  die "neither sha256sum nor shasum is available; the dump exists but has no checksum"
fi

log "wrote $TARGET ($(wc -c <"$TARGET" | tr -d ' ') bytes) and $checksum_file"

if [ "$RETENTION_DAYS" -gt 0 ]; then
  log "pruning backups of $LABEL older than $RETENTION_DAYS days in $OUT_DIR"
  # Only this script's own naming pattern is ever deleted.
  find "$OUT_DIR" -maxdepth 1 -type f \
    \( -name "bountyflow-${LABEL}-*.dump" -o -name "bountyflow-${LABEL}-*.dump.gz" \
       -o -name "bountyflow-${LABEL}-*.dump.sha256" -o -name "bountyflow-${LABEL}-*.dump.gz.sha256" \) \
    -mtime "+$RETENTION_DAYS" -print -delete
fi

log "done"
