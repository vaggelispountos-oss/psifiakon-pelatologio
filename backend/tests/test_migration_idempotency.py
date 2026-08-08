"""
test_migration_idempotency.py
--------------------------------------------------------------------
Regression test για το περιστατικό της 8ης Αυγούστου 2026, όπου ΤΕΣΣΕΡΑ
συνεχόμενα production deploys απέτυχαν σιωπηλά.

ΤΙ ΕΙΧΕ ΓΙΝΕΙ: το scripts/migrate.py έτρεχε το
_sync_missing_nullable_columns() ΠΡΙΝ το `alembic upgrade head`. Το sync
σαρώνει το models.py και προσθέτει όποια nullable στήλη λείπει — δηλαδή
πρόλαβε και πρόσθεσε ακριβώς τις στήλες που επρόκειτο να προσθέσει το
migration 0004. Το Alembic μετά πήγε να τις ξαναπροσθέσει και το build
έσκασε. Επειδή το sync κάνει commit ΠΡΙΝ σκάσει το upgrade, η βάση έμεινε
μισο-μεταναστευμένη (στήλες υπάρχουν, alembic_version κολλημένο στο 0003)
και κάθε επόμενο deploy απέτυχε ΙΔΙΑ, επ' άπειρον.

ΓΙΑΤΙ ΔΕΝ ΤΟ ΕΠΙΑΣΕ ΚΑΝΕΝΑ TEST ΤΟΤΕ: τα tests τρέχουν πάνω σε βάση που
είναι ήδη στο head, οπότε το sync δεν βρίσκει τίποτα να προσθέσει και δεν
υπάρχει σύγκρουση. Το bug εμφανιζόταν ΜΟΝΟ όταν υπήρχε εκκρεμές migration
— δηλαδή ακριβώς σε κάθε πραγματικό deploy, και ποτέ στο CI.

Αυτά τα tests στήνουν ρητά την κατάσταση «βάση πίσω από το head» ώστε το
κενό να μην ξαναϋπάρξει.
--------------------------------------------------------------------
"""
import os
import sys

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, inspect, text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config as config_module  # noqa: E402
from config import BASE_DIR  # noqa: E402

HEAD_REVISION = "0006"


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """
    Απομονωμένη SQLite βάση. Το monkeypatch στο Config είναι απαραίτητο
    επειδή ΚΑΙ το migrations/env.py ΚΑΙ το scripts/migrate.py διαβάζουν το
    ίδιο Config.SQLALCHEMY_DATABASE_URI — αλλιώς το test θα έτρεχε
    migrations πάνω στην πραγματική dev βάση.
    """
    db_file = tmp_path / "migtest.db"
    url = f"sqlite:////{db_file}"
    monkeypatch.setattr(config_module.Config, "SQLALCHEMY_DATABASE_URI", url)
    return url


def _version(url):
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    finally:
        engine.dispose()


def test_upgrade_from_clean_database_reaches_head(temp_db):
    from scripts.migrate import upgrade_to_head

    upgrade_to_head()

    assert _version(temp_db) == HEAD_REVISION
    assert inspect(create_engine(temp_db)).has_table("employees")


def test_upgrade_succeeds_when_columns_already_added_by_old_sync(temp_db):
    """
    Η ΑΚΡΙΒΗΣ κατάσταση στην οποία κόλλησε η production: alembic_version στο
    0003, αλλά οι στήλες που προσθέτουν τα 0004/0005/0006 υπάρχουν ήδη
    (τις είχε βάλει το παλιό sync πριν σκάσει το upgrade).

    Πριν τη διόρθωση, αυτό έσκαγε με DuplicateColumn (Postgres) /
    CircularDependencyError (SQLite).
    """
    alembic_cfg = AlembicConfig(os.path.join(BASE_DIR, "alembic.ini"))
    command.upgrade(alembic_cfg, "0003")

    engine = create_engine(temp_db)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE aade_logs ADD COLUMN workshop_id INTEGER"))
        conn.execute(text("ALTER TABLE aade_logs ADD COLUMN actor_employee_id INTEGER"))
        conn.execute(
            text("ALTER TABLE dcl_entries ADD COLUMN created_by_employee_id INTEGER")
        )
        conn.execute(text("ALTER TABLE workshops ADD COLUMN email_verified_at DATETIME"))
        # Δεδομένα πελάτη — το recovery ΔΕΝ επιτρέπεται να τα χάσει.
        conn.execute(
            text(
                "INSERT INTO workshops "
                "(name, email, password_hash, subscription_status, token_epoch) "
                "VALUES ('Πελάτης', 'p@example.com', 'h', 'active', 0)"
            )
        )
    engine.dispose()

    from scripts.migrate import upgrade_to_head

    upgrade_to_head()  # πριν τη διόρθωση: exception εδώ

    assert _version(temp_db) == HEAD_REVISION

    engine = create_engine(temp_db)
    inspector = inspect(engine)
    # Ο πίνακας employees ΔΕΝ μπορούσε να είχε δημιουργηθεί από το sync
    # (πρόσθετε μόνο στήλες σε υπάρχοντες πίνακες) — άρα το migration
    # πρέπει να τον έφτιαξε τώρα.
    assert inspector.has_table("employees")
    assert inspector.has_table("email_verification_tokens")

    workshops = {c["name"]: c for c in inspector.get_columns("workshops")}
    assert workshops["email_verified"]["nullable"] is False

    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM workshops")).scalar() == 1
        # Οι υπάρχοντες πελάτες θεωρούνται επιβεβαιωμένοι, αλλιώς θα
        # κλειδώνονταν έξω αναδρομικά από το email verification.
        assert conn.execute(text("SELECT email_verified FROM workshops")).scalar()
    engine.dispose()


def test_running_migrate_twice_is_a_noop(temp_db):
    """Ιδεμποτεντικότητα: κάθε deploy τρέχει το ίδιο script ξανά."""
    from scripts.migrate import upgrade_to_head

    upgrade_to_head()
    upgrade_to_head()

    assert _version(temp_db) == HEAD_REVISION
