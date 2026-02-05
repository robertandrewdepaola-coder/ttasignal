# TTA Engine - Live Trading Journal

A fully-featured trading journal system for the TTA Engine with persistent storage, live price monitoring, and performance tracking.

## 🎯 What This Does

This trading journal transforms your TTA backtesting notebook into a **live trading platform** that:

1. **Watchlist Management** - Track potential trade setups from your TTA scans
2. **Trade Execution** - Enter positions with proper risk management (entry, stop, target)
3. **Daily Monitoring** - Auto-update prices and check for stop losses daily
4. **Performance Tracking** - Calculate win rate, profit factor, R-multiples
5. **Trade History** - Permanent log of all closed trades with full metrics

## 📦 Installation

### Option 1: Standalone Demo (Test First)

```bash
# Copy these files to your directory:
# - trading_journal.py
# - trading_journal_ui.py  
# - journal_demo.py

# Run the demo
streamlit run journal_demo.py
```

### Option 2: Full Integration with TTA App

1. Copy files to your TTA Engine directory:
   ```bash
   cp trading_journal.py /path/to/tta-engine/
   cp trading_journal_ui.py /path/to/tta-engine/
   ```

2. Edit `app.py` and add this import at the top:
   ```python
   from trading_journal_ui import render_trading_journal_tab, add_journal_to_sidebar
   ```

3. Find the tabs section (search for `st.tabs`) and modify:
   ```python
   # BEFORE:
   # tab1, tab2, tab3 = st.tabs(["Single Ticker", "Batch Audit", "Settings"])
   
   # AFTER:
   tab1, tab2, tab3, tab4 = st.tabs(["Single Ticker", "Batch Audit", "Trading Journal", "Settings"])
   
   with tab4:
       render_trading_journal_tab()
   ```

4. (Optional) Add sidebar widget:
   ```python
   # In your sidebar section
   add_journal_to_sidebar()
   ```

## 🚀 Quick Start Workflow

### 1. Build Your Watchlist

Run your TTA Batch Audit to scan for setups, then add passing tickers:

```
📋 Watchlist Tab
├─ Add Ticker: GOOGL
├─ Setup Type: W3 + Daily MACD Cross
└─ Reason: Passed Quality Gate, 78% confidence
```

### 2. Enter a Trade

When you're ready to execute:

```
📈 Open Positions Tab
├─ Ticker: GOOGL (from watchlist)
├─ Entry Price: $100.00
├─ Stop Loss: $92.00 (8% risk)
├─ Position Size: $2,000
├─ Target: $115.00 (optional)
└─ Notes: "W3 entry on fresh daily MACD cross"
```

The system calculates:
- Number of shares (20 shares)
- Risk per share ($8.00)
- Risk percentage (8%)

### 3. Monitor Daily

Each morning, refresh your positions:

```
💰 Daily Monitor Tab
└─ Click "Refresh Prices"
   ├─ Fetches current prices via yfinance
   ├─ Calculates unrealized P&L
   ├─ Checks stop loss distance
   └─ Generates warnings:
       ⚠️ GOOGL: Near stop - only 2.5% away
       🎯 MSFT: TARGET HIT at $350! Consider profit
       🚨 TSLA: STOP HIT at $180 (entry $195)
```

### 4. Close Positions

When exiting a trade:

```
Close Position Form
├─ Select: GOOGL
├─ Exit Reason: Target Hit
├─ Use Market Price: ✓
└─ Result: ✅ Closed GOOGL: $300.00 (+15.0%)
           📊 Entry: $100.00 → Exit: $115.00
           📅 Held: 14 days
           🎯 R-Multiple: 1.88R
```

### 5. Review Performance

Track your results:

```
📊 Performance Tab
├─ Total Trades: 25
├─ Win Rate: 64%
├─ Total P&L: +$4,750
├─ Expectancy: 1.2R
└─ Profit Factor: 2.4
```

## 📊 Features in Detail

### Watchlist Management
- Add potential setups with notes
- Track setup type (W3, W5, Break-Retest, etc.)
- Remove or clear entire watchlist
- Automatically removed when trade opened

### Position Tracking
- Calculate shares from dollar position size
- Risk percentage validation (warns if >15%)
- Optional profit targets
- Trade notes for setup context

### Daily Monitoring
- Real-time price updates from yfinance
- Unrealized P&L calculation
- Stop loss proximity warnings
- Target achievement notifications
- Total portfolio exposure tracking

### Performance Analytics
- Win rate and number of trades
- Average winner vs average loser
- Total P&L and average return
- Best/worst trade identification
- R-multiple expectancy
- Profit factor calculation

### Trade History
- Complete log of all closed trades
- Entry/exit prices and dates
- Holding period calculation
- R-multiple per trade
- Exit reason tracking
- Export to CSV

## 💾 Data Persistence

All data is stored in local JSON files that survive:
- Page refreshes
- Server restarts  
- Browser sessions

**Files created:**
```
watchlist.json       # Potential trade setups
open_trades.json     # Active positions
trade_history.json   # Closed trades log
```

**Backup recommendation:**
```bash
# Backup your journal data
cp watchlist.json watchlist_backup_$(date +%Y%m%d).json
cp open_trades.json open_trades_backup_$(date +%Y%m%d).json
cp trade_history.json trade_history_backup_$(date +%Y%m%d).json
```

## 🔄 Integration with TTA Analysis

The journal works standalone but can be enhanced:

### Auto-Add from Batch Audit
```python
# In Batch Audit results section
if ticker_passed_gate:
    setup = f"Wave: {elliott_wave}, Conf: {confidence}%"
    reason = f"Efficiency: {efficiency_ratio}, Win Rate: {win_rate}%"
    journal.add_to_watchlist(ticker, reason, setup)
```

### Pre-Fill Trade Entry
```python
# From TTA analysis result
suggested_entry = analysis['entry_price']
suggested_stop = analysis['stop_loss']
suggested_target = analysis['target']
```

### Weekly MACD Monitoring
```python
# In daily_update()
if weekly_macd_bearish_cross_detected:
    warnings.append(f"⚠️ {ticker}: Weekly MACD crossed down")
```

## 📈 Example Trade Flow

**Day 1 - Setup Scan:**
```
Run Batch Audit → GOOGL passes gate
Add to watchlist: "W3 entry, 78% confidence"
```

**Day 2 - Entry:**
```
Enter trade: $100 entry, $92 stop, $2000 position
System calculates: 20 shares, 8% risk
```

**Days 3-10 - Monitoring:**
```
Daily update shows:
- Current price: $104 (+4%)
- Unrealized P&L: +$80
- Distance to stop: 13%
```

**Day 11 - Warning:**
```
⚠️ GOOGL: Near stop - only 2.8% away
Price dipped to $94.50
```

**Day 14 - Exit:**
```
Close trade: Target hit at $115
Final P&L: +$300 (+15%)
Holding period: 14 days
R-Multiple: 1.88R
```

**Month End - Review:**
```
Performance summary:
- 8 trades closed
- 5 winners (62.5%)
- Total P&L: +$850
- Avg win: +$240
- Avg loss: -$95
```

## ⚙️ Configuration

### Risk Management Settings

The journal includes built-in risk validation:

```python
# Maximum risk per trade (default 15%)
if risk_percent > 15:
    st.error("Risk too high - keep under 15%")

# Position sizing
shares = position_size / entry_price

# R-multiple calculation
r_multiple = pnl_per_share / risk_per_share
```

### Price Data Source

Uses yfinance for live prices:

```python
# Fetches last 5 days for current price
stock = yf.Ticker(ticker)
hist = stock.history(period='5d')
current_price = hist['Close'].iloc[-1]
```

## 🐛 Troubleshooting

### "Could not fetch price data"
- Check ticker symbol is correct (uppercase)
- Verify yfinance is installed: `pip install yfinance`
- Try manually: `yf.Ticker("GOOGL").history(period="1d")`

### Data not persisting
- Check file permissions in working directory
- Verify JSON files are being created
- Look for write errors in console

### Journal not appearing in app
- Confirm imports added to app.py
- Check tab creation code updated
- Verify `trading_journal.py` and `trading_journal_ui.py` in same directory

## 📚 API Reference

### TradingJournal Class

```python
from trading_journal import TradingJournal

journal = TradingJournal(data_dir=".")

# Watchlist
journal.add_to_watchlist(ticker, reason, setup_type)
journal.remove_from_watchlist(ticker)
journal.get_watchlist()  # Returns DataFrame

# Trading
journal.enter_trade(ticker, entry_price, stop_loss, position_size, ...)
journal.close_trade(ticker, exit_price, exit_reason)
journal.get_open_positions()  # Returns DataFrame

# Monitoring
dashboard = journal.daily_update()
# Returns: {'positions': [], 'warnings': [], 'total_exposure': 0, 'unrealized_pnl': 0}

# Performance
perf = journal.get_performance_summary()
# Returns: {'total_trades': 0, 'win_rate': 0, 'total_pnl': 0, ...}

history = journal.get_trade_history(last_n=10)  # Returns DataFrame
```

## 🎓 Best Practices

1. **Review watchlist weekly** - Remove stale setups
2. **Update daily before market open** - Check overnight moves
3. **Document exit reasons** - Learn from wins and losses
4. **Export history monthly** - Backup to CSV
5. **Keep notes detailed** - "W3 entry" vs "W3 on daily MACD with weekly confirmation"
6. **Respect your stops** - Journal tracks stops for a reason
7. **Review performance quarterly** - Adjust strategy based on results

## 📄 License

Private - All rights reserved

## 🙋 Support

For issues or questions:
1. Check this README thoroughly
2. Review INTEGRATION_GUIDE.py for examples
3. Test with journal_demo.py first
4. Check console for error messages

---

**Built for TTA Engine v16.37**  
*Transform your backtesting notebook into a live trading platform*
