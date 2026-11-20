# 원피스 시청 계획 도우미

한글 캐릭터 검색, 첫 등장 회차·시청 시간 조회, 시청 가능 구간 판단과 재계획을 지원한다. 배포 시점의 캐릭터 색인은 1,431명이다. Google Calendar 연동과 기타 심화 기능은 추후 범위다.

## 실행

`onepiece` 폴더에서 Python 3.11 이상과 Git Bash를 사용한다.

```bash
python -m venv .venv
source .venv/Scripts/activate
python -m pip install -r requirements.txt
cp .env.example .env
python -m uvicorn main:app --reload
```

자연어 대화에는 SSAFY GMS 또는 OpenAI에서 발급받은 모델 API 키가 필요하다. `.env`에 `OPENAI_API_KEY`를 넣고, GMS 사용 시 제공받은 `OPENAI_BASE_URL`과 `OPENAI_MODEL`도 지정한다. 키는 개인 환경에서 관리한다. 캐릭터 검색·선택은 모델 키 없이 가능하다.

- 앱은 [127.0.0.1:8000](http://127.0.0.1:8000), API 문서는 [/docs](http://127.0.0.1:8000/docs)에서 확인한다.
- 자동 테스트는 `python verify.py -v`, 외부 API는 `python verify.py --live`, 모델 연결은 `python verify.py --model`로 확인한다.
- 준비된 입력과 고정 Tool 응답으로 시나리오를 재현하려면 별도 프로젝트 복사본의 `onepiece` 폴더에서 `python ../evidence/run_scenarios.py`를 실행한다.

## 제출 문서

| 파일 | 내용 |
|---|---|
| [요구사항 정의서](docs/requirements.md) | F3001~F3019, NF3001~NF3007, 기획 검증 및 범위 |
| [Agent 설계](docs/agent-design.md) | 분석·조회·판단, 제약 비교·재계획, 대화 맥락과 로그 |
| [Tool 정의서](docs/tool-spec.md) | 입력·출력·실패 코드와 등록 방식 |
| [API 명세서](docs/api-spec.md) | HTTP 경로와 스키마, 재현 방법 |
| [검증 결과](docs/verification.md) | 대표 시나리오 결과, 제한 사항, 증빙 목록 |
| `self-checklist.xlsx` | 항목별 판정·증빙 경로와 재현 방법 |
| [소스 실행 안내와 외부 자료](onepiece/README.md) | 상세 설치·실행, 데이터 출처 및 이용 조건 확인 범위 |

브라우저 화면과 실제 모델로 확인이 남은 항목은 체크리스트에 미확인으로 기록했다. 텍스트 출력, JSON 로그, 실행 출력 이미지가 `evidence`에 있다.
