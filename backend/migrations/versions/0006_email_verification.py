"""add email verification (workshops.email_verified + email_verification_tokens)

Νέες εγγραφές (auth.register) ξεκινούν email_verified=False και παίρνουν
verification email — δες auth.py. Υπάρχοντα workshops θεωρούνται ήδη
έμπιστα (χρησιμοποιούν την εφαρμογή εδώ και καιρό), άρα η migration τα
γεμίζει με True ώστε να μην τους εμφανιστεί ξαφνικά ένα banner "επιβεβαίωσε
το email σου" για κάτι που δεν το ζήτησε κανείς όταν έκαναν εγγραφή.

Revision ID: 0006
Revises: 0005
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from migration_helpers import (
    add_column_if_missing,
    column_is_nullable,
    create_index_if_missing,
    table_exists,
)

# revision identifiers, used by Alembic.
revision: str = '0006'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotent — δες migration_helpers.py.
    add_column_if_missing(
        "workshops", sa.Column("email_verified", sa.Boolean(), nullable=True)
    )
    add_column_if_missing(
        "workshops", sa.Column("email_verified_at", sa.DateTime(), nullable=True)
    )
    # Ασφαλές να ξανατρέξει: πιάνει μόνο NULL. Οι ΥΠΑΡΧΟΝΤΕΣ πελάτες
    # θεωρούνται επιβεβαιωμένοι — αλλιώς θα κλειδώνονταν έξω αναδρομικά.
    op.execute("UPDATE workshops SET email_verified = true WHERE email_verified IS NULL")

    # Το σφίξιμο σε NOT NULL μόνο αν δεν έχει γίνει ήδη: σε Postgres το
    # SET NOT NULL είναι ιδεμπότεντ, αλλά σε SQLite το batch_alter_table
    # ΞΑΝΑΦΤΙΑΧΝΕΙ τον πίνακα — περιττό ρίσκο αν είναι ήδη σωστά.
    if column_is_nullable("workshops", "email_verified"):
        with op.batch_alter_table("workshops") as batch_op:
            batch_op.alter_column(
                "email_verified", existing_type=sa.Boolean(), nullable=False
            )

    if not table_exists("email_verification_tokens"):
        op.create_table(
            "email_verification_tokens",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "workshop_id",
                sa.Integer(),
                sa.ForeignKey("workshops.id"),
                nullable=False,
            ),
            sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("used_at", sa.DateTime(), nullable=True),
        )
    create_index_if_missing(
        "ix_email_verification_tokens_workshop_id",
        "email_verification_tokens",
        ["workshop_id"],
    )
    create_index_if_missing(
        "ix_email_verification_tokens_token_hash",
        "email_verification_tokens",
        ["token_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_email_verification_tokens_token_hash",
        table_name="email_verification_tokens",
    )
    op.drop_index(
        "ix_email_verification_tokens_workshop_id",
        table_name="email_verification_tokens",
    )
    op.drop_table("email_verification_tokens")

    with op.batch_alter_table("workshops") as batch_op:
        batch_op.drop_column("email_verified_at")
        batch_op.drop_column("email_verified")
