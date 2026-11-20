"""python verify.py [--live | --model]  (실서비스 키/네트워크 검사는 명시적으로 실행)."""
import sys
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

import agent
import store
import tools_api as tools
from main import app


def check_live():
    failures = []
    for name in ["로빈", "루피", "조로", "나미", "상디", "Shanks"]:
        search = tools.call("characters", name)
        exact = [r for r in search.get("data", []) if tools.key(r["name"]) == tools.key(tools.search_name(name))]
        if len(exact) != 1:
            failures.append((name, "characters", search.get("error", "정확한 후보 없음")))
            continue
        result = tools.call("debut", exact[0])
        duration = tools.call("runtime", result["data"]) if result["ok"] else result
        if not duration["ok"]:
            failures.append((name, "runtime" if result["ok"] else "debut", duration["error"]))
            continue
        print(name, exact[0]["name"], result["data"]["episode"], duration["data"]["minutes"], duration["data"]["source"])
    for failure in failures:
        print(*failure)
    return int(bool(failures))


class ServiceChecks(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "test.sqlite"
        with store.connection() as source:
            import sqlite3
            with sqlite3.connect(path) as target:
                for row in source.execute("SELECT sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL"):
                    target.execute(row[0])
        swap = patch.object(store, "DB", path)
        swap.start()
        self.addCleanup(swap.stop)
        self.sid = str(uuid4())
        self.q = "?session_id=" + self.sid
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_search_through_runtime(self):
        for name, label, episode in [("나미", "Nami", 1), ("조로", "Roronoa Zoro", 1),
                                     ("상디", "Sanji", 20), ("샹크스", "Shanks", 4),
                                     ("로빈", "Nico Robin", 67), ("루피", "Monkey D. Luffy", 1),
                                     ("Aisa", "Aisa", 155)]:
            ident = str(uuid4())
            character = {"id": ident, "name": {"en": label}}
            def get(url, **params):
                if url == tools.CHARACTERS:
                    self.assertEqual(params["q"], label)
                    return [character]
                if url == tools.CHARACTERS + "/" + ident:
                    return character
                if url.startswith("https://api.api-onepiece.com/"):
                    return {"number":"n°9999","release_date":"1999-10-20"}
                if url == tools.WIKI:
                    if params["prop"] == "text":
                        self.assertEqual(params["page"], label)
                        return {"parse": {"text": f'<div data-source="debut">Chapter 1 (cover); <a>Episode {episode}</a></div>'}}
                    self.assertEqual(params["page"], f"Episode {episode}")
                    return {"parse": {"wikitext": "|Translation = Fixture title\n|Airdate = October 20, 1999"}}
                self.assertEqual(url, tools.TV)
                return [{"type":"regular", "season":1, "number":i,"airdate":"1999-10-20" if i==episode else "",
                         "id":i, "runtime":24, "name":"Different title", "url":"https://www.tvmaze.com/"}
                        for i in range(1,episode+1)]
            with self.subTest(name=name), patch.object(tools, "get", get), patch.object(tools, "DEBUT_INDEX", {}), patch.object(tools, "CATALOG", {}):
                rows = self.client.get("/api/characters", params={"name":name}).json()["data"]
                self.assertEqual(rows[0]["id"], ident)
                run = str(uuid4())
                response = self.client.post("/api/character-info", json={
                    "session_id":self.sid, "message":name, "character":label, "character_id":ident, "run_id":run})
                self.assertEqual(response.status_code, 200)
                self.assertIn(f"{episode}화", response.json()["answer"])
                self.assertIn("24분", response.json()["answer"])
                events = self.client.get(f"/api/logs/{self.sid}?run_id={run}").json()
                self.assertEqual([e["kind"] for e in events].count("tool_end"), 3)
                self.assertEqual(events[-1]["kind"], "stage_end")

    def test_all_korean_names_resolve_to_original_id(self):
        names = self.client.get("/api/characters/names").json()
        self.assertEqual(len(names),len(tools.CATALOG))
        for row in names:
            self.assertRegex(row["korean_name"], "[가-힣]")
            self.assertIn(row["id"], {r["id"] for r in tools.korean_search(row["korean_name"])})
        for query, canonical in [("이무","Imu"),("네로나 이무","Nerona Imu"),("흰 수염","Edward Newgate"),
                                  ("봉쿠레","Bentham"),("로키","Loki")]:
            result=self.client.get("/api/characters",params={"name":query}).json()
            self.assertIn(canonical, [r["name"] for r in result["data"]])

    def test_korean_catalog_fetches_chosen_id(self):
        rows = tools.characters("이무")
        imu = next(row for row in rows if row["name"]=="Imu")
        def fetch(url,**params):
            if url == tools.CHARACTERS+"/"+imu["id"]:
                return {"id":imu["id"],"name":{"en":"Imu"},"extra_data":{"first_appearance":"Episode 1"}}
            self.assertEqual(url,"https://api.api-onepiece.com/v2/episodes/en/1")
            return {"number":"n°1","release_date":"1999-10-20","title":"Test"}
        with patch.object(tools,"get",side_effect=fetch):
            result = tools.debut(imu)
            self.assertIn(imu["id"],result["character_source"])

    def test_partial_and_no_matches(self):
        rows = [{"id":str(uuid4()), "name":{"en":n}} for n in ["Test Jack","Jack"]]
        with patch.object(tools,"get",return_value=rows):
            self.assertEqual(len(tools.characters("jack")), 2)
            self.assertEqual(tools.call("characters","no match")["error"]["code"], "NO_RESULTS")

    def test_wrong_airdate_does_not_select_next_episode(self):
        rows=[{"type":"regular","season":1,"number":1,"name":"Red Haired Shanks Appears","id":11,
               "airdate":"1999-12-08","runtime":25,"url":"https://www.tvmaze.com/episodes/11"},
              {"type":"regular","season":1,"number":2,"name":"Captain Buggy","id":12,"airdate":"1999-12-15"}]
        with patch.object(tools,"get",return_value=rows):
            result=tools.runtime({"episode":1,"titles":["Shanks the red haired pirate"],"airdate":"1999-12-15"})
            self.assertEqual(result["id"],11)
            failure=tools.call("runtime",{"episode":1,"titles":["Unrelated"],"airdate":"1999-12-15"})
            self.assertEqual(failure["error"]["code"],"EPISODE_CONFLICT")

    def test_numbered_episode_source(self):
        row = {"number":"n°20", "release_date":"2000-04-12","title":"A cook"}
        with patch.object(tools, "get", return_value=row) as fetch:
            result = tools.debut({"id":"123","name":"Sanji","first_appearance":"Chapter 43; Episode 20"})
            self.assertEqual(result["airdate"], "2000-04-12")
            fetch.assert_called_once_with("https://api.api-onepiece.com/v2/episodes/en/20")

    def test_ambiguous_date(self):
        rows = [{"name":n,"airdate":"2000-01-01"} for n in ["A","B"]]
        with patch.object(tools,"get",return_value=rows):
            self.assertEqual(tools.call("runtime",{"titles":[],"airdate":"2000-01-01"})["error"]["code"],"AMBIGUOUS_EPISODE")

    def test_invalid_tool_inputs_do_not_contact_upstream(self):
        inputs = [("characters", ""), ("characters", {}), ("characters", {"id": str(uuid4()), "name": "Nami"}),
                  ("characters", {"id": "invalid"}), ("debut", {"name": "Nami"}), ("runtime", {"titles": "invalid"})]
        with patch.object(tools, "get") as fetch:
            for name, payload in inputs:
                with self.subTest(name=name, payload=payload):
                    self.assertEqual(tools.call(name, payload)["error"]["code"], "INVALID_INPUT")
            fetch.assert_not_called()

    def test_deadline_uses_runtime_without_creating_saveable_slot(self):
        for deadline, expected in [
            ({"end": "19:00"}, "18:35"),
            ({"end": "00:15"}, "전날 23:50"),
            ({"day": "2026-11-22", "end": "00:15"}, "2026-11-21 23:50"),
        ]:
            with self.subTest(deadline=deadline):
                state = {"sid": self.sid, "run_id": str(uuid4()), "trace": [], "cache": {},
                         "plan": {"intent": "deadline", "character": "나미", "deadline": deadline}}
                answers = [
                    {"ok": True, "data": [{"id": "nami", "name": "Nami"}]},
                    {"ok": True, "data": {"episode": 1, "titles": []}},
                    {"ok": True, "data": {"minutes": 25}},
                ]
                with patch.object(agent, "call", side_effect=answers):
                    state.update(agent.lookup(state))
                    result = agent.decide(state)
                self.assertIn(f"늦어도 {expected}에", result["answer"])
                self.assertNotIn("slot", result)
        answers[-1] = {"ok": False, "error": {"code": "NO_RUNTIME"}}
        state["cache"] = {}
        with patch.object(agent, "call", side_effect=answers):
            result = agent.lookup(state)
        self.assertIn("NO_RUNTIME", result["answer"])
        self.assertNotIn("늦어도", result["answer"])

    def test_followup_reuses_results_and_stops_at_limit(self):
        cached = {"characters":[{"id":"1","name":"Nami"}],"debut":{"episode":1,"titles":[]},
                  "runtime":{"minutes":25}}
        window = {"start":"2026-11-22T18:00:00","end":"2026-11-22T18:10:00"}
        state = {"sid":self.sid,"run_id":str(uuid4()),"trace":[],
                 "plan":{"intent":"schedule","character":"나미","windows":[window]*5},"cache":cached}
        with patch.object(agent, "call", side_effect=AssertionError("불필요한 재호출")):
            state.update(agent.lookup(state))
            answer=agent.decide(state)["answer"]
        self.assertIn("상한",answer)
        self.assertEqual(sum(t["kind"]=="replan" for t in state["trace"]),3)
        self.assertEqual(sum(t["kind"]=="cache_hit" for t in state["trace"]),3)

    def test_plans_replan_and_logs(self):
        plan={"episode":1,"start":"2026-11-22T18:00:00","end":"2026-11-22T18:15:00"}
        def create():
            return self.client.post("/api/plans"+self.q,json=plan).json()
        pid=create()["id"]
        second=create()
        self.assertIn(pid,second["overlaps"])
        path=f"/api/plans/{pid}"+self.q
        original = self.client.get(path).json()
        self.assertEqual(original["episode"],1)
        self.assertEqual(self.client.put(path,json={**plan,"episode":2}).status_code,200)
        updated = self.client.get(path).json()
        self.assertEqual(updated["episode"], 2)
        self.assertEqual(updated["created"], original["created"])
        listed = next(row for row in self.client.get("/api/plans"+self.q).json() if row["id"] == pid)
        self.assertEqual(listed, updated)
        self.assertEqual(self.client.put(path, json={**plan, "episode": 0}).status_code, 422)
        self.assertEqual(self.client.put(path, json={**plan, "end": plan["start"]}).status_code, 422)
        state={"sid":self.sid,"run_id":str(uuid4()),"trace":[],"plan":{"intent":"schedule","character":"Nami",
               "windows":[{"start":plan["start"],"end":"2026-11-22T19:00:00"}]},
               "cache":{"debut":{"episode":1},"runtime":{"minutes":25}}}
        self.assertEqual(agent.decide(state)["slot"]["start"],"2026-11-22T18:15:00+09:00")
        self.assertEqual(self.client.get("/api/logs"+self.q).json()[0]["events"],1)
        self.assertEqual(self.client.delete("/api/logs/"+self.sid).json()["deleted"],1)
        self.assertEqual(self.client.delete(path).status_code,200)
        self.assertEqual(self.client.get(path).status_code,404)


if __name__ == "__main__":
    if "--live" in sys.argv:
        sys.exit(check_live())
    if "--model" in sys.argv:
        from langchain_openai import ChatOpenAI
        import os
        model = ChatOpenAI(model=os.getenv("OPENAI_MODEL") or "gpt-4o-mini",
                           base_url=os.getenv("OPENAI_BASE_URL") or None, timeout=30)
        functions = []
        for name, spec in tools.SPECS.items():
            schema = dict(spec["input"])
            definitions = schema.pop("$defs", {})
            functions.append({"type": "function", "function": {
                "name": name, "description": spec["description"], "parameters": {
                    "type": "object", "properties": {"value": schema},
                    "required": ["value"], "$defs": definitions},
            }})
        try:
            reply = model.bind_tools(functions).invoke("나미라는 이름의 캐릭터 후보를 먼저 검색해 줘.")
            if not any(c["name"]=="characters" for c in reply.tool_calls):
                sys.exit("캐릭터 검색 Tool 선택 실패")
        except Exception:
            sys.exit("모델 연결 또는 Tool 호출 실패. 모델 설정을 확인하세요.")
        result = agent.chat(str(uuid4()), "나미의 첫 등장 회차와 시청 시간을 알려줘", str(uuid4()))
        print(result["answer"])
        sys.exit(int(not any(e.get("tool")=="runtime" and e.get("result",{}).get("ok") for e in result["trace"])))
    unittest.main()
