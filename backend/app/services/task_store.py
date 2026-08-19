import json
import logging
import queue
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from threading import Lock, Event
from typing import Dict, List, Optional

# 任务/历史目录必须与配置中的 DATA_DIR 共用同一个根目录。
# 之前按 __file__ 推断路径时，本地运行会写入 backend/data，而上传结果
# 和 CSV 写入项目根目录 data，导致历史记录和下载文件彼此失联。
from app.config import DATA_DIR, RESULT_DIR

TASK_DIR = DATA_DIR / "tasks"
TASK_DIR.mkdir(parents=True, exist_ok=True)

# 历史记录目录（永久保存）
HISTORY_DIR = DATA_DIR / "history"
HISTORY_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger(__name__)

# 日志队列：task_id -> queue.Queue（由 logging_config.py 管理）
_log_queues: Dict[str, queue.Queue] = {}
_log_queues_lock = Lock()


def get_task_logs(task_id: str, max_count: int = 100) -> list:
    """获取积压的日志（供 SSE 推送）"""
    with _log_queues_lock:
        q = _log_queues.get(task_id)
    if q is None:
        return []
    logs = []
    while len(logs) < max_count:
        try:
            item = q.get_nowait()
            logs.append(item)
        except queue.Empty:
            break
    return logs


def register_log_queue(task_id: str, q: queue.Queue):
    """注册日志队列（由 logging_config.py 调用）"""
    with _log_queues_lock:
        _log_queues[task_id] = q


def unregister_log_queue(task_id: str):
    """注销日志队列"""
    with _log_queues_lock:
        _log_queues.pop(task_id, None)


class TaskStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Task:
    task_id: str
    status: str
    progress: int
    total: int
    completed: int
    results: List[dict] = field(default_factory=list)
    csv_filename: Optional[str] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)


# 内存存储（受 _tasks_lock 保护）
_tasks: Dict[str, Task] = {}
_tasks_lock = Lock()

# SSE 订阅者：task_id -> threading.Event（跨线程信号，受 _sse_lock 保护）
_sse_signals: Dict[str, Event] = {}
_sse_lock = Lock()

# 优雅停机标志
_shutdown_event = threading.Event()


def request_shutdown():
    """请求停止所有后台任务（收到 SIGTERM 时调用）"""
    _shutdown_event.set()


def is_shutting_down() -> bool:
    return _shutdown_event.is_set()


def _cleanup_old():
    """启动时清理 24 小时前的任务文件"""
    cutoff = time.time() - 86400
    for f in TASK_DIR.glob("*.json"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
        except Exception:
            pass


# ==================== 历史记录管理 ====================

def _migrate_to_history(task: Task):
    """将已完成/失败的任务迁移到 history 目录"""
    history_path = HISTORY_DIR / f"{task.task_id}.json"
    try:
        with open(history_path, "w", encoding="utf-8") as f:
            json.dump(asdict(task), f, ensure_ascii=False, indent=2)
        # 删除原始任务文件（不再等待 24h 清理）
        original = TASK_DIR / f"{task.task_id}.json"
        if original.exists():
            original.unlink()
        logger.debug(f"任务 {task.task_id} 已迁移到 history")
    except Exception as e:
        logger.error(f"迁移任务 {task.task_id} 到 history 失败: {e}")


def get_history_list(limit: int = 50, offset: int = 0) -> tuple:
    """
    获取历史记录列表（摘要）。
    返回 (items, total) 元组。
    """
    tasks = []
    for f in sorted(HISTORY_DIR.glob("*.json"), key=lambda x: -x.stat().st_mtime):
        try:
            with open(f, encoding="utf-8") as fp:
                task_data = json.load(fp)
            results = task_data.get("results", [])
            # 计算问题数
            issue_count = sum(
                1 for r in results
                if r.get("model1_issue") == "存在问题"
                or r.get("model5_issue") == "存在问题"
                or r.get("model10_issue") == "存在问题"
                or r.get("model3_issue") == "存在问题"
            )
            files = [r.get("filename", "") for r in results]
            tasks.append({
                "task_id": task_data["task_id"],
                "created_at": task_data["created_at"],
                "file_count": len(files),
                "files_summary": "、".join(files[:3]) + ("等" + str(len(files)) + "个文件" if len(files) > 3 else ""),
                "issue_count": issue_count,
                "total_count": len(files),
                "csv_filename": task_data.get("csv_filename"),
                "status": task_data.get("status", "unknown"),
            })
        except Exception:
            continue
    total = len(tasks)
    return tasks[offset:offset + limit], total


def get_history_task(task_id: str) -> Optional[dict]:
    """获取单条历史记录的完整数据"""
    path = HISTORY_DIR / f"{task_id}.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def delete_history_task(task_id: str) -> bool:
    """删除单条历史记录及其 CSV"""
    task = get_history_task(task_id)
    if not task:
        return False
    # 删除 CSV
    csv_filename = task.get("csv_filename")
    if csv_filename:
        csv_path = RESULT_DIR / csv_filename
        try:
            if csv_path.exists():
                csv_path.unlink()
        except Exception:
            pass
    # 删除 JSON
    path = HISTORY_DIR / f"{task_id}.json"
    try:
        if path.exists():
            path.unlink()
    except Exception:
        return False
    return True


def clear_all_history() -> int:
    """清除全部历史记录，返回删除数量"""
    count = 0
    for f in HISTORY_DIR.glob("*.json"):
        try:
            with open(f, encoding="utf-8") as fp:
                task_data = json.load(fp)
            csv_filename = task_data.get("csv_filename")
            if csv_filename:
                (RESULT_DIR / csv_filename).unlink(missing_ok=True)
            f.unlink()
            count += 1
        except Exception:
            pass
    return count


_cleanup_old()


def create_task(total: int) -> Task:
    task = Task(
        task_id=str(uuid.uuid4()),
        status=TaskStatus.PENDING.value,
        progress=0,
        total=total,
        completed=0,
        results=[],
        error=None,
        created_at=time.time(),
    )
    with _tasks_lock:
        _tasks[task.task_id] = task
    return task


def get_task(task_id: str) -> Optional[Task]:
    with _tasks_lock:
        return _tasks.get(task_id)


def get_sse_signal(task_id: str) -> Optional[Event]:
    with _sse_lock:
        return _sse_signals.get(task_id)


def create_sse_signal(task_id: str) -> Event:
    with _sse_lock:
        e = Event()
        _sse_signals[task_id] = e
        return e


def clear_sse_signal(task_id: str):
    """重置 SSE 信号，避免忙等；调用方获取状态后应调用此方法"""
    with _sse_lock:
        e = _sse_signals.get(task_id)
    if e is not None:
        e.clear()


def close_sse_signal(task_id: str):
    with _sse_lock:
        _sse_signals.pop(task_id, None)


def _save(task: Task):
    """持久化任务到磁盘，重试最多 2 次；仅写入成功后才通知 SSE"""
    path = TASK_DIR / f"{task.task_id}.json"
    for attempt in range(2):  # 0, 1 共 2 次尝试
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(asdict(task), f, ensure_ascii=False, indent=2)
            # 写入成功后通知 SSE 订阅者
            with _sse_lock:
                e = _sse_signals.get(task.task_id)
            if e is not None:
                e.set()
            return
        except Exception as e:
            if attempt == 1:
                logger.error(f"保存任务 {task.task_id} 失败（重试2次）: {e}")
            else:
                time.sleep(0.5)


def _update_progress(task_id: str, completed: int, total: int):
    """更新进度（内部函数，不做锁保护，由调用方确保线程安全）"""
    task = _tasks.get(task_id)
    if task:
        task.completed = completed
        task.progress = int(completed / total * 100) if total > 0 else 0


def update_task_progress(task_id: str, completed: int, total: int):
    """更新进度并持久化到磁盘"""
    with _tasks_lock:
        _update_progress(task_id, completed, total)
        task = _tasks.get(task_id)
    if task:
        _save(task)


def process_task_async(task_id: str, file_paths: List[Path]):
    """后台线程处理任务"""
    # 配置该任务的日志系统（将日志写入 SSE 队列）
    from app.logging_config import setup_logging
    setup_logging(task_id)

    with _tasks_lock:
        task = _tasks.get(task_id)
    if not task:
        return

    with _tasks_lock:
        task.status = TaskStatus.PROCESSING.value
    _save(task)

    try:
        # 延迟导入避免循环
        from app.main import process_batch, save_results_to_csv
        # 构建进度回调：每完成一个文件则更新进度并持久化
        # 如果收到停机信号则提前终止处理
        def on_file_completed(completed: int, total: int):
            if is_shutting_down():
                raise KeyboardInterrupt("收到停机信号，停止处理")
            update_task_progress(task_id, completed, total)

        # 处理文件（带进度更新）
        results = process_batch(file_paths, progress_callback=on_file_completed)

        with _tasks_lock:
            task.status = TaskStatus.COMPLETED.value
            task.progress = 100
            task.completed = len(results)
            task.results = [r.model_dump() for r in results]
        _save(task)

        # 同时保存 CSV
        ts = int(time.time())
        csv_filename = f"batch_{ts}.csv"
        csv_path = RESULT_DIR / csv_filename
        save_results_to_csv(results, csv_path)
        with _tasks_lock:
            task.csv_filename = csv_filename
        _save(task)

        # 迁移到历史记录（永久保存）
        _migrate_to_history(task)

    except KeyboardInterrupt:
        with _tasks_lock:
            task.status = TaskStatus.FAILED.value
            task.error = "任务因系统停机而中断"
        _save(task)
        _migrate_to_history(task)
    except Exception as e:
        with _tasks_lock:
            task.status = TaskStatus.FAILED.value
            task.error = str(e)
        _save(task)
        _migrate_to_history(task)
    finally:
        # 清理上传的文件
        import os
        for fp in file_paths:
            try:
                if fp.exists():
                    os.remove(fp)
                # 上传接口为每个文件创建独立目录，避免同名文件互相覆盖。
                # 仅清理带有受控前缀的空目录，绝不触碰用户目录。
                if fp.parent.name.startswith(".upload_"):
                    fp.parent.rmdir()
            except Exception:
                pass


def _cleanup_memory_tasks():
    """每小时清理一次已完成/失败且创建超过 1 小时的任务"""
    while not _shutdown_event.is_set():
        time.sleep(3600)
        with _tasks_lock:
            expired = [
                tid for tid, t in _tasks.items()
                if t.status in (TaskStatus.COMPLETED.value, TaskStatus.FAILED.value)
                and (time.time() - t.created_at) > 3600
            ]
            for tid in expired:
                del _tasks[tid]


# 启动内存清理线程（daemon=True，随进程一起终止）
_cleanup_thread = threading.Thread(target=_cleanup_memory_tasks, daemon=True)
_cleanup_thread.start()
