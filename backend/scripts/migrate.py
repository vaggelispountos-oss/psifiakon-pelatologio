#!/usr/bin/env python
"""
scripts/migrate.py
--------------------------------------------------------------------
Self-healing εφαρμογή του σχήματος βάσης — αντικαθιστά το σκέτο
`alembic upgrade head` στο buildCommand/dev bootstrap.

ΓΙΑΤΙ ΥΠΑΡΧΕΙ ΑΥΤΟ ΤΟ SCRIPT (και δεν φτάνει το σκέτο `alembic upgrade head`):

Όταν το Alembic μπήκε σε αυτό το project, η production βάση ΗΔΗ είχε όλους
τους πίνακες (φτιαγμένοι παλιότερα από db.create_all() + το χειροκίνητο
_add_missing_columns). Το πρώτο `alembic upgrade head` προσπάθησε να τρέξει
το baseline migration από την αρχή (CREATE TABLE workshops, ...) και έσκασε
με "relation already exists" — το build απέτυχε.

Η λύση ΤΟΤΕ ήταν χειροκίνητη: άλλαξε προσωρινά το buildCommand σε
`alembic stamp head` (σημείωσε "είσαι ήδη εδώ" χωρίς να τρέξει τίποτα),
deploy, μετά γύρνα το πίσω σε `alembic upgrade head`. Δουλεύει, αλλά είναι
εύθραυστο: αν ξεχαστεί το "γύρνα το πίσω", ΚΑΝΕΝΑ μελλοντικό migration δεν
θα εφαρμοστεί ποτέ ξανά — σιωπηλά (το stamp απλά ξαναγράφει "0001", δεν
τρέχει τίποτα καινούριο). Ήδη μπερδευτήκαμε μία φορά με αυτό το toggle.

Αυτό το script κάνει το ΙΔΙΟ πράγμα ΑΥΤΟΜΑΤΑ, ΚΑΘΕ φορά, χωρίς χειροκίνητο
βήμα να θυμάσαι:
  - Αν η βάση έχει ΗΔΗ πίνακες αλλά ΚΑΝΕΝΑ alembic_version (legacy/
    pre-Alembic state) -> stamp στο baseline ΠΡΩΤΑ, μετά upgrade.
  - Αλλιώς (κενή βάση, ή ήδη Alembic-managed) -> απλό upgrade head.
Ασφαλές να τρέχει σε ΚΑΘΕ deploy/boot — ιδεμπoτεντ και στις τρεις
περιπτώσεις.
--------------------------------------------------------------------
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, inspect

from config import BASE_DIR, Config as AppConfig

# Ο πρώτος πίνακας του baseline migration (models.Workshop) — χρησιμοποιείται
# ΜΟΝΟ ως δείκτης "υπάρχει ήδη σχήμα εδώ;", όχι για δεδομένα.
_BASELINE_PROBE_TABLE = "workshops"
_BASELINE_REVISION = "0001"


def upgrade_to_head():
    """
    Reusable πυρήνας — καλείται από εδώ (CLI/buildCommand), από το
    `python app.py` dev bootstrap, ΚΑΙ από τα tests (conftest.py). ΜΙΑ
    υλοποίηση της λογικής "stamp αν χρειάζεται, μετά upgrade", ώστε να μην
    υπάρχουν τρεις σημεία που μπορούν να ξεσυγχρονιστούν.
    """
    alembic_cfg = AlembicConfig(os.path.join(BASE_DIR, "alembic.ini"))

    engine = create_engine(AppConfig.SQLALCHEMY_DATABASE_URI)
    try:
        inspector = inspect(engine)
        has_alembic_version = inspector.has_table("alembic_version")
        has_app_tables = inspector.has_table(_BASELINE_PROBE_TABLE)
    finally:
        engine.dispose()

    if has_app_tables and not has_alembic_version:
        print(
            f"[migrate] Legacy schema εντοπίστηκε (υπάρχει '{_BASELINE_PROBE_TABLE}' "
            f"αλλά όχι alembic_version) — stamp στο {_BASELINE_REVISION} πριν το upgrade."
        )
        command.stamp(alembic_cfg, _BASELINE_REVISION)

    command.upgrade(alembic_cfg, "head")


if __name__ == "__main__":
    upgrade_to_head()
