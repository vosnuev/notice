"""
청약알리미 - 청약 공고 스크래퍼

지원 출처:
  1. 청약홈 (APT2you)  - applyhome.co.kr
  2. LH청약센터        - apply.lh.or.kr
  3. SH서울주택공사    - i-sh.co.kr
  4. 청년임대 (마이홈) - myhome.go.kr

주의: 사이트 구조 변경 시 URL/파싱 로직 수정이 필요할 수 있습니다.
"""

import requests
import json
import hashlib
import logging
from datetime import datetime
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'ko-KR,ko;q=0.9',
}

TIMEOUT = 15  # 초


# ────────────────────────────────────────────────────────────────────────────
# 공통 유틸
# ────────────────────────────────────────────────────────────────────────────

def make_key(*parts) -> str:
    """중복 방지용 고유 키 생성"""
    raw = '|'.join(str(p) for p in parts)
    return hashlib.md5(raw.encode()).hexdigest()


def safe_get(url, params=None, timeout=TIMEOUT):
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        return resp
    except Exception as e:
        logger.warning(f"[scraper] GET 실패 {url}: {e}")
        return None


# ────────────────────────────────────────────────────────────────────────────
# 1. 청약홈 (APT2you)
# ────────────────────────────────────────────────────────────────────────────

def scrape_applyhome():
    """청약홈 분양/임대 공고 수집 (HTML 파싱 방식)"""
    results = []
    base = 'https://www.applyhome.co.kr'
    
    views = [
        (f'{base}/ai/aia/selectAPTLttotPblancListView.do', False),
        (f'{base}/ai/aia/selectOtherLttotPblancListView.do', True)
    ]
    
    for url, is_other in views:
        try:
            resp = safe_get(url)
            if not resp: continue
            soup = BeautifulSoup(resp.text, 'html.parser')
            rows = soup.select('table.tbl_st tbody tr')
            for row in rows:
                if not row.has_attr('data-pbno'): continue
                
                hno = row.get('data-hmno', '')
                pno = row.get('data-pbno', '')
                title = row.get('data-honm', '')
                
                tds = row.select('td')
                if len(tds) < 5: continue
                
                reg = tds[0].get_text(strip=True)
                start_date = tds[6].get_text(strip=True) if not is_other else tds[5].get_text(strip=True)
                
                prefix = 'Other' if is_other else 'APT'
                link = f'{base}/ai/aia/select{prefix}LttotPblancDetail.do?houseManageNo={hno}&pblancNo={pno}'
                
                results.append({
                    'listing_key':    make_key('ah', hno, pno, title),
                    'title':          title,
                    'source':         '청약홈',
                    'listing_type':   '아파트' if not is_other else '오피스텔/기타',
                    'region':         _extract_sido(reg),
                    'district':       reg,
                    'address':        '',
                    'total_supply':   None,
                    'application_start': start_date,
                    'application_end':   '',
                    'winner_announce':   '',
                    'income_limit_pct': 100 if is_other else None,
                    'asset_limit_man':  None,
                    'min_age':          _guess_min_age(title),
                    'max_age':          _guess_max_age(title),
                    'marital_required': 'any',
                    'detail_url':     link,
                    'raw_data':       json.dumps({'hno': hno, 'pno': pno}, ensure_ascii=False),
                })
        except Exception as e:
            logger.warning(f"[청약홈] 파싱 오류 ({url}): {e}")
            
    logger.info(f"[청약홈] {len(results)}건 수집")
    return results



# ────────────────────────────────────────────────────────────────────────────
# 2. LH청약센터
# ────────────────────────────────────────────────────────────────────────────

def scrape_lh():
    """LH청약센터 공고 수집"""
    results = []
    url = 'https://apply.lh.or.kr/lhApply/apply/getApplyListJson.do'
    params = {
        'searchType': '', 'searchKeyword': '',
        'pageIndex': '1', 'pageUnit': '30',
    }
    resp = safe_get(url, params=params)
    if resp:
        try:
            data = resp.json()
            for item in data.get('resultList', []) or []:
                house_nm = item.get('SBD_LGO_NM', '') or item.get('LGO_NM', '')
                results.append({
                    'listing_key':    make_key('lh', item.get('AIS_TP_CD', ''), item.get('PAN_ID', '')),
                    'title':          house_nm,
                    'source':         'LH',
                    'listing_type':   _lh_type(item.get('AIS_TP_CD', '')),
                    'region':         _extract_sido(item.get('PAN_ADR', '')),
                    'district':       item.get('PAN_ADR', ''),
                    'address':        item.get('PAN_ADR', ''),
                    'total_supply':   _safe_int(item.get('SUP_CNT')),
                    'application_start': _fmt_date(item.get('SUBSCRPT_RCEPT_BGNDE')),
                    'application_end':   _fmt_date(item.get('SUBSCRPT_RCEPT_ENDDE')),
                    'winner_announce':   _fmt_date(item.get('PRZWNER_PRESNATN_DE')),
                    'income_limit_pct': _lh_income_pct(item.get('AIS_TP_CD', '')),
                    'asset_limit_man':  36100,  # LH 기본 자산 상한
                    'min_age':          None,
                    'max_age':          None,
                    'marital_required': 'any',
                    'detail_url': f"https://apply.lh.or.kr/lhApply/apply/view.do?panId={item.get('PAN_ID','')}",
                    'raw_data': json.dumps(item, ensure_ascii=False),
                })
        except Exception as e:
            logger.warning(f"[LH] 파싱 오류: {e}")

    # 청년 전세임대 별도
    url_youth = 'https://apply.lh.or.kr/lhApply/apply/getApplyListJson.do'
    resp_y = safe_get(url_youth, params={**params, 'searchType': 'young'})
    if resp_y:
        try:
            data_y = resp_y.json()
            for item in data_y.get('resultList', []) or []:
                house_nm = item.get('SBD_LGO_NM', '') or item.get('LGO_NM', '')
                results.append({
                    'listing_key':    make_key('lh_youth', item.get('AIS_TP_CD', ''), item.get('PAN_ID', ''), 'y'),
                    'title':          house_nm,
                    'source':         'LH',
                    'listing_type':   '청년전세임대',
                    'region':         _extract_sido(item.get('PAN_ADR', '')),
                    'district':       item.get('PAN_ADR', ''),
                    'address':        item.get('PAN_ADR', ''),
                    'total_supply':   _safe_int(item.get('SUP_CNT')),
                    'application_start': _fmt_date(item.get('SUBSCRPT_RCEPT_BGNDE')),
                    'application_end':   _fmt_date(item.get('SUBSCRPT_RCEPT_ENDDE')),
                    'winner_announce':   None,
                    'income_limit_pct': 100,
                    'asset_limit_man':  36100,
                    'min_age':          19,
                    'max_age':          39,
                    'marital_required': 'any',
                    'detail_url': f"https://apply.lh.or.kr/lhApply/apply/view.do?panId={item.get('PAN_ID','')}",
                    'raw_data': json.dumps(item, ensure_ascii=False),
                })
        except Exception as e:
            logger.warning(f"[LH 청년] 파싱 오류: {e}")

    logger.info(f"[LH] {len(results)}건 수집")
    return results


# ────────────────────────────────────────────────────────────────────────────
# 3. SH서울주택공사
# ────────────────────────────────────────────────────────────────────────────

def scrape_sh():
    """SH서울주택공사 공고 수집"""
    results = []
    base = 'https://www.i-sh.co.kr'
    url = f'{base}/main/lay2/program/S1T294C297/www/brd/m_247/list.do'
    resp = safe_get(url)
    if not resp:
        return results
    try:
        soup = BeautifulSoup(resp.text, 'html.parser')
        rows = soup.select('div#listTb table tbody tr') or soup.select('table.list_type tbody tr')
        for row in rows:
            tds = row.select('td')
            if len(tds) < 4:
                continue
            a = row.select_one('td.txtL a') or row.select_one('td a')
            if not a:
                continue
            title = a.get_text(strip=True)
            if 'NEW' in title: title = title.replace('NEW', '').strip()
            
            import re
            onclick = a.get('onclick', '')
            match = re.search(r"getDetailView\('(\d+)'\)", onclick)
            seq = match.group(1) if match else ''
            link = f'{base}/main/lay2/program/S1T294C297/www/brd/m_247/view.do?seq={seq}' if seq else url
            
            date_text = tds[-2].get_text(strip=True)
            status = tds[-1].get_text(strip=True)
            if not title:
                continue
            results.append({
                'listing_key':    make_key('sh', seq, title, date_text),
                'title':          title,
                'source':         'SH',
                'listing_type':   _sh_type(title),
                'region':         '서울',
                'district':       '서울',
                'address':        '',
                'total_supply':   None,
                'application_start': date_text,
                'application_end':   '',
                'winner_announce':   '',
                'income_limit_pct': _sh_income_pct(title),
                'asset_limit_man':  None,
                'min_age':          _guess_min_age(title),
                'max_age':          _guess_max_age(title),
                'marital_required': 'any',
                'detail_url':     link,
                'raw_data':       json.dumps({'title': title, 'status': status, 'seq': seq}, ensure_ascii=False),
            })
    except Exception as e:
        logger.warning(f"[SH] 파싱 오류: {e}")
    logger.info(f"[SH] {len(results)}건 수집")
    return results


# ────────────────────────────────────────────────────────────────────────────
# 4. 마이홈포털 청년주택
# ────────────────────────────────────────────────────────────────────────────

def scrape_myhome_youth():
    """마이홈포털 청년임대주택 공고 수집"""
    results = []
    url = 'https://www.myhome.go.kr/hws/portal/main/getMortgageLoanList.do'
    params = {'pageIndex': '1', 'pageUnit': '20', 'rcritPblancNm': ''}
    resp = safe_get(url, params=params)
    if resp:
        try:
            data = resp.json()
            for item in data.get('resultList', []) or []:
                house_nm = item.get('AIS_TP_NM', '') or item.get('PAN_NM', '')
                results.append({
                    'listing_key':    make_key('myhome', item.get('PAN_ID', ''), house_nm),
                    'title':          house_nm,
                    'source':         '마이홈',
                    'listing_type':   '청년임대',
                    'region':         _extract_sido(item.get('PAN_ADR', '')),
                    'district':       item.get('PAN_ADR', ''),
                    'address':        item.get('PAN_ADR', ''),
                    'total_supply':   _safe_int(item.get('SUP_CNT')),
                    'application_start': _fmt_date(item.get('RCEPT_BGNDE')),
                    'application_end':   _fmt_date(item.get('RCEPT_ENDDE')),
                    'winner_announce':   None,
                    'income_limit_pct': 100,
                    'asset_limit_man':  None,
                    'min_age':          19,
                    'max_age':          39,
                    'marital_required': 'any',
                    'detail_url':     f"https://www.myhome.go.kr/hws/portal/main/getMortgageLoanDetail.do?panId={item.get('PAN_ID','')}",
                    'raw_data':       json.dumps(item, ensure_ascii=False),
                })
        except Exception as e:
            logger.warning(f"[마이홈] 파싱 오류: {e}")
    logger.info(f"[마이홈/청년] {len(results)}건 수집")
    return results


# ────────────────────────────────────────────────────────────────────────────
# 5. 서울시 청년안심주택
# ────────────────────────────────────────────────────────────────────────────

def scrape_soco_youth():
    """서울시 청년안심주택 공고 수집"""
    results = []
    url = "https://soco.seoul.go.kr/youth/pgm/home/yohome/bbsListJson.json"
    params = {
        "bbsId": "BMSR00015",
        "pageIndex": "1"
    }
    try:
        # POST 요청 필요
        resp = requests.post(url, data=params, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        for item in data.get('resultList', []):
            title = item.get('nttSj', '')
            opt2 = item.get('optn2', '') # 1: 공공, 2: 민간
            opt5 = item.get('optn5', '') # 1: 최초, 2: 추가
            
            gubun_parts = []
            if opt2 == '1': gubun_parts.append('공공')
            elif opt2 == '2': gubun_parts.append('민간')
            if opt5 == '1': gubun_parts.append('최초')
            elif opt5 == '2': gubun_parts.append('추가')
            gubun = '/'.join(gubun_parts) if gubun_parts else '청년안심주택'

            results.append({
                'listing_key':    make_key('soco', item.get('boardId', ''), title),
                'title':          title,
                'source':         '서울시 청년안심주택',
                'listing_type':   gubun,
                'region':         '서울',
                'district':       '서울',
                'address':        '',
                'total_supply':   None,
                'application_start': item.get('optn4', ''),
                'application_end':   '',
                'winner_announce':   '',
                'income_limit_pct': 100,
                'asset_limit_man':  None,
                'min_age':          19,
                'max_age':          39,
                'marital_required': 'any',
                'detail_url':     f"https://soco.seoul.go.kr/youth/bbs/BMSR00015/view.do?boardId={item.get('boardId','')}&menuNo=400008",
                'raw_data':       json.dumps(item, ensure_ascii=False),
            })
    except Exception as e:
        logger.warning(f"[서울시청년안심주택] 파싱 오류: {e}")
    
    logger.info(f"[서울시청년안심주택] {len(results)}건 수집")
    return results


# ────────────────────────────────────────────────────────────────────────────
# 전체 수집 엔트리포인트
# ────────────────────────────────────────────────────────────────────────────

def scrape_all():
    """모든 출처에서 공고를 수집하여 통합 반환"""
    all_items = []
    scrapers = [
        ('청약홈',    scrape_applyhome),
        ('LH',       scrape_lh),
        ('SH',       scrape_sh),
        ('마이홈',   scrape_myhome_youth),
        ('청년안심주택', scrape_soco_youth),
    ]
    for name, func in scrapers:
        try:
            items = func()
            all_items.extend(items)
        except Exception as e:
            logger.error(f"[{name}] 수집 실패: {e}")
    logger.info(f"[전체] 총 {len(all_items)}건 수집 완료")
    return all_items


# ────────────────────────────────────────────────────────────────────────────
# 헬퍼 함수
# ────────────────────────────────────────────────────────────────────────────

def _safe_int(val) -> int | None:
    try:
        return int(str(val).replace(',', ''))
    except Exception:
        return None

def _fmt_date(val: str | None) -> str:
    if not val:
        return ''
    val = str(val).strip()
    if len(val) == 8 and val.isdigit():
        return f"{val[:4]}-{val[4:6]}-{val[6:]}"
    return val

def _extract_sido(address: str) -> str:
    """주소에서 시/도 추출"""
    if not address:
        return ''
    parts = address.strip().split()
    if parts:
        return parts[0]
    return address

def _map_ltype(secd_nm: str) -> str:
    mapping = {
        '민영': '민간분양', '국민': '공공분양',
        '공공': '공공분양', '민간': '민간분양',
    }
    for k, v in mapping.items():
        if k in secd_nm:
            return v
    return '공공분양'

def _map_rent_type(secd_nm: str) -> str:
    nm = secd_nm or ''
    if '행복' in nm:
        return '행복주택'
    if '청년' in nm:
        return '청년임대'
    if '국민' in nm or '영구' in nm or '장기' in nm:
        return '공공임대'
    return '공공임대'

def _lh_type(code: str) -> str:
    mapping = {
        'YR': '청년전세임대', 'YM': '청년매입임대',
        'HR': '행복주택', 'PR': '공공분양',
        'GR': '공공임대', 'NR': '공공임대',
    }
    return mapping.get(code, '공공임대')

def _lh_income_pct(code: str) -> int | None:
    mapping = {'YR': 100, 'YM': 100, 'HR': 100, 'PR': 140, 'GR': 100}
    return mapping.get(code)

def _sh_type(title: str) -> str:
    if '행복주택' in title:
        return '행복주택'
    if '청년' in title:
        return '청년임대'
    if '분양' in title:
        return '공공분양'
    return '공공임대'

def _sh_income_pct(title: str) -> int | None:
    if '청년' in title or '행복' in title:
        return 100
    if '분양' in title:
        return 140
    return 100

def _guess_income_pct(secd_nm: str) -> int | None:
    nm = secd_nm or ''
    if '청년' in nm or '행복' in nm:
        return 100
    if '공공분양' in nm:
        return 140
    return None

def _guess_min_age(title: str) -> int | None:
    if '청년' in title or '행복' in title:
        return 19
    return None

def _guess_max_age(title: str) -> int | None:
    if '청년' in title or '행복' in title:
        return 39
    return None
