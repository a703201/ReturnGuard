#!/usr/bin/env python3
# Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
# SPDX-License-Identifier: Apache-2.0
"""i18n 键完整性校验（可进 CI）。

校验四件事，任一不满足即退出码 1：
  1. index.html 里每个 data-i18n 键都在**每种语言**字典中存在；
  2. app.js / render.js 里每个 t('key') 调用的键都在每种语言字典中存在
     （含 sevLabel / lvlLabel 这类运行时拼接键，由 EXTRA_KEYS 显式声明）；
  3. 每种语言的键集合与基准语言（zh）完全一致（不允许单侧缺失/多余）；
  4. 每种语言内部无重复键（JS 中后者覆盖前者，是静默漂移隐患）。

背景：i18n 从 30 处标签扩展到「静态 + 动态」共 320+ 键、语言从 zh/en 扩到 zh/en/fr 后，
靠肉眼对账已不可靠。缺键时 t() 会原样返回 key，页面上会出现 'dyn.noSupplier' 这类裸 key，属明显缺陷。

用法：
    python scripts/check_i18n.py
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "demo" / "static"

# 基准语言：其余语言必须与它键集合完全一致。新增语言只需加进 LANGS 即可被自动校验。
BASE_LANG = "zh"
LANGS = ("zh", "en", "fr")

# 运行时拼接的键（sevLabel / lvlLabel 用字典映射拼出），静态正则扫不到，显式声明。
EXTRA_KEYS = {
    "dyn.sev.high",
    "dyn.sev.mid",
    "dyn.sev.low",
    "dyn.lvl.high",
    "dyn.lvl.improve",
    "dyn.lvl.pass",
    "dyn.lvl.top",
}

# 正则误命中：这些是 querySelector / createElement 的标签名，不是 i18n 键。
NOISE_KEYS = {".card", ".col", "div", "mode", "tr", "2d", "a", "option"}


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def parse_dict_blocks(src: str) -> dict[str, list[str]]:
    """按缩进切出每个语言块并提取其键（保留顺序，便于报告重复键）。"""
    blocks: dict[str, list[str]] = {}
    starts = {m.group(1): m.start() for m in re.finditer(r"^  (\w+): \{$", src, re.M)}
    for lang, a in starts.items():
        nxt = [v for v in starts.values() if v > a]
        b = min(nxt) if nxt else len(src)
        blocks[lang] = re.findall(r"^    '([a-zA-Z0-9._]+)':", src[a:b], re.M)
    return blocks


def main() -> int:
    i18n = read(STATIC / "i18n.js")
    blocks = parse_dict_blocks(i18n)

    missing_lang = [lang for lang in LANGS if lang not in blocks]
    if missing_lang:
        print(f"❌ i18n.js 缺少语言块：{missing_lang}")
        return 1

    key_sets = {lang: set(blocks[lang]) for lang in LANGS}
    base = key_sets[BASE_LANG]

    html = read(STATIC / "index.html")
    # data-i18n 覆盖纯文本节点；data-i18n-label 覆盖 <optgroup>（含子元素，只能改 label 属性）。
    html_keys = set(re.findall(r'data-i18n="([^"]+)"', html))
    html_keys |= set(re.findall(r'data-i18n-label="([^"]+)"', html))

    js_keys: set[str] = set()
    for f in ("app.js", "render.js"):
        js_keys |= set(re.findall(r"t\('([a-zA-Z0-9._]+)'\)", read(STATIC / f)))
    js_keys -= NOISE_KEYS
    js_keys |= EXTRA_KEYS

    need = html_keys | js_keys
    errors: list[str] = []

    # 4) 块内重复键
    for lang in LANGS:
        dup = sorted({k for k in blocks[lang] if blocks[lang].count(k) > 1})
        if dup:
            errors.append(f"{lang} 字典存在重复键（后者静默覆盖前者）：{dup}")

    # 3) 各语言与基准键集合一致
    for lang in LANGS:
        if lang == BASE_LANG:
            continue
        only_this = sorted(key_sets[lang] - base)
        only_base = sorted(base - key_sets[lang])
        if only_this or only_base:
            errors.append(f"{BASE_LANG}/{lang} 键集合不一致：{lang}-only={only_this} {BASE_LANG}-only={only_base}")

    # 1)+2) 每种语言都要覆盖全部需要的键
    for lang in LANGS:
        miss = sorted(need - key_sets[lang])
        if miss:
            errors.append(f"{lang} 字典缺键（{len(miss)}）：{miss}")

    unused = sorted(base - need)
    print(f"静态键（index.html data-i18n）：{len(html_keys)}")
    print(f"动态键（app.js/render.js t()）：{len(js_keys)}")
    print(f"合计需键：{len(need)}")
    print("字典键数：" + " ｜ ".join(f"{lang} {len(key_sets[lang])}" for lang in LANGS))
    if unused:
        print(f"⚠️  未被使用的键（{len(unused)}）：{unused}")

    if errors:
        print("\n❌ i18n 校验未通过：")
        for e in errors:
            print("  -", e)
        return 1
    print(f"\n✅ i18n 校验通过：无缺键，{'/'.join(LANGS)} 键集合一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
