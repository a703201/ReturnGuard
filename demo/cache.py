"""ReturnGuard · 进程内缓存层（cache.py）

独立模块，专门承载「洞察聚合缓存」这一跨模块共享状态，彻底解耦 db ⇄ pipeline 的循环依赖：

- 旧结构：pipeline 在顶层 import db；db 的写库函数又在函数体内 lazy import pipeline.invalidate_insights_cache，
  形成 db ⇄ pipeline 双向耦合（靠 lazy import 掩盖，属于架构债）。
- 新结构：洞察缓存与失效信号下沉到本模块（纯内存、不依赖 db/pipeline）；
  db 的写库函数改为 `from cache import invalidate_insights_cache`，只依赖 cache；
  pipeline 仍顶层 import db，但 db 不再反向 import pipeline → 单向依赖，循环消除。

缓存特性（详见 _ins_cache_put）：
- 键：(mode, source, 案件集合指纹, 代际)，代际自增即整体失效（写库后 db 调 invalidate）。
- 线程安全：uvicorn 线程池并发下用 _ins_lock 保护。
- 容量有界：LRU（_INS_CACHE_MAX）淘汰最久未用项，避免组合爆炸（P1-缓存无界）。
- 进程内：单 worker 场景正确；多 worker（多进程）部署仍需 Redis 等共享缓存。
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict

logger = logging.getLogger("returnguard.cache")

# 洞察聚合缓存：进程内、单 worker；并发写由 _ins_lock 串行化。
_INS_CACHE_MAX = 64
_ins_cache: OrderedDict = OrderedDict()
_ins_lock = threading.Lock()


def invalidate_insights_cache() -> None:
    """使洞察聚合缓存整体失效（由 db 写库后调用：save_case / delete_case / bulk_upsert_cases）。"""
    with _ins_lock:
        _ins_cache.clear()
    logger.debug("洞察聚合缓存已失效")


def _ins_cache_put(key, value) -> None:
    """按 LRU 写入聚合缓存：超出上限淘汰最久未用项（线程安全）。"""
    with _ins_lock:
        _ins_cache[key] = value
        _ins_cache.move_to_end(key)
        while len(_ins_cache) > _INS_CACHE_MAX:
            _ins_cache.popitem(last=False)
