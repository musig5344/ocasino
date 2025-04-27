from sqlalchemy import DateTime
from sqlalchemy.sql.expression import FunctionElement
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.types import DateTime as DateTimeType # 명확한 타입 임포트
import sqlalchemy as sa

class date_trunc(FunctionElement):
    """
    Represents the date_trunc function.
    SQLAlchemy doesn't automatically compile this for SQLite indexes,
    so we provide a custom compilation rule.
    """
    type = DateTimeType() # 반환 타입 지정
    name = 'date_trunc'
    # __init__에서 인자 개수 등을 강제할 수도 있음
    # def __init__(self, precision, column, **kwargs):
    #     super(date_trunc, self).__init__(precision, column, **kwargs)


@compiles(date_trunc, 'sqlite')
def compile_date_trunc_sqlite(element, compiler, **kw):
    """
    Compile date_trunc for SQLite.
    Uses strftime to truncate to the beginning of the day.
    Example: date_trunc('day', my_column) -> strftime('%Y-%m-%d 00:00:00', my_column)
    """
    # element.clauses에는 func() 호출 시 전달된 인자들이 포함됩니다.
    # 첫 번째 인자(precision)는 보통 문자열 리터럴, 두 번째 인자는 컬럼 표현식입니다.
    # 여기서는 'day' precision만 가정하고 간단히 구현합니다.
    if len(element.clauses.clauses) != 2:
        raise ValueError("date_trunc function expects 2 arguments (precision, column)")
        
    # 두 번째 인자인 컬럼 표현식을 컴파일합니다.
    column_expr = compiler.process(element.clauses.clauses[1], **kw)
    
    # precision 값 확인 (옵션)
    # precision_arg = element.clauses.clauses[0]
    # if isinstance(precision_arg, sqlalchemy.sql.elements.literal_column) and precision_arg.value.lower() == 'day':
    #    pass # 'day' precision 확인
    # else:
    #    raise NotImplementedError("Only 'day' precision is supported for SQLite date_trunc")

    # strftime을 사용하여 날짜 시작으로 변환 (SQLite는 결과로 문자열 반환)
    return f"strftime('%Y-%m-%d 00:00:00', {column_expr})"

# 참고: 다른 데이터베이스 (예: PostgreSQL)를 위한 컴파일 규칙은 기본 SQLAlchemy 핸들러가 처리합니다.
# 특정 데이터베이스에 대한 기본 동작을 오버라이드 하려면 @compiles(date_trunc, 'postgresql') 등을 추가할 수 있습니다.

# asyncpg 드라이버를 위한 컴파일러 추가
@compiles(date_trunc, 'postgresql')
@compiles(date_trunc, 'postgresql+asyncpg') # postgresql 기본 및 asyncpg 명시적 지정
def compile_date_trunc_postgresql(element, compiler, **kw):
    """PostgreSQL용 date_trunc 컴파일 (asyncpg 포함)"""
    if len(element.clauses.clauses) != 2:
        raise ValueError("date_trunc function expects 2 arguments (precision, column)")
    
    # PostgreSQL은 첫 번째 인자가 문자열 리터럴이어야 함
    precision_element = element.clauses.clauses[0]
    if not isinstance(precision_element, sa.sql.elements.BindParameter) and \
       not isinstance(precision_element, sa.sql.elements.literal_column):
         # 안전하게 문자열 값 추출 시도 (BindParameter의 경우 value 속성 사용)
        try:
            precision_val = str(sa.sql.elements.literal(precision_element).value)
        except Exception:
             # 실패 시 기본 컴파일러 처리 유도 (또는 에러 발생)
            return compiler.visit_function(element, **kw)
    else:
        precision_val = str(precision_element.value)
        
    # 컬럼 표현식 컴파일
    column_expr = compiler.process(element.clauses.clauses[1], **kw)
    
    # PostgreSQL date_trunc 함수 형식 사용
    return f"date_trunc('{precision_val}', {column_expr})" 