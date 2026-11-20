"""갱신 후 서버를 재시작한다. 공식 웹 목록의 총수·ID가 일치할 때만 파일을 교체한다."""
import json
import os
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID

import requests
from lxml import html

SITE = "https://www.onepieceapi.com"
DEST = Path(__file__).with_name("character-catalog.json")


def fetch(path, **params):
    for attempt in range(3):
        try:
            response = requests.get(SITE + path, params=params, timeout=(10, 30))
            response.raise_for_status()
            return response
        except requests.HTTPError as error:
            if error.response.status_code < 500 or attempt == 2:
                raise
        except (requests.Timeout, requests.ConnectionError):
            if attempt == 2:
                raise


def listing(page):
    doc = html.fromstring(fetch("/characters", page=page).content)
    links = doc.xpath('//a[starts-with(@href,"/characters/")]/@href')
    ids = {str(UUID(link.rsplit("/",1)[1])) for link in links}
    info = re.search(r"Page\s+(\d+)\s+of\s+(\d+)\s*·\s*showing\s+\d+\s+characters?\s+of\s+([\d,]+)", " ".join(doc.text_content().split()))
    if not info or int(info[1]) != page:
        raise ValueError("공식 목록의 페이지 번호·총수를 확인할 수 없습니다.")
    return ids, int(info[2]), int(info[3].replace(",", ""))


def detail(uid):
    row = fetch("/api/characters/"+uid).json()
    if row["id"] != uid or not row.get("name"):
        raise ValueError("캐릭터 상세 응답을 확인할 수 없습니다.")
    return uid, row["name"]


def sync():
    first, pages, total = listing(1)
    ids = set(first)
    with ThreadPoolExecutor(max_workers=4) as pool:
        for found, page_count, count in pool.map(listing, range(2,pages+1)):
            if (page_count,count) != (pages,total):
                raise ValueError("수집 중 목록 크기가 바뀌었습니다. 다시 실행하세요.")
            ids.update(found)
        if len(ids) != total or not ids:
            raise ValueError(f"ID 수 {len(ids)} / 공식 총수 {total}. 기존 목록을 보존합니다.")
        existing = json.loads(DEST.read_text(encoding="utf8")) if DEST.exists() else {}
        catalog = {uid:names for uid,names in existing.items() if uid in ids}
        catalog.update(pool.map(detail, sorted(ids - catalog.keys())))
    from korean_names import readings, spell
    for names in catalog.values():
        if not readings(names) and not spell(names.get("en") or names.get("romaji") or ""):
            raise ValueError(f"한글 이름 생성 실패: {names}")
    with tempfile.NamedTemporaryFile(mode="w",dir=DEST.parent,encoding="utf8",delete=False) as tmp:
        json.dump(catalog,tmp,ensure_ascii=False,sort_keys=True)
    os.replace(tmp.name,DEST)
    print(f"{len(catalog)} / {total}명 동기화 완료")


if __name__ == "__main__":
    sync()
