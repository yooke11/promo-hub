# 프로모션 허브 (promo-hub)

국내 쇼핑몰 **트래픽 상위 50개**(추정 순위, `config/sources.yaml`)의 기획전·이벤트와 **그 안에서 실제 판매 중인 상품(이미지·상품명·판매가·정가·할인율)**을 모아 한 화면에서 보는 플랫폼입니다. 설계는 [DESIGN.md](DESIGN.md)에 있습니다.

화면 구성
- **기획전** 보기: 카드마다 대표 상품 4개를 이미지+가격(또는 텍스트 목록)으로 미리 보기, 카드를 누르면 상세 패널에서 전체 상품을 노출순·낮은 가격·할인율로 정렬
- **상품** 보기: 진행 중 기획전에 담긴 상품 전체를 한 번에. 가격대·할인율·채널·검색으로 거르기
- **타임라인**: 채널별 행사 일정
- 상품 표시는 **이미지 / 텍스트** 전환(선택이 기억됨)

## 운영 중인 서비스

| 구성 | 위치 |
|---|---|
| 웹사이트 | https://promo-hub-one.vercel.app (Vercel · yooke team / promo-hub) |
| DB·API | Supabase 프로젝트 `promo-hub` (서울 리전) — 테이블 sources·promotions·promotion_items·crawl_runs, 화면용 뷰 v_promotions·v_items·v_sources |
| 자동 수집 | GitHub Actions `.github/workflows/collect.yml` — 매일 새벽 5시(한국 시간), 50개 채널을 8묶음으로 병렬 수집 → Supabase `ingest` 함수로 적재 |

보안 구조: 웹은 공개 읽기 전용 키로 **조회만** 합니다(RLS). 쓰기는 `ingest(token, payload)` 함수 하나로만 가능하고, 이 함수는 수집 토큰(해시만 DB에 저장)이 맞을 때만 동작합니다.

### GitHub Actions 연결(최초 1회)
저장소: https://github.com/yooke11/promo-hub (공개 — Actions 무료)
1. Settings → Secrets and variables → Actions → **Secrets** 탭 → New repository secret
   - Name `PROMOHUB_INGEST_TOKEN`, Secret = 따로 전달받은 수집 토큰
   (Supabase 주소·공개 키는 워크플로 파일에 이미 들어 있음)
2. Actions 탭 → collect → Run workflow 로 첫 수집을 바로 실행(이후 매일 새벽 5시 자동).

### 웹 최저가 비교·검색광고 키워드
- 웹 최저가는 에누리 가격비교에서 자동 조회합니다(키 불필요, 하루 400개 상품). 네이버 쇼핑 검색 API는 2026-07-31 종료돼 쓰지 않습니다.
- 검색광고 추천 키워드는 기획전마다 자동 생성됩니다. 월 검색량·경쟁도까지 보려면 네이버 검색광고(searchad.naver.com) → 도구 → API 사용 관리에서 발급한 값을 Secrets에 등록하세요:
  `NAVER_AD_API_KEY`(액세스라이선스), `NAVER_AD_SECRET`(비밀키), `NAVER_AD_CUSTOMER_ID`(CUSTOMER_ID)

### 해외 IP 차단 대비
GitHub Actions 서버는 해외(미국) IP라 일부 국내 쇼핑몰이 접속을 막을 수 있습니다. 특정 채널이 계속 0건이면(사이트 상단 '마지막 수집'·Supabase `crawl_runs` 확인) 그 채널만 사내 PC에서 `scripts/collect_windows.bat --only 채널id` 로 돌리세요. 같은 DB로 올라갑니다.

## 빠른 시작(로컬 개발)

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium

# 1) 채널 하나로 점검 (저장 안 함, 결과만 출력)
python -m promohub.cli probe gmarket
python -m promohub.cli probe musinsa --headed          # 브라우저 창을 띄워서 확인

# 2) 전체 수집 → data/promohub.db
python -m promohub.cli collect
python -m promohub.cli collect --only gmarket,auction,musinsa

# 3) 웹 화면
python -m promohub.cli serve          # http://127.0.0.1:8000
```

API가 없는 상태에서 `web/index.html`을 바로 열면 **샘플 데이터**로 화면이 뜹니다(상단에 샘플 표시).

## 처음 운영할 때 할 일

`config/sources.yaml`의 진입 URL·URL 패턴은 사이트 구조를 기준으로 잡은 초기값입니다. 채널마다 한 번씩 `probe`를 돌려 확인하세요.

- 결과가 0건이면 `--headed`로 실제 화면을 보고, 기획전 배너를 눌렀을 때 주소창 URL을 `include_patterns`에 정규식으로 추가
- 상품 상세 등 엉뚱한 링크가 섞이면 `exclude_patterns`에 추가
- 모바일 메인에 배너가 더 많은 채널은 `mobile: true`
- 기획전은 잡히는데 상품이 0개면 상품 상세 URL을 `product_patterns`에 추가(예: `goodsNo=`, `/products/\d+`)
- 50개 전체 수집은 채널당 기획전 30개 상세 방문 기준 1회 2~4시간 걸립니다. `--only`로 나눠 돌리거나 `detail_limit`을 줄이세요

## 주기 실행

crontab (3시간마다):
```
0 */3 * * * cd /path/promo-hub && .venv/bin/python -m promohub.cli collect >> logs/collect.log 2>&1
```
Windows는 작업 스케줄러에 같은 명령을 등록합니다.

## API

| 엔드포인트 | 설명 |
|---|---|
| `GET /api/promotions` | `source`, `channel_type`, `category`, `kind`, `status`, `q`(상품명 포함), `sort=ending|new|discount`, `limit`, `items_per`(기획전당 상품 수) |
| `GET /api/promotions/{id}/items` | 기획전에 담긴 판매 상품 전체(이미지·이름·판매가·정가·할인율·링크) |
| `GET /api/items` | 진행 중 기획전 상품 검색: `q`, `min_price`, `max_price`, `sort=discount|price|price_desc` |
| `GET /api/sources` | 채널 목록(트래픽 순위 포함) + 마지막 수집 시각·오류 |
| `GET /api/stats` | 상태·채널·카테고리별 건수, 24시간 신규 |

`python -m promohub.cli export out.json`으로 JSON 내보내기.

## 테스트

```bash
pip install pytest && python -m pytest -q
```
정규화(기간·혜택·분류), DOM/JSON 추출, 저장소, 로컬 JS 렌더링 사이트로 Playwright 수집 전 과정(e2e)을 검증합니다.

## 구조

```
config/sources.yaml   채널 정의(진입 URL, URL 패턴)
promohub/collector.py Playwright 수집(스크롤, JSON 가로채기, robots, 상세 보강)
promohub/extract.py   셀렉터 없는 범용 추출(DOM 링크·JSON·og 메타)
promohub/products.py  기획전 속 판매 상품 추출(DOM 상품 카드·상품 API JSON·JSON-LD) + 가격 파싱
promohub/normalize.py 기간 파싱·혜택·카테고리·유형·URL 정규화
promohub/store.py     SQLite 저장(신규/소멸 추적, 수집 이력)
promohub/api.py       FastAPI
web/index.html        웹 화면(카드·타임라인)
```

## 주의

robots.txt를 기본 준수하고 기획전·상품의 제목·기간·가격·이미지 URL·원문 링크만 저장합니다(이미지 파일은 저장하지 않고 원본 링크로 표시). 외부 공개 서비스로 운영하기 전에는 각 채널 이용약관의 자동 수집 조항을 검토하세요(DESIGN.md 6장).
