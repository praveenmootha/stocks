import os
import json
import contextlib
import time
import yfinance as yf
# removed direct NSE scraping (requests/BeautifulSoup) per user request
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, make_response, request, jsonify
from datetime import datetime, timedelta
import calendar

app = Flask(__name__)

# File to store persistent ticker list
TICKERS_FILE = os.environ.get('STOCKS_TICKERS_FILE', r'D:\flaskapp\data\nse_tickers.txt')
TARGETS_FILE = os.environ.get('STOCKS_TARGETS_FILE', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'target_prices.json'))
APACHE_HTML_FILE = os.environ.get('STOCKS_APACHE_HTML_FILE', r'C:\Apache24\htdocs\stocks.html')
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pattern_stocks.log')
DEBUG = True if os.environ.get('STOCKS_DEBUG', '') == '' else os.environ.get('STOCKS_DEBUG', '').lower() in ('1', 'true', 'yes')


def log_message(message):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass


def ensure_dir(path):
    try:
        if path:
            os.makedirs(path, exist_ok=True)
    except Exception as e:
        print(f"Error creating directory {path}: {e}")
        log_message(f"Error creating directory {path}: {e}")


def ensure_output_paths():
    ensure_dir(os.path.dirname(TICKERS_FILE))
    ensure_dir(os.path.dirname(TARGETS_FILE))
    ensure_dir(os.path.dirname(APACHE_HTML_FILE))


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
        ensure_dir(os.path.dirname(APACHE_HTML_FILE))
        with open(APACHE_HTML_FILE, 'w', encoding='utf-8') as f:
            f.write(html)
    except Exception as e:
        print(f"Error saving Apache copy: {e}")
        log_message(f"Error saving Apache copy: {e}")

def save_current_apache_copy():
    """Generate current Flask HTML and save it to Apache root"""
    global current_tickers, current_targets
    data, fifty_two_week_highs, fifty_two_week_lows = get_stock_report_data(current_tickers)
    nse_movers = fetch_nse_top_movers(10)
    html = build_stock_report_html(data, current_tickers, current_targets, fifty_two_week_highs, None, nse_movers, {}, fifty_two_week_lows, get_nse_index_data())
    save_apache_copy(html)

def save_tickers(tickers):
    """Save tickers to file"""
    try:
        ensure_dir(os.path.dirname(TICKERS_FILE))
        with open(TICKERS_FILE, 'w') as f:
            for ticker in tickers:
                f.write(f"{ticker}\n")
    except Exception as e:
        print(f"Error saving tickers: {e}")
        log_message(f"Error saving tickers: {e}")

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
        ensure_dir(os.path.dirname(TARGETS_FILE))
        with open(TARGETS_FILE, 'w') as f:
            json.dump(targets, f, indent=2)
    except Exception as e:
        print(f"Error saving targets: {e}")
        log_message(f"Error saving targets: {e}")

# Global list to store current tickers (loaded from file on startup)
current_tickers = load_tickers()

# Global dict to store target prices (loaded from file on startup)
current_targets = load_targets()

NSE_MOVER_UNIVERSE = [
    'RELIANCE', 'TCS', 'HDFCBANK', 'HDFC', 'INFY', 'ICICIBANK', 'KOTAKBANK',
    'LT', 'SBIN', 'ITC', 'AXISBANK', 'HINDUNILVR', 'BAJFINANCE', 'BHARTIARTL',
    'ASIANPAINT', 'SUNPHARMA', 'MARUTI', 'TITAN', 'JSWSTEEL', 'TECHM',
    'HCLTECH', 'NTPC', 'POWERGRID', 'ULTRACEMCO', 'GRASIM', 'TATAMOTORS',
    'EICHERMOT', 'M&M', 'DIVISLAB', 'BPCL', 'COALINDIA', 'ONGC', 'BRITANNIA',
    'NESTLEIND', 'CIPLA', 'HINDALCO', 'VEDL', 'ADANIENT', 'ADANIPORTS',
    'TATASTEEL', 'INDUSINDBK', 'UPL', 'SBILIFE', 'DMART', 'ABB', 'BOSCHLTD',
    'SIEMENS', 'HAVELLS', 'HEROMOTOCO', 'DRREDDY'
]

NSE_INDEX_SYMBOLS = {
    'NIFTY 50': '^NSEI',
    'NIFTY Midcap 50': '^NSEMDCP50',
    'NIFTY Bank': '^NSEBANK',
    'NIFTY Pharma': '^CNXPHARMA'
}

FUTURES_PRICE_CACHE = {}
FUTURES_CACHE_TTL_SECONDS = 300

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
        data = stock.history(period='1d', timeout=10)
        if data.empty or 'Close' not in data.columns or data['Close'].empty:
            if DEBUG:
                print(f"No price data found for {ticker_symbol}")
            return None
        current_price = data['Close'].iloc[-1]
        return current_price
    except Exception as e:
        if DEBUG:
            print(f"Error fetching price for {ticker_symbol}: {e}")
        return None

def get_nse_index_data():
    """Return latest value and daily change for selected NSE indexes."""
    indexes = []
    for name, symbol in NSE_INDEX_SYMBOLS.items():
        try:
            data = yf.Ticker(symbol).history(period='5d', interval='1d', timeout=10)
            if data.empty or 'Close' not in data.columns or len(data['Close']) < 1:
                continue
            close = data['Close'].dropna()
            if close.empty:
                continue
            current = float(close.iloc[-1])
            change = ((current - float(close.iloc[-2])) / float(close.iloc[-2]) * 100) if len(close) > 1 and close.iloc[-2] else 0.0
            indexes.append((name, current, change))
        except Exception as e:
            if DEBUG:
                print(f"Error fetching index {name}: {e}")
    return indexes

def get_52_week_high(ticker_symbol):
    """
    Fetch 52-week high for NSE ticker
    
    Args:
        ticker_symbol (str): Stock symbol (e.g., 'TCS', 'INFY', 'RELIANCE')
    
    Returns:
        float: 52-week high stock price
    """
    # Add .NS suffix for NSE stocks
    nse_ticker = f"{ticker_symbol}.NS"
    
    try:
        stock = yf.Ticker(nse_ticker)
        data = stock.history(period='1y', timeout=10)
        if data.empty or 'High' not in data.columns or data['High'].empty:
            if DEBUG:
                print(f"No 52-week high data found for {ticker_symbol}")
            return None
        high_52w = data['High'].max()
        return high_52w
    except Exception as e:
        if DEBUG:
            print(f"Error fetching 52-week high for {ticker_symbol}: {e}")
        return None

def get_52_week_low(ticker_symbol):
    """Fetch 52-week low for an NSE stock."""
    nse_ticker = f"{ticker_symbol}.NS"
    try:
        stock = yf.Ticker(nse_ticker)
        data = stock.history(period='1y', timeout=10)
        if data.empty or 'Low' not in data.columns or data['Low'].empty:
            return None
        return data['Low'].min()
    except Exception as e:
        if DEBUG:
            print(f"Error fetching 52-week low for {ticker_symbol}: {e}")
        return None


def get_stock_report_data(symbols):
    """Fetch the independent price and 52-week values concurrently."""
    def fetch_symbol_data(symbol):
        price = get_nse_price(symbol)
        high = get_52_week_high(symbol) if price else None
        low = get_52_week_low(symbol) if price else None
        return symbol, price, high, low

    data = []
    fifty_two_week_highs = {}
    fifty_two_week_lows = {}
    worker_count = min(8, max(1, len(symbols)))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        results = executor.map(fetch_symbol_data, symbols)
        for symbol, price, high_52w, low_52w in results:
            if price:
                data.append([symbol, f"₹{price:.2f}"])
                if high_52w:
                    fifty_two_week_highs[symbol] = high_52w
                if low_52w:
                    fifty_two_week_lows[symbol] = low_52w

    return data, fifty_two_week_highs, fifty_two_week_lows


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
        with open(os.devnull, 'w') as devnull:
            with contextlib.redirect_stderr(devnull):
                data = stock.history(period='1d')
        valid = not data.empty and 'Close' in data.columns and not data['Close'].empty
        if DEBUG and not valid:
            print(f"Ticker validation failed for {ticker_symbol}: no price data")
        return valid
    except Exception as e:
        if DEBUG:
            print(f"Error validating ticker {ticker_symbol}: {e}")
        return False


def get_futures_expiry_code(months_ahead=0):
    """
    Get NSE futures expiry code (e.g., 'JAN24', 'FEB24') using real calendar months.

    Args:
        months_ahead (int): 0 for current month, 1 for next month, etc.

    Returns:
        str: Expiry code in format 'MMMYY'
    """
    months = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
    today = datetime.now()
    month_index = (today.month - 1 + months_ahead) % 12
    year_offset = (today.month - 1 + months_ahead) // 12
    target_year = today.year + year_offset
    month_name = months[month_index]
    year_code = str(target_year % 100).zfill(2)
    return f"{month_name}{year_code}"


def get_futures_expiry_date(months_ahead=0):
    """Return the last Tuesday of the contract month for the chosen expiry cycle."""
    today = datetime.now()
    month_index = today.month - 1 + months_ahead
    year = today.year + (month_index // 12)
    month = (month_index % 12) + 1
    last_day = calendar.monthrange(year, month)[1]
    expiry_date = datetime(year, month, last_day)
    while expiry_date.weekday() != 1:  # Tuesday = 1
        expiry_date -= timedelta(days=1)
    return expiry_date.date()


def format_futures_contract_label(ticker_symbol, expiry_code='CURRENT'):
    """Format a contract label like 'INFY 25 Aug FUT' from an expiry code."""
    ticker_symbol = (ticker_symbol or '').strip().upper()
    if not ticker_symbol:
        return ''

    if isinstance(expiry_code, str):
        expiry_code = expiry_code.strip().upper()
    if expiry_code in (None, '', 'CURRENT'):
        expiry_code = get_futures_expiry_code(0)

    months = {
        'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
        'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12
    }

    match = expiry_code[:3].upper() if len(expiry_code) >= 3 else expiry_code.upper()
    month = months.get(match)
    if month is None:
        return f"{ticker_symbol} {expiry_code} FUT"

    year = 2000 + int(expiry_code[-2:]) if len(expiry_code) >= 2 and expiry_code[-2:].isdigit() else datetime.now().year
    if month == 12 and year < datetime.now().year:
        year += 1

    month_index = (year - datetime.now().year) * 12 + (month - datetime.now().month)
    date_obj = get_futures_expiry_date(month_index)
    return f"{ticker_symbol} {date_obj.day:02d} {date_obj.strftime('%b')} FUT"


def get_futures_ticker_variants(ticker_symbol, expiry_code='CURRENT'):
    """Return a few valid NSE futures ticker patterns to try for a symbol and expiry."""
    ticker_symbol = (ticker_symbol or '').strip().upper()
    if not ticker_symbol:
        return []

    if isinstance(expiry_code, str):
        expiry_code = expiry_code.strip().upper()
    if expiry_code in ('', 'CURRENT'):
        expiry_code = get_futures_expiry_code(0)
    elif expiry_code == 'NEXT':
        expiry_code = get_futures_expiry_code(1)

    code = expiry_code.replace(' ', '')
    month_token = code[:3]
    year_token = code[-2:]
    month = month_token if month_token.isalpha() else ''
    year = year_token if year_token.isdigit() else ''

    variants = []
    if month and year:
        variants.extend([
            f"{ticker_symbol}{month}{year}.NS",
            f"{ticker_symbol}{year}{month}.NS",
            f"{ticker_symbol}{month}{year}FUT.NS",
            f"{ticker_symbol}{year}{month}FUT.NS",
            f"{ticker_symbol}{month}{year}FUT.NS",
        ])

    variants.append(f"{ticker_symbol}{code}.NS")
    variants.append(f"{ticker_symbol}{code}FUT.NS")
    seen = set()
    ordered = []
    for variant in variants:
        v = variant.upper()
        if v not in seen:
            seen.add(v)
            ordered.append(v)
    return ordered


def get_nse_futures_price(ticker_symbol, expiry_code='CURRENT'):
    """
    Fetch current price for NSE futures
    
    Args:
        ticker_symbol (str): Stock symbol (e.g., 'TCS', 'INFY')
        expiry_code (str): Expiry code like 'JAN24' or 'CURRENT' for current month
    
    Returns:
        float: Current futures price, None if not found
    """
    symbol = (ticker_symbol or '').strip().upper()
    normalised_expiry = 'CURRENT' if expiry_code in (None, '', 'CURRENT') else str(expiry_code).strip().upper()
    cache_key = (symbol, normalised_expiry)
    now_ts = time.time()
    cached = FUTURES_PRICE_CACHE.get(cache_key)
    if cached and (now_ts - cached.get('timestamp', 0)) < FUTURES_CACHE_TTL_SECONDS:
        if cached.get('price') is not None:
            return cached['price']
        return None

    try:
        for futures_ticker in get_futures_ticker_variants(symbol, normalised_expiry):
            time.sleep(0.15)
            stock = yf.Ticker(futures_ticker)
            with open(os.devnull, 'w') as devnull:
                with contextlib.redirect_stderr(devnull):
                        data = stock.history(period='1d', timeout=10)
            if not data.empty and 'Close' in data.columns and not data['Close'].empty:
                current_price = float(data['Close'].iloc[-1])
                FUTURES_PRICE_CACHE[cache_key] = {'price': current_price, 'timestamp': time.time()}
                return current_price
        if DEBUG:
            print(f"No futures price data found for {symbol} {normalised_expiry}")
        FUTURES_PRICE_CACHE[cache_key] = {'price': None, 'timestamp': time.time()}
        return None
    except Exception as e:
        if DEBUG:
            print(f"Error fetching futures price for {symbol}: {e}")
        FUTURES_PRICE_CACHE[cache_key] = {'price': None, 'timestamp': time.time()}
        return None


def get_nse_futures_52_week_high(ticker_symbol, expiry_code='CURRENT'):
    """
    Fetch 52-week high for NSE futures
    
    Args:
        ticker_symbol (str): Stock symbol
        expiry_code (str): Expiry code
    
    Returns:
        float: 52-week high futures price
    """
    try:
        for futures_ticker in get_futures_ticker_variants(ticker_symbol, expiry_code):
            stock = yf.Ticker(futures_ticker)
            with open(os.devnull, 'w') as devnull:
                with contextlib.redirect_stderr(devnull):
                    data = stock.history(period='1y')
            if not data.empty and 'High' in data.columns and not data['High'].empty:
                high_52w = data['High'].max()
                return high_52w
        if DEBUG:
            print(f"No 52-week high data found for futures {ticker_symbol}")
        return None
    except Exception as e:
        if DEBUG:
            print(f"Error fetching futures 52-week high for {ticker_symbol}: {e}")
        return None


def validate_nse_futures_ticker(ticker_symbol, expiry_code='CURRENT'):
    """
    Validate if a futures ticker is valid
    
    Args:
        ticker_symbol (str): Stock symbol to validate
        expiry_code (str): Expiry code
    
    Returns:
        bool: True if valid NSE futures ticker
    """
    try:
        for futures_ticker in get_futures_ticker_variants(ticker_symbol, expiry_code):
            stock = yf.Ticker(futures_ticker)
            with open(os.devnull, 'w') as devnull:
                with contextlib.redirect_stderr(devnull):
                    data = stock.history(period='1d')
            if not data.empty and 'Close' in data.columns and not data['Close'].empty:
                return True
        if DEBUG:
            print(f"Futures ticker validation failed for {ticker_symbol}")
        return False
    except Exception as e:
        if DEBUG:
            print(f"Error validating futures ticker {ticker_symbol}: {e}")
        return False


def compute_daily_movers(symbols, top_n=10):
    """Compute percent change from previous close to latest close for given symbols.

    Returns dict with 'gainers' and 'losers' lists of tuples (symbol, pct_change, latest_price).
    """
    movers = []
    for sym in symbols:
        try:
            nse_ticker = f"{sym}.NS"
            stock = yf.Ticker(nse_ticker)
            with open(os.devnull, 'w') as devnull:
                with contextlib.redirect_stderr(devnull):
                        data = stock.history(period='2d', timeout=10)
            if data.empty or 'Close' not in data.columns or len(data['Close']) < 2:
                continue
            prev = float(data['Close'].iloc[-2])
            curr = float(data['Close'].iloc[-1])
            pct = ((curr - prev) / prev) * 100 if prev else 0.0
            movers.append((sym, pct, curr))
        except Exception as e:
            if DEBUG:
                print(f"Error computing mover for {sym}: {e}")
            continue

    gainers = sorted(movers, key=lambda x: x[1], reverse=True)[:top_n]
    losers = sorted(movers, key=lambda x: x[1])[:top_n]
    try:
        log_message(f"compute_daily_movers_all: processed {len(symbols)} symbols, movers found {len(movers)}")
        if movers:
            # log a small sample
            log_message(f"sample movers: {movers[:10]}")
    except Exception:
        pass
    return {'gainers': gainers, 'losers': losers}


def get_all_nse_tickers():
    """Return only the currently tracked ticker symbols."""
    return list(current_tickers)


def compute_daily_movers_all(symbols=None, top_n=10, chunk_size=200):
    """Compute movers across a large list of symbols using yfinance batch download.

    Returns dict with 'gainers' and 'losers'. Symbols should be without .NS suffix.
    """
    if symbols is None:
        symbols = get_all_nse_tickers()

    movers = []
    # iterate in chunks to avoid too-large requests
    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i:i+chunk_size]
        if not chunk:
            continue
        tickers_ns = [f"{s}.NS" for s in chunk]
        try:
            # Request enough calendar days to include two trading sessions.
            data = yf.download(tickers_ns, period='5d', group_by='ticker', threads=False, progress=False, timeout=10)
            if DEBUG:
                try:
                    print(f"Downloaded chunk {i}:{tickers_ns[:5]} -> columns sample: {list(data.columns)[:10]}")
                except Exception:
                    print(f"Downloaded chunk {i} (could not stringify columns)")
        except Exception as e:
            if DEBUG:
                print(f"yfinance batch download failed for chunk starting at {i}: {e}")
            # fallback: per-symbol
            for s in chunk:
                try:
                    df = yf.Ticker(f"{s}.NS").history(period='5d')
                    if df is None or df.empty or 'Close' not in df.columns or len(df['Close']) < 2:
                        continue
                    prev = float(df['Close'].iloc[-2])
                    curr = float(df['Close'].iloc[-1])
                    pct = ((curr - prev) / prev) * 100 if prev else 0.0
                    movers.append((s, pct, curr))
                except Exception:
                    continue
            continue

        # parse returned DataFrame
        # When multiple tickers, `data` has a MultiIndex columns like ('TCS.NS', 'Close')
        if isinstance(data.columns, pd.MultiIndex):
            if DEBUG:
                print(f"[DEBUG] MultiIndex detected. Level 0: {data.columns.get_level_values(0).unique().tolist()[:5]}, Level 1: {data.columns.get_level_values(1).unique().tolist()[:5]}")
            for s in chunk:
                key = f"{s}.NS"
                try:
                    # With MultiIndex columns (ticker, column), access via data[ticker][column]
                    if key in data.columns.get_level_values(0):
                        ticker_data = data[key]
                        if 'Close' in ticker_data.columns:
                                close_series = ticker_data['Close'].dropna()
                        elif 'Adj Close' in ticker_data.columns:
                            close_series = ticker_data['Adj Close'].dropna()
                        else:
                            continue
                    else:
                        if DEBUG:
                            print(f"[DEBUG] Ticker {key} not found in level 0")
                        continue
                    if close_series is None or len(close_series) < 2:
                        continue
                    prev = float(close_series.iloc[-2])
                    curr = float(close_series.iloc[-1])
                    pct = ((curr - prev) / prev) * 100 if prev else 0.0
                    movers.append((s, pct, curr))
                    if DEBUG and len(movers) <= 3:
                        print(f"[DEBUG] Added mover: {s} -> {pct:.2f}% (prev={prev:.2f}, curr={curr:.2f})")
                except Exception as e:
                    if DEBUG:
                        print(f"[DEBUG] Error processing {key}: {e}")
                    continue
        else:
            # single ticker in chunk or single-index columns
            for s in chunk:
                try:
                    # prefer 'Close' but accept 'Adj Close' when auto-adjusted
                    if isinstance(data, pd.DataFrame):
                        if 'Close' in data.columns and len(data['Close']) >= 2:
                            df = data
                        elif 'Adj Close' in data.columns and len(data['Adj Close']) >= 2:
                            df = data
                        else:
                            df = None
                    else:
                        df = None
                    if df is None:
                        # attempt per-symbol
                        df = yf.Ticker(f"{s}.NS").history(period='2d', timeout=10)
                    # handle 'Adj Close' fallback as well
                    if df is None or df.empty or (('Close' not in df.columns or len(df['Close']) < 2) and ('Adj Close' not in df.columns or len(df['Adj Close']) < 2)):
                        continue
                    if 'Close' in df.columns and len(df['Close']) >= 2:
                        prev = float(df['Close'].iloc[-2])
                        curr = float(df['Close'].iloc[-1])
                    else:
                        prev = float(df['Adj Close'].iloc[-2])
                        curr = float(df['Adj Close'].iloc[-1])
                    pct = ((curr - prev) / prev) * 100 if prev else 0.0
                    movers.append((s, pct, curr))
                except Exception:
                    continue

    # sort and pick top_n, filtering out NaN values
    valid_movers = [(s, pct, price) for s, pct, price in movers if not pd.isna(pct) and not pd.isna(price)]
    gainers = sorted(valid_movers, key=lambda x: x[1], reverse=True)[:top_n]
    losers = sorted(valid_movers, key=lambda x: x[1])[:top_n]
    if DEBUG:
        print(f"[DEBUG] Total movers found: {len(movers)}, valid: {len(valid_movers)}, gainers: {len(gainers)}, losers: {len(losers)}")
        print(f"[DEBUG] Gainers: {gainers}")
        print(f"[DEBUG] Losers: {losers}")
    return {'gainers': gainers, 'losers': losers}


def fetch_nse_top_movers(top_n=10):
    """Return top movers computed via yfinance across the NSE market universe.

    This function does NOT fetch data from nseindia.com; it uses `yfinance` only.
    """
    try:
        movers = compute_daily_movers_all(symbols=NSE_MOVER_UNIVERSE, top_n=top_n)
        return movers
    except Exception as e:
        if DEBUG:
            print(f"Error computing NSE movers via yfinance: {e}")
        return {'gainers': [], 'losers': []}


def get_nse_futures_history(ticker_symbol, expiry_code='CURRENT', period='10d', interval='1d'):
    """Fetch recent NSE futures OHLC history for candle patterns."""
    try:
        for futures_ticker in get_futures_ticker_variants(ticker_symbol, expiry_code):
            stock = yf.Ticker(futures_ticker)
            with open(os.devnull, 'w') as devnull:
                with contextlib.redirect_stderr(devnull):
                    data = stock.history(period=period, interval=interval)
            if not data.empty:
                return data
        return None
    except Exception as e:
        if DEBUG:
            print(f"Error fetching futures history for {ticker_symbol}: {e}")
        return None
    """Fetch recent NSE OHLC history for a ticker."""
    try:
        nse_ticker = f"{ticker_symbol}.NS"
        stock = yf.Ticker(nse_ticker)
        with open(os.devnull, 'w') as devnull:
            with contextlib.redirect_stderr(devnull):
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
    body{{font-family:Arial,Helvetica,sans-serif;padding:20px;background:#f5f7fa;color:#333;position:relative}}
    body.skin-ocean{{background:#eef7fb;color:#183642;}}
    body.skin-ocean h2{{color:#0b6174;border-color:#19a7a8;}}
    body.skin-ocean .management,body.skin-ocean table{{background:#ffffff;}}
    body.skin-ocean th{{background:#0b8793;}}
    body.skin-forest{{background:#f1f7f0;color:#263b2b;}}
    body.skin-forest h2{{color:#356b43;border-color:#6aa66f;}}
    body.skin-forest .management,body.skin-forest table{{background:#ffffff;}}
    body.skin-forest th{{background:#4d8757;}}
    body.skin-midnight{{background:#1f2933;color:#e7edf2;}}
    body.skin-midnight h2{{color:#b9e6ff;border-color:#4ca6c8;}}
    body.skin-midnight .management,body.skin-midnight table{{background:#293845;color:#e7edf2;}}
    body.skin-midnight th{{background:#24627b;}}
    body.skin-midnight td{{border-color:#405463;}}
    body.skin-midnight table tbody tr:nth-child(odd){{background:#293845 !important;}}
    body.skin-midnight table tbody tr:nth-child(even){{background:#25333e !important;}}
    body.skin-midnight table tbody tr:hover{{background:#3a4d5b !important;}}
    body.skin-midnight input,body.skin-midnight select{{background:#354957;color:#e7edf2;border-color:#607888;}}
    body.skin-midnight .ticker-management{{background:#293845;color:#e7edf2;}}
    body.skin-midnight .ticker-management label{{color:#e7edf2;}}
    body.skin-midnight .ticker-management input{{background:#354957;color:#e7edf2;border-color:#607888;}}
    .skin-control{{position:absolute;top:20px;left:20px;display:inline-flex;align-items:center;gap:8px;font-size:13px;font-weight:600;}}
    .skin-control select{{padding:6px 8px;border:1px solid #bdc3c7;border-radius:4px;font-size:13px;}}
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
    body.skin-ocean{{background:#eef7fb;color:#183642;}}
    body.skin-ocean h2{{color:#0b6174;border-color:#19a7a8;}}
    body.skin-ocean .management,body.skin-ocean table{{background:#ffffff;}}
    body.skin-ocean th{{background:#0b8793;}}
    body.skin-forest{{background:#f1f7f0;color:#263b2b;}}
    body.skin-forest h2{{color:#356b43;border-color:#6aa66f;}}
    body.skin-forest .management,body.skin-forest table{{background:#ffffff;}}
    body.skin-forest th{{background:#4d8757;}}
    body.skin-midnight{{background:#1f2933;color:#e7edf2;}}
    body.skin-midnight h2{{color:#b9e6ff;border-color:#4ca6c8;}}
    body.skin-midnight .management,body.skin-midnight table{{background:#293845;color:#e7edf2;}}
    body.skin-midnight th{{background:#24627b;}}
    body.skin-midnight td{{border-color:#405463;}}
    body.skin-midnight input,body.skin-midnight select{{background:#354957;color:#e7edf2;border-color:#607888;}}
    .skin-control{{position:absolute;top:20px;right:20px;display:inline-flex;align-items:center;gap:8px;font-size:13px;font-weight:600;z-index:1000;}}
    .skin-control select{{padding:6px 8px;border:1px solid #bdc3c7;border-radius:4px;font-size:13px;}}
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


def build_stock_report_html(data, current_symbols, target_prices=None, fifty_two_week_highs=None, futures_data=None, nse_movers=None, daily_movers=None, fifty_two_week_lows=None, nse_indexes=None):
    if target_prices is None:
        target_prices = {}
    if fifty_two_week_highs is None:
        fifty_two_week_highs = {}
    if fifty_two_week_lows is None:
        fifty_two_week_lows = {}
    if nse_indexes is None:
        nse_indexes = []
    if futures_data is None:
        futures_data = {}
    
    def get_below_25_indicator(current_price_str, high_52w):
        try:
            current_price = float(current_price_str.replace("₹", "").replace(",", ""))
            high = float(high_52w)
            if high <= 0:
                return '-'
            percentage_difference = ((high - current_price) / high) * 100
            css_class = 'diff-value above-25' if percentage_difference > 25 else 'diff-value'
            return f'<span class="{css_class}" title="Actual difference from 52W high">{percentage_difference:.1f}%</span>'
        except (ValueError, TypeError, ZeroDivisionError):
            return '-'
    
    def get_up_down_indicator(current_price_str, target_price):
        if target_price in (None, ''):
            return '-'
        try:
            current_price = float(current_price_str.replace("₹", "").replace(",", ""))
            target = float(target_price)
            if target <= 0:
                return '-'
            change = ((current_price - target) / target) * 100
            direction = 'up' if change >= 0 else 'down'
            return f'<span class="up-down {direction}">{change:+.1f}%</span>'
        except (ValueError, TypeError, ZeroDivisionError):
            return '-'

    def get_52w_low_value(low_52w):
        if low_52w in (None, ''):
            return '-'
        try:
            return f'₹{float(low_52w):.2f}'
        except (ValueError, TypeError):
            return '-'

    def get_52w_high_value(high_52w):
        if high_52w in (None, ''):
            return '-'
        try:
            return f'₹{float(high_52w):.2f}'
        except (ValueError, TypeError):
            return '-'
    
    rows = "\n".join(f"<tr data-ticker=\"{sym}\"><td>{sym}</td><td class=\"price\" data-current-price=\"{price.replace('₹', '').replace(',', '')}\" data-target-price=\"{target_prices.get(sym, '')}\">{price}</td><td><input type=\"number\" class=\"target-price\" data-ticker=\"{sym}\" step=\"0.01\" placeholder=\"Enter target\" value=\"{target_prices.get(sym, '')}\" onchange=\"saveTarget('{sym}', this.value)\" /></td><td class=\"up-down-cell\">{get_up_down_indicator(price, target_prices.get(sym, ''))}</td><td class=\"diff-cell\">{get_below_25_indicator(price, fifty_two_week_highs.get(sym, ''))}</td><td>{get_52w_high_value(fifty_two_week_highs.get(sym, ''))}</td><td>{get_52w_low_value(fifty_two_week_lows.get(sym, ''))}</td><td><button onclick=\"removeTicker('{sym}')\" style=\"background:#e74c3c;color:white;border:none;padding:4px 8px;border-radius:3px;cursor:pointer;\">Remove</button></td></tr>" for sym, price in data)
    
    # Build futures rows
    futures_rows = ""
    if futures_data:
        futures_rows = "\n".join(
            f"<tr data-ticker=\"{sym}\"><td>{format_futures_contract_label(sym, 'CURRENT')}</td><td class=\"price\" data-current-price=\"{price.replace('₹', '').replace(',', '')}\">{price}</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>"
            for sym, price in futures_data.items()
        )
    
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>NSE Stock Prices</title>
<meta http-equiv="refresh" content="120">
<style>
  body{{font-family:Arial,Helvetica,sans-serif;padding:20px;background:#f5f7fa;color:#333}}
    body.skin-ocean{{background:#eef7fb;color:#183642;}}
    body.skin-ocean h2{{color:#0b6174;border-color:#19a7a8;}}
    body.skin-ocean .management,body.skin-ocean table{{background:#ffffff;}}
    body.skin-ocean th{{background:#0b8793;}}
    body.skin-forest{{background:#f1f7f0;color:#263b2b;}}
    body.skin-forest h2{{color:#356b43;border-color:#6aa66f;}}
    body.skin-forest .management,body.skin-forest table{{background:#ffffff;}}
    body.skin-forest th{{background:#4d8757;}}
    body.skin-midnight{{background:#1f2933;color:#e7edf2;}}
    body.skin-midnight h2{{color:#b9e6ff;border-color:#4ca6c8;}}
    body.skin-midnight .management,body.skin-midnight table{{background:#293845;color:#e7edf2;}}
    body.skin-midnight th{{background:#24627b;}}
    body.skin-midnight td{{border-color:#405463;}}
    body.skin-midnight table tbody tr:nth-child(odd){{background:#293845 !important;}}
    body.skin-midnight table tbody tr:nth-child(even){{background:#25333e !important;}}
    body.skin-midnight table tbody tr:hover{{background:#3a4d5b !important;}}
    body.skin-midnight input,body.skin-midnight select{{background:#354957;color:#e7edf2;border-color:#607888;}}
    body.skin-midnight .ticker-management{{background:#293845;color:#e7edf2;}}
    body.skin-midnight .ticker-management label{{color:#e7edf2;}}
    body.skin-midnight .ticker-management input{{background:#354957;color:#e7edf2;border-color:#607888;}}
  h2{{color:#2c3e50;border-bottom:3px solid #3498db;padding-bottom:10px}}
  .management{{margin-bottom:20px;padding:15px;background:white;border-radius:6px;box-shadow:0 2px 8px rgba(0,0,0,0.1);}}
    .market-overview{{display:grid;grid-template-columns:minmax(240px,0.8fr) minmax(520px,2fr);gap:20px;align-items:start;}}
    .market-overview>.management{{margin-bottom:20px;}}
    @media (max-width:900px){{.market-overview{{grid-template-columns:1fr;}}}}
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
  table{{border-collapse:collapse;width:100%;max-width:1000px;background:white;box-shadow:0 2px 8px rgba(0,0,0,0.1);border-radius:6px;overflow:hidden}}
    #stockTable{{font-size:12px;}}
    #stockTable th,#stockTable td{{padding:6px 8px;line-height:1.2;}}
    .movers-table{{font-size:12px;box-shadow:none;}}
    .movers-table th,.movers-table td{{padding:6px 8px;}}
  th{{background:#3498db;color:white;padding:12px;text-align:left;font-weight:bold}}
  td{{border-bottom:1px solid #ecf0f1;padding:12px;text-align:left}}
  tbody tr:hover{{background:#ecf0f1}}
  tbody tr:nth-child(odd){{background:#f9fbfc}}
  .price{{white-space:nowrap;color:#27ae60;font-weight:bold}}
  .tabs{{display:flex;gap:10px;margin-bottom:15px;border-bottom:2px solid #ddd;}}
  .tab-btn{{padding:10px 20px;background:none;border:none;cursor:pointer;font-weight:600;color:#7f8c8d;border-bottom:3px solid transparent;}}
  .tab-btn.active{{color:#3498db;border-bottom-color:#3498db;}}
  .tab-content{{display:none;}}
  .tab-content.active{{display:block;}}
  .futures-selector{{margin-bottom:15px;padding:15px;background:#f0f4f8;border-radius:6px;}}
  .futures-selector select{{padding:8px;border:1px solid #bdc3c7;border-radius:4px;font-size:14px;}}
  .target-price{{width:100%;max-width:150px;padding:8px;border:1px solid #bdc3c7;border-radius:3px;font-size:14px;box-sizing:border-box;}}
  .target-price:focus{{outline:none;border-color:#3498db;box-shadow:0 0 5px rgba(52,152,219,0.3);}}
    .sort-arrows{{margin-left:6px;white-space:nowrap;}}
    .sort-arrow{{margin:0 2px;padding:0;background:none;color:white;font-size:14px;line-height:1;}}
    .diff-threshold{{width:48px;padding:3px;border:1px solid #bdc3c7;border-radius:3px;font-size:12px;}}
    .up-down{{font-weight:bold;white-space:nowrap;}}
    .up-down.up{{color:#27ae60;}}
    .up-down.down{{color:#e74c3c;}}
    .above-25{{color:#e74c3c;font-weight:bold;background:#ffeaea;padding:4px 8px;border-radius:3px;border:1px solid #f5c6cb;}}
    .diff-cell .diff-value{{display:inline-block;color:#2c3e50;font-weight:bold;background:#f8f9fa;padding:4px 8px;border-radius:3px;border:1px solid #bdc3c7;animation:none;}}
    .diff-cell .above-25{{display:inline-block;background:#ffeb3b;color:#d32f2f;border-color:#f39c12;animation:blink 0.8s infinite;}}
  .autocomplete-list{{position:absolute;top:100%;left:0;right:0;background:white;border:1px solid #bdc3c7;border-top:none;border-radius:0 0 4px 4px;max-height:200px;overflow-y:auto;z-index:1000;display:none;box-shadow:0 4px 6px rgba(0,0,0,0.1);}}
  .autocomplete-list.active{{display:block;}}
  .autocomplete-item{{padding:10px;cursor:pointer;color:#333;border-bottom:1px solid #ecf0f1;}}
  .autocomplete-item:hover{{background:#f0f4f8;}}
  .autocomplete-item.selected{{background:#e8f4f8;color:#3498db;font-weight:600;}}
  @keyframes blink{{0%{{opacity:1}}50%{{opacity:0.3}}100%{{opacity:1}}}}
  .price.target-reached{{animation:blink 0.6s infinite;background:#ffeb3b;color:#d32f2f;font-size:1.1em;padding:4px;border-radius:4px;}}
    .up-down.target-reached{{animation:blink 0.6s infinite;background:#ffeb3b;color:#d32f2f;padding:4px;border-radius:4px;}}
  .timestamp{{color:#7f8c8d;font-size:0.9em;margin-top:15px}}
    #flashNotification{{position:fixed;right:20px;bottom:20px;z-index:2000;display:flex;flex-direction:column;gap:8px;max-width:min(360px,calc(100vw - 40px));}}
    .flash-toast{{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:12px 12px 12px 16px;border-radius:6px;background:#2c3e50;color:white;box-shadow:0 4px 12px rgba(0,0,0,0.25);font-weight:600;animation:toast-in 0.25s ease-out;}}
    .flash-toast-close{{border:0;background:transparent;color:white;font-size:20px;line-height:1;cursor:pointer;padding:0 2px;}}
    .flash-toast.up{{border-left:5px solid #27ae60;}}
    .flash-toast.down{{border-left:5px solid #e74c3c;}}
    @keyframes toast-in{{from{{opacity:0;transform:translateY(12px)}}to{{opacity:1;transform:translateY(0)}}}}
</style>
</head>
<body>
    <label class="skin-control" for="skinSelector" title="Choose skin">
        <select id="skinSelector" aria-label="Choose skin" onchange="changeSkin(this.value)">
            <option value="default">Classic</option>
            <option value="ocean">Ocean</option>
            <option value="forest">Forest</option>
            <option value="midnight">Midnight</option>
        </select>
    </label>
    <div id="flashNotification" aria-live="polite" aria-atomic="true"></div>
        <h2 style="display:inline-block;">NSE Stock Prices</h2>
  <div class="nav" style="margin-bottom:15px;">
    <a href="/patterns" style="color:#3498db;text-decoration:none;font-weight:600;">Analyze candle patterns</a>
  </div>
  
  <div class="tabs">
    <button class="tab-btn active" onclick="switchTab('spot')">📊 Spot Prices</button>
  </div>
  
        <div id="spot" class="tab-content active">
          <div class="market-overview">
            <div class="management">
                    <h3>NSE Indexes</h3>
                    <table class="movers-table"><thead><tr><th>Index</th><th>Value</th><th>Change</th></tr></thead><tbody>{''.join(f"<tr><td>{name}</td><td>{value:.2f}</td><td style='color:{'#27ae60' if change >= 0 else '#e74c3c'};font-weight:bold;'>{change:+.2f}%</td></tr>" for name, value, change in nse_indexes) or '<tr><td colspan="3">No index data available</td></tr>'}</tbody></table>
                </div>
        <div class="management">
            <h3>Today's NSE Top 10 Gainers and Losers</h3>
            <div style="display:flex;gap:20px;flex-wrap:wrap;margin-bottom:12px;">
                <div style="min-width:260px;">
                    <h4 style="margin:6px 0 4px 0;color:#27ae60;">Top 10 Gainers</h4>
                    <table class="movers-table"><thead><tr><th>#</th><th>Symbol</th><th>Change</th><th>Price (INR)</th></tr></thead><tbody>{''.join(f"<tr><td>{rank}</td><td>{sym}</td><td style='color:#27ae60;font-weight:bold;'>{pct:+.2f}%</td><td>₹{price:.2f}</td></tr>" for rank, (sym, pct, price) in enumerate((nse_movers.get('gainers', []) if nse_movers else []), 1))}</tbody></table>
                </div>
                <div style="min-width:260px;">
                    <h4 style="margin:6px 0 4px 0;color:#e74c3c;">Top 10 Losers</h4>
                    <table class="movers-table"><thead><tr><th>#</th><th>Symbol</th><th>Change</th><th>Price (INR)</th></tr></thead><tbody>{''.join(f"<tr><td>{rank}</td><td>{sym}</td><td style='color:#e74c3c;font-weight:bold;'>{pct:+.2f}%</td><td>₹{price:.2f}</td></tr>" for rank, (sym, pct, price) in enumerate((nse_movers.get('losers', []) if nse_movers else []), 1))}</tbody></table>
                </div>
            </div>
        </div>
                    </div>
                <div class="management ticker-management">
      <h3>Manage Tickers</h3>
      <div class="form-group">
        <label for="addTicker">Add NSE Ticker:</label>
        <div style="position:relative;display:inline-block;width:100%;max-width:300px;">
          <input type="text" id="addTicker" placeholder="Enter ticker symbol (e.g., TCS)" />
          <div id="autocomplete-list" class="autocomplete-list"></div>
        </div>
        <button class="add-btn" onclick="addTicker()">Add Ticker</button>
      </div>
      <div id="statusMessage"></div>
    </div>
    
                <table id="stockTable">
                        <thead><tr><th>Stock Symbol</th><th>Current Price (INR)</th><th>Target Price (INR)</th><th>Up/Down <span class="sort-arrows"><button type="button" class="sort-arrow" title="Highest percentage first" onclick="sortByUpDown('desc')">↑</button><button type="button" class="sort-arrow" title="Lowest percentage first" onclick="sortByUpDown('asc')">↓</button></span></th><th>Diff % <input id="diffThreshold" class="diff-threshold" type="number" min="0" max="100" step="0.1" value="25" title="Flash above this percentage" oninput="updateDiffHighlight()"> <span class="sort-arrows"><button type="button" class="sort-arrow" title="Highest difference first" onclick="sortByDiff('desc')">↑</button><button type="button" class="sort-arrow" title="Lowest difference first" onclick="sortByDiff('asc')">↓</button></span></th><th>52W High (INR)</th><th>52W Low (INR)</th><th>Actions</th></tr></thead>
      <tbody>
                {rows or '<tr><td colspan="8">No data available</td></tr>'}
      </tbody>
    </table>
  </div>
  
  
  <p class="timestamp">Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    <p style="color:#7f8c8d;font-size:0.9em;">Auto-refreshes every 2 minutes</p>
  
  <script>
    // Popular NSE ticker symbols for autocomplete
    const popularTickers = [
      'TCS', 'INFY', 'RELIANCE', 'HDFCBANK', 'ICICIBANK', 'SBIN', 'HDFC',
      'BAJAJFINSV', 'WIPRO', 'MARUTI', 'SUNPHARMA', 'ASIANPAINT', 'ONGC', 'LT',
      'ITC', 'ULTRACEMCO', 'POWERGRID', 'BHARTIARTL', 'AXISBANK', 'KOTAKBANK',
      'JSWSTEEL', 'NTPC', 'INDIGO', 'BPCL', 'HINDUNILVR', 'NESTLEIND', 'TATAMOTORS',
      'M&M', 'TATASTEEL', 'DMART', 'ADANIGREEN', 'ADANIPORTS', 'GAIL', 'COAL',
      'NMDC', 'SAIL', 'HINDALCO', 'VEDL', 'TATACONSUM', 'CIPLA', 'DRREDDY',
      'LUPIN', 'APOLLOHOSP', 'BIOCON', 'IPCALAB', 'GLAXO', 'HEROMOTOCO',
      'EICHERMOT', 'BOSCHLTD', 'MOTHERSON', 'SIEMENS', 'HAVELLS', 'FLAMEUP',
      'CPLLAND', 'DLF', 'OBEROIRLTY', 'GODREJCP', 'BRITANNIA', 'COLPAL', 'MARICO'
    ];
    
    // Initialize autocomplete on page load
    document.addEventListener('DOMContentLoaded', function() {{
      const addTickerInput = document.getElementById('addTicker');
      if (addTickerInput) {{
        addTickerInput.addEventListener('input', function() {{
          handleAutoComplete(this.value);
        }});
        addTickerInput.addEventListener('focus', function() {{
          if (this.value.length > 0) {{
            handleAutoComplete(this.value);
          }}
        }});
        addTickerInput.addEventListener('blur', function() {{
          setTimeout(() => {{
            document.getElementById('autocomplete-list').classList.remove('active');
          }}, 200);
        }});
      }}
    }});
    
    // Handle autocomplete filtering and display
    function handleAutoComplete(value) {{
      const trimmedValue = value.trim().toUpperCase();
      const autocompleteList = document.getElementById('autocomplete-list');
      
      if (trimmedValue.length === 0) {{
        autocompleteList.classList.remove('active');
        return;
      }}
      
      const filtered = popularTickers.filter(ticker => 
        ticker.startsWith(trimmedValue)
      );
      
      if (filtered.length === 0) {{
        autocompleteList.classList.remove('active');
        return;
      }}
      
      autocompleteList.innerHTML = filtered
        .slice(0, 10) // Show top 10 matches
        .map((ticker, index) => 
          "<div class=\\\"autocomplete-item\\\" onclick=\\\"selectTicker('" + ticker + "')\\\" onmouseover=\\\"highlightItem(this)\\\" onmouseout=\\\"unhighlightItem(this)\\\" data-ticker=\\\"" + ticker + "\\\">" + ticker + "</div>"
        )
        .join('');
      
      autocompleteList.classList.add('active');
    }}
    
    // Select ticker from autocomplete
    function selectTicker(ticker) {{
      document.getElementById('addTicker').value = ticker;
      document.getElementById('autocomplete-list').classList.remove('active');
    }}
    
    // Highlight autocomplete item on hover
    function highlightItem(element) {{
      document.querySelectorAll('.autocomplete-item').forEach(item => {{
        item.classList.remove('selected');
      }});
      element.classList.add('selected');
    }}
    
    // Remove highlight
    function unhighlightItem(element) {{
      element.classList.remove('selected');
    }}
    
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

        function changeSkin(skin) {{
            document.body.className = skin === 'default' ? '' : `skin-${{skin}}`;
            localStorage.setItem('stockSkin', skin);
        }}

        const savedSkin = localStorage.getItem('stockSkin') || 'default';
        document.getElementById('skinSelector').value = savedSkin;
        changeSkin(savedSkin);

        function sortByUpDown(order) {{
            const tableBody = document.querySelector('#stockTable tbody');
            if (!tableBody) return;
            const rows = Array.from(tableBody.querySelectorAll('tr'));
            rows.sort((firstRow, secondRow) => {{
                const firstValue = parseFloat(firstRow.querySelector('.up-down-cell')?.textContent);
                const secondValue = parseFloat(secondRow.querySelector('.up-down-cell')?.textContent);
                if (isNaN(firstValue)) return 1;
                if (isNaN(secondValue)) return -1;
                return order === 'desc' ? secondValue - firstValue : firstValue - secondValue;
            }});
            rows.forEach(row => tableBody.appendChild(row));
        }}

        function sortByDiff(order) {{
            const tableBody = document.querySelector('#stockTable tbody');
            if (!tableBody) return;
            const rows = Array.from(tableBody.querySelectorAll('tr'));
            rows.sort((firstRow, secondRow) => {{
                const firstValue = parseFloat(firstRow.querySelector('.diff-cell')?.textContent);
                const secondValue = parseFloat(secondRow.querySelector('.diff-cell')?.textContent);
                if (isNaN(firstValue)) return 1;
                if (isNaN(secondValue)) return -1;
                return order === 'desc' ? secondValue - firstValue : firstValue - secondValue;
            }});
            rows.forEach(row => tableBody.appendChild(row));
        }}

        function updateDiffHighlight() {{
            const thresholdInput = document.getElementById('diffThreshold');
            const threshold = parseFloat(thresholdInput?.value);
            if (isNaN(threshold)) return;
            document.querySelectorAll('#stockTable .diff-cell .diff-value').forEach(value => {{
                const percentage = parseFloat(value.textContent);
                value.classList.toggle('above-25', percentage > threshold);
            }});
        }}

        function updateUpDown(row, targetValue) {{
            const priceCell = row.querySelector('.price');
            const upDownCell = row.querySelector('.up-down-cell');
            const currentPrice = parseFloat(priceCell?.getAttribute('data-current-price'));
            const targetPrice = parseFloat(targetValue);
            if (!upDownCell || isNaN(currentPrice) || isNaN(targetPrice) || targetPrice <= 0) {{
                if (upDownCell) upDownCell.textContent = '-';
                return;
            }}
            const change = ((currentPrice - targetPrice) / targetPrice) * 100;
            const direction = change >= 0 ? 'up' : 'down';
            upDownCell.innerHTML = `<span class="up-down ${{direction}}">${{change >= 0 ? '+' : ''}}${{change.toFixed(1)}}%</span>`;
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
                // Update the DOM so blinking can trigger without reload
                try {{
                    const row = document.querySelector(`tr[data-ticker="${{ticker}}"]`);
                    if (row) {{
                        const priceCell = row.querySelector('.price');
                        if (priceCell) {{
                            priceCell.setAttribute('data-target-price', value || '');
                        }}
                        updateUpDown(row, value);
                    }}
                }} catch (e) {{
                    console.warn('Could not update DOM target attribute:', e);
                }}

                // Re-evaluate blinking state immediately
                try {{
                    if (typeof checkTargetPrices === 'function') checkTargetPrices();
                }} catch (e) {{}}
            }} catch (error) {{
                console.error('Error saving target price:', error);
            }}
        }}
    
        const notifiedFlashes = new Set();
        let beepAudioContext;

        function playFlashBeep() {{
            try {{
                beepAudioContext = beepAudioContext || new (window.AudioContext || window.webkitAudioContext)();
                if (beepAudioContext.state === 'suspended') beepAudioContext.resume();
                const oscillator = beepAudioContext.createOscillator();
                const gain = beepAudioContext.createGain();
                oscillator.type = 'sine';
                oscillator.frequency.value = 880;
                gain.gain.setValueAtTime(0.2, beepAudioContext.currentTime);
                gain.gain.exponentialRampToValueAtTime(0.001, beepAudioContext.currentTime + 0.18);
                oscillator.connect(gain);
                gain.connect(beepAudioContext.destination);
                oscillator.start();
                oscillator.stop(beepAudioContext.currentTime + 0.18);
            }} catch (e) {{
                // Audio can be unavailable or blocked until the user interacts with the page.
            }}
        }}

        function showFlashNotification(ticker, direction) {{
            const notification = document.createElement('div');
            notification.className = `flash-toast ${{direction}}`;
            const message = document.createElement('span');
            message.textContent = `${{ticker}} is flashing ${{direction.toUpperCase()}}`;
            const closeButton = document.createElement('button');
            closeButton.className = 'flash-toast-close';
            closeButton.type = 'button';
            closeButton.setAttribute('aria-label', 'Close notification');
            closeButton.textContent = 'x';
            closeButton.addEventListener('click', () => notification.remove());
            notification.append(message, closeButton);
            document.getElementById('flashNotification')?.appendChild(notification);
            playFlashBeep();
        }}

    // Check if price reached target and apply blinking
        function checkTargetPrices() {{
            const rows = document.querySelectorAll('table tbody tr');
            rows.forEach(row => {{
                const priceCell = row.querySelector('.price');
                if (!priceCell) return;

                const currentPrice = parseFloat(priceCell.getAttribute('data-current-price'));
                const targetPrice = parseFloat(priceCell.getAttribute('data-target-price'));
                const upDownValue = row.querySelector('.up-down');

                if (!isNaN(currentPrice) && !isNaN(targetPrice) && targetPrice > 0) {{
                    // Blink the Up/Down value when current price is within ±1% of target.
                    const percentageDifference = Math.abs(currentPrice - targetPrice) / targetPrice;
                    const isFlashing = percentageDifference <= 0.01;
                    const shouldNotify = percentageDifference <= 0.005;
                    if (upDownValue) {{
                        upDownValue.classList.toggle('target-reached', isFlashing);
                        if (shouldNotify) {{
                            const ticker = row.getAttribute('data-ticker');
                            const direction = upDownValue.classList.contains('down') ? 'down' : 'up';
                            const notificationKey = `${{ticker}}:${{direction}}`;
                            if (!notifiedFlashes.has(notificationKey)) {{
                                notifiedFlashes.add(notificationKey);
                                showFlashNotification(ticker, direction);
                            }}
                        }}
                    }}
                    if (percentageDifference <= 0.005) {{
                        // Debugging aid for client-side console
                        try {{ console.debug('Target reached check', priceCell.closest('tr').getAttribute('data-ticker'), currentPrice, targetPrice, (percentageDifference * 100).toFixed(3) + '%'); }} catch (e) {{}}
                        priceCell.classList.add('target-reached');
                    }} else {{
                        priceCell.classList.remove('target-reached');
                    }}
                }} else {{
                    // Remove class if no valid target
                    priceCell.classList.remove('target-reached');
                    if (upDownValue) upDownValue.classList.remove('target-reached');
                }}
            }});
        }}
    
    checkTargetPrices();
    setInterval(checkTargetPrices, 5000);
    
    // Allow Enter key to add ticker
    document.getElementById('addTicker').addEventListener('keypress', function(e) {{
      if (e.key === 'Enter') {{
        addTicker();
      }}
    }});
    
    // Tab switching functionality
    function switchTab(tabName) {{
      // Hide all tab contents
      const contents = document.querySelectorAll('.tab-content');
      contents.forEach(content => content.classList.remove('active'));
      
      // Deactivate all tab buttons
      const buttons = document.querySelectorAll('.tab-btn');
      buttons.forEach(btn => btn.classList.remove('active'));
      
      // Show selected tab
      document.getElementById(tabName).classList.add('active');
      
      // Activate clicked button
      event.target.classList.add('active');
      
      // Refresh futures data if switching to futures tab
      if (tabName === 'futures') {{
        refreshFutures();
      }}
    }}
    
    // Refresh futures prices
    async function refreshFutures() {{
      const expiry = document.getElementById('futuresExpiry').value || 'CURRENT';
      try {{
        const response = await fetch(`/futures/prices?expiry=${{expiry}}`);
        const result = await response.json();
        
        const futuresTable = document.getElementById('futuresTable');
        if (result.success && result.data) {{
          const rows = Object.entries(result.data).map(([sym, data]) => {{
            const label = data && data.label ? data.label : sym;
            const price = data && data.price ? data.price : data;
            return `<tr><td>${{label}}</td><td class="price">${{price}}</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>`;
          }}).join('');
          futuresTable.innerHTML = rows || '<tr><td colspan="6">No futures data available</td></tr>';
        }}
      }} catch (error) {{
        console.error('Error refreshing futures:', error);
      }}
    }}
    
    // Switch futures expiry and refresh
    function switchFuturesExpiry() {{
      refreshFutures();
    }}
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

@app.route('/futures/patterns')
def futures_candle_patterns():
    ticker = request.args.get('ticker', '').strip().upper()
    expiry = request.args.get('expiry', 'CURRENT')
    
    if not ticker:
        html = build_pattern_page_html()
        response = make_response(html)
        response.headers['Content-Type'] = 'text/html; charset=utf-8'
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        return response

    if not validate_nse_futures_ticker(ticker, expiry):
        html = build_pattern_page_html(ticker=ticker, error=f"{ticker} futures ({expiry}) is not a valid NSE futures contract")
        response = make_response(html)
        response.headers['Content-Type'] = 'text/html; charset=utf-8'
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        return response

    df = get_nse_futures_history(ticker, expiry)
    if df is None:
        html = build_pattern_page_html(ticker=ticker, error=f"Could not load futures history for {ticker}")
        response = make_response(html)
        response.headers['Content-Type'] = 'text/html; charset=utf-8'
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        return response

    matches, recommendation = match_candle_patterns(df)
    html = build_pattern_page_html(ticker=f"{ticker} Futures ({expiry})", matches=matches, recommendation=recommendation)
    response = make_response(html)
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return response

@app.route('/futures/forecast')
def futures_candle_forecast():
    ticker = request.args.get('ticker', '').strip().upper()
    expiry = request.args.get('expiry', 'CURRENT')
    
    if not ticker:
        html = build_forecast_page_html()
        response = make_response(html)
        response.headers['Content-Type'] = 'text/html; charset=utf-8'
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        return response

    if not validate_nse_futures_ticker(ticker, expiry):
        html = build_forecast_page_html(ticker=ticker, error=f"{ticker} futures ({expiry}) is not a valid NSE futures contract")
        response = make_response(html)
        response.headers['Content-Type'] = 'text/html; charset=utf-8'
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        return response

    week_df = get_nse_futures_history(ticker, expiry, period='7d')
    month_df = get_nse_futures_history(ticker, expiry, period='1mo')

    if week_df is None or month_df is None:
        html = build_forecast_page_html(ticker=ticker, error=f"Could not load futures history for {ticker}")
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
        ticker=f"{ticker} Futures ({expiry})",
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

    data, fifty_two_week_highs, fifty_two_week_lows = get_stock_report_data(current_tickers)

    nse_movers = fetch_nse_top_movers(10)
    html = build_stock_report_html(data, current_tickers, current_targets, fifty_two_week_highs, {}, nse_movers, {}, fifty_two_week_lows, get_nse_index_data())
    save_apache_copy(html)
    response = make_response(html)
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return response

@app.route('/futures/prices')
def get_futures_prices():
    """Get futures prices for all current tickers."""
    global current_tickers
    
    expiry = request.args.get('expiry', 'CURRENT')
    futures_prices = {}
    
    for symbol in current_tickers:
        try:
            price = get_nse_futures_price(symbol, expiry)
            if price:
                futures_prices[symbol] = {
                    'label': format_futures_contract_label(symbol, expiry),
                    'price': f"₹{price:.2f}"
                }
        except Exception as e:
            if DEBUG:
                print(f"Error fetching futures price for {symbol}: {e}")
    
    return jsonify({
        'success': True,
        'expiry': expiry,
        'data': futures_prices
    })


@app.route('/nse-movers')
def nse_movers_endpoint():
    try:
        movers = fetch_nse_top_movers()
        return jsonify({'success': True, 'data': movers})
    except Exception as e:
        if DEBUG:
            print(f"Error in /nse-movers endpoint: {e}")
        return jsonify({'success': False, 'data': {'gainers': [], 'losers': []}, 'error': str(e)})

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
    try:
        ensure_output_paths()
        # Generate initial Apache copy so saved HTML contains latest prices/targets
        try:
            save_current_apache_copy()
        except Exception as e:
            log_message(f'Failed to generate initial Apache copy: {e}')
        log_message('Starting pattern_stocks Flask app')
        app.run(debug=DEBUG, host='127.0.0.1', port=5001)
    except Exception as e:
        log_message(f'Failed to start Flask app: {e}')
        raise

