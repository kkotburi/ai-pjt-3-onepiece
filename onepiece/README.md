# One Piece Watch Planner
로컬 교육용 FastAPI · LangGraph 프로젝트. Python 3.11 이상, Git Bash 기준.
압축을 풀고 main.py가 있는 디렉터리에서 실행한다.

```bash
python -m venv .venv
source .venv/Scripts/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

.env에 OPENAI_API_KEY를 입력한다. GMS를 사용하는 경우 교육기관이 안내한 OpenAI 호환 OPENAI_BASE_URL과 사용 가능한 OPENAI_MODEL도 설정한다. 키를 저장소에 커밋하지 않는다.
```bash
python -m uvicorn main:app --reload
```
화면 http://localhost:8000 · API 스키마 http://localhost:8000/docs. macOS/Linux에서는 .venv/bin/activate를 사용한다.

## 시연

- “나미 첫 등장 편을 19시까지 보려면?”이라고 질문한다. 확인된 러닝타임이 25분이면 늦어도 18:35에 시작해야 한다고 안내한다. 날짜가 없으면 시각만 표시한다. 구체적인 시청 구간을 요청한 뒤 제안된 계획을 저장한다.
- 저장한 계획 목록과 상세에서 생성 일시를 확인한다. ‘계획 수정’에서 회차와 시청 시간을 변경한다. 회차는 양의 정수로 검증하며 수정 시 외부 회차 재조회는 하지 않는다.

1. “로빈이 처음 나온 회차와 시청 시간을 알려줘.” 기존 실호출 기준 기대값은 통산 67화, TVmaze ID 256191, 25분이다.
2. “이번 토요일 18:00~18:20 또는 일요일 19:00~19:30에 그 회차를 볼래.” 일요일 후보와 토요일 제외 사유를 확인하고 계획 저장을 누른다.
3. “토요일에 30분 있어. 다른 캐릭터의 첫 등장 편을 보고 싶어.” 필요한 캐릭터 선택을 확인한다.

## 구현 범위

Tool 등록 명세는 `python -c "from tools_api import SPECS; import json; print(json.dumps(SPECS, ensure_ascii=False, indent=2))"`로 볼 수 있다. 모든 등록 도구는 외부 API 유형이다. 캐릭터 이름 문자열과 ID 객체 중 하나를 전달한다. 검증을 통과하지 못한 입력은 외부 API 호출 없이 `INVALID_INPUT`을 반환한다.
- F3001~04 tools_api.py: 공통 결과 ok/data 또는 ok/error. characters(한글·영문 이름) → ID·영문명 목록, debut(선택한 캐릭터) → 통산 회차·방영일·제목·근거 URL, runtime(회차 조회 결과) → 분·TVmaze ID·근거 URL. 다중 일치나 누락은 확인 실패로 처리한다.
- F3005~11 agent.py: 구조화된 의도 분석, 필요한 도구 선택, 세션별 조건·조회 결과 재사용, Python 시간 판정과 대안 탐색(최초 1회 + 최대 3회), 근거와 응답. 사용자가 제시한 시간대를 한국 시간으로 계산한다.
- F3012~14 store.py: 단계·판단·호출 로그를 세션별 순서대로 SQLite에 보관한다. 로그 목록·상세·삭제만 제공한다.
- F3015~19 main.py, static/: 계획 생성·목록·상세·수정·삭제, 시간 충돌 알림, 대화·진행 이력·로그 화면. 대화 POST /api/chat, 계획 /api/plans, 로그 /api/logs. 실행 중 생성되는 planner.sqlite가 로컬 저장소다. 브라우저 세션 식별은 교육용이며 사용자 인증을 제공하지 않는다.
- Google Calendar OAuth 및 실제 일정 등록은 별도 검증한 심화 F3023 범위다. 이 버전의 저장 버튼은 프로젝트 DB에 저장한다.

## 외부 자료
- 캐릭터: https://www.onepieceapi.com/documentation · 별칭은 이전 프로젝트의 캐릭터 자료에서 이름만 추출했다.
- 첫 등장: https://onepiece.fandom.com/wiki/Nico_Robin · MediaWiki API의 렌더링된 Debut 필드와 개별 회차 문서를 조회한다. 문서 형식 변경 시 실패 코드를 확인한다.
- 시청 시간: https://www.tvmaze.com/api · 작품 ID 1505의 정규 회차 순서·방영일·제목을 대조한다. 연도별 number는 통산 회차가 아니다.

## 캐릭터 검색과 검증
화면 상단의 캐릭터 검색은 모델 키 없이 사용할 수 있다. 검색창에서 전체 한글 이름을 자동완성하며, 한글 부분 이름·별칭과 띄어쓰기 없는 입력도 지원한다. API에는 한국어 필드가 없어 aliases.json의 한국어 표기를 우선하고, 없는 경우 일본어·로마자 독음을 한글로 전사한다. 한국 정식판 번역과 다를 수 있다. 결과에는 한글·원문을 함께 표시하고 동명이인은 ID로 구분한다. 색인에서 찾지 못한 한국어 표기는 기존 위키백과 교차 조회도 시도한다. 선택한 캐릭터 ID로 상세 이름을 다시 확인한다. 첫 등장 필드에서 애니 회차를 찾고 TVmaze에서 원제·영문 제목 또는 일본 방영일을 대조한다. 같은 날 여러 회차가 방영되면 정규 회차의 순서를 대조한다. 날짜가 다르면 제목 근거를 추가로 요구하고 불명확하면 시간을 확정하지 않는다.

자연어 질문과 후속 일정 요청에는 모델 키가 필요하다. 저장된 일정과 겹치면 사용자 허용 구간 안에서 다음 시작 시각을 계산한다. 요청별 진행 이벤트와 계획 상세를 화면에서 확인할 수 있다.

Git Bash에서 의존성 설치 후 다음 검사를 실행한다.

```bash
python verify.py -v
python verify.py --live
python verify.py --model
```

첫 명령은 네트워크 없이 고정 응답으로 검색부터 화면용 API 응답까지 검사한다. 두 번째는 로빈·루피·조로·나미·상디·샹크스를 실제 외부 서비스로 조회하고 실패한 단계와 코드를 출력한다. 세 번째는 설정한 모델의 도구 선택과 자연어 요청 처리를 확인하며 모델 사용료가 발생할 수 있다. 계획 충돌·수정·삭제 검사는 별도의 임시 DB를 사용한다.

## 데이터 이용
One Piece API는 인증 없이 이름 검색을 제공하며 기본 페이지 크기는 20이다. 공개 문서에서 고정 호출 한도는 확인되지 않았다. Wiki 자료는 원문 링크 및 해당 문서의 라이선스를 따른다. TVmaze API는 CC BY-SA이며 최소 10초당 20회 호출을 허용한다. 429 응답 시 재시도를 중단하고 안내한다. 한국어 이름 교차 확인에는 MediaWiki langlinks를 사용한다.

- https://www.onepieceapi.com/documentation
- https://onepiece.fandom.com/wiki/One_Piece_Wiki
- https://www.mediawiki.org/wiki/API:Langlinks
- https://www.tvmaze.com/api#licensing

첫 등장 판정 순서는 캐릭터 API의 명시적 Episode 값 → 출처가 있는 영문 이름·회차 색인 → Wiki의 Debut 필드다. 포함된 debut-index.json은 yjg30737/onepiece-characters의 영문 이름과 애니 회차만 추린 스냅샷이다. 이름이 정확히 일치할 때만 사용하며, 현행 자료와 차이가 있을 수 있다. 회차는 API One Piece가 반환한 통산 번호와 일본 방영일을 검증하고 TVmaze의 정규 회차 목록과 대조한다. 회차 API가 실패하면 Wiki 회차 문서를 사용한다. 첫 등장 근거와 회차·시청 시간의 출처는 응답에 각각 표시한다.

- https://huggingface.co/datasets/yjg30737/onepiece-characters
- https://documentation.api-onepiece.com/en/5-episode

2026-11-20 기준 전체 캐릭터 1,431명의 고유 ID와 이름을 포함한다. 예를 들어 이무, 네로나 이무, 흰수염, 봉쿠레를 한글로 입력해 후보를 고를 수 있다. 새 캐릭터는 프로젝트 폴더에서 `python sync_catalog.py`를 실행한 뒤 서버를 재시작하면 반영된다. 동기화는 공식 사이트의 전체 항목 수와 고유 ID 수가 일치할 때만 목록을 교체한다.
