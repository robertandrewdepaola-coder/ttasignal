"""
TTA Engine - Trading Journal UI for Streamlit
Provides user interface components for the trading journal.
"""

import streamlit as st
import pandas as pd
from trading_journal import TradingJournal
from datetime import datetime


def render_trading_journal_tab():
    """
    Render the Trading Journal tab in Streamlit.
    
    This creates a complete trading dashboard with:
    - Watchlist management
    - Trade entry form
    - Daily monitoring dashboard
    - Trade closing interface
    - Performance summary
    """
    
    # Initialize journal in session state
    if 'journal' not in st.session_state:
        st.session_state.journal = TradingJournal()
    
    journal = st.session_state.journal
    
    st.title("📊 Live Trading Journal")
    
    # Create tabs for different journal sections
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📋 Watchlist",
        "📈 Open Positions", 
        "💰 Daily Monitor",
        "📊 Performance",
        "📜 Trade History"
    ])
    
    # ═══════════════════════════════════════════════════════════════════════════
    # TAB 1: WATCHLIST MANAGEMENT
    # ═══════════════════════════════════════════════════════════════════════════
    with tab1:
        st.subheader("Watchlist - Potential Setups")
        
        # Add to watchlist form
        with st.form("add_watchlist"):
            col1, col2 = st.columns([1, 2])
            with col1:
                new_ticker = st.text_input("Ticker", placeholder="GOOGL")
            with col2:
                setup_type = st.text_input("Setup Type", placeholder="W3, W5, Break-Retest, etc.")
            
            reason = st.text_area("Reason/Notes", placeholder="Why is this interesting?", height=60)
            
            col_btn1, col_btn2 = st.columns([1, 1])
            with col_btn1:
                add_btn = st.form_submit_button("➕ Add to Watchlist", type="primary", use_container_width=True)
            with col_btn2:
                clear_btn = st.form_submit_button("🗑️ Clear All", use_container_width=True)
        
        if add_btn and new_ticker:
            result = journal.add_to_watchlist(new_ticker, reason, setup_type)
            st.success(result)
            st.rerun()
        
        if clear_btn:
            result = journal.clear_watchlist()
            st.success(result)
            st.rerun()
        
        # Display watchlist
        watchlist_df = journal.get_watchlist()
        
        if watchlist_df.empty:
            st.info("📝 Watchlist is empty. Add potential trades above.")
        else:
            st.dataframe(watchlist_df, use_container_width=True, hide_index=True)
            
            # Remove from watchlist
            st.caption("**Remove from watchlist:**")
            ticker_to_remove = st.selectbox(
                "Select ticker to remove",
                options=watchlist_df['Ticker'].tolist(),
                key="remove_ticker"
            )
            if st.button("🗑️ Remove Selected", key="remove_btn"):
                result = journal.remove_from_watchlist(ticker_to_remove)
                st.success(result)
                st.rerun()
    
    # ═══════════════════════════════════════════════════════════════════════════
    # TAB 2: OPEN POSITIONS & TRADE ENTRY
    # ═══════════════════════════════════════════════════════════════════════════
    with tab2:
        st.subheader("Open Positions")
        
        # Display current positions
        positions_df = journal.get_open_positions()
        
        if positions_df.empty:
            st.info("💼 No open positions. Enter a trade below.")
        else:
            st.dataframe(positions_df, use_container_width=True, hide_index=True)
        
        st.markdown("---")
        
        # Trade entry form
        st.subheader("Enter New Trade")
        
        # Get watchlist tickers for dropdown
        watchlist_tickers = journal.get_watchlist()['Ticker'].tolist() if not journal.get_watchlist().empty else []
        
        with st.form("enter_trade"):
            col1, col2 = st.columns(2)
            
            with col1:
                # Ticker selection (combo of watchlist + manual entry)
                if watchlist_tickers:
                    ticker = st.selectbox("Ticker", options=watchlist_tickers + ["Other..."])
                    if ticker == "Other...":
                        ticker = st.text_input("Enter Ticker", key="manual_ticker")
                else:
                    ticker = st.text_input("Ticker", placeholder="GOOGL")
                
                entry_price = st.number_input("Entry Price", min_value=0.01, value=100.0, step=0.01)
                stop_loss = st.number_input("Stop Loss", min_value=0.01, value=92.0, step=0.01)
            
            with col2:
                target = st.number_input("Target (optional)", min_value=0.0, value=0.0, step=0.01)
                position_size = st.number_input("Position Size ($)", min_value=1.0, value=1000.0, step=100.0)
                entry_date = st.date_input("Entry Date", value=datetime.now())
            
            notes = st.text_area("Trade Notes", placeholder="W3 entry on daily MACD cross...", height=80)
            
            enter_btn = st.form_submit_button("🚀 Open Position", type="primary", use_container_width=True)
        
        if enter_btn and ticker:
            # Calculate risk
            risk = entry_price - stop_loss
            risk_pct = (risk / entry_price) * 100
            
            # Validation
            if stop_loss >= entry_price:
                st.error("❌ Stop loss must be below entry price")
            elif risk_pct > 15:
                st.error(f"❌ Risk too high ({risk_pct:.1f}%). Keep risk under 15%.")
            else:
                target_val = target if target > 0 else None
                result = journal.enter_trade(
                    ticker=ticker,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    position_size=position_size,
                    entry_date=entry_date.strftime('%Y-%m-%d'),
                    notes=notes,
                    target=target_val
                )
                st.success(result)
                st.rerun()
    
    # ═══════════════════════════════════════════════════════════════════════════
    # TAB 3: DAILY MONITORING DASHBOARD
    # ═══════════════════════════════════════════════════════════════════════════
    with tab3:
        st.subheader("Daily Monitor - Position Status")
        
        if st.button("🔄 Refresh Prices", type="primary", use_container_width=True):
            with st.spinner("Fetching live prices..."):
                dashboard = journal.daily_update()
                st.session_state['dashboard_data'] = dashboard
                st.rerun()
        
        # Display dashboard if available
        if 'dashboard_data' in st.session_state:
            dashboard = st.session_state['dashboard_data']
            
            if 'message' in dashboard:
                st.info(dashboard['message'])
            else:
                # Summary metrics
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Total Exposure", f"${dashboard['total_exposure']:,.2f}")
                with col2:
                    pnl = dashboard['unrealized_pnl']
                    st.metric("Unrealized P&L", f"${pnl:,.2f}", delta=f"{pnl:+.2f}")
                with col3:
                    pnl_pct = (pnl / dashboard['total_exposure'] * 100) if dashboard['total_exposure'] > 0 else 0
                    st.metric("Return %", f"{pnl_pct:+.2f}%")
                
                st.caption(f"Last updated: {dashboard['as_of']}")
                
                # Warnings
                if dashboard['warnings']:
                    st.markdown("### ⚠️ Alerts")
                    for warning in dashboard['warnings']:
                        if "🚨" in warning:
                            st.error(warning)
                        elif "🎯" in warning:
                            st.success(warning)
                        else:
                            st.warning(warning)
                
                # Position details table
                st.markdown("### Position Details")
                if dashboard['positions']:
                    pos_df = pd.DataFrame(dashboard['positions'])
                    
                    # Format for display
                    display_data = []
                    for _, row in pos_df.iterrows():
                        status_emoji = "🚨" if row['stop_hit'] else ("🎯" if row['target_hit'] else "✅")
                        
                        display_data.append({
                            'Status': status_emoji,
                            'Ticker': row['ticker'],
                            'Entry': f"${row['entry_price']:.2f}",
                            'Current': f"${row['current_price']:.2f}",
                            'P&L $': f"${row['pnl_dollar']:.2f}",
                            'P&L %': f"{row['pnl_percent']:+.1f}%",
                            'Stop': f"${row['stop_loss']:.2f}",
                            'Dist to Stop': f"{row['distance_to_stop']:.1f}%"
                        })
                    
                    st.dataframe(pd.DataFrame(display_data), use_container_width=True, hide_index=True)
                    
                    # Close position form
                    st.markdown("---")
                    st.subheader("Close Position")
                    
                    with st.form("close_trade"):
                        col1, col2, col3 = st.columns(3)
                        
                        with col1:
                            close_ticker = st.selectbox(
                                "Select Position",
                                options=[p['ticker'] for p in dashboard['positions']]
                            )
                        
                        with col2:
                            exit_reason = st.selectbox(
                                "Exit Reason",
                                options=["Stop Hit", "Target Hit", "Manual Exit", "Risk Management", "Weekly MACD Cross"]
                            )
                        
                        with col3:
                            use_market_price = st.checkbox("Use Market Price", value=True)
                            if not use_market_price:
                                manual_exit = st.number_input("Exit Price", min_value=0.01, value=100.0)
                        
                        close_btn = st.form_submit_button("🔒 Close Position", type="primary")
                    
                    if close_btn:
                        exit_price = None if use_market_price else manual_exit
                        result = journal.close_trade(close_ticker, exit_price=exit_price, exit_reason=exit_reason)
                        st.success(result)
                        # Clear dashboard to force refresh
                        del st.session_state['dashboard_data']
                        st.rerun()
        else:
            st.info("Click 'Refresh Prices' to load current position status")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # TAB 4: PERFORMANCE SUMMARY
    # ═══════════════════════════════════════════════════════════════════════════
    with tab4:
        st.subheader("Performance Summary")
        
        perf = journal.get_performance_summary()
        
        if 'message' in perf:
            st.info(perf['message'])
        else:
            # Key metrics
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.metric("Total Trades", perf['total_trades'])
                st.metric("Winners", perf['winners'])
            
            with col2:
                st.metric("Win Rate", f"{perf['win_rate']:.1f}%")
                st.metric("Losers", perf['losers'])
            
            with col3:
                st.metric("Total P&L", f"${perf['total_pnl']:,.2f}")
                st.metric("Avg Return", f"{perf['avg_return']:.1f}%")
            
            with col4:
                st.metric("Expectancy", f"{perf['expectancy']:.2f}R")
                st.metric("Profit Factor", f"{perf['profit_factor']:.2f}")
            
            st.markdown("---")
            
            # Win/Loss details
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("### 🏆 Average Winner")
                st.metric("Avg Win", f"${perf['avg_win']:,.2f}")
                
                if perf['best_trade']:
                    st.markdown("**Best Trade:**")
                    st.write(f"**{perf['best_trade']['ticker']}**: ${perf['best_trade']['pnl']:,.2f} ({perf['best_trade']['return']:+.1f}%)")
            
            with col2:
                st.markdown("### 📉 Average Loser")
                st.metric("Avg Loss", f"${perf['avg_loss']:,.2f}")
                
                if perf['worst_trade']:
                    st.markdown("**Worst Trade:**")
                    st.write(f"**{perf['worst_trade']['ticker']}**: ${perf['worst_trade']['pnl']:,.2f} ({perf['worst_trade']['return']:+.1f}%)")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # TAB 5: TRADE HISTORY
    # ═══════════════════════════════════════════════════════════════════════════
    with tab5:
        st.subheader("Trade History")
        
        # Filter options
        col1, col2 = st.columns([1, 3])
        with col1:
            show_last = st.selectbox("Show Last", options=[10, 20, 50, "All"], index=0)
        
        last_n = None if show_last == "All" else int(show_last)
        history_df = journal.get_trade_history(last_n=last_n)
        
        if history_df.empty:
            st.info("📜 No trade history yet. Close some trades to see them here.")
        else:
            st.dataframe(history_df, use_container_width=True, hide_index=True)
            
            # Export option
            st.download_button(
                label="📥 Download Trade History (CSV)",
                data=history_df.to_csv(index=False),
                file_name=f"trade_history_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv"
            )


def add_journal_to_sidebar():
    """
    Add quick journal stats to the sidebar.
    Can be called from main app.py
    """
    if 'journal' not in st.session_state:
        st.session_state.journal = TradingJournal()
    
    journal = st.session_state.journal
    
    # Quick stats in sidebar
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 📊 Live Journal")
    
    # Open positions count
    open_count = len(journal.open_trades)
    st.sidebar.metric("Open Positions", open_count)
    
    # Watchlist count
    watch_count = len(journal.watchlist)
    st.sidebar.metric("Watchlist", watch_count)
    
    # Quick performance
    if journal.trade_history:
        perf = journal.get_performance_summary()
        st.sidebar.metric("Win Rate", f"{perf['win_rate']:.0f}%")
        st.sidebar.metric("Total P&L", f"${perf['total_pnl']:,.0f}")
