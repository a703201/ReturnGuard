"""P1-10：网关真实契约测试（离线录制式）。

不依赖外网：用 monkeypatch 替换 models_router._post，返回「符合百炼/ModelRouter 真实 schema」的
JSON 响应（choices[0].message.content / reasoning_content），断言：
  - 请求体含正确的 model 名（来自当前 profile 的 MODELS）与 messages 结构；
  - 响应解析（_extract_json / llm / llm_json）对 markdown 围栏、<think> 思考链、截断、
    多段 JSON 等真实噪声鲁棒；
  - 模型命名契约：official 等赛事档模型须带 qwen/ 前缀，杜绝 404/模型不存在。
"""

import re

import models_router as mr


class _RecordedResp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._p


def _make_fake_post(record):
    def _post(url, **kw):
        record["url"] = url
        record["json"] = kw.get("json")
        return _RecordedResp(record["payload"])

    return _post


def test_llm_request_contract(monkeypatch):
    """llm 请求体必须命中 /chat/completions，model 取自当前 profile，messages 结构正确。"""
    rec = {"payload": {"choices": [{"message": {"content": "一致性：中。"}}]}}
    monkeypatch.setattr(mr, "_post", _make_fake_post(rec))
    out = mr.llm("测试 prompt")
    assert rec["url"].endswith("/chat/completions")
    body = rec["json"]
    assert body["model"] == mr.TEXT_MODEL, "请求应使用当前 profile 的文本模型"
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][0]["content"] == "测试 prompt"
    assert out == "一致性：中。"


def test_llm_json_contract(monkeypatch):
    """llm_json 应稳健解析网关返回的结构化 JSON。"""
    rec = {"payload": {"choices": [{"message": {"content": '{"root_cause":"包装"}'}}]}}
    monkeypatch.setattr(mr, "_post", _make_fake_post(rec))
    assert mr.llm_json("聚合统计") == {"root_cause": "包装"}


def test_llm_json_reasoning_fallback(monkeypatch):
    """部分网关 content 为空、思考在 reasoning_content，llm_json 应回退读取。"""
    rec = {
        "payload": {
            "choices": [{"message": {"content": "", "reasoning_content": '{"root_cause":"x"}'}}]
        }
    }
    monkeypatch.setattr(mr, "_post", _make_fake_post(rec))
    assert mr.llm_json("聚合统计") == {"root_cause": "x"}


def test_extract_json_robustness():
    """_extract_json 对真实网关噪声（围栏/思考链/截断/多段 JSON）鲁棒。"""
    assert mr._extract_json('```json\n{"a":1}\n```') == {"a": 1}
    assert mr._extract_json('<think>let me think</think>{"b":2}') == {"b": 2}
    assert mr._extract_json('{"c":3') == {}  # 截断不可解析
    assert mr._extract_json('prefix {"x":1} tail {"y":2}') == {"x": 1}  # 取首个可解析对象
    assert mr._extract_json("") == {}
    assert mr._extract_json('好的，结果是：{"ok":true} 以上') == {"ok": True}


def test_model_naming_contract():
    """模型命名契约：official 等赛事档全部模型须带 qwen/ 前缀，杜绝 404/模型不存在。"""
    for prof_name, prof in mr._MODEL_ROUTER_PROFILES.items():
        models = prof.get("models", {})
        for cap, mname in models.items():
            assert re.match(r"^[\w./\-]+$", mname), f"模型名含非法字符：{mname}"
            if prof_name == "official":
                assert mname.startswith("qwen/"), (
                    f"{prof_name}.{cap}={mname} 必须以 qwen/ 开头（与官方 Model Router 白名单一致）"
                )
            if cap == "text":
                assert mname == prof["models"]["text"]
