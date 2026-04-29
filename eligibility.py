"""
청약알리미 - 청약 자격 판별 엔진

[ 2024년 기준 도시근로자 월평균소득 ]
  1인 가구 : 3,482,964원
  2인 가구 : 4,867,903원
  3인 가구 : 6,024,638원
  4인 가구 : 6,891,891원
  5인 가구 : 7,254,237원
매년 변경될 수 있으므로 URBAN_WORKER_INCOME 딕셔너리를 직접 수정하세요.
"""

# ── 도시근로자 월평균소득 (원 단위) ──────────────────────────────────────
URBAN_WORKER_INCOME = {
    1: 3_482_964,
    2: 4_867_903,
    3: 6_024_638,
    4: 6_891_891,
    5: 7_254_237,
}

def get_urban_income(family_count: int) -> int:
    """세대원 수에 따른 도시근로자 월평균소득 반환 (원)"""
    count = max(1, min(family_count, 5))
    return URBAN_WORKER_INCOME[count]


# ── 자격 판별 메인 함수 ───────────────────────────────────────────────────

def check_eligibility(profile, listing) -> dict:
    """
    profile  : UserProfile 모델 인스턴스
    listing  : Listing 모델 인스턴스
    반환값   : {'eligible': bool, 'reasons': [통과 이유], 'fails': [탈락 이유]}
    """
    reasons = []
    fails   = []

    ltype = (listing.listing_type or '').strip()

    # ── 0. 선호 유형 체크 ────────────────────────────────────────────────
    if not _type_preferred(profile, ltype):
        fails.append(f"선호 유형이 아님 ({ltype})")
        return {'eligible': False, 'reasons': reasons, 'fails': fails}

    # ── 1. 선호 지역 체크 ───────────────────────────────────────────────
    preferred = profile.get_preferred_regions()
    if preferred:
        region_ok = any(r in (listing.region or '') for r in preferred)
        if region_ok:
            reasons.append(f"선호 지역 ({listing.region})")
        else:
            fails.append(f"선호 지역 아님 ({listing.region})")
            return {'eligible': False, 'reasons': reasons, 'fails': fails}

    # ── 2. 무주택 체크 ──────────────────────────────────────────────────
    if profile.has_house or profile.family_has_house:
        fails.append("주택 보유 세대 (무주택 요건 미충족)")
        return {'eligible': False, 'reasons': reasons, 'fails': fails}
    else:
        reasons.append("무주택 세대 ✓")

    # ── 3. 연령 체크 ────────────────────────────────────────────────────
    age = profile.age or 0
    min_age = listing.min_age
    max_age = listing.max_age
    if min_age and age < min_age:
        fails.append(f"연령 미달 (최소 {min_age}세, 현재 {age}세)")
        return {'eligible': False, 'reasons': reasons, 'fails': fails}
    if max_age and age > max_age:
        fails.append(f"연령 초과 (최대 {max_age}세, 현재 {age}세)")
        return {'eligible': False, 'reasons': reasons, 'fails': fails}
    if min_age or max_age:
        reasons.append(f"연령 조건 충족 ({age}세) ✓")

    # ── 4. 혼인 상태 체크 ───────────────────────────────────────────────
    marital_req = listing.marital_required or 'any'
    if marital_req == 'single' and profile.marital_status != 'single':
        fails.append("미혼 조건 미충족")
        return {'eligible': False, 'reasons': reasons, 'fails': fails}
    if marital_req == 'married' and profile.marital_status != 'married':
        fails.append("기혼 조건 미충족")
        return {'eligible': False, 'reasons': reasons, 'fails': fails}

    # ── 5. 소득 기준 체크 ───────────────────────────────────────────────
    income_limit_pct = listing.income_limit_pct
    if income_limit_pct:
        base_income = get_urban_income(profile.family_count or 1)
        income_limit = base_income * income_limit_pct / 100
        monthly_income_won = (profile.monthly_income or 0) * 10_000  # 만원 → 원

        if monthly_income_won > income_limit:
            fails.append(
                f"소득 초과 (기준 {income_limit_pct}%: {income_limit/10000:.0f}만원, "
                f"내 월소득: {profile.monthly_income}만원)"
            )
            return {'eligible': False, 'reasons': reasons, 'fails': fails}
        else:
            reasons.append(
                f"소득 기준 충족 ({income_limit_pct}%: {income_limit/10000:.0f}만원 이하) ✓"
            )

    # ── 6. 자산 기준 체크 ───────────────────────────────────────────────
    asset_limit_man = listing.asset_limit_man
    if asset_limit_man:
        if profile.total_assets > asset_limit_man:
            fails.append(
                f"자산 초과 (상한 {asset_limit_man:,}만원, "
                f"내 자산: {profile.total_assets:,}만원)"
            )
            return {'eligible': False, 'reasons': reasons, 'fails': fails}
        else:
            reasons.append(f"자산 기준 충족 ({asset_limit_man:,}만원 이하) ✓")

    # ── 7. 청약통장 체크 (공공·민간분양) ────────────────────────────────
    if ltype in ('공공분양', '민간분양'):
        if profile.savings_period_months < 6:
            fails.append(
                f"청약통장 가입 기간 부족 ({profile.savings_period_months}개월, 최소 6개월)"
            )
            return {'eligible': False, 'reasons': reasons, 'fails': fails}
        else:
            reasons.append(f"청약통장 가입 {profile.savings_period_months}개월 ✓")

    # ── 최종 통과 ────────────────────────────────────────────────────────
    return {'eligible': True, 'reasons': reasons, 'fails': fails}


def _type_preferred(profile, ltype: str) -> bool:
    """선호 유형 여부 확인"""
    mapping = {
        '공공분양': profile.prefer_public_sale,
        '민간분양': profile.prefer_private_sale,
        '공공임대': profile.prefer_public_rental,
        '행복주택': profile.prefer_youth_rental,
        '청년임대': profile.prefer_youth_rental,
        '청년전세임대': profile.prefer_youth_rental,
        '청년매입임대': profile.prefer_youth_rental,
    }
    return mapping.get(ltype, True)


def get_eligibility_summary(profile) -> dict:
    """
    프로필만으로 대략적인 자격 가능 유형 요약 반환
    (사전에 어떤 유형에 해당하는지 안내용)
    """
    result = []
    base_income = get_urban_income(profile.family_count or 1)
    monthly_won = (profile.monthly_income or 0) * 10_000
    total_assets = profile.total_assets

    # 청년 특별공급 (공공분양)
    if 19 <= (profile.age or 0) <= 39 and profile.marital_status == 'single':
        if monthly_won <= base_income * 1.4 and total_assets <= 36_100:
            result.append({
                'type': '공공분양 청년 특별공급',
                'condition': f'소득 140% 이하, 순자산 3.61억 이하',
                'ok': True,
            })

    # 행복주택 청년
    if 19 <= (profile.age or 0) <= 39:
        if monthly_won <= base_income * 1.0:
            result.append({
                'type': '행복주택 (청년)',
                'condition': '소득 100% 이하',
                'ok': True,
            })
        else:
            result.append({
                'type': '행복주택 (청년)',
                'condition': f'소득 100% 초과 (기준 {base_income/10000:.0f}만원)',
                'ok': False,
            })

    # 청년 매입·전세임대
    if 19 <= (profile.age or 0) <= 39:
        if monthly_won <= base_income * 1.0:
            result.append({
                'type': '청년 매입/전세임대',
                'condition': '소득 100% 이하',
                'ok': True,
            })

    # 일반공급 (민간분양)
    if profile.savings_period_months >= 6:
        result.append({
            'type': '민간분양 일반공급',
            'condition': f'청약통장 {profile.savings_period_months}개월',
            'ok': True,
        })

    return result
