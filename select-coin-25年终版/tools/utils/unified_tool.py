import json
from pathlib import Path

import pandas as pd

from core.utils.path_kit import get_file_path


class UnifiedToolParam:
    input_path: Path
    output_path: Path

    # 直接嵌入 表格
    html_styled = """
        <!DOCTYPE html>
        <html>
        <head>
        <meta charset="utf-8">
        <style>
          .my-table {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
              sans-serif;
            border-collapse: collapse;
            width: 100%;
            font-size: 14px;
            background-color: #fff;
            color: #111827;
          }}

          .my-table th,
          .my-table td {{
            border: 1px solid #e5e7eb;
            padding: 8px 12px;
            text-align: left;
          }}

          .my-table th {{
            background-color: #f3f4f6;
            font-weight: 600;
            color: #374151;
          }}

          .my-table tr:hover {{
            background-color: #f9fafb;
          }}
        </style>
        </head>
        <body>
            {}
        </body>
        </html>
        """

    # 直接嵌入 文本超链接 , 文本名称
    html_a = """<a href="{}" target="_blank" style="color: #2563eb; text-decoration: none"
              onmouseover="this.style.textDecoration='underline';" onmouseout="this.style.textDecoration='none';"
              >{}</a>"""

    def __init__(self, name: str):
        self.input_path = get_file_path('data', 'tools_config', f'{name}_input.json', as_path_type=True)
        self.output_path = get_file_path('data', 'tools_config', f'{name}_output.json', as_path_type=True)

    def get_input_json(self):
        if self.input_path.exists():
            with open(self.input_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def save_output_json(self, data):
        if not data:
            return

        with open(self.output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    @classmethod
    def dataframe_to_html(cls, df: pd.DataFrame, html_path: str):
        html = df.to_html(classes='my-table', escape=False)
        # 保存为HTML文件
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(cls.html_styled.format(html))

    @classmethod
    def dataframe_to_html_with_link(cls, df: pd.DataFrame, html_path: str, col_file_name: str, tart_col_name: str,
                                    folder_path: str):
        df = df.copy(deep=False)
        df[tart_col_name] = df.apply(
            lambda row: cls.html_a.format(f"/analysis/{folder_path+row[col_file_name]}", Path(row[col_file_name]).stem), axis=1)
        del df[col_file_name]
        cls.dataframe_to_html(df, html_path)
