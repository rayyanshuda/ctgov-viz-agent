"""create saved_charts

Revision ID: 0001
Revises: 
Create Date: 2026-10-30 00:25:34.636700

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the table that stores saved charts."""
    op.create_table('saved_charts',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('query', sa.String(length=500), nullable=False),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('viz_type', sa.String(length=50), nullable=False),
    sa.Column('total_matching', sa.Integer(), nullable=False),
    sa.Column('request', sa.JSON(), nullable=False),
    sa.Column('plan', sa.JSON(), nullable=False),
    sa.Column('response', sa.JSON(), nullable=False),
    sa.Column('refreshed_from_id', sa.String(length=32), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['refreshed_from_id'], ['saved_charts.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    """Undo upgrade(): remove the table."""
    op.drop_table('saved_charts')
