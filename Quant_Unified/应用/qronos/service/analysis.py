
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import List, Dict, Any

from fastapi import HTTPException
from utils.log_kit import get_logger

logger = get_logger()

REPO_ROOT = Path(__file__).resolve().parents[3]
PROJECT_ROOT = REPO_ROOT / "策略仓库" / "一号择时策略" / "select-coin-feat-long_short_compose"
TOOLS_DIR = PROJECT_ROOT / "tools"
OUTPUT_DIR = PROJECT_ROOT / "data" / "分析结果"

TOOL_1_SCRIPT = TOOLS_DIR / "tool1_因子分析.py"
TOOL_4_SCRIPT = TOOLS_DIR / "tool4_选币相似度.py"
TOOL_5_SCRIPT = TOOLS_DIR / "tool5_资金曲线涨跌幅对比.py"

class AnalysisService:
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AnalysisService, cls).__new__(cls)
        return cls._instance

    def _run_script(self, script_path: Path, cwd: Path) -> List[str]:
        logs = []
        try:
            logger.info(f"Starting script: {script_path}")
            env = os.environ.copy()
            env["PYTHONUTF8"] = "1"

            repo_root = str(REPO_ROOT)
            env["PYTHONPATH"] = (
                f"{repo_root}{os.pathsep}{env['PYTHONPATH']}" if env.get("PYTHONPATH") else repo_root
            )
            
            python_executable = sys.executable or "python3"
            
            process = subprocess.Popen(
                [python_executable, str(script_path)],
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
                bufsize=1,
                universal_newlines=True
            )
            
            if process.stdout:
                for line in process.stdout:
                    line = line.strip()
                    if line:
                        logs.append(line)
                        logger.debug(f"[{script_path.name}] {line}")
            
            process.wait()
            
            if process.returncode != 0:
                raise Exception(f"Script failed with code {process.returncode}")
                
            return logs
        except Exception as e:
            logger.error(f"Error running script {script_path}: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    def run_factor_analysis(self) -> List[str]:
        with self._lock:
            return self._run_script(TOOL_1_SCRIPT, PROJECT_ROOT)

    def run_similarity_analysis(self) -> List[str]:
        with self._lock:
            return self._run_script(TOOL_4_SCRIPT, PROJECT_ROOT)

    def run_correlation_analysis(self) -> List[str]:
        with self._lock:
            return self._run_script(TOOL_5_SCRIPT, PROJECT_ROOT)

    def get_factor_reports(self) -> List[str]:
        report_dir = OUTPUT_DIR / "因子分析"
        if not report_dir.exists():
            return []
        return [f.name for f in report_dir.glob("*.html")]

    def get_factor_report_path(self, report_name: str) -> Path:
        path = OUTPUT_DIR / "因子分析" / report_name
        if not path.exists():
            raise HTTPException(status_code=404, detail="Report not found")
        return path

    def get_similarity_report_path(self) -> Path:
        path = OUTPUT_DIR / "选币相似度" / "多策略选币相似度对比.html"
        if not path.exists():
            raise HTTPException(status_code=404, detail="Report not found")
        return path

    def get_correlation_report_path(self) -> Path:
        path = OUTPUT_DIR / "资金曲线涨跌幅相关性" / "多策略选币资金曲线涨跌幅相关性.html"
        if not path.exists():
            raise HTTPException(status_code=404, detail="Report not found")
        return path

analysis_service = AnalysisService()
