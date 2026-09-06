"""ai_call_log replaces api_usage + api_usage_resets (Phase 3.9 M5)

Revision ID: b6e557ca6088
Revises: 173367a2aab2
Create Date: 2026-09-06

Gemini's free tier has no per-call dollar cost, so USD spend tracking goes away entirely:
drop api_usage + api_usage_resets, add ai_call_log (one row per attempted Gemini call —
task / model / outcome / token counts / error). No real data is lost — Chunk 3.6 never made
a live call. See CLAUDE.md > Data Model > ai_call_log.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b6e557ca6088"
down_revision: Union[str, Sequence[str], None] = "173367a2aab2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("api_usage_resets")
    op.drop_table("api_usage")
    op.create_table(
        "ai_call_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("context_id", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("ai_call_log")
    op.create_table(
        "api_usage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd_cents", sa.Float(), nullable=False),
        sa.Column("call_type", sa.Text(), nullable=False),
        sa.Column("context_id", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "api_usage_resets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reset_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
