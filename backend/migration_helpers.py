"""
migration_helpers.py
--------------------------------------------------------------------
Έλεγχοι ύπαρξης για idempotent migrations.

ΓΙΑΤΙ ΧΡΕΙΑΖΟΝΤΑΙ (πραγματικό περιστατικό, 2026-08-08):

Το scripts/migrate.py έτρεχε το _sync_missing_nullable_columns() ΠΡΙΝ το
`alembic upgrade head`. Το sync σαρώνει το models.py και προσθέτει με
introspection όποια nullable στήλη λείπει — δηλαδή πρόλαβε και πρόσθεσε
ακριβώς τις στήλες που επρόκειτο να προσθέσει το migration 0004. Το
Alembic μετά πήγε να τις ξαναπροσθέσει και το build έσκασε (DuplicateColumn
σε Postgres / CircularDependencyError σε SQLite).

Χειρότερα: το sync κάνει commit ΠΡΙΝ σκάσει το upgrade, οπότε η βάση
έμεινε μισο-μεταναστευμένη — στήλες προστέθηκαν, alembic_version κόλλησε
στο 0003, και ΚΑΘΕ επόμενο deploy απέτυχε με τον ίδιο τρόπο επ' άπειρον.
Τέσσερα deploys χάθηκαν έτσι.

Η σειρά στο migrate.py διορθώθηκε (upgrade ΠΡΩΤΑ, sync μετά ως repair),
αλλά αυτό ΔΕΝ αρκεί: οι ήδη χαλασμένες βάσεις (production) έχουν τις
στήλες χωρίς το αντίστοιχο alembic_version. Γι' αυτό τα migrations 0004+
ελέγχουν ΠΡΩΤΑ τι υπάρχει πραγματικά και προσπερνούν ό,τι έχει ήδη γίνει —
έτσι η βάση αυτοδιορθώνεται στο επόμενο deploy, χωρίς χειροκίνητο SQL σε
ζωντανά δεδομένα πελατών.

Σε ΚΑΘΑΡΗ βάση οι έλεγχοι δεν αλλάζουν τίποτα: όλα λείπουν, όλα
δημιουργούνται κανονικά.
--------------------------------------------------------------------
"""
import sqlalchemy as sa
from alembic import op


def _inspector():
    # Νέος inspector σε κάθε κλήση: μέσα σε ένα migration το σχήμα αλλάζει
    # καθώς προχωράμε, και ένας cached inspector θα έδειχνε παλιά εικόνα.
    return sa.inspect(op.get_bind())


def is_sqlite():
    """
    Το SQLite δεν υποστηρίζει ADD CONSTRAINT — τα foreign keys μπαίνουν μόνο
    με batch_alter_table, που ΞΑΝΑΦΤΙΑΧΝΕΙ ολόκληρο τον πίνακα. Ακριβώς αυτό
    το recreate έσκαγε με CircularDependencyError όταν οι στήλες υπήρχαν ήδη.
    Στο dev/test (SQLite) τα FK δεν επιβάλλονται καν από προεπιλογή, οπότε
    προτιμάμε να τα παραλείπουμε εκεί παρά να ρισκάρουμε table rebuild.
    Η production (Postgres) τα παίρνει κανονικά.
    """
    return op.get_bind().dialect.name == "sqlite"


def table_exists(table):
    return _inspector().has_table(table)


def column_exists(table, column):
    if not table_exists(table):
        return False
    return column in {c["name"] for c in _inspector().get_columns(table)}


def index_exists(table, index_name):
    if not table_exists(table):
        return False
    return index_name in {i["name"] for i in _inspector().get_indexes(table)}


def fk_exists(table, fk_name):
    if not table_exists(table):
        return False
    return fk_name in {
        fk.get("name") for fk in _inspector().get_foreign_keys(table)
    }


def column_is_nullable(table, column):
    for c in _inspector().get_columns(table):
        if c["name"] == column:
            return c.get("nullable", True)
    return True


def add_column_if_missing(table, column):
    """op.add_column που δεν σκάει αν η στήλη μπήκε ήδη από το παλιό sync."""
    if column_exists(table, column.name):
        print(f"[migration] {table}.{column.name} υπάρχει ήδη — παραλείπεται")
        return False
    op.add_column(table, column)
    return True


def create_index_if_missing(index_name, table, columns, unique=False):
    if index_exists(table, index_name):
        print(f"[migration] index {index_name} υπάρχει ήδη — παραλείπεται")
        return False
    op.create_index(index_name, table, columns, unique=unique)
    return True


def create_fk_if_missing(fk_name, source_table, target_table, local_cols,
                         remote_cols, ondelete=None):
    """
    Δημιουργεί FK ΜΟΝΟ σε Postgres (δες is_sqlite για το γιατί) και μόνο αν
    δεν υπάρχει ήδη.
    """
    if is_sqlite():
        return False
    if fk_exists(source_table, fk_name):
        print(f"[migration] FK {fk_name} υπάρχει ήδη — παραλείπεται")
        return False
    op.create_foreign_key(
        fk_name, source_table, target_table, local_cols, remote_cols,
        ondelete=ondelete,
    )
    return True
