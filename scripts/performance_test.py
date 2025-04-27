# scripts/performance_test.py

import asyncio
import aiohttp
import time
import uuid
import argparse
import json
from statistics import mean, median, stdev
from dataclasses import dataclass, field # field 추가
from typing import List, Dict, Any, Optional

@dataclass
class RequestResult:
    """요청 결과 데이터 클래스"""
    id: int
    status_code: int
    response_time: float
    error: Optional[str] = None
    response_data: Optional[Dict[str, Any]] = None

async def make_request(session: aiohttp.ClientSession, req_id: int, url: str, method: str, 
                       data: Optional[Dict[str, Any]] = None, 
                       headers: Optional[Dict[str, str]] = None) -> RequestResult:
    """단일 API 요청 수행"""
    start_time = time.time()
    
    try:
        if method.upper() == "GET":
            async with session.get(url, headers=headers) as response:
                status_code = response.status
                response_text = await response.text() # 텍스트 먼저 읽기
                response_data = None
                if response.content_type == 'application/json':
                    try:
                        response_data = json.loads(response_text)
                    except json.JSONDecodeError:
                        # JSON 파싱 실패 시 텍스트 데이터 사용
                        response_data = {"raw_response": response_text}
                else:
                    response_data = {"raw_response": response_text}
                
                response_time = time.time() - start_time
                return RequestResult(
                    id=req_id,
                    status_code=status_code,
                    response_time=response_time,
                    response_data=response_data
                )
        elif method.upper() == "POST": 
            async with session.post(url, json=data, headers=headers) as response:
                status_code = response.status
                response_text = await response.text()
                response_data = None
                if response.content_type == 'application/json':
                    try:
                        response_data = json.loads(response_text)
                    except json.JSONDecodeError:
                        response_data = {"raw_response": response_text}
                else:
                     response_data = {"raw_response": response_text}
                
                response_time = time.time() - start_time
                return RequestResult(
                    id=req_id,
                    status_code=status_code,
                    response_time=response_time,
                    response_data=response_data
                )
        else:
             raise ValueError(f"Unsupported HTTP method: {method}")
             
    except aiohttp.ClientError as e:
        response_time = time.time() - start_time
        return RequestResult(
            id=req_id,
            status_code=-1, # 클라이언트 오류 표시
            response_time=response_time,
            error=f"ClientError: {e}"
        )
    except Exception as e:
        response_time = time.time() - start_time
        return RequestResult(
            id=req_id,
            status_code=-2, # 일반 오류 표시
            response_time=response_time,
            error=f"UnexpectedError: {e}"
        )

async def run_test(endpoint_func, api_url: str, api_key: str, player_id: str, 
                 concurrent_requests: int) -> List[RequestResult]:
    """지정된 엔드포인트 테스트 실행"""
    url = f"{api_url}/api" # API 기본 경로 포함
    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
    
    async with aiohttp.ClientSession() as session:
        tasks = []
        for i in range(concurrent_requests):
            tasks.append(endpoint_func(session, i, url, headers, player_id))
        
        results = await asyncio.gather(*tasks)
    
    return results

# --- 엔드포인트별 테스트 함수 --- 

async def test_bet_request(session: aiohttp.ClientSession, req_id: int, base_url: str, 
                         headers: Dict[str, str], player_id: str) -> RequestResult:
    """베팅 요청 생성 및 전송"""
    url = f"{base_url}/wallet/{player_id}/bet"
    reference_id = f"perf-bet-{uuid.uuid4()}"
    data = {
        "reference_id": reference_id,
        "amount": 1.00, 
        "currency": "USD"
        # "game_id": "...", # 필요 시 게임 ID 추가
    }
    return await make_request(session, req_id, url, "POST", data, headers)

async def test_balance_request(session: aiohttp.ClientSession, req_id: int, base_url: str, 
                           headers: Dict[str, str], player_id: str) -> RequestResult:
    """잔액 조회 요청 생성 및 전송"""
    url = f"{base_url}/wallet/{player_id}/balance"
    # GET 요청이므로 헤더에서 Content-Type 제거 가능
    get_headers = {k: v for k, v in headers.items() if k.lower() != 'content-type'}
    return await make_request(session, req_id, url, "GET", None, get_headers)

# --- 결과 분석 함수 --- 

def analyze_results(results: List[RequestResult]) -> Dict[str, Any]:
    """테스트 결과 분석 및 요약"""
    if not results:
        return {"message": "No results to analyze."}
        
    response_times = [r.response_time for r in results if r.response_time is not None]
    success_count = sum(1 for r in results if 200 <= r.status_code < 300)
    error_count = len(results) - success_count
    
    # 시간 통계 계산 (결과가 있을 경우에만)
    time_stats = {}
    if response_times:
        response_times.sort()
        total_time = sum(response_times)
        count = len(response_times)
        time_stats = {
            "count": count,
            "total_time": round(total_time, 4),
            "min_time": round(response_times[0], 4),
            "max_time": round(response_times[-1], 4),
            "avg_time": round(mean(response_times), 4),
            "median_time": round(median(response_times), 4),
            "p90_time": round(response_times[int(count*0.9)] if count > 0 else 0, 4),
            "p95_time": round(response_times[int(count*0.95)] if count > 0 else 0, 4),
            "p99_time": round(response_times[int(count*0.99)] if count > 0 else 0, 4),
            "std_dev": round(stdev(response_times) if count > 1 else 0, 4)
        }

    # 결과 요약
    summary = {
        "total_requests": len(results),
        "success_count": success_count,
        "error_count": error_count,
        "success_rate": round(success_count / len(results) * 100, 2) if results else 0,
        **time_stats # 시간 통계 병합
    }
    
    # 에러 상세 분석
    errors = [r for r in results if r.status_code >= 300 or r.status_code < 0]
    error_details = {}
    for err in errors:
        key = f"HTTP_{err.status_code}" if err.status_code > 0 else (err.error.split(':')[0] if err.error else "UnknownError")
        error_details[key] = error_details.get(key, 0) + 1
    
    summary["error_summary"] = error_details
    
    # 첫 5개 에러 로그 (선택적)
    summary["error_samples"] = [
        {"id": r.id, "status": r.status_code, "error": r.error, "response": r.response_data} 
        for r in errors[:5]
    ]
    
    return summary

# --- 메인 실행 함수 --- 

async def main():
    """스크립트 실행 및 결과 출력"""
    parser = argparse.ArgumentParser(description='Casino API 성능 테스트 스크립트')
    parser.add_argument('--url', required=True, help='API 기본 URL (예: http://localhost:8000)')
    parser.add_argument('--api-key', required=True, help='테스트용 파트너 API 키')
    parser.add_argument('--player-id', required=True, help='테스트용 플레이어 ID (UUID)')
    parser.add_argument('--endpoint', choices=['balance', 'bet', 'all'], default='all', help='테스트할 엔드포인트')
    parser.add_argument('--concurrent', type=int, default=50, help='동시 요청 수')
    parser.add_argument('--duration', type=int, default=0, help='테스트 지속 시간(초). 0이면 concurrent 만큼만 실행.')
    
    args = parser.parse_args()
    
    start_run_time = time.time()
    all_results: Dict[str, List[RequestResult]] = {}

    endpoints_to_test = []
    if args.endpoint in ['balance', 'all']:
        endpoints_to_test.append(("Balance", test_balance_request))
    if args.endpoint in ['bet', 'all']:
        endpoints_to_test.append(("Bet", test_bet_request))

    if not endpoints_to_test:
        print("테스트할 엔드포인트가 지정되지 않았습니다.")
        return

    print(f"=== 성능 테스트 시작 ===")
    print(f"대상 URL: {args.url}/api")
    print(f"동시 요청 수: {args.concurrent}")
    if args.duration > 0:
        print(f"테스트 지속 시간: {args.duration} 초")
    print(f"테스트 엔드포인트: {args.endpoint}")
    print("---------------------------")

    if args.duration > 0:
        # 시간 기반 테스트
        end_time = start_run_time + args.duration
        loop_count = 0
        while time.time() < end_time:
            loop_count += 1
            print(f"\n--- 루프 {loop_count} 시작 ({time.time():.2f} / {end_time:.2f}) ---")
            for name, func in endpoints_to_test:
                results = await run_test(func, args.url, args.api_key, args.player_id, args.concurrent)
                if name not in all_results:
                    all_results[name] = []
                all_results[name].extend(results)
                print(f"[{name}] 루프 {loop_count}: {len(results)} 요청 완료")
            # 루프 간 짧은 대기 시간 (선택적)
            await asyncio.sleep(0.1)
    else:
        # 요청 수 기반 테스트
        for name, func in endpoints_to_test:
            print(f"\n--- [{name}] 엔드포인트 테스트 시작 ---")
            results = await run_test(func, args.url, args.api_key, args.player_id, args.concurrent)
            all_results[name] = results
            print(f"[{name}] 테스트 완료: {len(results)} 요청")

    print(f"\n=== 성능 테스트 종료 ===")
    total_run_time = time.time() - start_run_time
    print(f"총 실행 시간: {total_run_time:.2f} 초")
    print("---------------------------")

    # 최종 결과 분석 및 출력
    final_summary = {}
    for name, results in all_results.items():
        print(f"\n=== 결과 분석: [{name}] ===")
        summary = analyze_results(results)
        final_summary[name] = summary
        print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    asyncio.run(main()) 