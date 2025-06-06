"""Create initial database schema

Revision ID: cbfdeb980813
Revises: 
Create Date: 2025-04-26 20:48:06.420219

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# 필요한 모듈 임포트 추가
import backend.db.types
import backend.models.domain
# import sqlalchemy_utils # 만약 sqlalchemy_utils의 타입을 사용한다면 <- 주석 처리 또는 삭제


# revision identifiers, used by Alembic.
revision: str = 'cbfdeb980813'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 모든 ENUM 타입을 먼저 삭제 (CASCADE 옵션 사용)
    op.execute("DROP TYPE IF EXISTS gamestatus CASCADE")
    op.execute("DROP TYPE IF EXISTS partnertype CASCADE")
    op.execute("DROP TYPE IF EXISTS partnerstatus CASCADE")
    op.execute("DROP TYPE IF EXISTS commissionmodel CASCADE")
    op.execute("DROP TYPE IF EXISTS gamecategory CASCADE")
    op.execute("DROP TYPE IF EXISTS transactiontype CASCADE")
    op.execute("DROP TYPE IF EXISTS transactionstatus CASCADE")
    op.execute("DROP TYPE IF EXISTS auditlogtype CASCADE")
    op.execute("DROP TYPE IF EXISTS auditloglevel CASCADE")

    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('game_providers',
    sa.Column('id', backend.db.types.GUID(), nullable=False),
    sa.Column('code', sa.String(length=50), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('status', sa.Enum('ACTIVE', 'INACTIVE', 'MAINTENANCE', 'DISCONTINUED', name='gamestatus'), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('integration_type', sa.String(length=50), nullable=True),
    sa.Column('api_endpoint', sa.String(length=255), nullable=True),
    sa.Column('api_key', sa.String(length=255), nullable=True),
    sa.Column('api_secret', sa.String(length=255), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('logo_url', sa.String(length=255), nullable=True),
    sa.Column('website', sa.String(length=255), nullable=True),
    sa.Column('supported_currencies', backend.db.types.JSONType(), nullable=True),
    sa.Column('supported_languages', backend.db.types.JSONType(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_game_providers_code'), 'game_providers', ['code'], unique=True)
    op.create_table('partners',
    sa.Column('id', backend.db.types.GUID(), nullable=False),
    sa.Column('code', sa.String(), nullable=True),
    sa.Column('name', sa.String(), nullable=True),
    sa.Column('partner_type', sa.Enum('OPERATOR', 'AGGREGATOR', 'AFFILIATE', 'CASINO_OPERATOR', 'PAYMENT_PROVIDER', name='partnertype'), nullable=True),
    sa.Column('status', sa.Enum('PENDING', 'ACTIVE', 'INACTIVE', 'SUSPENDED', 'TERMINATED', name='partnerstatus'), nullable=True),
    sa.Column('commission_model', sa.Enum('REVENUE_SHARE', 'CPA', 'HYBRID', name='commissionmodel'), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_partners_code'), 'partners', ['code'], unique=True)
    op.create_index(op.f('ix_partners_name'), 'partners', ['name'], unique=False)
    op.create_table('api_keys',
    sa.Column('id', backend.db.types.GUID(), nullable=False),
    sa.Column('partner_id', backend.db.types.GUID(), nullable=False),
    sa.Column('key', sa.String(length=100), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('permissions', sa.JSON(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=True),
    sa.Column('created_by', sa.String(length=100), nullable=True),
    sa.Column('last_used_at', sa.DateTime(), nullable=True),
    sa.Column('last_used_ip', sa.String(length=50), nullable=True),
    sa.Column('expires_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['partner_id'], ['partners.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_api_keys_key'), 'api_keys', ['key'], unique=True)
    op.create_table('balances',
    sa.Column('id', backend.db.types.UUIDType(), nullable=False),
    sa.Column('partner_id', backend.db.types.UUIDType(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('total_balance', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('available_balance', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('pending_withdrawals', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('last_updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['partner_id'], ['partners.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_balance_partner_currency', 'balances', ['partner_id', 'currency'], unique=True)
    op.create_table('games',
    sa.Column('id', backend.db.types.GUID(), nullable=False),
    sa.Column('provider_id', backend.db.types.GUID(), nullable=False),
    sa.Column('game_code', sa.String(length=100), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('category', sa.Enum('SLOTS', 'TABLE_GAMES', 'LIVE_CASINO', 'POKER', 'BINGO', 'LOTTERY', 'SPORTS', 'ARCADE', name='gamecategory'), nullable=False),
    sa.Column('status', sa.Enum('ACTIVE', 'INACTIVE', 'MAINTENANCE', 'DISCONTINUED', name='gamestatus'), nullable=False),
    sa.Column('rtp', sa.Numeric(precision=5, scale=2), nullable=True),
    sa.Column('min_bet', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('max_bet', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('features', backend.db.types.JSONType(), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('thumbnail_url', sa.String(length=255), nullable=True),
    sa.Column('banner_url', sa.String(length=255), nullable=True),
    sa.Column('demo_url', sa.String(length=255), nullable=True),
    sa.Column('supported_currencies', backend.db.types.JSONType(), nullable=True),
    sa.Column('supported_languages', backend.db.types.JSONType(), nullable=True),
    sa.Column('platform_compatibility', backend.db.types.JSONType(), nullable=True),
    sa.Column('launch_date', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['provider_id'], ['game_providers.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_game_provider_code', 'games', ['provider_id', 'game_code'], unique=True)
    op.create_index(op.f('ix_games_game_code'), 'games', ['game_code'], unique=False)
    op.create_index(op.f('ix_games_provider_id'), 'games', ['provider_id'], unique=False)
    op.create_table('ip_whitelist',
    sa.Column('id', backend.db.types.GUID(), nullable=False),
    sa.Column('ip_address', backend.db.types.IPAddress(length=45), nullable=False),
    sa.Column('partner_id', backend.db.types.GUID(), nullable=False),
    sa.Column('description', sa.String(length=255), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['partner_id'], ['partners.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ip_whitelist_ip_address'), 'ip_whitelist', ['ip_address'], unique=False)
    op.create_index(op.f('ix_ip_whitelist_partner_id'), 'ip_whitelist', ['partner_id'], unique=False)
    op.create_table('wallets',
    sa.Column('id', backend.db.types.GUID(), nullable=False),
    sa.Column('player_id', backend.db.types.GUID(), nullable=False),
    sa.Column('partner_id', backend.db.types.GUID(), nullable=False),
    sa.Column('balance', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=True),
    sa.Column('is_locked', sa.Boolean(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['partner_id'], ['partners.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_wallet_player_partner', 'wallets', ['player_id', 'partner_id'], unique=True)
    op.create_index(op.f('ix_wallets_partner_id'), 'wallets', ['partner_id'], unique=False)
    op.create_index(op.f('ix_wallets_player_id'), 'wallets', ['player_id'], unique=False)
    op.create_table('audit_logs',
    sa.Column('id', backend.db.types.GUID(), nullable=False),
    sa.Column('timestamp', sa.DateTime(), nullable=False),
    sa.Column('log_type', sa.Enum('LOGIN', 'LOGOUT', 'API_ACCESS', 'API_REQUEST', 'RESOURCE_CREATE', 'RESOURCE_READ', 'RESOURCE_UPDATE', 'RESOURCE_DELETE', 'SYSTEM', 'SECURITY', 'TRANSACTION', name='auditlogtype'), nullable=False),
    sa.Column('level', sa.Enum('INFO', 'NOTICE', 'WARNING', 'ALERT', 'CRITICAL', name='auditloglevel'), nullable=False),
    sa.Column('action', sa.String(length=100), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('resource_type', sa.String(length=50), nullable=True),
    sa.Column('resource_id', sa.String(length=100), nullable=True),
    sa.Column('user_id', sa.String(length=100), nullable=True),
    sa.Column('username', sa.String(length=100), nullable=True),
    sa.Column('partner_id', backend.db.types.GUID(), nullable=True),
    sa.Column('api_key_id', backend.db.types.GUID(), nullable=True),
    sa.Column('ip_address', sa.String(length=50), nullable=True),
    sa.Column('user_agent', sa.String(length=255), nullable=True),
    sa.Column('request_id', sa.String(length=50), nullable=True),
    sa.Column('request_path', sa.String(length=255), nullable=True),
    sa.Column('request_method', sa.String(length=10), nullable=True),
    sa.Column('status_code', sa.String(length=10), nullable=True),
    sa.Column('response_time_ms', sa.Integer(), nullable=True),
    sa.Column('log_metadata', sa.JSON(), nullable=True),
    sa.ForeignKeyConstraint(['api_key_id'], ['api_keys.id'], ),
    sa.ForeignKeyConstraint(['partner_id'], ['partners.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_audit_logs_api_key_id'), 'audit_logs', ['api_key_id'], unique=False)
    op.create_index(op.f('ix_audit_logs_log_type'), 'audit_logs', ['log_type'], unique=False)
    op.create_index('ix_audit_logs_partner_date', 'audit_logs', ['partner_id', sa.literal_column("date_trunc('day', timestamp)")], unique=False)
    op.create_index(op.f('ix_audit_logs_partner_id'), 'audit_logs', ['partner_id'], unique=False)
    op.create_index(op.f('ix_audit_logs_request_id'), 'audit_logs', ['request_id'], unique=False)
    op.create_index(op.f('ix_audit_logs_resource_id'), 'audit_logs', ['resource_id'], unique=False)
    op.create_index(op.f('ix_audit_logs_resource_type'), 'audit_logs', ['resource_type'], unique=False)
    op.create_index(op.f('ix_audit_logs_timestamp'), 'audit_logs', ['timestamp'], unique=False)
    op.create_index(op.f('ix_audit_logs_user_id'), 'audit_logs', ['user_id'], unique=False)
    op.create_table('game_sessions',
    sa.Column('id', backend.db.types.GUID(), nullable=False),
    sa.Column('player_id', backend.db.types.GUID(), nullable=False),
    sa.Column('partner_id', backend.db.types.GUID(), nullable=False),
    sa.Column('game_id', backend.db.types.GUID(), nullable=False),
    sa.Column('token', sa.String(length=100), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=True),
    sa.Column('start_time', sa.DateTime(), nullable=True),
    sa.Column('end_time', sa.DateTime(), nullable=True),
    sa.Column('player_ip', sa.String(length=50), nullable=True),
    sa.Column('device_info', backend.db.types.JSONType(), nullable=True),
    sa.Column('session_data', backend.db.types.JSONType(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['game_id'], ['games.id'], ),
    sa.ForeignKeyConstraint(['partner_id'], ['partners.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_active_player_game_session', 'game_sessions', ['player_id', 'game_id', 'status'], unique=True, postgresql_where=sa.text("status = 'active'"))
    op.create_index(op.f('ix_game_sessions_game_id'), 'game_sessions', ['game_id'], unique=False)
    op.create_index(op.f('ix_game_sessions_partner_id'), 'game_sessions', ['partner_id'], unique=False)
    op.create_index(op.f('ix_game_sessions_player_id'), 'game_sessions', ['player_id'], unique=False)
    op.create_index(op.f('ix_game_sessions_token'), 'game_sessions', ['token'], unique=True)
    op.create_table('transactions',
    sa.Column('id', backend.db.types.GUID(), nullable=False),
    sa.Column('reference_id', sa.String(length=100), nullable=False),
    sa.Column('wallet_id', backend.db.types.GUID(), nullable=False),
    sa.Column('player_id', backend.db.types.GUID(), nullable=False),
    sa.Column('partner_id', backend.db.types.GUID(), nullable=False),
    sa.Column('transaction_type', sa.Enum('DEPOSIT', 'WITHDRAWAL', 'BET', 'WIN', 'REFUND', 'ADJUSTMENT', 'COMMISSION', 'BONUS', 'ROLLBACK', name='transactiontype'), nullable=False),
    sa.Column('amount', sa.Text(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('status', sa.Enum('PENDING', 'COMPLETED', 'FAILED', 'CANCELED', name='transactionstatus'), nullable=False),
    sa.Column('original_balance', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('updated_balance', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('game_id', backend.db.types.GUID(), nullable=True),
    sa.Column('game_session_id', backend.db.types.GUID(), nullable=True),
    sa.Column('original_transaction_id', backend.db.types.GUID(), nullable=True),
    sa.Column('metadata', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['game_id'], ['games.id'], ),
    sa.ForeignKeyConstraint(['game_session_id'], ['game_sessions.id'], ),
    sa.ForeignKeyConstraint(['original_transaction_id'], ['transactions.id'], ),
    sa.ForeignKeyConstraint(['partner_id'], ['partners.id'], ),
    sa.ForeignKeyConstraint(['wallet_id'], ['wallets.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_transactions_player_id'), 'transactions', ['player_id'], unique=False)
    op.create_index('ix_transactions_reference_id', 'transactions', ['reference_id'], unique=False)
    op.create_index('ix_transactions_wallet_id', 'transactions', ['wallet_id'], unique=False)
    op.create_index('uq_transaction_partner_reference', 'transactions', ['partner_id', 'reference_id'], unique=True)
    op.create_table('game_transactions',
    sa.Column('id', backend.db.types.UUIDType(), nullable=False),
    sa.Column('session_id', backend.db.types.UUIDType(), nullable=False),
    sa.Column('transaction_id', backend.db.types.UUIDType(), nullable=True),
    sa.Column('reference_id', sa.String(length=100), nullable=False),
    sa.Column('round_id', sa.String(length=100), nullable=True),
    sa.Column('action', sa.String(length=20), nullable=False),
    sa.Column('amount', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('game_data', backend.db.types.JSONType(), nullable=True),
    sa.Column('provider_transaction_id', sa.String(length=100), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['session_id'], ['game_sessions.id'], ),
    sa.ForeignKeyConstraint(['transaction_id'], ['transactions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_game_transactions_reference_id'), 'game_transactions', ['reference_id'], unique=True)
    op.create_index(op.f('ix_game_transactions_round_id'), 'game_transactions', ['round_id'], unique=False)
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f('ix_game_transactions_round_id'), table_name='game_transactions')
    op.drop_index(op.f('ix_game_transactions_reference_id'), table_name='game_transactions')
    op.drop_table('game_transactions')
    op.drop_index('uq_transaction_partner_reference', table_name='transactions')
    op.drop_index('ix_transactions_wallet_id', table_name='transactions')
    op.drop_index('ix_transactions_reference_id', table_name='transactions')
    op.drop_index(op.f('ix_transactions_player_id'), table_name='transactions')
    op.drop_table('transactions')
    op.drop_index(op.f('ix_game_sessions_token'), table_name='game_sessions')
    op.drop_index(op.f('ix_game_sessions_player_id'), table_name='game_sessions')
    op.drop_index(op.f('ix_game_sessions_partner_id'), table_name='game_sessions')
    op.drop_index(op.f('ix_game_sessions_game_id'), table_name='game_sessions')
    op.drop_index('ix_active_player_game_session', table_name='game_sessions', postgresql_where=sa.text("status = 'active'"))
    op.drop_table('game_sessions')
    op.drop_index(op.f('ix_audit_logs_user_id'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_timestamp'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_resource_type'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_resource_id'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_request_id'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_partner_id'), table_name='audit_logs')
    op.drop_index('ix_audit_logs_partner_date', table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_log_type'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_api_key_id'), table_name='audit_logs')
    op.drop_table('audit_logs')
    op.drop_index(op.f('ix_wallets_player_id'), table_name='wallets')
    op.drop_index(op.f('ix_wallets_partner_id'), table_name='wallets')
    op.drop_index('ix_wallet_player_partner', table_name='wallets')
    op.drop_table('wallets')
    op.drop_index(op.f('ix_ip_whitelist_partner_id'), table_name='ip_whitelist')
    op.drop_index(op.f('ix_ip_whitelist_ip_address'), table_name='ip_whitelist')
    op.drop_table('ip_whitelist')
    op.drop_index(op.f('ix_games_provider_id'), table_name='games')
    op.drop_index(op.f('ix_games_game_code'), table_name='games')
    op.drop_index('ix_game_provider_code', table_name='games')
    op.drop_table('games')
    op.drop_index('ix_balance_partner_currency', table_name='balances')
    op.drop_table('balances')
    op.drop_index(op.f('ix_api_keys_key'), table_name='api_keys')
    op.drop_table('api_keys')
    op.drop_index(op.f('ix_partners_name'), table_name='partners')
    op.drop_index(op.f('ix_partners_code'), table_name='partners')
    op.drop_table('partners')
    op.drop_index(op.f('ix_game_providers_code'), table_name='game_providers')
    op.drop_table('game_providers')
    # ### end Alembic commands ###
