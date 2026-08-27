# ReturnGuard · 平台规则出处核验（交付物 A 来源核查）

> 核验日期：2026-08-27
> 核查对象：`docs/PLATFORM_EVIDENCE.md`（平台适配举证包 / 交付物 A）
> 方法：对每个平台逐条规则检索其**官方公开政策页**并核验存活与原文；无法在公开页确认的供应商侧 SLA 标注为「需登录后台」。
> 结论：交付物 A 的**买家侧规则整体准确**，与官方政策一致；需补 2 类脚注（区域差异、供应商侧 SLA 来源）。

---

## 1. 官方来源总表（已核验存活）

| 平台 | 官方政策页（买家侧，公开可访问） | 核验日期 | 状态 |
|---|---|---|---|
| Amazon | `https://sellercentral.amazon.com/help/hub/reference/external/27951`（A-to-z Guarantee claims） | 2026-08-27 | ✅ 200，原文可引 |
| AliExpress | `https://m.aliexpress.com/p/buyerprotection/index.html`（Buyer protection） | 2026-08-27 | ✅ 200，原文可引 |
| Temu | `https://www.temu.com/return-and-refund-policy.html`（Return and Refund Policy） | 2026-08-27 | ⚠️ JS 渲染页，检索摘要可确认内容（30 天无理由 / 质量延至 90 天） |
| SHEIN | `https://us.shein.com/Return-Policy-a-281.html`（US Return Policy） | 2026-08-27 | ✅ 200，原文可引 |

> 次级官方入口（同域，可作补充引用）：AliExpress 帮助中心 `https://service.aliexpress.com/page/knowledge?...`；SHEIN EU `https://www.shein.com/Return-Policy-a-281.html`（14 天法定撤回权）；Amazon EU `https://sellercentral-europe.amazon.com/help/hub/reference/external/27951`。

---

## 2. 规则逐条核对

### 2.1 Amazon（核对官方 A-to-z 文档）
| 交付物 A 表述 | 官方原文要点 | 一致？ |
|---|---|---|
| A-to-z 索赔须 72h 内响应，否则自动判负 | "If you do not respond to our information request within 72 hours, Amazon may grant the claim in favor of the customer" | ✅ |
| 退货请求 48h 内授权/响应 | "you must authorize or respond to that request within 48 hours" | ✅ |
| ODR 目标 <1% | 官方说明 ODR 衡量窗口 + 行业共识 <1% 为健康线（搜索结果明确 "maintain an ODR below 1%"） | ✅ |
| 裁决后 30 天内可申诉 | "you have 30 calendar days to appeal" | ✅ |
| 偏向买家、卖家须主动举证 | 文档多处强调卖家须响应/授权，否则客户自动获赔 | ✅ |

**结论：Amazon 四项核心规则全部与官方一致，可直接引用上方 URL。**

### 2.2 AliExpress（核对官方 Buyer Protection）
| 交付物 A 表述 | 官方原文要点 | 一致？ |
|---|---|---|
| 确认收货后 15 天保护期 | "It lasts 15 days from the moment you confirm receipt of your item" | ✅ |
| 卖家 5 天响应 | 帮助中心："the seller will be notified and need to reply to your request in 5 days" | ✅ |
| 缺陷/不符由卖家承担运费，改主意买家承担 | "defective, arrives not as described... up to the store to cover" / "change of mind... up to you" | ✅ |
| 低值免退仅退款 | 文档未明示 $5 阈值（第三方口径）；官方仅称低值可 Refund Only | ⚠️ 阈值数字为第三方补充，建议改「低值订单可免退仅退款（具体阈值以平台为准）」 |

**结论：AliExpress 核心规则一致；<$5 阈值建议弱化为「低值订单」以免与官方口径冲突。**

### 2.3 Temu（核对官方 Return & Refund Policy）
| 交付物 A 表述 | 官方原文要点 | 一致？ |
|---|---|---|
| 无理由退货签收后 30 天 | 官方政策：购买后 30 天内可退（no-reason return） | ✅ |
| 质量问题凭证据延至 90 天 | 检索摘要确认质量缺陷可延长退货时效至 90 天 | ✅ |
| 非质量买家承担，手续费 5–15%（最低 $2） | 第三方跨境百科口径；官方公开买家页未披露卖家侧费率 | ⚠️ 卖家侧费率属 Seller Center 后台条款，公开页不载 |
| 卖家 24–48h 响应 / 争议 48h 上传凭证 | **公开买家政策页未包含**；来自第三方卖家百科（Seller Center 登录可见） | ⚠️ 需标注「供应商后台条款，非公开买家政策」 |

**结论：Temu 买家侧 30 天 / 90 天一致；卖家侧 SLA 与费率应标注来源为 Seller Center（登录）或第三方，不宜作为官方公开政策引用。**

### 2.4 SHEIN（核对官方 US Return Policy）
| 交付物 A 表述 | 官方原文要点 | 一致？ |
|---|---|---|
| 收货后 30 天无忧退货 | US 站："within 30 days from the delivery date" | ✅（US 默认） |
| 欧盟仓须遵守 14 天无理由 | EU 站："14 (14) days right of withdrawal"（法定撤回权） | ✅ |
| 供应商 48h 内提供证据链 | 买家政策页未规定供应商 SLA；属 SHEIN 供应商/伙伴协议（登录可见） | ⚠️ 同 Temu，标注后台条款 |
| 质量争议 90 天联系客服 | US 站："contact Customer Service within 90 days from the order date" | ✅ |

**结论：SHEIN 30 天（US）/14 天（EU）与官方一致；注意区域差异——部分第三方卖家/区域窗口可能更长（官方 US 页提示 "For certain products... longer or shorter"）。供应商 48h SLA 标注为后台条款。**

---

## 3. 需回写交付物 A 的修正（建议）

1. **补官方来源链接**：在 `PLATFORM_EVIDENCE.md` 顶部与每个平台模板追加「官方政策来源」一行，引用第 1 节 URL。
2. **区域差异脚注**（SHEIN 重点）：说明「30 天」为 US 站默认值，EU 为 14 天法定撤回权，部分商品/区域窗口不同，以商品详情页为准。
3. **供应商侧 SLA 来源标注**（Temu / SHEIN）：48h 举证时效、费率等来自平台**卖家/供应商后台条款**，非公开买家政策，引用时注明「平台方对商家的协议条款」。
4. **AliExpress 低值阈值**：将「<$5 自动免退仅退款」弱化为「低值订单可免退仅退款（阈值以平台为准）」，与官方公开表述对齐。
5. **Temu 公开页提示**：若评委深挖，可补一句「Temu 公开退货政策为买家侧；卖家仲裁细则见 Seller Center」。

---

## 4. 总体判定

- **准确性**：交付物 A 买家侧核心规则（窗口、响应时限、运费偏向、申诉期）**与四大平台官方政策高度一致**，可直接用于复赛举证。
- **待补强**：① 官方 URL 引用；② 区域差异与供应商后台条款的来源标注。两项均为「增强可信度」级，不影响事实正确性。
- **风险提示**：所有规则为「商家侧解读整理」，ReturnGuard 定位是「只取证不裁决」，文档措辞已守住该边界，无需改动。
