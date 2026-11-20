import os
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from tools_api import CATALOG, call
from agent import KST, chat
from store import connection, log_event
from events import subscribe

subscribe(log_event)

app = FastAPI(title="One Piece Watch Planner")


class Message(BaseModel):
    session_id: UUID
    run_id: UUID = Field(default_factory=uuid4)
    message: str = Field(min_length=1, max_length=2000)


class Plan(BaseModel):
    episode: int = Field(gt=0)
    start: datetime
    end: datetime


class Selected(Message):
    character_id: UUID | None = None
    character: str = Field(min_length=1, max_length=150)


class Candidate(BaseModel):
    korean_name: str | None = None
    id: str
    name: str


class SearchResult(BaseModel):
    ok: Literal[True]
    data: list[Candidate]


class SearchError(BaseModel):
    ok: Literal[False]
    error: dict[str, str]


class ChatResult(BaseModel):
    answer: str
    slot: Plan | None
    trace: list[dict]
    sources: list[str]


class StoredPlan(Plan):
    id: int
    sid: str
    created: str


class Saved(BaseModel):
    id: int
    overlaps: list[int]


class LogSummary(BaseModel):
    sid: str
    events: int


class LogEntry(BaseModel):
    id: int
    sid: str
    kind: str
    payload: str
    created: str


@app.get("/api/characters/names", response_model=list[Candidate])
def list_character_names():
    return sorted((row for row, _ in CATALOG.values()), key=lambda row: row["korean_name"])


@app.get("/api/characters", response_model=SearchResult | SearchError)
def search_characters(name: str):
    return call("characters", name)


@app.post("/api/character-info", response_model=ChatResult)
def character_info(body: Selected):
    return chat(str(body.session_id), body.message, str(body.run_id), body.character, str(body.character_id) if body.character_id else None)


@app.post("/api/chat", response_model=ChatResult)
def converse(body: Message):
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(503, ".env에 OPENAI_API_KEY를 설정하고 서버를 재시작하세요.")
    try:
        return chat(str(body.session_id), body.message, str(body.run_id))
    except Exception as exc:
        raise HTTPException(502, "요청 처리에 실패했습니다. 모델 설정과 서버 연결을 확인하세요.") from exc


def rows(query, *args):
    with connection() as db:
        return [dict(r) for r in db.execute(query, args)]


@app.get("/api/plans", response_model=list[StoredPlan])
def plans(session_id: UUID):
    return rows("SELECT * FROM plans WHERE sid=? ORDER BY start", str(session_id))


@app.get("/api/plans/{pid}", response_model=StoredPlan)
def detail(pid: int, session_id: UUID):
    matches = rows("SELECT * FROM plans WHERE sid=? AND id=?", str(session_id), pid)
    if not matches:
        raise HTTPException(404, "계획이 없습니다.")
    return matches[0]


def save(session_id, body, pid=None):
    start, end = [(t if t.tzinfo else t.replace(tzinfo=KST)).astimezone(KST).isoformat()
                  for t in (body.start, body.end)]
    if start >= end:
        raise HTTPException(422, "종료 시각은 시작 시각보다 늦어야 합니다.")
    sid = str(session_id)
    with connection() as db:
        if pid is None:
            pid = db.execute("INSERT INTO plans(sid,episode,start,end) VALUES(?,?,?,?)",
                             (sid,body.episode,start,end)).lastrowid
        elif not db.execute("UPDATE plans SET episode=?,start=?,end=? WHERE sid=? AND id=?",
                            (body.episode,start,end,sid,pid)).rowcount:
            raise HTTPException(404,"계획이 없습니다.")
        overlaps = db.execute("SELECT id FROM plans WHERE sid=? AND id!=? AND start<? AND end>?",
                              (sid,pid,end,start)).fetchall()
    return {"id":pid, "overlaps":[r[0] for r in overlaps]}


@app.post("/api/plans", status_code=201, response_model=Saved)
def create(session_id: UUID, body: Plan):
    return save(session_id,body)


@app.put("/api/plans/{pid}", response_model=Saved)
def update(pid: int, session_id: UUID, body: Plan):
    return save(session_id,body,pid)


@app.delete("/api/plans/{pid}", response_model=dict[str, int])
def delete(pid: int, session_id: UUID):
    with connection() as db:
        if not db.execute("DELETE FROM plans WHERE sid=? AND id=?", (str(session_id),pid)).rowcount:
            raise HTTPException(404,"계획이 없습니다.")
    return {"deleted":pid}


@app.get("/api/logs", response_model=list[LogSummary])
def sessions(session_id: UUID):
    return rows("SELECT sid, count(*) AS events FROM events WHERE sid=? GROUP BY sid", str(session_id))


@app.get("/api/logs/{session_id}", response_model=list[LogEntry])
def history(session_id: UUID, run_id: UUID | None = None, after: int = 0):
    if run_id:
        return rows("SELECT * FROM events WHERE sid=? AND id>? AND json_extract(payload, '$.run_id')=? ORDER BY id",
                    str(session_id), after, str(run_id))
    return rows("SELECT * FROM events WHERE sid=? ORDER BY id", str(session_id))


@app.delete("/api/logs/{session_id}", response_model=dict[str, int])
def clear(session_id: UUID):
    with connection() as db:
        count = db.execute("DELETE FROM events WHERE sid=?", (str(session_id),)).rowcount
    return {"deleted":count}


app.mount("/", StaticFiles(directory=Path(__file__).with_name("static"), html=True), name="web")
