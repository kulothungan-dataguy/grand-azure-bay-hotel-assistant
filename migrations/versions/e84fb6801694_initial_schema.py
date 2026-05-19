"""initial_schema

Revision ID: e84fb6801694
Revises: 
Create Date: 2026-05-19 20:15:07.849766

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e84fb6801694'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reservations",
        sa.Column("reservation_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("guest_name", sa.Text, nullable=False),
        sa.Column("email", sa.Text, nullable=False),
        sa.Column("room_type", sa.Text, nullable=False),
        sa.Column("check_in_date", sa.Text, nullable=False),
        sa.Column("check_out_date", sa.Text, nullable=False),
        sa.Column("status", sa.Text, server_default="CONFIRMED"),
        sa.Column("created_at", sa.TIMESTAMP, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "escalations",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("conversation_id", sa.Text, nullable=False),
        sa.Column("guest_email", sa.Text),
        sa.Column("query", sa.Text, nullable=False),
        sa.Column("status", sa.Text, server_default="PENDING"),
        sa.Column("created_at", sa.TIMESTAMP, server_default=sa.text("CURRENT_TIMESTAMP")),
    )


def downgrade() -> None:
    op.drop_table("escalations")
    op.drop_table("reservations")
