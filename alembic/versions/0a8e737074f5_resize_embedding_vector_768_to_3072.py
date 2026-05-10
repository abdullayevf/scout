"""resize embedding vector 768 to 3072

Revision ID: 0a8e737074f5
Revises: 27b2a086786d
Create Date: 2026-05-10 18:53:45.103603

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision: str = '0a8e737074f5'
down_revision: Union[str, Sequence[str], None] = '27b2a086786d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE listings ALTER COLUMN embedding TYPE vector(3072)")


def downgrade() -> None:
    op.execute("ALTER TABLE listings ALTER COLUMN embedding TYPE vector(768)")
