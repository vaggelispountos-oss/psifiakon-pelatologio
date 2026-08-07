"""composite indexes for entries and metrics

Γραμμένο με το χέρι (όχι autogenerate): προσθέτει ΜΟΝΟ indexes, καμία
αλλαγή σε στήλες/δεδομένα — άρα είναι από τα λίγα migrations που είναι
ασφαλή να γραφτούν απευθείας, και το autogenerate δεν προσθέτει τίποτα.

Γιατί: το /api/dcl/entries κάνει filter_by(workshop_id) + order_by(
created_at desc) + count() σε κάθε φόρτωση της λίστας. Με index ΜΟΝΟ στο
workshop_id (ό,τι υπήρχε), η βάση διαβάζει ΟΛΕΣ τις εγγραφές του
συνεργείου και τις ταξινομεί στη μνήμη κάθε φορά. Το ocr_metrics έχει το
ίδιο μοτίβο και μεγαλώνει ακόμη πιο γρήγορα (μία γραμμή ανά σάρωση).

Revision ID: 0003
Revises: 0002
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_entries_workshop_created", "dcl_entries", ["workshop_id", "created_at"]
    )
    op.create_index(
        "ix_metrics_workshop_created", "ocr_metrics", ["workshop_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_metrics_workshop_created", table_name="ocr_metrics")
    op.drop_index("ix_entries_workshop_created", table_name="dcl_entries")
