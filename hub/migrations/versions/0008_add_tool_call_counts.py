"""add tool call counters

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-21 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tool_call_counts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("server_name", sa.String(length=64), nullable=False),
        sa.Column("tool_name", sa.String(length=256), nullable=False),
        sa.Column("call_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_called_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "server_name",
            "tool_name",
            name="uq_tool_call_counts_server_tool",
        ),
    )
    op.create_index("ix_tool_call_counts_server_name", "tool_call_counts", ["server_name"])


def downgrade() -> None:
    op.drop_index("ix_tool_call_counts_server_name", table_name="tool_call_counts")
    op.drop_table("tool_call_counts")
