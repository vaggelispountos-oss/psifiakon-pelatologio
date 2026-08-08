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

⚠️ ΣΥΝΕΧΕΙΑ ΤΟΥ ΙΣΤΟΡΙΚΟΥ (μετά το πρώτο πραγματικό migration πέρα από το
baseline): αποδείχθηκε ότι το "stamp στο 0001" ΔΕΝ αρκεί όταν η πραγματική
production βάση ΔΕΝ ταιριάζει ΑΚΡΙΒΩΣ με ό,τι περιγράφει το migration 0001
— π.χ. το dcl_entries.aade_state προστέθηκε στο models.py ΠΡΙΝ φτιαχτεί το
baseline migration, οπότε το 0001 "υπόσχεται" αυτή τη στήλη, αλλά η
ΠΑΛΙΑ, ήδη υπάρχουσα production βάση (φτιαγμένη πριν υπάρξει καν αυτή η
στήλη στον κώδικα) δεν την είχε ποτέ. Το stamp είπε στο Alembic "είσαι
ήδη εδώ" χωρίς να το επαληθεύσει — αποτέλεσμα: UndefinedColumn σε runtime,
ΠΟΛΥ αργότερα, σε endpoint που δεν έχει καμία σχέση με migrations.

Γι' αυτό, ΠΡΙΝ από οποιαδήποτε απόφαση stamp/upgrade, αυτό το script κάνει
ΠΡΩΤΑ ένα ανεξάρτητο, μη-βασισμένο-στο-alembic_version πέρασμα: συγκρίνει
ΚΑΘΕ στήλη που δηλώνει το models.py με ό,τι ΠΡΑΓΜΑΤΙΚΑ υπάρχει στη βάση
(ΟΧΙ βάσει του τι λέει το alembic_version — βάσει introspection), και
προσθέτει ΜΟΝΟ nullable στήλες που λείπουν (ίδιο, ασφαλές μοτίβο με το
παλιό _add_missing_columns — ΔΕΝ αγγίζει NOT NULL στήλες, αυτές θέλουν
πραγματικό migration με backfill, όπως το 0002/token_epoch). Αυτό κάνει
το όλο pipeline ανθεκτικό σε ΟΠΟΙΑΔΗΠΟΤΕ ιστορική απόκλιση, όχι μόνο στα
δύο σενάρια (κενή/legacy) που είχαν προβλεφθεί αρχικά.

Ασφαλές να τρέχει σε ΚΑΘΕ deploy/boot — πλήρως ιδεμπότεντ.
--------------------------------------------------------------------
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, inspect, text

from config import BASE_DIR, Config as AppConfig

# Ο πρώτος πίνακας του baseline migration (models.Workshop) — χρησιμοποιείται
# ΜΟΝΟ ως δείκτης "υπάρχει ήδη σχήμα εδώ;", όχι για δεδομένα.
_BASELINE_PROBE_TABLE = "workshops"
_BASELINE_REVISION = "0001"


def _sync_missing_nullable_columns(engine):
    """
    Introspection-based repair: για ΚΑΘΕ πίνακα/στήλη που δηλώνει το
    models.py, αν λείπει από την ΠΡΑΓΜΑΤΙΚΗ βάση (ανεξάρτητα από το τι
    πιστεύει το alembic_version), πρόσθεσέ την — ΜΟΝΟ αν είναι nullable
    (χωρίς default value δεν μπορούμε να την προσθέσουμε με ασφάλεια σε
    πίνακα με υπάρχουσες γραμμές· αυτές θέλουν πραγματικό migration).
    """
    # Εισαγωγή εδώ (όχι στην κορυφή του αρχείου) ώστε το `models` module να
    # φορτώνεται με το ΣΩΣΤΟ sys.path (μπήκε λίγες γραμμές πιο πάνω).
    from models import db as _db

    inspector = inspect(engine)
    with engine.begin() as conn:
        for table in _db.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue  # νέος πίνακας -> θα τον φτιάξει το alembic upgrade
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                if not column.nullable:
                    print(
                        f"[migrate] ΠΡΟΣΟΧΗ: λείπει η NOT NULL στήλη "
                        f"'{table.name}.{column.name}' — χρειάζεται πραγματικό "
                        f"Alembic migration με backfill (δεν προστέθηκε αυτόματα)."
                    )
                    continue
                col_type = column.type.compile(engine.dialect)
                conn.execute(
                    text(
                        f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'
                    )
                )
                print(f"[migrate] Πρόσθεσα στήλη που έλειπε: {table.name}.{column.name}")


def upgrade_to_head():
    """
    Reusable πυρήνας — καλείται από εδώ (CLI/buildCommand), από το
    `python app.py` dev bootstrap, ΚΑΙ από τα tests (conftest.py). ΜΙΑ
    υλοποίηση της λογικής "sync ό,τι λείπει, stamp αν χρειάζεται, μετά
    upgrade", ώστε να μην υπάρχουν τρία σημεία που μπορούν να
    ξεσυγχρονιστούν.
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

    # ⚠️ Η ΣΕΙΡΑ ΕΔΩ ΕΙΝΑΙ ΚΡΙΣΙΜΗ — upgrade ΠΡΩΤΑ, sync ΜΕΤΑ.
    #
    # Παλιότερα το _sync_missing_nullable_columns έτρεχε ΠΡΙΝ το upgrade. Το
    # sync σαρώνει το models.py και προσθέτει όποια nullable στήλη λείπει,
    # οπότε πρόλαβε και πρόσθεσε ακριβώς τις στήλες που επρόκειτο να
    # προσθέσει το migration 0004 — το Alembic μετά πήγε να τις
    # ξαναπροσθέσει και το build έσκασε (DuplicateColumn σε Postgres).
    # Χειρότερα, το sync κάνει commit πριν σκάσει το upgrade, οπότε η βάση
    # έμενε μισο-μεταναστευμένη και ΚΑΘΕ επόμενο deploy απέτυχε ίδια.
    # Τέσσερα production deploys χάθηκαν έτσι (8 Αυγ 2026).
    #
    # Με αυτή τη σειρά, τα migrations βρίσκουν τη βάση όπως την περιμένουν,
    # και το sync κρατά τον αρχικό του ρόλο: δίχτυ ασφαλείας για ιστορική
    # απόκλιση που ΚΑΝΕΝΑ migration δεν καλύπτει (δες το docstring παραπάνω
    # για το περιστατικό με το aade_state).
    command.upgrade(alembic_cfg, "head")

    engine = create_engine(AppConfig.SQLALCHEMY_DATABASE_URI)
    try:
        if inspect(engine).has_table(_BASELINE_PROBE_TABLE):
            _sync_missing_nullable_columns(engine)
    finally:
        engine.dispose()


if __name__ == "__main__":
    upgrade_to_head()
