"""
Enhanced Trade Entry Module for TTA Strategy
Auto-fills entry price, calculates stops, validates strategy rules,
and provides quality scoring based on historical backtest performance.

FEATURES:
- AO zero-cross check looks BACKWARDS from signal bar (matches backtester)
- Quality scoring with mini-backtest
- Weekly MACD confirmation check
- LATE ENTRY DETECTION - finds recent crossovers and calculates entry window
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, Tuple, Optional, Any, List
import json
from pathlib import Path


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
# LATE ENTRY DETECTION - Find recent valid crossovers
# =============================================================================

# Late entry configuration
LATE_ENTRY_MAX_DAYS = 5  # Maximum days after crossover to allow entry
LATE_ENTRY_MAX_PREMIUM = 5.0  # Maximum % above crossover price to allow

# =============================================================================
# AO CONFIRMATION SIGNAL - MACD leads, AO confirms later
# =============================================================================
# This catches scenarios where:
#   - MACD crossed up in the last N days (when AO was still negative)
#   - AO just crossed positive TODAY
#   - MACD is still bullish
# This is a DIFFERENT signal type from the primary backtester signal

AO_CONFIRM_MACD_LOOKBACK = 7  # MACD must have crossed within this many days
AO_CONFIRM_MAX_PREMIUM = 8.0  # Max % above MACD cross price to allow


def check_ao_confirmation_signal(ticker: str, macd_lookback: int = 7) -> Dict[str, Any]:
    """
    Check for AO Confirmation signal - MACD leads, AO confirms later.
    
    This catches the scenario where:
    1. MACD crossed up in the last N days (when AO was still negative or barely positive)
    2. AO just crossed from ≤0 to >0 TODAY or in the last 1-2 days
    3. MACD is still bullish (above signal line)
    4. Market filter passes
    
    This is a DIFFERENT signal type from the primary backtester signal.
    
    Returns dict with:
    - is_valid: bool
    - signal_type: 'AO_CONFIRMATION' if valid
    - macd_cross_date: when MACD crossed
    - macd_cross_price: price at MACD cross
    - ao_cross_date: when AO crossed positive
    - ao_cross_days_ago: how recent the AO cross was
    - current_price: current price
    - entry_premium_pct: % above MACD cross price
    - quality: rating based on recency and premium
    """
    result = {
        'is_valid': False,
        'signal_type': None,
        'ticker': ticker.upper(),
        'macd_cross_date': None,
        'macd_cross_price': 0,
        'macd_cross_days_ago': 0,
        'ao_at_macd_cross': 0,
        'ao_cross_date': None,
        'ao_cross_days_ago': 0,
        'current_price': 0,
        'entry_premium_pct': 0,
        'macd_bullish': False,
        'ao_positive': False,
        'ao_value': 0,
        'quality': '❌ No Signal',
        'quality_score': 0,
        'reason': '',
        'recommendation': 'SKIP'
    }
    
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period='3mo', interval='1d')
        
        if hist.empty or len(hist) < 50:
            result['reason'] = 'Insufficient data'
            return result
        
        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = hist.columns.get_level_values(0)
        
        hist = calculate_macd(hist)
        hist = calculate_ao(hist)
        
        i = len(hist) - 1  # Today's index
        
        # Current values
        current_price = float(hist['Close'].iloc[i])
        current_macd = float(hist['MACD'].iloc[i])
        current_signal = float(hist['MACD_Signal'].iloc[i])
        current_ao = float(hist['AO'].iloc[i])
        prev_ao = float(hist['AO'].iloc[i-1]) if i > 0 else 0
        
        result['current_price'] = current_price
        result['macd_bullish'] = current_macd > current_signal
        result['ao_positive'] = current_ao > 0
        result['ao_value'] = round(current_ao, 2)
        
        # Check if MACD is currently bullish
        if not result['macd_bullish']:
            result['reason'] = 'MACD not bullish'
            return result
        
        # Check if AO is positive
        if not result['ao_positive']:
            result['reason'] = 'AO not positive'
            return result
        
        # Find when AO crossed positive (should be recent - TODAY or last 2 days)
        ao_cross_date = None
        ao_cross_days_ago = None
        
        for j in range(3):  # Check today and last 2 days
            check_idx = i - j
            if check_idx < 1:
                break
            
            ao_before = hist['AO'].iloc[check_idx - 1]
            ao_after = hist['AO'].iloc[check_idx]
            
            if ao_before <= 0 and ao_after > 0:
                ao_cross_date = hist.index[check_idx]
                ao_cross_days_ago = j
                break
        
        if ao_cross_date is None:
            result['reason'] = 'AO did not cross positive recently (need within last 2 days)'
            return result
        
        result['ao_cross_date'] = ao_cross_date.strftime('%Y-%m-%d') if hasattr(ao_cross_date, 'strftime') else str(ao_cross_date)
        result['ao_cross_days_ago'] = ao_cross_days_ago
        
        # Find when MACD crossed up (should be within lookback period)
        macd_cross_date = None
        macd_cross_price = 0
        macd_cross_days_ago = 0
        ao_at_macd_cross = 0
        
        for j in range(1, macd_lookback + 1):
            check_idx = i - j
            if check_idx < 1:
                break
            
            check_macd = hist['MACD'].iloc[check_idx]
            check_signal = hist['MACD_Signal'].iloc[check_idx]
            prev_macd = hist['MACD'].iloc[check_idx - 1]
            prev_signal = hist['MACD_Signal'].iloc[check_idx - 1]
            
            # MACD crossed up on this day
            if check_macd > check_signal and prev_macd <= prev_signal:
                macd_cross_date = hist.index[check_idx]
                macd_cross_price = float(hist['Close'].iloc[check_idx])
                macd_cross_days_ago = j
                ao_at_macd_cross = float(hist['AO'].iloc[check_idx])
                break
        
        if macd_cross_date is None:
            result['reason'] = f'No MACD crossover in last {macd_lookback} days'
            return result
        
        # The key check: AO should have been NEGATIVE or barely positive at MACD cross
        # This confirms this is a "MACD leads, AO confirms" scenario
        if ao_at_macd_cross > 2:  # If AO was already solidly positive, the standard signal should have triggered
            result['reason'] = f'AO was already positive ({ao_at_macd_cross:.1f}) at MACD cross - standard signal should apply'
            return result
        
        result['macd_cross_date'] = macd_cross_date.strftime('%Y-%m-%d') if hasattr(macd_cross_date, 'strftime') else str(macd_cross_date)
        result['macd_cross_price'] = round(macd_cross_price, 2)
        result['macd_cross_days_ago'] = macd_cross_days_ago
        result['ao_at_macd_cross'] = round(ao_at_macd_cross, 2)
        
        # Calculate entry premium
        entry_premium = ((current_price - macd_cross_price) / macd_cross_price) * 100
        result['entry_premium_pct'] = round(entry_premium, 2)
        
        # Check premium limit
        if entry_premium > AO_CONFIRM_MAX_PREMIUM:
            result['reason'] = f'Entry premium too high ({entry_premium:.1f}%, max {AO_CONFIRM_MAX_PREMIUM}%)'
            return result
        
        # Check market filter
        spy_above_200, vix_below_30, spy_close, spy_ma200, vix_close = get_market_filter()
        result['spy_above_200'] = spy_above_200
        result['vix_below_30'] = vix_below_30
        
        if not spy_above_200 or not vix_below_30:
            result['reason'] = f"Market filter failed (SPY>200: {spy_above_200}, VIX<30: {vix_below_30})"
            return result
        
        # VALID AO CONFIRMATION SIGNAL!
        result['is_valid'] = True
        result['signal_type'] = 'AO_CONFIRMATION'
        
        # Determine quality based on recency and premium
        if ao_cross_days_ago == 0 and entry_premium < 3:
            result['quality'] = '🟢 Fresh Confirm'
            result['quality_score'] = 90
            result['recommendation'] = 'ENTER'
        elif ao_cross_days_ago <= 1 and entry_premium < 5:
            result['quality'] = '🟢 Good Confirm'
            result['quality_score'] = 80
            result['recommendation'] = 'ENTER'
        elif ao_cross_days_ago <= 2 and entry_premium < 8:
            result['quality'] = '🟡 OK Confirm'
            result['quality_score'] = 65
            result['recommendation'] = 'ENTER WITH CAUTION'
        else:
            result['quality'] = '🟠 Late Confirm'
            result['quality_score'] = 50
            result['recommendation'] = 'SMALLER SIZE'
        
        result['reason'] = f"MACD crossed {macd_cross_days_ago}d ago (AO was {ao_at_macd_cross:.1f}), AO confirmed {ao_cross_days_ago}d ago"
        
        return result
        
    except Exception as e:
        result['reason'] = f'Error: {str(e)}'
        return result


def format_ao_confirmation_signal(result: Dict) -> str:
    """Format AO Confirmation signal for display."""
    if not result.get('is_valid'):
        return f"❌ **No AO Confirmation Signal**\n{result.get('reason', 'Unknown')}"
    
    lines = [
        f"### 🔄 AO Confirmation Signal",
        f"",
        f"**Signal Type:** MACD leads, AO confirms later",
        f"",
        f"**MACD Crossover:**",
        f"- Date: {result.get('macd_cross_date')} ({result.get('macd_cross_days_ago')} days ago)",
        f"- Price: ${result.get('macd_cross_price', 0):.2f}",
        f"- AO at cross: {result.get('ao_at_macd_cross', 0):.2f} (was negative/low)",
        f"",
        f"**AO Confirmation:**",
        f"- Date: {result.get('ao_cross_date')} ({result.get('ao_cross_days_ago')} days ago)",
        f"- Current AO: {result.get('ao_value', 0):.2f}",
        f"",
        f"**Entry:**",
        f"- Current Price: ${result.get('current_price', 0):.2f}",
        f"- Entry Premium: {result.get('entry_premium_pct', 0):+.1f}% vs MACD cross",
        f"",
        f"**Quality: {result.get('quality', 'N/A')}**",
        f"**Recommendation: {result.get('recommendation', 'N/A')}**",
    ]
    
    return "\n".join(lines)


# =============================================================================
# RE-ENTRY SIGNAL CHECK
# =============================================================================
# Handles the case where MACD crosses up while AO is ALREADY positive.
# This is a momentum resumption / re-entry scenario — the trend is established
# (AO positive for a while), MACD pulls back and crosses up again.
# Lower confidence than a fresh AO zero-cross, but still actionable.
# =============================================================================

RE_ENTRY_MACD_LOOKBACK = 10  # Look back up to 10 bars for MACD cross

def check_reentry_signal(ticker: str) -> Dict[str, Any]:
    """
    Check for a re-entry signal: MACD crosses up while AO is already positive.
    
    This covers the gap where:
    - Primary signal fails (no fresh AO zero-cross)
    - AO Confirmation fails (AO was already positive at MACD cross)
    
    Conditions:
    1. MACD crossed up within last 10 bars
    2. MACD is still bullish (above signal) now
    3. AO is positive now
    4. AO has been positive for a while (no recent zero-cross = established trend)
    5. Market filter passes
    """
    result = {
        'is_valid': False,
        'signal_type': 'RE_ENTRY',
        'macd_cross_date': None,
        'macd_cross_price': 0,
        'macd_cross_bars_ago': 0,
        'ao_value': 0,
        'current_price': 0,
        'reason': '',
        'quality': '',
        'quality_score': 0,
        'recommendation': ''
    }
    
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period='6mo', interval='1d')
        
        if len(hist) < 50:
            result['reason'] = 'Insufficient data'
            return result
        
        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = hist.columns.get_level_values(0)
        
        hist = calculate_macd(hist)
        hist = calculate_ao(hist)
        
        i = len(hist) - 1
        current_price = float(hist['Close'].iloc[i])
        result['current_price'] = round(current_price, 2)
        
        current_macd = hist['MACD'].iloc[i]
        current_signal = hist['MACD_Signal'].iloc[i]
        ao_current = float(hist['AO'].iloc[i])
        result['ao_value'] = round(ao_current, 2)
        
        # Condition 1: MACD must be bullish NOW
        if current_macd <= current_signal:
            result['reason'] = 'MACD not bullish (below signal)'
            return result
        
        # Condition 2: AO must be positive NOW
        if ao_current <= 0:
            result['reason'] = 'AO not positive'
            return result
        
        # Condition 3: Find recent MACD cross-up within lookback
        macd_cross_found = False
        for j in range(RE_ENTRY_MACD_LOOKBACK):
            check_idx = i - j
            if check_idx < 1:
                break
            
            check_macd = hist['MACD'].iloc[check_idx]
            check_signal = hist['MACD_Signal'].iloc[check_idx]
            prev_macd = hist['MACD'].iloc[check_idx - 1]
            prev_signal = hist['MACD_Signal'].iloc[check_idx - 1]
            
            if check_macd > check_signal and prev_macd <= prev_signal:
                result['macd_cross_date'] = hist.index[check_idx].strftime('%Y-%m-%d')
                result['macd_cross_price'] = round(float(hist['Close'].iloc[check_idx]), 2)
                result['macd_cross_bars_ago'] = j
                macd_cross_found = True
                break
        
        if not macd_cross_found:
            result['reason'] = f'No MACD crossover in last {RE_ENTRY_MACD_LOOKBACK} bars'
            return result
        
        # Condition 4: Confirm AO has been positive (no recent zero-cross)
        # If there WAS a recent zero-cross, the primary signal should handle it
        ao_had_recent_cross = False
        for j in range(1, 21):
            past_idx = i - j
            if past_idx < 1:
                break
            ao_before = hist['AO'].iloc[past_idx - 1]
            ao_after = hist['AO'].iloc[past_idx]
            if ao_before <= 0 and ao_after > 0:
                ao_had_recent_cross = True
                break
        
        if ao_had_recent_cross:
            result['reason'] = 'AO had recent zero-cross - primary signal should apply'
            return result
        
        # Condition 5: Market filter
        spy_above_200, vix_below_30, spy_close, spy_ma200, vix_close = get_market_filter()
        result['spy_above_200'] = spy_above_200
        result['vix_below_30'] = vix_below_30
        
        if not spy_above_200 or not vix_below_30:
            result['reason'] = f"Market filter failed (SPY>200: {spy_above_200}, VIX<30: {vix_below_30})"
            return result
        
        # VALID RE-ENTRY SIGNAL
        result['is_valid'] = True
        
        # Quality based on recency of MACD cross
        bars_ago = result['macd_cross_bars_ago']
        if bars_ago <= 2:
            result['quality'] = '🟢 Fresh Re-Entry'
            result['quality_score'] = 75
            result['recommendation'] = 'RE-ENTRY'
        elif bars_ago <= 5:
            result['quality'] = '🟡 Recent Re-Entry'
            result['quality_score'] = 65
            result['recommendation'] = 'RE-ENTRY (CAUTIOUS)'
        else:
            result['quality'] = '🟠 Late Re-Entry'
            result['quality_score'] = 55
            result['recommendation'] = 'RE-ENTRY (SMALLER SIZE)'
        
        result['reason'] = f"MACD crossed up {bars_ago}d ago while AO was already positive ({ao_current:.1f})"
        
        return result
    
    except Exception as e:
        result['reason'] = f'Error: {str(e)}'
        return result


def find_recent_crossover(ticker: str, lookback_days: int = 10, entry_window: int = 20) -> Optional[Dict]:
    """
    Find the most recent VALID TTA crossover signal within lookback period.
    
    A valid crossover requires:
    1. MACD crossed above signal on that day
    2. AO was positive on that day
    3. AO had crossed zero in the prior 20 days
    
    Returns dict with crossover details or None if not found.
    """
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period='6mo', interval='1d')
        
        if hist.empty or len(hist) < 50:
            return None
        
        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = hist.columns.get_level_values(0)
        
        hist = calculate_macd(hist)
        hist = calculate_ao(hist)
        
        # Look for crossovers in the last lookback_days
        for days_ago in range(lookback_days + 1):
            i = len(hist) - 1 - days_ago
            
            if i < entry_window + 1:
                continue
            
            # Check for MACD crossover on this day
            current_macd = hist['MACD'].iloc[i]
            current_signal = hist['MACD_Signal'].iloc[i]
            prev_macd = hist['MACD'].iloc[i - 1]
            prev_signal = hist['MACD_Signal'].iloc[i - 1]
            
            macd_cross = (current_macd > current_signal) and (prev_macd <= prev_signal)
            
            if not macd_cross:
                continue
            
            # Check AO > 0 on crossover day
            ao_on_cross = hist['AO'].iloc[i]
            if ao_on_cross <= 0:
                continue
            
            # Check AO crossed zero in prior 20 days
            ao_cross_found = False
            ao_cross_date = None
            for j in range(1, entry_window + 1):
                past_idx = i - j
                if past_idx < 1:
                    break
                if hist['AO'].iloc[past_idx - 1] <= 0 and hist['AO'].iloc[past_idx] > 0:
                    ao_cross_found = True
                    ao_cross_date = hist.index[past_idx]
                    break
            
            if not ao_cross_found:
                continue
            
            # Found a valid crossover!
            crossover_date = hist.index[i]
            crossover_price = float(hist['Close'].iloc[i])
            
            return {
                'crossover_date': crossover_date,
                'crossover_price': crossover_price,
                'days_ago': days_ago,
                'ao_at_crossover': float(ao_on_cross),
                'macd_at_crossover': float(current_macd),
                'signal_at_crossover': float(current_signal),
                'ao_zero_cross_date': ao_cross_date
            }
        
        return None
        
    except Exception as e:
        print(f"Error finding crossover for {ticker}: {e}")
        return None


def check_late_entry_conditions(ticker: str, crossover_info: Dict) -> Dict[str, Any]:
    """
    Check if late entry is still valid given a past crossover.
    
    Returns dict with:
    - is_valid: bool - Can we enter now?
    - quality: str - Entry quality rating
    - days_since_cross: int
    - entry_premium: float - % above crossover price
    - current conditions (MACD, AO, histogram)
    """
    result = {
        'is_valid': False,
        'quality': '❌ Invalid',
        'quality_score': 0,
        'days_since_cross': 0,
        'entry_premium_pct': 0,
        'crossover_date': None,
        'crossover_price': 0,
        'current_price': 0,
        'macd_bullish': False,
        'ao_positive': False,
        'histogram_growing': False,
        'histogram_positive': False,
        'reason': ''
    }
    
    if not crossover_info:
        result['reason'] = 'No recent crossover found'
        return result
    
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period='1mo', interval='1d')
        
        if hist.empty:
            result['reason'] = 'Could not fetch current data'
            return result
        
        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = hist.columns.get_level_values(0)
        
        hist = calculate_macd(hist)
        hist = calculate_ao(hist)
        
        # Current values
        current_price = float(hist['Close'].iloc[-1])
        current_macd = float(hist['MACD'].iloc[-1])
        current_signal = float(hist['MACD_Signal'].iloc[-1])
        current_ao = float(hist['AO'].iloc[-1])
        current_hist = current_macd - current_signal
        prev_hist = float(hist['MACD'].iloc[-2] - hist['MACD_Signal'].iloc[-2]) if len(hist) > 1 else 0
        
        # Calculate metrics
        days_since = crossover_info['days_ago']
        crossover_price = crossover_info['crossover_price']
        entry_premium = ((current_price - crossover_price) / crossover_price) * 100
        
        # Check conditions
        macd_bullish = current_macd > current_signal
        ao_positive = current_ao > 0
        histogram_positive = current_hist > 0
        histogram_growing = current_hist > prev_hist
        
        result['days_since_cross'] = days_since
        result['entry_premium_pct'] = round(entry_premium, 2)
        result['crossover_date'] = crossover_info['crossover_date']
        result['crossover_price'] = crossover_price
        result['current_price'] = current_price
        result['macd_bullish'] = macd_bullish
        result['ao_positive'] = ao_positive
        result['histogram_growing'] = histogram_growing
        result['histogram_positive'] = histogram_positive
        result['current_ao'] = round(current_ao, 2)
        result['current_macd'] = round(current_macd, 4)
        result['current_macd_signal'] = round(current_signal, 4)
        
        # Determine validity and quality
        if days_since > LATE_ENTRY_MAX_DAYS:
            result['reason'] = f'Signal expired ({days_since} days ago, max {LATE_ENTRY_MAX_DAYS})'
            result['quality'] = '❌ Expired'
            result['quality_score'] = 0
            return result
        
        if entry_premium > LATE_ENTRY_MAX_PREMIUM:
            result['reason'] = f'Entry premium too high ({entry_premium:.1f}%, max {LATE_ENTRY_MAX_PREMIUM}%)'
            result['quality'] = '❌ Too Expensive'
            result['quality_score'] = 0
            return result
        
        if not macd_bullish:
            result['reason'] = 'MACD no longer bullish'
            result['quality'] = '❌ MACD Reversed'
            result['quality_score'] = 0
            return result
        
        if not ao_positive:
            result['reason'] = 'AO no longer positive'
            result['quality'] = '❌ AO Negative'
            result['quality_score'] = 0
            return result
        
        # Valid entry - determine quality
        result['is_valid'] = True
        
        if days_since == 0:
            if histogram_growing:
                result['quality'] = '🟢 Perfect'
                result['quality_score'] = 100
            else:
                result['quality'] = '🟢 Strong'
                result['quality_score'] = 90
            result['reason'] = 'Same-day entry, optimal timing'
            
        elif days_since <= 2:
            if histogram_growing and entry_premium < 2:
                result['quality'] = '🟢 Strong'
                result['quality_score'] = 85
            else:
                result['quality'] = '🟢 Good'
                result['quality_score'] = 75
            result['reason'] = f'Day +{days_since}, still strong momentum'
            
        elif days_since <= 3:
            if histogram_positive:
                result['quality'] = '🟡 OK'
                result['quality_score'] = 60
            else:
                result['quality'] = '🟡 Caution'
                result['quality_score'] = 50
            result['reason'] = f'Day +{days_since}, momentum may be fading'
            
        else:  # days 4-5
            result['quality'] = '🟠 Late'
            result['quality_score'] = 40
            result['reason'] = f'Day +{days_since}, reduced edge - consider smaller position'
        
        return result
        
    except Exception as e:
        result['reason'] = f'Error: {str(e)}'
        return result


def get_late_entry_analysis(ticker: str) -> Dict[str, Any]:
    """
    Complete late entry analysis for a ticker.
    
    Returns comprehensive analysis including:
    - Whether there's a recent valid crossover
    - Current entry window status
    - Quality rating
    - Recommendation
    """
    result = {
        'ticker': ticker.upper(),
        'has_recent_signal': False,
        'entry_allowed': False,
        'crossover': None,
        'late_entry': None,
        'recommendation': 'NO SIGNAL',
        'summary': ''
    }
    
    # Find recent crossover
    crossover = find_recent_crossover(ticker)
    
    if not crossover:
        result['summary'] = 'No valid TTA crossover in the last 10 days'
        return result
    
    result['has_recent_signal'] = True
    result['crossover'] = crossover
    
    # Check late entry conditions
    late_entry = check_late_entry_conditions(ticker, crossover)
    result['late_entry'] = late_entry
    
    if late_entry['is_valid']:
        result['entry_allowed'] = True
        
        days = late_entry['days_since_cross']
        quality = late_entry['quality']
        premium = late_entry['entry_premium_pct']
        
        if days == 0:
            result['recommendation'] = 'ENTER NOW'
            result['summary'] = f"✅ Fresh signal TODAY! {quality}"
        elif late_entry['quality_score'] >= 75:
            result['recommendation'] = 'ENTER'
            result['summary'] = f"✅ Day +{days} of 5 | {quality} | Premium: {premium:+.1f}%"
        elif late_entry['quality_score'] >= 50:
            result['recommendation'] = 'ENTER WITH CAUTION'
            result['summary'] = f"🟡 Day +{days} of 5 | {quality} | Premium: {premium:+.1f}%"
        else:
            result['recommendation'] = 'REDUCE SIZE'
            result['summary'] = f"🟠 Day +{days} of 5 | {quality} | Consider smaller position"
    else:
        result['recommendation'] = 'DO NOT ENTER'
        result['summary'] = f"❌ {late_entry['reason']}"
    
    return result


def format_late_entry_status(analysis: Dict) -> str:
    """Format late entry analysis for display"""
    if not analysis.get('has_recent_signal'):
        return "📭 **No Recent Signal**\nNo valid TTA crossover in the last 10 days."
    
    crossover = analysis.get('crossover', {})
    late = analysis.get('late_entry', {})
    
    cross_date = crossover.get('crossover_date')
    if hasattr(cross_date, 'strftime'):
        cross_date_str = cross_date.strftime('%Y-%m-%d')
    else:
        cross_date_str = str(cross_date)
    
    lines = [
        f"### 📊 Late Entry Analysis",
        f"",
        f"**Crossover Signal:**",
        f"- Date: {cross_date_str}",
        f"- Price: ${crossover.get('crossover_price', 0):.2f}",
        f"- AO at cross: {crossover.get('ao_at_crossover', 0):.2f}",
        f"",
        f"**Current Status (Day +{late.get('days_since_cross', 0)} of {LATE_ENTRY_MAX_DAYS}):**",
        f"- Current Price: ${late.get('current_price', 0):.2f}",
        f"- Entry Premium: {late.get('entry_premium_pct', 0):+.1f}%",
        f"- MACD Bullish: {'✅' if late.get('macd_bullish') else '❌'}",
        f"- AO Positive: {'✅' if late.get('ao_positive') else '❌'}",
        f"- Histogram Growing: {'✅' if late.get('histogram_growing') else '❌'}",
        f"",
        f"**Quality: {late.get('quality', 'N/A')}**",
        f"",
        f"**Recommendation: {analysis.get('recommendation', 'N/A')}**",
        f"{analysis.get('summary', '')}"
    ]
    
    return "\n".join(lines)


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
        # CHECK 1: MACD crossover within recent bars (not just today)
        # v16.37 FIX: A cross 2-3 bars ago is still actionable
        # =================================================================
        current_macd = hist['MACD'].iloc[i]
        current_signal = hist['MACD_Signal'].iloc[i]
        prev_macd = hist['MACD'].iloc[i - 1]
        prev_signal = hist['MACD_Signal'].iloc[i - 1]
        
        # Check for cross on current bar first
        macd_cross_today = (current_macd > current_signal) and (prev_macd <= prev_signal)
        
        # Also check last 10 bars for a recent cross (still actionable)
        macd_cross_recent = False
        macd_cross_bars_ago = 0
        for lookback in range(10):
            check_idx = i - lookback
            if check_idx < 1:
                break
            check_macd = hist['MACD'].iloc[check_idx]
            check_signal = hist['MACD_Signal'].iloc[check_idx]
            prev_check_macd = hist['MACD'].iloc[check_idx - 1]
            prev_check_signal = hist['MACD_Signal'].iloc[check_idx - 1]
            
            if (check_macd > check_signal) and (prev_check_macd <= prev_check_signal):
                macd_cross_recent = True
                macd_cross_bars_ago = lookback
                break
        
        # Use recent cross (within 5 bars) as the primary check
        macd_cross = macd_cross_recent and (current_macd > current_signal)  # Must still be bullish now
        checks['daily_macd_cross'] = macd_cross
        checks['macd_cross_today'] = macd_cross_today  # Exact today for strict backtester compatibility
        checks['macd_cross_bars_ago'] = macd_cross_bars_ago
        
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
    1. Current entry signal validation (primary backtester signal)
    2. AO Confirmation signal check (MACD leads, AO confirms)
    3. Weekly confirmation status
    4. Quality score from backtest
    
    Returns comprehensive analysis dict.
    """
    result = {
        'ticker': ticker.upper(),
        'timestamp': datetime.now().isoformat(),
        'current_price': None,
        'entry_signal': {},
        'ao_confirmation': {},  # AO Confirmation signal
        'reentry': {},  # RE-ENTRY signal (MACD cross while AO already positive)
        'weekly_status': {},
        'quality': {},
        'recommendation': 'SKIP',
        'signal_type': None,  # 'PRIMARY', 'AO_CONFIRMATION', 'RE_ENTRY', or None
        'summary': ''
    }
    
    # Get current price
    result['current_price'] = fetch_current_price(ticker)
    
    # Check primary entry conditions (backtester signal)
    is_valid, checks = validate_entry_conditions(ticker)
    result['entry_signal'] = {
        'is_valid': is_valid,
        'checks': checks
    }
    
    # If primary signal is not valid, check for AO Confirmation signal
    ao_confirm = None
    reentry = None
    if not is_valid:
        ao_confirm = check_ao_confirmation_signal(ticker)
        result['ao_confirmation'] = ao_confirm
        
        # If AO confirmation also fails, check for re-entry signal
        if not ao_confirm or not ao_confirm.get('is_valid'):
            reentry = check_reentry_signal(ticker)
            result['reentry'] = reentry
    
    # Check weekly confirmation
    result['weekly_status'] = check_weekly_confirmation(ticker)
    
    # Calculate quality score
    result['quality'] = calculate_quality_score(ticker)
    
    # Generate recommendation
    quality_grade = result['quality'].get('quality_grade', 'N/A')
    weekly_bullish = result['weekly_status'].get('weekly_bullish', False)
    
    if is_valid:
        # PRIMARY SIGNAL - backtester criteria met
        result['signal_type'] = 'PRIMARY'
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
    
    elif ao_confirm and ao_confirm.get('is_valid'):
        # AO CONFIRMATION SIGNAL - MACD led, AO confirmed
        result['signal_type'] = 'AO_CONFIRMATION'
        ao_quality = ao_confirm.get('quality_score', 0)
        ao_rec = ao_confirm.get('recommendation', 'SKIP')
        
        if quality_grade in ['A', 'B'] and ao_quality >= 80:
            if weekly_bullish:
                result['recommendation'] = 'BUY (AO CONFIRM)'
                result['summary'] = f"🔄 AO Confirmation signal, Weekly bullish, Quality {quality_grade}"
            else:
                result['recommendation'] = 'CAUTION BUY (AO CONFIRM)'
                result['summary'] = f"🔄 AO Confirmation signal, Quality {quality_grade}, Weekly pending"
        elif quality_grade in ['A', 'B', 'C'] and ao_quality >= 65:
            result['recommendation'] = 'WATCH (AO CONFIRM)'
            result['summary'] = f"🟡 AO Confirmation - {ao_confirm.get('quality', 'OK')}, Quality {quality_grade}"
        else:
            result['recommendation'] = 'SKIP'
            result['summary'] = f"⚠️ AO Confirmation but weak ({ao_confirm.get('reason', '')})"
    
    elif reentry and reentry.get('is_valid'):
        # RE-ENTRY SIGNAL - MACD crossed while AO already positive
        result['signal_type'] = 'RE_ENTRY'
        re_quality = reentry.get('quality_score', 0)
        bars_ago = reentry.get('macd_cross_bars_ago', 0)
        
        if quality_grade in ['A', 'B'] and weekly_bullish:
            result['recommendation'] = 'RE-ENTRY'
            result['summary'] = f"🔁 Re-Entry signal ({bars_ago}d ago), Weekly bullish, Quality {quality_grade}"
        elif quality_grade in ['A', 'B']:
            result['recommendation'] = 'RE-ENTRY (CAUTIOUS)'
            result['summary'] = f"🔁 Re-Entry signal ({bars_ago}d ago), Quality {quality_grade}, Weekly pending"
        else:
            result['recommendation'] = 'WATCH (RE-ENTRY)'
            result['summary'] = f"🟡 Re-Entry signal but Quality {quality_grade}"
    
    else:
        # No signal
        result['signal_type'] = None
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


# =============================================================================
# AI TRADE NARRATIVE - GPT-powered trade assessment
# =============================================================================

def build_trade_context(ticker: str) -> Dict[str, Any]:
    """
    Build comprehensive trade context for AI narrative.
    Gathers all signal data, quality metrics, and market context.
    """
    context = {
        'ticker': ticker.upper(),
        'timestamp': datetime.now().isoformat(),
        'data_available': True
    }
    
    try:
        # Get full analysis
        analysis = analyze_ticker_full(ticker)
        context['analysis'] = analysis
        
        # Current price and ATR
        current_price = fetch_current_price(ticker)
        atr = calculate_atr_value(ticker)
        stop_loss, stop_type = calculate_strategy_stops(current_price, atr) if current_price else (0, 'N/A')
        target = current_price * 1.20 if current_price else 0
        
        context['trade_setup'] = {
            'current_price': current_price,
            'atr': atr,
            'stop_loss': stop_loss,
            'stop_type': stop_type,
            'target': target,
            'risk_pct': ((current_price - stop_loss) / current_price * 100) if current_price and stop_loss else 0,
            'reward_pct': 20.0,
            'risk_reward': ((target - current_price) / (current_price - stop_loss)) if current_price and stop_loss and current_price > stop_loss else 0
        }
        
        # Entry signal details
        entry = analysis.get('entry_signal', {})
        context['primary_signal'] = {
            'is_valid': entry.get('is_valid', False),
            'macd_cross': entry.get('checks', {}).get('daily_macd_cross', False),
            'macd_bullish': entry.get('checks', {}).get('macd_bullish', False),
            'ao_positive': entry.get('checks', {}).get('ao_positive', False),
            'ao_value': entry.get('checks', {}).get('ao_value', 0),
            'ao_recent_cross': entry.get('checks', {}).get('ao_recent_cross', False),
            'ao_cross_days_ago': entry.get('checks', {}).get('ao_cross_days_ago'),
        }
        
        # AO Confirmation signal
        ao_confirm = analysis.get('ao_confirmation', {})
        context['ao_confirmation'] = {
            'is_valid': ao_confirm.get('is_valid', False),
            'macd_cross_date': str(ao_confirm.get('macd_cross_date', '')),
            'macd_cross_days_ago': ao_confirm.get('macd_cross_days_ago', 0),
            'macd_cross_price': ao_confirm.get('macd_cross_price', 0),
            'ao_at_macd_cross': ao_confirm.get('ao_at_macd_cross', 0),
            'ao_cross_date': str(ao_confirm.get('ao_cross_date', '')),
            'ao_cross_days_ago': ao_confirm.get('ao_cross_days_ago'),
            'entry_premium_pct': ao_confirm.get('entry_premium_pct', 0),
            'quality': ao_confirm.get('quality', ''),
            'quality_score': ao_confirm.get('quality_score', 0),
        }
        
        # Weekly confirmation  
        weekly = analysis.get('weekly_status', {})
        context['weekly'] = {
            'bullish': weekly.get('weekly_bullish', False),
            'signal_type': weekly.get('signal_type', 'N/A'),
        }
        
        # Quality score
        quality = analysis.get('quality', {})
        context['quality'] = {
            'grade': quality.get('quality_grade', 'N/A'),
            'score': quality.get('quality_score', 0),
            'win_rate': quality.get('win_rate', 0),
            'avg_return': quality.get('avg_return', 0),
            'signals_found': quality.get('signals_found', 0),
            'best_return': quality.get('best_return', 0),
            'worst_return': quality.get('worst_return', 0),
        }
        
        # Signal type and recommendation
        context['signal_type'] = analysis.get('signal_type')
        context['system_recommendation'] = analysis.get('recommendation', 'SKIP')
        context['summary'] = analysis.get('summary', '')
        
    except Exception as e:
        context['data_available'] = False
        context['error'] = str(e)
    
    return context


def generate_ai_trade_narrative(ticker: str, openai_client=None, gemini_model=None) -> Dict[str, Any]:
    """
    Generate an AI-powered trade narrative using Google Gemini (preferred) or OpenAI.
    
    Args:
        ticker: Stock ticker to analyze
        openai_client: OpenAI client instance (fallback)
        gemini_model: Google Gemini model instance (preferred)
    
    Returns:
        Dict with narrative, recommendation, and metadata
    """
    result = {
        'ticker': ticker.upper(),
        'narrative': '',
        'recommendation': '',
        'confidence': '',
        'key_factors': [],
        'concerns': [],
        'success': False,
        'error': None,
        'provider': None
    }
    
    # Build context
    context = build_trade_context(ticker)
    
    if not context.get('data_available'):
        result['error'] = context.get('error', 'Failed to fetch trade data')
        return result
    
    # Create the prompt
    prompt = f"""You are a professional trade analyst providing a concise trade assessment for the TTA (Trend Trading with AO) strategy.

TICKER: {context['ticker']}

CURRENT SIGNAL DATA:
- Signal Type: {context['signal_type']}
- System Recommendation: {context['system_recommendation']}

PRIMARY SIGNAL (Strict Backtester):
- Valid: {context['primary_signal']['is_valid']}
- MACD Cross Today: {context['primary_signal']['macd_cross']}
- MACD Bullish: {context['primary_signal']['macd_bullish']}
- AO Positive: {context['primary_signal']['ao_positive']} (Value: {context['primary_signal']['ao_value']:.2f})
- AO Recent Cross: {context['primary_signal']['ao_recent_cross']} ({context['primary_signal']['ao_cross_days_ago']} days ago)

AO CONFIRMATION SIGNAL (MACD leads, AO confirms):
- Valid: {context['ao_confirmation']['is_valid']}
- MACD Crossed: {context['ao_confirmation']['macd_cross_date']} ({context['ao_confirmation']['macd_cross_days_ago']} days ago)
- MACD Cross Price: ${context['ao_confirmation']['macd_cross_price']:.2f}
- AO at MACD Cross: {context['ao_confirmation']['ao_at_macd_cross']:.2f}
- AO Confirmed: {context['ao_confirmation']['ao_cross_date']} ({context['ao_confirmation']['ao_cross_days_ago']} days ago)
- Entry Premium: {context['ao_confirmation']['entry_premium_pct']:+.1f}%
- Quality: {context['ao_confirmation']['quality']}

WEEKLY CONFIRMATION:
- Weekly MACD Bullish: {context['weekly']['bullish']}
- Signal Type: {context['weekly']['signal_type']}

QUALITY SCORE (Historical Backtest):
- Grade: {context['quality']['grade']}
- Score: {context['quality']['score']}/100
- Win Rate: {context['quality']['win_rate']:.0f}%
- Avg Return: {context['quality']['avg_return']:+.1f}%
- Historical Signals: {context['quality']['signals_found']}

TRADE SETUP:
- Current Price: ${context['trade_setup']['current_price']:.2f}
- Stop Loss ({context['trade_setup']['stop_type']}): ${context['trade_setup']['stop_loss']:.2f} ({context['trade_setup']['risk_pct']:.1f}% risk)
- Target (20%): ${context['trade_setup']['target']:.2f}
- ATR(14): ${context['trade_setup']['atr']:.2f}
- Risk/Reward: 1:{context['trade_setup']['risk_reward']:.1f}

Please provide a trade narrative with:
1. A 2-3 sentence SUMMARY of the setup
2. YOUR RECOMMENDATION: One of [STRONG BUY, BUY, CAUTIOUS ENTRY, WATCH, SKIP]
3. CONFIDENCE: One of [HIGH, MEDIUM, LOW]
4. KEY FACTORS (2-3 bullet points supporting the trade)
5. CONCERNS (1-3 bullet points of risks/cautions)
6. POSITION SIZE GUIDANCE (based on conviction level)

Keep the response concise and actionable. Be honest about risks.
Format your response with clear headers."""

    # Check if no AI is available
    if gemini_model is None and openai_client is None:
        # Return a structured assessment without AI
        result['narrative'] = _generate_fallback_narrative(context)
        result['recommendation'] = context['system_recommendation']
        result['confidence'] = 'MEDIUM'
        result['success'] = True
        result['provider'] = 'system'
        result['note'] = 'Using system analysis (no AI configured)'
        return result
    
    narrative = None
    
    # Try Gemini first (preferred)
    if gemini_model is not None:
        try:
            response = gemini_model.generate_content(
                f"You are a professional trade analyst. Be concise, honest, and actionable.\n\n{prompt}"
            )
            narrative = response.text
            result['provider'] = 'gemini'
        except Exception as e:
            error_str = str(e)
            # Log but continue to try OpenAI
            result['gemini_error'] = error_str[:100]
    
    # Try OpenAI if Gemini failed or unavailable
    if narrative is None and openai_client is not None:
        try:
            response = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a professional trade analyst. Be concise, honest, and actionable."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=800,
                temperature=0.7
            )
            narrative = response.choices[0].message.content
            result['provider'] = 'openai'
        except Exception as e:
            error_str = str(e)
            result['openai_error'] = error_str[:100]
    
    # If we got a narrative, parse it
    if narrative:
        result['narrative'] = narrative
        result['success'] = True
        
        # Parse recommendation from narrative
        if 'STRONG BUY' in narrative.upper():
            result['recommendation'] = 'STRONG BUY'
            result['confidence'] = 'HIGH'
        elif 'CAUTIOUS ENTRY' in narrative.upper():
            result['recommendation'] = 'CAUTIOUS ENTRY'
            result['confidence'] = 'MEDIUM'
        elif 'BUY' in narrative.upper() and 'SKIP' not in narrative.upper():
            result['recommendation'] = 'BUY'
            result['confidence'] = 'MEDIUM'
        elif 'WATCH' in narrative.upper():
            result['recommendation'] = 'WATCH'
            result['confidence'] = 'LOW'
        else:
            result['recommendation'] = 'SKIP'
            result['confidence'] = 'LOW'
    else:
        # Both APIs failed, use fallback
        result['narrative'] = _generate_fallback_narrative(context)
        result['recommendation'] = context['system_recommendation']
        result['confidence'] = 'MEDIUM'
        result['success'] = True
        result['provider'] = 'system'
        
        # Build error message
        errors = []
        if result.get('gemini_error'):
            if '429' in result['gemini_error'] or 'quota' in result['gemini_error'].lower():
                errors.append('Gemini: Rate limit')
            else:
                errors.append('Gemini unavailable')
        if result.get('openai_error'):
            if '429' in result['openai_error']:
                errors.append('OpenAI: Rate limit')
            else:
                errors.append('OpenAI unavailable')
        result['note'] = f"Using system analysis ({', '.join(errors) if errors else 'AI unavailable'})"
    
    return result


def _generate_fallback_narrative(context: Dict) -> str:
    """Generate a narrative without AI based on the context data."""
    ticker = context['ticker']
    signal_type = context['signal_type']
    rec = context['system_recommendation']
    
    # Build narrative
    lines = []
    lines.append(f"## 📊 Trade Assessment: {ticker}")
    lines.append("")
    
    # Summary based on signal type
    if signal_type == 'PRIMARY':
        lines.append(f"**Signal:** ✅ PRIMARY (Backtester confirmed)")
        lines.append(f"MACD crossed up today with AO positive - this is the standard TTA entry signal.")
    elif signal_type == 'AO_CONFIRMATION':
        ao = context['ao_confirmation']
        lines.append(f"**Signal:** 🔄 AO CONFIRMATION (MACD led, AO confirmed)")
        lines.append(f"MACD crossed {ao['macd_cross_days_ago']} days ago at ${ao['macd_cross_price']:.2f}. ")
        lines.append(f"AO just confirmed positive {ao['ao_cross_days_ago']} day(s) ago.")
        lines.append(f"Entry premium: {ao['entry_premium_pct']:+.1f}%")
    else:
        lines.append(f"**Signal:** ❌ No valid entry signal")
        lines.append(f"Neither PRIMARY nor AO CONFIRMATION criteria met.")
    
    lines.append("")
    lines.append(f"**Recommendation:** {rec}")
    
    # Weekly status
    lines.append("")
    weekly = "🟢 Bullish (Re-Entry)" if context['weekly']['bullish'] else "🔴 Bearish (New Wave)"
    lines.append(f"**Weekly MACD:** {weekly}")
    
    # Quality
    q = context['quality']
    lines.append("")
    lines.append(f"**Quality:** Grade {q['grade']} ({q['win_rate']:.0f}% win rate, {q['avg_return']:+.1f}% avg return)")
    
    # Trade setup
    ts = context['trade_setup']
    lines.append("")
    lines.append(f"**Trade Setup:**")
    lines.append(f"- Entry: ${ts['current_price']:.2f}")
    lines.append(f"- Stop: ${ts['stop_loss']:.2f} ({ts['risk_pct']:.1f}% risk)")
    lines.append(f"- Target: ${ts['target']:.2f} (20% gain)")
    lines.append(f"- R:R = 1:{ts['risk_reward']:.1f}")
    
    # Key factors and concerns
    lines.append("")
    lines.append("**Key Factors:**")
    if context['primary_signal']['is_valid'] or context['ao_confirmation']['is_valid']:
        lines.append("- ✅ Valid entry signal")
    if q['grade'] in ['A', 'B']:
        lines.append(f"- ✅ Good quality (Grade {q['grade']})")
    if context['weekly']['bullish']:
        lines.append("- ✅ Weekly trend confirmed")
    
    lines.append("")
    lines.append("**Concerns:**")
    if context['ao_confirmation']['entry_premium_pct'] > 5:
        lines.append(f"- ⚠️ High entry premium ({context['ao_confirmation']['entry_premium_pct']:+.1f}%)")
    if not context['weekly']['bullish']:
        lines.append("- ⚠️ Weekly MACD bearish - New Wave bet")
    if q['grade'] not in ['A', 'B']:
        lines.append(f"- ⚠️ Quality grade {q['grade']}")
    
    return "\n".join(lines)


def format_ai_narrative_for_display(result: Dict) -> str:
    """Format AI narrative result for Streamlit display."""
    if result.get('error') and not result.get('success'):
        return f"❌ **Error:** {result['error']}"
    
    lines = []
    
    # Header
    lines.append(f"## 🤖 AI Trade Assessment: {result['ticker']}")
    lines.append("")
    
    # Recommendation badge
    rec = result.get('recommendation', 'SKIP')
    conf = result.get('confidence', 'LOW')
    
    rec_emoji = {
        'STRONG BUY': '🟢',
        'BUY': '🟢',
        'CAUTIOUS ENTRY': '🟠',
        'WATCH': '🟡',
        'SKIP': '🔴'
    }.get(rec, '⚪')
    
    lines.append(f"### {rec_emoji} {rec} (Confidence: {conf})")
    lines.append("")
    
    # Narrative
    lines.append(result.get('narrative', 'No narrative available.'))
    
    # Note if fallback was used
    if result.get('note'):
        lines.append("")
        lines.append(f"*{result['note']}*")
    
    return "\n".join(lines)
