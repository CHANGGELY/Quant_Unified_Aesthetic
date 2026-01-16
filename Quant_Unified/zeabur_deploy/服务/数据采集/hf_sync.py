"""
Quant Unified 量化交易系统
Hugging Face Dataset 同步工具
"""
import os
import shutil
from pathlib import Path
from huggingface_hub import HfApi, create_repo
from datetime import datetime
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 配置区域
# ---------------------------------------------------------
# 数据集名称: 用户名/数据集名
DATASET_REPO = "chenchuanshen/Quant_Market_Data"
# 本地行情数据路径
LOCAL_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "行情数据_整理"
# ---------------------------------------------------------

def sync_to_hf():
    """执行同步逻辑"""
    token = os.getenv("HF_TOKEN")
    if not token:
        logger.error("❌ 未找到 HF_TOKEN，无法同步到 Dataset。请在 Space 的 Secrets 中配置。")
        return False
    
    # 获取或创建数据集
    repo_id = DATASET_REPO
    try:
        api = HfApi(token=token)
        # 尝试创建仓库，如果已存在会报错，我们忽略它
        try:
            api.create_repo(repo_id=repo_id, repo_type="dataset", exist_ok=True)
            logger.info(f"✅ 数据集仓库已就绪: {repo_id}")
        except Exception as e:
            if "already exists" not in str(e):
                logger.error(f"❌ 创建/检查数据集仓库失败: {e}")
                return False

        # 检查本地目录
        if not LOCAL_DATA_DIR.exists():
            logger.warning(f"⚠️ 本地目录不存在，跳过同步: {LOCAL_DATA_DIR}")
            return True

        # 上传整个目录
        logger.info(f"📤 正在同步数据到 Hugging Face Dataset: {repo_id}...")
        api.upload_folder(
            folder_path=str(LOCAL_DATA_DIR),
            repo_id=repo_id,
            repo_type="dataset",
            commit_message=f"Auto-sync: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            ignore_patterns=["*.tmp", "*.log"]
        )
        logger.info("✅ 同步完成！")
        
        # --- 新增：同步成功后清理本地已整理的文件，节省 1GB 空间 ---
        logger.info("🧹 正在清理本地已上传的数据以节省空间...")
        try:
            import shutil
            for item in os.listdir(LOCAL_DATA_DIR):
                item_path = os.path.join(LOCAL_DATA_DIR, item)
                if os.path.isfile(item_path):
                    os.remove(item_path)
                elif os.path.isdir(item_path):
                    shutil.rmtree(item_path)
            logger.info("✅ 本地已整理数据清理完毕，空间已释放。")
        except Exception as e:
            logger.warning(f"⚠️ 清理本地空间时出错 (非致命): {e}")
            
        return True
    except Exception as e:
        logger.error(f"❌ 同步过程中发生错误: {e}")
        return False

if __name__ == "__main__":
    sync_to_hf()
