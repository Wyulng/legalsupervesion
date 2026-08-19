import json
import logging
import os
import queue
import sys
from datetime import datetime, timezone
from logging.handlers import QueueHandler


# 全局日志开关，默认关闭（生产环境）
DEBUG_LOG_ENABLED = os.getenv("DEBUG_LOG", "false").lower() in ("true", "1", "yes")


class JSONFormatter(logging.Formatter):
    """JSON 格式化器，输出 {type, timestamp, level, module, message, data}"""

    def format(self, record: logging.LogRecord) -> str:
        # 使用 datetime 格式化时间戳（datetime.strftime 支持 %f，time.strftime 不支持）
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        log_obj = {
            "type": "log",
            "timestamp": ts,
            "level": record.levelname,
            "module": record.name,
            "message": record.getMessage(),
        }
        # 附加 extra 字段（data payload）
        if hasattr(record, "log_data"):
            log_obj["data"] = record.log_data
        if hasattr(record, "task_id"):
            log_obj["task_id"] = record.task_id
        return json.dumps(log_obj, ensure_ascii=False)


class SSEQueueHandler(QueueHandler):
    """
    将日志写入异步队列，供 SSE 推送使用。
    enqueue 时直接序列化 JSON 字符串，避免 LogRecord 对象跨线程传递问题。
    """

    def __init__(self, q: queue.Queue, formatter: logging.Formatter):
        super().__init__(q)
        self._sse_formatter = formatter

    def enqueue(self, record):
        # 直接放入 JSON 字符串，不走 QueueHandler 默认的 prepare 流程
        self.queue.put_nowait(self._sse_formatter.format(record))


def get_log_queue(task_id: str) -> queue.Queue:
    """获取或创建指定 task_id 的日志队列"""
    from app.services.task_store import register_log_queue
    with _get_lock():
        q = queue.Queue(maxsize=1000)
        register_log_queue(task_id, q)
        return q


# 模块级别的锁
_lock = None

def _get_lock():
    global _lock
    if _lock is None:
        import threading
        _lock = threading.Lock()
    return _lock


def setup_logging(task_id: str = None):
    """
    配置日志系统。
    - DEBUG_LOG=true 时，所有模块 logger 级别设为 DEBUG
    - DEBUG_LOG=false 时，仅 WARNING 及以上生效
    - task_id 用于将日志路由到对应的 SSE 队列
    """
    if not DEBUG_LOG_ENABLED:
        # 生产环境：保持 Python 默认 WARNING 级别
        logging.basicConfig(
            level=logging.WARNING,
            format="%(asctime)s %(name)s %(levelname)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            handlers=[logging.StreamHandler(sys.stdout)],
        )
        return

    # 调试模式：配置 DEBUG 级别
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # 清除已有 handlers
    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)

    # 控制台 handler（纯文本，便于 docker log / terminal 查看）
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    )
    root_logger.addHandler(console_handler)

    # 如果提供了 task_id，添加 SSE queue handler
    if task_id:
        q = get_log_queue(task_id)
        json_formatter = JSONFormatter()
        queue_handler = SSEQueueHandler(q, json_formatter)
        queue_handler.setLevel(logging.DEBUG)
        root_logger.addHandler(queue_handler)

    logging.debug(f"Logging configured for task_id={task_id}, DEBUG_MODE={DEBUG_LOG_ENABLED}")


def log_with_data(logger: logging.Logger, level: int, msg: str, task_id: str = None, **kwargs):
    """便捷方法：携带额外 data payload 记录日志"""
    extra = {"log_data": kwargs}
    if task_id:
        extra["task_id"] = task_id
    logger.log(level, msg, extra=extra)
