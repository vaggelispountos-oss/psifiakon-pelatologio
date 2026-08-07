"""
conftest.py
--------------------------------------------------------------------
Κοινές ρυθμίσεις για ΟΛΑ τα tests.

1) Εφαρμόζει τα Alembic migrations πριν τρέξει οτιδήποτε άλλο. Παλιότερα
   αυτό γινόταν σιωπηλά μέσα στο create_app() (db.create_all() +
   _add_missing_columns) — τώρα το σχήμα είναι αποκλειστικά ευθύνη του
   Alembic (δες app.create_app / migrations/), οπότε τα tests πρέπει να το
   κάνουν ρητά αυτά, μία φορά, πριν από κάθε άλλο import/query. Γίνεται σε
   επίπεδο module (όχι fixture) ώστε να τρέχει ΠΡΙΝ φορτωθεί οποιοδήποτε
   αρχείο test.

2) Απενεργοποιεί το rate limiting (Flask-Limiter). Χωρίς αυτό, τα tests
   συνδέονται όλα από την ΙΔΙΑ IP (127.0.0.1) και μοιράζονται τον ίδιο
   in-memory μετρητή: μόλις το σύνολο των κλήσεων /api/auth/login ξεπεράσει
   το όριο (10/λεπτό), τα ΕΠΟΜΕΝΑ αρχεία tests αποτυγχάνουν με 429 — δηλαδή
   το suite γίνεται εξαρτημένο από τη ΣΕΙΡΑ εκτέλεσης και σπάει καθώς
   προστίθενται νέα tests, χωρίς να έχει αλλάξει τίποτα στον κώδικα.

   Το rate limiting ελέγχεται ξεχωριστά· δεν πρέπει να είναι κρυφή
   προϋπόθεση κάθε άλλου test.
--------------------------------------------------------------------
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.migrate import upgrade_to_head  # noqa: E402

upgrade_to_head()

from app import app as flask_app  # noqa: E402
from auth import limiter  # noqa: E402


@pytest.fixture(autouse=True, scope="session")
def _disable_rate_limiting():
    flask_app.config["RATELIMIT_ENABLED"] = False
    limiter.enabled = False
    yield
    limiter.enabled = True
