"""
因子AI代码分析工具
从 factors 目录中选择任意因子文件，展示源码并分析是否存在未来函数或标签风险。
默认使用本地静态规则进行检测，可选接入外部 AI 接口做进一步审查。

AI 接口配置说明（可选，不开启也能用静态检测）：

1. 安装依赖（仅首次）：
   pip install streamlit requests

2. 通过环境变量配置 API（任选其一）：
   - 使用 DeepSeek 官方接口（推荐）：
       DEEPSEEK_API_KEY  : 你的 DeepSeek API 密钥
       DEEPSEEK_BASE_URL : https://api.deepseek.com/v1  （可省略，默认为此）
       DEEPSEEK_MODEL    : deepseek-chat                （可省略，默认为此）

   - 使用任意 OpenAI 兼容接口：
       OPENAI_API_KEY    : 你的接口密钥
       OPENAI_BASE_URL   : 平台提供的 base_url，例如 https://xxx/v1
       OPENAI_MODEL      : 模型名称，例如 gpt-4o-mini

3. 在同一个终端中设置环境变量后运行本工具，例如（Windows PowerShell）：
   $env:DEEPSEEK_API_KEY="你的密钥填写在此"
   $env:DEEPSEEK_BASE_URL="https://api.deepseek.com/v1"
   $env:DEEPSEEK_MODEL="deepseek-chat"
   streamlit run tools/tool11_因子AI代码分析.py
复制上面四行到运行本工具

未配置任何 API 时，本工具仍然可以使用“未来函数静态检测”功能。

使用方法：
         streamlit run tools/tool11_因子AI代码分析.py
"""
import os
import sys
import ast
import re
from pathlib import Path

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


FACTORS_DIR = PROJECT_ROOT / "factors"


@st.cache_data(show_spinner=False)
def list_factor_files():
    if not FACTORS_DIR.exists():
        return []
    return sorted(
        [
            p.name
            for p in FACTORS_DIR.glob("*.py")
            if p.name != "__init__.py"
        ]
    )


@st.cache_data(show_spinner=False)
def load_factor_source(filename: str) -> str:
    path = FACTORS_DIR / filename
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="gbk", errors="ignore")


def analyze_future_functions_static(source: str):
    suspicious = []
    seen = set()
    keyword_pattern = re.compile(
        r"\.shift\(\s*-\d+"
        r"|shift\(\s*-\d+"
        r"|future_"
        r"|future\s+price"
        r"|future\s*return"
        r"|forward\s*return"
        r"|前瞻"
        r"|未来数据"
        r"|lookahead"
        r"|look\s*ahead"
        r"|label"
        r"|target"
        r"|收益标签",
        re.IGNORECASE,
    )
    lines = source.splitlines()
    for lineno, line in enumerate(lines, start=1):
        if keyword_pattern.search(line):
            key = (lineno, line)
            if key not in seen:
                seen.add(key)
                suspicious.append(key)

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return suspicious, "源代码存在语法错误，无法进行完整的静态分析。"

    suspicious_name_fragments = ("future", "forward", "ahead", "label", "target")

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            attr_name = None
            if isinstance(func, ast.Attribute):
                attr_name = func.attr
            elif isinstance(func, ast.Name):
                attr_name = func.id

            if attr_name and attr_name.lower() == "shift":
                periods_value = None
                if node.args:
                    arg = node.args[0]
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, (int, float)):
                        periods_value = arg.value
                    elif (
                        isinstance(arg, ast.UnaryOp)
                        and isinstance(arg.op, ast.USub)
                        and isinstance(arg.operand, ast.Constant)
                        and isinstance(arg.operand.value, (int, float))
                    ):
                        periods_value = -arg.operand.value
                if periods_value is None:
                    for kw in node.keywords:
                        if kw.arg == "periods":
                            val = kw.value
                            if isinstance(val, ast.Constant) and isinstance(val.value, (int, float)):
                                periods_value = val.value
                            elif (
                                isinstance(val, ast.UnaryOp)
                                and isinstance(val.op, ast.USub)
                                and isinstance(val.operand, ast.Constant)
                                and isinstance(val.operand.value, (int, float))
                            ):
                                periods_value = -val.operand.value
                if isinstance(periods_value, (int, float)) and periods_value < 0:
                    lineno = getattr(node, "lineno", None)
                    if lineno is not None and 1 <= lineno <= len(lines):
                        text = lines[lineno - 1]
                        key = (lineno, text)
                        if key not in seen:
                            seen.add(key)
                            suspicious.append(key)

            if attr_name and attr_name.lower() in {"lead", "future"}:
                lineno = getattr(node, "lineno", None)
                if lineno is not None and 1 <= lineno <= len(lines):
                    text = lines[lineno - 1]
                    key = (lineno, text)
                    if key not in seen:
                        seen.add(key)
                        suspicious.append(key)

        if isinstance(node, ast.Assign):
            lineno = getattr(node, "lineno", None)
            if lineno is None or not (1 <= lineno <= len(lines)):
                continue
            is_suspicious = False
            for target in node.targets:
                if isinstance(target, ast.Name):
                    name_lower = target.id.lower()
                    if any(frag in name_lower for frag in suspicious_name_fragments):
                        is_suspicious = True
                        break
                elif isinstance(target, ast.Subscript):
                    key_node = target.slice
                    key_value = None
                    if isinstance(key_node, ast.Constant):
                        key_value = str(key_node.value)
                    if key_value:
                        name_lower = key_value.lower()
                        if any(frag in name_lower for frag in suspicious_name_fragments):
                            is_suspicious = True
                            break
            if is_suspicious:
                text = lines[lineno - 1]
                key = (lineno, text)
                if key not in seen:
                    seen.add(key)
                    suspicious.append(key)

        if isinstance(node, ast.Subscript):
            lineno = getattr(node, "lineno", None)
            if lineno is None or not (1 <= lineno <= len(lines)):
                continue
            key_node = node.slice
            key_value = None
            if isinstance(key_node, ast.Constant):
                key_value = str(key_node.value)
            if key_value:
                name_lower = key_value.lower()
                if any(frag in name_lower for frag in suspicious_name_fragments):
                    text = lines[lineno - 1]
                    key = (lineno, text)
                    if key not in seen:
                        seen.add(key)
                        suspicious.append(key)

    if not suspicious:
        summary = "静态规则未检测到明显的未来函数或标签特征，但这不代表绝对安全，请结合回测和代码逻辑进一步确认。"
    else:
        summary = "检测到若干可能涉及未来函数、前视偏差或收益标签的代码行，请重点检查这些位置是否仅使用历史可见信息。"
    return suspicious, summary


def build_ai_prompt(code: str, factor_filename: str) -> str:
    return (
        "你是一名擅长加密货币量化选币的高级风控工程师。"
        "请审查下面的因子代码，重点判断是否存在未来函数、前视偏差或使用未来数据的风险。"
        "如果存在，请给出具体行号、可疑代码片段以及原因，并给出修改建议。"
        "如果未发现明显问题，也请说明你认为安全的理由。\n\n"
        f"因子文件名: {factor_filename}\n\n"
        "源码如下：\n"
        "```python\n"
        f"{code}\n"
        "```"
    )


def analyze_with_ai(code: str, factor_filename: str) -> str:
    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        return "未检测到 DEEPSEEK_API_KEY 或 OPENAI_API_KEY 环境变量，无法调用外部 AI 接口。"
    try:
        import requests
    except ImportError:
        return "未安装 requests 库，无法通过 HTTP 调用 AI 接口。"

    base_url = (
        os.getenv("DEEPSEEK_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")
        or "https://api.deepseek.com/v1"
    )
    model = (
        os.getenv("DEEPSEEK_MODEL")
        or os.getenv("OPENAI_MODEL")
        or "deepseek-chat"
    )
    prompt = build_ai_prompt(code, factor_filename)

    url = base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是一名严格控制前视偏差的量化风控工程师。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=60)
    except Exception as e:
        return f"调用 AI 接口时出现异常: {e}"

    if resp.status_code != 200:
        text = resp.text
        if len(text) > 800:
            text = text[:800] + "..."
        return f"AI 接口调用失败，状态码 {resp.status_code}，响应: {text}"

    try:
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            return "AI 接口返回内容为空，请稍后重试或检查模型配置。"
        message = choices[0].get("message") or {}
        content = message.get("content", "")
        return content.strip() or "AI 接口未返回可解析的文本内容。"
    except Exception as e:
        return f"解析 AI 接口响应时发生错误: {e}"


def main():
    st.set_page_config(page_title="因子AI代码分析工具", layout="wide")
    st.title("因子AI代码分析工具")

    factor_files = list_factor_files()
    if not factor_files:
        st.error("未在 factors 目录下找到任何因子文件，请确认项目结构。")
        return

    col_left, col_right = st.columns([1, 1])

    with col_left:
        selected = st.selectbox("选择因子文件", options=factor_files, index=0)
        source = load_factor_source(selected)
        if not source:
            st.error("无法读取该因子文件的源码。")
        else:
            st.subheader("因子源码")
            st.code(source, language="python")

    with col_right:
        st.subheader("未来函数静态检测")
        if not source:
            st.info("请选择可用的因子文件以开始分析。")
        else:
            suspicious_lines, summary = analyze_future_functions_static(source)
            st.markdown(summary)
            if suspicious_lines:
                st.markdown("可能存在未来函数风险的代码位置：")
                for lineno, text in suspicious_lines:
                    display = f"{lineno}: {text}"
                    st.code(display, language="python")
            else:
                st.success("未发现明显的未来函数或前视偏差特征。")

        st.subheader("AI 深度审查")
        st.markdown("可选择调用外部 AI 工具，对当前因子代码进行更深入的未来函数和前视偏差分析。")
        ai_enabled = bool(os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY"))
        if not ai_enabled:
            st.warning("未检测到 DEEPSEEK_API_KEY 或 OPENAI_API_KEY 环境变量。配置后可启用 AI 分析。")

        if st.button("调用 AI 分析当前因子", disabled=not source):
            with st.spinner("正在调用 AI 工具，请稍候..."):
                result = analyze_with_ai(source, selected)
            st.markdown(result)


if __name__ == "__main__":
    main()

