"""
机器学习RSI过滤因子 | 适配邢不行量化框架
功能：过滤处于下跌状态（RSI低于短期阈值）的币种
返回值：1（保留，非下跌状态）/ 0（过滤，下跌状态），适配框架数值型过滤规则
"""
import pandas as pd
import numpy as np

def signal(candle_df, param_tuple, *args):
    """
    计算机器学习RSI因子，生成过滤信号
    :param candle_df: 单个币种的K线数据（DataFrame），需包含'close'列
    :param param_tuple: 因子参数元组（可哈希类型），对应TradingView配置项
    :param args: 其他参数，args[0]为因子名称（用于新增列名）
    :return: 包含过滤信号列的K线数据DataFrame
    """
    # 将参数元组转为列表，方便按索引提取参数
    param = list(param_tuple)

    # ======================== 可调整参数（从param提取，与TradingView对应） ========================
    # RSI基础设置
    rsi_length = param[0] if len(param) > 0 else 14  # RSI计算周期
    smooth_rsi = param[1] if len(param) > 1 else True  # 是否平滑RSI
    ma_type = param[2] if len(param) > 2 else 'Ema'  # 平滑均线类型
    smooth_period = param[3] if len(param) > 3 else 4  # 平滑周期
    alma_sigma = param[4] if len(param) > 4 else 6  # ALMA均线的sigma参数（仅ALMA用）

    # 机器学习阈值范围
    min_thresh = param[5] if len(param) > 5 else 15  # 阈值最小值
    max_thresh = param[6] if len(param) > 6 else 85  # 阈值最大值
    step = param[7] if len(param) > 7 else 5  # 步长（暂用于参数占位，不影响核心计算）

    # 聚类优化参数
    perf_memory = param[8] if len(param) > 8 else 8  # 性能内存（占位）
    max_clustering_steps = param[9] if len(param) > 9 else 800  # 最大聚类迭代次数
    max_data_points = param[10] if len(param) > 10 else 1500  # 用于聚类的最大数据点数量

    # 因子列名称（从args获取，默认'MLRSIFactor'）
    factor_name = args[0] if args else 'MLRSIFactor'
    # ==================================================================================

    # 1. 计算原始RSI（无外部依赖）
    close_series = candle_df['close']
    delta = close_series.diff()  # 价格变动差值
    # 计算上涨/下跌均值（滚动窗口）
    gain = (delta.where(delta > 0, 0)).rolling(window=rsi_length, min_periods=rsi_length).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=rsi_length, min_periods=rsi_length).mean()
    # 避免除零错误，替换loss为0的值
    rs = gain / loss.replace(0, 1e-10)
    # RSI计算公式：100 - (100 / (1 + RS))
    rsi = 100 - (100 / (1 + rs))

    # 2. 平滑RSI（根据配置选择均线类型）
    if smooth_rsi:
        rsi = ma(
            src=rsi,
            length=smooth_period,
            ma_type=ma_type,
            alma_sigma=alma_sigma
        )

    # 3. 收集用于聚类的RSI数据（限制最大数据点，过滤空值）
    rsi_values = rsi.tail(max_data_points).dropna().values
    # 数据不足3个时，无法聚类，直接返回0（过滤）
    if len(rsi_values) < 3:
        candle_df[factor_name] = 0
        return candle_df

    # 4. K-means聚类计算阈值（3个质心，对应下跌/中性/上涨）
    centroids = kmeans_clustering(
        data=rsi_values,
        n_clusters=3,
        max_iter=max_clustering_steps
    )
    short_s = np.min(centroids)  # 下跌状态阈值（红线阈值）

    # 5. 生成过滤信号（关键：转为1/0整数，适配框架val:==1规则）
    # 1表示保留（RSI >= 下跌阈值，非下跌状态），0表示过滤（下跌状态）
    candle_df[factor_name] = (rsi >= short_s).astype(int)

    return candle_df

# ------------------------------ 辅助函数：均线计算 ------------------------------
def ma(src, length, ma_type, alma_sigma):
    """
    实现多种移动平均线计算，用于平滑RSI
    :param src: 输入序列（RSI值，pandas.Series）
    :param length: 计算周期
    :param ma_type: 均线类型（SMA/Ema/Wma/ALMA）
    :param alma_sigma: ALMA的sigma参数
    :return: 平滑后的序列（pandas.Series）
    """
    src_series = pd.Series(src)

    if ma_type == 'SMA':
        # 简单移动平均线
        return src_series.rolling(window=length, min_periods=1).mean()

    elif ma_type == 'Ema':
        # 指数移动平均线
        return src_series.ewm(span=length, adjust=False, min_periods=1).mean()

    elif ma_type == 'Wma':
        # 加权移动平均线（权重1~length）
        weights = np.arange(1, length + 1)
        return src_series.rolling(window=length, min_periods=1).apply(
            lambda x: np.dot(x, weights) / weights.sum()
        )

    elif ma_type == 'ALMA':
        # 自适应均线（简化实现）
        m = (length - 1) / 2
        s = alma_sigma
        def alma_calc(window):
            if len(window) < length:
                return window.mean()  # 数据不足时用SMA替代
            weights = np.exp(-((np.arange(length) - m) **2) / (2 * s** 2))
            weights /= weights.sum()
            return np.dot(window, weights)
        return src_series.rolling(window=length, min_periods=1).apply(alma_calc)

    else:
        # 默认返回SMA（未实现的均线类型）
        return src_series.rolling(window=length, min_periods=1).mean()

# ------------------------------ 辅助函数：K-means聚类 ------------------------------
def kmeans_clustering(data, n_clusters=3, max_iter=1000):
    """
    K-means聚类算法，计算RSI的3个质心（下跌/中性/上涨阈值）
    :param data: RSI序列（numpy数组）
    :param n_clusters: 聚类数量（固定3）
    :param max_iter: 最大迭代次数
    :return: 排序后的质心（从小到大）
    """
    # 初始化质心（用25%/50%/75%分位数，避免随机偏差）
    centroids = np.percentile(data, [25, 50, 75])

    for _ in range(max_iter):
        # 计算每个点到质心的距离，分配聚类标签
        distances = np.abs(data[:, np.newaxis] - centroids)
        labels = np.argmin(distances, axis=1)

        # 计算新质心（每个聚类的均值）
        new_centroids = []
        for i in range(n_clusters):
            cluster_data = data[labels == i]
            new_centroid = cluster_data.mean() if len(cluster_data) > 0 else centroids[i]
            new_centroids.append(new_centroid)
        new_centroids = np.array(new_centroids)

        # 收敛判断（质心变化小于1e-3）
        if np.allclose(new_centroids, centroids, atol=1e-3):
            break
        centroids = new_centroids

    return np.sort(centroids)  # 按从小到大排序（下跌→中性→上涨）