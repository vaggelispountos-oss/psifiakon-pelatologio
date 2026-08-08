#!/usr/bin/env bash
# backup_db.sh
# --------------------------------------------------------------------
# Backup ολόκληρης της βάσης σε ένα gzip αρχείο. Υποστηρίζει ΚΑΙ Postgres
# (production, Render) ΚΑΙ SQLite (τοπική ανάπτυξη / self-host εγκατάσταση),
# επιλέγοντας αυτόματα βάσει του scheme του DATABASE_URL.
#
# Stopgap μέχρι να αναβαθμιστεί το Render Postgres σε paid plan (που έχει
# automated daily backups) — το free plan ΔΕΝ τα προσφέρει, οπότε μέχρι τότε
# αυτό είναι η ΜΟΝΗ προστασία από απώλεια δεδομένων πελατών.
#
# Χρήση:
#   DATABASE_URL=postgres://...           ./backup_db.sh [output_dir]
#   DATABASE_URL=sqlite:///dcl.db         ./backup_db.sh [output_dir]
#   ./backup_db.sh                        # default: το τοπικό instance/dcl.db
#
# Επαναφορά: δες restore_db.sh (δίπλα σε αυτό το αρχείο).
#
# Τρέχει είτε χειροκίνητα, είτε από το .github/workflows/backup.yml
# (scheduled, καθημερινά) — δες εκεί για τα σχετικά GitHub Secrets.
# --------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"

# Ίδιο default με το config.py: σχετικό SQLite path ζει στο instance/.
DATABASE_URL="${DATABASE_URL:-sqlite:///dcl.db}"

OUT_DIR="${1:-./backups}"
mkdir -p "$OUT_DIR"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"

case "$DATABASE_URL" in
  postgres://*|postgresql://*)
    # ------------------------------------------------------------------
    # Ο πιο συχνός τρόπος να αποτύχει σιωπηλά αυτό το backup: στο GitHub
    # secret μπαίνει το ΕΣΩΤΕΡΙΚΟ connection string του Render
    # (postgres://user:pass@dpg-xxxxx-a/dbname) αντί για το External.
    # Το εσωτερικό hostname δεν έχει τελείες και επιλύεται ΜΟΝΟ μέσα στο
    # δίκτυο του Render — από GitHub Actions δίνει σκέτο
    # "could not translate host name", που δεν λέει σε κανέναν τι φταίει.
    # Ακριβώς έτσι έτρεχε το backup.yml και αποτύγχανε κάθε μέρα χωρίς να
    # το προσέξει κανείς (καμία επιτυχής εκτέλεση ποτέ).
    # ------------------------------------------------------------------
    host="${DATABASE_URL#*@}"      # κόψε ό,τι είναι πριν το @
    host="${host%%/*}"             # κράτα μόνο host[:port]
    host="${host%%:*}"             # πέτα το port
    if [[ "$host" == dpg-* && "$host" != *.* ]]; then
      echo "ERROR: Το DATABASE_URL δείχνει στο ΕΣΩΤΕΡΙΚΟ hostname του Render" >&2
      echo "       ('$host' — χωρίς domain), που επιλύεται μόνο ΜΕΣΑ στο" >&2
      echo "       Render. Από GitHub Actions / το μηχάνημά σου χρειάζεσαι το" >&2
      echo "       External Database URL από το Render dashboard" >&2
      echo "       (μοιάζει με dpg-xxxxx-a.frankfurt-postgres.render.com)." >&2
      exit 2
    fi

    OUT_FILE="$OUT_DIR/dcl-backup-$TIMESTAMP.sql.gz"
    echo "Postgres -> $OUT_FILE"
    # pipefail (πάνω) ώστε αποτυχία του pg_dump να ΜΗΝ κρύβεται πίσω από
    # ένα επιτυχημένο gzip που παράγει έγκυρο αλλά ΑΔΕΙΟ αρχείο.
    pg_dump "$DATABASE_URL" | gzip > "$OUT_FILE"
    ;;

  sqlite://*)
    # sqlite:////abs/path (4 slashes) ή sqlite:///relative (3).
    path="${DATABASE_URL#sqlite://}"
    if [[ "$path" == //* ]]; then
      db_path="${path#/}"                     # απόλυτο
    else
      # Σχετικό: ΙΔΙΑ σύμβαση με το config._normalize_db_url — ζει στο
      # instance/, όχι στο cwd απ' όπου έτυχε να τρέξει το script.
      db_path="$BACKEND_DIR/instance/${path#/}"
    fi

    if [ ! -f "$db_path" ]; then
      echo "ERROR: Δεν βρέθηκε αρχείο SQLite στο '$db_path'." >&2
      exit 1
    fi

    OUT_FILE="$OUT_DIR/dcl-backup-$TIMESTAMP.db.gz"
    echo "SQLite ($db_path) -> $OUT_FILE"
    # VACUUM INTO και ΟΧΙ cp: το cp πάνω σε ανοιχτή βάση μπορεί να
    # αντιγράψει ασυνεπή κατάσταση (μισο-γραμμένη σελίδα, ή -wal που δεν
    # έχει ακόμα checkpointαριστεί). Το VACUUM INTO παίρνει συνεπές
    # snapshot ΖΩΝΤΑΝΗΣ βάσης και το γράφει συμπυκνωμένο. (SQLite 3.27+)
    tmp_copy="$(mktemp -u "${TMPDIR:-/tmp}/dcl-backup-XXXXXX.db")"
    sqlite3 "$db_path" "VACUUM INTO '$tmp_copy'"
    gzip -c "$tmp_copy" > "$OUT_FILE"
    rm -f "$tmp_copy"
    ;;

  *)
    echo "ERROR: Μη υποστηριζόμενο DATABASE_URL scheme: '$DATABASE_URL'" >&2
    echo "       Αναμένεται postgres://, postgresql:// ή sqlite://" >&2
    exit 1
    ;;
esac

# Δίχτυ ασφαλείας: ένα backup 20 bytes είναι «επιτυχία» για τον φλοιό αλλά
# άχρηστο για σένα. Καλύτερα να σκάσει τώρα παρά να το ανακαλύψεις τη μέρα
# που θα το χρειαστείς.
size_bytes="$(wc -c < "$OUT_FILE" | tr -d ' ')"
if [ "$size_bytes" -lt 1024 ]; then
  echo "ERROR: Το backup είναι ύποπτα μικρό ($size_bytes bytes) — πιθανόν κενό." >&2
  exit 1
fi

echo "OK: $(du -h "$OUT_FILE" | cut -f1) -> $OUT_FILE"
