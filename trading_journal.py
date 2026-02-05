"""
TTA Engine - Trading Journal Module
Provides persistent storage for watchlist, open trades, and trade history.
Integrates with yfinance for live price updates and stop loss monitoring.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
import json
import yfinance as yf
from typing import Optional, Dict, List, Tuple


class TradingJournal:
    """
    Live Trading Journal with persistent storage.
    
    Features:
    - Watchlist management (add/remove potential trades)
    - Trade execution (open positions with stop loss)
    - Daily monitoring (check stops, calculate P&L)
    - Trade closing (log final results)
    - Performance tracking (win rate, total profit)
    """
    
    def __init__(self, data_dir: str = "."):
        """
        Initialize trading journal with file-based persistence.
        
        Args:
            data_dir: Directory to store journal files (default: current directory)
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        
        # File paths
        self.watchlist_file = self.data_dir / "watchlist.json"
        self.open_trades_file = self.data_dir / "open_trades.json"
        self.trade_history_file = self.data_dir / "trade_history.json"
        
        # Load existing data
        self.watchlist = self._load_json(self.watchlist_file, default=[])
        self.open_trades = self._load_json(self.open_trades_file, default=[])
        self.trade_history = self._load_json(self.trade_history_file, default=[])
    
    def _load_json(self, filepath: Path, default=None):
        """Load JSON file or return default if not exists."""
        if filepath.exists():
            try:
                with open(filepath, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Warning: Could not load {filepath}: {e}")
        return default if default is not None else {}
    
    def _save_json(self, filepath: Path, data):
        """Save data to JSON file."""
        try:
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            print(f"Error saving {filepath}: {e}")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # WATCHLIST MANAGEMENT
    # ═══════════════════════════════════════════════════════════════════════════
    
    def add_to_watchlist(self, ticker: str, reason: str = "", setup_type: str = ""):
        """
        Add ticker to watchlist.
        
        Args:
            ticker: Stock ticker symbol
            reason: Why this trade is interesting
            setup_type: Elliott Wave state or pattern type
        """
        ticker = ticker.upper().strip()
        
        # Check if already in watchlist
        if any(w['ticker'] == ticker for w in self.watchlist):
            return f"❌ {ticker} already in watchlist"
        
        watch_entry = {
            'ticker': ticker,
            'added_date': datetime.now().isoformat(),
            'reason': reason,
            'setup_type': setup_type
        }
        
        self.watchlist.append(watch_entry)
        self._save_json(self.watchlist_file, self.watchlist)
        
        return f"✅ Added {ticker} to watchlist"
    
    def remove_from_watchlist(self, ticker: str):
        """Remove ticker from watchlist."""
        ticker = ticker.upper().strip()
        original_len = len(self.watchlist)
        self.watchlist = [w for w in self.watchlist if w['ticker'] != ticker]
        
        if len(self.watchlist) < original_len:
            self._save_json(self.watchlist_file, self.watchlist)
            return f"✅ Removed {ticker} from watchlist"
        else:
            return f"❌ {ticker} not found in watchlist"
    
    def get_watchlist(self) -> pd.DataFrame:
        """Return watchlist as DataFrame."""
        if not self.watchlist:
            return pd.DataFrame(columns=['Ticker', 'Added', 'Reason', 'Setup'])
        
        df = pd.DataFrame(self.watchlist)
        df['Added'] = pd.to_datetime(df['added_date']).dt.strftime('%Y-%m-%d')
        df = df[['ticker', 'Added', 'reason', 'setup_type']]
        df.columns = ['Ticker', 'Added', 'Reason', 'Setup']
        return df
    
    def clear_watchlist(self):
        """Clear entire watchlist."""
        self.watchlist = []
        self._save_json(self.watchlist_file, self.watchlist)
        return "✅ Watchlist cleared"
    
    # ═══════════════════════════════════════════════════════════════════════════
    # TRADE EXECUTION
    # ═══════════════════════════════════════════════════════════════════════════
    
    def enter_trade(
        self,
        ticker: str,
        entry_price: float,
        stop_loss: float,
        position_size: float,
        entry_date: Optional[str] = None,
        notes: str = "",
        target: Optional[float] = None
    ):
        """
        Open a new trade position.
        
        Args:
            ticker: Stock ticker symbol
            entry_price: Entry price per share
            stop_loss: Stop loss price (hard exit)
            position_size: Dollar amount invested or number of shares
            entry_date: Entry date (YYYY-MM-DD format, defaults to today)
            notes: Trade notes or setup description
            target: Optional profit target price
            
        Returns:
            Success message with trade ID
        """
        ticker = ticker.upper().strip()
        
        # Check if already have open position
        if any(t['ticker'] == ticker for t in self.open_trades):
            return f"❌ Already have open position in {ticker}"
        
        # Calculate shares if position_size is dollar amount
        shares = position_size / entry_price
        
        # Calculate risk per share
        risk_per_share = entry_price - stop_loss
        risk_percent = (risk_per_share / entry_price) * 100
        
        # Generate unique trade ID
        trade_id = f"{ticker}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        trade = {
            'trade_id': trade_id,
            'ticker': ticker,
            'entry_date': entry_date or datetime.now().strftime('%Y-%m-%d'),
            'entry_price': float(entry_price),
            'stop_loss': float(stop_loss),
            'target': float(target) if target else None,
            'shares': float(shares),
            'position_size': float(position_size),
            'risk_per_share': float(risk_per_share),
            'risk_percent': float(risk_percent),
            'notes': notes,
            'status': 'OPEN',
            'opened_at': datetime.now().isoformat()
        }
        
        self.open_trades.append(trade)
        self._save_json(self.open_trades_file, self.open_trades)
        
        # Remove from watchlist if present
        self.remove_from_watchlist(ticker)
        
        return (f"✅ Opened {ticker}: {shares:.2f} shares @ ${entry_price:.2f}\n"
                f"   💰 Investment: ${position_size:.2f}\n"
                f"   🛡️ Stop: ${stop_loss:.2f} (-{risk_percent:.1f}%)\n"
                f"   📊 Trade ID: {trade_id}")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # DAILY MONITORING
    # ═══════════════════════════════════════════════════════════════════════════
    
    def daily_update(self, check_weekly_cross: bool = False) -> Dict:
        """
        Update all open positions with current prices and check stops.
        
        Args:
            check_weekly_cross: If True, check for Weekly MACD bearish cross
            
        Returns:
            Dictionary with dashboard data:
            - positions: List of position updates
            - warnings: List of alert messages
            - total_exposure: Total capital invested
            - unrealized_pnl: Total unrealized profit/loss
        """
        if not self.open_trades:
            return {
                'positions': [],
                'warnings': [],
                'total_exposure': 0,
                'unrealized_pnl': 0,
                'message': 'No open positions'
            }
        
        positions = []
        warnings = []
        total_exposure = 0
        unrealized_pnl = 0
        
        for trade in self.open_trades:
            ticker = trade['ticker']
            
            # Fetch current price
            try:
                stock = yf.Ticker(ticker)
                hist = stock.history(period='5d')
                
                if hist.empty:
                    warnings.append(f"⚠️ {ticker}: Could not fetch price data")
                    continue
                
                current_price = float(hist['Close'].iloc[-1])
                
                # Calculate P&L
                pnl_per_share = current_price - trade['entry_price']
                pnl_total = pnl_per_share * trade['shares']
                pnl_percent = (pnl_per_share / trade['entry_price']) * 100
                
                # Distance from stop
                distance_to_stop = current_price - trade['stop_loss']
                distance_percent = (distance_to_stop / current_price) * 100
                
                # Check stop loss
                stop_hit = current_price <= trade['stop_loss']
                
                # Check target hit
                target_hit = False
                if trade['target']:
                    target_hit = current_price >= trade['target']
                
                # Build position summary
                position = {
                    'ticker': ticker,
                    'entry_price': trade['entry_price'],
                    'current_price': current_price,
                    'shares': trade['shares'],
                    'stop_loss': trade['stop_loss'],
                    'pnl_dollar': pnl_total,
                    'pnl_percent': pnl_percent,
                    'distance_to_stop': distance_percent,
                    'stop_hit': stop_hit,
                    'target_hit': target_hit,
                    'position_size': trade['position_size'],
                    'entry_date': trade['entry_date']
                }
                
                positions.append(position)
                total_exposure += trade['position_size']
                unrealized_pnl += pnl_total
                
                # Generate warnings
                if stop_hit:
                    warnings.append(f"🚨 {ticker}: STOP HIT at ${current_price:.2f} (entry ${trade['entry_price']:.2f})")
                elif distance_percent < 3:
                    warnings.append(f"⚠️ {ticker}: Near stop - only {distance_percent:.1f}% away")
                
                if target_hit:
                    warnings.append(f"🎯 {ticker}: TARGET HIT at ${current_price:.2f}! Consider taking profit")
                
                # Weekly MACD check (if requested and logic available)
                if check_weekly_cross:
                    # This would integrate with your existing MACD detection
                    # For now, placeholder
                    pass
                    
            except Exception as e:
                warnings.append(f"⚠️ {ticker}: Error fetching data - {str(e)}")
        
        return {
            'positions': positions,
            'warnings': warnings,
            'total_exposure': total_exposure,
            'unrealized_pnl': unrealized_pnl,
            'as_of': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
    
    # ═══════════════════════════════════════════════════════════════════════════
    # TRADE CLOSING
    # ═══════════════════════════════════════════════════════════════════════════
    
    def close_trade(
        self,
        ticker: str,
        exit_price: Optional[float] = None,
        exit_date: Optional[str] = None,
        exit_reason: str = "Manual Exit"
    ):
        """
        Close an open trade and log to history.
        
        Args:
            ticker: Stock ticker symbol
            exit_price: Exit price (if None, fetches current market price)
            exit_date: Exit date (defaults to today)
            exit_reason: Reason for exit (Stop Hit, Target, Manual, etc.)
            
        Returns:
            Summary of closed trade
        """
        ticker = ticker.upper().strip()
        
        # Find open trade
        trade = None
        for t in self.open_trades:
            if t['ticker'] == ticker:
                trade = t
                break
        
        if not trade:
            return f"❌ No open position found for {ticker}"
        
        # Fetch current price if not provided
        if exit_price is None:
            try:
                stock = yf.Ticker(ticker)
                hist = stock.history(period='1d')
                exit_price = float(hist['Close'].iloc[-1])
            except Exception as e:
                return f"❌ Could not fetch exit price for {ticker}: {e}"
        
        # Calculate final P&L
        pnl_per_share = exit_price - trade['entry_price']
        pnl_total = pnl_per_share * trade['shares']
        pnl_percent = (pnl_per_share / trade['entry_price']) * 100
        
        # Calculate R-multiple (profit relative to initial risk)
        r_multiple = pnl_per_share / trade['risk_per_share'] if trade['risk_per_share'] != 0 else 0
        
        # Determine win/loss
        win = pnl_total > 0
        
        # Calculate holding period
        entry_dt = datetime.strptime(trade['entry_date'], '%Y-%m-%d')
        exit_dt = datetime.strptime(exit_date or datetime.now().strftime('%Y-%m-%d'), '%Y-%m-%d')
        holding_days = (exit_dt - entry_dt).days
        
        # Create closed trade record
        closed_trade = {
            **trade,
            'exit_date': exit_date or datetime.now().strftime('%Y-%m-%d'),
            'exit_price': float(exit_price),
            'exit_reason': exit_reason,
            'pnl_dollar': float(pnl_total),
            'pnl_percent': float(pnl_percent),
            'r_multiple': float(r_multiple),
            'win': win,
            'holding_days': holding_days,
            'status': 'CLOSED',
            'closed_at': datetime.now().isoformat()
        }
        
        # Add to history
        self.trade_history.append(closed_trade)
        self._save_json(self.trade_history_file, self.trade_history)
        
        # Remove from open trades
        self.open_trades = [t for t in self.open_trades if t['ticker'] != ticker]
        self._save_json(self.open_trades_file, self.open_trades)
        
        # Return summary
        result_emoji = "✅" if win else "❌"
        return (f"{result_emoji} Closed {ticker}: ${pnl_total:.2f} ({pnl_percent:+.1f}%)\n"
                f"   📊 Entry: ${trade['entry_price']:.2f} → Exit: ${exit_price:.2f}\n"
                f"   📅 Held: {holding_days} days\n"
                f"   🎯 R-Multiple: {r_multiple:.2f}R\n"
                f"   📝 Reason: {exit_reason}")
    
    def close_all_trades(self, exit_reason: str = "Batch Close"):
        """Close all open positions."""
        if not self.open_trades:
            return "No open positions to close"
        
        results = []
        tickers = [t['ticker'] for t in self.open_trades]
        
        for ticker in tickers:
            result = self.close_trade(ticker, exit_reason=exit_reason)
            results.append(result)
        
        return "\n\n".join(results)
    
    # ═══════════════════════════════════════════════════════════════════════════
    # PERFORMANCE TRACKING
    # ═══════════════════════════════════════════════════════════════════════════
    
    def get_performance_summary(self) -> Dict:
        """
        Calculate overall trading performance metrics.
        
        Returns:
            Dictionary with performance stats:
            - total_trades: Number of closed trades
            - winners: Number of winning trades
            - losers: Number of losing trades
            - win_rate: Win rate percentage
            - total_pnl: Total profit/loss
            - avg_win: Average winning trade
            - avg_loss: Average losing trade
            - avg_return: Average return per trade
            - best_trade: Best performing trade
            - worst_trade: Worst performing trade
            - expectancy: Average R per trade
        """
        if not self.trade_history:
            return {
                'total_trades': 0,
                'message': 'No closed trades yet'
            }
        
        df = pd.DataFrame(self.trade_history)
        
        total_trades = len(df)
        winners = df[df['win'] == True]
        losers = df[df['win'] == False]
        
        win_count = len(winners)
        loss_count = len(losers)
        win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0
        
        total_pnl = df['pnl_dollar'].sum()
        avg_win = winners['pnl_dollar'].mean() if len(winners) > 0 else 0
        avg_loss = losers['pnl_dollar'].mean() if len(losers) > 0 else 0
        avg_return = df['pnl_percent'].mean()
        
        best_trade = df.loc[df['pnl_dollar'].idxmax()] if total_trades > 0 else None
        worst_trade = df.loc[df['pnl_dollar'].idxmin()] if total_trades > 0 else None
        
        avg_r_multiple = df['r_multiple'].mean() if total_trades > 0 else 0
        
        # Profit factor
        gross_profit = winners['pnl_dollar'].sum() if len(winners) > 0 else 0
        gross_loss = abs(losers['pnl_dollar'].sum()) if len(losers) > 0 else 0
        profit_factor = gross_profit / gross_loss if gross_loss != 0 else float('inf')
        
        return {
            'total_trades': total_trades,
            'winners': win_count,
            'losers': loss_count,
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'avg_return': avg_return,
            'best_trade': {
                'ticker': best_trade['ticker'],
                'pnl': best_trade['pnl_dollar'],
                'return': best_trade['pnl_percent']
            } if best_trade is not None else None,
            'worst_trade': {
                'ticker': worst_trade['ticker'],
                'pnl': worst_trade['pnl_dollar'],
                'return': worst_trade['pnl_percent']
            } if worst_trade is not None else None,
            'expectancy': avg_r_multiple,
            'profit_factor': profit_factor
        }
    
    def get_trade_history(self, last_n: Optional[int] = None) -> pd.DataFrame:
        """
        Return trade history as DataFrame.
        
        Args:
            last_n: Return only last N trades (default: all)
        """
        if not self.trade_history:
            return pd.DataFrame(columns=[
                'Ticker', 'Entry Date', 'Exit Date', 'Days', 
                'Entry', 'Exit', 'P&L $', 'P&L %', 'R-Multiple', 'Result'
            ])
        
        df = pd.DataFrame(self.trade_history)
        
        # Sort by exit date (most recent first)
        df = df.sort_values('exit_date', ascending=False)
        
        if last_n:
            df = df.head(last_n)
        
        # Format for display
        display_df = pd.DataFrame({
            'Ticker': df['ticker'],
            'Entry Date': df['entry_date'],
            'Exit Date': df['exit_date'],
            'Days': df['holding_days'],
            'Entry': df['entry_price'].apply(lambda x: f"${x:.2f}"),
            'Exit': df['exit_price'].apply(lambda x: f"${x:.2f}"),
            'P&L $': df['pnl_dollar'].apply(lambda x: f"${x:.2f}"),
            'P&L %': df['pnl_percent'].apply(lambda x: f"{x:+.1f}%"),
            'R-Multiple': df['r_multiple'].apply(lambda x: f"{x:.2f}R"),
            'Result': df['win'].apply(lambda x: '✅ Win' if x else '❌ Loss')
        })
        
        return display_df
    
    def get_open_positions(self) -> pd.DataFrame:
        """Return current open positions as DataFrame."""
        if not self.open_trades:
            return pd.DataFrame(columns=[
                'Ticker', 'Entry Date', 'Entry', 'Stop', 
                'Shares', 'Size', 'Risk %'
            ])
        
        df = pd.DataFrame(self.open_trades)
        
        display_df = pd.DataFrame({
            'Ticker': df['ticker'],
            'Entry Date': df['entry_date'],
            'Entry': df['entry_price'].apply(lambda x: f"${x:.2f}"),
            'Stop': df['stop_loss'].apply(lambda x: f"${x:.2f}"),
            'Shares': df['shares'].apply(lambda x: f"{x:.2f}"),
            'Size': df['position_size'].apply(lambda x: f"${x:.2f}"),
            'Risk %': df['risk_percent'].apply(lambda x: f"{x:.1f}%")
        })
        
        return display_df
