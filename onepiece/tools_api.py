"""원피스 공개 API의 응답을 에이전트용 결과로 변환한다."""
import json
import re
import unicodedata
from functools import lru_cache
from time import monotonic
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote
from uuid import UUID

from korean_names import readings, spell

import requests
from lxml import etree, html
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter, ValidationError
from typing import Annotated

ALIASES = json.loads(Path(__file__).with_name("aliases.json").read_text(encoding="utf8"))
DEBUT_INDEX = json.loads(Path(__file__).with_name("debut-index.json").read_text(encoding="utf8"))
INDEX_SOURCE = "https://huggingface.co/datasets/yjg30737/onepiece-characters"
CHARACTERS = "https://www.onepieceapi.com/api/characters"
WIKI = "https://onepiece.fandom.com/api.php"
TV = "https://api.tvmaze.com/shows/1505/episodes"


class LookupFailure(Exception):
    pass


def get(url, **params):
    return fetch_json(url, tuple(sorted(params.items())), int(monotonic() // 60))


@lru_cache(maxsize=128)
def fetch_json(url, params, cache_minute):
    headers = {"User-Agent": "OnePieceWatchPlanner/1.1 (educational project)"}
    try:
        response = requests.get(url, params=dict(params), timeout=(6, 15), headers=headers)
    except (requests.Timeout, requests.ConnectionError):
        response = requests.get(url, params=dict(params), timeout=(8, 15), headers=headers)
    if response.status_code == 429:
        raise LookupFailure("RATE_LIMIT")
    response.raise_for_status()
    return response.json()


def key(name):
    return "".join(c for c in unicodedata.normalize("NFKC", name).casefold() if c.isalnum())


def build_catalog(rows, aliases):
    by_english = {}
    for korean, english in aliases.items():
        by_english.setdefault(key(english), []).append(korean)
    catalog = {}
    for uid, names in rows.items():
        english = names.get("en") or names.get("romaji") or names.get("jp")
        standard = by_english.get(key(english), [])
        forms = standard + readings(names)
        if not forms:
            forms = [spell(english)]
        if not forms[0]:
            raise ValueError(f"한글 이름이 필요합니다: {english}")
        terms = {key(s) for s in forms}
        # 국내판 이름에 섞인 로마자 D 등도 한글로 검색한다.
        terms.update(key(re.sub(r"[A-Za-z]+", lambda m: spell(m[0]), s)) for s in forms)
        catalog[uid] = ({"id": uid, "name": english, "korean_name": forms[0]}, terms)
    return catalog


CATALOG = build_catalog(json.loads(Path(__file__).with_name("character-catalog.json").read_text(encoding="utf8")), ALIASES)


def korean_search(name):
    query = key(name)
    exact, partial = [], []
    for row, forms in CATALOG.values():
        if query in forms:
            exact.append(dict(row))
        elif any(query in value for value in forms):
            partial.append(dict(row))
    return exact + partial


def search_name(name):
    name = re.sub(r"\s*\(One Piece\)$", "", name.strip(), flags=re.I)
    return next((v for k, v in ALIASES.items() if key(k) == key(name)), name)


def candidate(row, label):
    extra = row.get("extra_data") or {}
    result = {"id": row["id"], "name": label}
    if row["id"] in CATALOG:
        result["korean_name"] = CATALOG[row["id"]][0]["korean_name"]
    if isinstance(extra, dict) and isinstance(extra.get("first_appearance"), str):
        result["first_appearance"] = extra["first_appearance"]
    return result


def characters(name):
    if isinstance(name, dict):
        identifier = str(UUID(name["id"]))
        row = get(f"{CHARACTERS}/{identifier}")
        if row["id"] != identifier:
            raise LookupFailure("INVALID_RESPONSE")
        label = row["name"].get("en") or row["name"].get("romaji") or row["name"].get("jp")
        return [candidate(row, label)] if label else []
    if re.search("[가-힣]", name):
        hits = korean_search(name)
        if hits:
            return [{**row, "from_catalog": True} for row in hits]
    query = search_name(name)
    if not query:
        raise LookupFailure("NAME_REQUIRED")
    if re.search("[가-힣]", query):
        # 동명 일반 문서와 구별한 한국어 문서의 실제 영문 링크를 사용한다.
        titles = f"{query} (원피스)|{query}"
        pages = get("https://ko.wikipedia.org/w/api.php", action="query", titles=titles,
                    prop="langlinks", lllang="en", redirects=1, format="json",
                    formatversion=2)["query"]["pages"]
        labels = [link["title"] for p in pages for link in p.get("langlinks", [])]
        labels.sort(key=lambda label: "(one piece)" not in label.lower())
        if not labels:
            raise LookupFailure("ENGLISH_NAME_REQUIRED")
        query = search_name(labels[0])
    matches = {}
    page = 1
    while True:
        params = {"q": query} if page == 1 else {"q": query, "page": page, "limit": 20}
        rows = get(CHARACTERS, **params)
        if not isinstance(rows, list):
            raise LookupFailure("INVALID_RESPONSE")
        previous = len(matches)
        for row in rows:
            names = row.get("name") or {}
            label = names.get("en") or names.get("romaji") or names.get("jp")
            if label and any(key(query) in key(v) for v in names.values() if isinstance(v, str)):
                matches[row["id"]] = candidate(row, label)
        if len(rows) < 20 or len(matches) == previous:
            break
        page += 1
    return list(matches.values())


def wiki(page, prop):
    result = get(WIKI, action="parse", page=page, prop=prop, redirects=1,
                 format="json", formatversion=2)
    if "parse" not in result:
        raise LookupFailure("WIKI_PAGE_MISSING")
    return result["parse"][prop]


def wiki_html(page):
    url = "https://onepiece.fandom.com/wiki/" + quote(page.replace(" ", "_"))
    response = requests.get(url, timeout=(6, 15), headers={"User-Agent": "OnePieceWatchPlanner/1.1"})
    response.raise_for_status()
    return response.text


def wiki_debut(name):
    try:
        document = wiki(name, "text")
    except (requests.RequestException, LookupFailure):
        document = wiki_html(name)
    root = html.fromstring(document)
    fields = root.xpath('//*[@data-source and contains(translate(@data-source,"DEBUT","debut"),"debut")]')
    if not fields:
        fields = root.xpath('//*[contains(@class,"pi-data")][./*[starts-with(normalize-space(.),"Debut")]]')
    for field in fields:
        match = re.search(r"\bEpisode\s+(\d+)\b", " ".join(field.itertext()), re.I)
        if match:
            number = int(match[1])
            break
    else:
        raise LookupFailure("NO_ANIME_DEBUT")
    return number


def debut(character):
    if isinstance(character, dict) and character.get("from_catalog"):
        details = characters({"id": character["id"]})
        if not details:
            raise LookupFailure("NO_RESULTS")
        character = details[0]
    name = character["name"] if isinstance(character, dict) else character
    appearance = character.get("first_appearance", "") if isinstance(character, dict) else ""
    explicit = re.search(r"\bEpisode\s+(\d+)\b", appearance, re.I)
    if explicit:
        number = int(explicit[1])
        origin = f"https://www.onepieceapi.com/characters/{character['id']}"
    elif name in DEBUT_INDEX:
        number = DEBUT_INDEX[name]
        origin = INDEX_SOURCE
    else:
        number = wiki_debut(name)
        origin = "https://onepiece.fandom.com/wiki/" + quote(name.replace(" ", "_"))
    detail_url = f"https://api.api-onepiece.com/v2/episodes/en/{number}"
    try:
        row = get(detail_url)
        tagged = re.fullmatch(r"(?:n[°º]\s*)?(\d+)", str(row.get("number", "")).strip(), re.I)
        if tagged and int(tagged[1]) == number and row.get("release_date"):
            airdate = datetime.strptime(row["release_date"], "%Y-%m-%d").date().isoformat()
            return {"episode": number, "titles": [row["title"]] if row.get("title") else [],
                    "airdate": airdate, "character_source": origin, "source": detail_url}
    except (requests.RequestException, LookupFailure, ValueError, AttributeError):
        pass
    page = f"Episode {number}"
    try:
        raw = wiki(page, "wikitext")
    except (requests.RequestException, LookupFailure):
        raw = ""

    titles = re.findall(r"^\|\s*(?:Translation|English|Funimation)\s*=[ \t]*([^\r\n]+)", raw, re.M | re.I)
    date_match = re.search(r"^\|[ \t]*(?:airdate|air date|aired)[ \t]*=[ \t]*([A-Z][a-z]+ \d{1,2}, \d{4})", raw, re.M | re.I)
    airdate = datetime.strptime(date_match[1], "%B %d, %Y").date().isoformat() if date_match else None
    if not airdate:
        # 영문 번역과 더빙 제목이 다를 때 일본 첫 방영일로 같은 회차를 확인한다.
        try:
            episode_page = html.fromstring(wiki_html(page))
            dates = episode_page.xpath('//*[@data-source="airdate" or @data-source="Airdate"]')
            for field in dates:
                match = re.search(r"([A-Z][a-z]+ \d{1,2}, \d{4})", " ".join(field.itertext()))
                if match:
                    airdate = datetime.strptime(match[1], "%B %d, %Y").date().isoformat()
                    break
        except (requests.RequestException, etree.ParserError, ValueError):
            pass
    return {"episode": number, "titles": [t.strip() for t in titles], "airdate": airdate,
            "character_source": origin,
            "source": f"https://onepiece.fandom.com/wiki/Episode_{number}"}


def runtime(episode):
    # 이전 세션의 제목 목록 입력도 지원한다.
    if isinstance(episode, list):
        episode = {"titles": episode}
    titles = {key(s) for s in episode["titles"] if key(s)}
    rows = get(TV)
    if not isinstance(rows, list):
        raise LookupFailure("INVALID_RESPONSE")
    named = [r for r in rows if key(r["name"]) in titles]
    dated = [r for r in rows if episode.get("airdate") and r.get("airdate") == episode["airdate"]]
    candidates = named
    if len(named) > 1:
        candidates = [r for r in named if r in dated]
    if not named:
        regular = [r for r in rows if r.get("type") == "regular"]
        number = episode.get("episode")
        if not isinstance(number, int) or not 1 <= number <= len(regular):
            raise LookupFailure("AMBIGUOUS_EPISODE" if len(dated) > 1 else "NO_EPISODE")
        counts = {}
        for row in regular[:number]:
            season = row["season"]
            counts[season] = counts.get(season, 0) + 1
            if counts[season] != row["number"]:
                raise LookupFailure("EPISODE_SEQUENCE_GAP")
        ordinal = regular[number - 1]
        # 통산 순서에 더해 방영일 또는 특징적인 제목 단어를 독립적으로 대조한다.
        def tokens(title):
            common = {"the","and","with","from","that","this","into","pirate","pirates","episode","one","piece","who","will","for","their"}
            return {w for w in re.findall(r"[a-z]{3,}", title.lower()) if w not in common}
        corroborated = any(len(tokens(t) & tokens(ordinal["name"])) >= 3 for t in episode["titles"])
        if ordinal not in dated and not corroborated:
            raise LookupFailure("EPISODE_CONFLICT")
        candidates = [ordinal]
    if len(candidates) != 1:
        raise LookupFailure("AMBIGUOUS_EPISODE" if candidates else "NO_EPISODE")
    row = candidates[0]
    if not isinstance(row.get("runtime"), int) or row["runtime"] <= 0:
        raise LookupFailure("NO_RUNTIME")
    return {"minutes": row["runtime"], "id": row["id"], "title": row["name"], "source": row["url"]}


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class CharacterID(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID


class CharacterCandidate(BaseModel):
    id: str
    name: Name
    korean_name: str | None = None
    first_appearance: str | None = None
    from_catalog: bool = False


class EpisodeLookup(BaseModel):
    episode: Annotated[int, Field(strict=True, gt=0)] | None = None
    titles: list[str]
    airdate: date | None = None
    character_source: str | None = None
    source: str | None = None


REGISTRY = {"characters": characters, "debut": debut, "runtime": runtime}
INPUTS = {
    "characters": TypeAdapter(Name | CharacterID),
    "debut": TypeAdapter(Name | CharacterCandidate),
    "runtime": TypeAdapter(list[str] | EpisodeLookup),
}
COMMON_ERRORS = ("INVALID_INPUT", "UPSTREAM_ERROR", "RATE_LIMIT", "INVALID_RESPONSE", "NO_RESULTS")
SPECS = {
    "characters": {
        "description": "이름 문자열로 후보 검색 또는 id 객체로 캐릭터 상세 조회",
        "output": "[{id, name, korean_name?, first_appearance?, from_catalog?}]",
        "errors": ("ENGLISH_NAME_REQUIRED", "NAME_REQUIRED"),
    },
    "debut": {
        "description": "선택한 캐릭터의 애니 첫 등장 조회",
        "output": "{episode, titles, airdate, character_source, source}",
        "errors": ("WIKI_PAGE_MISSING", "NO_ANIME_DEBUT"),
    },
    "runtime": {
        "description": "회차 제목과 일본 방영일로 TVmaze 러닝타임 확인",
        "output": "{minutes, id, title, source}",
        "errors": ("NO_EPISODE", "AMBIGUOUS_EPISODE", "EPISODE_SEQUENCE_GAP", "EPISODE_CONFLICT", "NO_RUNTIME"),
    },
}
for tool_name, spec in SPECS.items():
    spec.update(type="external_api", input=INPUTS[tool_name].json_schema(),
                errors=COMMON_ERRORS + spec["errors"])


def call(name, value):
    if name not in REGISTRY:
        return {"ok": False, "error": {"code": "UNKNOWN_TOOL", "message": "등록된 도구가 아닙니다."}}
    try:
        value = INPUTS[name].validate_python(value)
    except ValidationError:
        return {"ok": False, "error": {"code": "INVALID_INPUT", "message": "도구 입력값을 확인해 주세요."}}
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", exclude_unset=True)
    try:
        data = REGISTRY[name](value)
        if not data:
            raise LookupFailure("NO_RESULTS")
        return {"ok": True, "data": data}
    except LookupFailure as exc:
        code = str(exc)
    except requests.RequestException:
        code = "UPSTREAM_ERROR"
    except (KeyError, ValueError, TypeError, AttributeError, etree.ParserError):
        code = "INVALID_RESPONSE"
    return {"ok": False, "error": {"code": code, "message": "외부 자료를 확인할 수 없습니다."}}
