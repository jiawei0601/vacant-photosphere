from price_fetcher import PriceFetcher

def test_name():
    fetcher = PriceFetcher()
    for s in ["2330", "AAPL", "0050"]:
        name = fetcher.get_stock_name(s)
        print(f"Symbol: {s:8} -> Name: {name}")

if __name__ == "__main__":
    test_name()
