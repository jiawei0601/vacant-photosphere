from price_fetcher import PriceFetcher

def final_check():
    fetcher = PriceFetcher()
    test_cases = ["00763U", "00708L", "00738U", "2330", "6285", "6768"]
    for s in test_cases:
        yf_sym = fetcher._get_yf_symbol(s)
        print(f"Symbol: {s:8} -> YF Symbol: {yf_sym:12}")

if __name__ == "__main__":
    final_check()
