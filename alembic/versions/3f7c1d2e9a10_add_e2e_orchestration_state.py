"""add durable checkout orchestration state

Revision ID: 3f7c1d2e9a10
Revises: 9cc5c7843c51
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "3f7c1d2e9a10"
down_revision: Union[str, None] = "9cc5c7843c51"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("fulfillment_jobs", sa.Column("stripe_customer_id", sa.String(255), nullable=True))
    op.add_column("fulfillment_jobs", sa.Column("failed_stage", sa.String(64), nullable=True))
    op.add_column("fulfillment_jobs", sa.Column("hubspot_contact_id", sa.String(255), nullable=True))
    op.add_column("fulfillment_jobs", sa.Column("supabase_entitlement_id", sa.String(255), nullable=True))
    op.add_column("fulfillment_jobs", sa.Column("asana_project_id", sa.String(255), nullable=True))
    op.add_column("fulfillment_jobs", sa.Column("asana_task_id", sa.String(255), nullable=True))
    op.add_column("fulfillment_jobs", sa.Column("notion_event_id", sa.String(255), nullable=True))
    op.add_column("fulfillment_jobs", sa.Column("linear_issue_id", sa.String(255), nullable=True))
    op.create_index("ix_fulfillment_jobs_stripe_customer_id", "fulfillment_jobs", ["stripe_customer_id"])
    op.create_unique_constraint("uq_fulfillment_checkout_session", "fulfillment_jobs", ["checkout_session_id"])

    op.create_table(
        "integration_actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("job_id", "stage", name="uq_integration_action_job_stage"),
    )
    op.create_index("ix_integration_actions_job_id", "integration_actions", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_integration_actions_job_id", table_name="integration_actions")
    op.drop_table("integration_actions")
    op.drop_constraint("uq_fulfillment_checkout_session", "fulfillment_jobs", type_="unique")
    op.drop_index("ix_fulfillment_jobs_stripe_customer_id", table_name="fulfillment_jobs")
    for column in ["linear_issue_id", "notion_event_id", "asana_task_id", "supabase_entitlement_id", "hubspot_contact_id", "failed_stage", "stripe_customer_id"]:
        op.drop_column("fulfillment_jobs", column)
