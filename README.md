# 수원시 도서관 캠핑장 예약 자동화 봇

**대상 사이트:** https://www.suwonlib.go.kr/reserve/camping/campingApplySimple.do

매월 1일 오전 **10:00 KST** 에 예약이 열리는 수원시 도서관 캠핑장을 자동 예약하고,
결과(성공/실패)를 **Telegram** 으로 알려주는 Docker 기반 Python 봇입니다.

---

## 기술 스택

| 항목 | 선택 | 이유 |
|---|---|---|
| 언어 | Python 3.12 | 풍부한 자동화 생태계 |
| 브라우저 자동화 | **Playwright** (Selenium 아님) | JS 렌더링, async/await, WAF 우회에 유리 |
| WAF 우회 | playwright-stealth | navigator.webdriver 등 ~20개 탐지 벡터 패치 |
| 알림 | python-telegram-bot v21 | 무료, 설정 간단 |
| 컨테이너 | Docker + docker-compose | 환경 격리, 이식성 |

---

## 실행 흐름

```
컨테이너 시작
 ├─ .env 로드 & 검증 (필수 변수 누락 시 즉시 종료)
 ├─ Telegram: "봇 시작, X월 1일 10:00 대기중" 전송
 ├─ 다음 예약 오픈 시각까지 절전 대기
 │    Phase 1: 30분 단위 coarse sleep (CPU 효율)
 │    Phase 2: 마지막 5초 → 10 ms tight-loop (±10 ms 정밀도)
 ├─ [10:00 - 30초] 브라우저(Chromium) 시작 + 로그인
 ├─ 예약 페이지 미리 로드 (hot state)
 ├─ 정확히 10:00:00 에 예약 시도 시작
 │    최대 MAX_RETRIES 횟수 재시도
 │    성공 → Telegram 성공 알림 + 종료
 │    실패 → RETRY_DELAY_SECONDS 후 재시도
 └─ 전체 실패 → Telegram 실패 알림 + 스크린샷 첨부 + 종료
```

---

## 빠른 시작

### 1. 환경변수 설정

```bash
cp .env.example .env
```

`.env` 파일을 열고 아래 항목을 반드시 채워야 합니다:

| 변수 | 설명 |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Telegram 봇 토큰 (아래 설정 방법 참고) |
| `TELEGRAM_CHAT_ID` | 알림 받을 채팅 ID |
| `SUWON_USERNAME` | 수원시 도서관 회원 ID |
| `SUWON_PASSWORD` | 수원시 도서관 비밀번호 |
| `CAMPING_DATE` | 캠핑 희망 날짜 (예: `2026-03-15`) |
| `CAMPSITE_NAME` | 희망 구역명 (예: `A구역`) |

### 2. Docker 이미지 빌드

```bash
docker compose build
```

### 3. 봇 실행

```bash
docker compose up
```

봇은 다음 달 1일 오전 10시까지 대기 후 자동으로 예약을 시도합니다.

### 4. 로그 확인

```bash
docker logs camping_reservation_bot -f
```

### 5. 스크린샷 확인

실패 시 스크린샷이 `./screenshots/` 디렉토리에 저장됩니다.

---

## Telegram 봇 설정 방법

1. Telegram에서 **@BotFather** 에 접속
2. `/newbot` 명령 실행 → 봇 이름 입력 → **토큰** 복사
3. `.env`의 `TELEGRAM_BOT_TOKEN`에 붙여넣기
4. 생성한 봇에게 메시지 한 번 전송 (활성화 목적)
5. 아래 URL에서 `chat.id` 값 확인:
   ```
   https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
   ```
6. `.env`의 `TELEGRAM_CHAT_ID`에 입력

---

## 선택자(Selectors) 업데이트 방법

사이트 HTML 구조가 변경되면 `src/reservation.py`의 `SELECTORS` 딕셔너리를 업데이트해야 합니다.

1. 브라우저에서 예약 페이지 열기
2. F12 → Elements 탭
3. 아래 필드의 `name`, `id`, `class` 속성 확인:
   - 로그인 ID/PW 입력 필드
   - 날짜 입력 필드
   - 구역 선택 `<select>`
   - 인원 입력 필드
   - 신청 버튼
   - 성공/오류 메시지 컨테이너
4. `SELECTORS` 딕셔너리 수정 후 재빌드: `docker compose build`

---

## 설정 옵션 전체 목록

| 변수 | 기본값 | 설명 |
|---|---|---|
| `MAX_RETRIES` | `10` | 최대 재시도 횟수 |
| `RETRY_DELAY_SECONDS` | `1` | 재시도 간격 (초) |
| `PRE_POSITION_SECONDS` | `30` | 10시 전 브라우저 시작 여유 시간 |
| `HEADLESS` | `false` | `true` = 헤드리스 모드 |
| `SCREENSHOT_DIR` | `/app/screenshots` | 컨테이너 내 스크린샷 경로 |

---

## 주의사항

- 이 봇은 **개인 사용 목적**으로 제작되었습니다.
- 예약 오픈 시각, 폼 구조는 사이트 업데이트로 변경될 수 있으므로 정기적으로 확인하세요.
- 봇 실행 전 `.env`의 `CAMPING_DATE`와 `CAMPSITE_NAME`을 해당 월의 원하는 값으로 업데이트하세요.
