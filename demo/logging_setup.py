"""ReturnGuard · 结构化日志与请求追踪（A26）

- JsonFormatter：把每条日志记录输出为单行 JSON（ts/level/logger/msg/request_id + 业务 extra），
  便于 ELK/Loki 等集中采集与告警，替代原先仅面向人读的纯文本格式。
- request_id：用 contextvars 在线程/协程间透传，使同一次 HTTP 请求内的所有日志共享同一
  request_id，排障时可端到端串联（并发安全，无全局污染）。
- RequestIdFilter：把当前 request_id 注入每条 LogRecord，JSON 格式化时一并输出。
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
import uuid

# 当前请求的 request_id（默认 "-" 表示非请求上下文，如启动期/后台任务）。
request_id: contextvars.ContextVar[str] = contextvars.ContextVar("rg_request_id", default="-")


def new_request_id() -> str:
    """生成一个短 request_id（16 hex）。"""
    return uuid.uuid4().hex[:16]


class RequestIdFilter(logging.Filter):
    """把当前请求的 request_id 注入每条日志记录。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id.get()
        return True


class JsonFormatter(logging.Formatter):
    """单行 JSON 日志格式化（A26）。

    输出字段：ts(ISO8601)/level/logger/msg/request_id，外加记录中携带的任意 extra
    （如 event/status_code/latency_ms），便于结构化检索；异常以 err 字段附异常栈。
    """

    _RESERVED = {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName",
        "request_id",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        if record.exc_info:
            payload["err"] = self.formatException(record.exc_info)
        # 业务 extra（event/latency_ms/status_code 等）一并输出
        for k, v in record.__dict__.items():
            if k in self._RESERVED or k.startswith("_"):
                continue
            try:
                json.dumps(v)
            except (TypeError, ValueError):
                v = repr(v)
            payload[k] = v
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: int = logging.INFO) -> None:
    """安装 JSON 日志处理器（A26）。幂等：重复调用不会堆叠 handler。"""
    root = logging.getLogger()
    if any(getattr(h, "_rg_json", False) for h in root.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RequestIdFilter())
    handler._rg_json = True  # type: ignore[attr-defined]
    # 清掉此前 basicConfig 可能挂的默认 stderr handler，避免重复输出
    root.handlers = [h for h in root.handlers if not getattr(h, "_rg_json", False)]
    root.addHandler(handler)
    root.setLevel(level)
    # 第三方库降噪：uvicorn 访问日志 / SQLAlchemy 引擎日志改为 WARNING
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
