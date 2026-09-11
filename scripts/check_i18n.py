#!/usr/bin/env python3
"""i18n 键完整性校验（可进 CI）。

校验三件事，任一不满足即退出码 1：
  1. index.html 里每个 data-i18n 键都在 zh / en 字典中存在；
  2. app.js / render.js 里每个 t('key') 调用的键都在 zh / en 字典中存在
     （含 sevLabel / lvlLabel 这类运行时拼接键，由 EXTRA_KEYS 显式声明）；
  3. zh 与 en 字典的键集合完全一致（不允许单侧缺失）。

背景：i18n 从 30 处标签扩展到「116 静态 + 185 动态」共 300+ 键后，靠肉眼对账已不可靠。
缺键时 t() 会原样返回 key，页面上会出现 'dyn.noSupplier' 这类裸 key，属明显缺陷。

用法：
    python scripts/check_i18n.py
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "demo" / "static"

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


def main() -> int:
    i18n = read(STATIC / "i18n.js")
    split = i18n.find("  en: {")
    if split < 0:
        print("❌ i18n.js 未找到 en 字典")
        return 1
    zh = set(re.findall(r"'([a-zA-Z0-9._]+)':", i18n[:split]))
    en = set(re.findall(r"'([a-zA-Z0-9._]+)':", i18n[split:]))

    html_keys = set(re.findall(r'data-i18n="([^"]+)"', read(STATIC / "index.html")))

    js_keys: set[str] = set()
    for f in ("app.js", "render.js"):
        js_keys |= set(re.findall(r"t\('([a-zA-Z0-9._]+)'\)", read(STATIC / f)))
    js_keys -= NOISE_KEYS
    js_keys |= EXTRA_KEYS

    need = html_keys | js_keys
    errors: list[str] = []

    if zh != en:
        errors.append(f"zh/en 键集合不一致：zh-only={sorted(zh - en)} en-only={sorted(en - zh)}")

    miss_zh = sorted(need - zh)
    miss_en = sorted(need - en)
    if miss_zh:
        errors.append(f"zh 字典缺键（{len(miss_zh)}）：{miss_zh}")
    if miss_en:
        errors.append(f"en 字典缺键（{len(miss_en)}）：{miss_en}")

    unused = sorted((zh | en) - need)
    print(f"静态键（index.html data-i18n）：{len(html_keys)}")
    print(f"动态键（app.js/render.js t()）：{len(js_keys)}")
    print(f"合计需键：{len(need)} ｜ zh 字典 {len(zh)} 键 ｜ en 字典 {len(en)} 键")
    if unused:
        print(f"⚠️  未被使用的键（{len(unused)}）：{unused}")

    if errors:
        print("\n❌ i18n 校验未通过：")
        for e in errors:
            print("  -", e)
        return 1
    print("\n✅ i18n 校验通过：无缺键，zh/en 完全一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
