"""API 이름의 가나 독음을 검색용 한글로 전사한다. 국내판 이름은 aliases.json이 우선한다."""
import re
import unicodedata

KANA = {}
for jp, ko in [
    ("あいうえお", "아 이 우 에 오"), ("かきくけこ", "카 키 쿠 케 코"),
    ("がぎぐげご", "가 기 구 게 고"), ("さしすせそ", "사 시 스 세 소"),
    ("ざじずぜぞ", "자 지 즈 제 조"), ("たちつてと", "타 치 츠 테 토"),
    ("だぢづでど", "다 지 즈 데 도"), ("なにぬねの", "나 니 누 네 노"),
    ("はひふへほ", "하 히 후 헤 호"), ("ばびぶべぼ", "바 비 부 베 보"),
    ("ぱぴぷぺぽ", "파 피 푸 페 포"), ("まみむめも", "마 미 무 메 모"),
    ("やゆよ", "야 유 요"), ("らりるれろ", "라 리 루 레 로"),
    ("わゐゑを", "와 이 에 오"), ("ぁぃぅぇぉゃゅょゎゔ", "아 이 우 에 오 야 유 요 와 부"),
]:
    KANA.update(zip(jp, ko.split()))
for jp, ko in [
    ("き","캬 큐 쿄"),("ぎ","갸 규 교"),("し","샤 슈 쇼"),("じ","자 주 조"),
    ("ち","차 추 초"),("に","냐 뉴 뇨"),("ひ","햐 휴 효"),("び","뱌 뷰 뵤"),
    ("ぴ","퍄 퓨 표"),("み","먀 뮤 묘"),("り","랴 류 료"),
]:
    KANA.update(zip([jp+s for s in "ゃゅょ"], ko.split()))
KANA.update(dict(zip("ふぁ ふぃ ふぇ ふぉ てぃ でぃ とぅ どぅ しぇ じぇ ちぇ つぁ つぃ つぇ つぉ うぃ うぇ うぉ ゔぁ ゔぃ ゔぇ ゔぉ てゅ でゅ ふゅ".split(),
                     "파 피 페 포 티 디 투 두 셰 제 체 차 치 체 초 위 웨 워 바 비 베 보 튜 듀 퓨".split())))


def from_kana(text):
    text = unicodedata.normalize("NFKC", text)
    text = "".join(chr(ord(c)-96) if "ァ" <= c <= "ヶ" else c for c in text)
    result = []
    i = 0
    while i < len(text):
        c = text[i]
        pair = text[i:i+2]
        if len(pair) == 2 and pair in KANA:
            result.append(KANA[pair])
            i += 2
            continue
        if c in KANA:
            result.append(KANA[c])
        elif c in "んっ":
            if result and "가" <= result[-1] <= "힣" and (ord(result[-1])-0xac00)%28 == 0:
                result[-1] = chr(ord(result[-1]) + (4 if c == "ん" else 19))
            else:
                result.append("응" if c == "ん" else "읏")
        elif c in "・· =　":
            result.append(" ")
        elif c not in "ー~〜":
            # 한자나 라틴 문자는 전체를 확인할 수 있을 때만 별칭으로 등록한다.
            return ""
        i += 1
    return " ".join("".join(result).split())


LETTERS = "에이 비 씨 디 이 에프 지 에이치 아이 제이 케이 엘 엠 엔 오 피 큐 알 에스 티 유 브이 더블유 엑스 와이 지".split()
DIGITS = "영 일 이 삼 사 오 육 칠 팔 구".split()


def spell(name):
    parts = []
    for c in unicodedata.normalize("NFKD", name).lower():
        if "a" <= c <= "z":
            parts.append(LETTERS[ord(c)-97])
        elif "0" <= c <= "9":
            parts.append(DIGITS[int(c)])
    return "".join(parts)


def readings(names):
    jp = names.get("jp") or ""
    parts = re.findall(r"[ァ-ヺぁ-ゖー・]+", unicodedata.normalize("NFKC", jp))
    direct = from_kana(jp)
    romaji = names.get("romaji") or ""
    return [s for s in (direct, from_kana(parts[-1]) if parts and ("(" in jp or "（" in jp) else "",
                         from_romaji(romaji), from_romaji(names.get("en") or "")) if s]


ROMAJI = {}
for jp, syllables in [
    ("あいうえお", "a i u e o"), ("かきくけこ","ka ki ku ke ko"), ("がぎぐげご","ga gi gu ge go"),
    ("さしすせそ","sa shi su se so"), ("ざじずぜぞ","za ji zu ze zo"), ("たちつてと","ta chi tsu te to"),
    ("だぢづでど","da di du de do"), ("なにぬねの","na ni nu ne no"), ("はひふへほ","ha hi fu he ho"),
    ("ばびぶべぼ","ba bi bu be bo"), ("ぱぴぷぺぽ","pa pi pu pe po"), ("まみむめも","ma mi mu me mo"),
    ("やゆよ","ya yu yo"), ("らりるれろ","ra ri ru re ro"), ("わを","wa wo"),
]:
    ROMAJI.update(zip(syllables.split(),jp))
for prefix, jp in [("ky","き"),("gy","ぎ"),("sh","し"),("j","じ"),("ch","ち"),("ny","に"),
                   ("hy","ひ"),("by","び"),("py","ぴ"),("my","み"),("ry","り")]:
    for v, ending in zip("auo","ゃゅょ"):
        ROMAJI[prefix+v] = jp+ending
ROMAJI.update(dict(zip("ti fa fi fe fo wi we wo she je che".split(),"てぃ ふぁ ふぃ ふぇ ふぉ うぃ うぇ うぉ しぇ じぇ ちぇ".split())))


def from_romaji(name):
    if not name or name.lower() in ("n/a","unknown"):
        return ""
    text = "".join(c for c in unicodedata.normalize("NFKD", name.lower()) if not unicodedata.combining(c))
    result = []
    i = 0
    while i < len(text):
        c = text[i]
        if c in " -.,;'’/&":
            if c not in "'’":
                result.append(" ")
            i += 1
            continue
        if c == "n" and (i+1 == len(text) or text[i+1] not in "aeiouy"):
            result.append("ん")
            i += 1
            continue
        if c not in "aeiou" and text[i:i+2] == c*2:
            result.append("っ")
            i += 1
            continue
        for length in (3,2,1):
            part = text[i:i+length]
            if len(part)==length and part in ROMAJI:
                result.append(ROMAJI[part])
                i += length
                break
        else:
            return ""
    return from_kana("".join(result))
