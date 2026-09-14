import os
import json
import yfinance as yf
from flask import Flask, make_response, request, jsonify
from datetime import datetime

app = Flask(__name__)

# File to store persistent ticker list
TICKERS_FILE = r'D:\flaskapp\data\nse_tickers.txt'
TARGETS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'target_prices.json')
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
    global current_targets
    data = []
    for symbol in current_tickers:
        price = get_nse_price(symbol)
        if price:
            data.append([symbol, f"₹{price:.2f}"])
    html = build_stock_report_html(data, current_tickers, current_targets)
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

def load_targets():
    """Load target prices from file, return dictionary {ticker: target_price}"""
    if os.path.exists(TARGETS_FILE):
        try:
            with open(TARGETS_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading targets: {e}")
    return {}

def save_targets(targets):
    """Save target prices to file"""
    try:
        with open(TARGETS_FILE, 'w') as f:
            json.dump(targets, f, indent=2)
    except Exception as e:
        print(f"Error saving targets: {e}")

# Global list to store current tickers (loaded from file on startup)
current_tickers = load_tickers()

# Global dict to store target prices (loaded from file on startup)
current_targets = load_targets()

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


def get_nse_history(ticker_symbol, period='10d', interval='1d'):
    """Fetch recent NSE OHLC history for a ticker."""
    try:
        nse_ticker = f"{ticker_symbol}.NS"
        stock = yf.Ticker(nse_ticker)
        data = stock.history(period=period, interval=interval)
        if data.empty:
            return None
        return data
    except Exception as e:
        print(f"Error fetching history for {ticker_symbol}: {e}")
        return None


def match_candle_patterns(df):
    """Check recent candle patterns and return matches with a recommendation."""
    patterns = []
    recommendation = 'Hold / no clear signal'

    if df is None or len(df) < 2:
        return patterns, recommendation

    latest = df.iloc[-1]
    previous = df.iloc[-2]

    close = latest['Close']
    open_ = latest['Open']
    high = latest['High']
    low = latest['Low']
    prev_close = previous['Close']
    prev_open = previous['Open']

    if prev_close < prev_open and close > open_ and open_ < prev_close and close > prev_open:
        patterns.append('Bullish Engulfing')
        recommendation = 'Buy (bullish reversal)'
    elif prev_close > prev_open and close < open_ and open_ > prev_close and close < prev_open:
        patterns.append('Bearish Engulfing')
        recommendation = 'Sell (bearish reversal)'

    body = abs(close - open_)
    range_ = high - low if high != low else 1
    lower_shadow = min(open_, close) - low
    upper_shadow = high - max(open_, close)

    if body <= range_ * 0.3 and lower_shadow >= body * 2 and upper_shadow <= body:
        if close > open_:
            patterns.append('Hammer')
            recommendation = 'Buy (bullish reversal)'
        else:
            patterns.append('Hanging Man')
            recommendation = 'Caution (possible bearish reversal)'
    elif body <= range_ * 0.3 and upper_shadow >= body * 2 and lower_shadow <= body:
        patterns.append('Shooting Star')
        recommendation = 'Sell (bearish reversal)'

    if abs(close - open_) <= range_ * 0.1:
        patterns.append('Doji')
        if recommendation == 'Hold / no clear signal':
            recommendation = 'Wait for confirmation (indecision)'

    return patterns, recommendation


def score_pattern(pattern_name):
    bullish = {'Bullish Engulfing', 'Hammer'}
    bearish = {'Bearish Engulfing', 'Shooting Star', 'Hanging Man'}
    if pattern_name in bullish:
        return 1
    if pattern_name in bearish:
        return -1
    return 0


def detect_pair_pattern(previous, latest):
    df = previous.to_frame().T.append(latest.to_frame().T)
    return match_candle_patterns(df)


def scan_pattern_series(df):
    patterns = []
    if df is None or len(df) < 2:
        return patterns
    for i in range(1, len(df)):
        pair = df.iloc[i-1:i+1]
        pair_patterns, _ = match_candle_patterns(pair)
        patterns.extend(pair_patterns)
    return patterns


def forecast_from_history(df):
    patterns = scan_pattern_series(df)
    score = sum(score_pattern(p) for p in patterns)
    if score > 1:
        return 'Bullish next candle likely', patterns
    if score < -1:
        return 'Bearish next candle likely', patterns
    return 'Hold / wait for confirmation', patterns


def current_day_recommendation(df):
    if df is None or df.empty:
        return 'No current day data available'

    latest = df.iloc[-1]
    if latest['Close'] > latest['Open']:
        return 'Bullish current day candle — positive close'
    if latest['Close'] < latest['Open']:
        return 'Bearish current day candle — negative close'
    return 'Indecisive current day candle (Doji-like)'


def build_forecast_page_html(ticker='', week_patterns=None, month_patterns=None, week_recommendation='', month_recommendation='', current_recommendation='', next_recommendation='', error=''):
    week_html = ''
    month_html = ''
    if week_patterns is not None:
        week_html = '<ul>' + ''.join(f'<li>{pattern}</li>' for pattern in week_patterns) + '</ul>' if week_patterns else '<p>No clear weekly patterns detected.</p>'
    if month_patterns is not None:
        month_html = '<ul>' + ''.join(f'<li>{pattern}</li>' for pattern in month_patterns) + '</ul>' if month_patterns else '<p>No clear monthly patterns detected.</p>'

    error_html = f'<p style="color:#e74c3c;font-weight:bold;">{error}</p>' if error else ''

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>NSE Candle Forecast</title>
<style>
  body{{font-family:Arial,Helvetica,sans-serif;padding:20px;background:#f5f7fa;color:#333}}
  h2{{color:#2c3e50;border-bottom:3px solid #3498db;padding-bottom:10px}}
  .container{{max-width:760px;background:white;padding:20px;border-radius:8px;box-shadow:0 2px 10px rgba(0,0,0,0.08);}}
  label{{display:block;margin-bottom:8px;color:#34495e;font-weight:600;}}
  input[type=text]{{width:100%;max-width:320px;padding:10px;border:1px solid #bdc3c7;border-radius:4px;}}
  button{{margin-top:10px;padding:10px 18px;background:#3498db;color:white;border:none;border-radius:4px;cursor:pointer;}}
  button:hover{{background:#2980b9;}}
  .result{{margin-top:20px;padding:15px;border-radius:6px;border:1px solid #dfe6e9;background:#f8f9fa;}}
  .section{{margin-top:20px;}}
  .section h4{{margin-bottom:8px;}}
  .recommendation{{font-weight:700;color:#2c3e50;}}
  .nav{{margin-bottom:20px;}}
  .nav a{{color:#3498db;text-decoration:none;margin-right:16px;font-weight:600;}}
</style>
</head>
<body>
  <div class="container">
    <div class="nav"><a href="/">Back to stock list</a><a href="/patterns">Candle Pattern Analysis</a><a href="/forecast">Weekly/Monthly Forecast</a></div>
    <h2>NSE Weekly / Monthly Candle Forecast</h2>
    <form method="get" action="/forecast">
      <label for="ticker">Enter NSE ticker symbol:</label>
      <input id="ticker" name="ticker" type="text" placeholder="TCS" value="{ticker}" required />
      <button type="submit">Analyze</button>
    </form>
    {error_html}
    <div class="result">
      <h3>Current day recommendation</h3>
      <p class="recommendation">{current_recommendation or 'Enter a ticker to get a forecast.'}</p>
    </div>
    <div class="result">
      <h3>Next candle recommendation</h3>
      <p class="recommendation">{next_recommendation or 'Enter a ticker to get a forecast.'}</p>
    </div>
    <div class="section">
      <h4>Last 1 week patterns</h4>
      {week_html}
      <p><strong>Weekly signal:</strong> {week_recommendation}</p>
    </div>
    <div class="section">
      <h4>Last 1 month patterns</h4>
      {month_html}
      <p><strong>Monthly signal:</strong> {month_recommendation}</p>
    </div>
  </div>
</body>
</html>"""


def build_pattern_page_html(ticker='', matches=None, recommendation='', error=''):
    matches_html = ''
    if matches:
        matches_html = '<ul>' + ''.join(f'<li>{pattern}</li>' for pattern in matches) + '</ul>'
    elif ticker and not error:
        matches_html = '<p>No clear candle pattern detected in the latest data.</p>'

    error_html = f'<p style="color:#e74c3c;font-weight:bold;">{error}</p>' if error else ''

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>NSE Candle Pattern Analysis</title>
<style>
  body{{font-family:Arial,Helvetica,sans-serif;padding:20px;background:#f5f7fa;color:#333}}
  h2{{color:#2c3e50;border-bottom:3px solid #3498db;padding-bottom:10px}}
  .container{{max-width:760px;background:white;padding:20px;border-radius:8px;box-shadow:0 2px 10px rgba(0,0,0,0.08);}}
  label{{display:block;margin-bottom:8px;color:#34495e;font-weight:600;}}
  input[type=text]{{width:100%;max-width:320px;padding:10px;border:1px solid #bdc3c7;border-radius:4px;}}
  button{{margin-top:10px;padding:10px 18px;background:#3498db;color:white;border:none;border-radius:4px;cursor:pointer;}}
  button:hover{{background:#2980b9;}}
  .result{{margin-top:20px;padding:15px;border-radius:6px;border:1px solid #dfe6e9;background:#f8f9fa;}}
  .recommendation{{font-weight:700;color:#2c3e50;}}
  .nav{{margin-bottom:20px;}}
  .nav a{{color:#3498db;text-decoration:none;margin-right:16px;font-weight:600;}}
</style>
</head>
<body>
  <div class="container">
    <div class="nav"><a href="/">Back to stock list</a><a href="/patterns">Candle Pattern Analysis</a><a href="/forecast">Weekly/Monthly Forecast</a></div>
    <h2>NSE Candle Pattern Analysis</h2>
    <form method="get" action="/patterns">
      <label for="ticker">Enter NSE ticker symbol:</label>
      <input id="ticker" name="ticker" type="text" placeholder="TCS" value="{ticker}" required />
      <button type="submit">Analyze</button>
    </form>
    {error_html}
    <div class="result">
      <h3>Recommendation</h3>
      <p class="recommendation">{recommendation or 'Enter a ticker to get a recommendation.'}</p>
      {matches_html}
    </div>
  </div>
</body>
</html>"""


def build_stock_report_html(data, current_symbols, target_prices=None):
    if target_prices is None:
        target_prices = {}
    
    def get_below_30_indicator(current_price_str, target_price):
        if not target_price:
            return ""
        try:
            current_price = float(current_price_str.replace("₹", "").replace(",", ""))
            target = float(target_price)
            percentage = (target / current_price) * 100
            if percentage < 30:
                return f'<span class="below-30" title="{percentage:.1f}% of current price">⚠️ {percentage:.1f}%</span>'
            return ""
        except (ValueError, ZeroDivisionError):
            return ""
    
    rows = "\n".join(f"<tr><td>{sym}</td><td class=\"price\">{price}</td><td><input type=\"number\" class=\"target-price\" data-ticker=\"{sym}\" step=\"0.01\" placeholder=\"Enter target\" value=\"{target_prices.get(sym, '')}\" onchange=\"saveTarget('{sym}', this.value)\" /></td><td>{get_below_30_indicator(price, target_prices.get(sym, ''))}</td><td><button onclick=\"removeTicker('{sym}')\" style=\"background:#e74c3c;color:white;border:none;padding:4px 8px;border-radius:3px;cursor:pointer;\">Remove</button></td></tr>" for sym, price in data)
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
  input[type=number]{{padding:8px;border:1px solid #bdc3c7;border-radius:4px;font-size:14px;}}
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
  .target-price{{width:100%;max-width:150px;padding:8px;border:1px solid #bdc3c7;border-radius:3px;font-size:14px;box-sizing:border-box;}}
  .target-price:focus{{outline:none;border-color:#3498db;box-shadow:0 0 5px rgba(52,152,219,0.3);}}
  .below-30{{color:#e74c3c;font-weight:bold;background:#ffeaea;padding:4px 8px;border-radius:3px;border:1px solid #f5c6cb;}}
  .timestamp{{color:#7f8c8d;font-size:0.9em;margin-top:15px}}
</style>
</head>
<body>
  <h2>NSE Stock Prices</h2>
  <div class="nav" style="margin-bottom:15px;">
    <a href="/patterns" style="color:#3498db;text-decoration:none;font-weight:600;">Analyze candle patterns</a>
  </div>
  
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
    <thead><tr><th>Stock Symbol</th><th>Current Price (INR)</th><th>Target Price (INR)</th><th>Below 30%</th><th>Actions</th></tr></thead>
    <tbody>
      {rows or '<tr><td colspan="5">No data available</td></tr>'}
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
    
    async function saveTarget(ticker, value) {{
      try {{
        const response = await fetch(`/set-target/${{ticker}}`, {{
          method: 'POST',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{target: value}})
        }});
        const result = await response.json();
        console.log(result.message);
      }} catch (error) {{
        console.error('Error saving target price:', error);
      }}
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

@app.route('/patterns')
def candle_patterns():
    ticker = request.args.get('ticker', '').strip().upper()
    if not ticker:
        html = build_pattern_page_html()
        response = make_response(html)
        response.headers['Content-Type'] = 'text/html; charset=utf-8'
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        return response

    if not validate_nse_ticker(ticker):
        html = build_pattern_page_html(ticker=ticker, error=f"{ticker} is not a valid NSE ticker")
        response = make_response(html)
        response.headers['Content-Type'] = 'text/html; charset=utf-8'
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        return response

    df = get_nse_history(ticker)
    if df is None:
        html = build_pattern_page_html(ticker=ticker, error=f"Could not load history for {ticker}")
        response = make_response(html)
        response.headers['Content-Type'] = 'text/html; charset=utf-8'
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        return response

    matches, recommendation = match_candle_patterns(df)
    html = build_pattern_page_html(ticker=ticker, matches=matches, recommendation=recommendation)
    response = make_response(html)
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return response

@app.route('/forecast')
def candle_forecast():
    ticker = request.args.get('ticker', '').strip().upper()
    if not ticker:
        html = build_forecast_page_html()
        response = make_response(html)
        response.headers['Content-Type'] = 'text/html; charset=utf-8'
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        return response

    if not validate_nse_ticker(ticker):
        html = build_forecast_page_html(ticker=ticker, error=f"{ticker} is not a valid NSE ticker")
        response = make_response(html)
        response.headers['Content-Type'] = 'text/html; charset=utf-8'
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        return response

    week_df = get_nse_history(ticker, period='7d')
    month_df = get_nse_history(ticker, period='1mo')

    if week_df is None or month_df is None:
        html = build_forecast_page_html(ticker=ticker, error=f"Could not load history for {ticker}")
        response = make_response(html)
        response.headers['Content-Type'] = 'text/html; charset=utf-8'
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        return response

    current_recommendation = current_day_recommendation(week_df)
    week_recommendation, week_patterns = forecast_from_history(week_df)
    month_recommendation, month_patterns = forecast_from_history(month_df)
    next_recommendation = 'Bullish next candle likely' if week_recommendation.startswith('Bullish') and month_recommendation.startswith('Bullish') else \
        'Bearish next candle likely' if week_recommendation.startswith('Bearish') and month_recommendation.startswith('Bearish') else \
        'Mixed signals — wait for confirmation'

    html = build_forecast_page_html(
        ticker=ticker,
        week_patterns=week_patterns,
        month_patterns=month_patterns,
        week_recommendation=week_recommendation,
        month_recommendation=month_recommendation,
        current_recommendation=current_recommendation,
        next_recommendation=next_recommendation
    )
    response = make_response(html)
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return response

@app.route('/')
def stock_report():
    global current_tickers, current_targets
    
    data = []
    for symbol in current_tickers:
        price = get_nse_price(symbol)
        if price:
            data.append([symbol, f"₹{price:.2f}"])

    html = build_stock_report_html(data, current_tickers, current_targets)
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
    global current_tickers, current_targets
    
    ticker = ticker.upper()
    
    if ticker not in current_tickers:
        return jsonify({'success': False, 'message': f'{ticker} is not in the list'})
    
    current_tickers.remove(ticker)
    save_tickers(current_tickers)
    
    # Also remove target price for this ticker
    if ticker in current_targets:
        del current_targets[ticker]
        save_targets(current_targets)
    
    save_current_apache_copy()
    return jsonify({'success': True, 'message': f'Removed {ticker} from the list'})

@app.route('/set-target/<ticker>', methods=['POST'])
def set_target(ticker):
    global current_targets
    
    ticker = ticker.upper()
    
    try:
        data = request.get_json()
        target = float(data.get('target', 0)) if data else 0
    except (ValueError, TypeError):
        target = 0
    
    if target is None or target <= 0:
        if ticker in current_targets:
            del current_targets[ticker]
    else:
        current_targets[ticker] = target
    
    save_targets(current_targets)
    return jsonify({'success': True, 'message': f'Target price for {ticker} set to ₹{target}'})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)
