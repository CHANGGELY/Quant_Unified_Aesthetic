import pandas as pd
import numpy as np


def signal(*args):
    df = args[0]
    n = args[1]
    factor_name = args[2]

    df["diff"] = df["close"].diff()
    df["diff"].fillna(df["close"] - df["open"], inplace=True)
    df["up"] = np.where(df["diff"] >= 0, df["diff"], 0)
    df["down"] = np.where(df["diff"] < 0, df["diff"], 0)
    df["A"] = df["up"].rolling(n, min_periods=1).sum()
    df["B"] = df["down"].abs().rolling(n, min_periods=1).sum()
    df["UpRatio"] = df["A"] / (df["A"] + df["B"])

    df[factor_name] = df["UpRatio"]

    return df
