import backtrader as bt
import pandas as pd
import numpy as np
import time


# =========================
# 1) 毎バー必ず注文/決済する戦略
# =========================
class EveryBarTradeStrategy(bt.Strategy):
    params = dict(
        size=1,
    )

    def __init__(self):
        self.bar_index = 0

    def next(self):
        # 毎バー呼ばれる
        self.bar_index += 1

        # ポジションがなければ成行で買い
        if not self.position:
            self.buy(size=self.p.size)
        else:
            # ポジションがあれば必ずクローズ
            self.close()

        # もし「本当に毎バー新規＋決済」をやりたいなら、
        # 下のように「同一バー中に買ってすぐ売る」パターンも試せる。
        # ただし実際の約定ロジック次第では同一バー内fillの扱いが変わる点に注意。
        # self.buy(size=self.p.size)
        # self.sell(size=self.p.size)


# =========================
# 2) ダミーOHLCを1万ステップ生成
# =========================
def make_dummy_ohlc(n=10000):
    np.random.seed(0)
    rets = np.random.normal(loc=0, scale=0.001, size=n)
    price = 100 + np.cumsum(rets)

    idx = pd.date_range("2020-01-01", periods=n, freq="T")

    df = pd.DataFrame(index=idx)
    df["open"] = price
    df["high"] = df["open"] + np.random.uniform(0, 0.1, size=n)
    df["low"] = df["open"] - np.random.uniform(0, 0.1, size=n)
    df["close"] = df["open"] + np.random.uniform(-0.05, 0.05, size=n)
    df["volume"] = np.random.randint(100, 1000, size=n)
    df["openinterest"] = 0
    return df


if __name__ == "__main__":
    # 1万ステップ分のダミーデータ
    df = make_dummy_ohlc(10000)
    data = bt.feeds.PandasData(dataname=df)

    cerebro = bt.Cerebro()
    cerebro.adddata(data)
    cerebro.addstrategy(EveryBarTradeStrategy)
    cerebro.broker.setcash(100000.0)

    # 実行時間を計測（バックテスト区間のみ）
    t0 = time.time()
    cerebro.run()
    t1 = time.time()

    print(f"Backtrader 10000 step (every-bar trade) time: {t1 - t0:.3f} sec")
    print(f"Final portfolio value: {cerebro.broker.getvalue():.2f}")
