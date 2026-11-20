# Tool 정의서

세 도구의 유형은 `external_api`다. `SPECS`에 설명, JSON 입력 스키마, 출력 필드와 오류 코드가 등록된다. 원본 명세는 [tool-schemas.json](tool-schemas.json)에 포함했다.

| 이름 | 입력 | 정상 데이터 |
|---|---|---|
| characters | 이름 문자열 또는 UUID를 넣은 `{"id":"..."}` | 후보 배열. 원본 ID, 이름, 선택적인 한글 이름·첫 등장 단서 |
| debut | 선택한 후보 객체 또는 영문 이름 문자열 | 통산 회차, 제목 배열, 선택적 방영일, 캐릭터와 회차 출처 |
| runtime | debut 결과 또는 제목 문자열 배열 | 분 단위 러닝타임, TVmaze ID, 제목, 출처 URL |

공통 성공 형식은 `{"ok":true,"data":...}`다. 실패는 `{"ok":false,"error":{"code":"...","message":"..."}}`로 반환한다. 잘못된 이름/ID 형식은 `INVALID_INPUT`, 외부 서비스 연결 실패는 `UPSTREAM_ERROR`, 호출 제한은 `RATE_LIMIT`이다. 결과가 없을 때와 회차·시간을 확정할 수 없을 때의 상세 코드는 JSON 명세를 확인한다. 도구를 추가할 경우 함수와 입력 검증기를 `REGISTRY`, `INPUTS`에 등록하고 설명·출력·실패 코드를 `SPECS`에 등록한 뒤 Agent의 호출 분기에 연결한다.
