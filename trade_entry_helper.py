"""
Enhanced Trade Entry Module for TTA Strategy
Auto-fills entry price, calculates stops, and validates strategy rules
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta


def fetch_current_price(ticker):
    """Fetch current market price for a ticker"""
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period='1d')
        if not hist.empty:
            return float(hist['Close'].iloc[-1])
        return None
    except Exception as e:
        print(f"Error fetching price for {ticker}: {e}")
        return None


def calculate_atr(ticker, period=14):
    """Calculate Average True Range for stop loss"""
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period='3mo')  # Get enough data for ATR
        
        if len(hist) < period:
            return None
        
        # Calculate True Range
        high_low = hist['High'] - hist['Low']
        high_close = np.abs(hist['High'] - hist['Close'].shift())
        low_close = np.abs(hist['Low'] - hist['Close'].shift())
        
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)
        
        # ATR is the moving average of True Range
        atr = true_range.rolling(window=period).mean().iloc[-1]
        
        return float(atr)
    except Exception as e:
        print(f"Error calculating ATR for {ticker}: {e}")
        return None


def calculate_strategy_stops(entry_price, atr=None):
    """
    Calculate stop losses based on TTA strategy:
    - Initial stop: 15% below entry (protective stop)
    - ATR-based stop: 3.5x ATR below entry (if ATR available)
    - Use the less aggressive (higher) of the two
    """
    # Protective stop: 15% below entry
    protective_stop = entry_price * 0.85
    
    # ATR-based stop (if available)
    if atr and atr > 0:
        atr_stop = entry_price - (3.5 * atr)
        # Use the higher stop (less aggressive)
        stop_loss = max(protective_stop, atr_stop)
        stop_type = "ATR" if stop_loss == atr_stop else "15% Protective"
    else:
        stop_loss = protective_stop
        stop_type = "15% Protective"
    
    return stop_loss, stop_type


def calculate_profit_target(entry_price):
    """
    Calculate initial profit target:
    - 20% gain (where ATR trail would activate)
    """
    return entry_price * 1.20


def validate_entry_conditions(ticker):
    """
    Validate TTA strategy entry conditions:
    - Daily MACD above signal
    - Daily AO > 0
    - AO crossed from ≤0 to >0 in last 20 days
    - SPY not below 200 SMA
    - VIX not above 30
    
    Returns: (is_valid, reasons_dict)
    """
    try:
        # Fetch stock data with enough history for accurate MACD
        stock = yf.Ticker(ticker)
        hist = stock.history(period='6mo', interval='1d')
        
        if len(hist) < 50:
            return False, {"error": "Insufficient data"}
        
        # Verify data is recent (not stale)
        latest_date = hist.index[-1]
        days_old = (datetime.now() - latest_date.to_pydatetime()).days
        
        if days_old > 5:
            return False, {"error": f"Data is {days_old} days old"}
        
        # Calculate MACD (12, 26, 9) - need at least 35 bars for warmup
        exp1 = hist['Close'].ewm(span=12, adjust=False).mean()
        exp2 = hist['Close'].ewm(span=26, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.ewm(span=9, adjust=False).mean()
        
        # Calculate AO (5/34 of median price) - Awesome Oscillator
        median_price = (hist['High'] + hist['Low']) / 2
        ao_fast = median_price.rolling(window=5, min_periods=5).mean()
        ao_slow = median_price.rolling(window=34, min_periods=34).mean()
        ao = ao_fast - ao_slow
        
        # Drop NaN values that occur during warmup period
        ao = ao.dropna()
        
        # Check conditions
        checks = {}
        
        # 1. Daily MACD above signal (bullish)
        # Store actual values for debugging
        macd_value = float(macd.iloc[-1])
        signal_value = float(signal.iloc[-1])
        macd_cross = macd_value > signal_value
        checks['daily_macd_cross'] = macd_cross
        checks['_macd_debug'] = f"MACD:{macd_value:.2f} vs Signal:{signal_value:.2f}"
        
        # 2. Daily AO > 0
        ao_value = float(ao.iloc[-1])
        ao_positive = ao_value > 0
        checks['ao_positive'] = ao_positive
        checks['_ao_debug'] = f"AO:{ao_value:.2f}"
        
        # 3. AO crossed from ≤0 to >0 in last 20 days
        ao_recent = ao.iloc[-20:]
        ao_crosses = (ao_recent.shift(1) <= 0) & (ao_recent > 0)
        ao_recent_cross = any(ao_crosses)
        checks['ao_recent_cross'] = ao_recent_cross
        
        # Debug: Find when the most recent cross occurred
        if ao_recent_cross:
            cross_indices = ao_crosses[ao_crosses].index
            if len(cross_indices) > 0:
                days_since_cross = len(ao_recent) - list(ao_recent.index).index(cross_indices[-1]) - 1
                checks['_ao_cross_debug'] = f"Last AO cross: {days_since_cross} bars ago"
        else:
            # Check last few AO values to see why it failed
            recent_ao_values = [f"{float(ao.iloc[i]):.1f}" for i in range(-5, 0)]
            checks['_ao_cross_debug'] = f"Last 5 AO: {', '.join(recent_ao_values)}"
        
        # 4. SPY above 200 SMA
        spy = yf.Ticker("SPY")
        spy_hist = spy.history(period='1y', interval='1d')
        if len(spy_hist) >= 200:
            spy_sma200 = spy_hist['Close'].rolling(window=200).mean()
            spy_above_200 = spy_hist['Close'].iloc[-1] > spy_sma200.iloc[-1]
            checks['spy_above_200'] = spy_above_200
        else:
            checks['spy_above_200'] = False
            checks['error'] = "SPY data insufficient"
        
        # 5. VIX below 30
        vix = yf.Ticker("^VIX")
        vix_hist = vix.history(period='5d')
        if len(vix_hist) > 0:
            vix_value = float(vix_hist['Close'].iloc[-1])
            vix_below_30 = vix_value < 30
            checks['vix_below_30'] = vix_below_30
            checks['_vix_debug'] = f"VIX:{vix_value:.1f}"
        else:
            checks['vix_below_30'] = False
        
        # Store data freshness info
        checks['_data_date'] = latest_date.strftime('%Y-%m-%d')
        checks['_data_age_days'] = days_old
        
        # All must be true (ignore debug keys starting with _)
        condition_keys = [k for k in checks.keys() if not k.startswith('_')]
        is_valid = all(checks[k] for k in condition_keys if k != 'error')
        
        return is_valid, checks
        
    except Exception as e:
        return False, {"error": str(e)}


def format_entry_validation(is_valid, checks):
    """Format validation results for display"""
    if 'error' in checks:
        return f"❌ Error: {checks['error']}"
    
    status_emoji = "✅" if is_valid else "⚠️"
    
    messages = []
    messages.append(f"{status_emoji} **Entry Validation:**")
    
    check_map = {
        'daily_macd_cross': '📈 Daily MACD above signal',
        'ao_positive': '💚 AO > 0',
        'ao_recent_cross': '🔄 AO crossed zero recently (20d)',
        'spy_above_200': '📊 SPY above 200 SMA',
        'vix_below_30': '😌 VIX below 30'
    }
    
    for key, label in check_map.items():
        if key in checks:
            emoji = "✅" if checks[key] else "❌"
            messages.append(f"  {emoji} {label}")
    
    # Add debug info if available
    if '_data_date' in checks:
        messages.append(f"\n📅 Data as of: {checks['_data_date']} ({checks['_data_age_days']} days old)")
    
    if '_macd_debug' in checks:
        messages.append(f"🔍 {checks['_macd_debug']}")
    
    if '_ao_debug' in checks:
        messages.append(f"🔍 {checks['_ao_debug']}")
    
    if '_ao_cross_debug' in checks:
        messages.append(f"🔍 {checks['_ao_cross_debug']}")
        
    if '_vix_debug' in checks:
        messages.append(f"🔍 {checks['_vix_debug']}")
    
    if is_valid:
        messages.append("\n🎯 **All entry conditions met!**")
    else:
        messages.append("\n⚠️ **Some conditions not met - proceed with caution**")
    
    return "\n".join(messages)


def get_exit_strategy_note():
    """Return exit strategy reminder"""
    return """
**TTA Exit Strategy:**

1️⃣ **Protective Stop (15%)**: Exit if price falls 15% below entry

2️⃣ **Weekly MACD Cross**: Exit when Weekly MACD crosses below signal (Wave 3 complete)

3️⃣ **Volatility Trail (20%+)**: If up 20%+, ATR-based trailing stop protects profits

💡 Monitor Weekly MACD in your charting platform for exit signals
"""
