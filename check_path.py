import sys
print("\n".join(sys.path))

try:
    import backend
    print("backend 모듈을 임포트할 수 있습니다!")
    print(f"backend 모듈 위치: {backend.__file__}")
except ImportError as e:
    print(f"backend 모듈을 임포트할 수 없습니다: {e}") 