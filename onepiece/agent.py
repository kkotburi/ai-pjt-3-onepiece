import os
import re
from functools import lru_cache
from datetime import date, datetime, time, timedelta, timezone
from time import monotonic
from typing import Literal, TypedDict

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from store import connection, remember
from events import publish
from tools_api import INDEX_SOURCE, SPECS, call, key, search_name

load_dotenv()
KST = timezone(timedelta(hours=9))


class Window(BaseModel):
    start: datetime
    end: datetime


class Deadline(BaseModel):
    day: date | None = None
    end: time


class RequestPlan(BaseModel):
    intent: Literal["debut", "runtime", "schedule", "deadline", "clarify"]
    character: str
    windows: list[Window] = Field(default_factory=list)
    deadline: Deadline | None = None
    reason: str


class State(TypedDict, total=False):
    run_id: str
    sid: str
    message: str
    plan: dict
    cache: dict
    answer: str
    slot: dict
    trace: list


def emit(s, kind, **payload):
    payload["run_id"] = s["run_id"]
    s["trace"].append({"kind": kind, **payload})
    publish(s["sid"], kind, payload)


def analyze(s):
    old = remember(s["sid"])
    from langchain_openai import ChatOpenAI
    model = ChatOpenAI(model=os.getenv("OPENAI_MODEL") or "gpt-4o-mini",
                       base_url=os.getenv("OPENAI_BASE_URL") or None, timeout=30, max_retries=1)
    prompt = ("원피스 요청을 분석한다. 첫 등장 질문은 debut, 시간 질문은 runtime, 계획은 schedule. "
              "애니메이션 기준이다. 시청 시간·러닝타임은 한 회 길이이며 첫 등장과 함께 물으면 runtime이다. 시간 배정을 명시할 때만 schedule. 모호한 요청은 clarify. 사용자가 허용한 연속 시청 구간만 선호순으로 windows에 넣는다. "
              "종료 시각만 주고 늦어도 언제 시작해야 하는지 묻거나, 예를 들어 '나미 첫 등장 편을 19시까지 보려면?'이라고 묻는다면 deadline이다. "
              "그때 deadline.end에 한국시간의 종료 시각, 날짜가 명시되거나 대화에서 확정된 경우에만 deadline.day를 넣는다. 시작과 종료가 명시된 구간은 schedule이다. "
              "한국시간 기준. 시각을 추측하지 않는다. 이전 조건은 후속 요청에서 변경분만 갱신한다. "
              "누락된 이름은 빈 문자열. reason은 짧은 사용자용 판단 근거 또는 확인 질문. "
              f"도구 명세 {SPECS}. character에는 사용자가 입력한 캐릭터 이름을 원문 그대로 보존한다. "
              f"현재 {datetime.now(KST).isoformat()}, 이전 조건 {old.get('plan')}, "
              f"직전 질문 {old.get('message')}, 직전 응답 {old.get('answer')}")
    p = model.with_structured_output(RequestPlan).invoke([("system", prompt), ("human", s["message"])])
    # 명시한 응답 항목은 모델 분류가 달라져도 실행 계획에 보존한다.
    message = s["message"]
    duration = re.search(r"시청\s*시간|러닝\s*타임|런닝\s*타임|재생\s*시간|몇\s*분|얼마나\s*걸", message)
    planning = re.search(r"일정|계획|빈\s*시간|주말|토요일|일요일|등록|예약|볼\s*수", message)
    if p.intent != "deadline" and duration and not planning and not re.search(r"말고|제외|필요\s*없", message):
        p.intent = "runtime"
        p.reason = "요청한 회차의 시청 시간을 확인합니다."
        p.windows = []
    cache = old.get("cache", {}) if key(search_name(old.get("plan", {}).get("character", ""))) == key(search_name(p.character)) else {}
    emit(s, "decision", intent=p.intent, reason=p.reason)
    return {"plan": p.model_dump(mode="json"), "cache": cache}


def lookup(s):
    p, cache = s["plan"], s["cache"]
    if p["intent"] == "clarify" or not p["character"]:
        return {"answer": p["reason"] if p["intent"] == "clarify" else "어느 캐릭터를 볼까요?"}
    if p["intent"] == "schedule" and not p["windows"]:
        return {"answer": "시청 가능한 날짜와 시작·종료 시각을 알려주세요."}
    if p["intent"] == "deadline" and not p.get("deadline"):
        return {"answer": "몇 시까지 시청을 마쳐야 하는지 알려주세요."}
    sequence = ["characters", "debut"]
    if p["intent"] != "debut":
        sequence.append("runtime")
    emit(s, "plan", tools=sequence)
    value = {"id": p["character_id"]} if p.get("character_id") else p["character"]
    for tool in sequence:
        if tool in cache:
            emit(s, "cache_hit", tool=tool)
        else:
            emit(s, "tool_start", tool=tool, input=value)
            started = monotonic()
            result = call(tool, value)
            emit(s, "tool_end", tool=tool, result=result, ms=round((monotonic()-started)*1000))
            if not result["ok"]:
                code = result["error"]["code"]
                hint = {"NO_RESULTS": "이름을 찾지 못했습니다. 다른 한글 표기나 이름의 일부로 다시 검색해 주세요.",
                        "ENGLISH_NAME_REQUIRED": "검색창의 한글 이름 목록에서 캐릭터를 선택해 주세요.",
                        "RATE_LIMIT": "조회 요청이 많습니다. 잠시 후 다시 시도해 주세요."}.get(code, "외부 자료에서 값을 확인하지 못했습니다.")
                known = f"첫 등장은 {cache['debut']['episode']}화입니다. " if tool == "runtime" else ""
                return {"answer": f"{known}{hint} ({code})", "cache": cache}
            cache[tool] = result["data"]
        if tool == "characters":
            rows = cache[tool]
            exact = [r for r in rows if key(r["name"]) == key(search_name(p["character"])) or key(r.get("korean_name", "")) == key(p["character"])]
            candidates = exact or rows
            if len(candidates) != 1:
                return {"answer": "캐릭터를 선택해 주세요: " + ", ".join(r.get("korean_name", r["name"]) + " (" + r["name"] + ")" for r in candidates)}
            value = candidates[0]
            p["character"] = value.get("korean_name", value["name"])
        elif tool == "debut":
            value = cache[tool]
    return {"cache": cache, "plan": p}


def decide(s):
    if s.get("answer"):
        return {}
    p, cache = s["plan"], s["cache"]
    ep = cache["debut"]["episode"]
    answer = f"{p['character']}의 첫 등장: {ep}화."
    if cache["debut"].get("character_source") == INDEX_SOURCE:
        answer += " 공개 캐릭터 자료의 첫 등장 기록 기준입니다."
    if p["intent"] == "debut":
        return {"answer": answer}
    minutes = cache["runtime"]["minutes"]
    answer += f" 시청 시간은 {minutes}분입니다."
    if p["intent"] == "deadline":
        deadline = Deadline.model_validate(p["deadline"])
        end = datetime.combine(deadline.day or date(2000, 1, 2), deadline.end)
        end = end.astimezone(KST) if end.tzinfo else end.replace(tzinfo=KST)
        latest = end - timedelta(minutes=minutes)
        if deadline.day:
            when = latest.strftime("%Y-%m-%d %H:%M")
        else:
            days_before = (end.date() - latest.date()).days
            prefix = "전날 " if days_before == 1 else f"{days_before}일 전 " if days_before else ""
            when = f"{prefix}{latest:%H:%M}"
        return {"answer": answer + f" 마감 시각까지 보려면 늦어도 {when}에 시작해야 합니다."}
    if p["intent"] == "schedule":
        with connection() as db:
            busy = db.execute("SELECT start,end FROM plans WHERE sid=? ORDER BY start", (s["sid"],)).fetchall()
        attempts = 0
        for w in p["windows"]:
            if attempts >= 4:
                break
            if attempts:
                emit(s, "replan", attempt=attempts, reason="다음 허용 구간 탐색")
            attempts += 1
            start, end = [datetime.fromisoformat(w[k]) for k in ("start","end")]
            start, end = [(v if v.tzinfo else v.replace(tzinfo=KST)).astimezone(KST) for v in (start,end)]
            duration = timedelta(minutes=minutes)
            for occupied in busy:
                busy_start, busy_end = (datetime.fromisoformat(t) for t in occupied)
                if busy_end <= start or busy_start >= start + duration or start + duration > end:
                    continue
                answer += f" {start:%m/%d %H:%M} 시작은 저장된 계획과 겹칩니다."
                if attempts >= 4:
                    return {"answer": answer + " 재계획 상한(3회)에 도달했습니다. 다른 가능 시간을 알려주세요."}
                emit(s, "replan", attempt=attempts, reason="겹치는 계획 종료 후로 시작 시각 이동")
                attempts += 1
                start = busy_end
            finish = start + duration
            if finish <= end:
                return {"answer": answer + f" {start:%m/%d %H:%M}~{finish:%H:%M}에 볼 수 있습니다.",
                        "slot": {"episode":ep, "start":start.isoformat(), "end":finish.isoformat()}}
            answer += f" {start:%m/%d %H:%M} 구간은 {max(0,int((end-start).total_seconds()//60))}분으로 부족합니다."
        if attempts >= 4:
            answer += " 재계획 상한(3회)에 도달했습니다."
        answer += " 다른 시청 가능 시간을 알려주세요."
    return {"answer": answer}


def step(name, fn):
    def run(s):
        emit(s, "stage_start", stage=name)
        try:
            return {**fn(s), "trace": s["trace"]}
        finally:
            emit(s, "stage_end", stage=name)
    return run


@lru_cache(maxsize=1)
def build_graph():
    from langgraph.graph import END, START, StateGraph
    builder = StateGraph(State)
    for name, fn in [("analyze", analyze), ("lookup", lookup), ("decide", decide)]:
        builder.add_node(name, step(name, fn))
    builder.add_edge(START, "analyze")
    builder.add_edge("analyze", "lookup")
    builder.add_edge("lookup", "decide")
    builder.add_edge("decide", END)
    return builder.compile()


def chat(sid, message, run_id, character=None, character_id=None):
    initial = {"sid": sid, "message": message, "run_id": run_id, "trace": []}
    if character:
        def selected(s):
            reason = "선택한 캐릭터의 첫 등장과 시청 시간을 조회합니다."
            emit(s, "decision", intent="runtime", reason=reason)
            return {"plan": {"character": character, "character_id": character_id, "intent": "runtime", "windows": [], "reason": reason}, "cache": {}}
        result = initial
        for name, fn in [("analyze", selected), ("lookup", lookup), ("decide", decide)]:
            result.update(step(name, fn)(result))
    else:
        result = build_graph().invoke(initial)
    remember(sid, {k: result[k] for k in ("message", "answer", "plan", "cache")})
    sources = [v[k] for v in result["cache"].values() if isinstance(v, dict)
               for k in ("character_source", "source") if k in v]
    return {k: result.get(k) for k in ("answer", "slot", "trace")} | {"sources": sources}
