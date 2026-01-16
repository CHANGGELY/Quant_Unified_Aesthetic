# ☁️ 8号香农策略 - 免费云端部署指南 (Hugging Face Spaces)

本指南教你如何利用 **Hugging Face Spaces (Free Tier)** 免费部署本策略，并通过 Docker 实现全天候运行。

---

## 🚀 部署步骤

### 1. 准备 Hugging Face Space
1. 注册/登录 [Hugging Face](https://huggingface.co/)。
2. 点击右上角头像 -> **New Space**。
3. 填写信息：
   - **Space Name**: 例如 `shannon-strategy-live`
   - **License**: `MIT` (或者其他)
   - **SDK**: 选择 **Docker** (关键!)
   - **Space Hardware**: 选择 **Free** (2 vCPU, 16GB RAM) - 足够了！
   - **Visibility**: 建议选 **Private** (私有)，防止别人看到你的日志。

### 2. 配置环境变量 (Secrets)
为了安全，**不要**把 API Key 写在代码里。请在 Space 的 **Settings** 页设置：

1. 进入 Space 页面 -> **Settings** 选项卡。
2. 找到 **Variables and secrets** 部分。
3. 点击 **New secret**，添加以下必须变量：
   - `BINANCE_API_KEY`: 你的币安 API Key
   - `BINANCE_SECRET_KEY`: 你的币安 Secret Key
   - `USE_REAL_TRADING`: `True` (开启实盘)
   - `可以跳过确认`: `yes` (跳过启动时的确认输入)

### 3. 上传代码
你需要把 `Quant_Unified` 文件夹下的内容上传到 Space。
(注意：`Dockerfile` 必须在根目录，或者在 Space 设置里指定路径。**我们现在的 Dockerfile 设计是放在 `deployment_hf` 下**)

**最佳方式** (推荐使用 Git 命令行上传)：

```bash
# 1. 克隆你的 HF Space 仓库 (在本地找个空文件夹)
git clone https://huggingface.co/spaces/<你的用户名>/<你的Space名>

# 2. 把我们项目的文件复制进去
# 将 Quant_Unified 下的所有文件复制到克隆下来的文件夹根目录

# 3. 移动 Dockerfile 到根目录 (关键!)
# 我们生成的 Dockerfile 在 deployment_hf/Dockerfile，必须移出来
mv deployment_hf/Dockerfile .

# 4. 提交并推送
git add .
git commit -m "Deploy Shannon Strategy"
git push
```

### 4. 验证运行
1. 推送后，Hugging Face 会自动开始 Build (构建镜像)。
2. 等待几分钟，如果看到 `Running`，说明启动成功。
3. 点击 **App** 选项卡，你应该能看到我们写的 **Streamlit 监控面板**。
4. 如果面板显示 "运行中 (Running)" 并且日志在滚动，恭喜你，部署成功！

---

## 📡 如何永久保活 (重要!)

免费的 Space 在 48 小时没人访问后会进入 "Sleep" 模式。
为了让策略 7x24 小时跑，你需要一个外部服务定时访问你的 App 页面。

### 使用 UptimeRobot (免费)
1. 注册 [UptimeRobot](https://uptimerobot.com/)。
2. Create New Monitor -> 选择 **HTTP(s)** 类型。
3. **URL**: 填入你 HF Space 的网址 (例如 `https://huggingface.co/spaces/user/repo` 对应的应用链接，通常是 `https://user-repo.hf.space`)。
4. **Interval**: 选 5 分钟。
5. 保存。

这样 UptimeRobot 会每 5 分钟 Ping 一下你的网页，HF 就会认为有人在使用，永远不会休眠。

---

## ❓ 常见问题

**Q: 日志时间不对？**
A: `Dockerfile` 里已经预设了 `ENV TZ=Asia/Shanghai`，日志应该是北京时间。

**Q: 报错 -5022 Post Only?**
A: 请在 `config_live.py` 里确认 `post_only=False`，或者在 HF Secrets 里添加环境变量覆盖配置。

**Q: 我想停止策略？**
A: 在 HF Space 页面点击 **Settings -> Pause Space** 即可。重启只需 Resume。
