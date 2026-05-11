"""drop redundant matches standalone indexes

Revision ID: 941100c9d6c7
Revises: beee0bd92f29
Create Date: 2026-05-11 22:45:07.459689

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '941100c9d6c7'
down_revision: Union[str, Sequence[str], None] = 'beee0bd92f29'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_index("ix_matches_user_id", table_name="matches")
    op.drop_index("ix_matches_state", table_name="matches")


def downgrade() -> None:
    """Downgrade schema."""
    op.create_index("ix_matches_state", "matches", ["state"])
    op.create_index("ix_matches_user_id", "matches", ["user_id"])
