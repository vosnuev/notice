# Cheongak Alimi (청약알리미)

> A self-hosted Flask web app that scrapes Korean public housing subscription notices, checks your eligibility, and sends matched listings to you via KakaoTalk. (내 청약 자격에 맞는 공고를 자동 수집하고 카카오톡으로 알림을 보내주는 로컬 웹 앱)

---

## 🛠️ Tech Stack (기술 스택)

| Layer | Library / Tool |
|---|---|
| Web framework | Flask 3.x |
| ORM / DB | Flask-SQLAlchemy + SQLite |
| Scheduler | APScheduler (BackgroundScheduler) |
| Scraping | requests + BeautifulSoup4 |
| Notification | Kakao Talk "나에게 보내기" API |
| Runtime | Python ≥ 3.14, uv |
| Platform | Windows (install.bat / run.bat) |

---

## ✨ Features (주요 기능)

- **Multi-source scraping** — collects notices from 5 sources on a configurable interval (기본 6시간):
  - 청약홈 (APT2you) — apartment & officetel listings
  - LH청약센터 — public rental, youth jeonse, happy housing
  - SH서울주택공사 — Seoul public housing
  - 마이홈포털 (국토부) — public rental
  - 서울시 청년안심주택 (SOCO) — Seoul youth-safe housing
- **Eligibility engine** — evaluates each listing against your profile (age, income vs. urban-worker median, assets, house-ownership,청약통장 period, preferred regions & types)
- **KakaoTalk push notification** — sends a feed-type message with listing details and a link whenever an eligible notice appears
- **Web dashboard** — Bootstrap 5 UI with stat cards, eligible-listing cards, and a full listing table with inline eligibility badges
- **Profile page** — enter income, assets, 청약통장 info, preferred regions/types; eligibility is recalculated live
- **KakaoTalk settings page** — step-by-step OAuth2 setup (REST API key → login → token auto-refresh)
- **Duplicate prevention** — MD5-keyed deduplication across scrape runs

---

## 📁 Project Structure (프로젝트 구조)

```
notice/
├── app.py              # Single-file Flask app (models, scraper, eligibility, routes, scheduler)
├── scraper.py          # Standalone scraper module (5 sources)
├── eligibility.py      # Eligibility check engine (standalone, mirrors logic in app.py)
├── models.py           # SQLAlchemy models (UserProfile, Listing, NotificationLog)
├── kakao.py            # KakaoTalk OAuth2 + send module
├── main.py             # Entry stub (prints hello)
├── requirements.txt    # pip dependencies
├── pyproject.toml      # uv/PEP 517 project config
├── install.bat         # One-shot install: copies files to C:\cheongak, runs uv sync + app
├── run.bat             # Re-launch shortcut (uv run app.py)
├── templates/
│   ├── base.html       # Jinja2 base layout
│   ├── index.html      # Dashboard
│   ├── profile.html    # Profile / eligibility form
│   └── settings.html   # KakaoTalk setup
└── static/
    └── css/            # Custom CSS
```

> **Note:** `app.py` is a self-contained single-file version that inlines the models, scraper, eligibility, and Kakao logic. The sibling modules (`scraper.py`, `eligibility.py`, `models.py`, `kakao.py`) are the modular equivalents.

---

## 🔄 Usage Flow (사용 흐름)

```
[Start app]
    │
    ├─► Create default UserProfile in SQLite (~/cheongak_data/cheongak.db)
    │
    ├─► APScheduler runs scrape_all() every N hours
    │       └─► 5 scrapers → deduplicate → save new Listing rows
    │               └─► eligibility check against UserProfile
    │                       └─► if eligible + KakaoTalk connected → send feed message
    │
    └─► User opens http://localhost:5000
            ├─► Dashboard: stat cards + eligible listings + full table
            ├─► /profile: fill in personal / financial info → recalculates eligibility
            └─► /settings: enter Kakao REST API key → OAuth2 login → token stored in DB
```

---

## 🏗️ Architecture (아키텍처)

```
┌─────────────────────────────────────────────────────────┐
│  Flask app (app.py)                                     │
│                                                         │
│  Routes          Models (SQLite)   Scheduler            │
│  /               UserProfile       APScheduler          │
│  /profile    ◄── Listing       ◄── run_check()          │
│  /settings       NotifLog          every N hours        │
│  /check/now                                             │
│  /kakao/*                                               │
│                                                         │
│  Scraper                  Eligibility engine            │
│  scrape_apt2you()         eligible(profile, listing)    │
│  scrape_lh()              eli_summary(profile)          │
│  scrape_sh()                                            │
│  scrape_myhome()          KakaoTalk                     │
│  scrape_soco_youth()      ka_send(token, listing)       │
└─────────────────────────────────────────────────────────┘
         │ HTTP scraping                │ Kakao API
         ▼                             ▼
  청약홈 / LH / SH /           kapi.kakao.com
  마이홈 / SOCO                나에게 보내기
```

**Data directory** (created automatically): `~/cheongak_data/`
- `cheongak.db` — SQLite database
- `cheongak.log` — application log

---

## ⚙️ Environment Setup (환경 설정)

### Prerequisites

- Python ≥ 3.14
- [uv](https://docs.astral.sh/uv/) package manager

### KakaoTalk notification (optional)

1. Go to [developers.kakao.com](https://developers.kakao.com) → create an app
2. Platform → Web → add `http://localhost:5000`
3. Kakao Login → activate → add Redirect URI: `http://localhost:5000/kakao/callback`
4. Consent items → enable **카카오톡 메시지 전송** (talk_message)
5. Copy the **REST API key** — you will paste it in the `/settings` page

---

## 🚀 How to Run (실행 방법)

### First-time install (Windows)

```bat
install.bat
```

This copies all project files to `C:\cheongak`, runs `uv sync`, and starts the app.

### Subsequent runs

```bat
run.bat
```

or manually:

```bash
uv run app.py
```

Then open **http://localhost:5000** in your browser.

### Manual install (non-Windows / uv already set up)

```bash
# clone or download the repo
pip install -r requirements.txt   # or: uv sync
python app.py
```

---

## 📄 License & References (라이선스 & 참고 문서)

- [청약홈 (APT2you)](https://www.applyhome.co.kr)
- [LH청약센터](https://apply.lh.or.kr)
- [SH서울주택공사](https://www.i-sh.co.kr)
- [마이홈포털](https://www.myhome.go.kr)
- [서울시 청년안심주택](https://soco.seoul.go.kr/youth/bbs/BMSR00015/list.do?menuNo=400008)
- [카카오 Developers](https://developers.kakao.com)

> Scraping targets are Korean government and public housing portals. Site structure may change; update URL/parsing logic in `scraper.py` or `app.py` accordingly.
