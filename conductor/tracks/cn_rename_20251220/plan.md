# Track Plan: 核心目录与文件名全面中文化重构

## Phase 1: 准备与映射 [checkpoint: 9f424f1]
- [x] Task: 扫描当前目录结构，创建详细的“英文->中文”重命名映射表，并保存为 `rename_map.json` 供确认。 <!-- id: cae446d -->
- [x] Task: Conductor - User Manual Verification '准备与映射' (Protocol in workflow.md) <!-- id: da76e26 -->

## Phase 2: 执行重命名 (使用 Git)
- [x] Task: 使用 `git mv` 按照映射表对顶级目录（strategies, tests, libs 等）进行重命名。 <!-- id: rename_top_dirs -->
- [x] Task: 重命名 `Quant_Unified` 根目录下的关键 Python 文件（如 `main.py` -> `启动入口.py`，如果有的话）。 <!-- id: rename_root_files -->
- [x] Task: Conductor - User Manual Verification '执行重命名 (使用 Git)' (Protocol in workflow.md) <!-- id: verify_phase2 -->

## Phase 3: 修复引用与配置
- [x] Task: 全局搜索旧的目录名称字符串，批量替换 Python 代码中的 `import` 语句（例如 `from strategies import` -> `from 策略仓库 import`）。 <!-- id: fix_imports -->
- [x] Task: 更新 `sitecustomize.py` 或其他环境配置文件中的路径。 <!-- id: update_config -->
- [x] Task: 更新 `README.md` 文档中的目录结构说明。 <!-- id: update_readme -->
- [x] Task: Conductor - User Manual Verification '修复引用与配置' (Protocol in workflow.md) <!-- id: verify_phase3 -->

## Phase 4: 验证与清理
- [x] Task: 尝试运行现有的测试脚本或启动命令，捕捉 `ModuleNotFoundError` 并修复。
- [x] Task: 检查 Git 状态，提交所有更改。
- [x] Task: Conductor - User Manual Verification '验证与清理' (Protocol in workflow.md)
