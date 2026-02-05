"""
TTA Engine - Trading Journal Demo App
Minimal Streamlit app to test the trading journal independently.

Run with: streamlit run journal_demo.py
"""

import streamlit as st
import sys
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

from trading_journal_ui import render_trading_journal_tab, add_journal_to_sidebar

# Configure page
st.set_page_config(
    page_title="TTA Trading Journal",
    page_icon="📊",
    layout="wide"
)

# Header
st.title("📊 TTA Engine - Trading Journal Demo")
st.caption("Live trading journal with persistent storage")

# Sidebar
with st.sidebar:
    st.header("TTA Trading Journal")
    st.markdown("---")
    
    # Add quick stats
    add_journal_to_sidebar()
    
    st.markdown("---")
    st.markdown("""
    ### Features
    - 📋 Watchlist Management
    - 📈 Position Tracking
    - 💰 Live P&L Monitoring
    - 📊 Performance Analytics
    - 📜 Trade History
    
    ### Data Files
    - `watchlist.json`
    - `open_trades.json`
    - `trade_history.json`
    """)

# Main content
render_trading_journal_tab()

# Footer
st.markdown("---")
st.caption("TTA Engine v16.37 - Trading Journal Module")
