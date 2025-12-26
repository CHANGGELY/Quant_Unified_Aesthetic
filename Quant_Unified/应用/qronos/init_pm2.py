import json
import sys
import os
from pathlib import Path

# Add current directory to path so we can import modules
sys.path.append(os.getcwd())

from model.model import Pm2CfgModel
from service.command import create_pm2_cfg
from utils.log_kit import logger
from utils.constant import FRAMEWORK_ROOT_PATH

# Config
framework_name = 'select-coin-trade'
candidates = [
    p for p in FRAMEWORK_ROOT_PATH.iterdir()
    if p.is_dir() and not p.is_symlink() and (p.name == framework_name or p.name.startswith(framework_name + '_'))
]
framework_path = sorted(candidates, key=lambda x: x.stat().st_mtime, reverse=True)[0] if candidates else (FRAMEWORK_ROOT_PATH / framework_name)
framework_id = 'select-coin-trade'
apps = ['realtime_data', 'startup']

logger.info(f"Generating PM2 config for {framework_id} at {framework_path}")

# Generate App Configs
pm2_apps = []
for app in apps:
    cfg = create_pm2_cfg(app_name=app, framework_id=framework_id, framework_path=framework_path)
    pm2_apps.append(cfg)

# Create and Save startup.json
pm2_cfg = Pm2CfgModel(apps=pm2_apps)
config_path = framework_path / 'startup.json'
config_path.write_text(json.dumps(pm2_cfg.model_dump(), ensure_ascii=False, indent=2))

print(f"Successfully generated startup.json at {config_path}")
print(config_path.read_text())
