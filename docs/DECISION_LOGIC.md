# ReturnGuard 退货判定逻辑说明（DECISION_LOGIC）

> 适用版本：2.1.1（仓库根 `VERSION` 为单一来源）
> 关联文档：[`ARCHITECTURE.md`](ARCHITECTURE.md)（功能实现逻辑）、[`AI_PROVIDERS.md`](AI_PROVIDERS.md)（多平台对接）、[`API.md`](API.md)（接口契约）、[`AB_ROI_实证说明.md`](AB_ROI_实证说明.md)（口径边界）

本文回答一个问题：**「退货信息被判定成什么」这件事，具体是按哪条规则算出来的。**
每一条判定都按同一结构描述：**输入 → 规则/阈值 → 输出 → 边界与回退**。

---

## 0. 总原则（三条，先立规矩）

| 原则 | 含义 | 代码约束 |
|---|---|---|
| **只取证，不裁决** | 系统只输出客观事实（相似度、瑕疵、承诺差异、坐标框），**不给「该不该退款」的结论** | 文案与字段均不带裁决语；`dossier` 只陈述证据 |
| **阈值单一来源** | 所有判定阈值/词表只在一处定义，避免「两处各写一份」造成口径分叉 | `demo/constants.py`（阈值、词表、分级）、`demo/calibration.py`（运行期标定值） |
| **真实 vs 回退必须可区分** | 任何由确定性规则顶替真实模型的结果，都必须被标记出来 | `mode` / `capabilities` / `defect_boxes_live` / `reconciled_from` |

### 0.1 阈值与词表清单（单一来源）

| 名称 | 位置 | 默认值 | 作用 |
|---|---|---|---|
| `SAME_ITEM_THRESHOLD` | `constants.py` | `0.82` | 同款判定线 |
| 运行期阈值 | `calibration.get_active_threshold()` | 标定值，否则 `0.82` | 实际参与判定（`/api/calibrate` 可标定） |
| `DECIDED_OUTCOMES` | `constants.py` | `("赢","部分退款","输")` | 胜诉率分母口径 |
| `DEFECT_POOL` | `constants.py` | 7 类缺陷 | 瑕疵标签词表 |
| `SEVERITY` | `constants.py` | 0.2 ~ 0.8 | 缺陷严重度（优先级 / 主缺陷选取） |
| `SUPPLIER_LEVEL_THRESHOLDS` / `SUPPLIER_LEVEL_TOP` | `constants.py` | 20 / 30 / 38 / `≥38` | 供应商质量分分级 |
| `BLACKLIST_LEVELS` | `constants.py` | `("高风险","待改进")` | 进入黑名单的档位 |
| `REGION_MAP` / `MACRO_REGIONS` | `constants.py` | 国家码→8 个宏观地区 | 地区口径归一 |
| `TTS_VOICES` | `constants.py` | 8 语种→音色 | 举证语种与音色 |

---

## 1. 单案取证判定（阶段 A）

### 1.1 同款一致性 `similarity` / `same_item`

| 项 | 内容 |
|---|---|
| 输入 | 退回件图、本店主图 |
| 主路径（live） | VL 模型**同时看两张图**直接判同款：`models_router.vl_similarity()`，要求模型返回 `{similarity, same_item, reason}` |
| 备选（live） | 图像向量：`embed_image()` 取两张图向量 → `cosine()` 余弦相似度（零向量返回 `0.0`） |
| 末级回退 | 图片**内容哈希**：`imghash.content_seed(退回图, 主图)` → `0.55 + (seed % 1000)/1000 × 0.43`，值域 `[0.55, 0.98)` |
| 归一化 | 模型输出 `similarity` 强制 `clamp(0, 1)` |
| 判定线 | `same_item = similarity ≥ get_active_threshold()`（默认 `0.82`；VL 明确给出 `same_item` 时以模型为准） |
| 输出 | `similarity`（3 位小数）、`same_item` |
| 边界 | 相似度是**客观一致性指标**，不是「谁的责任」；调包/同款只是业务解释 |
| 为什么 VL 是主路径 | 百炼等平台的 OpenAI 兼容模式**不支持视觉向量模型**，而「两图放一起让模型判断」更贴合调包/同款业务语义 |

> ⚠️ 若走末级回退，`capabilities.similarity = false`，前端必须显示为「回退」，且该值只用于演示。

**阈值标定（`/api/calibrate`）**：给定「真同款」与「真调包」两组历史相似度样本，
用 **Youden J** 最大化 `敏感度 + 特异度 − 1` 得到最优分离点并落盘；样本缺任一类则不覆盖既有标定。

### 1.2 瑕疵标签 `defect_tags`

| 项 | 内容 |
|---|---|
| 输入 | 退回件图 + 本店主图（双图对比，定位**相对主图新增**的瑕疵） |
| live | `vl_chat(本店主图, DEFECT_RECOGNITION_PROMPT, second_image=退回件)`，返回逗号分隔标签 |
| 解析 | 中文逗号 `，` 归一为 `,` 后切分、去空白；结果为空 → `["无明显瑕疵"]` |
| 回退 | `_fallback_defects()`：`random.Random(content_seed(图))` → `n = randint(0,3)`，从 `DEFECT_POOL` 抽 `n` 个；`n = 0` → `["无明显瑕疵"]` |
| 词表 | `constants.DEFECT_POOL`：外包装破损 / 商品缺件 / 污渍划痕 / 使用痕迹 / 功能故障 / 货不对板 / 色差明显 |
| 输出 | `defect_tags`（list）、`defect_description`（拼接文本） |
| 边界 | 模型自由文本**一律经转义**再入 DOM；标签不参与「输赢」判定 |

### 1.3 货不对板 / 一致性结论 `consistency`

| 项 | 内容 |
|---|---|
| 输入 | ① `similarity` / `defect_tags`；② listing 承诺文本（优先 OCR 读图，失败用卖家自填 `listing_text`） |
| live | `llm(consistency_prompt(similarity, defects, promise))` |
| 回退规则 | `same_item == true 且 defects == ["无明显瑕疵"]` → **「一致（倾向买家责任）」**；否则 → **「存在差异（货不对板 / 运输或质量瑕疵）」** |
| 输出 | `consistency`（自然语言结论） |
| 边界 | 结论是「证据与承诺的差异」，不是仲裁结果；文案中不含赔付主张 |

**③ OCR 承诺提取**：`ocr(本店主图)` → 失败回退 `listing_text`。
`listing_text` 由卖家可控，故在 `live_analyze` 入口先经 `prompts.sanitize_user_content()` 净化，
防止提示词注入污染结论（对应回归测试 `test_prompt_injection.py`）。

### 1.4 举证卷宗与母语陈述 `dossier` / `voice_text`

| 项 | 内容 |
|---|---|
| live | `llm(dossier_prompt(...))` 生成卷宗；`llm(voice_prompt(similarity, defects, language))` 生成口播稿 |
| 失败回退 | 确定性模板（`voice_statement()`，8 语种）；卷宗带「文本生成服务暂不可用，已回退确定性模板」字样 |
| 语种 | `constants.TTS_VOICES` 的 key：`zh/en/es/pt/de/fr/ja/ko`；非法值在路由层 `400`，live 内部再兜底回默认语种 |
| 音色 | `constants.tts_voice_for(language)`（单一来源），音频失败回退占位 WAV |
| 输出 | `dossier`、`voice_text`、`language`、`voice`、`voice_audio_b64` |

### 1.5 案件优先级 `priority_score`

| 项 | 内容 |
|---|---|
| 语义 | **相似度越低 + 瑕疵越重 + 金额越高 → 越该先处理** |
| 本地可解释公式 | `min(1.0, 0.4 + (1 − similarity) × 0.3 + severity × 0.3 + (amount > 50 ? 0.2 : 0))`，其中 `severity = max(SEVERITY[d] for d in defect_tags)` |
| live 融合 | `rerank(_PRIORITY_QUERY, [案件描述])` 取 `relevance_score`（clamp 0~1）后 **5:5 融合**：`0.5 × 本地 + 0.5 × rerank` |
| 回退 | rerank 不可用 → 纯本地公式（`capabilities.rerank = false`） |
| 输出 | `priority_score`（0~1） |
| 边界 | 排序**只决定处理顺序**，不改变任何证据；融合比例写死 5:5 以避免单一信号失真 |

### 1.6 缺陷区域框 `defect_boxes` / `defect_boxes_live`

| 项 | 内容 |
|---|---|
| live | `vl_detect_boxes(本店主图, DEFECT_BBOX_PROMPT, img_size=退回件尺寸, second_image=退回件)` |
| 坐标 | 归一化到 `0~1`；模型返回像素坐标时按图片尺寸换算；越界/无效项丢弃 |
| 输出项 | `{label, x, y, w, h, confidence}` |
| 回退 | `_fallback_defect_boxes()` 确定性示意框：`x∈[0,0.6]`、`y∈[0,0.55]`、`w,h∈[0.20,0.42]`、`confidence∈[0.75,0.98]` |
| 真伪标记 | `defect_boxes_live=true` 才是真实视觉坐标；`false` 时前端改为琥珀色并标注「示意」 |
| 边界 | 红框不替代检测报告，更不替代平台裁决 |

---

## 2. 群体洞察判定（阶段 B）

### 2.1 案件结果与胜诉率 `outcome` / `win_rate`

| 项 | 内容 |
|---|---|
| `outcome` 枚举 | `赢` / `部分退款` / `输` / `待分析`（入库契约，**不随界面语言翻译**） |
| 归一 | 非 `赢/部分退款/输` 的值一律归入 **`待分析`**（不混入「未知」噪声桶） |
| 胜诉率 | `win_rate = 赢 ÷ (总案件 − 待分析)`；分母为 0 → `0.0` |
| 各维度口径 | 平台 / 地区 / 平台×供应商 均用 `decided`（已判定数）作分母，**与全局一致** |
| 单案取证与手动录入 | 一律写 `outcome = 待分析`（单笔无法判定输赢，避免稀释 KPI） |
| 边界 | 「部分退款」计入已判定但**不计入分子**（保守口径） |

### 2.2 代理争议率 `avg_dispute_rate`

| 项 | 内容 |
|---|---|
| 定义 | `1 − 平均相似度`（对**全量案件**求平均，不只算有平台的案件） |
| 业务含义 | 「货不对板/调包」嫌疑的**代理指标**，越接近 1 嫌疑越强 |
| 边界（重要） | **不是**平台标记的争议笔数；响应里强制带 `dispute_rate_note`，前端必须同屏展示，防止被读成真实争议率 |
| 下游用途 | ROI 回测的「争议案件数」= 总案件 × 该指标（见 2.8） |

### 2.3 品类退货热力

| 项 | 内容 |
|---|---|
| 分组 | 按 `category`；**缺失品类的案件直接跳过**（不制造「未分类」噪声桶） |
| 排序 | 按退款额降序 |
| 字段 | `cases` / `refund` / `win_rate = won÷cases` / `dispute_rate = 1 − 平均相似度` / `top_defect`（该品类最高频缺陷） |

### 2.4 供应商质量分与红黑榜

| 项 | 内容 |
|---|---|
| 缺陷计数 | 「真实缺陷案件数」= 缺陷标签中含**任一非「无明显瑕疵」**标签的案件数 |
| 缺陷率 | `defect_rate = 真实缺陷案件数 ÷ 供应商案件数` |
| 质量分 | `score = 100 × (0.5 × win_rate + 0.5 × (1 − defect_rate))`，取值 0~100 |
| 分级 | `score < 20` 高风险 ｜ `< 30` 待改进 ｜ `< 38` 合格 ｜ `≥ 38` 优质 |
| 黑名单 | 按**档位**判定：`level ∈ {高风险, 待改进}` |
| 跳过 | 缺失 / 「未知」供应商不进榜（避免污染可读性） |
| 边界 | 供应商编号 S1–S8 为**演示合成维度**（按退货缺陷信号反推品控），不代表真实工商主体 |

> ⚠️ 历史缺陷（已修）：黑名单曾另设「分数 < 50」阈值，与「≥38 即优质」的分级冲突，导致 38~49 分的“优质”供应商被同时拉黑。现黑名单只按 `BLACKLIST_LEVELS` 档位判定。

### 2.5 根因归因

| 项 | 内容 |
|---|---|
| 主缺陷 | 每案取 `defect_tags` 中**严重度最高**的标签（忽略「无明显瑕疵」） |
| 映射表 | `外包装破损/污渍划痕 → 物流与包装`、`商品缺件 → 供应商履约`、`功能故障 → 供应商质量`、`货不对板/色差明显 → Listing与图文`、`使用痕迹/无明显瑕疵 → 非质量(倾向买家)`；未收录 → `其他` |
| 每桶建议 | 固定整改建议（`_BUCKET_ADVICE`），如「升级加厚纸箱 + 跌落测试」「批次抽检老化测试」 |
| mock 归因 | 规则计算（确定性、可复现） |
| live 归因 | LLM 输出 + **数值对账**（见 2.9） |

### 2.6 SKU 异常预警

判定为「集中爆发」需**同时**满足（时间基准 = 数据集中的最新案件日期）：

| 条件 | 阈值 |
|---|---|
| 该 SKU 案件总数 | `≥ 6` |
| 近 30 天案件数 | `≥ 4` |
| 前期（30~60 天）案件数 | `> 0` |
| 环比 | `近 30 天 ≥ 1.8 × 前期` |

输出：`recent` / `prior` / `pct = round((recent − prior) ÷ prior × 100)` / 原因文案；
命中后该 SKU 在 `sku_ranking` 中标记 `anomaly = true`。

### 2.7 时间序列与次月预测

| 项 | 内容 |
|---|---|
| 聚合 | 按自然月 `YYYY-MM` 汇总案件数与退款；**缺日期的案件不计入** |
| 方法 | 以月序为自变量的 **OLS 线性最小二乘**：`slope = Sxy / Sxx`，`intercept = ȳ − slope × x̄` |
| 预测点 | `max(0, round(intercept + slope × (n − 1 + k)))`，`k = 1..3`（默认 3 个月） |
| 预测退款 | `预测案件数 × 历史单件退款均值` |
| 趋势判定 | `rel = |slope| ÷ ȳ`；`rel < 0.05` → `flat`（防噪声误报），否则按符号 `up` / `down` |
| 样本不足 | 少于 3 个月 → `available = false`，前端提示「暂无足够时间维度数据」 |
| 上行告警 | `trend == "up"` 且预测首月高于近期均值 → 生成 `forecast_alerts` |

### 2.8 ROI 真实回测（口径边界）

> ⚠️ 性质：**基于真实聚合值的模型回测（model-based backtest）**，**不是** A/B 实测因果。
> `method` 与 `disclaimer` 强制随结果下发，前端必须同屏展示。

| 类别 | 字段 | 来源 |
|---|---|---|
| **真实量** | `total_cases` / `total_refund` / `avg_dispute_rate` / `win_rate` / `logistics_cost` | 看板当前筛选下的真实聚合 |
| **假设量** | 胜诉率提升 `5 / 15 / 25` 个百分点；单案人工 `2h → 3min`；时薪 | 外置常量，可审 |

计算链：

```
争议案件数   = 案件总量 × 真实争议占比
headroom     = max(0, min(0.95 − 当前胜诉率, 1 − 当前胜诉率))   ← 双重约束，胜诉率不会溢出
有效提升     = min(假设提升, headroom)
由败转胜案件 = 争议案件数 × 有效提升
挽回退款     = 由败转胜案件 × 笔均退款
挽回物流     = 由败转胜案件 × 笔均物流成本
节省工时     = 争议案件数 × (2h − 3min)
```

敏感性：案件量与争议占比各 ±20% 的**单因子**扰动区间。

### 2.9 LLM 输出数值对账（防幻觉）

| 项 | 内容 |
|---|---|
| 触发 | live 归因返回后 |
| 扫描 | 正则 `胜诉率\s*(?:约为?|约)?\s*(\d{1,3}(?:\.\d+)?)\s*%`，覆盖字段 `root_cause` / `report` / `sku_insights[].finding|action` |
| 容差 | ±5 个百分点（正常措辞差异不误改） |
| 处理 | 超差**就地改写为权威值**并计数 `_consistency_mismatches`；结构化结论（根因/建议）保留不丢 |
| 边界 | 只纠数字，不重写论断；`reconciled_from` 标记被纠偏的事实 |

### 2.10 地区 / 季节 / 退货成本

| 项 | 内容 |
|---|---|
| 地区归一 | `REGION_MAP` 把国家码/国家全名映射为 8 个宏观地区；未收录 → `其他`，**聚合时丢弃**（不进 `region_view` 与成本）；`未知` 显式丢弃 |
| 季节 | 月份映射：`3–5 春 / 6–8 夏 / 9–11 秋 / 12,1,2 冬` |
| 物流成本 | `退款额 × 地区物流占比`（北美 0.16 / 欧洲 0.18 / 南美 0.15 / 东亚 0.13 / 东南亚 0.12 / 大洋洲 0.17 / 中东 0.15 / 非洲 0.16 / 其他 0.14） |
| 退货总成本 | `退款额 + 物流成本`（**估算**，非财务口径） |

> ⚠️ 接入新数据源时**必须**同步补录 `REGION_MAP`，否则样本会静默流失。

### 2.11 选品避坑可执行清单

由聚合结果收敛成**可执行动作**，按严重度（高→中→低）排序：

| 触发条件 | 动作 | 严重度 |
|---|---|---|
| 供应商进入黑名单 | 规避供应商 | 高 |
| 品类胜诉率 `< 0.30` | 上新前必核验 | 中 |
| SKU 命中异常预警 | 暂停推广 · 排查批次 | 高 |
| 预测退货量上行 | 前置品控 · 备货物流 | 中 |

---

## 3. 写入与入参判定（数据可信度）

判定不仅发生在读取时，写入前也要收敛，否则脏数据会污染全部落库来源。

### 3.1 持久层收敛 `db._clamp_values`（最后一道防线）

| 规则 | 说明 |
|---|---|
| 字符串按列长截断 | 以 ORM 列定义的长度为准（如 `sku` 64、`sku_name` 256），超长截断并记 `WARNING` |
| 非有限数值归零 | `amount` / `similarity` / `priority_score` 为 `NaN` / `±Inf` / 非数值 → `0.0` |
| 标签归一 | `defect_tags` 非 list → 包装为 list；元素转字符串并截断 64 字符；空 → `["无明显瑕疵"]` |
| 日期规整 | `date` 解析失败 → `NULL`（不写入非法日期） |
| 覆盖范围 | 手动录入、单案取证沉淀、CSV / xlsx 导入**三条链路共用** |

> 为什么放在持久层：上游入口会持续增加（已有 3 条），只在路由层校验必然漏；
> 且 openGauss 对 `VARCHAR(n)` 是**严格长度校验**，超长会直接 `DataError` → 接口 500。

### 3.2 接口层边界（面向用户，超限**明确报错**）

| 接口 | 约束 | 越界 |
|---|---|---|
| `POST /api/analyze` | `amount` 有限且 `0 ~ 1e9`；`sku ≤ 64`、`category ≤ 64`、`supplier ≤ 32`、`listing_text ≤ 20000` | `400` |
| `POST /api/cases` | `ManualCase` 全字段长度与范围（`amount ∈ [0,1e9]`、`similarity`/`priority_score ∈ [0,1]`） | `422` |
| `GET /api/cases` | `page ≥ 1`、`page_size ≤ 200` | `422` |
| `POST /api/import_csv` | 文件与表单文本均 ≤ 10MB | `413` |
| `POST /api/calibrate` | 每组样本 ≤ 5000 | `422` |

> 接口层「明确报错」而持久层「静默截断」是**有意为之**：面向人的表单要让用户知道输入非法；
> 面向批量的导入不能让一行脏数据毁掉整批，故截断并留痕。

### 3.3 结果可信度标注（不可省略）

| 字段 | 取值 | 含义 |
|---|---|---|
| `mode` | `mock` / `live` / `live(partial)` / `mock(fallback)` | 整体真实程度（`live(partial)` = 部分能力回退） |
| `capabilities{}` | `{cap: bool}` | **逐能力**是否走了真实模型 |
| `defect_boxes_live` | `bool` | 红框是否真实坐标 |
| `degraded[]` | `string[]` | 本轮实际降级的能力清单 |
| `reconciled_from` | `"aggregate"` | LLM 数字与聚合不符、已被纠偏 |
| `error` | 脱敏文案 | 回退原因（不含内部细节与密钥） |

---

## 4. 快速索引：想改某条判定，该动哪里

| 想调整… | 改这里 |
|---|---|
| 同款阈值默认值 | `demo/constants.py` → `SAME_ITEM_THRESHOLD`；运行期用 `/api/calibrate` 标定 |
| 缺陷词表 / 严重度 | `demo/constants.py` → `DEFECT_POOL` / `SEVERITY` |
| 供应商分级与黑名单 | `demo/constants.py` → `SUPPLIER_LEVEL_THRESHOLDS` / `BLACKLIST_LEVELS` |
| 地区归一或物流占比 | `demo/constants.py` → `REGION_MAP`；`demo/pipeline.py` → `_REGION_SHIP_RATIO` |
| 异常预警阈值 | `demo/pipeline.py` → `_build_sku_ranking` |
| 预测方法 / 趋势判定 | `demo/pipeline.py` → `_forecast_monthly` |
| 根因桶映射与建议 | `demo/pipeline.py` → `_DEFECT_BUCKET` / `_BUCKET_ADVICE` |
| ROI 假设与上限 | `demo/pipeline.py` → `ROI_SCENARIOS` / `ROI_MAX_WIN_RATE` / `ROI_LABOR_*` |
| 防幻觉容差 | `demo/pipeline.py` → `_TOLERANCE_PP` |
| 写入收敛规则 | `demo/db.py` → `_clamp_values` |
| 接口入参边界 | `demo/routers/*.py` + `demo/schemas.py` |

> 改动后请同步 `demo/tests/`（`test_pipeline.py` / `test_roi_backtest.py` / `test_hardening.py` / `test_docs_consistency.py`）
> 与本文档；`test_docs_consistency.py` 会校验文档与代码的可机检事实。
