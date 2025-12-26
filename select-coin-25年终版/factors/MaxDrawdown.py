import numpy as np
import pandas as pd


def signal(*args):
    """
    计算最大回撤因子
    支持两种配置方式:
    1. 传统方式: (n) - 计算n根K线内的最大回撤
    2. 新方式: (n1, n2) - 在n1时间段内检查是否存在n2时间段最大回撤大于阈值
    参数:
        args[0]: DataFrame, 包含OHLCV等价格数据
        args[1]: int或tuple, 参数配置
        args[2]: str, 因子列名
    返回:
        DataFrame, 包含计算出的因子值
    """
    df = args[0]
    param = args[1]
    factor_name = args[2]

    # 默认阈值
    threshold = 0.45

    try:
        # 检查数据完整性
        if df.empty or len(df) < 2:
            df[factor_name] = 0.0
            return df

        if df['close'].isna().any():
            print("警告: close价格数据中存在NaN值")
            df[factor_name] = 0.0
            return df

        # 计算最大回撤的辅助函数
        def calc_drawdown(close_series):
            if len(close_series) < 2:
                return 0.0
            # 计算累积最大值
            cumulative_max = close_series.expanding().max()
            # 计算回撤
            drawdown = (cumulative_max - close_series) / cumulative_max
            return drawdown.max() if not drawdown.empty else 0.0

        # 判断参数类型，支持两种配置方式
        if isinstance(param, tuple) and len(param) == 2:
            # 新配置方式: (n1, n2)
            n1, n2 = param

            # 检查参数有效性
            if n2 >= n1:
                print("错误: n2必须小于n1")
                df[factor_name] = 0.0
                return df

            if len(df) < max(n1, n2):
                df[factor_name] = 0.0
                return df

            # 计算每个n2窗口的最大回撤
            n2_drawdown = df['close'].rolling(
                window=n2,
                min_periods=max(1, n2 // 2)
            ).apply(calc_drawdown, raw=False)

            # 处理NaN值
            n2_drawdown.fillna(0.0, inplace=True)

            # 在n1窗口内检查是否存在n2最大回撤大于阈值
            def check_max_drawdown_exists(drawdown_series):
                if len(drawdown_series) < 1:
                    return 0.0
                # 检查n1窗口内是否有任何一个n2最大回撤超过阈值
                return 1.0 if (drawdown_series > threshold).any() else 0.0

            # 应用n1窗口检查
            df[factor_name] = n2_drawdown.rolling(
                window=n1,
                min_periods=max(1, n1 // 2)
            ).apply(check_max_drawdown_exists, raw=False)

        else:
            # 传统配置方式: 单个整数n
            n = param if isinstance(param, int) else param[0] if isinstance(param, (list, tuple)) else param

            # 使用滚动窗口计算最大回撤
            df[factor_name] = df['close'].rolling(
                window=n,
                min_periods=1
            ).apply(calc_drawdown, raw=False)

        # 处理可能的NaN值
        df[factor_name].fillna(0.0, inplace=True)

        return df

    except Exception as e:
        print(f"计算MaxDrawdown因子时出错: {e}")
        df[factor_name] = 0.0
        return df