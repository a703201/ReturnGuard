"""ReturnGuard · 真实数据回流演示种子脚本

把一批「真实跨境退货纠纷」注入 real 数据源（cases_real.db），用于演示
「真实数据回流 → 群体洞察 → 选品/品控建议」的完整闭环：

    1) 真实纠纷经网页「数据录入」/ 本脚本回流进 real 库（与演示数据物理隔离）；
    2) 切换数据源为「实际数据」后，洞察看板实时反映这批真实案件；
    3) 异常预警（SKU-RG07 蓝牙耳机近期暴增）、供应商红黑榜（S3 电池鼓包批量退货）、
       选品/品控建议自动生成。

用法：
    python seed_real.py            # 增量追加（幂等需先 --reset）
    python seed_real.py --reset    # 先清空 real 库再播种（推荐，保证演示可复现）
    python seed_real.py --live     # 播种后额外打印 live（LLM）洞察，演示真实 AI 归因

说明：
    - 通过 HTTP 调用运行中的服务（默认 http://localhost:8000），写库即失效服务端洞察缓存；
    - 仅用标准库（urllib），不依赖项目虚拟环境，可在任意 python3 下运行；
    - 真实数据不入库（.gitignore 已忽略 *.db），本脚本即「可复现的真实数据」载体。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from datetime import date

from constants import BLACKLIST_LEVELS

BASE_URL = "http://localhost:8000"
SOURCE = "real"

# ---- 供应商主数据（编号 → 名称）----
SUPPLIERS = {
    "S1": "深圳市晨星电子",
    "S2": "义乌优品供应链",
    "S3": "东莞华强数码",
    "S4": "广州速派仓储",
    "S5": "杭州织造服饰",
}

# ---- 真实纠纷样本（故事：S3 蓝牙耳机电池鼓包近期暴增）----
# 字段对齐 ManualCase；consistency / listing_text 仅作真实感补充。
CASES = [
    # —— SKU-RG07 蓝牙耳机 Pro（S3，3C数码）：近 30 天集中爆发，触发异常预警 ——
    dict(
        sku="SKU-RG07",
        sku_name="蓝牙耳机 Pro",
        category="3C数码",
        supplier="S3",
        platform="Amazon",
        region="北美",
        amount=129.0,
        date="2026-06-15",
        similarity=0.91,
        same_item=True,
        defect_tags=["电池鼓包"],
        consistency="存在差异（运输或质量瑕疵）",
        outcome="输",
        listing_text="续航 30 小时，IPX5 防水",
    ),
    dict(
        sku="SKU-RG07",
        sku_name="蓝牙耳机 Pro",
        category="3C数码",
        supplier="S3",
        platform="AliExpress",
        region="欧洲",
        amount=129.0,
        date="2026-06-28",
        similarity=0.88,
        same_item=True,
        defect_tags=["功能故障"],
        consistency="存在差异（运输或质量瑕疵）",
        outcome="部分退款",
        listing_text="续航 30 小时，IPX5 防水",
    ),
    dict(
        sku="SKU-RG07",
        sku_name="蓝牙耳机 Pro",
        category="3C数码",
        supplier="S3",
        platform="Amazon",
        region="北美",
        amount=129.0,
        date="2026-07-20",
        similarity=0.90,
        same_item=True,
        defect_tags=["电池鼓包"],
        consistency="存在差异（运输或质量瑕疵）",
        outcome="输",
        listing_text="续航 30 小时，IPX5 防水",
    ),
    dict(
        sku="SKU-RG07",
        sku_name="蓝牙耳机 Pro",
        category="3C数码",
        supplier="S3",
        platform="Temu",
        region="东南亚",
        amount=129.0,
        date="2026-07-25",
        similarity=0.89,
        same_item=True,
        defect_tags=["功能故障"],
        consistency="存在差异（运输或质量瑕疵）",
        outcome="输",
        listing_text="续航 30 小时，IPX5 防水",
    ),
    dict(
        sku="SKU-RG07",
        sku_name="蓝牙耳机 Pro",
        category="3C数码",
        supplier="S3",
        platform="Amazon",
        region="北美",
        amount=129.0,
        date="2026-08-02",
        similarity=0.92,
        same_item=True,
        defect_tags=["电池鼓包"],
        consistency="存在差异（运输或质量瑕疵）",
        outcome="输",
        listing_text="续航 30 小时，IPX5 防水",
    ),
    dict(
        sku="SKU-RG07",
        sku_name="蓝牙耳机 Pro",
        category="3C数码",
        supplier="S3",
        platform="AliExpress",
        region="欧洲",
        amount=129.0,
        date="2026-08-08",
        similarity=0.87,
        same_item=True,
        defect_tags=["功能故障"],
        consistency="存在差异（运输或质量瑕疵）",
        outcome="部分退款",
        listing_text="续航 30 小时，IPX5 防水",
    ),
    dict(
        sku="SKU-RG07",
        sku_name="蓝牙耳机 Pro",
        category="3C数码",
        supplier="S3",
        platform="Amazon",
        region="北美",
        amount=129.0,
        date="2026-08-12",
        similarity=0.91,
        same_item=True,
        defect_tags=["电池鼓包"],
        consistency="存在差异（运输或质量瑕疵）",
        outcome="输",
        listing_text="续航 30 小时，IPX5 防水",
    ),
    # —— SKU-RG01 无线充电器 / SKU-RG06 数据线（S1，优质供应商对照组）——
    dict(
        sku="SKU-RG01",
        sku_name="无线充电器",
        category="3C数码",
        supplier="S1",
        platform="Amazon",
        region="北美",
        amount=59.0,
        date="2026-07-10",
        similarity=0.95,
        same_item=True,
        defect_tags=["无明显瑕疵"],
        consistency="一致（疑似非质量原因）",
        outcome="赢",
        listing_text="15W 快充，兼容多机型",
    ),
    dict(
        sku="SKU-RG01",
        sku_name="无线充电器",
        category="3C数码",
        supplier="S1",
        platform="Amazon",
        region="北美",
        amount=59.0,
        date="2026-07-22",
        similarity=0.96,
        same_item=True,
        defect_tags=["无明显瑕疵"],
        consistency="一致（疑似非质量原因）",
        outcome="赢",
        listing_text="15W 快充，兼容多机型",
    ),
    dict(
        sku="SKU-RG01",
        sku_name="无线充电器",
        category="3C数码",
        supplier="S1",
        platform="SHEIN",
        region="欧洲",
        amount=59.0,
        date="2026-08-05",
        similarity=0.93,
        same_item=True,
        defect_tags=["外包装破损"],
        consistency="存在差异（运输或质量瑕疵）",
        outcome="部分退款",
        listing_text="15W 快充，兼容多机型",
    ),
    dict(
        sku="SKU-RG06",
        sku_name="快充数据线",
        category="3C数码",
        supplier="S1",
        platform="AliExpress",
        region="欧洲",
        amount=25.0,
        date="2026-07-19",
        similarity=0.96,
        same_item=True,
        defect_tags=["无明显瑕疵"],
        consistency="一致（疑似非质量原因）",
        outcome="赢",
        listing_text="2米 尼龙编织",
    ),
    dict(
        sku="SKU-RG06",
        sku_name="快充数据线",
        category="3C数码",
        supplier="S1",
        platform="AliExpress",
        region="欧洲",
        amount=25.0,
        date="2026-08-04",
        similarity=0.97,
        same_item=True,
        defect_tags=["无明显瑕疵"],
        consistency="一致（疑似非质量原因）",
        outcome="赢",
        listing_text="2米 尼龙编织",
    ),
    # —— SKU-RG02 纯棉T恤 / SKU-RG08 运动鞋（S5，服饰：尺码/色差）——
    dict(
        sku="SKU-RG02",
        sku_name="纯棉圆领T恤",
        category="服饰鞋包",
        supplier="S5",
        platform="SHEIN",
        region="欧洲",
        amount=39.0,
        date="2026-07-15",
        similarity=0.90,
        same_item=True,
        defect_tags=["尺寸偏差"],
        consistency="存在差异（图文不符）",
        outcome="赢",
        listing_text="100% 纯棉，欧码标准",
    ),
    dict(
        sku="SKU-RG02",
        sku_name="纯棉圆领T恤",
        category="服饰鞋包",
        supplier="S5",
        platform="SHEIN",
        region="欧洲",
        amount=39.0,
        date="2026-08-01",
        similarity=0.89,
        same_item=True,
        defect_tags=["色差明显"],
        consistency="存在差异（图文不符）",
        outcome="部分退款",
        listing_text="100% 纯棉，欧码标准",
    ),
    dict(
        sku="SKU-RG02",
        sku_name="纯棉圆领T恤",
        category="服饰鞋包",
        supplier="S5",
        platform="Temu",
        region="东南亚",
        amount=39.0,
        date="2026-08-09",
        similarity=0.91,
        same_item=True,
        defect_tags=["尺寸偏差"],
        consistency="存在差异（图文不符）",
        outcome="输",
        listing_text="100% 纯棉，欧码标准",
    ),
    dict(
        sku="SKU-RG08",
        sku_name="轻量运动鞋",
        category="服饰鞋包",
        supplier="S5",
        platform="Temu",
        region="东南亚",
        amount=99.0,
        date="2026-07-14",
        similarity=0.89,
        same_item=True,
        defect_tags=["尺寸偏差"],
        consistency="存在差异（图文不符）",
        outcome="赢",
        listing_text="透气网面，偏大半码",
    ),
    dict(
        sku="SKU-RG08",
        sku_name="轻量运动鞋",
        category="服饰鞋包",
        supplier="S5",
        platform="Temu",
        region="东南亚",
        amount=99.0,
        date="2026-08-07",
        similarity=0.88,
        same_item=True,
        defect_tags=["材质不符"],
        consistency="存在差异（图文不符）",
        outcome="部分退款",
        listing_text="透气网面，偏大半码",
    ),
    # —— SKU-RG03 迷你加湿器 / SKU-RG05 口红 / SKU-RG09 台灯（S2，小家电/美妆）——
    dict(
        sku="SKU-RG03",
        sku_name="迷你加湿器",
        category="小家电",
        supplier="S2",
        platform="Amazon",
        region="北美",
        amount=79.0,
        date="2026-07-18",
        similarity=0.94,
        same_item=True,
        defect_tags=["无明显瑕疵"],
        consistency="一致（疑似非质量原因）",
        outcome="赢",
        listing_text="静音 300ml",
    ),
    dict(
        sku="SKU-RG03",
        sku_name="迷你加湿器",
        category="小家电",
        supplier="S2",
        platform="Amazon",
        region="北美",
        amount=79.0,
        date="2026-08-03",
        similarity=0.88,
        same_item=True,
        defect_tags=["功能故障"],
        consistency="存在差异（运输或质量瑕疵）",
        outcome="部分退款",
        listing_text="静音 300ml",
    ),
    dict(
        sku="SKU-RG05",
        sku_name="哑光丝绒口红",
        category="美妆个护",
        supplier="S2",
        platform="SHEIN",
        region="欧洲",
        amount=45.0,
        date="2026-07-25",
        similarity=0.95,
        same_item=True,
        defect_tags=["无明显瑕疵"],
        consistency="一致（疑似非质量原因）",
        outcome="赢",
        listing_text="持久不沾杯",
    ),
    dict(
        sku="SKU-RG05",
        sku_name="哑光丝绒口红",
        category="美妆个护",
        supplier="S2",
        platform="SHEIN",
        region="欧洲",
        amount=45.0,
        date="2026-08-10",
        similarity=0.91,
        same_item=True,
        defect_tags=["色差明显"],
        consistency="存在差异（图文不符）",
        outcome="部分退款",
        listing_text="持久不沾杯",
    ),
    dict(
        sku="SKU-RG09",
        sku_name="LED 护眼台灯",
        category="小家电",
        supplier="S2",
        platform="Amazon",
        region="北美",
        amount=69.0,
        date="2026-08-08",
        similarity=0.94,
        same_item=True,
        defect_tags=["无明显瑕疵"],
        consistency="一致（疑似非质量原因）",
        outcome="赢",
        listing_text="无频闪，三档色温",
    ),
    # —— SKU-RG04 桌面收纳盒（S4，家居：包装/缺件）——
    dict(
        sku="SKU-RG04",
        sku_name="桌面收纳盒",
        category="家居日用",
        supplier="S4",
        platform="AliExpress",
        region="欧洲",
        amount=29.0,
        date="2026-07-12",
        similarity=0.92,
        same_item=True,
        defect_tags=["外包装破损"],
        consistency="存在差异（运输或质量瑕疵）",
        outcome="部分退款",
        listing_text="PP 材质，分层收纳",
    ),
    dict(
        sku="SKU-RG04",
        sku_name="桌面收纳盒",
        category="家居日用",
        supplier="S4",
        platform="AliExpress",
        region="欧洲",
        amount=29.0,
        date="2026-08-06",
        similarity=0.90,
        same_item=True,
        defect_tags=["商品缺件"],
        consistency="存在差异（运输或质量瑕疵）",
        outcome="输",
        listing_text="PP 材质，分层收纳",
    ),
]


def _url(path: str) -> str:
    """拼接请求地址：path 若已带 ? 查询则用 & 追加 source，避免双 ? 导致 422。"""
    sep = "&" if "?" in path else "?"
    return f"{BASE_URL}{path}{sep}source={SOURCE}"


def _http_json(method: str, path: str, payload: dict | None = None, retries: int = 3) -> dict:
    """带重试的 JSON 请求（应对服务冷启动 / 瞬时连接抖动）。"""
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(_url(path), data=data, method=method, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # 瞬时失败重试
            last_err = e
            if attempt < retries:
                time.sleep(1.0 * attempt)
    raise last_err  # type: ignore[misc]


def _post(path: str, payload: dict) -> dict:
    return _http_json("POST", path, payload)


def _get(path: str) -> dict:
    return _http_json("GET", path)


def _delete(path: str) -> None:
    _http_json("DELETE", path)


def _reset() -> None:
    print("→ 清空 real 数据源现有案件…")
    try:
        existing = _get("/api/cases?slim=1")
    except Exception as e:
        print(f"  （读取列表失败，跳过重置：{e}）")
        return
    for row in existing:
        cid = row.get("case_id")
        if cid:
            try:
                _delete(f"/api/cases/{cid}")
            except Exception as e:
                print(f"  （删除 {cid} 失败：{e}）")
    print(f"  已尝试清理 {len(existing)} 条。")


def _print_summary(agg: dict, mode: str) -> None:
    print(f"\n===== 洞察看板（mode={mode}, source=real）=====")
    print(f"已分析退货：{agg.get('total_cases')} 笔")
    print(f"累计退款：¥{agg.get('total_refund')}")
    print(f"维权胜诉率：{agg.get('win_rate')}")
    print(f"货不对板嫌疑率（代理指标）：{agg.get('avg_dispute_rate')}")
    print("\n— 异常 SKU 预警 —")
    for a in agg.get("anomaly_alerts", []):
        print(f"  ⚠ {a.get('sku')}：{a.get('reason')}")
    print("\n— 供应商红黑榜（黑榜=高风险）—")
    for s in agg.get("supplier_scorecard", []):
        if s.get("level") in BLACKLIST_LEVELS:
            print(
                f"  🔴 {s.get('supplier')} {s.get('name')}：质量分 {s.get('quality_score')}（{s.get('level')}）"
                f" 胜诉率={s.get('win_rate')} 缺陷率={s.get('defect_rate')}"
            )
    print("\n— 选品 / 品控建议 —")
    for i, r in enumerate(agg.get("recommendations", []) or agg.get("sourcing_advice", []), 1):
        print(f"  {i}. {r}")
    if mode == "live":
        print("\n— AI 根因归因 —")
        print("  " + (agg.get("root_cause") or "(无)").replace("\n", "\n  "))
        print("\n— AI 洞察报告 —")
        print("  " + (agg.get("report") or "(无)").replace("\n", "\n  "))


def main() -> int:
    global BASE_URL
    ap = argparse.ArgumentParser(description="ReturnGuard 真实数据回流演示种子")
    ap.add_argument("--reset", action="store_true", help="播种前先清空 real 库")
    ap.add_argument("--live", action="store_true", help="额外打印 live（LLM）洞察")
    ap.add_argument("--base-url", default=BASE_URL, help="服务地址（默认 http://localhost:8000）")
    args = ap.parse_args()

    BASE_URL = args.base_url.rstrip("/")

    if args.reset:
        _reset()

    ok = 0
    fail = 0
    for c in CASES:
        c = dict(c)
        c["supplier_name"] = SUPPLIERS.get(c["supplier"], c["supplier"])
        # 校验日期格式，避免落库被忽略
        try:
            date.fromisoformat(c["date"])
        except Exception:
            print(f"  ✗ 非法日期：{c['date']}（{c['sku']}）")
            fail += 1
            continue
        try:
            _post("/api/cases", c)
            ok += 1
            time.sleep(0.15)  # 错开写入，避免瞬时连接抖动
        except Exception as e:
            print(f"  ✗ 写入失败 {c['sku']} {c['date']}：{e}")
            fail += 1

    print(f"\n播种完成：成功 {ok} 条，失败 {fail} 条。")
    if fail:
        print("存在失败，请检查服务是否在运行（python main.py）。")
        return 1

    # mock 洞察（确定性、可复现，适合录屏）
    try:
        mock = _get("/api/insights?mode=mock")
        _print_summary(mock, "mock")
    except Exception as e:
        print(f"（获取 mock 洞察失败：{e}）")

    # live 洞察（真实 AI 归因，耗时长、消耗额度，按需开启）
    if args.live:
        print("\n⏳ 正在调用 live（LLM）洞察，请稍候（约 30-60 秒）…")
        try:
            live = _get("/api/insights?mode=live")
            _print_summary(live, "live")
        except Exception as e:
            print(f"（获取 live 洞察失败：{e}）")

    return 0


if __name__ == "__main__":
    sys.exit(main())
