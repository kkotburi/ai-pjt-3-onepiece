# API 명세서

실행한 앱에서 추출한 [OpenAPI JSON](../evidence/openapi.json)에 모든 경로의 요청·응답 스키마가 있다.

| 요청 | 필수 입력 | 결과 |
|---|---|---|
| GET /api/characters | name | 검색 성공 또는 구조화 오류 |
| GET /api/characters/names | 없음 | 전체 표시명과 고유 ID |
| POST /api/character-info | session_id, message, character. 선택적으로 character_id와 run_id | answer, slot, trace, sources |
| POST /api/chat | session_id, message. 선택적으로 run_id | 자연어 답변과 일정 제안·로그·출처 |
| GET /api/plans | session_id | 계획 목록 |
| POST /api/plans | session_id, episode, start, end | 201, 계획 ID와 겹치는 ID 목록 |
| GET /api/plans/{pid} | pid, session_id | 회차·시청 시각·생성 일시 |
| PUT /api/plans/{pid} | pid, session_id, episode, start, end | 수정한 ID와 겹치는 ID 목록 |
| DELETE /api/plans/{pid} | pid, session_id | 삭제 ID |
| GET /api/logs | session_id | 세션별 이벤트 수 |
| GET /api/logs/{session_id} | session_id. 선택적으로 run_id, after | 순서대로 저장한 이벤트 |
| DELETE /api/logs/{session_id} | session_id | 삭제 이벤트 수 |

일정 본문 예시는 `{"episode":1,"start":"2026-11-21T18:00:00+09:00","end":"2026-11-21T18:25:00+09:00"}`다. API는 종료가 시작보다 늦은지 검사한다. 조회·수정·삭제 대상을 찾을 수 없으면 404, 입력 검증 실패는 422, 모델 키 누락은 503, 모델 요청 처리 실패는 502로 응답한다. 경로별 상태와 세부 스키마는 FastAPI의 `/docs`에서 확인한다.
