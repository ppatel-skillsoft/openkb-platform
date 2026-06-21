# Phase: 0
"""phase0 initial schema

Creates the three Phase 0 tables: knowledge_bases, documents, wiki_pages.
See specs/001-phase0-postgres-schema/data-model.md for full column specs.

Revision ID: 0001
Revises:
Create Date: 2026-06-21
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- knowledge_bases ---------------------------------------------------
    # Created first; documents and wiki_pages have FK references to it.
    op.create_table(
        "knowledge_bases",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("slug", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("storage_container_path", sa.Text, nullable=True),
        sa.Column(
            "git_versioning_enabled",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
        sa.Column("compilation_config", postgresql.JSONB, nullable=True),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        # Unique slug constraint (FR-004)
        sa.UniqueConstraint("slug", name="uq_knowledge_bases_slug"),
    )

    # --- documents ---------------------------------------------------------
    op.create_table(
        "documents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "kb_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_bases.id"),
            nullable=False,
        ),
        sa.Column("source_type", sa.Text, nullable=False),
        sa.Column("source_uri", sa.Text, nullable=True),
        sa.Column("original_filename", sa.Text, nullable=True),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("failure_reason", sa.Text, nullable=True),
        sa.Column("pageindex_used", sa.Boolean, nullable=True),
        sa.Column("token_cost", sa.Integer, nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    # Index on FK column for efficient KB-scoped lookups (FR-006)
    op.create_index("ix_documents_kb_id", "documents", ["kb_id"])

    # --- wiki_pages --------------------------------------------------------
    op.create_table(
        "wiki_pages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "kb_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_bases.id"),
            nullable=False,
        ),
        sa.Column("page_type", sa.Text, nullable=False),
        sa.Column("slug", sa.Text, nullable=False),
        sa.Column("blob_path", sa.Text, nullable=True),
        sa.Column("entity_type", sa.Text, nullable=True),
        sa.Column("last_compiled_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        # Composite unique: slug is unique per KB (FR-005)
        sa.UniqueConstraint("kb_id", "slug", name="uq_wiki_pages_kb_id_slug"),
    )
    # Index on FK column (FR-006)
    op.create_index("ix_wiki_pages_kb_id", "wiki_pages", ["kb_id"])


def downgrade() -> None:
    op.drop_index("ix_wiki_pages_kb_id", table_name="wiki_pages")
    op.drop_table("wiki_pages")
    op.drop_index("ix_documents_kb_id", table_name="documents")
    op.drop_table("documents")
    op.drop_table("knowledge_bases")
