"""
TTA Engine - Trading Journal UI for Streamlit (Enhanced Version)
Provides user interface components for the trading journal.

ENHANCEMENTS:
- Quality scoring with mini-backtest in watchlist scanner
- Fixed signal detection matching backtester logic
- Weekly confirmation status display
- Comprehensive ticker analysis
- LATE ENTRY DETECTION - Shows entry window for recent signals
"""

import streamlit as st
import pandas as pd
from datetime import datetime
import traceback

# Graceful imports with error handling
try:
    from trading_journal import TradingJournal
    JOURNAL_AVAILABLE = True
except ImportError as e:
    JOURNAL_AVAILABLE = False
    JOURNAL_IMPORT_ERROR = str(e)

try:
    from trade_entry_helper import (
        fetch_current_price,
        calculate_atr_value,
        calculate_strategy_stops,
        calculate_profit_target,
        validate_entry_conditions,
        format_entry_validation,
        format_quality_score,
        get_exit_strategy_note,
        check_weekly_confirmation,
        calculate_quality_score,
        analyze_ticker_full,
        # Late entry functions
        find_recent_crossover,
        check_late_entry_conditions,
        get_late_entry_analysis,
        format_late_entry_status,
        LATE_ENTRY_MAX_DAYS
    )
    HELPER_AVAILABLE = True
    LATE_ENTRY_AVAILABLE = True
except ImportError as e:
    HELPER_AVAILABLE = False
    LATE_ENTRY_AVAILABLE = False
    HELPER_IMPORT_ERROR = str(e)
    
    # Provide fallback functions if trade_entry_helper not available
    LATE_ENTRY_MAX_DAYS = 5
    
    def fetch_current_price(ticker):
        import yfinance as yf
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period='1d')
            if not hist.empty:
                return float(hist['Close'].iloc[-1])
        except:
            pass
        return None
    
    def calculate_atr_value(ticker, period=14):
        return None
    
    def calculate_strategy_stops(entry_price, atr=None):
        return entry_price * 0.85, "15% Protective"
    
    def calculate_profit_target(entry_price):
        return entry_price * 1.20
    
    def validate_entry_conditions(ticker):
        return False, {"error": "trade_entry_helper not available"}
    
    def format_entry_validation(is_valid, checks):
        if 'error' in checks:
            return f"❌ {checks['error']}"
        return "Entry validation unavailable"
    
    def format_quality_score(quality):
        return "Quality scoring unavailable"
    
    def get_exit_strategy_note():
        return "Exit strategy: 15% stop loss, Weekly MACD cross down"
    
    def check_weekly_confirmation(ticker):
        return {'weekly_bullish': False, 'signal_type': 'N/A', 'error': 'Not available'}
    
    def calculate_quality_score(ticker):
        return {'quality_grade': 'N/A', 'error': 'Not available'}
    
    def analyze_ticker_full(ticker):
        return {
            'ticker': ticker,
            'entry_signal': {'is_valid': False, 'checks': {}},
            'weekly_status': {},
            'quality': {},
            'recommendation': 'N/A',
            'summary': 'Full analysis not available'
        }


def safe_render(func):
    """Decorator to catch all errors and display them nicely"""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            st.error(f"Error: {str(e)}")
            with st.expander("Debug Info"):
                st.code(traceback.format_exc())
            return None
    return wrapper


def render_trading_journal_tab():
    """
    Render the Trading Journal tab in Streamlit.
    
    This creates a complete trading dashboard with:
    - Watchlist management with QUALITY SCORING
    - Trade entry form
    - Daily monitoring dashboard
    - Trade closing interface
    - Performance summary
    """
    
    try:
        # Check if required modules are available
        if not JOURNAL_AVAILABLE:
            st.error(f"❌ Trading Journal module not found: {JOURNAL_IMPORT_ERROR}")
            st.info("Make sure `trading_journal.py` is in your project directory.")
            st.code("""
# Required files in your project:
├── app.py
├── trading_journal.py      ← This file is missing
├── trading_journal_ui.py
├── trade_entry_helper.py
└── requirements.txt
            """)
            return
        
        if not HELPER_AVAILABLE:
            st.warning(f"⚠️ Trade entry helper not fully loaded: {HELPER_IMPORT_ERROR}")
            st.info("Some features may be limited. Make sure `trade_entry_helper.py` is in your project directory.")
        
        # Initialize journal in session state
        if 'journal' not in st.session_state:
            st.session_state.journal = TradingJournal()
        
        journal = st.session_state.journal
        
        # Custom CSS for better dark theme visibility
        st.markdown("""
        <style>
        .stApp { background-color: #0E1117; }
        .stTextInput > div > div > input,
        .stTextArea > div > div > textarea,
        .stNumberInput > div > div > input {
            color: #FAFAFA !important;
            background-color: #262730 !important;
            border: 1px solid #4A4A4A !important;
        }
        .stSelectbox > div > div { background-color: #262730 !important; }
        .stSelectbox > div > div > div {
            color: #FAFAFA !important;
            background-color: #262730 !important;
        }
        .stSelectbox div[data-baseweb="select"] > div {
            background-color: white !important;
            color: #1E1E1E !important;
        }
        .stSelectbox ul[role="listbox"] { background-color: white !important; }
        .stSelectbox li[role="option"] {
            color: #1E1E1E !important;
            background-color: white !important;
        }
        .stSelectbox li[role="option"]:hover { background-color: #E8E8E8 !important; }
        [data-baseweb="popover"], [data-baseweb="popover"] > div { background-color: white !important; }
        .stDateInput > div > div > input {
            color: #FAFAFA !important;
            background-color: #262730 !important;
            border: 1px solid #4A4A4A !important;
        }
        .stDateInput [data-baseweb="popover"] { background-color: white !important; }
        .stDateInput [data-baseweb="calendar"] {
            background-color: white !important;
            color: #1E1E1E !important;
        }
        .stDataFrame { background-color: #262730 !important; }
        .stDataFrame table { color: #FAFAFA !important; }
        label { color: #FAFAFA !important; }
        .main p { color: #FAFAFA !important; }
        h1, h2, h3, h4, h5, h6 {
            color: #FAFAFA !important;
            font-weight: 600 !important;
        }
        .main h2 {
            font-size: 1.8rem !important;
            margin-bottom: 1rem !important;
            border-bottom: 2px solid #4A4A4A !important;
            padding-bottom: 0.5rem !important;
        }
        .main h3 {
            font-size: 1.4rem !important;
            margin-top: 1.5rem !important;
            margin-bottom: 0.8rem !important;
        }
        button { color: inherit !important; }
        .stButton > button {
            color: white !important;
            background-color: #FF4B4B !important;
        }
        .stButton > button[kind="primary"] {
            background-color: #FF4B4B !important;
            color: white !important;
        }
        .stSelectbox option {
            color: #1E1E1E !important;
            background-color: white !important;
        }
        .stForm {
            background-color: #1E1E1E !important;
            border: 1px solid #4A4A4A !important;
            padding: 20px;
            border-radius: 10px;
        }
        ::placeholder {
            color: #888888 !important;
            opacity: 1 !important;
        }
        .stSuccess, .stWarning, .stInfo, .stError { color: #1E1E1E !important; }
        .stSuccess p, .stWarning p, .stInfo p, .stError p { color: #1E1E1E !important; }
        .stCaptionContainer { color: #A0A0A0 !important; }
        .stTabs [data-baseweb="tab-list"] { background-color: #1E1E1E !important; }
        .stTabs [data-baseweb="tab"] { color: #FAFAFA !important; }
        
        /* Quality grade badges */
        .grade-a { background-color: #00C851; color: white; padding: 2px 8px; border-radius: 4px; font-weight: bold; }
        .grade-b { background-color: #33b5e5; color: white; padding: 2px 8px; border-radius: 4px; font-weight: bold; }
        .grade-c { background-color: #ffbb33; color: black; padding: 2px 8px; border-radius: 4px; font-weight: bold; }
        .grade-f { background-color: #ff4444; color: white; padding: 2px 8px; border-radius: 4px; font-weight: bold; }
        </style>
        """, unsafe_allow_html=True)
        
        st.title("📊 Live Trading Journal")
        
        # Create tabs for different journal sections
        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "📋 Watchlist",
            "📈 Open Positions", 
            "💰 Daily Monitor",
            "📊 Performance",
            "📜 Trade History"
        ])
        
        with tab1:
            render_watchlist_tab(journal)
        
        with tab2:
            render_positions_tab(journal)
        
        with tab3:
            render_monitor_tab(journal)
        
        with tab4:
            render_performance_tab(journal)
        
        with tab5:
            render_history_tab(journal)
            
    except Exception as e:
        st.error(f"Fatal error in trading journal: {str(e)}")
        st.code(traceback.format_exc())


@safe_render
def render_watchlist_tab(journal):
    """Render the watchlist management tab with QUALITY SCORING"""
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
        st.markdown("---")
        
        # ═══════════════════════════════════════════════════════════════════════
        # ENHANCED SCANNER - Entry Signals + Quality Scoring + Late Entry
        # ═══════════════════════════════════════════════════════════════════════
        st.subheader("📡 Entry Signal Scanner")
        
        st.markdown("""
        **Scan Modes:**
        - 🔍 **Full Scan** - Entry signal + Quality backtest + Weekly status
        - ⚡ **Quick Scan** - Entry signal check only (faster)
        - 🕐 **Late Entry** - Find recent signals still within entry window
        """)
        
        col_scan1, col_scan2, col_scan3, col_scan4 = st.columns([2, 1, 1, 1])
        with col_scan1:
            if st.button("🔍 Full Scan", type="primary", use_container_width=True):
                st.session_state['run_full_scan'] = True
                st.rerun()
        
        with col_scan2:
            if st.button("⚡ Quick Scan", use_container_width=True):
                st.session_state['run_quick_scan'] = True
                st.rerun()
        
        with col_scan3:
            if st.button("🕐 Late Entry", use_container_width=True):
                st.session_state['run_late_entry_scan'] = True
                st.rerun()
        
        with col_scan4:
            min_grade = st.selectbox("Min Grade", options=['Any', 'C+', 'B+', 'A'], index=0)
        
        # ═══════════════════════════════════════════════════════════════════════
        # LATE ENTRY SCAN - Find recent crossovers still valid
        # ═══════════════════════════════════════════════════════════════════════
        if st.session_state.get('run_late_entry_scan'):
            st.session_state['run_late_entry_scan'] = False
            
            late_results = []
            tickers = watchlist_df['Ticker'].tolist()
            
            with st.spinner("Scanning for late entry opportunities..."):
                for ticker in tickers:
                    try:
                        if LATE_ENTRY_AVAILABLE:
                            analysis = get_late_entry_analysis(ticker)
                            
                            if analysis.get('has_recent_signal'):
                                late = analysis.get('late_entry', {})
                                crossover = analysis.get('crossover', {})
                                
                                days = late.get('days_since_cross', 0)
                                quality = late.get('quality', 'N/A')
                                premium = late.get('entry_premium_pct', 0)
                                
                                # Entry window display
                                if days == 0:
                                    window = "🟢 TODAY"
                                elif days <= 2:
                                    window = f"🟢 Day +{days}"
                                elif days <= 3:
                                    window = f"🟡 Day +{days}"
                                elif days <= LATE_ENTRY_MAX_DAYS:
                                    window = f"🟠 Day +{days}"
                                else:
                                    window = f"❌ Day +{days}"
                                
                                late_results.append({
                                    'Ticker': ticker,
                                    'Entry Window': window,
                                    'Quality': quality,
                                    'Premium': f"{premium:+.1f}%",
                                    'Cross Price': f"${crossover.get('crossover_price', 0):.2f}",
                                    'Current': f"${late.get('current_price', 0):.2f}",
                                    'MACD↑': '✅' if late.get('macd_bullish') else '❌',
                                    'AO>0': '✅' if late.get('ao_positive') else '❌',
                                    'Hist↑': '✅' if late.get('histogram_growing') else '❌',
                                    'Recommendation': analysis.get('recommendation', 'N/A'),
                                    '_days': days,
                                    '_valid': late.get('is_valid', False)
                                })
                        else:
                            late_results.append({
                                'Ticker': ticker,
                                'Entry Window': '❓',
                                'Quality': 'N/A',
                                'Premium': 'N/A',
                                'Cross Price': 'N/A',
                                'Current': 'N/A',
                                'MACD↑': '❓',
                                'AO>0': '❓',
                                'Hist↑': '❓',
                                'Recommendation': 'Late entry not available',
                                '_days': 99,
                                '_valid': False
                            })
                    except Exception as e:
                        late_results.append({
                            'Ticker': ticker,
                            'Entry Window': '⚠️ ERROR',
                            'Quality': 'N/A',
                            'Premium': 'N/A',
                            'Cross Price': 'N/A',
                            'Current': 'N/A',
                            'MACD↑': '❓',
                            'AO>0': '❓',
                            'Hist↑': '❓',
                            'Recommendation': str(e)[:30],
                            '_days': 99,
                            '_valid': False
                        })
            
            st.session_state['late_entry_results'] = late_results
        
        # Display late entry results
        if 'late_entry_results' in st.session_state and st.session_state['late_entry_results']:
            results = st.session_state['late_entry_results']
            df = pd.DataFrame(results)
            
            # Separate by validity
            valid_entries = df[df['_valid'] == True].sort_values('_days')
            no_signal = df[df['_valid'] == False]
            
            st.markdown("### 🕐 Late Entry Scan Results")
            st.caption(f"Entry window: Up to {LATE_ENTRY_MAX_DAYS} days after crossover")
            
            if len(valid_entries) > 0:
                st.success(f"**✅ {len(valid_entries)} ticker(s) with valid entry window!**")
                display_cols = ['Ticker', 'Entry Window', 'Quality', 'Premium', 'Cross Price', 'Current', 'MACD↑', 'AO>0', 'Hist↑', 'Recommendation']
                st.dataframe(valid_entries[display_cols], use_container_width=True, hide_index=True)
            else:
                st.info("No tickers with valid late entry window. All signals either expired or no recent crossover.")
            
            if len(no_signal) > 0:
                with st.expander(f"📭 No Recent Signal ({len(no_signal)} tickers)"):
                    display_cols = ['Ticker', 'Entry Window', 'Recommendation']
                    st.dataframe(no_signal[display_cols], use_container_width=True, hide_index=True)
            
            st.markdown("---")
        
        # ═══════════════════════════════════════════════════════════════════════
        # FULL SCAN - Entry + Quality
        # ═══════════════════════════════════════════════════════════════════════
        if st.session_state.get('run_full_scan'):
            st.session_state['run_full_scan'] = False
            
            all_results = []
            tickers = watchlist_df['Ticker'].tolist()
            
            progress_bar = st.progress(0, text="Scanning...")
            
            for idx, ticker in enumerate(tickers):
                progress_bar.progress((idx + 1) / len(tickers), text=f"Analyzing {ticker}...")
                
                try:
                    # Full analysis
                    analysis = analyze_ticker_full(ticker)
                    
                    # Entry checks
                    checks = analysis['entry_signal'].get('checks', {})
                    is_valid = analysis['entry_signal'].get('is_valid', False)
                    
                    # Quality metrics
                    quality = analysis.get('quality', {})
                    grade = quality.get('quality_grade', 'N/A')
                    score = quality.get('quality_score', 0)
                    win_rate = quality.get('win_rate', 0)
                    avg_return = quality.get('avg_return', 0)
                    signals_found = quality.get('signals_found', 0)
                    
                    # Weekly status
                    weekly = analysis.get('weekly_status', {})
                    weekly_bullish = weekly.get('weekly_bullish', False)
                    signal_type = weekly.get('signal_type', 'N/A')
                    
                    # Late entry check
                    late_entry_status = ""
                    if LATE_ENTRY_AVAILABLE and not is_valid:
                        late_analysis = get_late_entry_analysis(ticker)
                        if late_analysis.get('entry_allowed'):
                            days = late_analysis['late_entry'].get('days_since_cross', 0)
                            late_entry_status = f"🕐 +{days}d"
                    
                    # Grade emoji
                    grade_emoji = {'A': '🏆', 'B': '✅', 'C': '⚠️', 'F': '❌', 'N/A': '❓'}.get(grade, '❓')
                    
                    # Status determination (now includes late entry)
                    if is_valid and grade in ['A', 'B']:
                        status = '🟢 READY'
                    elif is_valid and grade == 'C':
                        status = '🟡 CAUTION'
                    elif late_entry_status:
                        status = f'🕐 LATE OK'
                    elif checks.get('valid_relaxed') and grade in ['A', 'B']:
                        status = '🟡 WATCH'
                    else:
                        status = '🔴 SKIP'
                    
                    all_results.append({
                        'Ticker': ticker,
                        'Status': status,
                        'Late': late_entry_status,
                        'Grade': f"{grade_emoji} {grade}",
                        'Score': score,
                        'Win%': f"{win_rate:.0f}%",
                        'Avg Ret': f"{avg_return:+.1f}%",
                        'Signals': signals_found,
                        'Weekly': '🟢' if weekly_bullish else '🔴',
                        'Type': signal_type,
                        'MACD✓': '✅' if checks.get('daily_macd_cross') else ('🟡' if checks.get('macd_bullish') else '❌'),
                        'AO>0': '✅' if checks.get('ao_positive') else '❌',
                        'AO Cross': '✅' if checks.get('ao_recent_cross') else '❌',
                        'Mkt OK': '✅' if (checks.get('spy_above_200') and checks.get('vix_below_30')) else '❌',
                        'Recommendation': analysis.get('recommendation', 'SKIP'),
                        '_grade': grade,
                        '_score': score
                    })
                    
                except Exception as e:
                    all_results.append({
                        'Ticker': ticker,
                        'Status': '⚠️ ERROR',
                        'Late': '',
                        'Grade': '❓ N/A',
                        'Score': 0,
                        'Win%': 'N/A',
                        'Avg Ret': 'N/A',
                        'Signals': 0,
                        'Weekly': '❓',
                        'Type': 'N/A',
                        'MACD✓': '❌',
                        'AO>0': '❌',
                        'AO Cross': '❌',
                        'Mkt OK': '❌',
                        'Recommendation': 'ERROR',
                        '_grade': 'F',
                        '_score': 0
                    })
            
            progress_bar.empty()
            st.session_state['scan_results'] = all_results
        
        # ═══════════════════════════════════════════════════════════════════════
        # QUICK SCAN - Entry Only (no backtest)
        # ═══════════════════════════════════════════════════════════════════════
        if st.session_state.get('run_quick_scan'):
            st.session_state['run_quick_scan'] = False
            
            all_results = []
            tickers = watchlist_df['Ticker'].tolist()
            
            with st.spinner("Quick scanning for entry signals..."):
                for ticker in tickers:
                    try:
                        is_valid, checks = validate_entry_conditions(ticker)
                        weekly = check_weekly_confirmation(ticker)
                        
                        conditions_met = sum(1 for k, v in checks.items() 
                                           if k in ['daily_macd_cross', 'ao_positive', 'ao_recent_cross', 'spy_above_200', 'vix_below_30'] 
                                           and v == True)
                        
                        if is_valid:
                            status = '🟢 READY'
                        elif checks.get('valid_relaxed'):
                            status = '🟡 WATCH'
                        elif conditions_met >= 3:
                            status = f'🟡 {conditions_met}/5'
                        else:
                            status = f'🔴 {conditions_met}/5'
                        
                        all_results.append({
                            'Ticker': ticker,
                            'Status': status,
                            'Grade': '⏳ Run Full',
                            'Score': '-',
                            'Win%': '-',
                            'Avg Ret': '-',
                            'Signals': '-',
                            'Weekly': '🟢' if weekly.get('weekly_bullish') else '🔴',
                            'Type': weekly.get('signal_type', 'N/A'),
                            'MACD✓': '✅' if checks.get('daily_macd_cross') else ('🟡' if checks.get('macd_bullish') else '❌'),
                            'AO>0': '✅' if checks.get('ao_positive') else '❌',
                            'AO Cross': '✅' if checks.get('ao_recent_cross') else '❌',
                            'Mkt OK': '✅' if (checks.get('spy_above_200') and checks.get('vix_below_30')) else '❌',
                            'Recommendation': 'ENTER' if is_valid else 'WAIT',
                            '_grade': 'N/A',
                            '_score': 0
                        })
                        
                    except Exception as e:
                        all_results.append({
                            'Ticker': ticker,
                            'Status': '⚠️ ERROR',
                            'Grade': '❓',
                            'Score': '-',
                            'Win%': '-',
                            'Avg Ret': '-',
                            'Signals': '-',
                            'Weekly': '❓',
                            'Type': '-',
                            'MACD✓': '❌',
                            'AO>0': '❌',
                            'AO Cross': '❌',
                            'Mkt OK': '❌',
                            'Recommendation': 'ERROR',
                            '_grade': 'F',
                            '_score': 0
                        })
            
            st.session_state['scan_results'] = all_results
        
        # ═══════════════════════════════════════════════════════════════════════
        # DISPLAY RESULTS
        # ═══════════════════════════════════════════════════════════════════════
        if 'scan_results' in st.session_state and st.session_state['scan_results']:
            results = st.session_state['scan_results']
            df = pd.DataFrame(results)
            
            # Filter by grade if selected
            if min_grade == 'A':
                df = df[df['_grade'] == 'A']
            elif min_grade == 'B+':
                df = df[df['_grade'].isin(['A', 'B'])]
            elif min_grade == 'C+':
                df = df[df['_grade'].isin(['A', 'B', 'C'])]
            
            # Sort by score
            df = df.sort_values('_score', ascending=False)
            
            # Separate by status
            ready = df[df['Status'].str.contains('READY')]
            late_ok = df[df['Status'].str.contains('LATE')]
            watch = df[df['Status'].str.contains('WATCH|CAUTION')]
            skip = df[~df['Status'].str.contains('READY|WATCH|CAUTION|LATE')]
            
            # Identify high-quality tickers waiting for signals (Grade A/B but skipped)
            quality_waiting = skip[skip['_grade'].isin(['A', 'B'])]
            low_quality_skip = skip[~skip['_grade'].isin(['A', 'B'])]
            
            # Show summary
            st.markdown(f"""
            ### Scan Results
            - 🟢 **Ready to Trade:** {len(ready)}
            - 🕐 **Late Entry OK:** {len(late_ok)}
            - 🟡 **Watch/Caution:** {len(watch)}
            - ⏳ **Quality Waiting:** {len(quality_waiting)} *(Grade A/B, no signal yet)*
            - 🔴 **Skip:** {len(low_quality_skip)}
            """)
            
            # Ready tickers - with Weekly confirmation warning
            if len(ready) > 0:
                st.success(f"**🎯 Ready to Trade:** {', '.join(ready['Ticker'].tolist())}")
                display_cols = ['Ticker', 'Status', 'Grade', 'Win%', 'Avg Ret', 'Weekly', 'Type', 'MACD✓', 'AO>0', 'AO Cross']
                st.dataframe(ready[display_cols], use_container_width=True, hide_index=True)
                
                # Weekly confirmation warnings
                weekly_bearish = ready[ready['Weekly'] == '🔴']
                if len(weekly_bearish) > 0:
                    st.warning(f"""
                    ⚠️ **Weekly MACD Bearish Warning:** {', '.join(weekly_bearish['Ticker'].tolist())}
                    
                    These have valid daily signals but Weekly MACD is still bearish (🔴).
                    - **Lower conviction** - This is a "New Wave" bet, not a "Re-Entry"
                    - **Consider:** Smaller position size or wait for Weekly confirmation
                    - **Watch for:** Weekly MACD to cross bullish for full confirmation
                    """)
            
            # Late entry tickers - with Weekly warning
            if len(late_ok) > 0:
                st.info(f"**🕐 Late Entry Available:** {', '.join(late_ok['Ticker'].tolist())}")
                display_cols = ['Ticker', 'Status', 'Late', 'Grade', 'Win%', 'Avg Ret', 'Weekly', 'MACD✓', 'AO>0']
                st.dataframe(late_ok[display_cols], use_container_width=True, hide_index=True)
                st.caption("💡 These tickers had a valid signal recently and are still within the entry window")
                
                # Weekly warning for late entries
                late_weekly_bearish = late_ok[late_ok['Weekly'] == '🔴']
                if len(late_weekly_bearish) > 0:
                    st.warning(f"⚠️ **{', '.join(late_weekly_bearish['Ticker'].tolist())}** - Late entry + Weekly bearish = Higher risk")
            
            # Watch tickers
            if len(watch) > 0:
                with st.expander(f"🟡 Watch List ({len(watch)} tickers) - Signal forming"):
                    display_cols = ['Ticker', 'Status', 'Grade', 'Win%', 'Avg Ret', 'Weekly', 'MACD✓', 'AO>0', 'AO Cross']
                    st.dataframe(watch[display_cols], use_container_width=True, hide_index=True)
                    st.caption("These are close to triggering - MACD is bullish but no fresh cross today")
            
            # Quality tickers waiting for signal (NEW SECTION)
            if len(quality_waiting) > 0:
                with st.expander(f"⏳ Quality Watchlist ({len(quality_waiting)} tickers) - Grade A/B waiting for signal"):
                    st.markdown("""
                    **These are HIGH QUALITY tickers** based on backtested performance, 
                    but they don't have a valid entry signal right now. Keep them on your watchlist!
                    """)
                    display_cols = ['Ticker', 'Grade', 'Win%', 'Avg Ret', 'MACD✓', 'AO>0', 'AO Cross', 'Mkt OK']
                    st.dataframe(quality_waiting[display_cols], use_container_width=True, hide_index=True)
                    
                    # Show what's missing for each
                    st.markdown("**What's needed for signal:**")
                    for _, row in quality_waiting.iterrows():
                        missing = []
                        if row['MACD✓'] != '✅':
                            missing.append("MACD cross up")
                        if row['AO>0'] != '✅':
                            missing.append("AO > 0")
                        if row['AO Cross'] != '✅':
                            missing.append("AO zero-cross in last 20d")
                        if row.get('Mkt OK') != '✅':
                            missing.append("Market filter")
                        
                        if missing:
                            st.caption(f"**{row['Ticker']}** ({row['Grade']}, {row['Win%']}): Needs {', '.join(missing)}")
            
            # Low quality skipped tickers
            if len(low_quality_skip) > 0:
                with st.expander(f"🔴 Skipped ({len(low_quality_skip)} tickers) - No signal + Lower quality"):
                    display_cols = ['Ticker', 'Status', 'Grade', 'Win%', 'Avg Ret', 'MACD✓', 'AO>0', 'AO Cross', 'Mkt OK']
                    st.dataframe(low_quality_skip[display_cols], use_container_width=True, hide_index=True)
            
            # Detailed analysis for selected ticker
            st.markdown("---")
            st.subheader("🔬 Detailed Ticker Analysis")
            
            selected_ticker = st.selectbox(
                "Select ticker for detailed analysis",
                options=df['Ticker'].tolist()
            )
            
            if st.button(f"📊 Analyze {selected_ticker} in Detail"):
                with st.spinner(f"Running detailed analysis on {selected_ticker}..."):
                    analysis = analyze_ticker_full(selected_ticker)
                    
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.markdown("### Entry Signal Validation")
                        is_valid = analysis['entry_signal'].get('is_valid', False)
                        checks = analysis['entry_signal'].get('checks', {})
                        st.markdown(format_entry_validation(is_valid, checks))
                    
                    with col2:
                        st.markdown("### Quality Score (Backtest)")
                        quality = analysis.get('quality', {})
                        st.markdown(format_quality_score(quality))
                    
                    # Late entry analysis
                    if LATE_ENTRY_AVAILABLE:
                        st.markdown("---")
                        late_analysis = get_late_entry_analysis(selected_ticker)
                        st.markdown(format_late_entry_status(late_analysis))
                    
                    # Weekly status
                    weekly = analysis.get('weekly_status', {})
                    st.markdown("### Weekly Trend Status")
                    if weekly.get('weekly_bullish'):
                        st.success(f"✅ **Weekly MACD Bullish** - {weekly.get('signal_type', '')}")
                    else:
                        st.warning(f"⚠️ **Weekly MACD Bearish** - {weekly.get('signal_type', '')}")
                    
                    # Overall recommendation
                    st.markdown("### 🎯 Recommendation")
                    rec = analysis.get('recommendation', 'SKIP')
                    summary = analysis.get('summary', '')
                    
                    if rec == 'STRONG BUY':
                        st.success(f"**{rec}**: {summary}")
                    elif rec == 'BUY':
                        st.info(f"**{rec}**: {summary}")
                    elif rec == 'WATCH':
                        st.warning(f"**{rec}**: {summary}")
                    else:
                        st.error(f"**{rec}**: {summary}")
        
        st.markdown("---")
        
        # Display watchlist table
        st.subheader("Current Watchlist")
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


@safe_render
def render_positions_tab(journal):
    """Render the open positions tab"""
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
    
    # Ticker selection OUTSIDE form so it can trigger auto-fill
    st.markdown("**Select or Enter Ticker:**")
    col_ticker1, col_ticker2 = st.columns([1, 1])
    
    with col_ticker1:
        if watchlist_tickers:
            selected_from_list = st.selectbox(
                "From Watchlist", 
                options=[""] + watchlist_tickers,
                key="ticker_select",
                label_visibility="collapsed"
            )
        else:
            st.info("💡 Add tickers to Watchlist tab first, or type manually →")
            selected_from_list = ""
    
    with col_ticker2:
        manual_ticker = st.text_input(
            "Or Type Manually",
            placeholder="e.g., GOOGL",
            key="manual_ticker_input",
            label_visibility="collapsed"
        ).upper()
    
    # Use manual entry if provided, otherwise use dropdown selection
    ticker = manual_ticker if manual_ticker else selected_from_list
    
    # Auto-fill button
    if ticker and ticker not in ["", "Other..."]:
        col_auto1, col_auto2 = st.columns([2, 1])
        with col_auto1:
            if st.button(f"🔄 Auto-Fill Data for {ticker}", use_container_width=True):
                with st.spinner(f"Fetching data for {ticker}..."):
                    # Fetch current price
                    current_price = fetch_current_price(ticker)
                    
                    if current_price:
                        # Calculate ATR
                        atr = calculate_atr_value(ticker)
                        
                        # Calculate stops
                        stop_loss, stop_type = calculate_strategy_stops(current_price, atr)
                        target_price = calculate_profit_target(current_price)
                        
                        # Validate entry conditions
                        is_valid, checks = validate_entry_conditions(ticker)
                        
                        # Store in session state
                        st.session_state['auto_entry_price'] = current_price
                        st.session_state['auto_stop_loss'] = stop_loss
                        st.session_state['auto_target'] = target_price
                        st.session_state['auto_stop_type'] = stop_type
                        st.session_state['auto_atr'] = atr
                        st.session_state['entry_validation'] = (is_valid, checks)
                        
                        st.success(f"✅ Data loaded! Entry: ${current_price:.2f}, Stop ({stop_type}): ${stop_loss:.2f}")
                    else:
                        st.error(f"❌ Could not fetch data for {ticker}")
        
        with col_auto2:
            if st.button("🗑️ Clear", use_container_width=True):
                # Clear auto-fill data
                for key in ['auto_entry_price', 'auto_stop_loss', 'auto_target', 'auto_stop_type', 'auto_atr', 'entry_validation']:
                    if key in st.session_state:
                        del st.session_state[key]
                st.rerun()
    
    # Display entry validation if available
    if 'entry_validation' in st.session_state:
        is_valid, checks = st.session_state['entry_validation']
        validation_msg = format_entry_validation(is_valid, checks)
        
        if is_valid:
            st.success(validation_msg)
        else:
            st.warning(validation_msg)
    
    # Show exit strategy reminder
    with st.expander("📖 TTA Exit Strategy Reminder"):
        st.markdown(get_exit_strategy_note())
    
    st.markdown("---")
    
    # Trade entry form with pre-filled values
    with st.form("enter_trade"):
        col1, col2 = st.columns(2)
        
        # Get auto-filled values or defaults
        default_entry = st.session_state.get('auto_entry_price', 100.0)
        default_stop = st.session_state.get('auto_stop_loss', 85.0)
        default_target = st.session_state.get('auto_target', 120.0)
        stop_type = st.session_state.get('auto_stop_type', '15% Protective')
        atr_value = st.session_state.get('auto_atr')
        
        with col1:
            entry_price = st.number_input("Entry Price", min_value=0.01, value=float(default_entry), step=0.01)
            
            stop_label = f"Stop Loss ({stop_type})"
            stop_loss = st.number_input(stop_label, min_value=0.01, value=float(default_stop), step=0.01)
            
            if atr_value:
                st.caption(f"💡 ATR(14): ${atr_value:.2f}")
        
        with col2:
            target = st.number_input("Target (20% gain)", min_value=0.0, value=float(default_target), step=0.01)
            position_size = st.number_input("Position Size ($)", min_value=1.0, value=1000.0, step=100.0)
            entry_date = st.date_input("Entry Date", value=datetime.now())
        
        notes = st.text_area("Trade Notes", placeholder="Daily MACD cross + AO > 0...", height=80)
        
        enter_btn = st.form_submit_button("🚀 Open Position", type="primary", use_container_width=True)
    
    if enter_btn and ticker and ticker not in ["", "Other..."]:
        # Calculate risk
        risk = entry_price - stop_loss
        risk_pct = (risk / entry_price) * 100
        
        # Validation
        if stop_loss >= entry_price:
            st.error("❌ Stop loss must be below entry price")
        elif risk_pct > 20:
            st.error(f"❌ Risk too high ({risk_pct:.1f}%). TTA strategy uses max 15% stop.")
        else:
            target_val = target if target > 0 else None
            
            # Get entry conditions if they were validated
            entry_conditions_data = None
            if 'entry_validation' in st.session_state:
                is_valid, checks = st.session_state['entry_validation']
                entry_conditions_data = {
                    'validated_at': datetime.now().isoformat(),
                    'all_conditions_met': is_valid,
                    'conditions': checks
                }
            
            result = journal.enter_trade(
                ticker=ticker,
                entry_price=entry_price,
                stop_loss=stop_loss,
                position_size=position_size,
                entry_date=entry_date.strftime('%Y-%m-%d'),
                notes=notes,
                target=target_val,
                entry_conditions=entry_conditions_data
            )
            st.success(result)
            
            # Clear auto-fill data after successful entry
            for key in ['auto_entry_price', 'auto_stop_loss', 'auto_target', 'auto_stop_type', 'auto_atr', 'entry_validation']:
                if key in st.session_state:
                    del st.session_state[key]
            
            st.rerun()


@safe_render
def render_monitor_tab(journal):
    """Render the daily monitoring tab"""
    st.subheader("Daily Monitor - Position Status")
    
    if st.button("🔄 Refresh Prices", type="primary", use_container_width=True):
        with st.spinner("Fetching live prices..."):
            try:
                dashboard = journal.daily_update()
                if dashboard and isinstance(dashboard, dict):
                    st.session_state['dashboard_data'] = dashboard
                    st.success("Prices updated!")
                    st.rerun()
                else:
                    st.error("Failed to fetch prices. Dashboard returned empty.")
            except Exception as e:
                st.error(f"Error fetching prices: {str(e)}")
                st.code(traceback.format_exc())
    
    # Display dashboard if available
    if 'dashboard_data' in st.session_state:
        try:
            dashboard = st.session_state.get('dashboard_data')
            
            # Safety check
            if not dashboard or not isinstance(dashboard, dict):
                st.warning("No dashboard data available. Click 'Refresh Prices' above.")
                if 'dashboard_data' in st.session_state:
                    del st.session_state['dashboard_data']
                return
            
            if dashboard.get('message'):
                st.info(dashboard['message'])
            elif len(dashboard.get('positions', [])) == 0:
                st.info('No open positions')
            else:
                # Summary metrics
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Total Exposure", f"${dashboard.get('total_exposure', 0):,.2f}")
                with col2:
                    pnl = dashboard.get('unrealized_pnl', 0)
                    st.metric("Unrealized P&L", f"${pnl:,.2f}", delta=f"{pnl:+.2f}")
                with col3:
                    exposure = dashboard.get('total_exposure', 1)
                    pnl_pct = (pnl / exposure * 100) if exposure > 0 else 0
                    st.metric("Return %", f"{pnl_pct:+.2f}%")
                
                st.caption(f"Last updated: {dashboard.get('as_of', 'Unknown')}")
                
                # Warnings
                if dashboard.get('warnings'):
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
                if dashboard.get('positions'):
                    pos_df = pd.DataFrame(dashboard['positions'])
                    
                    # Format for display
                    display_data = []
                    for _, row in pos_df.iterrows():
                        status_emoji = "🚨" if row.get('stop_hit') else ("🎯" if row.get('target_hit') else "✅")
                        
                        display_data.append({
                            'Status': status_emoji,
                            'Ticker': row.get('ticker', ''),
                            'Entry': f"${row.get('entry_price', 0):.2f}",
                            'Current': f"${row.get('current_price', 0):.2f}",
                            'P&L $': f"${row.get('pnl_dollar', 0):.2f}",
                            'P&L %': f"{row.get('pnl_percent', 0):+.1f}%",
                            'Stop': f"${row.get('stop_loss', 0):.2f}",
                            'Dist to Stop': f"{row.get('distance_to_stop', 0):.1f}%"
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
                        if 'dashboard_data' in st.session_state:
                            del st.session_state['dashboard_data']
                        st.rerun()
        except Exception as e:
            st.error(f"Error displaying dashboard: {str(e)}")
            st.code(traceback.format_exc())
            if 'dashboard_data' in st.session_state:
                del st.session_state['dashboard_data']
    else:
        st.info("Click 'Refresh Prices' to load current position status")


@safe_render
def render_performance_tab(journal):
    """Render the performance summary tab"""
    st.subheader("Performance Summary")
    
    perf = journal.get_performance_summary()
    
    if not perf or perf.get('message'):
        st.info(perf.get('message', 'No performance data available'))
    else:
        # Key metrics
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Trades", perf.get('total_trades', 0))
            st.metric("Winners", perf.get('winners', 0))
        
        with col2:
            st.metric("Win Rate", f"{perf.get('win_rate', 0):.1f}%")
            st.metric("Losers", perf.get('losers', 0))
        
        with col3:
            st.metric("Total P&L", f"${perf.get('total_pnl', 0):,.2f}")
            st.metric("Avg Return", f"{perf.get('avg_return', 0):.1f}%")
        
        with col4:
            st.metric("Expectancy", f"{perf.get('expectancy', 0):.2f}R")
            st.metric("Profit Factor", f"{perf.get('profit_factor', 0):.2f}")
        
        st.markdown("---")
        
        # Win/Loss details
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("### 🏆 Average Winner")
            st.metric("Avg Win", f"${perf.get('avg_win', 0):,.2f}")
            
            if perf.get('best_trade'):
                st.markdown("**Best Trade:**")
                best = perf['best_trade']
                st.write(f"**{best.get('ticker', 'N/A')}**: ${best.get('pnl', 0):,.2f} ({best.get('return', 0):+.1f}%)")
        
        with col2:
            st.markdown("### 📉 Average Loser")
            st.metric("Avg Loss", f"${perf.get('avg_loss', 0):,.2f}")
            
            if perf.get('worst_trade'):
                st.markdown("**Worst Trade:**")
                worst = perf['worst_trade']
                st.write(f"**{worst.get('ticker', 'N/A')}**: ${worst.get('pnl', 0):,.2f} ({worst.get('return', 0):+.1f}%)")


@safe_render
def render_history_tab(journal):
    """Render the trade history tab"""
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
    try:
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
            st.sidebar.metric("Win Rate", f"{perf.get('win_rate', 0):.0f}%")
            st.sidebar.metric("Total P&L", f"${perf.get('total_pnl', 0):,.0f}")
    except Exception as e:
        st.sidebar.error(f"Journal error: {str(e)}")
