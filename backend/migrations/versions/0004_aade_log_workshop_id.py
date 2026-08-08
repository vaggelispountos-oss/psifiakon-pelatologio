"""add workshop_id to aade_logs + backfill

Χωρίς workshop_id, το /api/account DELETE δεν μπορούσε να σβήσει logs
χωρίς dcl_entry_id (π.χ. «Έλεγχος σύνδεσης» στις Ρυθμίσεις — δες
app._log_aade) -> ημιτελής GDPR διαγραφή + πίνακας aade_logs που μεγαλώνει
χωρίς όριο για ήδη διαγραμμένους λογαριασμούς.

nullable=True ΜΟΝΙΜΑ (όχι μεταβατικό βήμα προς NOT NULL, δες 0002 για το
αντίθετο πρότυπο): οι ΠΑΛΙΕΣ γραμμές χωρίς dcl_entry_id δεν μπορούν να
αναχθούν σε συγκεκριμένο συνεργείο πλέον — backfill ΜΟΝΟ όσων συνδέονται
με dcl_entries (JOIN). ΚΑΘΕ νέα γραμμή γεμίζει πάντα το workshop_id.

Revision ID: 0004
Revises: 0003
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from migration_helpers import (
    add_column_if_missing,
    create_fk_if_missing,
    create_index_if_missing,
)

# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotent: η στήλη μπορεί να υπάρχει ήδη από το παλιό
    # _sync_missing_nullable_columns που έτρεχε ΠΡΙΝ το upgrade και άφησε
    # τη βάση μισο-μεταναστευμένη — δες migration_helpers.py.
    add_column_if_missing(
        "aade_logs", sa.Column("workshop_id", sa.Integer(), nullable=True)
    )
    create_index_if_missing(
        "ix_aade_logs_workshop_id", "aade_logs", ["workshop_id"]
    )
    create_fk_if_missing(
        "fk_aade_logs_workshop_id", "aade_logs", "workshops",
        ["workshop_id"], ["id"],
    )

    # Backfill: ΜΟΝΟ οι γραμμές που συνδέονται με ένα dcl_entries (άρα
    # ξέρουμε σε ποιο workshop ανήκουν). Γραμμές με dcl_entry_id IS NULL
    # (ιστορικά system-level logs) μένουν workshop_id IS NULL — δεν
    # μπορούν να αναχθούν αναδρομικά.
    op.execute(
        """
        UPDATE aade_logs
        SET workshop_id = dcl_entries.workshop_id
        FROM dcl_entries
        WHERE aade_logs.dcl_entry_id = dcl_entries.id
        """
        if op.get_bind().dialect.name != "sqlite"
        else """
        UPDATE aade_logs
        SET workshop_id = (
            SELECT dcl_entries.workshop_id FROM dcl_entries
            WHERE dcl_entries.id = aade_logs.dcl_entry_id
        )
        WHERE EXISTS (
            SELECT 1 FROM dcl_entries WHERE dcl_entries.id = aade_logs.dcl_entry_id
        )
        """
    )


def downgrade() -> None:
    with op.batch_alter_table("aade_logs") as batch_op:
        batch_op.drop_constraint("fk_aade_logs_workshop_id", type_="foreignkey")
        batch_op.drop_index("ix_aade_logs_workshop_id")
        batch_op.drop_column("workshop_id")
