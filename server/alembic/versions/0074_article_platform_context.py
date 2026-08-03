"""Add article target platform and immutable generation context."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision: str = "0074_article_platform_context"
down_revision: str | None = "0073_collector_gateway_model"
branch_labels: str | None = None
depends_on: str | None = None


TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_unicode_ci",
}


def upgrade() -> None:
    op.add_column(
        "articles",
        sa.Column("target_platform_code", sa.String(length=50), nullable=True),
    )
    op.create_index(
        "ix_articles_target_platform_code",
        "articles",
        ["target_platform_code"],
        unique=False,
    )

    op.create_table(
        "article_generation_contexts",
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column(
            "schema_version",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
        sa.Column("entrypoint", sa.String(length=40), nullable=False),
        sa.Column("target_platform_code", sa.String(length=50), nullable=False),
        sa.Column("prompt_template_id", sa.Integer(), nullable=True),
        sa.Column(
            "prompt_template_name_snapshot",
            sa.String(length=200),
            nullable=False,
        ),
        sa.Column(
            "prompt_template_updated_at_snapshot",
            sa.DateTime(),
            nullable=True,
        ),
        sa.Column(
            "prompt_template_content_snapshot",
            mysql.LONGTEXT(),
            nullable=False,
        ),
        sa.Column("effective_prompt_snapshot", mysql.LONGTEXT(), nullable=False),
        sa.Column(
            "effective_prompt_sha256",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "platform_policy_version",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column("platform_policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("question_snapshot", sa.JSON(), nullable=True),
        sa.Column("model_label", sa.String(length=120), nullable=True),
        sa.Column("generation_params", sa.JSON(), nullable=True),
        sa.Column("evidence_refs", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["articles.id"],
            name="fk_article_generation_contexts_article_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("article_id"),
        **TABLE_OPTIONS,
    )
    op.create_index(
        "ix_article_generation_contexts_target_platform_code",
        "article_generation_contexts",
        ["target_platform_code"],
        unique=False,
    )
    op.create_index(
        "ix_article_generation_contexts_prompt_template_id",
        "article_generation_contexts",
        ["prompt_template_id"],
        unique=False,
    )
    op.create_index(
        "ix_article_generation_contexts_effective_prompt_sha256",
        "article_generation_contexts",
        ["effective_prompt_sha256"],
        unique=False,
    )
    op.create_index(
        "ix_article_generation_contexts_platform_policy_version",
        "article_generation_contexts",
        ["platform_policy_version"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_article_generation_contexts_platform_policy_version",
        table_name="article_generation_contexts",
    )
    op.drop_index(
        "ix_article_generation_contexts_effective_prompt_sha256",
        table_name="article_generation_contexts",
    )
    op.drop_index(
        "ix_article_generation_contexts_prompt_template_id",
        table_name="article_generation_contexts",
    )
    op.drop_index(
        "ix_article_generation_contexts_target_platform_code",
        table_name="article_generation_contexts",
    )
    op.drop_table("article_generation_contexts")

    op.drop_index("ix_articles_target_platform_code", table_name="articles")
    op.drop_column("articles", "target_platform_code")
