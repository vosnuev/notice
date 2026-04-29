"""
청약알리미 - 데이터베이스 모델
"""
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import json

db = SQLAlchemy()


class UserProfile(db.Model):
    """사용자 프로필 - 청약 자격 판별에 사용"""
    __tablename__ = 'user_profile'

    id = db.Column(db.Integer, primary_key=True)

    # ── 기본 정보 ──
    name = db.Column(db.String(50), default='나')
    age = db.Column(db.Integer, default=25)
    marital_status = db.Column(db.String(20), default='single')   # single | married
    has_children = db.Column(db.Boolean, default=False)
    children_count = db.Column(db.Integer, default=0)
    family_count = db.Column(db.Integer, default=1)                # 세대원 수 (본인 포함)

    # ── 주택 보유 ──
    has_house = db.Column(db.Boolean, default=False)               # 본인 주택 보유 여부
    family_has_house = db.Column(db.Boolean, default=False)        # 세대원 주택 보유 여부

    # ── 소득 (단위: 만원/월) ──
    monthly_income = db.Column(db.Integer, default=0)              # 월 소득

    # ── 자산 (단위: 만원) ──
    real_estate_assets = db.Column(db.Integer, default=0)          # 부동산 자산
    financial_assets = db.Column(db.Integer, default=0)            # 금융 자산
    car_value = db.Column(db.Integer, default=0)                   # 자동차 가액

    # ── 청약통장 ──
    savings_period_months = db.Column(db.Integer, default=0)       # 가입기간 (개월)
    savings_payment_count = db.Column(db.Integer, default=0)       # 납입 횟수
    savings_amount = db.Column(db.Integer, default=0)              # 납입 총액 (만원)

    # ── 선호 지역 (JSON 배열: ["서울", "경기", "인천", ...]) ──
    preferred_regions = db.Column(db.Text, default='[]')

    # ── 선호 청약 유형 ──
    prefer_public_sale = db.Column(db.Boolean, default=True)       # 공공분양
    prefer_private_sale = db.Column(db.Boolean, default=True)      # 민간분양
    prefer_public_rental = db.Column(db.Boolean, default=True)     # 공공임대
    prefer_youth_rental = db.Column(db.Boolean, default=True)      # 청년임대/행복주택

    # ── 카카오톡 설정 ──
    kakao_rest_api_key = db.Column(db.String(200))
    kakao_access_token = db.Column(db.String(1000))
    kakao_refresh_token = db.Column(db.String(1000))
    kakao_token_expires_at = db.Column(db.DateTime)

    # ── 공공데이터 API 키 (선택) ──
    public_data_api_key = db.Column(db.String(500))

    # ── 스케줄 설정 ──
    check_interval_hours = db.Column(db.Integer, default=6)        # 확인 주기 (시간)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # ── 헬퍼 ──
    def get_preferred_regions(self):
        try:
            return json.loads(self.preferred_regions or '[]')
        except Exception:
            return []

    def set_preferred_regions(self, regions: list):
        self.preferred_regions = json.dumps(regions, ensure_ascii=False)

    @property
    def total_assets(self):
        return (self.real_estate_assets or 0) + (self.financial_assets or 0) + (self.car_value or 0)

    @property
    def annual_income(self):
        return (self.monthly_income or 0) * 12

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'age': self.age,
            'marital_status': self.marital_status,
            'has_children': self.has_children,
            'children_count': self.children_count,
            'family_count': self.family_count,
            'has_house': self.has_house,
            'family_has_house': self.family_has_house,
            'monthly_income': self.monthly_income,
            'real_estate_assets': self.real_estate_assets,
            'financial_assets': self.financial_assets,
            'car_value': self.car_value,
            'total_assets': self.total_assets,
            'savings_period_months': self.savings_period_months,
            'savings_payment_count': self.savings_payment_count,
            'savings_amount': self.savings_amount,
            'preferred_regions': self.get_preferred_regions(),
            'prefer_public_sale': self.prefer_public_sale,
            'prefer_private_sale': self.prefer_private_sale,
            'prefer_public_rental': self.prefer_public_rental,
            'prefer_youth_rental': self.prefer_youth_rental,
            'check_interval_hours': self.check_interval_hours,
        }


class Listing(db.Model):
    """청약 공고 목록"""
    __tablename__ = 'listings'

    id = db.Column(db.Integer, primary_key=True)
    listing_key = db.Column(db.String(300), unique=True, nullable=False)  # 중복 방지용 고유키

    # ── 공고 기본 정보 ──
    title = db.Column(db.String(500))
    source = db.Column(db.String(50))         # 청약홈 | LH | SH | 청년
    listing_type = db.Column(db.String(50))   # 공공분양 | 민간분양 | 공공임대 | 행복주택 | 청년임대

    # ── 위치 ──
    region = db.Column(db.String(100))        # 시/도
    district = db.Column(db.String(100))      # 시/군/구
    address = db.Column(db.String(500))

    # ── 공급 정보 ──
    total_supply = db.Column(db.Integer, default=0)

    # ── 일정 ──
    application_start = db.Column(db.String(20))
    application_end = db.Column(db.String(20))
    winner_announce = db.Column(db.String(20))

    # ── 자격 기준 ──
    income_limit_pct = db.Column(db.Integer)   # 도시근로자 월평균소득 기준 % (예: 100, 120, 140)
    asset_limit_man = db.Column(db.Integer)    # 자산 상한 (만원)
    min_age = db.Column(db.Integer)
    max_age = db.Column(db.Integer)
    marital_required = db.Column(db.String(20))  # any | single | married

    # ── 링크 ──
    detail_url = db.Column(db.String(1000))

    # ── 원본 데이터 (JSON) ──
    raw_data = db.Column(db.Text)

    # ── 처리 상태 ──
    is_eligible = db.Column(db.Boolean, default=False)
    notified = db.Column(db.Boolean, default=False)

    scraped_at = db.Column(db.DateTime, default=datetime.utcnow)

    def get_raw(self):
        try:
            return json.loads(self.raw_data or '{}')
        except Exception:
            return {}

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'source': self.source,
            'listing_type': self.listing_type,
            'region': self.region,
            'district': self.district,
            'address': self.address,
            'total_supply': self.total_supply,
            'application_start': self.application_start,
            'application_end': self.application_end,
            'winner_announce': self.winner_announce,
            'income_limit_pct': self.income_limit_pct,
            'asset_limit_man': self.asset_limit_man,
            'min_age': self.min_age,
            'max_age': self.max_age,
            'detail_url': self.detail_url,
            'is_eligible': self.is_eligible,
            'notified': self.notified,
            'scraped_at': self.scraped_at.strftime('%Y-%m-%d %H:%M') if self.scraped_at else '',
        }


class NotificationLog(db.Model):
    """카카오톡 알림 발송 이력"""
    __tablename__ = 'notification_log'

    id = db.Column(db.Integer, primary_key=True)
    listing_id = db.Column(db.Integer, db.ForeignKey('listings.id'))
    listing_title = db.Column(db.String(500))
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)
    success = db.Column(db.Boolean, default=True)
    error_msg = db.Column(db.String(500))
