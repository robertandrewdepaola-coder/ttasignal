"""
Weinstein Break-and-Retest 30-Week SMA Continuation Strategy
============================================================

Detects and trades strong continuation moves where:
1. Price rapidly breaks up from below a rising 30-week SMA into Stage 2
2. After initial break, price pulls back toward SMA, finds support
3. Price moves back up and breaks through the prior swing high
4. Long trade opens only on that second break above prior high

Multi-cycle capable: allows pattern to trigger multiple times per ticker.
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION - All tunable parameters
# ═══════════════════════════════════════════════════════════════════════════════

DEFAULT_CONFIG = {
    # SMA settings
    'sma_length': 30,
    'sma_rising_lookback': 4,  # weeks to check if SMA is rising
    
    # Initial breakout (Point A)
    'rapid_break_min_pct': 0.03,  # 3% above SMA minimum for valid breakout
    
    # Pullback/Retest (Point B)
    'pullback_buffer': 0.02,  # 2% band around SMA for "touch"
    'max_allowed_sma_closes_below': 1,  # max bars closing below SMA
    'max_below_sma_pct': 0.03,  # max % below SMA before invalidation
    'max_pullback_pct_from_breakout': 0.20,  # 20% max drawdown from breakout high
    
    # Continuation trigger (Point C)
    'entry_close_vs_high_tolerance_pct': 0.01,  # 1% tolerance for breakout confirmation
    
    # Trade management
    'stop_buffer_pct': 0.02,  # 2% below retest low for stop
    'exit_mode': 'SMA',  # 'RR' | 'SMA' | 'TRAIL'
    'rr_target': 3.0,  # Risk:Reward target for RR mode
    'trail_atr_mult': 2.0,  # ATR multiplier for trailing stop
    'trail_atr_length': 14,  # ATR period for trailing stop
    
    # Entry timing
    'entry_on_close': True,  # True = enter on signal bar close, False = next bar open
}


# ═══════════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class PatternState:
    """Tracks current pattern detection state"""
    active: bool = False
    breakout_bar_idx: Optional[int] = None
    breakout_date: Optional[datetime] = None
    breakout_high: float = 0.0
    breakout_close: float = 0.0
    retest_active: bool = False
    retest_low: float = float('inf')
    retest_low_date: Optional[datetime] = None
    closes_below_sma: int = 0
    support_confirmed: bool = False
    support_confirmed_date: Optional[datetime] = None
    invalidated: bool = False
    invalidation_reason: str = ""


@dataclass
class Trade:
    """Represents a single trade"""
    ticker: str
    entry_date: datetime
    entry_price: float
    stop_loss: float
    breakout_date: datetime
    breakout_high: float
    retest_low: float
    retest_date: datetime
    exit_date: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: str = ""
    r_multiple: float = 0.0
    pnl_pct: float = 0.0


@dataclass
class PatternLog:
    """Logs a detected pattern (whether traded or invalidated)"""
    ticker: str
    breakout_date: datetime
    breakout_high: float
    retest_low: float
    retest_date: datetime
    support_confirmed: bool
    support_confirmed_date: Optional[datetime]
    outcome: str  # 'TRADED' | 'INVALIDATED' | 'PENDING'
    invalidation_reason: str = ""
    trade: Optional[Trade] = None


@dataclass
class BacktestResult:
    """Complete backtest results for a ticker"""
    ticker: str
    patterns_detected: int = 0
    trades_taken: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    avg_r: float = 0.0
    total_r: float = 0.0
    max_drawdown: float = 0.0
    total_return_pct: float = 0.0
    trades: List[Trade] = field(default_factory=list)
    pattern_logs: List[PatternLog] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def compute_sma(df: pd.DataFrame, length: int) -> pd.Series:
    """Compute Simple Moving Average on Close"""
    return df['Close'].rolling(window=length).mean()


def compute_atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    """Compute Average True Range"""
    high = df['High']
    low = df['Low']
    close = df['Close']
    
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=length).mean()


def is_sma_rising(df: pd.DataFrame, sma: pd.Series, idx: int, lookback: int) -> bool:
    """Check if SMA is rising over lookback period"""
    if idx < lookback:
        return False
    current_sma = sma.iloc[idx]
    prior_sma = sma.iloc[idx - lookback]
    return current_sma > prior_sma


def is_stage_2(close: float, sma_value: float, sma_rising: bool) -> bool:
    """Check if bar qualifies as Stage 2 candidate"""
    return close > sma_value and sma_rising


def is_stage_4(close: float, sma_value: float, sma_rising: bool) -> bool:
    """Check if bar qualifies as Stage 4 (invalidation)"""
    return close < sma_value and not sma_rising


# ═══════════════════════════════════════════════════════════════════════════════
# PATTERN DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

def detect_initial_breakout(
    df: pd.DataFrame,
    sma: pd.Series,
    idx: int,
    config: Dict
) -> Optional[Dict]:
    """
    Detect Initial Breakout (Point A)
    
    Conditions:
    - Previous bar close was below SMA
    - Current bar close is above SMA by at least rapid_break_min_pct
    - SMA is rising
    """
    if idx < config['sma_rising_lookback'] + 1:
        return None
    
    prev_close = df['Close'].iloc[idx - 1]
    curr_close = df['Close'].iloc[idx]
    curr_high = df['High'].iloc[idx]
    curr_sma = sma.iloc[idx]
    prev_sma = sma.iloc[idx - 1]
    
    # Check SMA is rising
    if not is_sma_rising(df, sma, idx, config['sma_rising_lookback']):
        return None
    
    # Previous close was below SMA
    if prev_close >= prev_sma:
        return None
    
    # Current close is above SMA
    if curr_close <= curr_sma:
        return None
    
    # Check "rapid" break - must be at least X% above SMA
    pct_above_sma = (curr_close - curr_sma) / curr_sma
    if pct_above_sma < config['rapid_break_min_pct']:
        return None
    
    # Valid breakout detected
    return {
        'idx': idx,
        'date': df.index[idx],
        'high': curr_high,
        'close': curr_close,
        'sma': curr_sma,
        'pct_above_sma': pct_above_sma
    }


def update_retest_state(
    df: pd.DataFrame,
    sma: pd.Series,
    idx: int,
    state: PatternState,
    config: Dict
) -> PatternState:
    """
    Update Pullback/Retest (Point B) state
    
    Tracks:
    - Pullback toward SMA
    - Closes below SMA count
    - Support confirmation
    - Invalidation conditions
    """
    curr_close = df['Close'].iloc[idx]
    curr_low = df['Low'].iloc[idx]
    curr_high = df['High'].iloc[idx]
    curr_sma = sma.iloc[idx]
    curr_date = df.index[idx]
    
    # Track retest low
    if curr_low < state.retest_low:
        state.retest_low = curr_low
        state.retest_low_date = curr_date
    
    # Track closes below SMA (for logging, not invalidation)
    if curr_close < curr_sma:
        state.closes_below_sma += 1
    
    # NOTE: We do NOT invalidate on deep pullbacks or closes below SMA
    # The pattern remains valid as long as price eventually recovers and breaks the prior high
    # Only Stage 4 (trend reversal with declining SMA) truly invalidates the pattern
    
    # Check for pullback "touch" of SMA zone (for support confirmation)
    pullback_buffer = config['pullback_buffer']
    sma_upper_band = curr_sma * (1 + pullback_buffer)
    
    # Price touched or went below SMA zone at some point
    touched_sma_zone = curr_low <= sma_upper_band
    
    # Support confirmation: price recovers and closes back above SMA
    if touched_sma_zone and not state.support_confirmed:
        if curr_close > curr_sma:
            state.support_confirmed = True
            state.support_confirmed_date = curr_date
    
    # Check for Stage 4 transition (trend reversal)
    sma_rising = is_sma_rising(df, sma, idx, config['sma_rising_lookback'])
    if is_stage_4(curr_close, curr_sma, sma_rising):
        state.invalidated = True
        state.invalidation_reason = "Stage 4 detected - trend reversal"
    
    return state


def check_continuation_trigger(
    df: pd.DataFrame,
    idx: int,
    state: PatternState,
    config: Dict
) -> bool:
    """
    Check Continuation Trigger (Point C)
    
    Entry signal when:
    - support_confirmed == True
    - Weekly close breaks above breakout_high (or high breaks with close near)
    """
    if not state.support_confirmed:
        return False
    
    curr_close = df['Close'].iloc[idx]
    curr_high = df['High'].iloc[idx]
    
    tolerance = config['entry_close_vs_high_tolerance_pct']
    
    # Close above breakout high
    if curr_close > state.breakout_high:
        return True
    
    # High breaks above with close within tolerance
    if curr_high > state.breakout_high:
        breakout_range = state.breakout_high - state.retest_low
        if breakout_range > 0:
            close_vs_high = (curr_high - curr_close) / breakout_range
            if close_vs_high <= tolerance:
                return True
    
    return False


# ═══════════════════════════════════════════════════════════════════════════════
# TRADE MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════

def calculate_stop_loss(retest_low: float, config: Dict) -> float:
    """Calculate initial stop loss based on retest low"""
    return retest_low * (1 - config['stop_buffer_pct'])


def calculate_rr_target(entry_price: float, stop_loss: float, config: Dict) -> float:
    """Calculate take profit based on Risk:Reward ratio"""
    risk = entry_price - stop_loss
    return entry_price + (risk * config['rr_target'])


def check_exit_conditions(
    df: pd.DataFrame,
    sma: pd.Series,
    atr: pd.Series,
    idx: int,
    trade: Trade,
    config: Dict,
    highest_close: float
) -> Optional[Tuple[str, float]]:
    """
    Check exit conditions based on exit_mode
    
    Returns: (exit_reason, exit_price) or None if no exit
    """
    curr_close = df['Close'].iloc[idx]
    curr_low = df['Low'].iloc[idx]
    curr_sma = sma.iloc[idx]
    curr_atr = atr.iloc[idx] if not pd.isna(atr.iloc[idx]) else 0
    
    exit_mode = config['exit_mode']
    
    # Always check stop loss first
    if curr_low <= trade.stop_loss:
        return ('STOP_LOSS', trade.stop_loss)
    
    if exit_mode == 'RR':
        # Risk:Reward target
        target = calculate_rr_target(trade.entry_price, trade.stop_loss, config)
        if curr_close >= target:
            return ('RR_TARGET', curr_close)
    
    elif exit_mode == 'SMA':
        # Weekly close below SMA
        if curr_close < curr_sma:
            return ('SMA_BREAK', curr_close)
    
    elif exit_mode == 'TRAIL':
        # Trailing stop based on ATR
        if highest_close > 0 and curr_atr > 0:
            trail_stop = highest_close - (curr_atr * config['trail_atr_mult'])
            if curr_close < trail_stop:
                return ('TRAILING_STOP', curr_close)
    
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN STRATEGY FUNCTION
# ═══════════════════════════════════════════════════════════════════════════════

def strategy_break_retest_30w_sma(
    df: pd.DataFrame,
    ticker: str,
    config: Optional[Dict] = None
) -> BacktestResult:
    """
    Main strategy function - detects and trades Weinstein break-and-retest patterns
    
    Args:
        df: Weekly OHLCV DataFrame with DatetimeIndex
        ticker: Stock symbol
        config: Strategy parameters (uses DEFAULT_CONFIG if None)
    
    Returns:
        BacktestResult with all trades and statistics
    """
    if config is None:
        config = DEFAULT_CONFIG.copy()
    else:
        # Merge with defaults
        merged = DEFAULT_CONFIG.copy()
        merged.update(config)
        config = merged
    
    # Initialize result
    result = BacktestResult(ticker=ticker)
    
    # Compute indicators
    sma = compute_sma(df, config['sma_length'])
    atr = compute_atr(df, config['trail_atr_length'])
    
    # State tracking
    state = PatternState()
    active_trade: Optional[Trade] = None
    highest_close_since_entry = 0.0
    
    # Scan through data
    for idx in range(config['sma_length'] + config['sma_rising_lookback'], len(df)):
        curr_date = df.index[idx]
        curr_close = df['Close'].iloc[idx]
        curr_sma = sma.iloc[idx]
        
        if pd.isna(curr_sma):
            continue
        
        # ═══════════════════════════════════════════════════════════════════
        # TRADE MANAGEMENT - Check exits first
        # ═══════════════════════════════════════════════════════════════════
        if active_trade is not None:
            highest_close_since_entry = max(highest_close_since_entry, curr_close)
            
            exit_result = check_exit_conditions(
                df, sma, atr, idx, active_trade, config, highest_close_since_entry
            )
            
            if exit_result:
                exit_reason, exit_price = exit_result
                active_trade.exit_date = curr_date
                active_trade.exit_price = exit_price
                active_trade.exit_reason = exit_reason
                
                # Calculate R-multiple and PnL
                risk = active_trade.entry_price - active_trade.stop_loss
                if risk > 0:
                    active_trade.r_multiple = (exit_price - active_trade.entry_price) / risk
                active_trade.pnl_pct = (exit_price - active_trade.entry_price) / active_trade.entry_price * 100
                
                result.trades.append(active_trade)
                
                if active_trade.r_multiple > 0:
                    result.wins += 1
                else:
                    result.losses += 1
                
                # Reset for next pattern
                active_trade = None
                highest_close_since_entry = 0.0
                state = PatternState()  # Full reset after trade
                continue
        
        # ═══════════════════════════════════════════════════════════════════
        # PATTERN DETECTION - Only when not in a trade
        # ═══════════════════════════════════════════════════════════════════
        if active_trade is None:
            
            # Check for new breakout if no active pattern
            if not state.active:
                breakout = detect_initial_breakout(df, sma, idx, config)
                if breakout:
                    state = PatternState(
                        active=True,
                        breakout_bar_idx=breakout['idx'],
                        breakout_date=breakout['date'],
                        breakout_high=breakout['high'],
                        breakout_close=breakout['close'],
                        retest_active=True,
                        retest_low=breakout['high'],  # Start tracking from here
                    )
                    result.patterns_detected += 1
                    print(f"[{ticker}] BREAKOUT detected at {breakout['date'].strftime('%Y-%m-%d')}: "
                          f"High ${breakout['high']:.2f}, {breakout['pct_above_sma']:.1%} above SMA")
            
            # Update retest state if pattern active
            elif state.active and state.retest_active:
                state = update_retest_state(df, sma, idx, state, config)
                
                # Check for invalidation
                if state.invalidated:
                    result.pattern_logs.append(PatternLog(
                        ticker=ticker,
                        breakout_date=state.breakout_date,
                        breakout_high=state.breakout_high,
                        retest_low=state.retest_low,
                        retest_date=state.retest_low_date,
                        support_confirmed=state.support_confirmed,
                        support_confirmed_date=state.support_confirmed_date,
                        outcome='INVALIDATED',
                        invalidation_reason=state.invalidation_reason
                    ))
                    print(f"[{ticker}] PATTERN INVALIDATED at {curr_date.strftime('%Y-%m-%d')}: "
                          f"{state.invalidation_reason}")
                    state = PatternState()  # Reset for next pattern
                    continue
                
                # Check for continuation trigger
                if check_continuation_trigger(df, idx, state, config):
                    # ENTRY SIGNAL
                    entry_price = curr_close if config['entry_on_close'] else None
                    stop_loss = calculate_stop_loss(state.retest_low, config)
                    
                    # Determine entry date and price based on config
                    if config['entry_on_close']:
                        actual_entry_date = curr_date
                        actual_entry_price = curr_close
                    else:
                        # Entry on next bar open
                        next_idx = min(idx + 1, len(df) - 1)
                        actual_entry_date = df.index[next_idx]
                        actual_entry_price = df['Open'].iloc[next_idx]
                    
                    active_trade = Trade(
                        ticker=ticker,
                        entry_date=actual_entry_date,
                        entry_price=actual_entry_price,
                        stop_loss=stop_loss,
                        breakout_date=state.breakout_date,
                        breakout_high=state.breakout_high,
                        retest_low=state.retest_low,
                        retest_date=state.retest_low_date
                    )
                    
                    result.trades_taken += 1
                    highest_close_since_entry = curr_close
                    
                    result.pattern_logs.append(PatternLog(
                        ticker=ticker,
                        breakout_date=state.breakout_date,
                        breakout_high=state.breakout_high,
                        retest_low=state.retest_low,
                        retest_date=state.retest_low_date,
                        support_confirmed=state.support_confirmed,
                        support_confirmed_date=state.support_confirmed_date,
                        outcome='TRADED',
                        trade=active_trade
                    ))
                    
                    risk = active_trade.entry_price - stop_loss
                    print(f"[{ticker}] ENTRY at {curr_date.strftime('%Y-%m-%d')}: "
                          f"${active_trade.entry_price:.2f}, Stop ${stop_loss:.2f}, "
                          f"Risk ${risk:.2f} ({risk/active_trade.entry_price*100:.1f}%)")
                    
                    # Don't reset state yet - will reset after trade closes
    
    # Close any open trade at end of data
    if active_trade is not None:
        final_close = df['Close'].iloc[-1]
        active_trade.exit_date = df.index[-1]
        active_trade.exit_price = final_close
        active_trade.exit_reason = 'END_OF_DATA'
        
        risk = active_trade.entry_price - active_trade.stop_loss
        if risk > 0:
            active_trade.r_multiple = (final_close - active_trade.entry_price) / risk
        active_trade.pnl_pct = (final_close - active_trade.entry_price) / active_trade.entry_price * 100
        
        result.trades.append(active_trade)
        if active_trade.r_multiple > 0:
            result.wins += 1
        else:
            result.losses += 1
    
    # Calculate summary statistics
    if result.trades:
        result.win_rate = result.wins / len(result.trades) * 100 if result.trades else 0
        r_multiples = [t.r_multiple for t in result.trades]
        result.avg_r = sum(r_multiples) / len(r_multiples) if r_multiples else 0
        result.total_r = sum(r_multiples)
        
        # Calculate max drawdown and total return
        equity_curve = [1.0]
        for trade in result.trades:
            pnl_mult = 1 + (trade.pnl_pct / 100)
            equity_curve.append(equity_curve[-1] * pnl_mult)
        
        peak = equity_curve[0]
        max_dd = 0
        for eq in equity_curve:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak
            if dd > max_dd:
                max_dd = dd
        
        result.max_drawdown = max_dd * 100
        result.total_return_pct = (equity_curve[-1] - 1) * 100
    
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# REPORTING FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def print_trade_log(result: BacktestResult):
    """Print detailed per-trade log"""
    print(f"\n{'='*80}")
    print(f"TRADE LOG: {result.ticker}")
    print(f"{'='*80}")
    
    for i, trade in enumerate(result.trades, 1):
        print(f"\nTrade #{i}")
        print(f"  Breakout Date: {trade.breakout_date.strftime('%Y-%m-%d')}")
        print(f"  Breakout High: ${trade.breakout_high:.2f}")
        print(f"  Retest Low:    ${trade.retest_low:.2f} ({trade.retest_date.strftime('%Y-%m-%d')})")
        print(f"  Entry:         ${trade.entry_price:.2f} ({trade.entry_date.strftime('%Y-%m-%d')})")
        print(f"  Stop Loss:     ${trade.stop_loss:.2f}")
        print(f"  Exit:          ${trade.exit_price:.2f} ({trade.exit_date.strftime('%Y-%m-%d')})")
        print(f"  Exit Reason:   {trade.exit_reason}")
        print(f"  R-Multiple:    {trade.r_multiple:+.2f}R")
        print(f"  P&L:           {trade.pnl_pct:+.1f}%")


def print_summary(result: BacktestResult):
    """Print backtest summary statistics"""
    print(f"\n{'='*80}")
    print(f"BACKTEST SUMMARY: {result.ticker}")
    print(f"{'='*80}")
    print(f"  Patterns Detected:  {result.patterns_detected}")
    print(f"  Trades Taken:       {result.trades_taken}")
    print(f"  Wins/Losses:        {result.wins}/{result.losses}")
    print(f"  Win Rate:           {result.win_rate:.1f}%")
    print(f"  Average R:          {result.avg_r:+.2f}R")
    print(f"  Total R:            {result.total_r:+.2f}R")
    print(f"  Max Drawdown:       {result.max_drawdown:.1f}%")
    print(f"  Total Return:       {result.total_return_pct:+.1f}%")


def run_backtest_multi(
    tickers: List[str],
    config: Optional[Dict] = None,
    period: str = '5y'
) -> Dict[str, BacktestResult]:
    """
    Run backtest across multiple tickers
    
    Args:
        tickers: List of stock symbols
        config: Strategy parameters
        period: Data period ('5y', '10y', etc.)
    
    Returns:
        Dict mapping ticker to BacktestResult
    """
    import yfinance as yf
    
    results = {}
    
    for ticker in tickers:
        print(f"\n{'='*80}")
        print(f"BACKTESTING: {ticker}")
        print(f"{'='*80}")
        
        try:
            # Fetch weekly data
            stock = yf.Ticker(ticker)
            df = stock.history(period=period, interval='1wk')
            
            if len(df) < 50:
                print(f"[{ticker}] Insufficient data ({len(df)} bars)")
                continue
            
            # Run strategy
            result = strategy_break_retest_30w_sma(df, ticker, config)
            results[ticker] = result
            
            # Print results
            print_trade_log(result)
            print_summary(result)
            
        except Exception as e:
            print(f"[{ticker}] Error: {e}")
    
    # Print aggregate summary
    if results:
        print(f"\n{'='*80}")
        print("AGGREGATE SUMMARY")
        print(f"{'='*80}")
        
        total_trades = sum(r.trades_taken for r in results.values())
        total_wins = sum(r.wins for r in results.values())
        total_r = sum(r.total_r for r in results.values())
        
        print(f"  Tickers Tested:     {len(results)}")
        print(f"  Total Trades:       {total_trades}")
        print(f"  Aggregate Win Rate: {total_wins/total_trades*100:.1f}%" if total_trades > 0 else "  N/A")
        print(f"  Aggregate R:        {total_r:+.2f}R")
    
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# STANDALONE EXECUTION
# ═══════════════════════════════════════════════════════════════════════════════

def get_current_pattern_state(ticker: str, period: str = '2y') -> Dict:
    """
    Get the current Break-Retest pattern state for a ticker.
    Used for displaying current signals in the UI without running a full backtest.
    
    Properly tracks pattern lifecycle:
    - Resets after trigger fires (trade would be active, not "pattern")
    - Resets on Stage 4 invalidation
    - Only shows pending patterns, not historical triggers
    
    Returns a dict with:
        - stage: Current Weinstein stage (1, 2, 3, or 4)
        - pattern_phase: Current pattern phase (None, 'A_BREAKOUT', 'B_RETEST')
        - signal: Current actionable signal text
        - sma_value: Current 30-week SMA value
        - price_vs_sma: Percentage above/below SMA
        - last_bar_date: Date of most recent data bar
    """
    import yfinance as yf
    
    config = DEFAULT_CONFIG.copy()
    
    # Fetch weekly data
    df = yf.download(ticker, period=period, interval='1wk', progress=False)
    if df is None or df.empty or len(df) < config['sma_length'] + config['sma_rising_lookback']:
        return {'stage': None, 'pattern_phase': None, 'signal': 'Insufficient data'}
    
    # Handle MultiIndex columns from yfinance
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    # Compute indicators
    sma = compute_sma(df, config['sma_length'])
    
    # Track state - only care about the CURRENT pending pattern
    state = PatternState()
    
    # Scan through data to find the current pattern state
    for idx in range(config['sma_length'] + config['sma_rising_lookback'], len(df)):
        curr_date = df.index[idx]
        curr_close = float(df['Close'].iloc[idx])
        curr_sma = float(sma.iloc[idx])
        
        if pd.isna(curr_sma):
            continue
        
        sma_rising = is_sma_rising(df, sma, idx, config['sma_rising_lookback'])
        in_stage4 = is_stage_4(curr_close, curr_sma, sma_rising)
        
        # Check for Stage 4 invalidation - resets any pending pattern
        if state.active and in_stage4:
            state = PatternState()  # Reset on trend reversal
            continue
        
        # Pattern detection
        if not state.active:
            breakout = detect_initial_breakout(df, sma, idx, config)
            if breakout:
                state = PatternState(
                    active=True,
                    breakout_bar_idx=breakout['idx'],
                    breakout_date=breakout['date'],
                    breakout_high=breakout['high'],
                    breakout_close=breakout['close'],
                    retest_active=True,
                    retest_low=breakout['high'],
                )
        elif state.active and state.retest_active:
            state = update_retest_state(df, sma, idx, state, config)
            
            if state.invalidated:
                state = PatternState()  # Reset
                continue
            
            # Check for continuation trigger
            if check_continuation_trigger(df, idx, state, config):
                # Trigger fired = trade would be active now
                # Reset pattern state since we're now "in a trade"
                state = PatternState()  # Pattern consumed by trigger
    
    # Build result from final state
    curr_close = float(df['Close'].iloc[-1])
    curr_sma = float(sma.iloc[-1])
    last_bar_date = df.index[-1].strftime('%Y-%m-%d') if hasattr(df.index[-1], 'strftime') else str(df.index[-1])[:10]
    sma_rising = is_sma_rising(df, sma, len(df)-1, config['sma_rising_lookback'])
    
    # Classify current stage
    if is_stage_4(curr_close, curr_sma, sma_rising):
        stage = 4
    elif is_stage_2(curr_close, curr_sma, sma_rising):
        stage = 2
    elif curr_close > curr_sma:
        stage = 2  # Above SMA but not rising = early Stage 2
    else:
        stage = 1  # Base building
    
    price_vs_sma = (curr_close / curr_sma - 1) * 100 if curr_sma > 0 else 0
    
    # Determine pattern phase - only pending patterns, not past triggers
    if state.active and state.support_confirmed:
        pattern_phase = 'B_RETEST'
    elif state.active:
        pattern_phase = 'A_BREAKOUT'
    else:
        pattern_phase = None
    
    result = {
        'stage': stage,
        'pattern_phase': pattern_phase,
        'sma_value': round(curr_sma, 2),
        'price_vs_sma': round(price_vs_sma, 1),
        'breakout_high': round(state.breakout_high, 2) if state.breakout_high > 0 else None,
        'retest_low': round(state.retest_low, 2) if state.retest_low < float('inf') else None,
        'last_bar_date': last_bar_date,
    }
    
    # Generate signal text
    if pattern_phase == 'B_RETEST':
        result['signal'] = f"RETEST: Watching for close above ${state.breakout_high:.2f}"
    elif pattern_phase == 'A_BREAKOUT':
        result['signal'] = f"BREAKOUT: High ${state.breakout_high:.2f}, waiting for pullback"
    else:
        if stage == 2:
            result['signal'] = "Stage 2 - waiting for breakout pattern"
        elif stage == 4:
            result['signal'] = "Stage 4 Decline - no setups"
        else:
            result['signal'] = "No active pattern"
    
    return result


def classify_weinstein_stage(close: float, sma_value: float, sma_rising: bool) -> int:
    """Classify the current Weinstein stage (1-4)"""
    if is_stage_4(close, sma_value, sma_rising):
        return 4
    elif is_stage_2(close, sma_value, sma_rising):
        return 2
    elif close > sma_value:
        return 2  # Above SMA = Stage 2 (simplified)
    else:
        return 1  # Base building


if __name__ == "__main__":
    # Example usage
    test_tickers = ['GOOGL', 'NVDA', 'AAPL', 'GS', 'META']
    
    # Custom config (optional)
    custom_config = {
        'exit_mode': 'SMA',  # Try 'RR', 'SMA', or 'TRAIL'
        'rr_target': 3.0,
        'rapid_break_min_pct': 0.03,
    }
    
    results = run_backtest_multi(test_tickers, custom_config, period='5y')
