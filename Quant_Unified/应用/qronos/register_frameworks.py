import json
import sys
import os
from pathlib import Path
from sqlalchemy import create_engine, Column, String, Integer
from sqlalchemy.orm import sessionmaker, declarative_base

# Add current directory to path
sys.path.append(os.getcwd())

from model.model import Pm2CfgModel
from service.command import create_pm2_cfg
from utils.constant import DATA_CENTER_ID, SELECT_COIN_ID, DB_PATH, FRAMEWORK_ROOT_PATH
from utils.log_kit import logger

# 1. Re-generate PM2 Config with Correct IDs
framework_name = 'select-coin-trade'
candidates = [
    p for p in FRAMEWORK_ROOT_PATH.iterdir()
    if p.is_dir() and not p.is_symlink() and (p.name == framework_name or p.name.startswith(framework_name + '_'))
]
framework_path = sorted(candidates, key=lambda x: x.stat().st_mtime, reverse=True)[0] if candidates else (FRAMEWORK_ROOT_PATH / framework_name)
apps_config = []

# App 1: Data Center (realtime_data)
# Namespace must match DATA_CENTER_ID so backend can control it
cfg_dc = create_pm2_cfg(
    app_name='realtime_data', 
    framework_id=DATA_CENTER_ID, 
    framework_path=framework_path
)
apps_config.append(cfg_dc)

# App 2: Strategy (startup)
# Namespace must match SELECT_COIN_ID
cfg_st = create_pm2_cfg(
    app_name='startup', 
    framework_id=SELECT_COIN_ID, 
    framework_path=framework_path
)
apps_config.append(cfg_st)

# App 3: Summary Framework
# Use a new UUID or derived ID
SUMMARY_ID = "summary_" + SELECT_COIN_ID
cfg_sm = create_pm2_cfg(
    app_name='summary_framework',
    framework_id=SUMMARY_ID,
    framework_path=framework_path
)
apps_config.append(cfg_sm)

# Save startup.json
pm2_cfg = Pm2CfgModel(apps=apps_config)
config_path = framework_path / 'startup.json'
config_path.write_text(json.dumps(pm2_cfg.model_dump(), ensure_ascii=False, indent=2))
print(f"✅ Updated startup.json with correct IDs:\n- DataCenter: {DATA_CENTER_ID}\n- Strategy: {SELECT_COIN_ID}")

# 2. Register in Database (SQLite)
Base = declarative_base()

class FrameworkStatus(Base):
    __tablename__ = 'framework_status'
    id = Column(Integer, primary_key=True, index=True)
    framework_id = Column(String, unique=True, index=True)
    framework_name = Column(String)
    status = Column(String)  # finished
    type = Column(String)    # data_center, select_coin
    path = Column(String)
    time = Column(String)

# Connect to DB
engine = create_engine(f'sqlite:///{DB_PATH}')
Session = sessionmaker(bind=engine)
session = Session()

def register_framework(f_id, name, f_type):
    existing = session.query(FrameworkStatus).filter_by(framework_id=f_id).first()
    if existing:
        existing.status = 'finished'
        existing.path = str(framework_path)
        existing.framework_name = name # Update name just in case
        print(f"🔄 Updated DB record for {name} ({f_id})")
    else:
        new_record = FrameworkStatus(
            framework_id=f_id,
            framework_name=name,
            status='finished',
            type=f_type,
            path=str(framework_path),
            time='2024-01-01 00:00:00'
        )
        session.add(new_record)
        print(f"➕ Created DB record for {name} ({f_id})")

try:
    # Register Data Center
    register_framework(DATA_CENTER_ID, '实盘数据中心', 'data_center')
    
    # Register Strategy
    register_framework(SELECT_COIN_ID, '实盘选币策略', 'select_coin')
    
    session.commit()
    print("✅ Database registration complete.")
except Exception as e:
    session.rollback()
    print(f"❌ Database error: {e}")
finally:
    session.close()
