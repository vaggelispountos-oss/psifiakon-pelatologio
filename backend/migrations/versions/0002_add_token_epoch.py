"""add token_epoch to workshops

Χειροκίνητα προσαρμοσμένο από το autogenerate output: το autogenerate
παρήγαγε ένα απλό `ADD COLUMN ... NOT NULL` χωρίς default — αυτό σκάει σε
Postgres με ΥΠΑΡΧΟΥΣΕΣ γραμμές (δεν ξέρει τι τιμή να βάλει στις ήδη
αποθηκευμένες εγγραφές). Ασφαλές 3-βημάτων pattern για NOT NULL στήλη σε
πίνακα με δεδομένα: (1) πρόσθεσε nullable, (2) γέμισε τις υπάρχουσες
γραμμές, (3) μετά κάνε NOT NULL.

Το βήμα (3) χρησιμοποιεί `batch_alter_table`: το σκέτο `op.alter_column`
παράγει `ALTER TABLE ... ALTER COLUMN ... SET NOT NULL`, που είναι
Postgres-only syntax — η SQLite (dev/tests) δεν το υποστηρίζει καθόλου. Το
`batch_alter_table` το χειρίζεται διαφανώς και στα δύο dialects (στη
SQLite ξαναφτιάχνει τον πίνακα από κάτω, στην Postgres κάνει απλό ALTER).

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-07 21:53:53.614781

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('workshops', sa.Column('token_epoch', sa.Integer(), nullable=True))
    op.execute('UPDATE workshops SET token_epoch = 0 WHERE token_epoch IS NULL')
    with op.batch_alter_table('workshops') as batch_op:
        batch_op.alter_column('token_epoch', nullable=False)


def downgrade() -> None:
    with op.batch_alter_table('workshops') as batch_op:
        batch_op.drop_column('token_epoch')
