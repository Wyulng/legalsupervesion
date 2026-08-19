import logging
import os
from pathlib import Path
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


def _find_project_root() -> Path:
    """查找项目根目录，优先使用 PROJECT_ROOT 环境变量，否则向上查找 .env"""
    env_root = os.getenv("PROJECT_ROOT")
    if env_root:
        return Path(env_root).resolve()
    # 从当前文件位置向上回溯，寻找包含 .env 的目录
    current = Path(__file__).resolve().parent
    for _ in range(5):  # 最多向上查找 5 层
        if (current / ".env").exists():
            return current
        current = current.parent
    # 兜底：从当前文件推断常规结构（用于无 .env 文件场景）
    return Path(__file__).resolve().parent.parent.parent


BASE_DIR = _find_project_root()

# 加载 .env 文件
load_dotenv(BASE_DIR / ".env")

# 数据目录
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
RESULT_DIR = DATA_DIR / "results"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
RESULT_DIR.mkdir(parents=True, exist_ok=True)

# OpenAI 通用配置
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
if not OPENAI_API_KEY:
    logger.warning("OPENAI_API_KEY 未设置，API 调用将会失败")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-3.5-turbo")

# LLM 并发配置
try:
    LLM_MAX_CONCURRENT = int(os.getenv("LLM_MAX_CONCURRENT", "2"))
except (ValueError, TypeError):
    logger.warning(f"LLM_MAX_CONCURRENT 值无效，使用默认值 2")
    LLM_MAX_CONCURRENT = 2


def _mask_key(key: str) -> str:
    """脱敏 API Key：仅显示前4位和后4位"""
    if len(key) <= 8:
        return "****"
    return key[:4] + "****" + key[-4:]
