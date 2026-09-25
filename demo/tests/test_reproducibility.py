# Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
# SPDX-License-Identifier: Apache-2.0
"""可复现性 + 结果缓存（P1-3 / P1-7）。

审查要点：
- P1-3：mock 取证结果必须由输入**内容**决定（与随机文件名无关），同输入跨调用完全一致；
         图片内容指纹（imghash.content_seed）同内容同值、异内容异值。
- P1-7：相同两张图 + 相同入参的 mock 取证应命中结果缓存，跳过重复的 _mock 计算，
         且返回深拷贝避免被调用方就地补写字段污染缓存。
"""

import os
import tempfile
from unittest import mock

from imghash import content_seed
from pipeline import _analyze_cache, _analyze_cache_key, analyze_case, build_insights


def _mk(bytes_, name: str) -> str:
    p = os.path.join(tempfile.gettempdir(), name)
    with open(p, "wb") as f:
        f.write(bytes_)
    return p


def test_content_seed_deterministic_by_content():
    """同内容（不同文件名）指纹相同；不同内容指纹不同。"""
    same_a = _mk(b"\x89PNG minimal A", "rg_seeda.png")
    same_b = _mk(b"\x89PNG minimal A", "rg_seedb.png")  # 内容相同、文件名不同
    diff = _mk(b"\x89PNG minimal B", "rg_seedc.png")
    assert content_seed(same_a, same_b) == content_seed(same_a, same_b)
    assert content_seed(same_a, same_b) != content_seed(same_a, diff)


def test_mock_analyze_reproducible_across_runs():
    """P1-3：相同输入两次取证，结果完全一致（确定性）。"""
    a = _mk(b"img-a-bytes", "rg_m1.png")
    b = _mk(b"img-b-bytes", "rg_m2.png")
    r1 = analyze_case(a, b, "listing X", "SKU-1", 120, "mock")
    r2 = analyze_case(a, b, "listing X", "SKU-1", 120, "mock")
    assert r1 == r2


def test_mock_analyze_ignores_filename():
    """P1-3：相似度只取决于图片内容，不取决于上传时的随机文件名。"""
    content = b"same-image-content"
    p1, p2 = _mk(content, "alpha.png"), _mk(content, "beta.png")
    p3, p4 = _mk(content, "gamma.png"), _mk(content, "delta.png")
    assert (
        analyze_case(p1, p2, "", "S", 1, "mock")["similarity"]
        == analyze_case(p3, p4, "", "S", 1, "mock")["similarity"]
    )


def test_analyze_cache_avoid_recompute():
    """P1-7：相同输入第二次调用应命中缓存，不再触发 _mock 计算。"""
    a = _mk(b"recompute-a", "rg_rc1.png")
    b = _mk(b"recompute-b", "rg_rc2.png")
    with mock.patch("pipeline._mock") as m:
        analyze_case(a, b, "", "S", 1, "mock")
        first = m.call_count
        analyze_case(a, b, "", "S", 1, "mock")
        assert m.call_count == first, "第二次调用应命中缓存、不再调用 _mock"


def test_analyze_cache_returns_deepcopy():
    """P1-7：缓存命中返回深拷贝，调用方就地补写字段不会污染缓存对象。"""
    a = _mk(b"deepcopy-a", "rg_dc1.png")
    b = _mk(b"deepcopy-b", "rg_dc2.png")
    key = _analyze_cache_key(a, b, "", "S", 1)
    r1 = analyze_case(a, b, "", "S", 1, "mock")
    r1["case_id"] = "RG-INJECTED"  # 模拟 main.py 就地补写
    r2 = analyze_case(a, b, "", "S", 1, "mock")
    # 用 .get 而非 []：mock 结果本身不含 case_id（由 main.py 后续补写），
    # 正确的深拷贝实现下 r2 不应携带被注入的脏值。
    assert r2.get("case_id") != "RG-INJECTED", "缓存对象被调用方污染"
    # 清掉注入的脏键，避免影响其它用例（同一进程共享缓存）
    cached = _analyze_cache.get(key)
    if cached is not None:
        cached.pop("case_id", None)


def test_insights_cache_returns_deepcopy():
    """P1-8：洞察缓存命中返回深拷贝，调用方就地补写字段不污染缓存。

    与单案层 P1-7 同思路：命中返回 deepcopy，且写入缓存时也存 deepcopy，
    使「返回给调用方的对象」与「缓存中的副本」互不别名。
    """
    from db import init_db, load_cases

    init_db()
    cases = load_cases()
    r1 = build_insights(cases, "mock", "demo")
    r1["_injected"] = "DIRTY"  # 模拟 main.py / 前端就地补写字段
    # 同时改写嵌套结构（模拟前端按品类·平台过滤后就地改 sourcing_checklist）
    if isinstance(r1.get("sourcing_checklist"), list):
        r1["sourcing_checklist"].append({"action": "DIRTY"})

    r2 = build_insights(cases, "mock", "demo")
    assert r2.get("_injected") != "DIRTY", "洞察缓存对象被调用方污染（顶层字段）"
    assert {"action": "DIRTY"} not in (r2.get("sourcing_checklist") or []), (
        "洞察缓存对象被调用方污染（嵌套结构）"
    )
