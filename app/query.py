from __future__ import annotations

import json
import os
import re
import unicodedata

from . import paths

_FILENAME = "query_roles.json"

_BUILTIN_WORDS = {
    "QUALITY": [
        "2160p", "1440p", "1080p", "1080i", "720p", "480p", "4k", "uhd", "8k",
        "bluray", "blu-ray", "bdrip", "brrip", "web-dl", "webdl", "webrip",
        "hdtv", "hdrip", "dvdrip", "remux", "bdmv", "hdr", "sdr", "10bit",
    ],
    "CODEC": [
        "x264", "x265", "h264", "h265", "h.264", "h.265", "hevc", "av1",
        "xvid", "vc1", "vc-1", "mpeg2",
    ],
    "AUDIO": [
        "atmos", "truehd", "dts", "ddp", "aac", "flac", "dolby", "5.1", "7.1",
    ],
    "LANG": [
        "中字", "中文字幕", "中英", "简中", "简体", "繁中", "繁體", "粤语", "粵語",
        "广东话", "廣東話", "双语", "雙語", "国语", "國語", "普通话", "chs", "cht",
        "gb", "big5",
    ],
    "TYPE": [
        "电影", "影片", "movie", "film", "游戏", "遊戲", "game", "单机", "單機",
        "动漫", "動漫", "动画", "動畫", "anime", "剧集", "劇集", "电视剧", "電視劇",
        "音乐", "音樂", "软件", "軟體", "电子书",
    ],
    "GENRE": [
        "射击", "射擊", "第三人称", "第三人稱", "第一人称", "第一人稱", "开放世界",
        "開放世界", "像素", "沙盒", "策略", "策略", "动作", "動作", "冒险", "冒險",
        "角色扮演", "恐怖", "喜剧", "喜劇", "科幻", "爱情", "愛情", "悬疑", "懸疑",
        "3d", "2d", "vr", "回合制", "即时", "即時",
    ],
    "MISC": [
        "合集", "全集", "完结", "完結", "未删减", "未刪減", "加长版", "加長版",
        "珍藏版", "修复", "修復", "batch", "pack", "complete", "proper", "repack",
    ],
}

_BUILTIN_VARIANTS = {
    "4k": ["2160p", "uhd", "2160", "4kuhd"],
    "2160p": ["4k", "uhd", "2160"],
    "1440p": ["2k", "qhd"],
    "1080p": ["fhd", "fullhd", "1920x1080"],
    "720p": ["hd", "1280x720"],
    "bluray": ["blu-ray", "bd", "bdrip", "brrip"],
    "blu-ray": ["bluray", "bd", "bdrip", "brrip"],
    "web-dl": ["webdl", "webrip", "web dl"],
    "webdl": ["web-dl", "webrip"],
    "webrip": ["web-dl", "webdl"],
    "remux": ["bdmv"],
    "x265": ["hevc", "h265", "h.265"],
    "x264": ["h264", "h.264", "avc"],
    "hevc": ["x265", "h265", "h.265"],
    "中字": ["中文字幕", "简中", "简体中文", "chs", "gb", "中文", "国语", "普通话"],
    "粤语": ["粵語", "广东话", "廣東話", "cantonese"],
    "粵語": ["粤语", "广东话", "廣東話", "cantonese"],
    "双语": ["雙語", "中英", "bilingual"],
    "电影": ["影片", "movie", "film"],
    "影片": ["电影", "movie", "film"],
    "movie": ["电影", "影片", "film"],
    "游戏": ["遊戲", "game", "单机"],
    "遊戲": ["游戏", "game", "单机"],
    "game": ["游戏", "遊戲"],
    "动漫": ["動漫", "动画", "動畫", "anime"],
    "动画": ["動漫", "动漫", "動畫", "anime"],
    "第三人称": ["第三人稱", "third person", "third-person", "tps", "3rd person"],
    "第三人稱": ["第三人称", "third person", "third-person", "tps"],
    "射击": ["射擊", "shooter", "fps", "tps"],
    "开放世界": ["開放世界", "open world", "openworld"],
}

_YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_ASCII_RE = re.compile(r"^[\x20-\x7f]+$")
_SPACE_RE = re.compile(r"\s+")
_SEP_RE = re.compile(r"[_+,/|]+")

_CACHE = None


def reload() -> None:
    global _CACHE
    _CACHE = None


def _load() -> dict:
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    words = {k: list(v) for k, v in _BUILTIN_WORDS.items()}
    variants = {k: list(v) for k, v in _BUILTIN_VARIANTS.items()}

    try:
        path = os.path.join(str(paths.data_dir()), _FILENAME)
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        raw = None

    if isinstance(raw, dict):
        got = raw.get("words")
        if isinstance(got, dict):
            for role, items in got.items():
                if isinstance(items, list) and items:
                    words[str(role)] = [str(x).strip().lower()
                                        for x in items if str(x).strip()]
        got = raw.get("variants")
        if isinstance(got, dict):
            for key, forms in got.items():
                if isinstance(forms, list) and forms:
                    variants[str(key).strip().lower()] = [
                        str(x).strip().lower() for x in forms if str(x).strip()]

    _CACHE = {"words": words, "variants": variants}
    return _CACHE


def normalize(text) -> str:
    s = unicodedata.normalize("NFKC", str(text or ""))
    s = s.lower()
    s = _SEP_RE.sub(" ", s)
    s = _SPACE_RE.sub(" ", s)
    return s.strip()


def bigrams(text) -> list[str]:
    s = _SPACE_RE.sub("", str(text or ""))
    if len(s) < 2:
        return [s] if s else []
    out = []
    for i in range(len(s) - 1):
        piece = s[i:i + 2]
        if piece not in out:
            out.append(piece)
    return out


def _uniq(values) -> list[str]:
    out = []
    for v in values:
        s = str(v or "").strip()
        if s and s not in out:
            out.append(s)
    return out


def _contains(token: str, word: str) -> bool:
    if not word:
        return False
    if _ASCII_RE.match(word):
        return re.search(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])",
                         token) is not None
    return word in token


_SEASON_PATTERNS = (
    (re.compile(r"(?i)^s(\d{1,2})e(\d{1,3})$"), "se"),
    (re.compile(r"(?i)^s(\d{1,2})$"), "s"),
    (re.compile(r"^第(\d+)[集话話]$"), "e"),
    (re.compile(r"^第(\d+)季$"), "s"),
    (re.compile(r"(?i)^ep?(\d{1,3})$"), "e"),
    (re.compile(r"(?i)^season(\d{1,2})$"), "s"),
)


def _season_of(token: str):
    for pat, kind in _SEASON_PATTERNS:
        m = pat.match(token)
        if not m:
            continue
        if kind == "se":
            return {"s": int(m.group(1)), "e": int(m.group(2))}
        if kind == "s":
            return {"s": int(m.group(1)), "e": 0}
        return {"s": 0, "e": int(m.group(1))}
    return None


def _season_forms(picked: dict) -> list[str]:
    s = picked["s"]
    e = picked["e"]
    forms = []
    if s and e:
        forms += ["s%de%d" % (s, e), "s%02de%02d" % (s, e),
                  "s%02d e%02d" % (s, e), "e%d" % e, "ep%d" % e]
    elif s:
        forms += ["s%d" % s, "s%02d" % s, "season %d" % s, "第%d季" % s]
    elif e:
        forms += ["第%d集" % e, "第%d话" % e, "第%d話" % e,
                  "e%d" % e, "e%02d" % e, "ep%d" % e]
    return _uniq(forms)


def parse(query) -> dict:
    text = normalize(query)
    table = _load()
    words = table["words"]
    variants = table["variants"]

    flat = []
    for role, items in words.items():
        for w in items:
            flat.append((w, role))

    subject: list[str] = []
    mods: list[dict] = []
    soft: list[dict] = []
    season = None
    year = None

    tokens = [t for t in text.split(" ") if t]
    for token in tokens:
        picked = _season_of(token)
        if picked:
            season = picked
            mods.append({"role": "SEASON", "text": token,
                         "forms": _season_forms(picked),
                         "s": picked["s"], "e": picked["e"]})
            continue

        m = _YEAR_RE.search(token)
        if m and len(token) <= 4:
            year = int(m.group(0))
            mods.append({"role": "YEAR", "text": token,
                         "forms": _uniq([m.group(0)])})
            continue

        hits = [w for w, _role in flat if _contains(token, w)]
        if not hits:
            subject.append(token)
            continue

        role = ""
        for w, r in flat:
            if w in hits:
                role = r
                break

        forms = [token] + hits
        for w in hits:
            forms.extend(variants.get(w, []))
        forms.extend(variants.get(token, []))

        entry = {"text": token, "forms": _uniq(forms)}
        if role in ("QUALITY", "CODEC"):
            entry["role"] = role
            mods.append(entry)
        else:
            entry["kind"] = role
            soft.append(entry)

    grams = []
    for t in subject:
        for b in bigrams(t):
            if b not in grams:
                grams.append(b)
    if not subject:
        grams = bigrams(text)

    return {
        "raw": str(query or ""),
        "text": text,
        "tokens": tokens,
        "subject": subject,
        "bigrams": grams,
        "mods": mods,
        "soft": soft,
        "season": season,
        "year": year,
        "browse": not subject,
    }
