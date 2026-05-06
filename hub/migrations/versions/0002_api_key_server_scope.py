"""Allow API keys to target groups or single MCP servers.

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("api_keys") as batch_op:
        batch_op.alter_column("group_id", existing_type=sa.Integer(), nullable=True)
        batch_op.add_column(sa.Column("server_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_api_keys_mcp_servers",
            "mcp_servers",
            ["server_id"],
            ["id"],
        )
        batch_op.create_index("ix_api_keys_server_id", ["server_id"])


def downgrade() -> None:
    with op.batch_alter_table("api_keys") as batch_op:
        batch_op.drop_index("ix_api_keys_server_id")
        batch_op.drop_constraint("fk_api_keys_mcp_servers", type_="foreignkey")
        batch_op.drop_column("server_id")
        batch_op.alter_column("group_id", existing_type=sa.Integer(), nullable=False)
