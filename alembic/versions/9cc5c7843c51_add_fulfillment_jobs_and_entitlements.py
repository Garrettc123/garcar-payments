"""add_fulfillment_jobs_and_entitlements

Revision ID: 9cc5c7843c51
Revises:
Create Date: 2026-08-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '9cc5c7843c51'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "fulfillment_jobs",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("stripe_event_id", sa.String(255), unique=True, index=True, nullable=False),
        sa.Column("checkout_session_id", sa.String(255), index=True, nullable=True),
        sa.Column("plan", sa.String(100), nullable=True),
        sa.Column("customer_email", sa.String(320), nullable=True),
        sa.Column("status", sa.String(32), index=True, nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("email_sent", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.create_table(
        "download_entitlements",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("stripe_event_id", sa.String(255), index=True, nullable=False),
        sa.Column("customer_email", sa.String(320), index=True, nullable=False),
        sa.Column("plan", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("download_entitlements")
    op.drop_table("fulfillment_jobs")
