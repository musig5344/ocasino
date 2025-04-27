""add transaction indexes

Revision ID: xxxx # 실제 리비전 ID로 교체 필요
Revises: previous_revision # 이전 리비전 ID로 교체 필요
Create Date: 2025-04-22 12:00:00.000000 # 실제 생성 날짜로 교체

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = 'xxxx' # 실제 리비전 ID로 교체 필요
down_revision = 'previous_revision' # 이전 리비전 ID로 교체 필요
branch_labels = None
depends_on = None

def upgrade():
    # 트랜잭션 조회를 위한 복합 인덱스 추가
    op.create_index(
        'ix_transactions_player_partner_date',
        'transactions',
        [
            'player_id',
            'partner_id',
            sa.text("date_trunc('day', created_at)")
        ],
        unique=False
    )
    
    # 트랜잭션 타입별 분석을 위한 인덱스
    op.create_index(
        'ix_transactions_type_date',
        'transactions',
        [
            'transaction_type',
            sa.text("date_trunc('day', created_at)")
        ],
        unique=False
    )
    
    # 상태별 트랜잭션 조회를 위한 인덱스
    op.create_index(
        'ix_transactions_status_date',
        'transactions',
        ['status', 'created_at'],
        unique=False
    )
    
    # 참조 트랜잭션 인덱스 (롤백/취소용)
    op.create_index(
        'ix_transactions_ref_transaction',
        'transactions',
        ['reference_transaction_id'],
        unique=False
    )

def downgrade():
    # 인덱스 제거
    op.drop_index('ix_transactions_player_partner_date', table_name='transactions')
    op.drop_index('ix_transactions_type_date', table_name='transactions')
    op.drop_index('ix_transactions_status_date', table_name='transactions')
    op.drop_index('ix_transactions_ref_transaction', table_name='transactions')
