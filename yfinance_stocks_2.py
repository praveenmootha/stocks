import yfinance as yf
from tabulate import tabulate
import os

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
    
    data = []
    for symbol in symbols:
        price = get_nse_price(symbol)
        if price:
            data.append([symbol, f"₹{price:.2f}"])
    
    # Generate HTML table
    rows = "\n".join(f"<tr><td>{sym}</td><td class=\"price\">{price}</td></tr>" for sym, price in data)
    html = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>NSE Stock Prices</title>
<style>
  body{{font-family:Arial,Helvetica,sans-serif;padding:18px}}
  table{{border-collapse:collapse;width:100%;max-width:800px}}
  th,td{{border:1px solid #ddd;padding:8px;text-align:left}}
  th{{background:#f4f4f4}}
  .price{{white-space:nowrap}}
</style>
</head>
<body>
  <h2>NSE Stock Prices</h2>
  <table>
    <thead><tr><th>Stock Symbol</th><th>Current Price (INR)</th></tr></thead>
    <tbody>
      {rows or '<tr><td colspan=\"2\">No data available</td></tr>'}
    </tbody>
  </table>
</body>
</html>"""
    
    out_path = os.path.join(os.path.dirname(__file__), "stocks.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    
    # Print path and HTML to stdout
    print(f"HTML written to: {out_path}")
    print(html)