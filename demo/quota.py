# Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
# SPDX-License-Identifier: Apache-2.0
"""live 模式独立配额闸（SEC-13）

背景：
    公网演示账号 ``demo/demo123`` 是**公开凭据**（已随提交材料对外发布），
    且 ``REGISTRATION_ENABLED=false`` 时它是唯一可用账号。任何人都能登录并调用
    ``POST /api/analyze mode=live``，而 live 链路会真实消耗**服务端付费 Key**
    （文本 / 视觉 / TTS 均按量计费），存在被脚本刷量造成资损的风险。

    通用的写接口限流（``main._check_rate_limit``，默认 60 次/分钟/IP）只防"手速快"，
    防不住"低频但持续"的刷量——一天 86400 秒足以累积出巨额账单。故 live 模式
    必须另设**按天计费周期**的独立配额闸。

设计：三层递减闸门，任一不放行即拒绝（429）
    1. 全局日配额 —— 最硬的兜底闸，全场共享，直接决定账单上限
    2. 租户日配额 —— 单账号上限（当前所有访客共用 demo 租户，故与全局冗余；
                      多租户/开放注册后即生效，故保留）
    3. IP 小时配额 —— 抑制单点突发刷量

    配额 0 = 关闭该层（便于本地开发全放开）。

为什么复用 shared_state 而非进程内 dict：
    计数必须**跨 worker、跨进程**一致，否则多 worker 部署下每个进程各计一份，
    实际放行量 = 配额 × worker 数，闸门形同虚设（SEC-12 的教训）。

已知取舍（保守方向）：
    三层闸门依次调用 ``rate_check``（先自增再判超限、超限则回退），若后面的闸门
    拒绝，前面闸门的计数**不会回滚**，会出现少量"多扣"。多扣使闸门更保守（更安全），
    且仅发生在临近配额上限时，可接受。
"""

from __future__ import annotations

import logging
import os

import shared_state

logger = logging.getLogger("returnguard.quota")

# 默认值（可被环境变量覆盖，见 .env.example 的 LIVE_QUOTA_* 说明）
_DEFAULT_GLOBAL_DAY = 300  # 全场每天 live 分析上限
_DEFAULT_TENANT_DAY = 60  # 单租户每天 live 分析上限
_DEFAULT_IP_HOUR = 20  # 单 IP 每小时 live 分析上限

_DAY = 86400
_HOUR = 3600


def _env_int(name: str, default: int) -> int:
    """读取正整数型配额配置；缺失或非法值回退默认，负数按 0（关闭）处理。"""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        logger.warning("配额配置 %s=%r 非法，回退默认值 %d", name, raw, default)
        return default


def _gates(tenant: str, client_ip: str) -> list[tuple[str, str, int, int, str]]:
    """构造三层闸门：(名称, 计数 key, 上限, 窗口秒, 超限文案)。"""
    tenant_key = tenant or "anonymous"
    ip_key = client_ip or "unknown"
    return [
        (
            "全局日配额",
            "live:global:day",
            _env_int("LIVE_QUOTA_GLOBAL_DAY", _DEFAULT_GLOBAL_DAY),
            _DAY,
            "演示环境当日的 AI 实算总配额已用尽，请明天再试",
        ),
        (
            "账号日配额",
            f"live:tenant:{tenant_key}:day",
            _env_int("LIVE_QUOTA_TENANT_DAY", _DEFAULT_TENANT_DAY),
            _DAY,
            "当前账号当日的 AI 实算配额已用尽，请明天再试",
        ),
        (
            "IP 小时配额",
            f"live:ip:{ip_key}:hour",
            _env_int("LIVE_QUOTA_IP_HOUR", _DEFAULT_IP_HOUR),
            _HOUR,
            "当前网络的 AI 实算过于频繁，请稍后再试",
        ),
    ]


def check_live_quota(tenant: str, client_ip: str) -> tuple[bool, str]:
    """live 模式配额闸：放行返回 (True, "")，拦截返回 (False, 面向用户的提示文案)。

    Args:
        tenant: 当前登录租户（用户名）；空值按 anonymous 计。
        client_ip: 客户端 IP（经可信代理还原）；空值按 unknown 计。

    Note:
        仅在 **live** 模式调用；mock 模式不消耗付费额度，沿用通用限流即可。
    """
    for name, key, limit, window, message in _gates(tenant, client_ip):
        if limit <= 0:  # 0 = 该层关闭
            continue
        if not shared_state.rate_check(key, limit, window):
            unit = "天" if window >= _DAY else "小时"
            logger.warning(
                "live 配额拦截：%s（key=%s，上限 %d 次/%s）tenant=%s ip=%s",
                name,
                key,
                limit,
                unit,
                tenant,
                client_ip,
            )
            return False, f"{message}（{name}：{limit} 次/{unit}）"
    return True, ""
