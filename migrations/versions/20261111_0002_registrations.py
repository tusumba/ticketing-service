"""registrations: записи на мероприятия (#19051)."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "ticketing"

ENUMS = {
    "registration_status": ("going", "interested"),
    "registration_visibility": ("public", "friends_only", "anonymous"),
    "registration_source": ("free_signup", "ticket"),
}


def enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(*ENUMS[name], name=name, schema=SCHEMA, create_type=False)


def upgrade() -> None:
    for name in ENUMS:
        enum(name).create(op.get_bind(), checkfirst=True)
    op.create_table(
        "registrations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", enum("registration_status"), nullable=False),
        sa.Column("visibility", enum("registration_visibility"), nullable=False),
        sa.Column("source", enum("registration_source"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_registrations")),
        sa.UniqueConstraint("event_id", "user_id", name=op.f("uq_registrations_event_id_user_id")),
        schema=SCHEMA,
    )
    op.create_index(
        op.f("ix_registrations_user_id_created_at"),
        "registrations",
        ["user_id", "created_at"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_registrations_user_id_created_at"), table_name="registrations", schema=SCHEMA
    )
    op.drop_table("registrations", schema=SCHEMA)
    for name in reversed(ENUMS):
        enum(name).drop(op.get_bind(), checkfirst=True)
