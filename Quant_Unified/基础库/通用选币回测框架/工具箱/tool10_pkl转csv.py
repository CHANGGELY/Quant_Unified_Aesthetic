"""
邢不行｜策略分享会
选币策略框架𝓟𝓻𝓸

版权所有 ©️ 邢不行
微信: xbx1717

本代码仅供个人学习使用，未经授权不得复制、修改或用于商业用途。

Author: 邢不行

使用方法：
        直接运行文件即可
"""


import sys
import pickle
import csv
import shlex
from pathlib import Path

import pandas as pd


def pickle_to_csv(input_path, output_path=None):
    try:
        with open(input_path, "rb") as f:
            data = pickle.load(f)
        print(f"成功加载Pickle文件: {input_path}")
    except Exception as e:
        print(f"读取Pickle文件失败: {e}")
        return

    input_path = Path(input_path)
    if output_path is None:
        output_path = input_path.with_suffix(".csv")
    else:
        output_path = Path(output_path)

    if isinstance(data, (pd.DataFrame, pd.Series)):
        try:
            data.to_csv(output_path, index=False)
            print(f"成功保存CSV文件到: {output_path}")
            return
        except Exception as e:
            print(f"Pandas保存失败: {e}")

    try:
        if isinstance(data, list) and data and isinstance(data[0], dict):
            with open(output_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=data[0].keys())
                writer.writeheader()
                writer.writerows(data)
        elif isinstance(data, list) and data and isinstance(data[0], (list, tuple)):
            with open(output_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerows(data)
        else:
            with open(output_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                if isinstance(data, dict):
                    writer.writerow(data.keys())
                    writer.writerow(data.values())
                else:
                    writer.writerow([data])

        print(f"成功保存CSV文件到: {output_path}")
    except Exception as e:
        print(f"CSV转换失败: {e}")
        print("支持的数据类型: DataFrame/Series/字典列表/二维列表/字典/基础类型")


def _normalize_input_path(p: str) -> str:
    p = p.strip()
    if len(p) >= 2 and ((p[0] == p[-1] == '"') or (p[0] == p[-1] == "'")):
        p = p[1:-1]
    return p


def main():
    if len(sys.argv) > 1:
        for pickle_file in sys.argv[1:]:
            pickle_to_csv(_normalize_input_path(pickle_file))
        return

    print("请输入要转换的.pkl文件路径，可以输入多个，用空格分隔:")
    line = input().strip()
    if not line:
        print("未输入任何路径，程序结束")
        return

    try:
        paths = shlex.split(line, posix=False)
    except ValueError as e:
        print(f"解析输入失败: {e}")
        return

    for p in paths:
        pickle_to_csv(_normalize_input_path(p))


if __name__ == "__main__":
    main()

