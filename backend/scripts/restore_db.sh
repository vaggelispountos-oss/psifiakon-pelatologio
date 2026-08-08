#!/usr/bin/env bash
# restore_db.sh
# --------------------------------------------------------------------
# Επαναφορά της βάσης από αρχείο που παρήγαγε το backup_db.sh.
# Υποστηρίζει Postgres (.sql.gz) και SQLite (.db.gz), επιλέγοντας βάσει
# του scheme του DATABASE_URL.
#
# Χρήση:
#   DATABASE_URL=postgres://...   ./restore_db.sh backups/dcl-backup-....sql.gz
#   DATABASE_URL=sqlite:///dcl.db ./restore_db.sh backups/dcl-backup-....db.gz
#
#   # Χωρίς ερώτηση επιβεβαίωσης (π.χ. μέσα σε script):
#   FORCE=1 ./restore_db.sh <αρχείο>
#
# ⚠️ ΚΑΤΑΣΤΡΟΦΙΚΟ: ΣΒΗΝΕΙ τα τρέχοντα δεδομένα και τα αντικαθιστά με το
# περιεχόμενο του backup. Ζητά ρητή επιβεβαίωση εκτός αν FORCE=1.
#
# ⚠️ ΚΛΕΙΔΙ ΚΡΥΠΤΟΓΡΑΦΗΣΗΣ: τα aade_subscription_key είναι κρυπτογραφημένα
# με το ENCRYPTION_KEY (δες crypto.py). Επαναφορά backup ΜΕ ΔΙΑΦΟΡΕΤΙΚΟ
# ENCRYPTION_KEY από αυτό που ίσχυε όταν πάρθηκε το backup αφήνει τα κλειδιά
# ΑΑΔΕ μη αναγνώσιμα — οι πελάτες θα πρέπει να τα ξαναπεράσουν από τις
# Ρυθμίσεις. Κράτα το ENCRYPTION_KEY μαζί με τα backups.
# --------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"

BACKUP_FILE="${1:-}"
if [ -z "$BACKUP_FILE" ]; then
  echo "Χρήση: DATABASE_URL=... $0 <backup-file.(sql|db).gz>" >&2
  exit 1
fi
if [ ! -f "$BACKUP_FILE" ]; then
  echo "ERROR: Δεν βρέθηκε το αρχείο '$BACKUP_FILE'." >&2
  exit 1
fi

DATABASE_URL="${DATABASE_URL:-sqlite:///dcl.db}"

confirm() {
  # Ξεχωριστή συνάρτηση ώστε το μήνυμα να λέει ΑΚΡΙΒΩΣ πού θα γραφτεί —
  # ένα "σίγουρα;" χωρίς προορισμό είναι πώς γίνονται τα ατυχήματα.
  if [ "${FORCE:-}" = "1" ]; then
    return 0
  fi
  echo "⚠️  Θα ΔΙΑΓΡΑΦΟΥΝ τα τρέχοντα δεδομένα στο:"
  echo "      $1"
  echo "    και θα αντικατασταθούν από:"
  echo "      $BACKUP_FILE"
  printf "Γράψε 'ναι' για συνέχεια: "
  read -r answer
  if [ "$answer" != "ναι" ]; then
    echo "Ακυρώθηκε." >&2
    exit 1
  fi
}

case "$DATABASE_URL" in
  postgres://*|postgresql://*)
    case "$BACKUP_FILE" in
      *.sql.gz) ;;
      *) echo "ERROR: Για Postgres περιμένω αρχείο .sql.gz (βρήκα '$BACKUP_FILE')." >&2; exit 1 ;;
    esac

    host="${DATABASE_URL#*@}"; host="${host%%/*}"; host="${host%%:*}"
    if [[ "$host" == dpg-* && "$host" != *.* ]]; then
      echo "ERROR: Το DATABASE_URL δείχνει στο ΕΣΩΤΕΡΙΚΟ hostname του Render" >&2
      echo "       ('$host'). Χρειάζεσαι το External Database URL." >&2
      exit 2
    fi

    confirm "$host"
    echo "Επαναφορά Postgres από $BACKUP_FILE ..."
    # --clean --if-exists ζει μέσα στο dump του pg_dump μόνο αν δόθηκε στο
    # dump. Δεν το υποθέτουμε: καθαρίζουμε ρητά το public schema πρώτα,
    # αλλιώς το restore σκάει σε "already exists" πάνω σε υπάρχουσα βάση.
    psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
      -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
    gunzip -c "$BACKUP_FILE" | psql "$DATABASE_URL" -v ON_ERROR_STOP=1
    ;;

  sqlite://*)
    case "$BACKUP_FILE" in
      *.db.gz) ;;
      *) echo "ERROR: Για SQLite περιμένω αρχείο .db.gz (βρήκα '$BACKUP_FILE')." >&2; exit 1 ;;
    esac

    path="${DATABASE_URL#sqlite://}"
    if [[ "$path" == //* ]]; then
      db_path="${path#/}"
    else
      db_path="$BACKEND_DIR/instance/${path#/}"
    fi

    confirm "$db_path"
    mkdir -p "$(dirname "$db_path")"

    # Κράτα την προηγούμενη κατάσταση πριν τη σβήσεις — αν το backup
    # αποδειχθεί λάθος/κατεστραμμένο, χωρίς αυτό δεν υπάρχει γυρισμός.
    if [ -f "$db_path" ]; then
      safety="$db_path.pre-restore-$(date -u +%Y%m%dT%H%M%SZ)"
      cp "$db_path" "$safety"
      echo "Προηγούμενη βάση φυλάχθηκε: $safety"
    fi

    echo "Επαναφορά SQLite στο $db_path ..."
    gunzip -c "$BACKUP_FILE" > "$db_path"
    # Τα -wal/-shm της παλιάς βάσης δεν ταιριάζουν πια με το νέο αρχείο και
    # θα το «μόλυναν» με παλιές συναλλαγές στο πρώτο άνοιγμα.
    rm -f "$db_path-wal" "$db_path-shm"
    # Επιβεβαίωση ότι το αποτέλεσμα είναι όντως έγκυρη βάση, όχι σκουπίδια.
    sqlite3 "$db_path" "PRAGMA integrity_check;" | head -1
    ;;

  *)
    echo "ERROR: Μη υποστηριζόμενο DATABASE_URL scheme: '$DATABASE_URL'" >&2
    exit 1
    ;;
esac

echo "OK: η επαναφορά ολοκληρώθηκε."
echo "ΥΠΕΝΘΥΜΙΣΗ: αν το ENCRYPTION_KEY διαφέρει από τότε που πάρθηκε το"
echo "backup, τα κλειδιά ΑΑΔΕ θα χρειαστεί να ξαναπεραστούν από τις Ρυθμίσεις."
