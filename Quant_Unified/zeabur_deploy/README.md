# Zeabur 部署（从仓库根目录构建）

这份目录现在只保留“部署配置”，不再复制一套主代码。

## 为什么要这么做？

把 `zeabur_deploy` 复制一份代码再部署，就像你有两本一模一样的作业本：
- 你改了其中一本，另一本没改，最后就会“回测/实盘/部署”三套逻辑越走越远。

现在的做法是“单一事实源”（Single Source of Truth：只有一份真代码）：
- 主代码永远以 `Quant_Unified/` 为准
- `Quant_Unified/zeabur_deploy/` 只管“怎么在 Zeabur 上跑起来”

## Zeabur 怎么配置？

你可以把 Zeabur 理解成“它会去 GitHub 拉代码，然后按 Dockerfile 做一个能跑的盒子”。

关键点只有两个：
1) **构建上下文（Build Context）**：用仓库根目录（也就是这个项目最外层）
2) **Dockerfile 路径**：用 `Quant_Unified/zeabur_deploy/Dockerfile`

## 启动脚本

容器启动时会执行：
- `Quant_Unified/zeabur_deploy/entrypoint.sh`

它会用 `python -X utf8 -u` 启动：
- `Quant_Unified/策略仓库/八号香农策略/real_trading.py`

`-u` 的意思是“不缓冲日志”，你能在 Zeabur 控制台实时看到输出。

