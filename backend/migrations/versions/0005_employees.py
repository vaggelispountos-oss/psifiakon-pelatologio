"""add employees table + audit trail columns

Πολλαπλά logins ανά συνεργείο (owner + υπάλληλοι), ίδια δεδομένα
(g.workshop_id filtering αμετάβλητο παντού) αλλά με δυνατότητα να ξέρουμε
ΠΟΙΟΣ έκανε ΤΙ — δες models.Employee, auth.require_owner.

Revision ID: 0005
Revises: 0004
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "employees",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "workshop_id",
            sa.Integer(),
            sa.ForeignKey("workshops.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "token_epoch", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_employees_workshop_id", "employees", ["workshop_id"], unique=False
    )

    with op.batch_alter_table("dcl_entries") as batch_op:
        batch_op.add_column(
            sa.Column("created_by_employee_id", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_dcl_entries_created_by_employee_id",
            "employees",
            ["created_by_employee_id"],
            ["id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("aade_logs") as batch_op:
        batch_op.add_column(
            sa.Column("actor_employee_id", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_aade_logs_actor_employee_id",
            "employees",
            ["actor_employee_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("aade_logs") as batch_op:
        batch_op.drop_constraint(
            "fk_aade_logs_actor_employee_id", type_="foreignkey"
        )
        batch_op.drop_column("actor_employee_id")

    with op.batch_alter_table("dcl_entries") as batch_op:
        batch_op.drop_constraint(
            "fk_dcl_entries_created_by_employee_id", type_="foreignkey"
        )
        batch_op.drop_column("created_by_employee_id")

    op.drop_index("ix_employees_workshop_id", table_name="employees")
    op.drop_table("employees")
