"""
Enhanced Trade Entry Module for TTA Strategy
Auto-fills entry price, calculates stops, validates strategy rules,
and provides quality scoring based on historical backtest performance.

FIXES APPLIED:
- AO zero-cross check now looks BACKWARDS from signal bar (matches backtester)
- Added quality scoring with mini-backtest
- Added Weekly MACD confirmation check
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, Tuple, Optional, Any, List


# =============================================================================
# INDICATOR CALCULATIONS (matching backtester exactly)
# =============================================================================

def calculate_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """Calculate MACD indicator - matches backtester"""
    df = df.copy()
    ema_fast = df['Close'].ewm(span=fast, adjust=False).mean()
    ema_slow = df['Close'].ewm(span=slow, adjust=False).mean()
    df['MACD'] = ema_fast - ema_slow
    df['MACD_Signal'] = df['MACD'].ewm(span=signal, adjust=False).mean()
    df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']
    return df


def calculate_ao(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate Awesome Oscillator - matches backtester"""
    df = df.copy()
    median_price = (df['High'] + df['Low']) / 2
    df['AO'] = median_price.rolling(window=5).mean() - median_price.rolling(window=34).mean()
    return df


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Calculate Average True Range - matches backtester"""
    df = df.copy()
    high_low = df['High'] - df['Low']
    high_close = (df['High'] - df['Close'].shift(1)).abs()
    low_close = (df['Low'] - df['Close'].shift(1)).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['ATR'] = true_range.rolling(period).mean()
    return df


# =============================================================================
# PRICE AND ATR HELPERS
# =============================================================================

def fetch_current_price(ticker: str) -> Optional[float]:
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


def calculate_atr_value(ticker: str, period: int = 14) -> Optional[float]:
    """Calculate Average True Range for stop loss"""
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period='3mo')
        
        if len(hist) < period:
            return None
        
        # Handle MultiIndex columns
        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = hist.columns.get_level_values(0)
        
        hist = calculate_atr(hist, period)
        return float(hist['ATR'].iloc[-1])
    except Exception as e:
        print(f"Error calculating ATR for {ticker}: {e}")
        return None


def calculate_strategy_stops(entry_price: float, atr: float = None) -> Tuple[float, str]:
    """
    Calculate stop losses based on TTA strategy:
    - Initial stop: 15% below entry (protective stop)
    - ATR-based stop: 3.5x ATR below entry (if ATR available)
    - Use the less aggressive (higher) of the two
    """
    protective_stop = entry_price * 0.85
    
    if atr and atr > 0:
        atr_stop = entry_price - (3.5 * atr)
        stop_loss = max(protective_stop, atr_stop)
        stop_type = "ATR" if stop_loss == atr_stop else "15% Protective"
    else:
        stop_loss = protective_stop
        stop_type = "15% Protective"
    
    return stop_loss, stop_type


def calculate_profit_target(entry_price: float) -> float:
    """Calculate initial profit target: 20% gain (where ATR trail activates)"""
    return entry_price * 1.20


# =============================================================================
# MARKET FILTER
# =============================================================================

def get_market_filter() -> Tuple[bool, bool, float, float, float]:
    """
    Check market conditions for TTA strategy.
    
    Returns: (spy_above_200, vix_below_30, spy_close, spy_ma200, vix_close)
    """
    try:
        # SPY check
        spy = yf.Ticker("SPY")
        spy_hist = spy.history(period='1y', interval='1d')
        
        if isinstance(spy_hist.columns, pd.MultiIndex):
            spy_hist.columns = spy_hist.columns.get_level_values(0)
        
        spy_close = float(spy_hist['Close'].iloc[-1])
        spy_ma200 = float(spy_hist['Close'].rolling(window=200).mean().iloc[-1])
        spy_above_200 = spy_close > spy_ma200
        
        # VIX check
        vix = yf.Ticker("^VIX")
        vix_hist = vix.history(period='5d')
        
        if isinstance(vix_hist.columns, pd.MultiIndex):
            vix_hist.columns = vix_hist.columns.get_level_values(0)
        
        vix_close = float(vix_hist['Close'].iloc[-1])
        vix_below_30 = vix_close < 30
        
        return spy_above_200, vix_below_30, spy_close, spy_ma200, vix_close
        
    except Exception as e:
        print(f"Error fetching market filter data: {e}")
        return True, True, 0, 0, 0  # Default to passing on error


# =============================================================================
# CORRECTED ENTRY VALIDATION - MATCHES BACKTESTER EXACTLY
# =============================================================================

def validate_entry_conditions(ticker: str, entry_window: int = 20) -> Tuple[bool, Dict]:
    """
    Validate TTA strategy entry conditions - CORRECTED VERSION.
    
    This now matches the backtester logic EXACTLY:
    
    1. Daily MACD crossover on CURRENT bar (today)
       - Today's MACD > Today's Signal
       - Yesterday's MACD <= Yesterday's Signal
    
    2. Daily AO > 0 on CURRENT bar
    
    3. AO crossed from ≤0 to >0 in the PRIOR entry_window days
       - Look BACKWARDS from today (not including today)
       - This confirms coming out of a pullback
    
    4. Market filter: SPY above 200 SMA AND VIX < 30
    
    Returns: (is_valid, checks_dict)
    """
    checks = {}
    
    try:
        # Fetch stock data
        stock = yf.Ticker(ticker)
        hist = stock.history(period='6mo', interval='1d')
        
        if len(hist) < 50:
            return False, {"error": "Insufficient data"}
        
        # Handle MultiIndex columns
        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = hist.columns.get_level_values(0)
        
        # Calculate indicators
        hist = calculate_macd(hist)
        hist = calculate_ao(hist)
        
        # Current bar index
        i = len(hist) - 1
        
        if i < entry_window + 1:
            return False, {"error": "Not enough history for lookback"}
        
        # =================================================================
        # CHECK 1: MACD crossover on CURRENT bar
        # =================================================================
        current_macd = hist['MACD'].iloc[i]
        current_signal = hist['MACD_Signal'].iloc[i]
        prev_macd = hist['MACD'].iloc[i - 1]
        prev_signal = hist['MACD_Signal'].iloc[i - 1]
        
        # MACD crossover: today above, yesterday at or below
        macd_cross = (current_macd > current_signal) and (prev_macd <= prev_signal)
        checks['daily_macd_cross'] = macd_cross
        
        # Also store if MACD is just bullish (above signal) even without fresh cross
        checks['macd_bullish'] = current_macd > current_signal
        
        # =================================================================
        # CHECK 2: AO > 0 on CURRENT bar
        # =================================================================
        ao_current = hist['AO'].iloc[i]
        ao_positive = ao_current > 0
        checks['ao_positive'] = ao_positive
        checks['ao_value'] = float(ao_current)
        
        # =================================================================
        # CHECK 3: AO crossed from ≤0 to >0 in PRIOR entry_window days
        # THIS IS THE KEY FIX - look BACKWARDS, not including today
        # =================================================================
        ao_cross_found = False
        ao_cross_date = None
        ao_cross_days_ago = None
        
        # Look backwards from yesterday (i-1) for entry_window bars
        for j in range(1, entry_window + 1):
            past_idx = i - j
            
            if past_idx < 1:
                break
            
            # Check if AO crossed from ≤0 to >0 at this bar
            ao_before = hist['AO'].iloc[past_idx - 1]
            ao_after = hist['AO'].iloc[past_idx]
            
            if ao_before <= 0 and ao_after > 0:
                ao_cross_found = True
                ao_cross_date = hist.index[past_idx].strftime('%Y-%m-%d')
                ao_cross_days_ago = j
                break
        
        checks['ao_recent_cross'] = ao_cross_found
        checks['ao_cross_date'] = ao_cross_date
        checks['ao_cross_days_ago'] = ao_cross_days_ago
        
        # =================================================================
        # CHECK 4: Market filter
        # =================================================================
        spy_above_200, vix_below_30, spy_close, spy_ma200, vix_close = get_market_filter()
        
        checks['spy_above_200'] = spy_above_200
        checks['vix_below_30'] = vix_below_30
        checks['spy_close'] = spy_close
        checks['spy_ma200'] = spy_ma200
        checks['vix_close'] = vix_close
        
        # =================================================================
        # FINAL DETERMINATION
        # =================================================================
        # Strict mode: require exact MACD cross today
        is_valid_strict = all([
            checks['daily_macd_cross'],
            checks['ao_positive'],
            checks['ao_recent_cross'],
            checks['spy_above_200'],
            checks['vix_below_30']
        ])
        
        # Relaxed mode: MACD just needs to be bullish (not fresh cross)
        is_valid_relaxed = all([
            checks['macd_bullish'],
            checks['ao_positive'],
            checks['ao_recent_cross'],
            checks['spy_above_200'],
            checks['vix_below_30']
        ])
        
        checks['valid_strict'] = is_valid_strict
        checks['valid_relaxed'] = is_valid_relaxed
        
        # Primary validity uses strict (matches backtester)
        return is_valid_strict, checks
        
    except Exception as e:
        return False, {"error": str(e)}


# =============================================================================
# WEEKLY CONFIRMATION CHECK
# =============================================================================

def check_weekly_confirmation(ticker: str) -> Dict[str, Any]:
    """
    Check Weekly MACD status for trend confirmation.
    
    From backtester:
    - If Weekly MACD > Weekly Signal = Bullish (Re-Entry signal type)
    - If Weekly MACD < Weekly Signal = Waiting for Wave 3 confirmation
    """
    result = {
        'weekly_bullish': False,
        'weekly_macd': None,
        'weekly_signal': None,
        'signal_type': None,
        'error': None
    }
    
    try:
        stock = yf.Ticker(ticker)
        weekly = stock.history(period='2y', interval='1wk')
        
        if weekly.empty or len(weekly) < 30:
            result['error'] = "Insufficient weekly data"
            return result
        
        if isinstance(weekly.columns, pd.MultiIndex):
            weekly.columns = weekly.columns.get_level_values(0)
        
        weekly = calculate_macd(weekly)
        
        weekly_macd = float(weekly['MACD'].iloc[-1])
        weekly_signal = float(weekly['MACD_Signal'].iloc[-1])
        
        result['weekly_macd'] = round(weekly_macd, 4)
        result['weekly_signal'] = round(weekly_signal, 4)
        result['weekly_bullish'] = weekly_macd > weekly_signal
        
        if result['weekly_bullish']:
            result['signal_type'] = "Re-Entry 🔄"
        else:
            result['signal_type'] = "New Wave 🌊"
        
        return result
        
    except Exception as e:
        result['error'] = str(e)
        return result


# =============================================================================
# QUALITY SCORING - MINI BACKTEST
# =============================================================================

def calculate_quality_score(ticker: str, lookback_years: int = 3) -> Dict[str, Any]:
    """
    Run a mini-backtest on the ticker to calculate a quality score.
    
    This simulates the TTA strategy on historical data and calculates:
    - Number of signals generated
    - Win rate
    - Average return
    - Quality grade (A/B/C/F)
    
    Returns dict with quality metrics.
    """
    result = {
        'ticker': ticker,
        'quality_grade': 'N/A',
        'quality_score': 0,
        'signals_found': 0,
        'win_rate': 0,
        'avg_return': 0,
        'best_return': 0,
        'worst_return': 0,
        'weekly_confirmed_pct': 0,
        'error': None,
        'details': []
    }
    
    try:
        # Fetch data
        end_date = datetime.now()
        start_date = end_date - timedelta(days=lookback_years * 365)
        
        stock = yf.Ticker(ticker)
        daily = stock.history(start=start_date.strftime('%Y-%m-%d'), 
                             end=end_date.strftime('%Y-%m-%d'), 
                             interval='1d')
        weekly = stock.history(start=start_date.strftime('%Y-%m-%d'),
                              end=end_date.strftime('%Y-%m-%d'),
                              interval='1wk')
        
        if daily.empty or len(daily) < 100:
            result['error'] = "Insufficient daily data"
            return result
        
        if weekly.empty or len(weekly) < 30:
            result['error'] = "Insufficient weekly data"
            return result
        
        # Handle MultiIndex
        if isinstance(daily.columns, pd.MultiIndex):
            daily.columns = daily.columns.get_level_values(0)
        if isinstance(weekly.columns, pd.MultiIndex):
            weekly.columns = weekly.columns.get_level_values(0)
        
        # Calculate indicators
        daily = calculate_macd(daily)
        daily = calculate_ao(daily)
        weekly = calculate_macd(weekly)
        
        # Configuration (matching backtester)
        ENTRY_WINDOW = 20
        PROTECTIVE_STOP_PCT = -15.0
        
        signals = []
        
        # Scan for signals
        for i in range(ENTRY_WINDOW + 30, len(daily)):
            current_date = daily.index[i]
            
            # Check MACD crossover
            current_macd = daily['MACD'].iloc[i]
            current_signal = daily['MACD_Signal'].iloc[i]
            prev_macd = daily['MACD'].iloc[i - 1]
            prev_signal = daily['MACD_Signal'].iloc[i - 1]
            
            macd_cross = (current_macd > current_signal) and (prev_macd <= prev_signal)
            if not macd_cross:
                continue
            
            # Check AO positive
            if daily['AO'].iloc[i] <= 0:
                continue
            
            # Check AO zero-cross in lookback (CORRECTED)
            ao_cross_found = False
            for j in range(1, ENTRY_WINDOW + 1):
                past_idx = i - j
                if past_idx < 1:
                    break
                if daily['AO'].iloc[past_idx - 1] <= 0 and daily['AO'].iloc[past_idx] > 0:
                    ao_cross_found = True
                    break
            
            if not ao_cross_found:
                continue
            
            # Entry signal found - simulate trade
            entry_price = daily['Close'].iloc[i]
            entry_date = current_date
            
            # Check weekly confirmation
            weekly_dates = weekly.index[weekly.index <= current_date]
            weekly_confirmed = False
            if len(weekly_dates) > 0:
                weekly_idx = len(weekly_dates) - 1
                if weekly_idx >= 26:
                    w_macd = weekly['MACD'].iloc[weekly_idx]
                    w_signal = weekly['MACD_Signal'].iloc[weekly_idx]
                    weekly_confirmed = w_macd > w_signal
            
            # Simulate exit (simplified: protective stop or 60-day hold)
            exit_price = entry_price
            exit_reason = "End_Data"
            
            for future_day in range(i + 1, min(i + 60, len(daily))):
                future_price = daily['Close'].iloc[future_day]
                current_return = ((future_price - entry_price) / entry_price) * 100
                
                # Protective stop
                if current_return <= PROTECTIVE_STOP_PCT:
                    exit_price = future_price
                    exit_reason = "Stop_Loss"
                    break
                
                # Check weekly cross down
                future_date = daily.index[future_day]
                future_weekly_dates = weekly.index[weekly.index <= future_date]
                if len(future_weekly_dates) > 0:
                    fw_idx = len(future_weekly_dates) - 1
                    if fw_idx > weekly_idx and fw_idx >= 26:
                        curr_w_macd = weekly['MACD'].iloc[fw_idx]
                        curr_w_signal = weekly['MACD_Signal'].iloc[fw_idx]
                        prev_w_macd = weekly['MACD'].iloc[fw_idx - 1]
                        prev_w_signal = weekly['MACD_Signal'].iloc[fw_idx - 1]
                        
                        if curr_w_macd < curr_w_signal and prev_w_macd >= prev_w_signal:
                            exit_price = future_price
                            exit_reason = "Weekly_Cross_Down"
                            break
            else:
                # Reached end of simulation window
                exit_price = daily['Close'].iloc[min(i + 59, len(daily) - 1)]
            
            return_pct = ((exit_price - entry_price) / entry_price) * 100
            
            signals.append({
                'entry_date': entry_date.strftime('%Y-%m-%d'),
                'entry_price': entry_price,
                'exit_price': exit_price,
                'return_pct': return_pct,
                'win': return_pct > 0,
                'weekly_confirmed': weekly_confirmed,
                'exit_reason': exit_reason
            })
        
        # Calculate metrics
        if len(signals) == 0:
            result['error'] = "No signals found in backtest"
            result['quality_grade'] = 'N/A'
            return result
        
        df = pd.DataFrame(signals)
        
        result['signals_found'] = len(signals)
        result['win_rate'] = (df['win'].sum() / len(df)) * 100
        result['avg_return'] = df['return_pct'].mean()
        result['best_return'] = df['return_pct'].max()
        result['worst_return'] = df['return_pct'].min()
        result['weekly_confirmed_pct'] = (df['weekly_confirmed'].sum() / len(df)) * 100
        result['details'] = signals[-5:]  # Last 5 signals
        
        # Calculate quality score (0-100)
        # Based on: win rate (40%), avg return (30%), signal count (20%), worst loss (10%)
        wr_score = min(result['win_rate'], 80) / 80 * 40  # Cap at 80% win rate
        ret_score = min(max(result['avg_return'], 0), 30) / 30 * 30  # Cap at 30% avg return
        sig_score = min(result['signals_found'], 20) / 20 * 20  # Cap at 20 signals
        loss_score = max(0, 10 + result['worst_return'] / 3)  # Penalize big losses
        
        result['quality_score'] = int(wr_score + ret_score + sig_score + loss_score)
        
        # Assign grade
        if result['quality_score'] >= 70 and result['win_rate'] >= 60:
            result['quality_grade'] = 'A'
        elif result['quality_score'] >= 50 and result['win_rate'] >= 50:
            result['quality_grade'] = 'B'
        elif result['quality_score'] >= 30 and result['win_rate'] >= 40:
            result['quality_grade'] = 'C'
        else:
            result['quality_grade'] = 'F'
        
        return result
        
    except Exception as e:
        result['error'] = str(e)
        return result


# =============================================================================
# COMPREHENSIVE TICKER ANALYSIS
# =============================================================================

def analyze_ticker_full(ticker: str) -> Dict[str, Any]:
    """
    Run complete analysis on a ticker:
    1. Current entry signal validation
    2. Weekly confirmation status
    3. Quality score from backtest
    
    Returns comprehensive analysis dict.
    """
    result = {
        'ticker': ticker.upper(),
        'timestamp': datetime.now().isoformat(),
        'current_price': None,
        'entry_signal': {},
        'weekly_status': {},
        'quality': {},
        'recommendation': 'SKIP',
        'summary': ''
    }
    
    # Get current price
    result['current_price'] = fetch_current_price(ticker)
    
    # Check entry conditions
    is_valid, checks = validate_entry_conditions(ticker)
    result['entry_signal'] = {
        'is_valid': is_valid,
        'checks': checks
    }
    
    # Check weekly confirmation
    result['weekly_status'] = check_weekly_confirmation(ticker)
    
    # Calculate quality score
    result['quality'] = calculate_quality_score(ticker)
    
    # Generate recommendation
    quality_grade = result['quality'].get('quality_grade', 'N/A')
    weekly_bullish = result['weekly_status'].get('weekly_bullish', False)
    
    if is_valid:
        if quality_grade in ['A', 'B'] and weekly_bullish:
            result['recommendation'] = 'STRONG BUY'
            result['summary'] = f"✅ Entry signal valid, Weekly bullish, Quality {quality_grade}"
        elif quality_grade in ['A', 'B']:
            result['recommendation'] = 'BUY'
            result['summary'] = f"✅ Entry signal valid, Quality {quality_grade}, Weekly pending"
        elif quality_grade == 'C':
            result['recommendation'] = 'WAIT'
            result['summary'] = f"⚠️ Entry signal valid but Quality {quality_grade}"
        else:
            result['recommendation'] = 'SKIP'
            result['summary'] = f"❌ Entry signal valid but Quality {quality_grade}"
    else:
        if checks.get('valid_relaxed'):
            result['recommendation'] = 'WATCH'
            result['summary'] = f"🟡 MACD bullish but no fresh cross, Quality {quality_grade}"
        else:
            result['recommendation'] = 'SKIP'
            failed = []
            if not checks.get('macd_bullish'):
                failed.append("MACD bearish")
            if not checks.get('ao_positive'):
                failed.append("AO negative")
            if not checks.get('ao_recent_cross'):
                failed.append("No AO zero-cross")
            result['summary'] = f"❌ {', '.join(failed)}"
    
    return result


# =============================================================================
# FORMATTING HELPERS
# =============================================================================

def format_entry_validation(is_valid: bool, checks: Dict) -> str:
    """Format validation results for display"""
    if 'error' in checks:
        return f"❌ Error: {checks['error']}"
    
    status_emoji = "✅" if is_valid else "⚠️"
    
    messages = []
    messages.append(f"{status_emoji} **Entry Validation:**")
    
    check_map = {
        'daily_macd_cross': '📈 Daily MACD crossed up TODAY',
        'ao_positive': '💚 AO > 0',
        'ao_recent_cross': '🔄 AO crossed zero recently',
        'spy_above_200': '📊 SPY above 200 SMA',
        'vix_below_30': '😌 VIX below 30'
    }
    
    for key, label in check_map.items():
        if key in checks:
            emoji = "✅" if checks[key] else "❌"
            extra = ""
            if key == 'ao_recent_cross' and checks.get('ao_cross_date'):
                extra = f" ({checks['ao_cross_date']}, {checks.get('ao_cross_days_ago', '?')}d ago)"
            if key == 'ao_positive' and 'ao_value' in checks:
                extra = f" ({checks['ao_value']:.2f})"
            messages.append(f"  {emoji} {label}{extra}")
    
    if is_valid:
        messages.append("\n🎯 **All entry conditions met!**")
    elif checks.get('valid_relaxed'):
        messages.append("\n🟡 **MACD bullish but no fresh cross today**")
    else:
        messages.append("\n⚠️ **Some conditions not met - proceed with caution**")
    
    return "\n".join(messages)


def format_quality_score(quality: Dict) -> str:
    """Format quality score results for display"""
    if quality.get('error'):
        return f"❌ Quality Error: {quality['error']}"
    
    grade = quality.get('quality_grade', 'N/A')
    score = quality.get('quality_score', 0)
    
    grade_emoji = {
        'A': '🏆',
        'B': '✅',
        'C': '⚠️',
        'F': '❌',
        'N/A': '❓'
    }.get(grade, '❓')
    
    messages = [
        f"{grade_emoji} **Quality Grade: {grade}** (Score: {score}/100)",
        f"",
        f"📊 **Backtest Results:**",
        f"  • Signals Found: {quality.get('signals_found', 0)}",
        f"  • Win Rate: {quality.get('win_rate', 0):.1f}%",
        f"  • Avg Return: {quality.get('avg_return', 0):+.1f}%",
        f"  • Best Trade: {quality.get('best_return', 0):+.1f}%",
        f"  • Worst Trade: {quality.get('worst_return', 0):+.1f}%",
        f"  • Weekly Confirmed: {quality.get('weekly_confirmed_pct', 0):.0f}%"
    ]
    
    return "\n".join(messages)


def get_exit_strategy_note() -> str:
    """Return exit strategy reminder"""
    return """
**TTA Exit Strategy:**

1️⃣ **Protective Stop (15%)**: Exit if price falls 15% below entry

2️⃣ **Weekly MACD Cross**: Exit when Weekly MACD crosses below signal (Wave 3 complete)

3️⃣ **Volatility Trail (20%+)**: If up 20%+, ATR-based trailing stop protects profits

💡 Monitor Weekly MACD in your charting platform for exit signals
"""
