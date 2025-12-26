
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional, Dict, Any, List

from fastapi import HTTPException

from utils.log_kit import get_logger

logger = get_logger()

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BACKTEST_DIR = PROJECT_ROOT / "策略仓库" / "二号网格策略"
CONFIG_FILE = BACKTEST_DIR / "config.py"
BACKTEST_SCRIPT = BACKTEST_DIR / "backtest.py"

class BacktestService:
    _instance = None
    _is_running = False
    _lock = threading.Lock()
    _logs: List[str] = []

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(BacktestService, cls).__new__(cls)
        return cls._instance

    def get_config_content(self) -> str:
        if not CONFIG_FILE.exists():
            raise HTTPException(status_code=404, detail="Config file not found")
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return f.read()

    def update_config_content(self, content: str):
        if not CONFIG_FILE.exists():
            raise HTTPException(status_code=404, detail="Config file not found")
        
        # Backup before writing
        backup_file = CONFIG_FILE.with_suffix(".py.bak")
        shutil.copy2(CONFIG_FILE, backup_file)
        
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            # Restore backup if write fails
            shutil.copy2(backup_file, CONFIG_FILE)
            raise HTTPException(status_code=500, detail=f"Failed to write config: {str(e)}")

    def run_backtest(self) -> Dict[str, Any]:
        with self._lock:
            if self._is_running:
                raise HTTPException(status_code=400, detail="Backtest is already running")
            self._is_running = True
            self._logs = [] # Clear logs

        def _run():
            try:
                logger.info("Starting backtest...")
                self._logs.append("Starting backtest process...")
                env = os.environ.copy()
                env["PYTHONUTF8"] = "1"
                project_root = str(PROJECT_ROOT)
                env["PYTHONPATH"] = (
                    f"{project_root}{os.pathsep}{env['PYTHONPATH']}"
                    if env.get("PYTHONPATH")
                    else project_root
                )
                
                # Use the same python interpreter as the current process or find one
                python_executable = sys.executable or "python3"
                
                process = subprocess.Popen(
                    [python_executable, str(BACKTEST_SCRIPT)],
                    cwd=str(BACKTEST_DIR),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, # Merge stderr to stdout
                    text=True,
                    env=env,
                    bufsize=1,
                    universal_newlines=True
                )
                
                # Read stdout line by line
                if process.stdout:
                    for line in process.stdout:
                        line = line.strip()
                        if line:
                            self._logs.append(line)
                            logger.debug(f"[Backtest] {line}")
                
                process.wait()
                
                if process.returncode != 0:
                    msg = f"Backtest failed with code {process.returncode}"
                    logger.error(msg)
                    self._logs.append(msg)
                else:
                    msg = "Backtest completed successfully"
                    logger.info(msg)
                    self._logs.append(msg)
                    
            except Exception as e:
                msg = f"Backtest execution error: {str(e)}"
                logger.error(msg)
                self._logs.append(msg)
            finally:
                with self._lock:
                    self._is_running = False

        thread = threading.Thread(target=_run)
        thread.start()
        
        return {"status": "started", "msg": "Backtest process started in background"}

    def get_status(self) -> Dict[str, Any]:
        return {
            "is_running": self._is_running,
            "logs_count": len(self._logs)
        }

    def get_logs(self) -> List[str]:
        return self._logs

    def get_reports(self) -> List[str]:
        """List all available backtest reports."""
        reports_dir = BACKTEST_DIR / "data" / "回测结果"
        if not reports_dir.exists():
            return []
        
        reports = []
        for item in reports_dir.iterdir():
            if not item.is_dir():
                continue

            single_html = item / "资金曲线.html"
            portfolio_html_cn = item / "组合报告" / "组合资金曲线.html"
            portfolio_html_en = item / "portfolio_report" / "组合资金曲线.html"

            if single_html.exists() or portfolio_html_cn.exists() or portfolio_html_en.exists():
                reports.append(item.name)
        
        # Sort by modification time (newest first)
        reports.sort(key=lambda x: (reports_dir / x).stat().st_mtime, reverse=True)
        return reports

    def get_report_html_path(self, report_name: str) -> Path:
        """Get the path to the report HTML file."""
        base = BACKTEST_DIR / "data" / "回测结果" / report_name
        candidates = [
            base / "资金曲线.html",
            base / "组合报告" / "组合资金曲线.html",
            base / "portfolio_report" / "组合资金曲线.html",
        ]
        for p in candidates:
            if p.exists():
                return p
        raise HTTPException(status_code=404, detail="Report not found")

backtest_service = BacktestService()
