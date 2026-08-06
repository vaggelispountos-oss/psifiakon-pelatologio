#!/usr/bin/env bash
# backup_db.sh
# --------------------------------------------------------------------
# Dump ολόκληρης της Postgres βάσης (pg_dump) σε ένα gzip αρχείο.
# Stopgap μέχρι να αναβαθμιστεί το Render Postgres σε paid plan (που
# έχει automated daily backups) — το free plan ΔΕΝ τα προσφέρει, και
# διαγράφεται μετά από κάποιο διάστημα, οπότε μέχρι τότε αυτό είναι η
# μόνη προστασία από απώλεια δεδομένων πελατών.
#
# Χρήση:
#   DATABASE_URL=postgres://... ./backup_db.sh [output_dir]
#
# Τρέχει είτε χειροκίνητα, είτε από το .github/workflows/backup.yml
# (scheduled, καθημερινά) — δες εκεί για τα σχετικά GitHub Secrets.
# --------------------------------------------------------------------
set -euo pipefail

if [ -z "${DATABASE_URL:-}" ]; then
  echo "ERROR: DATABASE_URL δεν έχει οριστεί." >&2
  exit 1
fi

OUT_DIR="${1:-./backups}"
mkdir -p "$OUT_DIR"

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_FILE="$OUT_DIR/dcl-backup-$TIMESTAMP.sql.gz"

echo "Dumping database to $OUT_FILE ..."
pg_dump "$DATABASE_URL" | gzip > "$OUT_FILE"
echo "Done: $(du -h "$OUT_FILE" | cut -f1)"
