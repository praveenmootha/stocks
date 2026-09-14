import os
import yfinance as yf
from flask import Flask, make_response, request, jsonify
from datetime import datetime

app = Flask(__name__)

# File to store persistent ticker list
TICKERS_FILE = r'D:\flaskapp\data\nse_tickers.txt'
APACHE_HTML_FILE = r'C:\Apache24\htdocs\stocks.html'

def load_tickers():
    """Load tickers from file, or return defaults if file doesn't exist"""
    if os.path.exists(TICKERS_FILE):
        try:
            with open(TICKERS_FILE, 'r') as f:
                tickers = [line.strip() for line in f if line.strip()]
                return tickers if tickers else ['TCS', 'INFY', 'RELIANCE', 'HDFCBANK']
        except Exception as e:
            print(f"Error loading tickers: {e}")
    return ['TCS', 'INFY', 'RELIANCE', 'HDFCBANK']

def save_apache_copy(html):
    """Save the generated HTML to the Apache document root"""
    try:
        with open(APACHE_HTML_FILE, 'w', encoding='utf-8') as f:
            f.write(html)
    except Exception as e:
        print(f"Error saving Apache copy: {e}")

def save_current_apache_copy():
    """Generate current Flask HTML and save it to Apache root"""
    data = []
    for symbol in current_tickers:
        price = get_nse_price(symbol)
        if price:
            data.append([symbol, f"₹{price:.2f}"])
    html = build_stock_report_html(data, current_tickers)
    save_apache_copy(html)

def save_tickers(tickers):
    """Save tickers to file"""
    try:
        os.makedirs(os.path.dirname(TICKERS_FILE), exist_ok=True)
        with open(TICKERS_FILE, 'w') as f:
            for ticker in tickers:
                f.write(f"{ticker}\n")
    except Exception as e:
        print(f"Error saving tickers: {e}")

# Global list to store current tickers (loaded from file on startup)
current_tickers = load_tickers()

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
        data = stock.history(period='1d')
        if data.empty or 'Close' not in data.columns or data['Close'].empty:
            raise ValueError('No price data available')
        current_price = data['Close'].iloc[-1]
        return current_price
    except Exception as e:
        print(f"Error fetching price for {ticker_symbol}: {e}")
        return None
def validate_nse_ticker(ticker_symbol):
    """
    Validate if a ticker is a valid NSE stock
    
    Args:
        ticker_symbol (str): Stock symbol to validate
    
    Returns:
        bool: True if valid NSE ticker, False otherwise
    """
    nse_ticker = f"{ticker_symbol}.NS"
    try:
        stock = yf.Ticker(nse_ticker)
        data = stock.history(period='1d')
        return not data.empty and 'Close' in data.columns and not data['Close'].empty
    except Exception as e:
        print(f"Error validating ticker {ticker_symbol}: {e}")
        return False

def build_stock_report_html(data, current_symbols):
    rows = "\n".join(f"<tr><td>{sym}</td><td class=\"price\">{price}</td><td><button onclick=\"removeTicker('{sym}')\" style=\"background:#e74c3c;color:white;border:none;padding:4px 8px;border-radius:3px;cursor:pointer;\">Remove</button></td></tr>" for sym, price in data)
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>NSE Stock Prices</title>
<meta http-equiv="refresh" content="900">
<style>
  body{{font-family:Arial,Helvetica,sans-serif;padding:20px;background:#f5f7fa;color:#333}}
  h2{{color:#2c3e50;border-bottom:3px solid #3498db;padding-bottom:10px}}
  .management{{margin-bottom:20px;padding:15px;background:white;border-radius:6px;box-shadow:0 2px 8px rgba(0,0,0,0.1);}}
  .form-group{{margin-bottom:15px;}}
  label{{display:block;margin-bottom:5px;color:#34495e;font-weight:600;}}
  input[type=text]{{width:100%;max-width:300px;padding:8px;border:1px solid #bdc3c7;border-radius:4px;}}
  button{{margin-right:10px;padding:8px 16px;border:none;border-radius:4px;cursor:pointer;font-size:14px;}}
  .add-btn{{background:#27ae60;color:white;}}
  .add-btn:hover{{background:#229954;}}
  .remove-btn{{background:#e74c3c;color:white;}}
  .remove-btn:hover{{background:#c0392b;}}
  .status{{margin-top:10px;padding:8px;border-radius:4px;font-size:14px;}}
  .success{{background:#d4edda;color:#155724;border:1px solid #c3e6cb;}}
  .error{{background:#f8d7da;color:#721c24;border:1px solid #f5c6cb;}}
  table{{border-collapse:collapse;width:100%;max-width:800px;background:white;box-shadow:0 2px 8px rgba(0,0,0,0.1);border-radius:6px;overflow:hidden}}
  th{{background:#3498db;color:white;padding:12px;text-align:left;font-weight:bold}}
  td{{border-bottom:1px solid #ecf0f1;padding:12px;text-align:left}}
  tbody tr:hover{{background:#ecf0f1}}
  tbody tr:nth-child(odd){{background:#f9fbfc}}
  .price{{white-space:nowrap;color:#27ae60;font-weight:bold}}
  .timestamp{{color:#7f8c8d;font-size:0.9em;margin-top:15px}}
</style>
</head>
<body>
  <h2>NSE Stock Prices</h2>
  
  <div class="management">
    <h3>Manage Tickers</h3>
    <div class="form-group">
      <label for="addTicker">Add NSE Ticker:</label>
      <input type="text" id="addTicker" placeholder="Enter ticker symbol (e.g., TCS)" />
      <button class="add-btn" onclick="addTicker()">Add Ticker</button>
    </div>
    <div id="statusMessage"></div>
  </div>
  
  <table>
    <thead><tr><th>Stock Symbol</th><th>Current Price (INR)</th><th>Actions</th></tr></thead>
    <tbody>
      {rows or '<tr><td colspan="3">No data available</td></tr>'}
    </tbody>
  </table>
  <p class="timestamp">Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
  <p style="color:#7f8c8d;font-size:0.9em;">Auto-refreshes every 15 minutes</p>
  
  <script>
    async function addTicker() {{
      const ticker = document.getElementById('addTicker').value.trim().toUpperCase();
      if (!ticker) {{
        showStatus('Please enter a ticker symbol', 'error');
        return;
      }}
      
      showStatus('Validating ticker...', '');
      
      try {{
        const response = await fetch(`/add/${{ticker}}`);
        const result = await response.json();
        
        if (result.success) {{
          showStatus(`Successfully added ${{ticker}}`, 'success');
          document.getElementById('addTicker').value = '';
          setTimeout(() => location.reload(), 1000);
        }} else {{
          showStatus(result.message, 'error');
        }}
      }} catch (error) {{
        showStatus('Error adding ticker', 'error');
      }}
    }}
    
    async function removeTicker(ticker) {{
      if (!confirm(`Remove ${{ticker}} from the list?`)) return;
      
      try {{
        const response = await fetch(`/remove/${{ticker}}`);
        const result = await response.json();
        
        if (result.success) {{
          location.reload();
        }} else {{
          alert('Error removing ticker');
        }}
      }} catch (error) {{
        alert('Error removing ticker');
      }}
    }}
    
    function showStatus(message, type) {{
      const statusDiv = document.getElementById('statusMessage');
      statusDiv.innerHTML = `<div class="status ${{type}}">${{message}}</div>`;
    }}
    
    // Allow Enter key to add ticker
    document.getElementById('addTicker').addEventListener('keypress', function(e) {{
      if (e.key === 'Enter') {{
        addTicker();
      }}
    }});
  </script>
</body>
</html>"""

@app.route('/')
def stock_report():
    global current_tickers
    
    data = []
    for symbol in current_tickers:
        price = get_nse_price(symbol)
        if price:
            data.append([symbol, f"₹{price:.2f}"])

    html = build_stock_report_html(data, current_tickers)
    save_apache_copy(html)
    response = make_response(html)
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return response

@app.route('/add/<ticker>')
def add_ticker(ticker):
    global current_tickers
    
    ticker = ticker.upper()
    
    if ticker in current_tickers:
        return jsonify({'success': False, 'message': f'{ticker} is already in the list'})
    
    if not validate_nse_ticker(ticker):
        return jsonify({'success': False, 'message': f'{ticker} is not a valid NSE ticker'})
    
    current_tickers.append(ticker)
    save_tickers(current_tickers)
    save_current_apache_copy()
    return jsonify({'success': True, 'message': f'Added {ticker} to the list'})

@app.route('/remove/<ticker>')
def remove_ticker(ticker):
    global current_tickers
    
    ticker = ticker.upper()
    
    if ticker not in current_tickers:
        return jsonify({'success': False, 'message': f'{ticker} is not in the list'})
    
    current_tickers.remove(ticker)
    save_tickers(current_tickers)
    save_current_apache_copy()
    return jsonify({'success': True, 'message': f'Removed {ticker} from the list'})

if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=5000)
