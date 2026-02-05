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
    - Daily MACD cross above signal
    - Daily AO > 0
    - AO crossed from ≤0 to >0 in last 20 days
    - SPY not below 200 SMA
    - VIX not above 30
    
    Returns: (is_valid, reasons_dict)
    """
    try:
        # Fetch stock data
        stock = yf.Ticker(ticker)
        hist = stock.history(period='3mo', interval='1d')
        
        if len(hist) < 50:
            return False, {"error": "Insufficient data"}
        
        # Calculate MACD (12, 26, 9)
        exp1 = hist['Close'].ewm(span=12, adjust=False).mean()
        exp2 = hist['Close'].ewm(span=26, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.ewm(span=9, adjust=False).mean()
        
        # Calculate AO (5/34 of median price)
        median_price = (hist['High'] + hist['Low']) / 2
        ao = median_price.rolling(window=5).mean() - median_price.rolling(window=34).mean()
        
        # Check conditions
        checks = {}
        
        # 1. Daily MACD cross (today's MACD > signal AND yesterday's MACD <= signal)
        macd_cross = (macd.iloc[-1] > signal.iloc[-1]) and (macd.iloc[-2] <= signal.iloc[-2])
        checks['daily_macd_cross'] = macd_cross
        
        # 2. Daily AO > 0
        ao_positive = ao.iloc[-1] > 0
        checks['ao_positive'] = ao_positive
        
        # 3. AO crossed from ≤0 to >0 in last 20 days
        ao_recent = ao.iloc[-20:]
        ao_recent_cross = any((ao_recent.shift(1) <= 0) & (ao_recent > 0))
        checks['ao_recent_cross'] = ao_recent_cross
        
        # 4. SPY above 200 SMA
        spy = yf.Ticker("SPY")
        spy_hist = spy.history(period='1y', interval='1d')
        spy_sma200 = spy_hist['Close'].rolling(window=200).mean()
        spy_above_200 = spy_hist['Close'].iloc[-1] > spy_sma200.iloc[-1]
        checks['spy_above_200'] = spy_above_200
        
        # 5. VIX below 30
        vix = yf.Ticker("^VIX")
        vix_hist = vix.history(period='5d')
        vix_below_30 = vix_hist['Close'].iloc[-1] < 30
        checks['vix_below_30'] = vix_below_30
        
        # All must be true
        is_valid = all(checks.values())
        
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
        'daily_macd_cross': '📈 Daily MACD crossed up',
        'ao_positive': '💚 AO > 0',
        'ao_recent_cross': '🔄 AO crossed zero recently (20d)',
        'spy_above_200': '📊 SPY above 200 SMA',
        'vix_below_30': '😌 VIX below 30'
    }
    
    for key, label in check_map.items():
        if key in checks:
            emoji = "✅" if checks[key] else "❌"
            messages.append(f"  {emoji} {label}")
    
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
