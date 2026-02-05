"""
TTA Engine v16.37 - Trading Journal Integration Patch

This file contains the code snippets to integrate the Trading Journal into app.py.

INSTALLATION STEPS:
===================

1. Copy trading_journal.py and trading_journal_ui.py to your project directory

2. Add imports at the top of app.py (around line 20):

    from trading_journal_ui import render_trading_journal_tab, add_journal_to_sidebar

3. Find the tab creation section (search for "st.tabs") and add Trading Journal tab:

   BEFORE:
   tab1, tab2, tab3 = st.tabs(["Single Ticker", "Batch Audit", "Settings"])
   
   AFTER:
   tab1, tab2, tab3, tab4 = st.tabs(["Single Ticker", "Batch Audit", "Trading Journal", "Settings"])
   
   Then in the new tab section, add:
   
   with tab4:
       render_trading_journal_tab()

4. (Optional) Add sidebar widget at the end of the sidebar section:

   add_journal_to_sidebar()

5. Run the app:

   streamlit run app.py

FEATURES:
=========

✅ Watchlist Management
   - Add potential trade setups
   - Track reasons and setup types
   - Remove or clear watchlist

✅ Trade Execution
   - Open positions from watchlist
   - Set entry, stop loss, target
   - Position sizing with risk calculation
   - Trade notes and metadata

✅ Daily Monitoring
   - Fetch live prices from yfinance
   - Real-time P&L calculation
   - Stop loss proximity warnings
   - Target hit notifications

✅ Trade Management
   - Close positions with reason tracking
   - Manual or market price exits
   - Automatic P&L calculation
   - R-multiple tracking

✅ Performance Tracking
   - Win rate and profit factor
   - Average winner/loser
   - Total P&L across all trades
   - Trade history export (CSV)

DATA PERSISTENCE:
=================

All data is saved to local JSON files:
- watchlist.json (potential setups)
- open_trades.json (active positions)
- trade_history.json (closed trades)

These files survive server restarts and page refreshes.

INTEGRATION WITH EXISTING TTA FEATURES:
=======================================

The journal works standalone BUT can be enhanced to integrate with your existing
TTA analysis:

1. Auto-add from Batch Audit results:
   - When a ticker passes Quality Gate, add "Add to Watchlist" button
   - Pre-fill setup type (W3, W5, etc.) from Elliott detection

2. Auto-populate entry recommendations:
   - When opening trade, fetch last TTA analysis
   - Suggest entry price based on pattern state
   - Calculate stop from ATR or swing low

3. Weekly MACD monitoring:
   - In daily_update(), check for Weekly MACD bearish cross
   - Auto-warn if Weekly momentum fades on open position

EXAMPLE WORKFLOW:
=================

1. Run Batch Audit on your watchlist
2. Find GOOGL passes gate with "W3 + Daily MACD Cross"
3. Add GOOGL to journal watchlist with reason: "W3 entry, 78% confidence"
4. Enter trade: $100 entry, $92 stop, $2000 position
5. Run Daily Monitor each morning
6. System warns: "GOOGL near stop - only 2.5% away"
7. Close trade: Exit at $105, +5% gain, logged to history
8. Check Performance tab: Win rate, total P&L, trade log

"""

# ═══════════════════════════════════════════════════════════════════════════
# CODE SNIPPET 1: Add imports at top of app.py
# ═══════════════════════════════════════════════════════════════════════════

# Add this around line 20 with other imports:
"""
from trading_journal_ui import render_trading_journal_tab, add_journal_to_sidebar
"""


# ═══════════════════════════════════════════════════════════════════════════
# CODE SNIPPET 2: Add Trading Journal tab
# ═══════════════════════════════════════════════════════════════════════════

# Find where tabs are created (search for "st.tabs") and modify:
"""
# BEFORE:
# tab1, tab2, tab3 = st.tabs(["Single Ticker", "Batch Audit", "Settings"])

# AFTER:
tab1, tab2, tab3, tab4 = st.tabs(["Single Ticker", "Batch Audit", "Trading Journal", "Settings"])

# Then add the new tab content:
with tab4:
    render_trading_journal_tab()
"""


# ═══════════════════════════════════════════════════════════════════════════
# CODE SNIPPET 3: (Optional) Add sidebar widget
# ═══════════════════════════════════════════════════════════════════════════

# At the end of your sidebar section (before main content), add:
"""
# Quick journal stats in sidebar
add_journal_to_sidebar()
"""


# ═══════════════════════════════════════════════════════════════════════════
# CODE SNIPPET 4: (Advanced) Auto-add from Batch Audit
# ═══════════════════════════════════════════════════════════════════════════

# In the Batch Audit results section, add a button to add passing tickers to watchlist:
"""
# After displaying passed_df leaderboard (around line 4400)
if len(passed_df) > 0:
    st.markdown("---")
    st.subheader("Add to Trading Journal")
    
    # Initialize journal
    if 'journal' not in st.session_state:
        from trading_journal import TradingJournal
        st.session_state.journal = TradingJournal()
    
    col1, col2 = st.columns([2, 1])
    with col1:
        add_ticker = st.selectbox(
            "Select ticker to add to watchlist",
            options=passed_df['Ticker'].tolist()
        )
    with col2:
        if st.button("➕ Add to Watchlist", type="primary"):
            # Get row data for this ticker
            row = passed_df[passed_df['Ticker'] == add_ticker].iloc[0]
            
            # Build setup description from TTA data
            setup = f"Confidence: {row.get('Confidence', 'N/A')}"
            reason = f"Passed Quality Gate. Eff: {row.get('Efficiency Ratio', 'N/A')}, " \
                     f"Win Rate: {row.get('Win Rate', 'N/A')}"
            
            result = st.session_state.journal.add_to_watchlist(
                add_ticker,
                reason=reason,
                setup_type=setup
            )
            st.success(result)
"""


# ═══════════════════════════════════════════════════════════════════════════
# COMPLETE INTEGRATION EXAMPLE
# ═══════════════════════════════════════════════════════════════════════════

def example_integration():
    """
    This is a complete example showing how to integrate the journal
    with your existing TTA workflow.
    """
    import streamlit as st
    from trading_journal import TradingJournal
    from trading_journal_ui import render_trading_journal_tab
    
    # Initialize
    if 'journal' not in st.session_state:
        st.session_state.journal = TradingJournal()
    
    # In your Batch Audit results (when ticker passes gate):
    def add_to_journal_from_audit(ticker, confidence, elliott_wave, win_rate):
        """Add passing ticker to journal watchlist"""
        setup = f"Wave: {elliott_wave}, Conf: {confidence}%"
        reason = f"Passed Quality Gate with {win_rate:.0f}% win rate"
        
        result = st.session_state.journal.add_to_watchlist(
            ticker=ticker,
            reason=reason,
            setup_type=setup
        )
        return result
    
    # In your Daily Monitor tab:
    def check_positions_against_weekly_cross():
        """
        Check if any open position has Weekly MACD bearish cross.
        This integrates with your existing MACD detection.
        """
        journal = st.session_state.journal
        
        for trade in journal.open_trades:
            ticker = trade['ticker']
            
            # Use your existing MACD detection code here
            # weekly_cross_detected = your_weekly_macd_check(ticker)
            
            # If cross detected, add warning
            # if weekly_cross_detected:
            #     st.warning(f"⚠️ {ticker}: Weekly MACD bearish cross detected!")
            pass
    
    # Example of pre-filling trade entry from TTA analysis:
    def suggest_entry_from_tta(ticker, analysis_result):
        """
        Pre-fill trade entry form with TTA recommendations.
        
        Args:
            ticker: Stock symbol
            analysis_result: Your TTA analysis dict with entry/stop/target
        """
        suggested_entry = analysis_result.get('entry_price', 0)
        suggested_stop = analysis_result.get('stop_loss', 0)
        suggested_target = analysis_result.get('target', 0)
        
        # These would populate the trade entry form
        return {
            'ticker': ticker,
            'entry_price': suggested_entry,
            'stop_loss': suggested_stop,
            'target': suggested_target
        }
