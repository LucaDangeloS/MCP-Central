"""add server language runtime metadata

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-20 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_servers",
        sa.Column("language", sa.String(length=32), nullable=False, server_default="python"),
    )
    op.add_column(
        "mcp_servers",
        sa.Column("launch_command", sa.String(length=64), nullable=False, server_default=""),
    )
    op.add_column(
        "mcp_servers",
        sa.Column("launch_args", sa.Text(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("mcp_servers", "launch_args")
    op.drop_column("mcp_servers", "launch_command")
    op.drop_column("mcp_servers", "language")
