"""
청약알리미 - 카카오톡 알림 모듈

[ 사용 방법 - 카카오 나에게 보내기 ]

1. https://developers.kakao.com 접속 → 앱 만들기
2. 앱 설정 > 플랫폼 > Web 플랫폼 추가: http://localhost:5000
3. 제품 설정 > 카카오 로그인 > 활성화 ON
4. 카카오 로그인 > Redirect URI 추가: http://localhost:5000/kakao/callback
5. 동의항목 > talk_message (카카오톡 메시지) 권한 ON
6. 앱 설정 > 앱 키 > REST API 키 복사
7. 웹사이트 설정 페이지에서 REST API 키 입력 후 '카카오 로그인' 버튼 클릭

* 토큰은 자동으로 갱신됩니다.
"""

import requests
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

KAKAO_AUTH_URL   = 'https://kauth.kakao.com/oauth/authorize'
KAKAO_TOKEN_URL  = 'https://kauth.kakao.com/oauth/token'
KAKAO_SEND_URL   = 'https://kapi.kakao.com/v2/api/talk/memo/default/send'
KAKAO_ME_URL     = 'https://kapi.kakao.com/v2/user/me'
REDIRECT_URI     = 'http://localhost:5000/kakao/callback'


# ── OAuth URL 생성 ────────────────────────────────────────────────────────

def get_auth_url(rest_api_key: str) -> str:
    """카카오 로그인 OAuth URL 반환"""
    return (
        f"{KAKAO_AUTH_URL}"
        f"?client_id={rest_api_key}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&response_type=code"
        f"&scope=talk_message"
    )


# ── 토큰 발급 ────────────────────────────────────────────────────────────

def exchange_code_for_token(rest_api_key, code):
    """인가 코드로 Access Token 교환"""
    try:
        resp = requests.post(KAKAO_TOKEN_URL, data={
            'grant_type':   'authorization_code',
            'client_id':    rest_api_key,
            'redirect_uri': REDIRECT_URI,
            'code':         code,
        }, timeout=10)
        data = resp.json()
        if 'access_token' in data:
            logger.info("[카카오] 토큰 발급 성공")
            return data
        logger.warning(f"[카카오] 토큰 발급 실패: {data}")
        return None
    except Exception as e:
        logger.error(f"[카카오] 토큰 발급 오류: {e}")
        return None


def refresh_access_token(rest_api_key, refresh_token):
    """Refresh Token으로 Access Token 갱신"""
    try:
        resp = requests.post(KAKAO_TOKEN_URL, data={
            'grant_type':    'refresh_token',
            'client_id':     rest_api_key,
            'refresh_token': refresh_token,
        }, timeout=10)
        data = resp.json()
        if 'access_token' in data:
            logger.info("[카카오] 토큰 갱신 성공")
            return data
        logger.warning(f"[카카오] 토큰 갱신 실패: {data}")
        return None
    except Exception as e:
        logger.error(f"[카카오] 토큰 갱신 오류: {e}")
        return None


# ── 토큰 상태 확인 ───────────────────────────────────────────────────────

def verify_token(access_token: str) -> bool:
    """Access Token 유효 여부 확인"""
    try:
        resp = requests.get(KAKAO_ME_URL, headers={
            'Authorization': f'Bearer {access_token}'
        }, timeout=10)
        return resp.status_code == 200
    except Exception:
        return False


# ── 메시지 전송 ──────────────────────────────────────────────────────────

def send_notification(access_token: str, listing: dict) -> bool:
    """
    청약 공고를 카카오톡 나에게 보내기로 전송
    listing: Listing.to_dict() 결과
    """
    title   = listing.get('title', '')
    ltype   = listing.get('listing_type', '')
    region  = listing.get('region', '')
    district = listing.get('district', '')
    supply  = listing.get('total_supply') or '-'
    start   = listing.get('application_start') or '-'
    end     = listing.get('application_end') or '-'
    url     = listing.get('detail_url') or 'https://www.applyhome.co.kr'
    source  = listing.get('source', '')

    # ── 카카오 피드형 메시지 (링크 포함) ──
    template = {
        "object_type": "feed",
        "content": {
            "title": f"🏠 {title}",
            "description": (
                f"📌 유형: {ltype}\n"
                f"📍 위치: {district or region}\n"
                f"🏘️ 공급세대: {supply}세대\n"
                f"📅 접수: {start} ~ {end}\n"
                f"📋 출처: {source}"
            ),
            "link": {
                "web_url": url,
                "mobile_web_url": url,
            }
        },
        "buttons": [
            {
                "title": "공고 상세 보기",
                "link": {
                    "web_url": url,
                    "mobile_web_url": url,
                }
            }
        ]
    }

    import json
    try:
        resp = requests.post(
            KAKAO_SEND_URL,
            headers={'Authorization': f'Bearer {access_token}'},
            data={'template_object': json.dumps(template, ensure_ascii=False)},
            timeout=10,
        )
        result = resp.json()
        if result.get('result_code') == 0:
            logger.info(f"[카카오] 알림 전송 성공: {title}")
            return True
        else:
            logger.warning(f"[카카오] 알림 전송 실패: {result}")
            return False
    except Exception as e:
        logger.error(f"[카카오] 알림 전송 오류: {e}")
        return False


def send_test_message(access_token: str) -> bool:
    """테스트 메시지 전송"""
    return send_notification(access_token, {
        'title': '청약알리미 테스트 메시지',
        'listing_type': '테스트',
        'region': '서울',
        'district': '서울시',
        'total_supply': 100,
        'application_start': '2025-01-01',
        'application_end': '2025-01-07',
        'detail_url': 'https://www.applyhome.co.kr',
        'source': '청약알리미',
    })
