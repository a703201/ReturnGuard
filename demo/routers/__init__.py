# Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
# SPDX-License-Identifier: Apache-2.0
"""ReturnGuard 业务路由包（P1-9 拆分）。

各子模块各自持有一个 APIRouter，由 main.py 统一 include_router 聚合：
    frontend.py     —— 页面 / 签名文件 / 配置 / 指标 / 平台举证包
    forensic.py     —— 单案取证 / 案件库增删
    insights.py     —— 群体洞察 / PDF 导出
    auth.py         —— 账户 / 多租户隔离
    calibration.py  —— 相似度阈值自标定
    import_.py      —— 真实数据回流（CSV / 数据集文件）
"""
