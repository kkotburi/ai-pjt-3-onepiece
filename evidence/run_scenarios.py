"""프로젝트 복사본의 onepiece 폴더에서 python ../evidence/run_scenarios.py 실행."""
import json
import sys
from pathlib import Path
from time import perf_counter
from uuid import uuid4
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "onepiece"))
import agent
from fastapi.testclient import TestClient
from main import app

OUT = Path(__file__).resolve().parent


def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")


def window(day, start, end):
    return {"start": f"2026-11-{day}T{start}:00", "end": f"2026-11-{day}T{end}:00"}


def run():
    sid = str(uuid4())
    cases = [
        ("s1", "11월 21일 18:00~19:00에 나미 첫 등장 편을 보고 싶어", "schedule", [window(21,"18:00","19:00")], 0, "18:00~18:25"),
        ("s2", "토요일 18:00~18:10이나 일요일 19:00~19:30에 보고 싶어", "schedule", [window(21,"18:00","18:10"),window(22,"19:00","19:30")], 1, "19:00~19:25"),
        ("s3", "21~25일 매일 18:00~18:10 중에 보고 싶어", "schedule", [window(d,"18:00","18:10") for d in range(21,26)], 3, "상한(3회)"),
        ("s4", "나미의 첫 등장 편은 몇 분이야?", "runtime", [], 0, "NO_RUNTIME"),
        ("s5", "안녕하세요", "clarify", [], 0, "안녕하세요!"),
    ]
    def tool(name, value):
        data = {
            "characters": [{"id":"fixture-nami","name":"Nami","korean_name":"나미"}],
            "debut": {"episode":1,"titles":["Fixture title"],"source":"https://onepiece.fandom.com/wiki/Episode_1"},
            "runtime": {"minutes":25,"source":"https://www.tvmaze.com/episodes/256125"},
        }
        if name == "runtime" and case == "s4":
            return {"ok":False,"error":{"code":"NO_RUNTIME","message":"시청 시간 누락"}}
        return {"ok":True,"data":data[name]}
    summaries=[]
    with TestClient(app) as client:
        save("openapi.json",client.get("/openapi.json").json())
        for case, question, intent, windows, replans, expected in cases:
            run_id = str(uuid4())
            reason = "안녕하세요! 캐릭터 조회나 시청 계획을 도와드릴게요." if intent == "clarify" else "테스트에서 지정한 의도"
            state = {"sid":sid,"run_id":run_id,"message":question,"trace":[]}
            def analyze(state):
                agent.emit(state,"decision",intent=intent,reason=reason)
                return {"plan":{"intent":intent,"character":"나미","windows":windows,"reason":reason},"cache":{}}
            began=perf_counter()
            with patch.object(agent,"call",side_effect=tool):
                for name, fn in [("analyze",analyze),("lookup",agent.lookup),("decide",agent.decide)]:
                    state.update(agent.step(name,fn)(state))
            elapsed=round((perf_counter()-began)*1000,2)
            trace=state["trace"]
            logged=client.get("/api/logs/"+sid,params={"run_id":run_id}).json()
            assert len(trace)==len(logged)
            assert sum(event["kind"]=="replan" for event in trace)==replans
            assert expected in state["answer"]
            assert sum(event["kind"]=="tool_start" for event in trace)==(0 if case=="s5" else 3)
            save(case+"-trace.json",{"request":question,"response":state["answer"],"slot":state.get("slot"),"elapsed_ms":elapsed,"trace":trace,"saved_events":logged})
            summaries.append({"case":case,"expected":expected,"answer":state["answer"],"elapsed_ms":elapsed,
                              "replans":replans,"difference":"지정된 의도 및 고정 응답 환경에서 기대와 일치"})
            print(case,elapsed,"ms",f"replans={replans}",state["answer"])

        path=f"/api/plans?session_id={sid}"
        body={"episode":1,"start":"2026-11-21T18:00:00+09:00","end":"2026-11-21T18:25:00+09:00"}
        first=client.post(path,json=body)
        second=client.post(path,json=body)
        assert first.status_code==second.status_code==201 and second.json()["overlaps"]==[first.json()["id"]]
        plan_path=f"/api/plans/{first.json()['id']}?session_id={sid}"
        updated=client.put(plan_path,json={**body,"episode":2})
        assert updated.status_code==200
        listed=client.get(path).json()
        detail=client.get(plan_path).json()
        assert detail in listed and detail["episode"]==2
        deleted=client.delete(plan_path)
        assert deleted.status_code==200 and client.get(plan_path).status_code==404
        logs_path=f"/api/logs/{sid}"
        assert client.get("/api/logs",params={"session_id":sid}).json()
        log_delete=client.delete(logs_path)
        assert log_delete.status_code==200 and client.get(logs_path).json()==[]
        assert set(client.get("/openapi.json").json()["paths"]["/api/logs/{session_id}"])=={"get","delete"}
        save("18-20-plan-and-log-api.json",{"first_save":first.json(),"second_save":second.json(),
              "updated_list":listed,"updated_detail":detail,"delete_plan":deleted.json(),
              "detail_after_delete_status":404,"delete_logs":log_delete.json(),"logs_after_delete":[]})
    save("scenario-results.json",summaries)


if __name__ == "__main__":
    run()
