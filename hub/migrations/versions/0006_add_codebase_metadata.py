"""add codebase and manifest tool metadata

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-16 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_servers",
        sa.Column("manifest_tools", sa.Text(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "mcp_servers",
        sa.Column("source_type", sa.String(length=32), nullable=False, server_default="package"),
    )
    op.add_column(
        "mcp_servers",
        sa.Column("install_on_start", sa.Boolean(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("mcp_servers", "install_on_start")
    op.drop_column("mcp_servers", "source_type")
    op.drop_column("mcp_servers", "manifest_tools")
