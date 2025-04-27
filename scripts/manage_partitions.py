# scripts/manage_partitions.py

import argparse
import datetime
import psycopg2
from dateutil.relativedelta import relativedelta

def create_partition(conn, year, month):
    """특정 연월에 대한 트랜잭션 파티션 생성"""
    
    # 파티션 시작일과 종료일 계산
    start_date = datetime.date(year, month, 1)
    if month == 12:
        end_date = datetime.date(year + 1, 1, 1)
    else:
        end_date = datetime.date(year, month + 1, 1)
    
    # 파티션 테이블 이름
    # 주의: 파티셔닝 마이그레이션 SQL에서 사용된 'transactions_partitioned_...' 이름과 일치해야 합니다.
    # 여기서는 마이그레이션 SQL과 일치시킨다고 가정합니다. 만약 SQLAlchemy 모델 정의에 파티셔닝을 추가했다면 그 이름 규칙을 따라야 합니다.
    partition_name = f"transactions_partitioned_y{year}m{month:02d}" 
    
    # 파티션 생성 SQL (IF NOT EXISTS 추가 권장)
    # 주의: 메인 테이블 이름이 'transactions'라고 가정합니다. 마이그레이션 후 바뀐 이름을 사용해야 합니다.
    sql = f"""
    CREATE TABLE IF NOT EXISTS {partition_name} PARTITION OF transactions
        FOR VALUES FROM ('{start_date}') TO ('{end_date}');
    """
    
    cursor = conn.cursor()
    try:
        cursor.execute(sql)
        conn.commit()
        print(f"Checked/Created partition {partition_name} for {start_date} to {end_date}")
    except Exception as e:
        conn.rollback()
        print(f"Error creating partition {partition_name}: {e}")
    finally:
        cursor.close()

def manage_partitions(conn, months_ahead=3, months_behind=12):
    """트랜잭션 파티션 관리
    
    Args:
        conn: 데이터베이스 연결
        months_ahead: 미래 몇 개월 파티션을 생성할지
        months_behind: 과거 몇 개월 파티션을 유지할지 (이 스크립트에서는 생성만 확인)
    """
    now = datetime.datetime.now()
    current_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    # 미래 파티션 생성 확인/생성
    for i in range(months_ahead + 1): 
        future_month = current_month + relativedelta(months=i)
        create_partition(conn, future_month.year, future_month.month)
    
    # 과거 파티션 생성 확인/생성 (데이터 마이그레이션 후 필요할 수 있음)
    for i in range(1, months_behind + 1):
        past_month = current_month - relativedelta(months=i)
        create_partition(conn, past_month.year, past_month.month)
    
    # 매우 오래된 파티션 아카이빙/삭제 로직은 여기에 추가 (선택적)
    # 예: drop_old_partition(conn, months_to_keep=24)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Manage transaction table partitions')
    parser.add_argument('--ahead', type=int, default=3,
                       help='Number of months ahead to create partitions for')
    parser.add_argument('--behind', type=int, default=12, 
                       help='Number of past months to ensure partitions exist for')
    parser.add_argument('--db-url', type=str, required=True,
                       help='Database connection URL (e.g., postgresql+psycopg2://user:password@host/dbname)')
    
    args = parser.parse_args()
    
    # 데이터베이스 연결
    conn = None
    try:
        conn = psycopg2.connect(args.db_url)
        manage_partitions(conn, args.ahead, args.behind)
    except Exception as e:
        print(f"Database connection error: {e}")
    finally:
        if conn:
            conn.close() 