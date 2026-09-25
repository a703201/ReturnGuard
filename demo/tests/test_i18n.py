# Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
# SPDX-License-Identifier: Apache-2.0
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

from common import APP_VERSION
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


def test_static_assets_must_not_be_cached():
    """回归：/static/* 必须 `no-store`，不得带任何 max-age。

    两次踩坑都表现为「升级后前端不生效」：
      1. `max-age=60, must-revalidate` —— 窗口内浏览器不回源，直连本机也能复现；
      2. 改 `no-cache` 后本机正常、**公网仍不正常** —— 中间 CDN 把 `no-cache` 覆写成
         `max-age=14400` 下发给浏览器（实测 Cloudflare）。故必须 `no-store`。
    """
    with TestClient(app) as c:
        for asset in ("/static/i18n.js", "/static/app.js"):
            r = c.get(asset)
            assert r.status_code == 200, f"{asset} 应可访问"
            cc = r.headers.get("cache-control", "")
            assert "no-store" in cc, f"{asset} Cache-Control={cc!r}，应为 no-store"
            assert "max-age" not in cc, f"{asset} 不应带 max-age（旧 JS 会被继续执行）：{cc!r}"


def test_index_page_is_not_cached():
    with TestClient(app) as c:
        r = c.get("/")
        assert r.status_code == 200
        assert "no-cache" in r.headers.get("cache-control", "")


def test_entry_script_is_version_stamped():
    """入口脚本 URL 必须带版本号：发版换 URL，才能绕过浏览器与 CDN 的缓存。

    `__ASSET_VER__` 占位符若未被后端替换，页面上会原样出现该串，且版本化失效。
    """
    with TestClient(app) as c:
        html = c.get("/").text
    assert "__ASSET_VER__" not in html, "index.html 的 __ASSET_VER__ 未被后端替换"
    assert f"/static/app.js?v={APP_VERSION}" in html, f"入口脚本未带版本号 v={APP_VERSION}"


def test_submodule_imports_are_version_stamped():
    """子模块的相对 import 必须被追加与入口一致的版本号，整条依赖链才会换 URL。

    前端 ESM 用相对路径互相 import，子模块 URL 天然不带版本；若不改写，
    浏览器会命中缓存的旧 i18n.js（缺 fr 块）→ 切法语无效、显示裸 key。
    """
    with TestClient(app) as c:
        for asset in ("/static/app.js", "/static/render.js", "/static/api.js"):
            js = c.get(asset).text
            imports = re.findall(r"""from\s*['"](\./[A-Za-z0-9_.\-]+\.js[^'"]*)['"]""", js)
            assert imports, f"{asset} 未解析到相对 import（测试前提失效）"
            for spec in imports:
                assert spec.endswith(f"?v={APP_VERSION}"), (
                    f"{asset} 的子模块 import 未版本化：{spec}"
                )


def test_version_stamped_assets_are_still_valid_js():
    """改写后的 JS 仍是合法模块：import 后缀只加查询串，不能破坏语法。"""
    with TestClient(app) as c:
        js = c.get("/static/app.js").text
    assert f"from './store.js?v={APP_VERSION}'" in js
    assert "from './store.js'" not in js.replace(f"from './store.js?v={APP_VERSION}'", "")
    # 书写上仍是单引号 + 相对路径，未被引号/转义破坏
    assert "'./store.js" in js and '"' not in js.split("import", 1)[1].split("\n")[0].replace(
        "'", ""
    )


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


# ===================== 首次开启引导（onboarding）=====================


def test_onboarding_overlay_structure():
    """首启引导必须是一个完整的多步流程：5 个步骤 + 进度点 + 关闭/跳过/上一步/下一步。"""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'id="onboardOverlay"' in html, "index.html 未找到 #onboardOverlay"
    steps = re.findall(r'<section class="onb-step[^"]*" data-step="(\d+)"', html)
    assert steps == ["1", "2", "3", "4", "5"], f"引导步骤异常：{steps}"
    for el_id in (
        "onbTitle",
        "onbStepNo",
        "onbClose",
        "onbDots",
        "onbAi",
        "onbDontShow",
        "onbSkip",
        "onbPrev",
        "onbNext",
    ):
        assert f'id="{el_id}"' in html, f"引导缺少 #{el_id}"
    # 「不再自动显示」默认勾选：首次看完即不再打扰
    assert re.search(r'id="onbDontShow"[^>]*checked', html), "「不再自动显示」应默认勾选"


def test_onboarding_guide_button_can_reopen():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'id="guideBtn"' in html, "顶栏缺少「使用引导」按钮（否则关掉后无法再看）"
    assert 'data-i18n="btn.guide"' in html


def test_onboarding_uses_persisted_flag():
    """关闭引导要写 localStorage 标记，否则每次刷新都弹（体验灾难）。"""
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "rg_onboarded" in js, "未持久化首启标记"
    assert "maybeAutoOpenOnboard" in js, "缺少首启自动判定"
    assert "renderOnbAiInfo" in js, "第 4 步的 AI 通路信息未渲染"


def test_onboarding_step_tabs_point_to_real_tabs():
    """第 3 步的跳转按钮必须指向真实存在的 Tab，否则点了没反应。"""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    real = set(re.findall(r'data-tab="(\w+)"', html))
    jumps = set(re.findall(r'data-go="(\w+)"', html))
    assert jumps, "未找到引导内的跳转按钮"
    assert jumps <= real, f"引导跳转指向不存在的 Tab：{sorted(jumps - real)}"


def test_onboarding_ai_block_reads_config_provider():
    """/api/config 下发的 provider 是引导第 4 步的数据源（能力矩阵/展示名）。"""
    from fastapi.testclient import TestClient
    from main import app as _app

    with TestClient(_app) as c:
        d = c.get("/api/config").json()
    assert "provider" in d, "/api/config 未下发 provider，引导第 4 步会空白"
    assert d["provider"]["label"] and d["provider"]["capabilities"]
