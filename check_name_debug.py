from price_fetcher import PriceFetcher
import yfinance as yf

def check_00763u():
    fetcher = PriceFetcher()
    symbol = "00763U"
    yf_sym = fetcher._get_yf_symbol(symbol)
    print(f"Symbol: {symbol} -> YF Symbol: {yf_sym}")
    
    ticker = yf.Ticker(yf_sym)
    print(f"Short Name: {ticker.info.get('shortName')}")
    print(f"Long Name: {ticker.info.get('longName')}")
    
    # Also check without suffix just in case
    ticker2 = yf.Ticker("00763U")
    print(f"Raw 00763U Short Name: {ticker2.info.get('shortName')}")

if __name__ == "__main__":
    check_00763u()
