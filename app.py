"""cheongak alimi - single file Flask app"""
import os, logging, json, hashlib, requests
from datetime import datetime
from flask import Flask, render_template_string, request, redirect, url_for, jsonify, flash, get_flashed_messages
from flask_sqlalchemy import SQLAlchemy
from apscheduler.schedulers.background import BackgroundScheduler
from bs4 import BeautifulSoup

DATA_DIR = os.path.join(os.path.expanduser('~'), 'cheongak_data')
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH  = os.path.join(DATA_DIR, 'cheongak.db')
LOG_PATH = os.path.join(DATA_DIR, 'cheongak.log')

logging.basicConfig(level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(), logging.FileHandler(LOG_PATH, encoding='utf-8')])
log = logging.getLogger(__name__)

try:
    import pytz; KST = pytz.timezone('Asia/Seoul')
except ImportError:
    KST = 'UTC'

app = Flask(__name__)
app.secret_key = 'cheongak2024'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + DB_PATH
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ── Models ────────────────────────────────────────────────────────────────────
class UserProfile(db.Model):
    __tablename__ = 'user_profile'
    id                    = db.Column(db.Integer, primary_key=True)
    name                  = db.Column(db.String(50),   default='나')
    age                   = db.Column(db.Integer,      default=25)
    marital_status        = db.Column(db.String(20),   default='single')
    has_children          = db.Column(db.Boolean,      default=False)
    children_count        = db.Column(db.Integer,      default=0)
    family_count          = db.Column(db.Integer,      default=1)
    has_house             = db.Column(db.Boolean,      default=False)
    family_has_house      = db.Column(db.Boolean,      default=False)
    monthly_income        = db.Column(db.Integer,      default=0)
    real_estate_assets    = db.Column(db.Integer,      default=0)
    financial_assets      = db.Column(db.Integer,      default=0)
    car_value             = db.Column(db.Integer,      default=0)
    savings_period_months = db.Column(db.Integer,      default=0)
    savings_payment_count = db.Column(db.Integer,      default=0)
    savings_amount        = db.Column(db.Integer,      default=0)
    preferred_regions     = db.Column(db.Text,         default='[]')
    prefer_public_sale    = db.Column(db.Boolean,      default=True)
    prefer_private_sale   = db.Column(db.Boolean,      default=True)
    prefer_public_rental  = db.Column(db.Boolean,      default=True)
    prefer_youth_rental   = db.Column(db.Boolean,      default=True)
    kakao_rest_api_key    = db.Column(db.String(200))
    kakao_access_token    = db.Column(db.String(1000))
    kakao_refresh_token   = db.Column(db.String(1000))
    check_interval_hours  = db.Column(db.Integer,      default=6)

    def get_preferred_regions(self):
        try: return json.loads(self.preferred_regions or '[]')
        except: return []
    def set_preferred_regions(self, lst):
        self.preferred_regions = json.dumps(lst, ensure_ascii=False)
    @property
    def total_assets(self):
        return (self.real_estate_assets or 0)+(self.financial_assets or 0)+(self.car_value or 0)

class Listing(db.Model):
    __tablename__ = 'listings'
    id                = db.Column(db.Integer,     primary_key=True)
    listing_key       = db.Column(db.String(300), unique=True, nullable=False)
    title             = db.Column(db.String(500))
    source            = db.Column(db.String(50))
    listing_type      = db.Column(db.String(50))
    region            = db.Column(db.String(100))
    district          = db.Column(db.String(100))
    total_supply      = db.Column(db.Integer)
    application_start = db.Column(db.String(20))
    application_end   = db.Column(db.String(20))
    income_limit_pct  = db.Column(db.Integer)
    asset_limit_man   = db.Column(db.Integer)
    min_age           = db.Column(db.Integer)
    max_age           = db.Column(db.Integer)
    marital_required  = db.Column(db.String(20))
    detail_url        = db.Column(db.String(1000))
    is_eligible       = db.Column(db.Boolean, default=False)
    notified          = db.Column(db.Boolean, default=False)
    scraped_at        = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}

class NotifLog(db.Model):
    __tablename__ = 'notif_log'
    id            = db.Column(db.Integer,  primary_key=True)
    listing_title = db.Column(db.String(500))
    sent_at       = db.Column(db.DateTime, default=datetime.utcnow)
    success       = db.Column(db.Boolean,  default=True)

# 수집 상태 기록 (메모리)
scrape_status = {'last_run': None, 'errors': [], 'counts': {}}

# ── Eligibility ───────────────────────────────────────────────────────────────
URBAN = {1:3482964,2:4867903,3:6024638,4:6891891,5:7254237}

def ui(n): return URBAN[max(1,min(n or 1,5))]

def eligible(profile, lst):
    ltype = (lst.listing_type or '').strip()
    pm = {'공공분양':profile.prefer_public_sale,'민간분양':profile.prefer_private_sale,
          '공공임대':profile.prefer_public_rental,'행복주택':profile.prefer_youth_rental,
          '청년임대':profile.prefer_youth_rental,'청년전세임대':profile.prefer_youth_rental,
          '청년매입임대':profile.prefer_youth_rental}
    if not pm.get(ltype, True): return False
    prefs = profile.get_preferred_regions()
    if prefs and not any(r in (lst.region or '') for r in prefs): return False
    if profile.has_house or profile.family_has_house: return False
    age = profile.age or 0
    if lst.min_age and age < lst.min_age: return False
    if lst.max_age and age > lst.max_age: return False
    if lst.marital_required == 'single' and profile.marital_status != 'single': return False
    if lst.income_limit_pct:
        if (profile.monthly_income or 0)*10000 > ui(profile.family_count)*lst.income_limit_pct/100: return False
    if lst.asset_limit_man and profile.total_assets > lst.asset_limit_man: return False
    if ltype in ('공공분양','민간분양') and (profile.savings_period_months or 0) < 6: return False
    return True

def eli_summary(profile):
    base = ui(profile.family_count or 1)
    mine = (profile.monthly_income or 0)*10000
    age  = profile.age or 0
    out  = []
    if 19<=age<=39 and profile.marital_status=='single':
        out.append({'type':'공공분양 청년특별공급','ok':mine<=base*1.4 and profile.total_assets<=36100,'cond':'소득 140% 이하, 순자산 3.61억 이하'})
    if 19<=age<=39:
        out.append({'type':'행복주택 (청년)','ok':mine<=base,'cond':f'소득 100% ({base//10000}만원) 이하'})
        out.append({'type':'청년 매입/전세임대','ok':mine<=base,'cond':'소득 100% 이하'})
    if (profile.savings_period_months or 0)>=6:
        out.append({'type':'민간분양 일반공급','ok':True,'cond':f'청약통장 {profile.savings_period_months}개월'})
    return out

# ── Scraper ───────────────────────────────────────────────────────────────────
# 브라우저처럼 보이는 헤더 (정부 사이트 차단 방지)
BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'sec-ch-ua': '"Chromium";v="124", "Google Chrome";v="124"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-origin',
}

def new_session(referer=None):
    s = requests.Session()
    h = dict(BROWSER_HEADERS)
    if referer:
        h['Referer'] = referer
    s.headers.update(h)
    return s

def sg(url, params=None, referer=None, as_json=False):
    """GET 요청, 실패 시 None 반환"""
    try:
        s = new_session(referer)
        r = s.get(url, params=params, timeout=15)
        r.raise_for_status()
        if as_json:
            return r.json()
        return r
    except requests.exceptions.JSONDecodeError:
        log.warning(f'JSON 파싱 실패 {url}')
        return None
    except Exception as e:
        log.warning(f'GET 실패 {url}: {e}')
        scrape_status['errors'].append(f'{url.split("/")[2]}: {type(e).__name__}')
        return None

def mk(s): return hashlib.md5(str(s).encode()).hexdigest()
def fd(v):
    v=str(v or '').strip()
    return f'{v[:4]}-{v[4:6]}-{v[6:]}' if len(v)==8 and v.isdigit() else v
def sido(a): p=str(a or '').strip().split(); return p[0] if p else ''

def scrape_apt2you():
    """청약홈 분양/임대 공고 수집 (HTML 파싱 방식)"""
    out = []
    base = 'https://www.applyhome.co.kr'
    
    # 1. APT 분양정보
    # 2. 오피스텔/도시형/민간임대 등
    views = [
        (f'{base}/ai/aia/selectAPTLttotPblancListView.do', False),
        (f'{base}/ai/aia/selectOtherLttotPblancListView.do', True)
    ]
    
    for url, is_other in views:
        try:
            s = new_session(base + '/')
            r = s.get(url, timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, 'html.parser')
            rows = soup.select('table.tbl_st tbody tr')
            for row in rows:
                if not row.has_attr('data-pbno'): continue
                
                hno = row.get('data-hmno', '')
                pno = row.get('data-pbno', '')
                title = row.get('data-honm', '')
                
                tds = row.select('td')
                if len(tds) < 5: continue
                
                reg = tds[0].get_text(strip=True)
                # tds[1]: 주택구분 (민영/국민), tds[2]: 분양/임대
                # tds[3]: 주택명 (a태그 포함)
                # tds[6]: 모집공고일
                # tds[7]: 청약기간
                
                start_date = tds[6].get_text(strip=True) if not is_other else tds[5].get_text(strip=True)
                
                prefix = 'Other' if is_other else 'APT'
                d_url = f'{base}/ai/aia/select{prefix}LttotPblancDetail.do?houseManageNo={hno}&pblancNo={pno}'
                
                out.append({
                    'listing_key': mk(f'ah{hno}{pno}{title}'),
                    'title': title,
                    'source': 'APT2YOU',
                    'listing_type': '청약홈' + ('(기타)' if is_other else ''),
                    'region': sido(reg),
                    'district': reg,
                    'total_supply': None,
                    'application_start': start_date,
                    'application_end': '',
                    'income_limit_pct': 100 if is_other else None,
                    'asset_limit_man': None,
                    'min_age': None, 'max_age': None,
                    'marital_required': 'any',
                    'detail_url': d_url,
                })
        except Exception as e:
            log.warning(f'APT2YOU {url}: {e}')
    return out

def scrape_lh():
    out = []
    base = 'https://apply.lh.or.kr'
    urls = [
        f'{base}/lhApply/apply/getApplyListJson.do',
        f'{base}/lhApply/apply/list.do',
    ]
    params = {'searchType':'','searchKeyword':'','pageIndex':'1','pageUnit':'30'}
    lm = {'YR':'청년전세임대','YM':'청년매입임대','HR':'행복주택','PR':'공공분양','GR':'공공임대','NR':'공공임대','CR':'공공임대'}
    im = {'YR':100,'YM':100,'HR':100,'PR':140}

    for url in urls:
        try:
            s = new_session(base + '/')
            r = s.get(url, params=params, timeout=15)
            r.raise_for_status()
            try:
                data = r.json()
            except Exception:
                # HTML 응답이면 BeautifulSoup으로 파싱
                soup = BeautifulSoup(r.text, 'html.parser')
                for row in soup.select('table tbody tr'):
                    cols = row.select('td')
                    if len(cols) < 4:
                        continue
                    a = row.select_one('a')
                    title = a.get_text(strip=True) if a else cols[0].get_text(strip=True)
                    href  = a.get('href','') if a else ''
                    stype = '행복주택' if '행복' in title else ('청년임대' if '청년' in title else '공공임대')
                    out.append({
                        'listing_key': mk(f'lh_html_{title}'),
                        'title': title, 'source': 'LH', 'listing_type': stype,
                        'region': '전국', 'district': '',
                        'total_supply': None, 'application_start': '', 'application_end': '',
                        'income_limit_pct': 100, 'asset_limit_man': None,
                        'min_age': 19 if '청년' in title else None,
                        'max_age': 39 if '청년' in title else None,
                        'marital_required': 'any',
                        'detail_url': base + href if href.startswith('/') else href or base,
                    })
                if out:
                    break
                continue

            items = (data.get('resultList') or data.get('data') or data.get('list') or [])
            for item in items:
                code = item.get('AIS_TP_CD','') or item.get('aisTpCd','')
                youth = code in ('YR','YM')
                pan_id = item.get('PAN_ID') or item.get('panId','')
                out.append({
                    'listing_key': mk(f'lh{code}{pan_id}'),
                    'title': item.get('SBD_LGO_NM') or item.get('LGO_NM') or item.get('sbdLgoNm') or item.get('lgoNm',''),
                    'source': 'LH',
                    'listing_type': lm.get(code, '공공임대'),
                    'region': sido(item.get('PAN_ADR') or item.get('panAdr','')),
                    'district': item.get('PAN_ADR') or item.get('panAdr',''),
                    'total_supply': None,
                    'application_start': fd(item.get('SUBSCRPT_RCEPT_BGNDE') or item.get('subscrptRceptBgnde','')),
                    'application_end':   fd(item.get('SUBSCRPT_RCEPT_ENDDE') or item.get('subscrptRceptEndde','')),
                    'income_limit_pct': im.get(code),
                    'asset_limit_man': 36100 if im.get(code) else None,
                    'min_age': 19 if youth else None,
                    'max_age': 39 if youth else None,
                    'marital_required': 'any',
                    'detail_url': f'{base}/lhApply/apply/view.do?panId={pan_id}',
                })
            if out:
                break
        except Exception as e:
            log.warning(f'LH {url}: {e}')
            scrape_status['errors'].append(f'LH: {e}')
    return out

def scrape_sh():
    out = []
    base = 'https://www.i-sh.co.kr'
    # SH 공고 목록 URL (최신)
    urls = [
        f'{base}/main/lay2/program/S1T294C297/www/brd/m_247/list.do',
    ]
    for url in urls:
        try:
            s = new_session(base + '/')
            r = s.get(url, timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, 'html.parser')
            rows = soup.select('div#listTb table tbody tr') or soup.select('table.list_type tbody tr')
            if not rows:
                continue
            for row in rows:
                tds = row.select('td')
                if len(tds) < 4: continue
                a = row.select_one('td.txtL a') or row.select_one('td a')
                if not a: continue
                title = a.get_text(strip=True)
                if 'NEW' in title: title = title.replace('NEW', '').strip()
                if not title: continue
                
                # getDetailView('303687') 에서 ID 추출
                import re
                onclick = a.get('onclick', '')
                match = re.search(r"getDetailView\('(\d+)'\)", onclick)
                seq = match.group(1) if match else ''
                d_url = f'{base}/main/lay2/program/S1T294C297/www/brd/m_247/view.do?seq={seq}' if seq else url
                
                date_val = tds[-2].get_text(strip=True)
                stype = '행복주택' if '행복' in title else ('청년임대' if '청년' in title else '공공임대')
                youth = '청년' in title or '행복' in title
                
                out.append({
                    'listing_key': mk(f'sh{seq}{title}{date_val}'),
                    'title': title, 'source': 'SH', 'listing_type': stype,
                    'region': '서울', 'district': '서울',
                    'total_supply': None, 'application_start': date_val, 'application_end': '',
                    'income_limit_pct': 100, 'asset_limit_man': None,
                    'min_age': 19 if youth else None,
                    'max_age': 39 if youth else None,
                    'marital_required': 'any',
                    'detail_url': d_url,
                })
            if out:
                break
        except Exception as e:
            log.warning(f'SH {url}: {e}')
            scrape_status['errors'].append(f'SH: {e}')
    return out

def scrape_myhome():
    """마이홈포털 (국토부 청년임대)"""
    out = []
    base = 'https://www.myhome.go.kr'
    url  = f'{base}/mw/AA/selectReqstInfolist.do'
    try:
        s = new_session(base + '/')
        r = s.post(url, data={'pageIndex':'1','pageUnit':'20','ctgCd':'04'}, timeout=15)
        r.raise_for_status()
        data = r.json()
        for item in (data.get('list') or data.get('resultList') or []):
            title = item.get('taskNm') or item.get('taskNm','')
            if not title: continue
            out.append({
                'listing_key': mk(f'mh{item.get("reqstNo","")}'),
                'title': title, 'source': '마이홈', 'listing_type': '공공임대',
                'region': sido(item.get('locCd','')),
                'district': item.get('locCd',''),
                'total_supply': None,
                'application_start': fd(item.get('rcptBgnDt','')),
                'application_end':   fd(item.get('rcptEndDt','')),
                'income_limit_pct': 100, 'asset_limit_man': None,
                'min_age': None, 'max_age': None, 'marital_required': 'any',
                'detail_url': f'{base}/mw/AA/selectReqstInfoDetail.do?reqstNo={item.get("reqstNo","")}',
            })
    except Exception as e:
        log.warning(f'마이홈 오류: {e}')
    return out

def scrape_soco_youth():
    """서울시 청년안심주택 공고 수집"""
    out = []
    base = 'https://soco.seoul.go.kr'
    url = f'{base}/youth/pgm/home/yohome/bbsListJson.json'
    params = {"bbsId": "BMSR00015", "pageIndex": "1"}
    try:
        s = new_session(f'{base}/youth/bbs/BMSR00015/list.do?menuNo=400008')
        r = s.post(url, data=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        for item in data.get('resultList', []):
            title = item.get('nttSj', '')
            opt2 = item.get('optn2', '') # 1: 공공, 2: 민간
            opt5 = item.get('optn5', '') # 1: 최초, 2: 추가
            
            gubun_parts = []
            if opt2 == '1': gubun_parts.append('공공')
            elif opt2 == '2': gubun_parts.append('민간')
            if opt5 == '1': gubun_parts.append('최초')
            elif opt5 == '2': gubun_parts.append('추가')
            stype = '/'.join(gubun_parts) if gubun_parts else '청년안심주택'
            
            bid = item.get('boardId','')
            out.append({
                'listing_key': mk(f'soco{bid}{title}'),
                'title': title,
                'source': '서울시 청년안심주택',
                'listing_type': stype,
                'region': '서울',
                'district': '서울',
                'total_supply': None,
                'application_start': item.get('optn4', ''), # 청약신청일
                'application_end':   '',
                'income_limit_pct': 100,
                'asset_limit_man': None,
                'min_age': 19, 'max_age': 39,
                'marital_required': 'any',
                'detail_url': f'{base}/youth/bbs/BMSR00015/view.do?boardId={bid}&menuNo=400008',
            })
    except Exception as e:
        log.warning(f'서울시 청년안심주택 오류: {e}')
        scrape_status['errors'].append(f'SOCO: {e}')
    return out

def scrape_all():
    global scrape_status
    scrape_status['errors'] = []
    scrape_status['last_run'] = datetime.now().strftime('%Y-%m-%d %H:%M')
    scrape_status['counts'] = {}

    items = []
    for name, fn in [('APT2YOU', scrape_apt2you), ('LH', scrape_lh), ('SH', scrape_sh), ('마이홈', scrape_myhome), ('청년안심주택', scrape_soco_youth)]:
        try:
            result = fn()
            scrape_status['counts'][name] = len(result)
            items.extend(result)
            log.info(f'{name}: {len(result)}건')
        except Exception as e:
            log.error(f'{name} 실패: {e}')
            scrape_status['errors'].append(f'{name}: {e}')
            scrape_status['counts'][name] = 0

    log.info(f'총 {len(items)}건 수집')
    return items

# ── Kakao ─────────────────────────────────────────────────────────────────────
REDIR='http://localhost:5000/kakao/callback'
def ka_url(key): return f'https://kauth.kakao.com/oauth/authorize?client_id={key}&redirect_uri={REDIR}&response_type=code&scope=talk_message'
def ka_exchange(key,code):
    try:
        r=requests.post('https://kauth.kakao.com/oauth/token',data={'grant_type':'authorization_code','client_id':key,'redirect_uri':REDIR,'code':code},timeout=10)
        d=r.json(); return d if 'access_token' in d else None
    except: return None
def ka_verify(token):
    try: return requests.get('https://kapi.kakao.com/v2/user/me',headers={'Authorization':f'Bearer {token}'},timeout=8).status_code==200
    except: return False
def ka_send(token,lst):
    url=lst.get('detail_url','https://www.apt2you.com')
    tmpl={"object_type":"feed","content":{"title":f"[청약알리미] {lst.get('title','')}",
        "description":f"유형: {lst.get('listing_type','')}\n위치: {lst.get('district','') or lst.get('region','')}\n접수: {lst.get('application_start','-')}~{lst.get('application_end','-')}",
        "link":{"web_url":url,"mobile_web_url":url}},
        "buttons":[{"title":"공고 보기","link":{"web_url":url,"mobile_web_url":url}}]}
    try:
        r=requests.post('https://kapi.kakao.com/v2/api/talk/memo/default/send',
            headers={'Authorization':f'Bearer {token}'},
            data={'template_object':json.dumps(tmpl,ensure_ascii=False)},timeout=10)
        return r.json().get('result_code')==0
    except: return False

# ── Scheduler ─────────────────────────────────────────────────────────────────
scheduler=BackgroundScheduler(timezone=KST)
def run_check():
    with app.app_context():
        profile=UserProfile.query.first()
        if not profile: return
        new_count = 0
        for item in scrape_all():
            if Listing.query.filter_by(listing_key=item['listing_key']).first(): continue
            lst=Listing(**{k:v for k,v in item.items() if hasattr(Listing,k)})
            lst.is_eligible=eligible(profile,lst)
            db.session.add(lst)
            new_count += 1
            if lst.is_eligible and profile.kakao_access_token:
                ok=ka_send(profile.kakao_access_token,lst.to_dict())
                lst.notified=True
                db.session.add(NotifLog(listing_title=lst.title,success=ok))
        db.session.commit()
        log.info(f'수집 완료 (신규 {new_count}건)')

def reschedule(h):
    if scheduler.get_job('chk'): scheduler.remove_job('chk')
    scheduler.add_job(run_check,'interval',hours=max(1,h),id='chk',replace_existing=True)

# ── CSS & HTML helpers ────────────────────────────────────────────────────────
CSS="""<style>
body{background:#f8f9fa;font-family:'Apple SD Gothic Neo',-apple-system,sans-serif}
.stat-num{font-size:2rem;font-weight:800}.stat-lbl{font-size:.8rem;color:#6c757d}
.lcard{border-radius:12px!important;transition:box-shadow .2s,transform .2s}
.lcard:hover{box-shadow:0 8px 24px rgba(0,0,0,.12)!important;transform:translateY(-2px)}
.b-ps{background:#0d6efd!important}.b-pr{background:#6610f2!important}
.b-pub{background:#198754!important}.b-hh{background:#20c997!important}
.b-yr{background:#fd7e14!important}.b-oth{background:#6c757d!important}
.erow td{background:#d1f7e4!important}
</style>"""

def btype(t):
    m={'공공분양':'b-ps','민간분양':'b-pr','공공임대':'b-pub','행복주택':'b-hh',
       '청년임대':'b-yr','청년전세임대':'b-yr','청년매입임대':'b-yr'}
    return m.get(t,'b-oth')

def fmt(v):
    try: return f'{int(v):,}'
    except: return str(v or '')

def navbar(active=''):
    links=[('/','대시보드'),('/profile','내 정보'),('/settings','카카오 설정')]
    items=''.join(f'<li class="nav-item"><a class="nav-link{"  active" if url==active else ""}" href="{url}">{label}</a></li>' for url,label in links)
    return f'<nav class="navbar navbar-dark bg-primary navbar-expand-lg"><div class="container"><a class="navbar-brand fw-bold" href="/"><i class="bi bi-house-heart-fill me-2"></i>청약알리미</a><div class="collapse navbar-collapse"><ul class="navbar-nav ms-auto">{items}</ul></div></div></nav>'

def flashes():
    msgs=get_flashed_messages(with_categories=True)
    if not msgs: return ''
    return '<div class="container mt-3">'+''.join(f'<div class="alert alert-{c} alert-dismissible fade show">{m}<button type="button" class="btn-close" data-bs-dismiss="alert"></button></div>' for c,m in msgs)+'</div>'

HEAD='<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/><title>청약알리미</title><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.3.2/css/bootstrap.min.css"/><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/bootstrap-icons/1.11.3/font/bootstrap-icons.min.css"/>'+CSS+'</head><body>'
FOOT='<script src="https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.3.2/js/bootstrap.bundle.min.js"></script></body></html>'

def page(active, content, scripts=''):
    return HEAD+navbar(active)+flashes()+'<main class="container my-4">'+content+'</main>'+scripts+FOOT

# ── Routes ────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    p=UserProfile.query.first()
    eligible_lst=Listing.query.filter_by(is_eligible=True).order_by(Listing.scraped_at.desc()).limit(20).all()
    all_lst=Listing.query.order_by(Listing.scraped_at.desc()).limit(50).all()
    total=Listing.query.count()
    etotal=Listing.query.filter_by(is_eligible=True).count()
    last=NotifLog.query.order_by(NotifLog.sent_at.desc()).first()
    last_date=last.sent_at.strftime('%m/%d') if last else '-'

    # 수집 상태 배너
    status_html = ''
    if scrape_status['last_run']:
        cnt_txt = ' | '.join(f'{k}: {v}건' for k,v in scrape_status['counts'].items())
        status_html = f'<div class="alert alert-info py-2 small mb-3"><i class="bi bi-info-circle me-1"></i>마지막 수집: {scrape_status["last_run"]} &nbsp;|&nbsp; {cnt_txt}</div>'
    if scrape_status['errors']:
        err_txt = ' / '.join(scrape_status['errors'][:3])
        status_html += f'<div class="alert alert-warning py-2 small mb-3"><i class="bi bi-exclamation-triangle me-1"></i>수집 오류: {err_txt}</div>'

    cards=''
    for lst in eligible_lst:
        bt=btype(lst.listing_type)
        cards+=f'''<div class="col-md-6 col-lg-4"><div class="card h-100 border-success border-2 shadow-sm lcard">
<div class="card-body">
<div class="d-flex justify-content-between mb-2"><span class="badge {bt}">{lst.listing_type}</span><span class="badge bg-secondary">{lst.source}</span></div>
<h6 class="fw-bold">{lst.title}</h6>
<div class="text-muted small"><i class="bi bi-geo-alt me-1"></i>{lst.district or lst.region or '-'}</div>
{"<div class='small mt-1'><i class='bi bi-calendar me-1'></i>"+str(lst.application_start)+" ~ "+(lst.application_end or '?')+"</div>" if lst.application_start else ""}
</div>
<div class="card-footer bg-transparent border-0"><a href="{lst.detail_url}" target="_blank" class="btn btn-sm btn-outline-primary w-100"><i class="bi bi-box-arrow-up-right me-1"></i>상세 보기</a></div>
</div></div>'''

    rows=''
    for lst in all_lst:
        bt=btype(lst.listing_type)
        ec='erow' if lst.is_eligible else ''
        badge='<span class="badge bg-success">해당</span>' if lst.is_eligible else '<span class="badge bg-light text-muted">미해당</span>'
        rows+=f'<tr class="{ec}"><td class="fw-semibold" style="max-width:200px">{lst.title}</td><td><span class="badge {bt}">{lst.listing_type}</span></td><td><span class="badge bg-secondary">{lst.source}</span></td><td class="text-muted small">{lst.district or lst.region or "-"}</td><td class="text-muted small">{lst.application_start or "-"}<br><span class="text-danger">~{lst.application_end or "-"}</span></td><td>{badge}</td><td><a href="{lst.detail_url}" target="_blank" class="btn btn-sm btn-outline-secondary"><i class="bi bi-link-45deg"></i></a></td></tr>'

    pname=p.name if p else '-'
    page_age=str(p.age)+'세' if p else '-'
    housing='무주택' if (p and not p.has_house) else '유주택'
    no_kakao='<a href="/settings" class="btn btn-warning"><i class="bi bi-chat-fill me-1"></i>카카오 연동 필요</a>' if not (p and p.kakao_access_token) else ''
    no_info='<a href="/profile" class="btn btn-outline-secondary"><i class="bi bi-person-gear me-1"></i>내 정보 입력</a>' if not (p and p.monthly_income) else ''
    eligible_section=f'<h5 class="fw-bold mb-3"><i class="bi bi-star-fill text-warning me-2"></i>내가 신청 가능한 청약 <span class="badge bg-success ms-1">{etotal}건</span></h5><div class="row g-3 mb-5">{cards}</div>' if eligible_lst else ''
    table_section=f'<div class="table-responsive"><table class="table table-hover align-middle" style="font-size:.87rem"><thead class="table-light"><tr><th>공고명</th><th>유형</th><th>출처</th><th>지역</th><th>접수기간</th><th>자격</th><th></th></tr></thead><tbody>{rows}</tbody></table></div><form action="/listings/clear" method="post" class="text-end mt-2" onsubmit="return confirm(\'초기화할까요?\')"><button class="btn btn-sm btn-outline-danger"><i class="bi bi-trash me-1"></i>목록 초기화</button></form>' if all_lst else '<div class="text-center text-muted py-5"><i class="bi bi-inbox display-4 d-block mb-3"></i>아직 공고가 없습니다. <strong>지금 바로 수집</strong> 버튼을 눌러보세요!</div>'

    content=f'''
{status_html}
<div class="row g-3 mb-4">
  <div class="col-6 col-md-3"><div class="card text-center border-0 shadow-sm h-100"><div class="card-body"><div class="fs-2 text-primary"><i class="bi bi-search"></i></div><div class="stat-num">{total}</div><div class="stat-lbl">모니터링 공고</div></div></div></div>
  <div class="col-6 col-md-3"><div class="card text-center border-0 shadow-sm h-100 bg-success-subtle"><div class="card-body"><div class="fs-2 text-success"><i class="bi bi-check-circle-fill"></i></div><div class="stat-num text-success">{etotal}</div><div class="stat-lbl">신청 가능 공고</div></div></div></div>
  <div class="col-6 col-md-3"><div class="card text-center border-0 shadow-sm h-100"><div class="card-body"><div class="fs-2 text-warning"><i class="bi bi-bell-fill"></i></div><div class="stat-num">{last_date}</div><div class="stat-lbl">마지막 알림</div></div></div></div>
  <div class="col-6 col-md-3"><div class="card text-center border-0 shadow-sm h-100"><div class="card-body"><div class="fs-2 text-info"><i class="bi bi-person-fill"></i></div><div class="stat-num" style="font-size:1.3rem">{pname}</div><div class="stat-lbl">{page_age} · {housing}</div></div></div></div>
</div>
<div class="d-flex gap-2 mb-4 flex-wrap">
  <form action="/check/now" method="post"><button class="btn btn-primary"><i class="bi bi-arrow-clockwise me-1"></i>지금 바로 수집</button></form>
  {no_kakao} {no_info}
</div>
{eligible_section}
<h5 class="fw-bold mb-3"><i class="bi bi-list-ul me-2"></i>전체 공고</h5>
{table_section}'''
    return render_template_string(page('/', content))

@app.route('/profile', methods=['GET','POST'])
def profile_page():
    p=UserProfile.query.first()
    if request.method=='POST':
        f=request.form
        ib=lambda k: f.get(k)=='on'
        ii=lambda k,d=0: int(f.get(k) or d)
        p.name=f.get('name','나'); p.age=ii('age',25)
        p.marital_status=f.get('marital_status','single')
        p.has_children=ib('has_children'); p.children_count=ii('children_count')
        p.family_count=ii('family_count',1)
        p.has_house=ib('has_house'); p.family_has_house=ib('family_has_house')
        p.monthly_income=ii('monthly_income')
        p.real_estate_assets=ii('real_estate_assets')
        p.financial_assets=ii('financial_assets'); p.car_value=ii('car_value')
        p.savings_period_months=ii('savings_period_months')
        p.savings_payment_count=ii('savings_payment_count')
        p.savings_amount=ii('savings_amount')
        p.prefer_public_sale=ib('prefer_public_sale')
        p.prefer_private_sale=ib('prefer_private_sale')
        p.prefer_public_rental=ib('prefer_public_rental')
        p.prefer_youth_rental=ib('prefer_youth_rental')
        p.check_interval_hours=ii('check_interval_hours',6)
        regions=[r.strip() for r in f.get('preferred_regions','').split(',') if r.strip()]
        p.set_preferred_regions(regions)
        db.session.commit()
        for lst in Listing.query.all():
            lst.is_eligible=eligible(p,lst)
        db.session.commit()
        reschedule(p.check_interval_hours)
        flash('저장됐습니다! 자격이 다시 계산됐습니다.','success')
        return redirect(url_for('profile_page'))

    cur=p.get_preferred_regions() if p else []
    all_regions=['서울','경기','인천','부산','대구','대전','광주','울산','세종','강원','충북','충남','전북','전남','경북','경남','제주']
    region_cbs=''.join(f'<div class="form-check form-check-inline"><input class="form-check-input region-cb" type="checkbox" id="r_{r}" value="{r}" {"checked" if r in cur else ""}><label class="form-check-label" for="r_{r}">{r}</label></div>' for r in all_regions)

    def v(attr,default=''):
        val=getattr(p,attr,default) if p else default
        return str(val) if val is not None else str(default)
    def ck(attr): return 'checked' if (p and getattr(p,attr,False)) else ''
    def sel(attr,val): return 'selected' if (p and getattr(p,attr)==val) else ''

    summary_html=''
    if p:
        for item in eli_summary(p):
            icon='check-circle-fill text-success' if item['ok'] else 'x-circle-fill text-danger'
            summary_html+=f'<div class="d-flex align-items-start mb-2"><i class="bi bi-{icon} me-2 mt-1"></i><div><div class="fw-semibold small">{item["type"]}</div><div class="text-muted" style="font-size:.77rem">{item["cond"]}</div></div></div>'
    if not summary_html: summary_html='<div class="text-muted small">정보를 입력하면 자격 예측이 표시됩니다.</div>'
    total_assets_val=fmt(p.total_assets) if p else '0'
    interval_opts=''.join(f'<option value="{h}" {"selected" if (p and p.check_interval_hours==h) else ""}>{h}시간마다</option>' for h in [1,2,3,6,12,24])
    pref_val=','.join(cur)

    content=f'''
<div class="row">
<div class="col-lg-8">
<h4 class="fw-bold mb-1"><i class="bi bi-person-circle me-2"></i>내 정보 입력</h4>
<p class="text-muted mb-4">소득·자산 정보를 입력하면 자격이 자동 계산됩니다.</p>
<form method="post">
<div class="card mb-4 shadow-sm"><div class="card-header fw-semibold bg-primary text-white"><i class="bi bi-person me-2"></i>기본 정보</div><div class="card-body"><div class="row g-3">
  <div class="col-md-3"><label class="form-label">이름</label><input type="text" class="form-control" name="name" value="{v('name','나')}"></div>
  <div class="col-md-3"><label class="form-label">나이 *</label><input type="number" class="form-control" name="age" min="18" max="80" value="{v('age',25)}" required></div>
  <div class="col-md-3"><label class="form-label">혼인 상태</label><select class="form-select" name="marital_status"><option value="single" {sel('marital_status','single')}>미혼</option><option value="married" {sel('marital_status','married')}>기혼</option></select></div>
  <div class="col-md-3"><label class="form-label">세대원 수</label><input type="number" class="form-control" name="family_count" min="1" max="10" value="{v('family_count',1)}"></div>
  <div class="col-md-6"><div class="form-check mt-3"><input class="form-check-input" type="checkbox" name="has_children" id="hc" {ck('has_children')}><label class="form-check-label" for="hc">자녀 있음</label></div></div>
  <div class="col-md-6"><label class="form-label">자녀 수</label><input type="number" class="form-control" name="children_count" min="0" value="{v('children_count',0)}"></div>
</div></div></div>

<div class="card mb-4 shadow-sm"><div class="card-header fw-semibold bg-warning text-dark"><i class="bi bi-house me-2"></i>주택 보유</div><div class="card-body"><div class="row g-3">
  <div class="col-md-6"><div class="form-check form-switch"><input class="form-check-input" type="checkbox" name="has_house" id="hh" {ck('has_house')}><label for="hh">본인 주택 보유</label></div><small class="text-danger">주택 보유 시 대부분 자격 없음</small></div>
  <div class="col-md-6"><div class="form-check form-switch"><input class="form-check-input" type="checkbox" name="family_has_house" id="fhh" {ck('family_has_house')}><label for="fhh">세대원 주택 보유</label></div></div>
</div></div></div>

<div class="card mb-4 shadow-sm"><div class="card-header fw-semibold bg-info text-white"><i class="bi bi-cash-coin me-2"></i>월 소득 (세전)</div><div class="card-body"><div class="row g-3">
  <div class="col-md-6"><div class="input-group"><input type="number" class="form-control" name="monthly_income" min="0" value="{v('monthly_income',0)}" placeholder="예: 250"><span class="input-group-text">만원/월</span></div><div class="form-text">가구 전체 합산</div></div>
  <div class="col-md-6"><div class="p-2 bg-light rounded small">2024 도시근로자 월평균소득<br>1인:348만 · 2인:487만 · 3인:602만</div></div>
</div></div></div>

<div class="card mb-4 shadow-sm"><div class="card-header fw-semibold bg-secondary text-white"><i class="bi bi-bank me-2"></i>자산</div><div class="card-body"><div class="row g-3">
  <div class="col-md-4"><label class="form-label">부동산 자산</label><div class="input-group"><input type="number" class="form-control asset-inp" name="real_estate_assets" min="0" value="{v('real_estate_assets',0)}"><span class="input-group-text">만원</span></div></div>
  <div class="col-md-4"><label class="form-label">금융 자산</label><div class="input-group"><input type="number" class="form-control asset-inp" name="financial_assets" min="0" value="{v('financial_assets',0)}"><span class="input-group-text">만원</span></div></div>
  <div class="col-md-4"><label class="form-label">자동차 가액</label><div class="input-group"><input type="number" class="form-control asset-inp" name="car_value" min="0" value="{v('car_value',0)}"><span class="input-group-text">만원</span></div></div>
  <div class="col-12"><div class="alert alert-secondary mb-0 py-2">총 자산: <strong id="tot">{total_assets_val}만원</strong> <small class="text-muted ms-2">(청년특공 기준 3.61억 이하)</small></div></div>
</div></div></div>

<div class="card mb-4 shadow-sm"><div class="card-header fw-semibold"><i class="bi bi-piggy-bank me-2"></i>청약통장</div><div class="card-body"><div class="row g-3">
  <div class="col-md-4"><label class="form-label">가입 기간</label><div class="input-group"><input type="number" class="form-control" name="savings_period_months" min="0" value="{v('savings_period_months',0)}"><span class="input-group-text">개월</span></div></div>
  <div class="col-md-4"><label class="form-label">납입 횟수</label><div class="input-group"><input type="number" class="form-control" name="savings_payment_count" min="0" value="{v('savings_payment_count',0)}"><span class="input-group-text">회</span></div></div>
  <div class="col-md-4"><label class="form-label">납입 총액</label><div class="input-group"><input type="number" class="form-control" name="savings_amount" min="0" value="{v('savings_amount',0)}"><span class="input-group-text">만원</span></div></div>
</div></div></div>

<div class="card mb-4 shadow-sm"><div class="card-header fw-semibold bg-success text-white"><i class="bi bi-geo-alt me-2"></i>선호 지역 & 유형</div><div class="card-body">
  <label class="form-label">선호 지역 <small class="text-muted">(미선택 시 전국)</small></label>
  <div class="d-flex flex-wrap gap-2 mb-3">{region_cbs}</div>
  <input type="hidden" name="preferred_regions" id="pref_r" value="{pref_val}">
  <hr><label class="form-label">선호 유형</label><div class="row g-2">
    <div class="col-6 col-md-3"><div class="form-check form-switch"><input class="form-check-input" type="checkbox" name="prefer_public_sale" id="pp1" {ck('prefer_public_sale')}><label for="pp1">공공분양</label></div></div>
    <div class="col-6 col-md-3"><div class="form-check form-switch"><input class="form-check-input" type="checkbox" name="prefer_private_sale" id="pp2" {ck('prefer_private_sale')}><label for="pp2">민간분양</label></div></div>
    <div class="col-6 col-md-3"><div class="form-check form-switch"><input class="form-check-input" type="checkbox" name="prefer_public_rental" id="pp3" {ck('prefer_public_rental')}><label for="pp3">공공임대</label></div></div>
    <div class="col-6 col-md-3"><div class="form-check form-switch"><input class="form-check-input" type="checkbox" name="prefer_youth_rental" id="pp4" {ck('prefer_youth_rental')}><label for="pp4">청년임대</label></div></div>
  </div>
</div></div>

<div class="card mb-4 shadow-sm"><div class="card-header fw-semibold"><i class="bi bi-clock me-2"></i>자동 수집 주기</div><div class="card-body"><div class="col-md-4"><select class="form-select" name="check_interval_hours">{interval_opts}</select></div></div></div>

<div class="d-flex gap-2"><button type="submit" class="btn btn-primary btn-lg"><i class="bi bi-save me-2"></i>저장</button><a href="/" class="btn btn-outline-secondary btn-lg">취소</a></div>
</form>
</div>
<div class="col-lg-4 mt-4 mt-lg-0">
<div class="card shadow-sm sticky-top" style="top:80px"><div class="card-header fw-semibold"><i class="bi bi-clipboard-check me-2"></i>현재 자격 예측</div>
<div class="card-body">{summary_html}<hr><small class="text-muted">참고용. 실제 자격은 공고문 확인 필요.</small></div></div>
</div></div>'''

    scripts='<script>document.querySelectorAll(".asset-inp").forEach(el=>el.addEventListener("input",()=>{let s=0;document.querySelectorAll(".asset-inp").forEach(e=>s+=parseInt(e.value||0));document.getElementById("tot").textContent=s.toLocaleString("ko-KR")+"만원";}));document.querySelectorAll(".region-cb").forEach(cb=>cb.addEventListener("change",()=>{document.getElementById("pref_r").value=[...document.querySelectorAll(".region-cb:checked")].map(c=>c.value).join(",");}));</script>'
    return render_template_string(page('/profile', content, scripts))

@app.route('/settings', methods=['GET','POST'])
def settings_page():
    p=UserProfile.query.first()
    if request.method=='POST':
        key=request.form.get('kakao_rest_api_key','').strip()
        if key: p.kakao_rest_api_key=key; db.session.commit()
        flash('REST API 키가 저장됐습니다. 카카오 로그인해주세요.','info')
        return redirect(url_for('settings_page'))
    kakao_url=ka_url(p.kakao_rest_api_key) if p and p.kakao_rest_api_key else None
    tok_ok=ka_verify(p.kakao_access_token) if p and p.kakao_access_token else False
    status_html=f'<i class="bi bi-check-circle-fill text-success fs-2 me-3"></i><div><div class="fw-bold text-success">카카오톡 연동 완료</div><div class="text-muted small">청약 알림을 받을 준비가 됐습니다.</div></div><button id="testBtn" class="btn btn-sm btn-outline-success ms-auto"><i class="bi bi-send me-1"></i>테스트 전송</button>' if tok_ok else '<i class="bi bi-exclamation-circle-fill text-warning fs-2 me-3"></i><div><div class="fw-bold text-warning">카카오톡 미연동</div><div class="text-muted small">아래 단계를 따라 연동해주세요.</div></div>'
    login_btn=f'<a href="{kakao_url}" class="btn btn-warning btn-lg"><i class="bi bi-chat-fill me-2"></i>카카오 로그인 (권한 허용)</a><div class="form-text mt-2"><strong>카카오톡 메시지 전송</strong> 권한을 허용해주세요.</div>' if kakao_url else '<div class="text-muted">REST API 키를 먼저 저장해주세요.</div>'
    api_val=p.kakao_rest_api_key if p and p.kakao_rest_api_key else ''

    content=f'''
<h4 class="fw-bold mb-1"><i class="bi bi-gear me-2"></i>카카오톡 알림 설정</h4>
<p class="text-muted mb-4">연동하면 자격이 되는 청약이 올라올 때 카카오톡으로 알림을 받습니다.</p>
<div class="row"><div class="col-lg-7">
<div class="card mb-4 shadow-sm"><div class="card-body d-flex align-items-center">{status_html}</div></div>
<div class="card mb-4 shadow-sm"><div class="card-header fw-semibold"><span class="badge bg-primary me-2">1단계</span>REST API 키 입력</div><div class="card-body"><form method="post"><div class="input-group"><input type="text" class="form-control font-monospace" name="kakao_rest_api_key" value="{api_val}" placeholder="REST API 키 붙여넣기"><button class="btn btn-primary">저장</button></div><div class="form-text"><a href="https://developers.kakao.com" target="_blank">developers.kakao.com</a> → 내 애플리케이션 → 앱 키 → REST API 키</div></form></div></div>
<div class="card mb-4 shadow-sm"><div class="card-header fw-semibold"><span class="badge bg-primary me-2">2단계</span>카카오 로그인</div><div class="card-body">{login_btn}</div></div>
</div><div class="col-lg-5 mt-4 mt-lg-0">
<div class="card shadow-sm"><div class="card-header fw-semibold"><i class="bi bi-question-circle me-2"></i>앱 설정 방법</div><div class="card-body small"><ol class="mb-0">
<li class="mb-1"><a href="https://developers.kakao.com" target="_blank">developers.kakao.com</a> 로그인 → <strong>내 애플리케이션 → 추가</strong></li>
<li class="mb-1">플랫폼 → Web: <code>http://localhost:5000</code></li>
<li class="mb-1">카카오 로그인 활성화 ON</li>
<li class="mb-1">Redirect URI: <code>http://localhost:5000/kakao/callback</code></li>
<li class="mb-1">동의항목 → <strong>카카오톡 메시지 전송</strong> 선택동의</li>
<li class="mb-1">앱 키 → REST API 키 복사 후 위에 입력</li>
<li>카카오 로그인 버튼 클릭 → 완료!</li>
</ol></div></div>
</div></div>
<div id="testResult" class="mt-3"></div>'''

    scripts='<script>const b=document.getElementById("testBtn");if(b)b.addEventListener("click",async()=>{b.disabled=true;b.textContent="전송 중...";const r=await fetch("/kakao/test",{method:"POST"});const d=await r.json();document.getElementById("testResult").innerHTML=`<div class="alert alert-${d.ok?"success":"danger"}">${d.msg}</div>`;b.disabled=false;b.innerHTML="<i class=\'bi bi-send me-1\'></i>테스트 전송";});</script>'
    return render_template_string(page('/settings', content, scripts))

@app.route('/kakao/callback')
def kakao_callback():
    code=request.args.get('code'); error=request.args.get('error')
    if error: flash(f'카카오 로그인 취소: {error}','warning'); return redirect(url_for('settings_page'))
    p=UserProfile.query.first()
    data=ka_exchange(p.kakao_rest_api_key, code)
    if data:
        p.kakao_access_token=data['access_token']; p.kakao_refresh_token=data.get('refresh_token','')
        db.session.commit(); flash('카카오 로그인 성공!','success')
    else:
        flash('카카오 로그인 실패. API 키를 확인해주세요.','danger')
    return redirect(url_for('settings_page'))

@app.route('/kakao/test', methods=['POST'])
def kakao_test():
    p=UserProfile.query.first()
    if not p or not p.kakao_access_token: return jsonify({'ok':False,'msg':'카카오 로그인이 필요합니다.'})
    ok=ka_send(p.kakao_access_token,{'title':'청약알리미 테스트','listing_type':'테스트','region':'서울','district':'서울시','application_start':'2025-01-01','application_end':'2025-01-07','detail_url':'https://www.apt2you.com'})
    return jsonify({'ok':ok,'msg':'전송 성공!' if ok else '전송 실패. 토큰 확인 필요.'})

@app.route('/check/now', methods=['POST'])
def check_now():
    run_check(); flash('수집 완료!','success'); return redirect(url_for('index'))

@app.route('/listings/clear', methods=['POST'])
def clear_listings():
    Listing.query.delete(); db.session.commit(); flash('목록 초기화됐습니다.','info'); return redirect(url_for('index'))

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__=='__main__':
    with app.app_context():
        db.create_all()
        if UserProfile.query.count()==0:
            db.session.add(UserProfile()); db.session.commit(); log.info('기본 프로필 생성')
    with app.app_context():
        p=UserProfile.query.first()
    reschedule(p.check_interval_hours if p else 6)
    scheduler.start()
    log.info('청약알리미 시작 - http://localhost:5000')
    try: app.run(debug=False, host='0.0.0.0', port=5000, use_reloader=False)
    finally: scheduler.shutdown()
