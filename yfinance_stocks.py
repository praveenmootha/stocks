import yfinance as yf

# NSE tickers use .NS suffix
# Example: TCS.NS for Tata Consultancy Services

def get_nse_price(ticker_symbol):
    """
    Fetch current price for NSE ticker
    
    Args:
        ticker_symbol (str): Stock symbol (e.g., 'TCS', 'INFY', 'RELIANCE')
    
    Returns:
        float: Current stock price
    """
    # Add .NS suffix for NSE stocks
    nse_ticker = f"{ticker_symbol}.NS"
    
    try:
        stock = yf.Ticker(nse_ticker)
        current_price = stock.history(period='1d')['Close'].iloc[-1]
        return current_price
    except Exception as e:
        print(f"Error fetching price for {ticker_symbol}: {e}")
        return None

# Example usage
if __name__ == "__main__":
    symbols = ['TCS', 'INFY', 'RELIANCE', 'HDFCBANK']
    
    for symbol in symbols:
        price = get_nse_price(symbol)
        if price:
            print(f"{symbol}: ₹{price:.2f}")