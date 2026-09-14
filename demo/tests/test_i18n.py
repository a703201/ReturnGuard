"""多语言本地化回归测试（zh / en / fr）。

守住四类容易静默漂移的问题：
  1. 前端字典（demo/static/i18n.js）三种语言的键集合必须完全一致——
     缺键时 t() 会把裸 key 显示到页面上，属明显缺陷，但不会抛异常；
  2. 每种语言块内部不得有重复键（JS 中后者覆盖前者，改文案时容易漏改一处）；
  3. 后端 constants.TTS_VOICES 的语言清单必须包含前端可选语言，且音色映射确定；
  4. /static 资源必须下发 no-cache——前端 ESM 无法给子模块带版本 query，
     若允许浏览器窗口期内直接用本地副本，升级后会出现「HTML 新 / JS 旧」的撕裂，
     表现为新增语言选项可见但切换无效（曾实际发生）。

不再依赖模型 Key，也不需要外网。
"""

from __future__ import annotations

import re
from pathlib import Path

from constants import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, tts_voice_for
from fastapi.testclient import TestClient
from main import app

STATIC = Path(__file__).resolve().parent.parent / "static"
LANGS = ("zh", "en", "fr")
LOCALE_BY_LANG = {"zh": "zh-CN", "en": "en-US", "fr": "fr-FR"}


def _blocks() -> dict[str, str]:
    """按 `  xx: {` 缩进切出各语言块源码。"""
    src = (STATIC / "i18n.js").read_text(encoding="utf-8")
    starts = {m.group(1): m.start() for m in re.finditer(r"^  (\w+): \{$", src, re.M)}
    out: dict[str, str] = {}
    for lang, a in starts.items():
        nxt = [v for v in starts.values() if v > a]
        out[lang] = src[a : min(nxt) if nxt else len(src)]
    return out


def _keys(block: str) -> list[str]:
    return re.findall(r"^    '([a-zA-Z0-9._]+)':", block, re.M)


def test_all_langs_present():
    blocks = _blocks()
    assert set(LANGS) <= set(blocks), f"i18n.js 缺少语言块：{sorted(set(LANGS) - set(blocks))}"


def test_key_sets_identical_across_langs():
    blocks = _blocks()
    sets = {lang: set(_keys(blocks[lang])) for lang in LANGS}
    base = sets["zh"]
    for lang in LANGS:
        if lang == "zh":
            continue
        assert sets[lang] == base, (
            f"{lang} 与 zh 键集合不一致：{lang}-only={sorted(sets[lang] - base)} zh-only={sorted(base - sets[lang])}"
        )


def test_no_duplicate_keys_within_block():
    blocks = _blocks()
    for lang in LANGS:
        keys = _keys(blocks[lang])
        dup = sorted({k for k in keys if keys.count(k) > 1})
        assert not dup, f"{lang} 字典存在重复键：{dup}"


def test_locale_key_matches_language():
    """locale 键驱动 toLocaleString 的数字/日期格式，必须与语言对应（否则法语界面会显示中文日期格式）。"""
    blocks = _blocks()
    for lang in LANGS:
        m = re.search(r"^    'locale': '([^']+)'", blocks[lang], re.M)
        assert m, f"{lang} 缺少 locale 键"
        assert m.group(1) == LOCALE_BY_LANG[lang], (
            f"{lang} locale={m.group(1)}，应为 {LOCALE_BY_LANG[lang]}"
        )


def test_lang_selector_offers_all_langs():
    """界面语言选择器必须列出全部受支持语言，否则用户切不到。"""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    m = re.search(r'<select id="langSel".*?</select>', html, re.S)
    assert m, "index.html 未找到 #langSel"
    options = re.findall(r'<option value="(\w+)"', m.group(0))
    assert options == list(LANGS), f"语言选择器选项 {options}，应为 {list(LANGS)}"


def test_backend_covers_all_frontend_langs():
    for lang in LANGS:
        assert lang in SUPPORTED_LANGUAGES, f"后端 SUPPORTED_LANGUAGES 缺少 {lang}"
    assert DEFAULT_LANGUAGE == "zh"


def test_french_voice_is_deterministic():
    """法语必须有明确音色，且与英语不同（否则听感语言错位）。"""
    fr = tts_voice_for("fr")
    assert fr, "fr 无音色映射"
    assert fr != tts_voice_for("en") or fr != tts_voice_for("zh")


def test_unknown_language_falls_back_to_default_voice():
    assert tts_voice_for("xx-not-a-lang") == tts_voice_for(DEFAULT_LANGUAGE)


def test_static_assets_must_revalidate():
    """回归：/static/* 不得带 max-age，否则升级后浏览器会继续执行旧版 JS。

    曾经为省带宽下发 `max-age=60, must-revalidate`，导致新增法语选项在 HTML 里可见、
    但 i18n.js 仍是旧版（无 fr 块），切语言无效且下拉显示裸 key `lang.fr`。
    """
    with TestClient(app) as c:
        r = c.get("/static/i18n.js")
        assert r.status_code == 200
        cc = r.headers.get("cache-control", "")
        assert "no-cache" in cc, f"/static/i18n.js Cache-Control={cc!r}，应为 no-cache"
        assert "max-age" not in cc, f"/static 不应带 max-age（会导致旧 JS 被继续执行）：{cc!r}"


def test_index_page_is_not_cached():
    with TestClient(app) as c:
        r = c.get("/")
        assert r.status_code == 200
        assert "no-cache" in r.headers.get("cache-control", "")


def test_entry_form_enum_values_are_not_translated():
    """本地化的是「显示文案」，不是表单 value——value 是入库枚举契约。

    outcome / same_item 的 value 直接写入数据库（db.py 注释：赢/部分退款/输/未知），
    若把 value 一起翻译，录入数据会变成英文/法文枚举，聚合与筛选全部失效。
    """
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for v in ("赢", "部分退款", "输", "待分析"):
        assert f'value="{v}"' in html, f"outcome 枚举 value={v} 丢失（疑似被翻译）"
    assert 'name="same_item"' in html
    assert 'value="true"' in html and 'value="false"' in html


def test_optgroup_labels_use_label_attribute():
    """<optgroup> 含 <option> 子元素，只能挂 data-i18n-label（改 label 属性）。

    若误用 data-i18n，applyI18n 的 textContent 会把整组选项清空。
    """
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for key in (
        "entry.supGood",
        "entry.supRisk",
        "entry.platMain",
        "entry.platEmerging",
        "entry.platDataset",
    ):
        assert f'data-i18n-label="{key}"' in html, f"optgroup 缺少 data-i18n-label={key}"
    # optgroup 上不得出现 data-i18n（会清空子项）
    for m in re.finditer(r"<optgroup[^>]*>", html):
        assert "data-i18n=" not in m.group(0), f"optgroup 误用 data-i18n：{m.group(0)}"
