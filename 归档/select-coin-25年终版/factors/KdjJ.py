# from utils.diff import  eps
eps = 1e-9
def signal(*args):
    # J
    df = args[0]
    n = args[1]
    factor_name = args[2]

    low_list = df['low'].rolling(n, min_periods=1).min()  # MIN(LOW,N) 求周期内low的最小值
    high_list = df['high'].rolling(n, min_periods=1).max()  # MAX(HIGH,N) 求周期内high 的最大值
    # Stochastics=(CLOSE-LOW_N)/(HIGH_N-LOW_N)*100 计算一个随机值
    rsv = (df['close'] - low_list) / (high_list - low_list + eps) * 100
    # K D J的值在固定的范围内
    df['K'] = rsv.ewm(com=2).mean()  # K=SMA(Stochastics,3,1) 计算k
    df['D'] = df['K'].ewm(com=2).mean()  # D=SMA(K,3,1)  计算D
    df[factor_name] = 3 * df['K'] - 2 * df['D']  # 计算J
    return df
