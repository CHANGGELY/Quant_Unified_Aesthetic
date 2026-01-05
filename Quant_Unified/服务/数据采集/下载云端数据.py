"""
Quant Unified 量化交易系统
下载云端数据 (HF Dataset -> Local)
"""
import os
from pathlib import Path
from huggingface_hub import snapshot_download
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 配置区域
# ---------------------------------------------------------
# 数据集名称
DATASET_REPO = "chenchuanshen/Quant_Market_Data"
# 本地行情数据存放路径
LOCAL_DATA_DIR = Path(__file__).resolve().parent / "data" / "行情数据_整理"
# ---------------------------------------------------------

def download_data():
    """从 Hugging Face Dataset 下载/同步数据到本地"""
    logger.info(f"🔍 正在检查云端数据集: {DATASET_REPO}...")
    
    # 确保本地目录存在
    LOCAL_DATA_DIR.mkdir(parents=True, exist_ok=True)

    try:
        # 使用 snapshot_download 自动对比并下载增量数据
        # ignore_patterns 可以排除一些不必要的文件
        local_path = snapshot_download(
            repo_id=DATASET_REPO,
            repo_type="dataset",
            local_dir=str(LOCAL_DATA_DIR),
            local_dir_use_symlinks=False,  # 直接拷贝文件
            # token=os.getenv("HF_TOKEN") # 如果是私有数据集需要 Token
        )
        
        logger.info(f"✨ 同步完成！数据已保存至: {local_path}")
        return True
    except Exception as e:
        logger.error(f"❌ 下载失败: {e}")
        logger.info("💡 提示: 如果是私有数据集，请先运行 `huggingface-cli login` 或设置 HF_TOKEN 环境变量")
        return False

if __name__ == "__main__":
    download_data()
