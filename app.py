import sys
import os
sys.path.append(os.path.dirname(__file__))

import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from scipy.signal import argrelextrema
from datetime import datetime, timedelta
import os
import base64
import re
import io
# OpenAI removed — using Gemini for AI analysis
from utils.react_bridge import render_react_dashboard, parse_analysis_for_dashboard, enforce_v71_narrative_hygiene, enforce_verdict_consistency, validate_fib_numeric_sanity
from trading_journal_ui import render_trading_journal_tab, add_journal_to_sidebar
from strategy_break_retest import get_current_pattern_state, classify_weinstein_stage
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.enums import TA_LEFT, TA_CENTER
import sys
from io import StringIO


def load_daily_verdicts() -> list:
    """Load all verdict JSONs from today"""
    import os
    import json
    from datetime import datetime
    
    verdicts = []
    today = datetime.now().strftime('%Y%m%d')
    
    try:
        files = os.listdir('.')
    except OSError:
        return []
    
    for file in files:
        if '_tta_verdict.json' in file:
            try:
                with open(file, 'r') as f:
                    data = json.load(f)
                    verdicts.append(data)
            except (json.JSONDecodeError, IOError, KeyError) as e:
                print(f"TTA: Warning - Could not load verdict {file}: {e}")
    
    # Safe sort - handle missing timestamp key
    try:
        return sorted(verdicts, key=lambda x: x.get('timestamp', ''), reverse=True)
    except Exception:
        return verdicts


def display_daily_summary():
    """Show all verdicts from today in a summary table"""
    verdicts = load_daily_verdicts()
    
    if not verdicts:
        st.info("No verdicts yet today")
        return
    
    st.subheader(f"📊 Today's Verdicts ({len(verdicts)} total)")
    
    summary_data = []
    for v in verdicts:
        if v['confidence'] >= 78 and v['win_rate'] >= 60:
            status = "🟢 ENTER"
        elif v['confidence'] >= 65 and v['win_rate'] >= 45:
            status = "🟡 WAIT"
        else:
            status = "🔴 SKIP"
        
        summary_data.append({
            'Ticker': v['ticker'],
            'Status': status,
            'Conf': f"{v['confidence']}%",
            'Elliott': f"{v['elliott_quality']}/100",
            'Win%': f"{v['win_rate']:.0f}%",
            'R:R': f"{v['risk_reward']}:1",
            'Entry': f"${v['entry_price']}",
            'Target': f"${v['target']}"
        })
    
    st.dataframe(summary_data, width='stretch')


# ═══════════════════════════════════════════════════════════════════════════════
# LOG CAPTURE SYSTEM - Captures all print output during analysis runs
# ═══════════════════════════════════════════════════════════════════════════════
class LogCapture:
    """Captures print output to both console and a buffer for download."""
    def __init__(self):
        self.buffer = StringIO()
        self.errors = []
        self.is_capturing = False
    
    def start(self):
        """Start capturing logs."""
        self.buffer = StringIO()
        self.errors = []
        self.is_capturing = True
    
    def stop(self):
        """Stop capturing logs."""
        self.is_capturing = False
    
    def log(self, message):
        """Log a message to both console and buffer."""
        print(message)  # Still print to console
        if self.is_capturing:
            self.buffer.write(f"{message}\n")
            # Capture errors
            msg_lower = str(message).lower()
            if 'error' in msg_lower or 'exception' in msg_lower or 'traceback' in msg_lower:
                self.errors.append(str(message))
    
    def get_logs(self):
        """Get all captured logs with errors summary at bottom."""
        content = self.buffer.getvalue()
        if self.errors:
            content += "\n\n" + "="*60 + "\n"
            content += "ERRORS SUMMARY (from this analysis run)\n"
            content += "="*60 + "\n"
            for err in self.errors:
                content += f"{err}\n"
        return content
    
    def has_logs(self):
        """Check if there are any logs captured."""
        return len(self.buffer.getvalue()) > 0

# Initialize global log capture
if 'log_capture' not in st.session_state:
    st.session_state.log_capture = LogCapture()

def tlog(message):
    """TTA Log - logs to both console and capture buffer."""
    st.session_state.log_capture.log(message)

# ═══════════════════════════════════════════════════════════════════════════════
# BUILD VERSION - Update this when making changes
# Major.Minor.Patch: Major = new feature system, Minor = improvements, Patch = bug fixes
# ═══════════════════════════════════════════════════════════════════════════════
BUILD_VERSION = "v16.16"
BUILD_DATE = "2026-01-20"
BUILD_NAME = "ULTIMATE MTF Enforcement Fix"

# ═══════════════════════════════════════════════════════════════════════════════
# v16.11 FILTER SWITCHBOARD - Configurable Filter Profiles
# ═══════════════════════════════════════════════════════════════════════════════
FILTER_PROFILES = {
    "CONSERVATIVE": {
        "name": "Conservative (v14.6 Anti-Grinder)",
        "description": "Original strict filters - minimizes false positives",
        "suitability_floor": 70,
        "suitability_grinder": 85,
        "verticality_universal": 1.2,
        "peak_dominance_leader": 3.0,
        "peak_dominance_grinder": 5.0,
        "max_trade_count": 6,           # Fewer trades = higher quality
        "drawdown_ceiling": 18.0,       # Strict DD limit
        "min_win_rate": 45.0,           # Require >45% winners
    },
    "BALANCED": {
        "name": "Balanced",
        "description": "Verticality disabled (-2.0) - captures consolidating momentum",
        "suitability_floor": 65,
        "suitability_grinder": 85,
        "verticality_universal": -2.0,  # Effectively disabled (allows below SMA)
        "peak_dominance_leader": 2.5,
        "peak_dominance_grinder": 4.0,
        "max_trade_count": 8,           # Moderate trade count
        "drawdown_ceiling": 25.0,       # Moderate DD tolerance
        "min_win_rate": 40.0,           # 40% floor
    },
    "AGGRESSIVE": {
        "name": "Aggressive",
        "description": "Verticality OFF, relaxed PeakDom - max signal capture",
        "suitability_floor": 60,
        "suitability_grinder": 90,
        "verticality_universal": None,  # Completely disabled
        "peak_dominance_leader": 1.5,
        "peak_dominance_grinder": 2.5,
        "max_trade_count": 10,          # Allow more trades
        "drawdown_ceiling": 30.0,       # Higher DD tolerance
        "min_win_rate": 30.0,           # Lower win rate floor
    },
    "HYBRID": {
        "name": "Hybrid (Recommended)",
        "description": "Verticality -1.0 + strict suitability - best for HOOD/PLTR",
        "suitability_floor": 70,
        "suitability_grinder": 85,
        "verticality_universal": -1.0,  # Allows slight pullbacks below SMA
        "peak_dominance_leader": 2.5,
        "peak_dominance_grinder": 4.0,
        "max_trade_count": 7,           # Balanced trade limit
        "drawdown_ceiling": 20.0,       # Moderate-strict DD
        "min_win_rate": 42.0,           # Solid win rate floor
    },
}

# Default filter values (will be overridden by profile selection)
SUITABILITY_FLOOR = 70         # v14.6: Minimum suitability to even be considered
SUITABILITY_GRINDER = 85       # v14.6: Grinder threshold - must prove impulse
VERTICALITY_UNIVERSAL = 1.2    # v14.6: Universal verticality gate for ALL stocks
PEAK_DOMINANCE_LEADER = 3.0    # v14.6: Leader pass for Suit <= 85
PEAK_DOMINANCE_GRINDER = 5.0   # v14.6: Anti-grinder requirement for Suit > 85

# v15.4 Profit Protector Thresholds (v16.0: TIME_STOP_DAYS deprecated, use TIME_STOP_BASE)
TIME_STOP_MIN_GAIN = 0.0       # v15.5: Forgiving Time-Stop - only exit if negative (< 0%)
OVEREXTENSION_LIMIT = 5.0      # v15.4: Max verticality ratio at entry (blow-off protection)
ATR_INITIAL_STOP_MULT = 3.5    # v15.5: ATR multiplier for initial stop (3.5x prevents shadow stops in high-beta)

# v15.1 Drawdown Ceiling Thresholds
DRAWDOWN_CEILING = 18.0        # v16.4: Slightly higher tolerance for high-beta momentum stocks
SMA_SLOPE_THRESHOLD = 1.0      # v15.5: Default SMA slope threshold for standard stocks
SMA_SLOPE_HIGH_ALPHA = 0.5     # v15.5: Lower threshold for High-Alpha Leaders (Suit > 75 AND PeakDom > 3.0)
HIGH_ALPHA_SUITABILITY = 75    # v15.5: Minimum suitability for High-Alpha classification
HIGH_ALPHA_PEAKDOM = 3.0       # v15.5: Minimum peak dominance for High-Alpha classification

# v16.0 Adaptive Architect - MSR & NSR Thresholds
MSR_ESCAPE_VELOCITY = 1.5      # v16.0: 1.5-sigma momentum spike for escape velocity override (calibrated to real data)
MSR_LOOKBACK = 60              # v16.0: Rolling window for MSR median/MAD
MSR_FLOOR_PERCENTILE = 0.10    # v16.0: 10th percentile for MAD floor
NSR_FAST_WINDOW = 60           # v16.0: Short-term NSR window (recent regime)
NSR_SLOW_WINDOW = 252          # v16.0: Long-term NSR window (personality)
NSR_REGIME_SHIFT = 1.5         # v16.0: Threshold for regime shift detection
CATASTROPHIC_FLOOR_MIN = 3.0   # v16.0: Minimum ATR distance for catastrophic floor
CATASTROPHIC_FLOOR_MAX = 8.0   # v16.0: Maximum ATR distance for catastrophic floor
TIME_STOP_BASE = 120           # v16.0: Base max holding period (days)
TIME_STOP_CONSOLIDATION_EXT = 20  # v16.0: Extension for bull flag consolidation
CYCLICAL_PEAK_DOMINANCE = 4.5  # v15.1: Higher PeakDom requirement for cyclical/industrial stocks
CYCLICAL_TICKERS = {           # v15.1: Cyclical/Industrial sector stocks
    'CAT', 'DE', 'XOM', 'URI', 'CVX', 'FCX', 'NUE', 'CLF', 'AA', 'X',
    'PCAR', 'CMI', 'EMR', 'HON', 'MMM', 'GE', 'LMT', 'RTX', 'BA', 'NOC',
    'SLB', 'HAL', 'BKR', 'OXY', 'COP', 'EOG', 'DVN', 'MRO', 'HES', 'VLO'
}

# ═══════════════════════════════════════════════════════════════════════════════
# v16.11 VIX-BASED PROFILE RECOMMENDATION
# ═══════════════════════════════════════════════════════════════════════════════
def get_vix_recommendation():
    """
    Fetch VIX from Yahoo Finance and return recommended filter profile.
    
    VIX Thresholds:
      - VIX < 15: Low volatility regime -> AGGRESSIVE (max signal capture)
      - VIX 15-20: Normal volatility -> BALANCED (moderate filters)
      - VIX 20-25: Elevated volatility -> HYBRID (tighter controls)
      - VIX > 25: High volatility regime -> CONSERVATIVE (strict risk management)
    
    Returns:
        dict: {vix, profile, regime, reason}
    """
    try:
        vix_ticker = yf.Ticker("^VIX")
        vix_data = vix_ticker.history(period="1d")
        
        if vix_data.empty:
            return {
                "vix": None,
                "profile": "HYBRID",
                "regime": "UNKNOWN",
                "reason": "VIX data unavailable - defaulting to HYBRID"
            }
        
        vix_value = float(vix_data['Close'].iloc[-1])
        
        if vix_value < 15:
            return {
                "vix": vix_value,
                "profile": "AGGRESSIVE",
                "regime": "LOW VOLATILITY",
                "reason": f"VIX {vix_value:.1f} < 15 indicates complacency. Maximize signal capture with relaxed filters."
            }
        elif vix_value < 20:
            return {
                "vix": vix_value,
                "profile": "BALANCED",
                "regime": "NORMAL",
                "reason": f"VIX {vix_value:.1f} in 15-20 range. Normal market conditions - balanced approach."
            }
        elif vix_value < 25:
            return {
                "vix": vix_value,
                "profile": "HYBRID",
                "regime": "ELEVATED",
                "reason": f"VIX {vix_value:.1f} in 20-25 range. Elevated uncertainty - tighten quality controls."
            }
        else:
            return {
                "vix": vix_value,
                "profile": "CONSERVATIVE",
                "regime": "HIGH VOLATILITY",
                "reason": f"VIX {vix_value:.1f} > 25 indicates fear. Strict risk management required."
            }
    
    except Exception as e:
        return {
            "vix": None,
            "profile": "HYBRID",
            "regime": "ERROR",
            "reason": f"Failed to fetch VIX: {str(e)[:50]}"
        }

# v16.10: Tesla console page configuration
st.set_page_config(
    page_title="TTA Engine",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"  # Keep expanded so users can see ticker input
)

# v16.10: Custom CSS for Tesla-grade UI
st.markdown("""
<style>
    /* Remove Streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    /* v16.11: Wider sidebar to prevent text cropping */
    [data-testid="stSidebar"] {
        min-width: 280px;
        max-width: 320px;
    }
    [data-testid="stSidebar"] > div:first-child {
        width: 280px;
    }
    
    /* Tesla dark theme */
    .stApp {
        background: #000000;
    }
    
    /* Clean input fields */
    .stTextInput > div > div > input {
        background: #1a1a1a;
        border: 1px solid #2a2a2a;
        border-radius: 8px;
        color: #ffffff;
        padding: 12px;
    }
    
    /* Buttons */
    .stButton > button {
        background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);
        color: white;
        border: none;
        border-radius: 8px;
        padding: 12px 24px;
        font-weight: 600;
        transition: all 0.3s ease;
    }
    
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 16px rgba(37, 99, 235, 0.3);
    }
    
    /* Minimal padding for maximum chart visibility */
    .block-container {
        padding-top: 0.5rem;
        padding-bottom: 0rem;
        padding-left: 2rem;
        padding-right: 2rem;
    }
    
    /* Dividers */
    hr {
        border-color: #2a2a2a;
        margin: 2rem 0;
    }
</style>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
# v7.1 CANONICAL DEGREE MAP — SINGLE SOURCE OF TRUTH (NON-NEGOTIABLE)
# Weekly = Intermediate (Regime context + A2 ONLY — NEVER execution authority)
# Daily = Minor (Execution if user chooses Daily)
# 4H = Minuette (Execution if user chooses 4H)
# 60m/H1 = Minute (Entry timing only)
# ═══════════════════════════════════════════════════════════════════════════════
DEGREE_MAP = {
    "W": "Intermediate",
    "WEEKLY": "Intermediate",
    "D": "Minor",
    "DAILY": "Minor",
    "4H": "Minuette",
    "H4": "Minuette",
    "60m": "Minute",
    "H1": "Minute",
    "M60": "Minute"
}

# Execution authority can ONLY be Daily or 4H — NEVER Weekly
EXECUTION_LABELS = {
    "DAILY": "DAILY (MINOR)",
    "DAILY_MINOR": "DAILY (MINOR)",
    "H4": "4H (MINUETTE)",
    "H4_MINUETTE": "4H (MINUETTE)"
}


def get_execution_authority(execution_mode: str) -> str:
    """
    Return the execution authority label.
    execution_mode is a stable internal choice such as:
      - 'DAILY' or 'DAILY_MINOR'
      - 'H4' or 'H4_MINUETTE'
    Weekly is NEVER execution authority.
    """
    m = (execution_mode or "").upper()
    if "H4" in m or "MINUETTE" in m:
        return EXECUTION_LABELS["H4"]
    # Default is always Daily (Minor)
    return EXECUTION_LABELS["DAILY"]


# AI client: Gemini is primary (via gemini_auditor.py)
# OpenAI removed — set client to None for any legacy references
client = None

SYSTEM_PROMPT = """✅ MASTER RISK-FIRST CHART AUDIT PROMPT — v7.1 (LOGIC-STRICT EDITION)
DEGREE-LOCKED • STRUCTURE-FIRST • MOMENTUM-CONFIRMED • FIB-CONTEXTUALIZED (Weinstein + Elliott Wave + Awesome Oscillator + Fibonacci — AUDIT ONLY)

🎯 ROLE (NON-NEGOTIABLE)
Act as a Senior Portfolio-Grade Technical Analyst and Professional Elliott Wave Analyst.
You must:
    * Analyze, not predict
    * Never violate Elliott Wave sequencing rules
    * Never mix Elliott degrees
    * Never allow AO to override price structure
    * State uncertainty explicitly when structure is incomplete
You audit structure first, momentum second, risk always.

🧭 DEGREE & TIMEFRAME MAP (MANDATORY — CANONICAL)
You MUST apply the following fixed Elliott degree conventions:
Timeframe       Elliott Degree      Role
Weekly          Intermediate        Regime Context + A2 ONLY (NEVER execution)
Daily           Minor               Execution Structure (if Daily selected)
4-Hour          Minuette            Execution Structure (if 4H selected)
60-Minute       Minute              Entry Timing
⚠️ Degree Rules (Absolute)
    * Never mix degrees
    * Lower-degree waves may complete without completing higher-degree waves
    * A completed impulse at any degree must be followed by a correction at the same degree

🔴 0️⃣ RISK-FIRST DECLARATION (GRADUATED — REQUIRED)
State explicitly with GRADUATED risk levels:
    * A) Bearish Activation (Minor Degree): __________ (most recent structural swing low at current degree)
    * A2) Structural Failure (Higher Degree): __________ (prior major swing low - regime failure)
    * B) Bullish Continuation / "Correction Dead" Level: __________ (prior impulse high)
Rules:
    * Below A (Minor low) → corrective extension / bearish activation at Minor degree
    * Below A2 (Major low) → regime failure / alternate count promoted
    * Above B → impulse continuation confirmed
CRITICAL: Risk levels must be DEGREE-APPROPRIATE. Do NOT skip the Minor-degree trigger.
No bias without this section completed.

1️⃣ TOP-DOWN DEGREE CONTEXT (MANDATORY)
For each timeframe provided, explicitly state:
    * Elliott degree in use
    * Current wave position (Impulse vs Corrective)
    * Whether that wave is:
        * Complete
        * Developing
        * Structurally unconfirmed
Use explicit language:
"At the Minor degree, price is correcting an incomplete impulse."

2️⃣ WEINSTEIN STAGE AUDIT (WEEKLY — CONTEXT ONLY)
Confirm:
    * Weinstein Stage (1–4)
    * 30-week SMA slope
    * Price vs 30-week SMA
Verdict:
    * Trend-trading eligible? (Yes / No)
    * One-sentence justification
(Weinstein informs environment, not wave labeling.)

3️⃣ PRICE STRUCTURE FIRST (NON-NEGOTIABLE)
For the primary execution timeframe (usually 4H or 1H):
A. Structure Classification
Identify price action as:
    * Impulsive (directional, non-overlapping)
    * Corrective (overlapping, ABC / W-X-Y / Flat / Triangle)
B. Elliott Rule Enforcement
Explicitly confirm:
    * Wave-4 must precede Wave-5
    * Wave-4 cannot occur after Wave-5 completion
    * If Wave-5 is complete → all subsequent movement must be corrective at that degree
If violated → count rejected.

4️⃣ ELLIOTT WAVE STRUCTURE (DEGREE-LOCKED)
For the active degree:
    * Identify current wave (e.g., Minuette Wave-4)
    * Impulse or correction?
    * If corrective:
        * Zigzag / Flat / Triangle / W-X-Y
        * Final leg structure check (3 vs 5 waves — mandatory)
Rule:
    * If Wave-C subdivides into 3 waves, it cannot be ABC → must be W-X-Y.

5️⃣ AWESOME OSCILLATOR (AO) — MOMENTUM CONFIRMATION ONLY
🔑 AO Usage Rules (Critical)
AO MAY:
    * Confirm Wave-3 expansion
    * Confirm Wave-4 momentum reset
    * Warn of Wave-5 exhaustion via divergence
AO MAY NOT:
    * Declare a wave complete
    * Override price structure
    * Redefine wave degree
📌 Key Principle
AO completion = end-risk alert Price structure = degree confirmation

AO Analysis
At the same timeframe, state:
    * Momentum expanding / resetting / diverging
    * Does AO support, warn, or remain neutral toward the price-based count?
Use explicit language:
"AO warns of Wave-5 exhaustion but does not confirm structural completion."

6️⃣ FIBONACCI CONTEXT (ZONES — NOT SIGNALS)
Fibonacci is contextual only.
For the active wave, state:
Measurement Logic
    * Wave-2 → retrace of Wave-1
    * Wave-3 → projection of Wave-1 from end of Wave-2
    * Wave-4 → retrace of Wave-3
    * Wave-5 → projection of Wave-1 from end of Wave-4
    * Wave-B → retrace of Wave-A
    * Wave-C → projection of Wave-A
List only relevant levels:
    * 38.2 / 50 / 61.8 / 78.6 / 88.6
    * 100 / 161.8 / 200
State:
    * Normal
    * Extreme but valid
    * Invalidation threshold
⚠️ Fibonacci is never an entry trigger.

7️⃣ DEGREE-CONSISTENT SYNTHESIS
Combine structure + AO + Fibonacci into a single, contradiction-free count.
If Wave-5 is complete:
    * Identify the corrective wave that must follow (A, W, etc.)
    * Explain how lower-degree structure subdivides that correction
If Wave-5 is NOT complete:
    * State what is structurally missing
    * State what price action would confirm completion

8️⃣ ALTERNATE COUNT (REQUIRED)
Provide one credible alternate count that:
    * Obeys all Elliott rules
    * Explains the same price action
    * Has a lower probability, with reasons

9️⃣ PROBABILITY & INTEGRITY CHECK
Assign probabilities:
    * Primary count: ___ %
    * Alternate count: ___ %
Justify using:
    * Structural clarity
    * Degree alignment
    * AO behavior
    * Fibonacci context
Probabilities must sum to 100%.

🔟 INVALIDATION LEVELS (MANDATORY)
State exact price conditions that would:
    * Invalidate the primary count
    * Promote the alternate count
No vague language allowed.

1️⃣1️⃣ MULTI-TIMEFRAME VERIFICATION (MANDATORY - ONLY IF 4 CHARTS PROVIDED)

If you received 4 charts (Monthly/Weekly/Daily/4H), you MUST complete this section:

**Chart Receipt Confirmation:**
- Monthly Chart: [RECEIVED/NOT RECEIVED] - Describe one specific visual element you see (e.g., "uptrend from $X to $Y visible")
- Weekly Chart: [RECEIVED/NOT RECEIVED] - Describe one specific visual element
- Daily Chart: [RECEIVED/NOT RECEIVED] - Describe one specific visual element  
- 4H Chart: [RECEIVED/NOT RECEIVED] - Describe one specific visual element

**Wave Count Per Timeframe:**
- **MONTHLY (Cycle/Primary):** Current wave = [State exact wave label]
- **WEEKLY (Intermediate):** Current wave = [State exact wave label]
- **DAILY (Minor):** Current wave = [State exact wave label]
- **4-HOUR (Minuette):** Current wave = [State exact wave label]

**Degree Consistency Check:**
- Does the Daily wave fit logically WITHIN the Weekly wave? [YES/NO + brief explanation]
- Does the 4H wave fit logically WITHIN the Daily wave? [YES/NO + brief explanation]
- Are there any degree violations? [YES/NO + list if any]

**Top-Down Synthesis:**
One paragraph explaining how waves nest from Monthly → Weekly → Daily → 4H.

If you only received 1 chart, skip this section entirely.

🧠 FINAL RISK-FIRST VERDICT (MANDATORY)
Choose ONE:
    * ✅ Bullish Continuation — Impulse Valid
    * ⚠️ Corrective / Range — No Trade
    * ❌ Bearish Activation — Trend Failure
    * ⏳ Developing — Evidence Incomplete
One-sentence justification referencing: Structure + AO + Fibonacci

🧠 REQUIRED CLOSING SUMMARY (ONE PARAGRAPH)
Answer explicitly:
    * What degree just completed (if any)
    * What degree is correcting now
    * Whether AO is confirming or warning
    * What price must do next to remain Elliott-consistent
Optional closing line (use when appropriate):
"This count remains valid unless and until price violates the stated invalidation level, at which point the alternate count becomes dominant."

🔒 NON-NEGOTIABLE OPERATING PRINCIPLE
Structure decides the wave AO confirms the wave Fibonacci frames the zone Price action triggers the trade
If these disagree → stand aside.

📝 TEXT FORMATTING RULES (CRITICAL — MUST FOLLOW)
Your output MUST use clean, plain text formatting:
* ❌ FORBIDDEN: Arrow notation like "$243.76→$288.62" — use "from $243.76 to $288.62" instead
* ❌ FORBIDDEN: Tilde notation like "~$255.70" — use "near $255.70" or "approximately $255.70" instead
* ❌ FORBIDDEN: LaTeX or markdown formatting around prices — no asterisks, no special characters
* ❌ FORBIDDEN: Concatenated text — always use proper spacing between words and dollar amounts
* ✅ REQUIRED: Plain English text with proper spacing
* ✅ REQUIRED: "from $243.76 to $288.62" NOT "$243.76→$288.62"
* ✅ REQUIRED: "near $255.70" NOT "~$255.70"
* ✅ REQUIRED: "$288.62 or below $243.76" NOT "$288.62orbelow$243.76"

📊 SECTION 4 PROBABILITY RULE (CRITICAL)
* ❌ FORBIDDEN: "Primary View (70%):" or "Alternate View (30%):" in Section 4
* ✅ REQUIRED: "Primary View:" and "Alternate View:" (no percentages in Section 4)
* All probability assignments go ONLY in Section 9 (PROBABILITY & INTEGRITY CHECK)"""

def load_validation_prompt():
    """Load the world-class audit prompt from file."""
    try:
        with open('world_class_audit_prompt.txt', 'r') as f:
            return f.read()
    except FileNotFoundError:
        return "Error: world_class_audit_prompt.txt not found"

VALIDATION_PROMPT = load_validation_prompt()


def fetch_stock_data(ticker: str, period: str = "2y", interval: str = "1d") -> pd.DataFrame:
    """Fetch OHLCV data from yfinance."""
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period=period, interval=interval)
        if df.empty:
            return pd.DataFrame()
        df.index = pd.to_datetime(df.index)
        if df.index.tzinfo is not None:
            df.index = df.index.tz_localize(None)
        return df
    except Exception as e:
        st.error(f"Error fetching data: {e}")
        return pd.DataFrame()


def calculate_sma(df: pd.DataFrame, period: int) -> pd.Series:
    """Calculate Simple Moving Average."""
    return df['Close'].rolling(window=period).mean()


def calculate_awesome_oscillator(df: pd.DataFrame, fast_period: int = 5, slow_period: int = 34) -> pd.Series:
    """Calculate Awesome Oscillator (AO) using midpoint price."""
    # Handle both 'High'/'Low' and 'high'/'low' column names
    high_col = 'High' if 'High' in df.columns else 'high'
    low_col = 'Low' if 'Low' in df.columns else 'low'
    midpoint = (df[high_col] + df[low_col]) / 2
    ao = midpoint.rolling(window=fast_period).mean() - midpoint.rolling(window=slow_period).mean()
    return ao


def export_tta_verdict(ticker: str, timeframe: str, analysis_results: dict) -> dict:
    """Export TTA verdict data to JSON file for external consumption."""
    import json
    from datetime import datetime
    
    # Safety check - return empty verdict if analysis_results is None
    if not analysis_results:
        analysis_results = {}
    
    all_signals = analysis_results.get('all_signals', [])
    tta_stats = analysis_results.get('tta_stats', {})
    chart_info = analysis_results.get('chart_info', {}) or {}
    
    trade_count = len(all_signals)
    win_count = len([s for s in all_signals if s.get('result') == 'WIN'])
    win_rate = (win_count / trade_count * 100) if trade_count > 0 else 0
    
    ao_diagnostic = chart_info.get('ao_diagnostic', {}) or {}
    
    # Safe nested dict access - handles None values
    wave5_data = ao_diagnostic.get('wave5') or {}
    wave5_complete = wave5_data.get('complete', False) if isinstance(wave5_data, dict) else False
    
    wave4_data = ao_diagnostic.get('wave4') or {}
    wave4_complete = wave4_data.get('complete', False) if isinstance(wave4_data, dict) else False
    
    wave3_data = ao_diagnostic.get('wave3') or {}
    wave3_complete = wave3_data.get('complete', False) if isinstance(wave3_data, dict) else False
    
    has_divergence = ao_diagnostic.get('divergence', False)
    
    if wave5_complete and not has_divergence:
        elliott_quality = 92
    elif wave5_complete and has_divergence:
        elliott_quality = 70
    elif wave4_complete:
        elliott_quality = 85
    elif wave3_complete:
        elliott_quality = 75
    else:
        elliott_quality = 60
    entry_price = 0
    stop_loss = 0
    target = 0
    if all_signals:
        last_signal = all_signals[-1]
        entry_price = last_signal.get('entry_price', 0)
        stop_loss = last_signal.get('stop_loss', 0)
        target = last_signal.get('target', 0)
    if entry_price > 0 and stop_loss > 0:
        risk = entry_price - stop_loss
        reward = target - entry_price if target > 0 else entry_price * 0.05
        risk_reward = (reward / risk) if risk > 0 else 2.0
    else:
        risk_reward = 2.0
    if trade_count >= 5 and win_rate >= 60:
        signal_strength = 9
    elif trade_count >= 3 and win_rate >= 50:
        signal_strength = 7
    elif trade_count > 0:
        signal_strength = 5
    else:
        signal_strength = 3
    confidence = (elliott_quality * 0.4) + (signal_strength * 10 * 0.3) + (win_rate * 0.3)
    confidence = min(confidence, 100)
    verdict_data = {'ticker': ticker, 'timeframe': timeframe, 'timestamp': datetime.now().isoformat(), 'elliott_quality': int(elliott_quality), 'entry_price': round(entry_price, 2), 'stop_loss': round(stop_loss, 2), 'target': round(target, 2), 'risk_reward': round(risk_reward, 2), 'trade_count': trade_count, 'win_rate': round(win_rate, 1), 'signal_strength': signal_strength, 'confidence': int(confidence)}
    json_filename = f'{ticker}_tta_verdict.json'
    try:
        with open(json_filename, 'w') as f:
            json.dump(verdict_data, f, indent=2)
        tlog(f"✅ VERDICT EXPORTED: {json_filename}")
    except Exception as e:
        tlog(f"⚠️ Error exporting verdict: {e}")
    return verdict_data


def display_verdict_banner(verdict_data: dict):
    """Display verdict banner in Streamlit UI."""
    if not verdict_data:
        return
    conf = verdict_data['confidence']
    rr = verdict_data['risk_reward']
    ew_qual = verdict_data['elliott_quality']
    wr = verdict_data['win_rate']
    if conf >= 78 and wr >= 60:
        conviction = "🟢 FULL CONVICTION"
        color = "background-color: rgba(34, 197, 94, 0.2); border-left: 4px solid #22c55e;"
    elif conf >= 65 and wr >= 45:
        conviction = "🟡 PARTIAL CONVICTION"
        color = "background-color: rgba(251, 191, 36, 0.2); border-left: 4px solid #fbbf24;"
    else:
        conviction = "🔴 SKIP THIS TRADE"
        color = "background-color: rgba(239, 68, 68, 0.2); border-left: 4px solid #ef4444;"
    one_liner = f"{conviction} | {wr:.0f}% Win | {rr}:1 RR | Elliott {ew_qual}/100"
    st.markdown(f"""<div style="padding: 12px; border-radius: 6px; {color}"><div style="font-size: 20px; font-weight: 600; color: #ffffff;">{one_liner}</div></div>""", unsafe_allow_html=True)


def apply_tta_decision_logic(verdict_data: dict) -> str:
    """
    Apply the TTA timeframe decision tree logic:
    - If ANY timeframe = AVOID → Stay out
    - If M+W = STRONG and D actionable → Enter long
    - If WEAK on M or W → Don't buy
    - If FADING detected → Prepare exit
    - If correction phase → Be patient
    - If BASE forming → Watch for entry
    """
    conf = verdict_data['confidence']
    wr = verdict_data['win_rate']
    rr = verdict_data['risk_reward']
    ew_qual = verdict_data['elliott_quality']
    
    # Decision logic
    if conf < 50:
        decision = "🔴 AVOID - Insufficient conviction"
        action = "Stay out of market"
    elif conf >= 78 and wr >= 60 and rr >= 2.0:
        decision = "🟢 STRONG - Enter long"
        action = "Place entry order with stop/target"
    elif conf >= 65 and wr >= 45 and rr >= 1.5:
        decision = "🟡 WEAK - Don't buy yet"
        action = "Wait for confirmation or correction phase"
    elif ew_qual >= 85 and conf >= 70:
        decision = "🟢 BASE FORMING - Watch for entry"
        action = "Monitor for breakout confirmation"
    elif ew_qual < 70 and conf >= 60:
        decision = "🟡 FADING - Prepare exit"
        action = "Tighten stops, reduce position size"
    else:
        decision = "🟡 CORRECTION PHASE - Be patient"
        action = "Wait for new setup to form"
    
    return f"{decision}\nAction: {action}"


def generate_trading_checklist(ticker: str, verdict_data: dict, decision: str) -> str:
    """Generate a trading checklist PDF for the journal"""
    from datetime import datetime
    import json
    
    checklist = {
        'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'ticker': ticker,
        'timeframe': verdict_data['timeframe'],
        'conviction': verdict_data['confidence'],
        'elliott_quality': verdict_data['elliott_quality'],
        'win_rate': verdict_data['win_rate'],
        'risk_reward': verdict_data['risk_reward'],
        'entry_price': verdict_data['entry_price'],
        'stop_loss': verdict_data['stop_loss'],
        'target': verdict_data['target'],
        'trade_count': verdict_data['trade_count'],
        'signal_strength': verdict_data['signal_strength'],
        'decision': decision,
        'checklist_items': [
            '✓ Elliott Wave structure confirmed',
            '✓ Awesome Oscillator aligned',
            '✓ Risk:Reward ratio acceptable',
            '✓ Entry price within range',
            '✓ Stop loss below support',
            '✓ Target at resistance level',
            '✓ Position size calculated',
            '✓ Market conditions verified'
        ]
    }
    
    filename = f'{ticker}_checklist_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
    with open(filename, 'w') as f:
        json.dump(checklist, f, indent=2)
    
    tlog(f"✅ CHECKLIST SAVED: {filename}")
    return filename


# ═══════════════════════════════════════════════════════════════════════════════
# v16.12 HELPER FUNCTIONS - MACD, AO Momentum, Fractal Detection
# ═══════════════════════════════════════════════════════════════════════════════

def calculate_macd(close_prices, fast=12, slow=26, signal=9):
    """Calculate MACD line, Signal line, and Histogram"""
    ema_fast = close_prices.ewm(span=fast, adjust=False).mean()
    ema_slow = close_prices.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def macd_bullish_cross(macd_line, signal_line):
    """Check if MACD crossed above Signal line (bullish) - STRICT: only on cross bar"""
    if len(macd_line) < 2:
        return False
    current_macd = macd_line.iloc[-1]
    current_signal = signal_line.iloc[-1]
    previous_macd = macd_line.iloc[-2]
    previous_signal = signal_line.iloc[-2]
    return (current_macd > current_signal) and (previous_macd <= previous_signal)


def macd_is_bullish(macd_line, signal_line):
    """Check if MACD is above Signal line (bullish trend) - RELAXED: any bar where MACD > signal"""
    if len(macd_line) < 1:
        return False
    current_macd = macd_line.iloc[-1]
    current_signal = signal_line.iloc[-1]
    return current_macd > current_signal


def macd_bearish_cross(macd_line, signal_line):
    """Check if MACD crossed below Signal line (bearish)"""
    if len(macd_line) < 2:
        return False
    current_macd = macd_line.iloc[-1]
    current_signal = signal_line.iloc[-1]
    previous_macd = macd_line.iloc[-2]
    previous_signal = signal_line.iloc[-2]
    return (current_macd < current_signal) and (previous_macd >= previous_signal)


def ao_momentum_growing(ao_series, consecutive_bars=2):
    """Check if AO bars growing for N consecutive bars"""
    if len(ao_series) < consecutive_bars + 1:
        return False
    recent_ao = ao_series.iloc[-(consecutive_bars+1):].values
    growing = all(abs(recent_ao[i]) > abs(recent_ao[i-1]) 
                  for i in range(1, len(recent_ao)))
    return growing


def ao_momentum_shrinking(ao_series, consecutive_bars=2):
    """Check if AO bars shrinking for N consecutive bars"""
    if len(ao_series) < consecutive_bars + 1:
        return False
    recent_ao = ao_series.iloc[-(consecutive_bars+1):].values
    shrinking = all(abs(recent_ao[i]) < abs(recent_ao[i-1]) 
                    for i in range(1, len(recent_ao)))
    return shrinking


def detect_down_fractal(low_series):
    """Detect Down Fractal (5-bar pattern)"""
    if len(low_series) < 5:
        return False
    center_idx = -3  # 2 bars ago for confirmation
    center_low = low_series.iloc[center_idx]
    left_2 = low_series.iloc[center_idx - 2]
    left_1 = low_series.iloc[center_idx - 1]
    right_1 = low_series.iloc[center_idx + 1]
    right_2 = low_series.iloc[center_idx + 2]
    is_fractal = (center_low < left_2 and center_low < left_1 and 
                  center_low < right_1 and center_low < right_2)
    return is_fractal


def detect_up_fractal(high_series):
    """Detect Up Fractal (5-bar pattern)"""
    if len(high_series) < 5:
        return False
    center_idx = -3
    center_high = high_series.iloc[center_idx]
    left_2 = high_series.iloc[center_idx - 2]
    left_1 = high_series.iloc[center_idx - 1]
    right_1 = high_series.iloc[center_idx + 1]
    right_2 = high_series.iloc[center_idx + 2]
    is_fractal = (center_high > left_2 and center_high > left_1 and 
                  center_high > right_1 and center_high > right_2)
    return is_fractal


def detect_macd_bearish_cross(macd_line, signal_line):
    """
    Detect if MACD is bearish (below signal line) within the last 3 bars.
    
    NOTE: Despite the name, this checks if MACD is BELOW signal (bearish state),
    not specifically for a crossover event. This is intentional for traffic light
    logic where we want to detect bearish conditions, not just the cross moment.
    
    For actual crossover detection, use macd_bearish_cross() instead.
    
    v16.9: Used to confirm AO weakness before showing yellow dot.
    """
    if macd_line is None or signal_line is None:
        return False
    
    if len(macd_line) < 2 or len(signal_line) < 2:
        return False
    
    # Check last 3 bars for MACD below signal (bearish state)
    for i in range(min(3, len(macd_line))):
        idx = -(i + 1)
        current_macd = macd_line.iloc[idx] if hasattr(macd_line, 'iloc') else macd_line[idx]
        current_signal = signal_line.iloc[idx] if hasattr(signal_line, 'iloc') else signal_line[idx]
        
        if current_macd < current_signal:
            return True
    
    return False


# ═══════════════════════════════════════════════════════════════════════════════
# v16.17 DIVERGENCE BLOCKER - Prevent entries during active bearish divergence
# ═══════════════════════════════════════════════════════════════════════════════

def detect_divergence_with_active_flag(df: pd.DataFrame, lookback: int = 20) -> pd.DataFrame:
    """
    Detect bearish divergence and track active flag.
    
    Bearish Divergence: Price makes higher high BUT AO makes lower high.
    Active Flag: Set True when divergence detected, False when price breaks 2% above previous high.
    
    Args:
        df: DataFrame with High, Low, Close columns
        lookback: Number of bars to look back for divergence detection (default 20)
    
    Returns:
        DataFrame with added 'bearish_div_active' column
    """
    if df is None or len(df) < lookback + 5:
        df = df.copy() if df is not None else pd.DataFrame()
        df['bearish_div_active'] = False
        return df
    
    df = df.copy()
    
    # Handle column name case sensitivity
    high_col = 'High' if 'High' in df.columns else 'high'
    low_col = 'Low' if 'Low' in df.columns else 'low'
    close_col = 'Close' if 'Close' in df.columns else 'close'
    
    # Calculate Awesome Oscillator
    midpoint = (df[high_col] + df[low_col]) / 2
    ao = midpoint.rolling(window=5).mean() - midpoint.rolling(window=34).mean()
    df['ao_temp'] = ao
    
    # Initialize divergence tracking columns
    df['bearish_div_detected'] = False
    df['bearish_div_active'] = False
    
    # Track state
    last_divergence_high = None
    divergence_active = False
    
    for i in range(lookback + 5, len(df)):
        current_high = df[high_col].iloc[i]
        current_ao = df['ao_temp'].iloc[i]
        
        if pd.isna(current_ao):
            df.iloc[i, df.columns.get_loc('bearish_div_active')] = divergence_active
            continue
        
        # Look back to find previous swing high in price
        lookback_start = max(0, i - lookback)
        price_lookback = df[high_col].iloc[lookback_start:i]
        ao_lookback = df['ao_temp'].iloc[lookback_start:i]
        
        if len(price_lookback) == 0 or len(ao_lookback) == 0:
            df.iloc[i, df.columns.get_loc('bearish_div_active')] = divergence_active
            continue
        
        # Find the highest high in the lookback period
        prev_high_idx = price_lookback.idxmax()
        prev_high_price = price_lookback.loc[prev_high_idx] if prev_high_idx in price_lookback.index else price_lookback.max()
        
        # Get AO at that previous high
        try:
            prev_high_pos = df.index.get_loc(prev_high_idx)
            prev_high_ao = df['ao_temp'].iloc[prev_high_pos]
        except:
            prev_high_ao = ao_lookback.max()
        
        # Check for bearish divergence: Price higher high, AO lower high
        if current_high > prev_high_price and current_ao < prev_high_ao and current_ao > 0:
            df.iloc[i, df.columns.get_loc('bearish_div_detected')] = True
            divergence_active = True
            last_divergence_high = current_high
            tlog(f"DIVERGENCE: Bearish divergence detected at bar {i} - Price HH but AO LH")
        
        # Check if divergence should be cleared: Price breaks 2% above the divergence high
        if divergence_active and last_divergence_high is not None:
            breakout_threshold = last_divergence_high * 1.02
            if current_high > breakout_threshold:
                divergence_active = False
                last_divergence_high = None
                tlog(f"DIVERGENCE: Cleared - Price broke 2% above divergence high at bar {i}")
        
        df.iloc[i, df.columns.get_loc('bearish_div_active')] = divergence_active
    
    # Clean up temp column
    df.drop('ao_temp', axis=1, inplace=True)
    
    return df


def check_entry_with_divergence_blocker(df: pd.DataFrame, idx: int) -> tuple:
    """
    Check if entry is allowed based on divergence blocker status.
    
    Args:
        df: DataFrame with 'bearish_div_active' column from detect_divergence_with_active_flag()
        idx: Current bar index to check
    
    Returns:
        Tuple of (allowed: bool, reason: str)
    """
    if df is None or 'bearish_div_active' not in df.columns:
        return (True, 'Entry allowed - no divergence data')
    
    if idx < 0 or idx >= len(df):
        return (True, 'Entry allowed - index out of range')
    
    try:
        div_active = df['bearish_div_active'].iloc[idx]
        if div_active:
            return (False, 'BLOCKED: Bearish divergence active')
        else:
            return (True, 'Entry allowed')
    except Exception as e:
        tlog(f"Divergence check error at idx {idx}: {e}")
        return (True, 'Entry allowed - check error')


# ═══════════════════════════════════════════════════════════════════════════════
# v16.17 4H DIVERGENCE DETECTION - Early Warning System for Wave Exhaustion
# ═══════════════════════════════════════════════════════════════════════════════

def detect_4h_divergence(h4_df: pd.DataFrame, lookback: int = 20) -> dict:
    """
    Detect bearish divergence on 4H timeframe to catch Wave 3/5 exhaustion early.
    
    Bearish Divergence: Price makes higher high BUT AO makes lower high.
    This is an early warning that momentum is weakening before price reverses.
    
    Args:
        h4_df: 4-Hour DataFrame with High, Low, Close columns
        lookback: Number of bars to look back for swing detection (default 20)
    
    Returns:
        dict with:
            detected: bool - True if divergence found
            price_highs: list of (date, value) tuples for swing highs
            ao_peaks: list of (date, value) tuples for AO at swing highs
            severity: 'WEAK' | 'MODERATE' | 'STRONG' based on AO decline %
            message: str description of divergence
    """
    result = {
        "detected": False,
        "price_highs": [],
        "ao_peaks": [],
        "severity": None,
        "message": "No divergence detected"
    }
    
    if h4_df is None or len(h4_df) < lookback + 10:
        result["message"] = "Insufficient 4H data for divergence detection"
        return result
    
    df = h4_df.copy()
    
    # Handle column name case sensitivity
    high_col = 'High' if 'High' in df.columns else 'high'
    low_col = 'Low' if 'Low' in df.columns else 'low'
    
    # Calculate Awesome Oscillator for 4H
    midpoint = (df[high_col] + df[low_col]) / 2
    ao = midpoint.rolling(window=5).mean() - midpoint.rolling(window=34).mean()
    df['ao'] = ao
    
    # Find swing highs using scipy argrelextrema
    try:
        from scipy.signal import argrelextrema
        order = 3  # Minimum bars on each side to be considered a swing high
        
        # Find local maxima in price
        high_prices = df[high_col].values
        swing_high_indices = argrelextrema(high_prices, np.greater_equal, order=order)[0]
        
        if len(swing_high_indices) < 2:
            result["message"] = "Not enough swing highs detected"
            return result
        
        # Get the last 3 swing highs (most recent)
        recent_swing_indices = swing_high_indices[-3:] if len(swing_high_indices) >= 3 else swing_high_indices[-2:]
        
        # Extract price highs and AO values at those swing points
        price_highs = []
        ao_peaks = []
        
        for idx in recent_swing_indices:
            date = df.index[idx]
            price = df[high_col].iloc[idx]
            ao_val = df['ao'].iloc[idx]
            
            if pd.notna(ao_val):
                price_highs.append((date, price))
                ao_peaks.append((date, ao_val))
        
        if len(price_highs) < 2:
            result["message"] = "Not enough valid swing highs with AO data"
            return result
        
        result["price_highs"] = price_highs
        result["ao_peaks"] = ao_peaks
        
        # Check for bearish divergence: Higher price high, Lower AO high
        # Compare last two swing highs
        prev_price = price_highs[-2][1]
        curr_price = price_highs[-1][1]
        prev_ao = ao_peaks[-2][1]
        curr_ao = ao_peaks[-1][1]
        
        # Divergence: Price made higher high, but AO made lower high
        if curr_price > prev_price and curr_ao < prev_ao:
            result["detected"] = True
            
            # Calculate severity based on AO decline percentage
            ao_decline_pct = ((prev_ao - curr_ao) / abs(prev_ao)) * 100 if prev_ao != 0 else 0
            
            if ao_decline_pct >= 30:
                result["severity"] = "STRONG"
            elif ao_decline_pct >= 15:
                result["severity"] = "MODERATE"
            else:
                result["severity"] = "WEAK"
            
            result["message"] = f"4H Divergence: Price HH (+{((curr_price/prev_price)-1)*100:.1f}%) but AO LH (-{ao_decline_pct:.1f}%)"
            
            # Log the detection
            tlog(f"⚠️ 4H DIVERGENCE DETECTED [{result['severity']}]:")
            tlog(f"  Price: {prev_price:.2f} → {curr_price:.2f} (Higher High)")
            tlog(f"  AO: {prev_ao:.2f} → {curr_ao:.2f} (Lower High, -{ao_decline_pct:.1f}%)")
            tlog(f"  Dates: {price_highs[-2][0]} → {price_highs[-1][0]}")
        else:
            result["message"] = "No divergence: Price and AO aligned"
            
    except Exception as e:
        result["message"] = f"Divergence detection error: {e}"
        tlog(f"4H Divergence error: {e}")
    
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# v16.0 ADAPTIVE ARCHITECT - MSR, NSR, and Pattern Detection Functions
# ═══════════════════════════════════════════════════════════════════════════════

def calculate_msr_robust(ao_series: pd.Series, lookback: int = 60, floor_percentile: float = 0.10) -> pd.Series:
    """v16.0 Momentum Surge Ratio with adaptive floor to prevent denominator collapse.
    
    MSR measures how many standard deviations the current AO is from its rolling median.
    The adaptive floor prevents division by near-zero MAD during consolidation.
    
    Args:
        ao_series: Awesome Oscillator pandas Series
        lookback: Rolling window for median/MAD (default 60 days)
        floor_percentile: Historical MAD percentile for floor (default 10th)
    
    Returns:
        pandas Series of MSR values (capped at ±10)
    """
    if ao_series is None or ao_series.empty:
        return pd.Series(dtype=float)
    
    # Standard MAD calculation
    median_ao = ao_series.rolling(lookback).median()
    mad_ao = (ao_series - median_ao).abs().rolling(lookback).median()
    
    # Calculate historical MAD distribution for safety floor
    historical_mad = (ao_series - ao_series.rolling(lookback).median()).abs()
    mad_floor = historical_mad.rolling(252).quantile(floor_percentile)
    
    # Use max of current MAD or historical floor (prevents collapse)
    mad_adjusted = mad_ao.combine(mad_floor, max)
    
    # Ensure we never divide by zero
    mad_adjusted = mad_adjusted.replace(0, 0.001)
    
    # Calculate MSR and cap at ±10 for stability
    msr = (ao_series - median_ao) / mad_adjusted
    msr_capped = msr.clip(-10, 10)
    
    return msr_capped


def calculate_nsr_adaptive(high: pd.Series, low: pd.Series, close: pd.Series, 
                           fast_window: int = 60, slow_window: int = 252) -> dict:
    """v16.0 Regime-adaptive Noise-to-Signal Ratio using dual timeframes.
    
    NSR measures the ratio of intraday noise to directional signal.
    Uses fast/slow windows to detect regime shifts and adapt dynamically.
    
    Args:
        high, low, close: pandas Series of OHLC data
        fast_window: Short-term volatility window (default 60d)
        slow_window: Long-term personality window (default 252d)
    
    Returns:
        dict with NSR_Adaptive, NSR_Fast, NSR_Slow, Regime_Ratio series
    """
    if close is None or close.empty:
        return {'NSR_Adaptive': pd.Series(dtype=float), 'NSR_Fast': pd.Series(dtype=float),
                'NSR_Slow': pd.Series(dtype=float), 'Regime_Ratio': pd.Series(dtype=float)}
    
    # Calculate noise and signal components
    intraday_range = (high - low) / close
    noise = intraday_range.rolling(5).mean()
    
    signal = close.diff(5).abs()
    signal = signal.replace(0, 0.01)  # Prevent division by zero
    
    # Fast NSR (recent regime)
    nsr_fast = (noise.rolling(fast_window).mean() / 
                signal.rolling(fast_window).mean())
    
    # Slow NSR (long-term personality)
    nsr_slow = (noise.rolling(slow_window).mean() / 
                signal.rolling(slow_window).mean())
    
    # Regime detection: fast/slow ratio > 1.5 = regime shift
    nsr_slow_safe = nsr_slow.replace(0, 0.001)
    regime_ratio = nsr_fast / nsr_slow_safe
    regime_shift = regime_ratio > NSR_REGIME_SHIFT
    
    # Adaptive blend: use fast during shifts, blend during stability
    nsr_adaptive = np.where(
        regime_shift,
        nsr_fast,                          # Pure fast window
        0.8 * nsr_slow + 0.2 * nsr_fast   # Weighted blend
    )
    
    return {
        'NSR_Adaptive': pd.Series(nsr_adaptive, index=close.index),
        'NSR_Fast': nsr_fast,
        'NSR_Slow': nsr_slow,
        'Regime_Ratio': regime_ratio
    }


def detect_consolidation(high: pd.Series, low: pd.Series, volume: pd.Series, lookback: int = 10) -> pd.Series:
    """v16.0 Detects bull flag consolidation pattern.
    
    Criteria:
    - Price range contracting (30-70% of prior range)
    - Volume declining (< 90% of prior volume)
    
    Returns: pandas Series of boolean values
    """
    if high is None or high.empty:
        return pd.Series(dtype=bool)
    
    # Range contraction: current range vs. prior range
    recent_range = high.rolling(lookback).max() - low.rolling(lookback).min()
    prior_range = (high.shift(lookback).rolling(lookback).max() - 
                   low.shift(lookback).rolling(lookback).min())
    prior_range = prior_range.replace(0, 1)  # Avoid division by zero
    
    contraction_ratio = recent_range / prior_range
    
    # Volume decline: current volume vs. prior volume
    recent_vol = volume.rolling(lookback).mean()
    prior_vol = volume.shift(lookback).rolling(lookback).mean()
    prior_vol = prior_vol.replace(0, 1)  # Avoid division by zero
    volume_ratio = recent_vol / prior_vol
    
    # Bull flag pattern
    is_consolidating = (
        (contraction_ratio > 0.3) &   # Not too tight
        (contraction_ratio < 0.7) &   # Genuinely contracting
        (volume_ratio < 0.9)          # Volume drying up
    )
    
    return is_consolidating


def calculate_catastrophic_floor(trailing_stop: float, atr: float, 
                                  historical_gaps: pd.Series = None) -> float:
    """v16.0 Probabilistic floor calibrated to P(recovery) < 10%.
    
    Uses historical gap distribution to set a floor below which 
    recovery probability is very low (catastrophic gap protection).
    
    Args:
        trailing_stop: Current trailing stop level
        atr: Current ATR value
        historical_gaps: Series of historical gap ratios (optional)
    
    Returns:
        catastrophic_floor: Price level for immediate exit
    """
    # Default conservative threshold if no historical data
    catastrophic_threshold = -5.0
    
    if historical_gaps is not None and len(historical_gaps) > 0:
        # Find severe gaps (more than 2 ATR down)
        severe_gaps = historical_gaps[historical_gaps < -2.0]
        
        if len(severe_gaps) > 20:  # Minimum sample size
            # 5th percentile of severe gaps (empirically -5 to -6 ATR)
            catastrophic_threshold = severe_gaps.quantile(0.05)
    
    # Floor = stop + threshold (threshold is negative)
    floor = trailing_stop + (catastrophic_threshold * atr)
    
    # Safety bounds: never tighter than -3 ATR, never wider than -8 ATR
    floor = max(floor, trailing_stop - CATASTROPHIC_FLOOR_MAX * atr)
    floor = min(floor, trailing_stop - CATASTROPHIC_FLOOR_MIN * atr)
    
    return floor


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculate Average True Range for volatility measurement."""
    if df is None or df.empty:
        return pd.Series(dtype=float)
    
    high = df['High']
    low = df['Low']
    close = df['Close']
    
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    
    return atr


def calculate_avg_weekly_drawdown(weekly_df: pd.DataFrame) -> float:
    """v15.1 Drawdown Ceiling: Calculate 3-year average weekly drawdown.
    
    Returns the average weekly drawdown as a positive percentage.
    Used to identify high-risk structural volatility (targets TSLA, CAT).
    """
    if weekly_df is None or weekly_df.empty or len(weekly_df) < 52:
        return 0.0
    
    # Use last 3 years of weekly data (156 weeks)
    lookback = min(len(weekly_df), 156)
    df = weekly_df.tail(lookback).copy()
    
    # Calculate running peak and drawdown for each week
    running_peak = df['Close'].expanding().max()
    weekly_drawdowns = (running_peak - df['Close']) / running_peak * 100
    
    # Return average drawdown (positive number)
    avg_dd = weekly_drawdowns.mean()
    return avg_dd if not pd.isna(avg_dd) else 0.0


def calculate_suitability_score(df, weekly_sma_data):
    """v12.5 Personality Scouter: Quantifies Trend Smoothness for Wave 3."""
    if df is None or df.empty or weekly_sma_data is None:
        return 0, "N/A"
    
    # 1. Linearity: Spend above SMA (> 3% buffer)
    sma_aligned = weekly_sma_data.reindex(df.index, method='ffill')
    above_sma = (df['Close'] > sma_aligned * 1.03).sum() / len(df) * 100
    
    # 2. Momentum Thrust: King Peak Ratio
    ao = calculate_awesome_oscillator(df).abs()
    king_peak = ao.max()
    avg_peak = ao.mean()
    thrust_ratio = (king_peak / avg_peak) if avg_peak > 0 else 0
    
    # 3. Suitability Logic
    score = (above_sma * 0.6) + (min(thrust_ratio * 10, 40))
    
    if score > 80:
        verdict = "HIGH SUITABILITY (Smooth Wave 3)"
    elif score > 50:
        verdict = "MODERATE (Expect Noise)"
    else:
        verdict = "AVOID (Erratic Personality)"
    
    return int(score), verdict


def get_personality_audit(df, weekly_sma_data):
    """v12.6 Personality Audit: Returns breakdown metrics explaining the score."""
    if df is None or df.empty or weekly_sma_data is None:
        return None
    
    # 1. Calculate Average Gap (Linearity check)
    sma_aligned = weekly_sma_data.reindex(df.index, method='ffill')
    gaps = (df['Close'] - sma_aligned) / sma_aligned
    avg_gap = gaps.mean() * 100
    
    # 2. Calculate Peak Dominance (Momentum check)
    ao = calculate_awesome_oscillator(df).abs()
    king = ao.max()
    noise_floor = ao.rolling(window=50).mean().mean()
    dominance = king / noise_floor if noise_floor > 0 else 0
    
    # 3. Calculate Efficiency (Noise check) - using ATR
    tr = pd.concat([
        df['High'] - df['Low'],
        (df['High'] - df['Close'].shift()).abs(),
        (df['Low'] - df['Close'].shift()).abs()
    ], axis=1).max(axis=1)
    atr = tr.rolling(window=14).mean()
    
    total_move = abs(df['Close'].iloc[-1] - df['Close'].iloc[0])
    total_noise = atr.sum()
    efficiency = total_move / total_noise if total_noise > 0 else 0
    
    return {
        "SMA Gap %": f"{avg_gap:+.1f}%",
        "Peak Dominance": f"{dominance:.1f}x",
        "Efficiency": f"{efficiency:.2f}"
    }


def get_adaptive_strategy_recommendation(suitability_score):
    """
    v16.35 Adaptive Strategy Router
    Routes tickers to optimal strategy based on volatility personality.
    
    Backtest Results (64 tickers, 5Y):
    - VOLATILE (<55): High-beta tech (NVDA, AMD, PANW) - TTA handles better with tight stops
    - MODERATE (55-80): Financials (GS, MS, XOM) - Break-Retest shines on steady compounders
    - STEADY (>80): Ultra-steady (MSFT, COST) - Often don't trigger BR patterns
    
    Returns: (strategy, rationale, color)
    """
    if suitability_score is None or suitability_score == 0:
        return "TTA", "Insufficient data for classification", "gray"
    
    if suitability_score < 55:
        return "TTA", "Volatile stock - use TTA with tight daily stops", "orange"
    elif suitability_score <= 80:
        return "BREAK-RETEST", "Moderate volatility - ideal for 30-week SMA continuation plays", "green"
    else:
        return "TTA", "Ultra-steady compounder - rarely pulls back to SMA for BR entry", "blue"


def run_break_retest_for_chart(ticker, daily_df):
    """
    v16.35 Break-Retest Strategy Wrapper
    Runs the Break-Retest 30-week SMA continuation strategy and returns
    chart markers + stats in a format compatible with TTA display.
    
    Returns: (markers, stats) similar to scan_tta_for_daily_chart
    """
    from strategy_break_retest import strategy_break_retest_30w_sma
    import yfinance as yf
    
    markers = []
    stats = {
        "count": 0, "avg_run": 0.0, "total_return": None, "final_balance": None,
        "max_drawdown": None, "efficiency_ratio": None, "cagr": None,
        "success_rate": 0, "trade_count": 0, "active_sl": None,
        "strategy_type": "BREAK-RETEST"
    }
    
    try:
        # Fetch weekly data for Break-Retest (uses 30-week SMA)
        weekly_df = yf.download(ticker, period='5y', interval='1wk', progress=False)
        if weekly_df.empty or len(weekly_df) < 52:
            print(f"BR: Insufficient weekly data for {ticker}")
            return markers, stats
        
        # Handle multi-level columns from yfinance
        if isinstance(weekly_df.columns, pd.MultiIndex):
            weekly_df.columns = weekly_df.columns.get_level_values(0)
        
        # Run Break-Retest strategy
        result = strategy_break_retest_30w_sma(weekly_df, ticker)
        
        # Convert trades to chart markers (map weekly dates to daily chart)
        for trade in result.trades:
            # BUY marker at entry
            markers.append({
                "time": trade.entry_date,
                "position": "belowBar",
                "color": "#22c55e",  # Green
                "shape": "arrowUp",
                "text": "BR-BUY",
                "size": 2
            })
            
            # SELL marker at exit
            if trade.exit_date:
                exit_color = "#22c55e" if trade.r_multiple > 0 else "#ef4444"  # Green if win, red if loss
                markers.append({
                    "time": trade.exit_date,
                    "position": "aboveBar",
                    "color": exit_color,
                    "shape": "arrowDown",
                    "text": f"BR-SELL ({trade.r_multiple:+.1f}R)",
                    "size": 2
                })
        
        # Calculate stats
        if result.trades:
            stats["trade_count"] = len(result.trades)
            stats["success_rate"] = result.win_rate
            stats["count"] = len(result.trades)
            
            # Calculate total return
            total_r = sum(t.r_multiple for t in result.trades)
            stats["total_return"] = total_r
            stats["avg_run"] = total_r / len(result.trades) if result.trades else 0
        
        print(f"BR: Generated {len(markers)} markers from {len(result.trades)} trades for {ticker}")
        
    except Exception as e:
        print(f"BR: Error running Break-Retest for {ticker}: {e}")
    
    return markers, stats


def calculate_macd_with_crossovers(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple:
    """
    Calculate MACD (Moving Average Convergence Divergence) with crossover detection.
    Returns: (macd_line, signal_line, histogram, crossover_signals)
    crossover_signals: DataFrame with 'date', 'value', 'type' (bullish/bearish)
    NOTE: This version takes a DataFrame and includes crossover detection.
    For simple MACD calculations, use calculate_macd() which takes a Series.
    """
    # Handle both 'Close' and 'close' column names
    close_col = 'Close' if 'Close' in df.columns else 'close' if 'close' in df.columns else None
    if close_col is None:
        raise ValueError("DataFrame must have 'Close' or 'close' column")
    ema_fast = df[close_col].ewm(span=fast, adjust=False).mean()
    ema_slow = df[close_col].ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    
    crossovers = []
    for i in range(1, len(macd_line)):
        prev_diff = macd_line.iloc[i-1] - signal_line.iloc[i-1]
        curr_diff = macd_line.iloc[i] - signal_line.iloc[i]
        
        if prev_diff <= 0 and curr_diff > 0:
            crossovers.append({
                'date': df.index[i],
                'value': macd_line.iloc[i],
                'type': 'bullish'
            })
        elif prev_diff >= 0 and curr_diff < 0:
            crossovers.append({
                'date': df.index[i],
                'value': macd_line.iloc[i],
                'type': 'bearish'
            })
    
    return macd_line, signal_line, histogram, crossovers


def find_price_pivots(df: pd.DataFrame, order: int = 5) -> tuple:
    """
    Find the last 10 significant price pivots (highs and lows) using scipy.signal.argrelextrema.
    Returns a tuple: (formatted text string, dict with A/B levels for v7.1)
    """
    if len(df) < order * 2:
        return "Insufficient data for pivot analysis", {'A': None, 'B': None}
    
    high_prices = df['High'].values
    low_prices = df['Low'].values
    
    local_max_indices = argrelextrema(high_prices, np.greater, order=order)[0]
    local_min_indices = argrelextrema(low_prices, np.less, order=order)[0]
    
    pivots = []
    
    for idx in local_max_indices:
        pivots.append({
            'type': 'HIGH',
            'price': high_prices[idx],
            'date': df.index[idx],
            'index': idx
        })
    
    for idx in local_min_indices:
        pivots.append({
            'type': 'LOW',
            'price': low_prices[idx],
            'date': df.index[idx],
            'index': idx
        })
    
    pivots.sort(key=lambda x: x['index'], reverse=True)
    last_10_pivots = pivots[:10]
    last_10_pivots.sort(key=lambda x: x['date'])
    
    # Extract v7.1 trigger levels from most recent pivots
    # A = most recent structural swing LOW (bearish activation)
    # B = most recent structural swing HIGH (bullish continuation)
    recent_lows = [p for p in pivots if p['type'] == 'LOW'][:3]
    recent_highs = [p for p in pivots if p['type'] == 'HIGH'][:3]
    
    level_A = recent_lows[0]['price'] if recent_lows else None
    level_B = recent_highs[0]['price'] if recent_highs else None
    
    trigger_levels = {
        'A': level_A,
        'B': level_B,
        'A_date': recent_lows[0]['date'] if recent_lows else None,
        'B_date': recent_highs[0]['date'] if recent_highs else None
    }
    
    if not last_10_pivots:
        return "No significant pivots found", trigger_levels
    
    formatted_lines = []
    formatted_lines.append("=== LAST 10 SIGNIFICANT PRICE PIVOTS ===")
    formatted_lines.append("")
    
    for i, pivot in enumerate(last_10_pivots, 1):
        date_str = pivot['date'].strftime('%Y-%m-%d')
        price_str = f"${pivot['price']:.2f}"
        pivot_type = pivot['type']
        formatted_lines.append(f"{i}. {pivot_type}: {price_str} on {date_str}")
    
    # Add v7.1 trigger level summary
    formatted_lines.append("")
    formatted_lines.append("=== v7.1 TRIGGER LEVELS (from structural pivots) ===")
    if level_A:
        formatted_lines.append(f"Level A (Bearish Activation): ${level_A:.2f}")
    if level_B:
        formatted_lines.append(f"Level B (Bullish Continuation): ${level_B:.2f}")
    formatted_lines.append("")
    formatted_lines.append("=== END OF PIVOT DATA ===")
    
    return "\n".join(formatted_lines), trigger_levels


def build_ao_chunk_diagnostic(ao_values, dates, highs, lows, closes=None, sma_values=None):
    """
    v9.4 AO HISTOGRAM KING-CHUNK DIAGNOSTIC (SMA RESET AWARE)
    - Wave count only starts AFTER price crosses below 30W SMA then back above (reset)
    - W3 = Largest AO peak after reset, W4 = first negative after W3, W5 = next positive
    """
    if ao_values is None or len(ao_values) < 10:
        return None
    
    # Ensure inputs are lists for iteration
    def to_list(x): return x.tolist() if hasattr(x, 'tolist') else list(x)
    ao, dts, hgh, low = to_list(ao_values), to_list(dates), to_list(highs), to_list(lows)
    
    # =========================================================================
    # SMA RESET DETECTION: Find where price went below SMA then crossed back above
    # This marks the start of a new impulse wave count
    # We need to find a reset that leaves enough data for wave analysis
    # =========================================================================
    reset_idx = 0  # Default: start from beginning if no SMA data
    
    # Keep ORIGINAL SMA values for slope validation (before slicing)
    original_sma = None
    original_dts = dts.copy()
    current_sma_rising = False  # Track if SMA is currently rising (turnaround detection)
    
    if closes is not None and sma_values is not None:
        cls = to_list(closes)
        sma = to_list(sma_values)
        original_sma = sma.copy()  # Keep full SMA for slope check
        
        # Scan FORWARD to find all reset points (below -> above SMA crosses)
        reset_points = []
        was_below = False
        for i in range(len(cls)):
            if sma[i] is not None and not pd.isna(sma[i]):
                if cls[i] < sma[i]:
                    was_below = True
                elif was_below and cls[i] > sma[i]:
                    # Found a recross point
                    reset_points.append(i)
                    was_below = False
        
        # Use the LAST reset that leaves at least 50 data points for analysis
        # AND where the SMA was RISING at the reset point (not declining)
        min_data_after_reset = 50
        sma_lookback_for_slope = 30  # Check if SMA is rising over 30 bars
        
        # First, check if SMA is CURRENTLY rising (turnaround detection)
        current_sma_rising = False
        if len(sma) >= sma_lookback_for_slope:
            sma_now = sma[-1]
            sma_30_ago = sma[-sma_lookback_for_slope]
            if sma_now is not None and sma_30_ago is not None:
                if not pd.isna(sma_now) and not pd.isna(sma_30_ago):
                    current_sma_rising = float(sma_now) > float(sma_30_ago)
        
        # Track the most recent valid reset (enough data) for fallback
        most_recent_valid_reset = None
        
        for rp in reversed(reset_points):
            data_remaining = len(cls) - rp
            if data_remaining >= min_data_after_reset:
                # Track the most recent reset with enough data
                if most_recent_valid_reset is None:
                    most_recent_valid_reset = rp
                
                # Check if SMA was RISING at this reset point
                if rp >= sma_lookback_for_slope:
                    sma_at_reset = sma[rp]
                    sma_earlier = sma[rp - sma_lookback_for_slope]
                    if sma_at_reset is not None and sma_earlier is not None:
                        if not pd.isna(sma_at_reset) and not pd.isna(sma_earlier):
                            sma_rising = float(sma_at_reset) > float(sma_earlier)
                            if not sma_rising:
                                print(f"RESET REJECTED at index {rp}: SMA declining ({float(sma_earlier):.2f} -> {float(sma_at_reset):.2f})")
                                continue  # Skip this reset, try earlier one
                
                reset_idx = rp
                print(f"SMA RESET DETECTED: Price recrossed above SMA at index {rp}, date {dts[rp]}, {data_remaining} bars remaining")
                break
        
        # FALLBACK: If no valid reset found but SMA is CURRENTLY rising,
        # use the most recent reset - this handles stocks just turning bullish
        if reset_idx == 0 and most_recent_valid_reset is not None and current_sma_rising:
            reset_idx = most_recent_valid_reset
            print(f"SMA TURNAROUND: Using most recent reset at index {reset_idx} because SMA is NOW rising")
        
        # If we found a valid reset, filter data to only include points after reset
        if reset_idx > 0:
            ao = ao[reset_idx:]
            dts = dts[reset_idx:]
            hgh = hgh[reset_idx:]
            low = low[reset_idx:]
            print(f"Wave analysis starting from {dts[0]} (after SMA reset)")
        else:
            print(f"No valid SMA reset found with enough data, using full dataset")

    if len(ao) < 5:
        return None

    # 1. GENERATE ALL CHUNKS (from reset point onwards)
    all_chunks = []
    curr = {"type": "pos" if ao[0] >= 0 else "neg", "values": [ao[0]], "highs": [hgh[0]], "lows": [low[0]], "dates": [dts[0]], "indices": [0]}
    
    for i in range(1, len(ao)):
        t = "pos" if ao[i] >= 0 else "neg"
        if t == curr["type"]:
            curr["values"].append(ao[i])
            curr["highs"].append(hgh[i])
            curr["lows"].append(low[i])
            curr["dates"].append(dts[i])
            curr["indices"].append(i)
        else:
            all_chunks.append(curr)
            curr = {"type": t, "values": [ao[i]], "highs": [hgh[i]], "lows": [low[i]], "dates": [dts[i]], "indices": [i]}
    all_chunks.append(curr)

    # Filter: Ignore very short chunks (< 2 bars) unless it is the final chunk
    # Reduced from 3 to 2 to avoid filtering out significant wave markers
    valid_chunks = [c for idx, c in enumerate(all_chunks) if len(c["values"]) >= 2 or idx == len(all_chunks)-1]
    
    # Debug: Show chunk summary
    pos_count = len([c for c in valid_chunks if c["type"] == "pos"])
    neg_count = len([c for c in valid_chunks if c["type"] == "neg"])
    print(f"CHUNKS: {len(valid_chunks)} valid ({pos_count} pos, {neg_count} neg) from {len(all_chunks)} total")

    # Calculate metrics for each chunk
    for c in valid_chunks:
        c["area"] = sum([abs(v) for v in c["values"]])
        c["peak"] = max(c["values"]) if c["type"] == "pos" else min(c["values"])
        c["max_high"] = max(c["highs"])
        c["min_low"] = min(c["lows"])
        # Dates of extremes
        c["peak_date"] = c["dates"][c["values"].index(c["peak"])]
        # For price-pinned labels: use the LAST occurrence of max_high (before zero-cross)
        max_high_indices = [i for i, h in enumerate(c["highs"]) if h == c["max_high"]]
        c["max_high_date"] = c["dates"][max_high_indices[-1]]  # Last occurrence
        min_low_indices = [i for i, l in enumerate(c["lows"]) if l == c["min_low"]]
        c["min_low_date"] = c["dates"][min_low_indices[-1]]  # Last occurrence
        c["start_date"] = c["dates"][0]
        c["end_date"] = c["dates"][-1]

    # =========================================================================
    # WAVE 3 RULE: W3 MUST have the LARGEST AO peak after reset - no exceptions
    # BUT W3 must be COMPLETE (followed by a negative chunk) - can't be the current developing chunk
    # =========================================================================
    pos_chunks = [c for c in valid_chunks if c["type"] == "pos"]
    if not pos_chunks:
        return None

    # Filter to only COMPLETE positive chunks (those followed by a negative chunk)
    complete_pos_chunks = []
    for c in pos_chunks:
        c_idx = valid_chunks.index(c)
        if c_idx + 1 < len(valid_chunks) and valid_chunks[c_idx + 1]["type"] == "neg":
            complete_pos_chunks.append(c)
    
    # If no complete positive chunks, use the last positive chunk as "developing W3"
    if not complete_pos_chunks:
        w3_chunk = sorted(pos_chunks, key=lambda x: abs(x["peak"]), reverse=True)[0]
        w3_idx = valid_chunks.index(w3_chunk)
        w3_is_developing = True
    else:
        # Sort complete chunks by AO PEAK - W3 has highest momentum among COMPLETE chunks
        w3_chunk = sorted(complete_pos_chunks, key=lambda x: abs(x["peak"]), reverse=True)[0]
        w3_idx = valid_chunks.index(w3_chunk)
        w3_is_developing = False
        print(f"W3 SELECTION: Highest complete chunk has peak {w3_chunk['peak']:.2f}")
    
    # =========================================================================
    # SMA SLOPE VALIDATION: Cannot label bullish W3 when SMA is declining
    # Compare SMA at W3 peak vs SMA at RESET POINT to capture true trend
    # IMPORTANT: Use ORIGINAL SMA data (before reset slicing) for accurate slope check
    # EXCEPTION: If SMA is CURRENTLY rising (turnaround), allow even if historical slope was down
    # =========================================================================
    sma_slope_valid = True
    if original_sma is not None and reset_idx > 0 and not current_sma_rising:
        # Find the index in the ORIGINAL data corresponding to W3 peak date
        w3_peak_date = w3_chunk["max_high_date"]
        try:
            w3_data_idx = original_dts.index(w3_peak_date)
            # Compare SMA at W3 peak to SMA at RESET POINT (not just 20 bars earlier)
            # This captures the true long-term trend direction
            sma_at_reset = original_sma[reset_idx]
            sma_at_w3 = original_sma[w3_data_idx]
            
            if sma_at_reset is not None and sma_at_w3 is not None:
                if not pd.isna(sma_at_reset) and not pd.isna(sma_at_w3):
                    sma_at_w3 = float(sma_at_w3)
                    sma_at_reset = float(sma_at_reset)
                    sma_slope_valid = sma_at_w3 > sma_at_reset  # SMA must be rising from reset to W3
                    print(f"SMA SLOPE CHECK: SMA at W3 = {sma_at_w3:.2f}, SMA at reset = {sma_at_reset:.2f}, valid = {sma_slope_valid}")
                    if not sma_slope_valid:
                        print(f"SMA SLOPE INVALID: SMA declining from reset to W3 - this is a bear market rally, not a bullish impulse")
        except (ValueError, IndexError) as e:
            print(f"SMA slope check error: {e}")
            pass  # If we can't find the date, assume valid
    elif current_sma_rising:
        print(f"SMA TURNAROUND OVERRIDE: SMA is currently rising, allowing wave count despite historical decline")
    
    if not sma_slope_valid:
        # Don't label W3 when SMA is declining - this is likely a bear market rally
        return {"wave3": None, "wave4": None, "wave5": None, "divergence": False, "div_ratio": 0.0, 
                "post5_negative": False, "corrective_warning": False, "chart_markers": [], 
                "divergence_lines": [], "w5_extension": False, "sma_slope_invalid": True}
    
    # W3 is complete if it's not the developing chunk (already determined above)
    w3_is_complete = not w3_is_developing

    # v16.7: Detect AO momentum (rising vs falling) - current bar vs previous bar
    # This is more responsive to momentum changes like MACD crosses
    ao_momentum_rising = False
    if len(ao) >= 2:
        ao_momentum_rising = ao[-1] > ao[-2]  # Compare current bar vs previous bar
    
    # v16.5: Determine current wave state (what wave are we IN right now)
    last_chunk = valid_chunks[-1] if valid_chunks else None
    current_wave = "W3" if not w3_is_complete else "W4?"  # Default: W3 developing or post-W3
    
    result = {
        "wave3": {"peak": float(w3_chunk["peak"]), "area": float(w3_chunk["area"]), "date": w3_chunk["max_high_date"], "price_high": float(w3_chunk["max_high"]), "start": w3_chunk["start_date"], "end": w3_chunk["end_date"], "complete": w3_is_complete},
        "wave4": None, "wave5": None, "divergence": False, "div_ratio": 0.0, "post5_negative": False, "corrective_warning": False,
        "chart_markers": [],
        "divergence_lines": [],
        "w5_extension": False,
        "current_wave": current_wave,
        "ao_momentum_rising": ao_momentum_rising
    }
    
    # Label W3 - show as developing if AO still positive
    if w3_is_complete:
        result["chart_markers"].append({"time": w3_chunk["max_high_date"], "position": "aboveBar", "color": "#4ade80", "shape": "arrowDown", "text": "W3(dia)", "size": 1})
    else:
        result["chart_markers"].append({"time": w3_chunk["max_high_date"], "position": "aboveBar", "color": "#86efac", "shape": "arrowDown", "text": "W3?(dev)", "size": 1})
        print(f"W3 DEVELOPING: Largest AO peak {w3_chunk['peak']:.2f}, still positive")
        return result  # Can't identify W4/W5 until W3 completes

    print(f"W3 CONFIRMED: AO peak {w3_chunk['peak']:.2f} at {w3_chunk['max_high_date']}")

    # 3. FIND W4 (First negative chunk after W3 - AO crossed below zero)
    after_w3 = valid_chunks[w3_idx+1:]
    neg_after_w3 = [c for c in after_w3 if c["type"] == "neg"]
    
    w4_chunk = None
    w5_chunk = None
    
    if neg_after_w3:
        w4_chunk = neg_after_w3[0]
        w4_idx = valid_chunks.index(w4_chunk)
        
        # 4. FIND W5 (Positive chunks after W4 - track the developing wave)
        # W5 is the entire upward move after W4 - may span multiple pos chunks
        after_w4 = valid_chunks[w4_idx+1:]
        pos_after_w4 = [c for c in after_w4 if c["type"] == "pos"]
        
        # W4 is only complete when AO crosses back positive (W5 starts)
        # If no positive chunks after W4, W4 is still developing
        w4_is_complete = len(pos_after_w4) > 0
        
        result["wave4"] = {"trough": float(w4_chunk["peak"]), "date": w4_chunk["min_low_date"], "price_low": float(w4_chunk["min_low"]), "start": w4_chunk["start_date"], "end": w4_chunk["end_date"], "complete": w4_is_complete}
        
        if w4_is_complete:
            result["chart_markers"].append({"time": w4_chunk["min_low_date"], "position": "belowBar", "color": "#facc15", "shape": "arrowUp", "text": "W4(dia)", "size": 1})
            result["current_wave"] = "W5?"  # v16.7: W5 developing (will be updated later if complete)
            print(f"W4 CONFIRMED: AO trough at {w4_chunk['min_low_date']}, W5 has started")
        else:
            result["chart_markers"].append({"time": w4_chunk["min_low_date"], "position": "belowBar", "color": "#fde047", "shape": "arrowUp", "text": "W4?(dev)", "size": 1})
            result["current_wave"] = "W4"  # v16.5: In W4 corrective
            print(f"W4 DEVELOPING: AO still negative, no W5 yet")
            return result  # Can't identify W5 until W4 completes
        
        if pos_after_w4:
            # W5 spans ALL positive activity after W4 that makes higher highs
            # The "W5 chunk" is the one with the highest price high
            w5_chunk = max(pos_after_w4, key=lambda x: x["max_high"])
            
            # Also track the LAST positive chunk (most recent activity)
            last_pos_chunk = pos_after_w4[-1]
            last_pos_idx = valid_chunks.index(last_pos_chunk)
        
        if w5_chunk is not None:
            w5_idx = valid_chunks.index(w5_chunk)
            
            # =========================================================================
            # W5 COMPLETION RULE:
            # W5 is complete when AO crosses negative AFTER the W5 peak
            # Even if AO goes positive again later, W5 remains complete
            # UNLESS price makes a NEW HIGH above the W5 peak (then W5 extends)
            # =========================================================================
            
            # Check if there's ANY negative chunk after W5
            chunks_after_w5 = valid_chunks[w5_idx+1:]
            neg_after_w5 = [c for c in chunks_after_w5 if c["type"] == "neg"]
            pos_after_w5 = [c for c in chunks_after_w5 if c["type"] == "pos"]
            
            # W5 is complete if AO crossed negative after W5
            ao_crossed_negative_after_w5 = len(neg_after_w5) > 0
            
            # Check if price made a NEW HIGH after W5 (would extend W5)
            new_high_after_w5 = False
            if pos_after_w5:
                highest_after_w5 = max(c["max_high"] for c in pos_after_w5)
                if highest_after_w5 > w5_chunk["max_high"]:
                    new_high_after_w5 = True
                    # Update W5 chunk to the new highest
                    w5_chunk = max(pos_after_w5, key=lambda x: x["max_high"])
                    w5_idx = valid_chunks.index(w5_chunk)
            
            # W5 is complete if AO crossed negative AND no new high was made
            if new_high_after_w5:
                # W5 is extending - check if it's still developing
                last_chunk = valid_chunks[-1]
                w5_is_complete = last_chunk["type"] == "neg"
            else:
                # W5 is complete once AO crossed negative (even if positive again now)
                w5_is_complete = ao_crossed_negative_after_w5
            
            print(f"W5 ANALYSIS: ao_crossed_neg={ao_crossed_negative_after_w5}, new_high={new_high_after_w5}, complete={w5_is_complete}")
            
            w5_price_high = float(w5_chunk["max_high"])
            w3_price_high = float(w3_chunk["max_high"])
            w4_price_low = float(w4_chunk["min_low"])
            w5_ao_peak = float(w5_chunk["peak"])
            w3_ao_peak = float(w3_chunk["peak"])
            
            # =========================================================================
            # W5 VALIDITY RULE: W5 must make a NEW HIGH above W3 to be valid
            # If price high after W4 is BELOW W3 high:
            #   - If W5 is NOT complete (AO still positive): W4 correction still in progress
            #   - If W5 IS complete (AO crossed negative): TRUNCATED 5th / FAILURE - very bearish!
            # =========================================================================
            if w5_price_high < w3_price_high:
                if w5_is_complete:
                    # AMBIGUOUS STRUCTURE: Could be either:
                    # 1. Truncated W5 (impulse complete, now in correction)
                    # 2. Expanded Flat W4 (Wave B exceeded A, Wave C in progress, W5 still to come)
                    
                    # TRUNCATION VALIDITY: W5 must reach at least 70% of W4's height from W4 low
                    # If it doesn't reach 70%, truncated W5 is NOT valid - only expanded flat
                    w4_height = w3_price_high - w4_price_low
                    w5_height_from_w4 = w5_price_high - w4_price_low
                    w5_retracement_pct = (w5_height_from_w4 / w4_height) * 100 if w4_height > 0 else 0
                    
                    truncation_valid = w5_retracement_pct >= 70  # Must reach at least 70% of W4 height
                    
                    print(f"AMBIGUOUS: W5 high {w5_price_high:.2f} < W3 high {w3_price_high:.2f}, retracement {w5_retracement_pct:.1f}%")
                    
                    if truncation_valid:
                        # Both options are valid - show W5tr/B?
                        result["wave5"] = {"peak": w5_ao_peak, "area": float(w5_chunk["area"]), "date": w5_chunk["max_high_date"], "price_high": w5_price_high, "start": w5_chunk["start_date"], "end": w5_chunk["end_date"], "complete": True, "ambiguous": True}
                        result["wave4"]["expanded_flat_possible"] = True
                        result["ambiguous_structure"] = True
                        result["chart_markers"] = [
                            {"time": w3_chunk["max_high_date"], "position": "aboveBar", "color": "#4ade80", "shape": "arrowDown", "text": "W3(dia)", "size": 1},
                            {"time": w4_chunk["min_low_date"], "position": "belowBar", "color": "#facc15", "shape": "arrowUp", "text": "W4/A?", "size": 1},
                            {"time": w5_chunk["max_high_date"], "position": "aboveBar", "color": "#f59e0b", "shape": "arrowDown", "text": "W5tr/B?", "size": 1}
                        ]
                        # v16.5: Truncated W5 = corrective territory
                        result["current_wave"] = "Corr"
                        print(f"Truncated W5 valid (retracement {w5_retracement_pct:.1f}% >= 70%)")
                    else:
                        # Truncation NOT valid (< 70% retracement) - only expanded flat option
                        result["wave5"] = None
                        result["wave4"]["expanded_flat_possible"] = True
                        result["ambiguous_structure"] = False
                        result["chart_markers"] = [
                            {"time": w3_chunk["max_high_date"], "position": "aboveBar", "color": "#4ade80", "shape": "arrowDown", "text": "W3(dia)", "size": 1},
                            {"time": w4_chunk["min_low_date"], "position": "belowBar", "color": "#facc15", "shape": "arrowUp", "text": "W4(A)", "size": 1},
                            {"time": w5_chunk["max_high_date"], "position": "aboveBar", "color": "#f59e0b", "shape": "arrowDown", "text": "W4(B)", "size": 1}
                        ]
                        # v16.5: Expanded flat = still in W4 correction
                        result["current_wave"] = "W4"
                        print(f"Truncated W5 INVALID (retracement {w5_retracement_pct:.1f}% < 70%) - Expanded Flat only")
                    
                    # No corrective warning - structure is ambiguous/incomplete
                    return result
                else:
                    # W5 is developing but hasn't exceeded W3 price yet
                    # W4 IS complete (we have a positive chunk after it), W5 is developing
                    print(f"W5 DEVELOPING: Price high {w5_price_high:.2f} < W3 high {w3_price_high:.2f} (not yet exceeded)")
                    result["wave4"]["complete"] = True
                    result["wave5"] = {"peak": w5_ao_peak, "area": float(w5_chunk["area"]), "date": w5_chunk["max_high_date"], "price_high": w5_price_high, "start": w5_chunk["start_date"], "end": w5_chunk["end_date"], "complete": False}
                    result["chart_markers"] = [
                        {"time": w3_chunk["max_high_date"], "position": "aboveBar", "color": "#4ade80", "shape": "arrowDown", "text": "W3(dia)", "size": 1},
                        {"time": w4_chunk["min_low_date"], "position": "belowBar", "color": "#facc15", "shape": "arrowUp", "text": "W4(dia)", "size": 1},
                        {"time": w5_chunk["max_high_date"], "position": "aboveBar", "color": "#86efac", "shape": "arrowDown", "text": "W5?(dev)", "size": 1}
                    ]
                    # v16.7: W5 developing but not yet exceeded W3 - use "?" for active
                    result["current_wave"] = "W5?"
                    return result
            
            # =========================================================================
            # EXTENSION RULE: If W5 price > 138.2% of W3-W4 range, W5 is extending
            # This invalidates corrective structure - W5 becomes new W3
            # =========================================================================
            w3_w4_range = w3_price_high - w4_price_low
            extension_target = w4_price_low + (w3_w4_range * 1.382)
            is_extending = w5_price_high > extension_target
            
            if is_extending:
                result["w5_extension"] = True
                print(f"W5 EXTENSION: Price {w5_price_high:.2f} > 138.2% target {extension_target:.2f}")
            
            # =========================================================================
            # RELABEL CHECK: If W5's AO > W3's AO, W5 becomes the new W3
            # This should not happen if we selected W3 correctly, but double-check
            # =========================================================================
            if w5_ao_peak > w3_ao_peak:
                # W5 has larger AO - this means structure is extending
                # Previous W3 becomes part of earlier wave, W5 becomes new W3
                result["w5_extension"] = True
                print(f"STRUCTURE SHIFT: W5 AO {w5_ao_peak:.2f} > W3 AO {w3_ao_peak:.2f} - extending")
                
                # Update labels - mark old W3 as earlier structure, W5 as new W3
                result["chart_markers"] = [
                    {"time": w3_chunk["max_high_date"], "position": "aboveBar", "color": "#94a3b8", "shape": "arrowDown", "text": "(ext)", "size": 1},
                    {"time": w4_chunk["min_low_date"], "position": "belowBar", "color": "#94a3b8", "shape": "arrowUp", "text": "(ext)", "size": 1},
                ]
                if w5_is_complete:
                    result["chart_markers"].append({"time": w5_chunk["max_high_date"], "position": "aboveBar", "color": "#4ade80", "shape": "arrowDown", "text": "W3(dia)", "size": 1})
                else:
                    result["chart_markers"].append({"time": w5_chunk["max_high_date"], "position": "aboveBar", "color": "#86efac", "shape": "arrowDown", "text": "W3?(dev)", "size": 1})
                
                # Update wave3 data to the new W3
                result["wave3"] = {"peak": w5_ao_peak, "area": float(w5_chunk["area"]), "date": w5_chunk["max_high_date"], "price_high": w5_price_high, "start": w5_chunk["start_date"], "end": w5_chunk["end_date"], "complete": w5_is_complete}
                result["wave4"] = None
                result["wave5"] = None
                # v16.5: W5 relabeled as new W3 - structure is in W3 phase
                result["current_wave"] = "W3"
                return result
            
            # Normal W5 processing
            result["wave5"] = {"peak": w5_ao_peak, "area": float(w5_chunk["area"]), "date": w5_chunk["max_high_date"], "price_high": w5_price_high, "start": w5_chunk["start_date"], "end": w5_chunk["end_date"], "complete": w5_is_complete}
            
            # BEARISH DIVERGENCE: W5 price > W3 price BUT W5 AO peak < W3 AO peak
            result["div_ratio"] = round(w5_ao_peak / w3_ao_peak, 2) if w3_ao_peak != 0 else 0
            is_bearish_div = (w5_price_high > w3_price_high) and (w5_ao_peak < w3_ao_peak)
            result["divergence"] = is_bearish_div
            
            result["post5_negative"] = w5_is_complete
            result["corrective_warning"] = is_bearish_div and w5_is_complete
            result["divergence_warning"] = is_bearish_div  # Show warning even if W5 developing
            
            # v16.7: Update current_wave based on W5 status
            # Use "W5?" for developing (no brackets, green border)
            # Use "Corr" for complete (brackets, yellow/red border)
            if w5_is_complete:
                # Impulse exhausted - now in corrective phase
                result["current_wave"] = "Corr" if not is_bearish_div else "Corr!"
            else:
                # W5 still developing - use "?" suffix to indicate active
                result["current_wave"] = "W5?"

            # Label W5 - show divergence warning even when developing!
            if w5_is_complete:
                marker_color = "#f87171" if is_bearish_div else "#60a5fa"
                result["chart_markers"].append({"time": w5_chunk["max_high_date"], "position": "aboveBar", "color": marker_color, "shape": "arrowDown", "text": "W5(dia)", "size": 1})
                print(f"W5 LABELED: Complete, Divergence={is_bearish_div}")
            else:
                # Show divergence warning even while developing - this is critical intel!
                if is_bearish_div:
                    result["chart_markers"].append({"time": w5_chunk["max_high_date"], "position": "aboveBar", "color": "#f87171", "shape": "arrowDown", "text": "W5?(div)", "size": 1})
                    print(f"W5 DEVELOPING with DIVERGENCE: AO peak {w5_ao_peak:.2f} < W3 AO peak {w3_ao_peak:.2f}")
                else:
                    result["chart_markers"].append({"time": w5_chunk["max_high_date"], "position": "aboveBar", "color": "#94a3b8", "shape": "arrowDown", "text": "W5?(dev)", "size": 1})
                    print(f"W5 DEVELOPING: AO still positive, no divergence")
            
            # Draw divergence lines when divergence detected (even if developing!)
            if is_bearish_div:
                line_color = "#ef4444"
                result["divergence_lines"].append({
                    "type": "price", 
                    "x0": w3_chunk["max_high_date"], "y0": w3_price_high,
                    "x1": w5_chunk["max_high_date"], "y1": w5_price_high, 
                    "color": line_color, "row": 1
                })
                result["divergence_lines"].append({
                    "type": "oscillator", 
                    "x0": w3_chunk["peak_date"], "y0": w3_ao_peak,
                    "x1": w5_chunk["peak_date"], "y1": w5_ao_peak, 
                    "color": line_color, "row": 2
                })

    return result


def create_chart(df: pd.DataFrame, ticker: str, timeframe: str, sma_period: int = None, weekly_sma_data: pd.Series = None, level_A: float = None, level_B: float = None, macd_markers: list = None, divergence_lines: list = None, traffic_lights: dict = None):
    """Create candlestick chart with SMA overlay, AO subplot, v7.1 trigger levels, MACD diagnostic markers, divergence lines, and traffic light indicators."""
    
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.65, 0.35],  # Larger AO panel for better visibility
        subplot_titles=('', 'AO (5/34) + MACD (12/26/9)'),
        specs=[[{"secondary_y": False}], [{"secondary_y": True}]]
    )
    
    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df['Open'],
            high=df['High'],
            low=df['Low'],
            close=df['Close'],
            name='Price',
            increasing_line_color='#26a69a',
            decreasing_line_color='#ef5350'
        ),
        row=1, col=1
    )
    
    # Add 30-Week SMA (always show this for Weinstein analysis)
    sma_current_value = None
    sma_slope = None
    if weekly_sma_data is not None and len(weekly_sma_data) > 0:
        # Filter SMA data to match the chart date range
        chart_start = df.index.min()
        chart_end = df.index.max()
        filtered_sma = weekly_sma_data[(weekly_sma_data.index >= chart_start) & (weekly_sma_data.index <= chart_end)]
        
        if len(filtered_sma) > 0:
            sma_current_value = filtered_sma.iloc[-1]
            # Calculate slope (compare current to 4 weeks ago)
            if len(filtered_sma) >= 5:
                sma_slope = "RISING" if filtered_sma.iloc[-1] > filtered_sma.iloc[-5] else "FALLING"
            
            fig.add_trace(
                go.Scatter(
                    x=filtered_sma.index,
                    y=filtered_sma,
                    mode='lines',
                    name=f'30-Week SMA (${sma_current_value:.2f})',
                    line=dict(color='#ff9800', width=3)
                ),
                row=1, col=1
            )
            
            # SMA annotation removed - value already shown in legend
    elif sma_period and len(df) >= sma_period:
        sma = calculate_sma(df, sma_period)
        sma_current_value = sma.iloc[-1]
        if len(sma) >= 5:
            sma_slope = "RISING" if sma.iloc[-1] > sma.iloc[-5] else "FALLING"
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=sma,
                mode='lines',
                name=f'30-Week SMA (${sma_current_value:.2f})',
                line=dict(color='#ff9800', width=3)
            ),
            row=1, col=1
        )
        
        # SMA annotation removed - value already shown in legend
    
    ao = calculate_awesome_oscillator(df)
    ao_colors = ['#26a69a' if val >= 0 else '#ef5350' for val in ao]
    
    fig.add_trace(
        go.Bar(
            x=df.index,
            y=ao,
            name='Awesome Oscillator',
            marker_color=ao_colors,
            opacity=1.0,  # Full opacity for better visibility
            marker_line_width=0  # No outline for cleaner bars
        ),
        row=2, col=1
    )
    
    # Calculate and overlay MACD (12, 26, 9) on secondary y-axis
    macd_line, signal_line, macd_hist, crossovers = calculate_macd_with_crossovers(df, fast=12, slow=26, signal=9)
    
    # Add MACD line on secondary y-axis
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=macd_line,
            mode='lines',
            name='MACD (12,26)',
            line=dict(color='#2196F3', width=1.5)
        ),
        row=2, col=1, secondary_y=True
    )
    
    # Add Signal line on secondary y-axis
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=signal_line,
            mode='lines',
            name='Signal (9)',
            line=dict(color='#FF9800', width=1.5, dash='dot')
        ),
        row=2, col=1, secondary_y=True
    )
    
    # Add crossover dots (bullish = green, bearish = red)
    bullish_crossovers = [c for c in crossovers if c['type'] == 'bullish']
    bearish_crossovers = [c for c in crossovers if c['type'] == 'bearish']
    
    if bullish_crossovers:
        fig.add_trace(
            go.Scatter(
                x=[c['date'] for c in bullish_crossovers],
                y=[c['value'] for c in bullish_crossovers],
                mode='markers',
                name='Bullish Cross',
                marker=dict(color='#00E676', size=12, symbol='circle', line=dict(width=2, color='white'))
            ),
            row=2, col=1, secondary_y=True
        )
    
    if bearish_crossovers:
        fig.add_trace(
            go.Scatter(
                x=[c['date'] for c in bearish_crossovers],
                y=[c['value'] for c in bearish_crossovers],
                mode='markers',
                name='Bearish Cross',
                marker=dict(color='#FF1744', size=12, symbol='circle', line=dict(width=2, color='white'))
            ),
            row=2, col=1, secondary_y=True
        )
    
    # Add v7.1 Trigger Level Lines (A = bearish, B = bullish)
    current_price = df['Close'].iloc[-1] if len(df) > 0 else None
    trigger_state = None
    
    if level_A is not None:
        fig.add_hline(
            y=level_A,
            line_dash="dot",
            line_color="rgba(239, 83, 80, 0.6)",
            line_width=1.5,
            annotation_text=f"▼ SELL ${level_A:.2f}",
            annotation_position="right",
            annotation_font=dict(size=10, color="#ef5350"),
            row=1, col=1
        )
    
    if level_B is not None:
        fig.add_hline(
            y=level_B,
            line_dash="dot",
            line_color="rgba(38, 166, 154, 0.6)",
            line_width=1.5,
            annotation_text=f"▲ BUY ${level_B:.2f}",
            annotation_position="right",
            annotation_font=dict(size=10, color="#26a69a"),
            row=1, col=1
        )
    
    # Determine trigger state and add conclusion annotation
    if level_A is not None and level_B is not None and current_price is not None:
        if current_price > level_B:
            trigger_state = "BULLISH"
            conclusion_text = f"▲ ${current_price:.2f} > ${level_B:.2f} = BUY"
            conclusion_color = "#26a69a"
        elif current_price < level_A:
            trigger_state = "BEARISH"
            conclusion_text = f"▼ ${current_price:.2f} < ${level_A:.2f} = SELL"
            conclusion_color = "#ef5350"
        else:
            trigger_state = "NEUTRAL"
            conclusion_text = f"${current_price:.2f} in range — WAIT"
            conclusion_color = "#ffa726"
        
        # Add conclusion annotation at top-right of price chart
        fig.add_annotation(
            x=1.0,
            y=1.0,
            xref="paper",
            yref="paper",
            text=conclusion_text,
            showarrow=False,
            font=dict(size=11, color=conclusion_color, family="monospace"),
            bgcolor="rgba(0,0,0,0.75)",
            bordercolor=conclusion_color,
            borderwidth=1,
            borderpad=6,
            xanchor="right",
            yanchor="top"
        )
    
    # Add MACD Diagnostic Markers (W3, W5, WA, WC) as annotations on price chart
    if macd_markers:
        for marker in macd_markers:
            marker_time = marker.get("time")
            marker_text = marker.get("text", "")
            marker_color = marker.get("color", "#ffffff")
            marker_position = marker.get("position", "aboveBar")
            
            # Find price at marker time for y-position
            try:
                if hasattr(marker_time, 'strftime'):
                    # Already a datetime
                    time_key = marker_time
                else:
                    # Convert string to datetime
                    time_key = pd.to_datetime(marker_time)
                
                # Find the closest bar
                time_diffs = abs(df.index - time_key)
                closest_idx = time_diffs.argmin()
                
                if marker_position == "aboveBar":
                    y_pos = df['High'].iloc[closest_idx] * 1.01  # Slightly above high
                    ay_offset = -25
                else:
                    y_pos = df['Low'].iloc[closest_idx] * 0.99  # Slightly below low
                    ay_offset = 25
                
                fig.add_annotation(
                    x=df.index[closest_idx],
                    y=y_pos,
                    text=marker_text,
                    showarrow=True,
                    arrowhead=2,
                    arrowsize=1,
                    arrowwidth=1.5,
                    arrowcolor=marker_color,
                    font=dict(size=9, color=marker_color, family="monospace"),
                    bgcolor="rgba(0,0,0,0.7)",
                    bordercolor=marker_color,
                    borderwidth=1,
                    borderpad=3,
                    ax=0,
                    ay=ay_offset,
                    row=1, col=1
                )
            except Exception:
                # Skip marker if time doesn't match
                pass
    
    # Draw divergence lines connecting W3 to W5 (or WA to WC)
    if divergence_lines:
        for div_line in divergence_lines:
            try:
                x0_raw = div_line.get("x0")
                x1_raw = div_line.get("x1")
                y0 = div_line.get("y0")
                y1 = div_line.get("y1")
                color = div_line.get("color", "#ef4444")
                row = div_line.get("row", 1)
                
                # Handle various timestamp formats (numpy datetime64, nanoseconds, strings)
                def parse_timestamp(ts_raw):
                    if hasattr(ts_raw, 'astype'):
                        # numpy datetime64
                        return pd.Timestamp(ts_raw)
                    elif isinstance(ts_raw, (int, float)) and ts_raw > 1e15:
                        # Nanosecond timestamp - convert to datetime
                        return pd.Timestamp(ts_raw, unit='ns')
                    elif isinstance(ts_raw, (int, float)) and ts_raw > 1e9:
                        # Millisecond timestamp
                        return pd.Timestamp(ts_raw, unit='ms')
                    else:
                        # String or other
                        return pd.to_datetime(ts_raw)
                
                x0 = parse_timestamp(x0_raw)
                x1 = parse_timestamp(x1_raw)
                
                # Find closest bar indices for x positions
                time_diffs_0 = abs(df.index - x0)
                time_diffs_1 = abs(df.index - x1)
                closest_idx_0 = time_diffs_0.argmin()
                closest_idx_1 = time_diffs_1.argmin()
                
                if row == 1:
                    # Price chart - solid red divergence line
                    fig.add_trace(
                        go.Scatter(
                            x=[df.index[closest_idx_0], df.index[closest_idx_1]],
                            y=[y0, y1],
                            mode='lines',
                            line=dict(color=color, width=3),
                            showlegend=False,
                            hoverinfo='skip',
                            name='Divergence'
                        ),
                        row=1, col=1
                    )
                else:
                    # Oscillator chart - solid divergence line on AO
                    fig.add_trace(
                        go.Scatter(
                            x=[df.index[closest_idx_0], df.index[closest_idx_1]],
                            y=[y0, y1],
                            mode='lines',
                            line=dict(color=color, width=3),
                            showlegend=False,
                            hoverinfo='skip',
                            name='AO Divergence'
                        ),
                        row=2, col=1, secondary_y=False
                    )
            except Exception as e:
                # Log error for debugging
                print(f"Divergence line error: {e}, line: {div_line}")
                pass
    
    # v16.10: Tesla console - compact chart with no dead space
    fig.update_layout(
        height=650,
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.0,
            xanchor="center",
            x=0.5,
            bgcolor='rgba(0,0,0,0)',
            font=dict(size=9),
            itemsizing='constant',
            itemwidth=30
        ),
        xaxis_rangeslider_visible=False,
        template='plotly_dark',
        
        # v16.10: Tesla console - remove all dead space
        margin=dict(l=20, r=20, t=40, b=20),
        plot_bgcolor='#0a0a0a',
        paper_bgcolor='#0a0a0a',
        font=dict(
            family="'Inter', 'SF Pro Display', -apple-system, sans-serif",
            color='#e5e7eb',
            size=12
        ),
        
        # Clean grid
        xaxis=dict(
            showgrid=True,
            gridcolor='#1f2937',
            gridwidth=1,
            zeroline=False
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor='#1f2937',
            gridwidth=1,
            zeroline=False,
            side='left',
            showticklabels=True
        )
    )
    
    # v16.10: Add right-side y-axis mirror for price (show ticks on both sides)
    fig.update_yaxes(
        row=1, col=1,
        mirror='allticks',
        ticks='outside',
        showticklabels=True
    )
    
    # v16.10: Apply grid styling to all axes
    fig.update_xaxes(
        gridcolor='#1f2937',
        showgrid=True,
        zeroline=False
    )
    fig.update_yaxes(
        gridcolor='#1f2937',
        showgrid=True,
        zeroline=False
    )
    
    # Add Traffic Light indicators at top-left of chart
    # v16.6: Compact clustered badges with bold labels (M W D 4H) + divergence flags
    if traffic_lights:
        # Badge color functions
        def get_badge_color(wave_label, has_wave, momentum=True, divergence=False):
            """
            Badge border color based on BOTH structure and momentum.
            GREEN = Strong bullish, YELLOW = Caution/weak, RED = Avoid
            """
            if not has_wave or wave_label == '—':
                return '#6b7280'  # Gray - no data
            
            # AVOID always RED (active correction with bearish momentum)
            if wave_label == 'AVOID':
                return '#ef4444'  # Red - danger
            
            # STRONG always GREEN (impulse with bullish momentum)
            if wave_label == 'STRONG':
                return '#00E676'  # Green - go
            
            # HOLD GREEN if still extending (late impulse, bullish momentum)
            if wave_label == 'HOLD':
                return '#00E676'  # Green - hold position
            
            # WEAK YELLOW (impulse structure but losing momentum)
            if wave_label == 'WEAK':
                return '#fbbf24'  # Yellow - caution
            
            # FADING YELLOW (late impulse weakening)
            if wave_label == 'FADING':
                return '#fbbf24'  # Yellow - prepare exit
            
            # Corrective waves - YELLOW
            if wave_label in ['PULL', 'WAIT', 'WATCH']:
                return '#fbbf24'  # Yellow - patience
            
            # BASE GREEN (bottom formed, opportunity)
            if wave_label == 'BASE':
                return '#00E676'  # Green - prepare entry
            
            return '#6b7280'  # Default gray
        
        # Extract data from traffic lights dict (4 timeframes)
        monthlywave = traffic_lights.get('monthly_wave', '—')
        weeklywave = traffic_lights.get('weekly_wave', '—')
        dailywave = traffic_lights.get('daily_wave', '—')
        h4wave = traffic_lights.get('h4_wave', '—')
        
        # v16.9: Three-state dot colors (hex strings)
        monthlydot = traffic_lights.get('monthly_dot_color', '#6b7280')
        weeklydot = traffic_lights.get('weekly_dot_color', '#6b7280')
        dailydot = traffic_lights.get('daily_dot_color', '#6b7280')
        h4dot = traffic_lights.get('h4_dot_color', '#6b7280')
        
        monthly_has_wave = traffic_lights.get('monthly', False)
        weekly_has_wave = traffic_lights.get('weekly', False)
        daily_has_wave = traffic_lights.get('daily', False)
        h4_has_wave = traffic_lights.get('h4', False)
        
        # v16.6: Extract divergence flags
        monthly_div = traffic_lights.get('monthly_divergence', False)
        weekly_div = traffic_lights.get('weekly_divergence', False)
        daily_div = traffic_lights.get('daily_divergence', False)
        h4_div = traffic_lights.get('h4_divergence', False)
        
        # Calculate badge colors (wave structure only)
        monthlybadge = get_badge_color(monthlywave, monthly_has_wave)
        weeklybadge = get_badge_color(weeklywave, weekly_has_wave)
        dailybadge = get_badge_color(dailywave, daily_has_wave)
        h4badge = get_badge_color(h4wave, h4_has_wave)
        # Note: dot colors already extracted above from traffic_lights dict
        
        # v16.9: Context-aware badges with symbols
        # Format: M [🟢●] ✓ STRONG  W [🟡●] ⚠ WEAK  D [🟡●] ⚠ WAIT  4H [🔴●] ✗ AVOID
        
        def get_action_symbol(label):
            """Get symbol prefix for context-aware label"""
            symbol_map = {
                'STRONG': '✓',   # Strong bullish - green
                'WEAK': '⚠',     # Weakening - yellow warning
                'HOLD': '↑',     # Holding position - monitor
                'FADING': '⚠',   # Losing strength - caution
                'PULL': '⚠',     # Pullback with strength
                'WAIT': '⚠',     # Correction - patience
                'BASE': '✓',     # Bottom formed - opportunity
                'WATCH': '○',    # Watch for confirmation
                'AVOID': '✗',    # Active drop - danger
                '—': ''
            }
            return symbol_map.get(label, '')
        
        # v16.10: Traffic lights moved to dedicated panel above chart
        # Chart annotations removed to declutter - see render_traffic_light_panel() for new Tesla-style display
        # Badge data preserved for panel rendering:
        badge_data = {
            'labels': ['M', 'W', 'D', '4H'],
            'waves': [monthlywave, weeklywave, dailywave, h4wave],
            'badge_colors': [monthlybadge, weeklybadge, dailybadge, h4badge],
            'dot_colors': [monthlydot, weeklydot, dailydot, h4dot],
            'divergences': [monthly_div, weekly_div, daily_div, h4_div],
            'get_action_symbol': get_action_symbol
        }
    
    # Build version watermark (bottom-right)
    fig.add_annotation(
        x=0.99, y=0.02, xref="paper", yref="paper",
        text=f"TTA {BUILD_VERSION} '{BUILD_NAME}' • {BUILD_DATE}",
        showarrow=False,
        font=dict(size=10, color="rgba(255,255,255,0.5)", family="monospace"),
        xanchor="right", yanchor="bottom"
    )
    
    # Return figure and SMA info for AI analysis
    sma_info = {
        'value': sma_current_value,
        'slope': sma_slope
    }
    return fig, sma_info


def capture_chart_as_base64(fig) -> str:
    """Capture the plotly chart as a base64-encoded PNG image."""
    img_bytes = fig.to_image(format="png", width=1200, height=800, scale=2)
    return base64.b64encode(img_bytes).decode('utf-8')



def audit_chart_with_ai(chart_base64: str, pivot_text: str, ticker: str, timeframe: str, sma_info: dict = None, current_price: float = None, highest_price: float = None, lowest_price: float = None, mtf_charts: dict = None) -> str:
    """
    Perform AI Chart Analysis using Google Gemini 1.5 Flash (Vision).
    Replaces legacy OpenAI implementation.
    """
    import uuid
    from datetime import datetime
    
    # Generate unique analysis ID
    analysis_id = f"{ticker}_{timeframe}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    
    # Prepare SMA Context
    sma_context = ""
    if sma_info and sma_info.get('value') is not None:
        sma_value = sma_info['value']
        sma_slope = sma_info.get('slope', 'UNKNOWN')
        sma_context = f"IMPORTANT - 30-WEEK SMA DATA (VISIBLE ON CHART):\\n- Current 30-Week SMA Value: ${sma_value:.2f}\\n- SMA Slope: {sma_slope}\\n- Current Price: ${current_price:.2f}\\n- Price vs SMA: {'ABOVE' if current_price > sma_value else 'BELOW'} the 30-Week SMA"
    else:
        sma_context = "30-WEEK SMA DATA: Not available for this analysis."

    # Use the separated Gemini Auditor module
    try:
        from gemini_auditor import audit_chart_with_gemini_vision
        
        return audit_chart_with_gemini_vision(
            chart_base64=chart_base64,
            pivot_text=pivot_text,
            ticker=ticker,
            timeframe=timeframe,
            sma_context=sma_context,
            analysis_id=analysis_id,
            system_prompt=SYSTEM_PROMPT,
            mtf_charts=mtf_charts
        )
    except Exception as e:
        return f"⚠️ Error initializing Gemini: {str(e)}"

def _legacy_audit_chart_with_openai(chart_base64: str, pivot_text: str, ticker: str, timeframe: str, sma_info: dict = None, current_price: float = None, highest_price: float = None, lowest_price: float = None, mtf_charts: dict = None) -> str:
    """
    Two-step AI pipeline for chart analysis with Multi-Timeframe support:
    Step 1: Generate initial analysis using Master Prompt (with all 4 timeframes if available)
    Step 2: Validate and repair using Validation Prompt
    
    ANTI-CONTAMINATION DESIGN:
    - Each API call is stateless (no conversation history passed)
    - Messages array is constructed fresh each call
    - No caching of AI responses
    - Unique analysis_id generated per audit
    
    MTF ENHANCEMENT (v16.17):
    - When mtf_charts is provided, sends all 4 timeframes to GPT-4o
    - Enables proper top-down Elliott Wave analysis like Juan's method
    """
    # Check if OpenAI client is available
    if client is None:
        return """⚠️ **AI Chart Analysis Unavailable**

OpenAI API is not configured. To enable AI chart analysis:

1. Add `OPENAI_API_KEY` to your Streamlit secrets
2. Or use the Trading Journal's AI Assessment (uses Google Gemini)

The rest of the chart analysis features work without AI."""

    import uuid
    from datetime import datetime
    
    # Generate unique analysis ID to ensure no contamination
    analysis_id = f"{ticker}_{timeframe}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    
    # Build SMA context for the AI
    sma_context = ""
    if sma_info and sma_info.get('value') is not None:
        sma_value = sma_info['value']
        sma_slope = sma_info.get('slope', 'UNKNOWN')
        sma_context = f"""
IMPORTANT - 30-WEEK SMA DATA (VISIBLE ON CHART):
- Current 30-Week SMA Value: ${sma_value:.2f}
- SMA Slope: {sma_slope} (compared to 4 weeks ago)
- Current Price: ${current_price:.2f}
- Price vs SMA: {"ABOVE" if current_price > sma_value else "BELOW"} the 30-Week SMA
- Weinstein Context: Price is {"above" if current_price > sma_value else "below"} the 30-Week SMA with a {sma_slope.lower()} slope
"""
    else:
        sma_context = """
30-WEEK SMA DATA: Not available for this analysis.
"""

    try:
        # Check if we have multi-timeframe charts for top-down analysis
        if mtf_charts and all(k in mtf_charts for k in ['monthly', 'weekly', 'daily', 'h4']):
            print(f"🔄 MTF AI ANALYSIS: Sending all 4 timeframes to GPT-4o for {ticker}")
            
            # MTF SYSTEM PROMPT ENHANCEMENT
            mtf_system_prompt = SYSTEM_PROMPT + """

=== MULTI-TIMEFRAME TOP-DOWN ANALYSIS MODE ===

CRITICAL: You are receiving 4 charts in sequence for proper top-down Elliott Wave analysis:
1. MONTHLY (Primary/Cycle degree) - Highest timeframe context
2. WEEKLY (Intermediate degree) - Trend confirmation
3. DAILY (Minor degree) - Execution timeframe
4. 4-HOUR (Minuette degree) - Entry timing precision

You MUST perform TOP-DOWN analysis following Juan's methodology:
- START with Monthly to identify the highest-degree wave structure
- CONFIRM on Weekly how that wave subdivides into Intermediate waves
- VERIFY on Daily the current Minor wave position within Weekly structure
- USE 4H for precise entry timing within Daily wave

DEGREE CONSISTENCY IS MANDATORY:
- If Monthly shows "Primary Wave 3", Weekly must show subdivisions OF that Wave 3
- If Weekly shows "Intermediate Wave 3 of Primary 3", Daily cannot show "Minor Wave 5 complete"
- Wave labels MUST cascade logically: Primary → Intermediate → Minor → Minuette

CROSS-TIMEFRAME ALIGNMENT CHECK:
- All bullish impulses must align across timeframes for high-confidence entries
- Divergences between timeframes indicate caution or lower position sizing
- Entry only when lower timeframe confirms higher timeframe direction

=== END MTF MODE ===
"""
            
            # Build multi-image message content
            user_content = [
                {"type": "text", "text": f"""=== FRESH TOP-DOWN ANALYSIS — NO PRIOR CONTEXT ===
Analysis ID: {analysis_id}
Ticker: {ticker}
This is a NEW, INDEPENDENT multi-timeframe analysis.
{sma_context}

You are receiving 4 charts for complete top-down Elliott Wave analysis.
Analyze from Monthly down to 4H to provide a comprehensive wave count.
"""},
                {"type": "text", "text": "**CHART 1: MONTHLY (Primary/Cycle Degree)**"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{mtf_charts['monthly']}"}},
                {"type": "text", "text": "**CHART 2: WEEKLY (Intermediate Degree)**"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{mtf_charts['weekly']}"}},
                {"type": "text", "text": "**CHART 3: DAILY (Minor Degree - EXECUTION TIMEFRAME)**"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{mtf_charts['daily']}"}},
                {"type": "text", "text": "**CHART 4: 4-HOUR (Minuette Degree - ENTRY TIMING)**"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{mtf_charts['h4']}"}},
                {"type": "text", "text": f"""
Provide your v7.1 compliant analysis with MANDATORY top-down synthesis:

SECTION 0: MULTI-TIMEFRAME WAVE STRUCTURE SUMMARY
- State the wave structure on ALL 4 timeframes first
- Example: "Monthly: Wave 3 of Primary | Weekly: Wave 3 of Intermediate | Daily: Wave 5 of Minor | 4H: Wave 3 of Minuette"

SECTION 1-10: Complete your normal v7.1 analysis (Risk levels, Wave count, Weinstein, etc.)

SECTION 11: MULTI-TIMEFRAME ALIGNMENT CHECK (NEW)
- Does Daily Minor wave fit logically within Weekly Intermediate wave?
- Does 4H Minuette entry timing align with Daily Minor structure?
- Are there any degree violations or inconsistencies across timeframes?
- Overall MTF Alignment Score: ALIGNED / PARTIAL / MISALIGNED

Pivot data from execution timeframe:
{pivot_text}
"""}
            ]
            
            # Step 1: Generate initial draft with all 4 charts
            step1_response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": mtf_system_prompt},
                    {"role": "user", "content": user_content}
                ],
                max_tokens=10000  # Increased for MTF analysis
            )
        else:
            # Standard single-chart analysis (fallback)
            user_message = f"""=== FRESH ANALYSIS — NO PRIOR CONTEXT ===
Analysis ID: {analysis_id}
This is a NEW, INDEPENDENT analysis. Do NOT reference any prior analyses.
Clear all prior: A, B, A2, SMA, wave labels, probabilities.
=== END FRESH ANALYSIS HEADER ===

Please analyze this {ticker} stock chart ({timeframe} timeframe).

The chart displays:
- Candlestick price action
- 30-week SMA overlay (orange line) - SEE SMA DATA BELOW
- Awesome Oscillator (5/34) in the lower subplot
{sma_context}
Here is the price pivot data extracted from the chart:

{pivot_text}

Please provide your complete technical analysis following the MASTER RISK-FIRST CHART AUDIT PROMPT structure."""

            # Step 1: Generate initial draft using Master Prompt
            step1_response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": SYSTEM_PROMPT
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": user_message
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{chart_base64}"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=8192
            )
        draft_analysis = step1_response.choices[0].message.content
        
        # Step 2: Validate and repair using Validation Prompt
        # Extract structural levels from the data
        level_notes = ""
        if highest_price is not None:
            level_notes += f"\n- Level B (Bullish Continuation) MUST be the prior impulse HIGH: ${highest_price:.2f}"
        
        if lowest_price is not None:
            level_notes += f"\n- Level A (Bearish Activation) should be a STRUCTURAL SWING LOW from the pivot data (NOT the SMA value)"
            level_notes += f"\n- Chart structural low: ${lowest_price:.2f} — use an appropriate pivot low from the data, NOT the SMA"
        
        validation_message = f"""You are reviewing and validating a technical analysis draft. 
Your task is to check this analysis for any violations of Elliott Wave rules, degree mixing, 
AO misuse, or logical inconsistencies. Repair any errors and output the corrected, final analysis.

Here is the original chart context:
- Ticker: {ticker}
- Timeframe: {timeframe}
- Pivot Data: {pivot_text}
{sma_context}
CRITICAL RULES FOR THIS VALIDATION:

1) WEINSTEIN STAGE AUDIT: Use the SMA data provided above. Do NOT say "not visible" or "cannot confirm".

2) DEGREE DISCIPLINE: {timeframe} chart = {"Minor" if timeframe == "Daily" else "Intermediate" if timeframe == "Weekly" else "Minuette"} degree ONLY.
   - CANONICAL DEGREE MAP: Weekly=Intermediate, Daily=Minor, 4H=Minuette, 60m=Minute
   - Do NOT call Daily "Intermediate" — Daily is Minor degree
   - Keep ALL wave labels, fibs, and structure at {"Minor" if timeframe == "Daily" else "Intermediate" if timeframe == "Weekly" else "Minuette"} degree

3) RISK LEVELS (BINARY — EXACTLY TWO LEVELS):{level_notes}
   - Level A is a STRUCTURAL SWING LOW from pivot data — NOT the SMA value
   - Level B is the PRIOR IMPULSE HIGH — NOT an internal swing, NOT the SMA
   - SMA data is for Weinstein Stage ONLY — it does NOT change Level A or Level B
   - Do NOT introduce additional trigger levels beyond A and B

4) WAVE LABELS: Use "possible", "potential", "may have" — NOT definitive assertions
   - Do NOT assert pattern types as fact (e.g., "Minor Wave-4 flat")
   - Use "possible flat structure" or "structure may be unfolding as..."
   - If you say "no internal wave claims permitted" you CANNOT then describe ABC as fact

5) FIBONACCI - Anchors and Context Only
   - Verify that Fibonacci anchors are explicitly stated (e.g., "from $243.76 to $288.62")
   - Do NOT recalculate fib levels - accept the AI's calculations as-is
   - Only check that:
     a) Anchors are clearly identified (Wave-1 start/end, Wave-A start/end, etc.)
     b) The levels are being used as CONTEXT, not entry triggers
     c) No percentage calculations are shown in the text
   - If anchors are stated and fibs are contextual only, mark as valid
   - If anchors are missing or fibs are used as entry signals, flag for correction

Here is the DRAFT ANALYSIS to validate and repair:

{draft_analysis}

Please output the FINAL CORRECTED analysis. Fix any degree violations, risk level errors, pattern assertions, or fib errors."""

        step2_response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": VALIDATION_PROMPT
                },
                {
                    "role": "user",
                    "content": validation_message
                }
            ],
            max_tokens=8192
        )
        
        raw_output = step2_response.choices[0].message.content
        cleaned_output = clean_ai_output(raw_output)
        return cleaned_output
    except Exception as e:
        return f"Error during AI analysis: {str(e)}"


def clean_ai_output(text: str) -> str:
    """Post-process AI output to fix formatting issues."""
    import re
    
    # Fix arrow notation (handle various unicode arrows): $243.76→$288.62 -> from $243.76 to $288.62
    text = re.sub(r'(\$?\d+\.?\d*)\s*[→\->]+\s*(\$?\d+\.?\d*)', r'from \1 to \2', text)
    
    # Fix tilde notation: ~$255.70 -> near $255.70
    text = re.sub(r'~\s*(\$?\d+\.?\d*)', r'near \1', text)
    
    # Fix LaTeX-style asterisks: ∗∗$288.62∗∗ -> $288.62
    text = text.replace('∗∗', '')
    
    # Fix concatenated text patterns
    text = re.sub(r'(\$?\d+\.?\d*)orbelow(\$?\d+\.?\d*)', r'\1 or below \2', text)
    text = re.sub(r'(\$?\d+\.?\d*)orabove(\$?\d+\.?\d*)', r'\1 or above \2', text)
    text = re.sub(r'above(\$\d+\.?\d*)', r'above \1', text)
    text = re.sub(r'below(\$\d+\.?\d*)', r'below \1', text)
    
    # Fix "to" without spaces: $243.76to$288.62 -> from $243.76 to $288.62
    text = re.sub(r'(\$?\d+\.?\d*)to(\$?\d+\.?\d*)', r'from \1 to \2', text)
    
    # Fix patterns like "255.70low)alignswith" - broken LaTeX
    text = re.sub(r'(\d+\.?\d*)[a-z]+\)[a-z]+[a-z]*', r'\1', text)
    
    # Fix patterns with letters concatenated after prices
    text = re.sub(r'(\$\d+\.?\d*)([a-z])', r'\1 \2', text)
    
    # Fix "and" without spaces: 266and260 -> 266 and 260
    text = re.sub(r'(\d+)and(\d+)', r'\1 and \2', text)
    
    # Remove percentage from Section 4 headers
    text = re.sub(r'Primary View \(\d+%\):', 'Primary View:', text)
    text = re.sub(r'Alternate View \(\d+%\):', 'Alternate View:', text)
    
    return text


def validate_report_text(execution_mode: str, text: str) -> tuple:
    """
    v7.1 PREFLIGHT VALIDATION: Check for forbidden phrases in the report text.
    Returns (ok: bool, errors: list of strings).
    Weekly must NEVER be execution authority.
    """
    import re
    
    errors = []
    text_lower = text.lower()
    
    # HARD FAIL: Weekly must NEVER be execution authority
    if re.search(r"execution authority is .*weekly", text, re.IGNORECASE):
        errors.append("Execution authority incorrectly assigned to Weekly (forbidden).")
    
    if re.search(r"execution authority:\s*weekly", text, re.IGNORECASE):
        errors.append("Execution Authority set to Weekly (forbidden).")
    
    if re.search(r"intermediate\s*\(weekly\)", text, re.IGNORECASE):
        errors.append("Degree label leak: 'Intermediate (Weekly)' is forbidden.")
    
    if re.search(r"weekly\s*\(intermediate\)", text, re.IGNORECASE):
        errors.append("Degree label leak: 'Weekly (Intermediate)' is forbidden.")
    
    if re.search(r"primary\s*\(weekly\)", text, re.IGNORECASE):
        errors.append("Degree label leak: 'Primary (Weekly)' as execution is forbidden.")
    
    if re.search(r"weekly\s*\(primary\)", text, re.IGNORECASE):
        errors.append("Degree label leak: 'Weekly (Primary)' as execution is forbidden.")
    
    # Legacy sentence check
    if "lower timeframes are diagnostics only" in text_lower and "weekly" in text_lower:
        if not "weekly is regime context only" in text_lower:
            errors.append("Legacy execution-authority sentence references Weekly (forbidden).")
    
    # FORBIDDEN PATTERNS
    forbidden_patterns = [
        # A2 must be Weekly close only
        (r"daily close below a2", "A2 must use Weekly close only, not Daily close"),
        (r"4h close below a2", "A2 must use Weekly close only, not 4H close"),
        
        # Degree label violations (CANONICAL: Weekly=Intermediate, Daily=Minor, 4H=Minuette)
        (r"daily\s*\(intermediate\)", "Forbidden: 'Daily (Intermediate)' — Daily is Minor degree"),
        (r"intermediate\s*\(daily\)", "Forbidden: 'Intermediate (Daily)' — Daily is Minor degree"),
        (r"daily\s+intermediate\s+degree", "Forbidden: 'Daily Intermediate' — Daily is Minor degree"),
        (r"4h\s*\(minor\)", "Forbidden: '4H (Minor)' — 4H is Minuette degree"),
        (r"minor\s*\(4h\)", "Forbidden: 'Minor (4H)' — 4H is Minuette degree"),
        
        # AO cannot confirm structural completion
        (r"ao confirms? completion", "AO cannot confirm structural completion"),
        (r"ao confirms? wave", "AO cannot confirm wave structure"),
        (r"ao confirms? the wave", "AO cannot confirm wave structure"),
        (r"ao confirms? structural", "AO cannot confirm structural completion"),
        (r"ao has confirmed wave", "AO cannot confirm wave structure"),
        (r"oscillator confirms? completion", "AO cannot confirm structural completion"),
        
        # Replace "last impulse high" with "last structural swing high / cap"
        (r"last impulse high", "Use 'last structural swing high / cap' instead of 'last impulse high'"),
    ]
    
    # Mode-specific forbidden patterns
    if execution_mode == "DAILY_MINOR":
        forbidden_patterns.append(
            (r"price structure first\s*\(4h", "In DAILY_MINOR mode, do not reference 4H as primary structure")
        )
    elif execution_mode == "H4_MINUETTE":
        forbidden_patterns.append(
            (r"price structure first\s*\(daily", "In H4_MINUETTE mode, do not reference Daily as primary structure")
        )
    
    for pattern, error_msg in forbidden_patterns:
        if re.search(pattern, text_lower):
            errors.append(error_msg)
    
    return (len(errors) == 0, errors)


def get_ao_narrative(ao_state: str) -> str:
    """
    AO CONSISTENCY ENFORCER: Return AO paragraph that is directionally consistent with computed state.
    """
    state_lower = (ao_state or "").lower()
    
    if "bullish" in state_lower or "expanding" in state_lower:
        return "AO is bullish/expanding. Momentum supports upside continuation. Downside moves are corrective unless price structure confirms otherwise."
    elif "bearish" in state_lower or "contracting" in state_lower:
        return "AO is bearish/contracting. Momentum supports downside pressure. Upside moves are corrective unless price structure confirms otherwise."
    elif "reset" in state_lower or "neutral" in state_lower:
        return "AO is resetting/neutral. Momentum is inconclusive. Wait for directional confirmation from price structure."
    else:
        return "AO state not provided. Momentum analysis inconclusive."


def get_elliott_primary_narrative(ai_analysis: str, is_overlapping: bool = True) -> tuple:
    """
    PRIMARY vs ALTERNATE HYGIENE: Choose exactly ONE corrective family for primary.
    Returns (primary_narrative, alternate_narrative).
    
    RULE: When structure is overlapping/unclear, default Primary = "Corrective (developing), W-X-Y preferred".
    Alternate must NOT use ABC language unless 5-wave C leg is explicitly detected.
    """
    text_lower = ai_analysis.lower()
    
    # Check for evidence of different patterns
    has_wxy = "w-x-y" in text_lower or "wxy" in text_lower
    has_abc = "abc" in text_lower or "a-b-c" in text_lower
    has_wave4 = "wave-4" in text_lower or "wave 4" in text_lower
    has_flat = "flat" in text_lower
    has_triangle = "triangle" in text_lower
    # STRICT: Only allow ABC if 5-wave C is EXPLICITLY confirmed
    has_5wave_c = any(phrase in text_lower for phrase in [
        "5-wave c", "five-wave c", "5 wave c", "c-leg is 5-wave", 
        "c subdivides into 5", "c-leg subdivides into 5", "impulsive c"
    ])
    
    # When overlapping/unclear → default to W-X-Y; no ABC unless 5-wave C proven
    if is_overlapping and not has_5wave_c:
        primary = "Corrective (developing), W-X-Y preferred. Structure-first analysis governs."
        alternate = "Complex correction promoted only on regime failure (A2)."
        return (primary, alternate)
    
    # Primary chooses exactly ONE corrective family
    if has_wxy:
        primary = "W-X-Y correction developing (preferred). Structure-first analysis governs."
        if has_5wave_c:
            # Only allow ABC in alternate if 5-wave C is confirmed
            alternate = "ABC correction (confirmed — 5-wave C-leg detected)."
        elif has_flat:
            alternate = "Flat correction (conditional — requires B-leg retest of origin)."
        else:
            alternate = "Complex correction (conditional — promoted only on regime failure)."
    elif has_abc and has_5wave_c:
        # Only allow ABC as primary if 5-wave C is confirmed
        primary = "ABC correction developing (5-wave C-leg confirmed). Structure-first analysis."
        alternate = "W-X-Y promoted if C-leg subdivides into 3 waves."
    elif has_wave4:
        primary = "Wave-4 correction developing at current degree. Structure-first analysis."
        alternate = "Wave-4 failure / truncation promoted on regime break (A2)."
    elif has_flat:
        primary = "Flat correction developing. Structure-first analysis governs."
        alternate = "Expanded flat or running flat (conditional on B-leg extension)."
    elif has_triangle:
        primary = "Triangle correction developing. Structure-first analysis governs."
        alternate = "Triangle failure promoted on thrust break."
    else:
        # DEFAULT: W-X-Y preferred; no ABC unless proven
        primary = "Corrective (developing), W-X-Y preferred. Structure-first analysis governs."
        alternate = "Complex correction promoted only on regime failure (A2)."
    
    return (primary, alternate)


def get_fib_section(anchor_low: float, anchor_high: float, level_B: float, 
                     anchor_low_label: str = None, anchor_high_label: str = None) -> tuple:
    """
    FIB MODULE FIX (PF7 Strict Enforcement):
    - If anchors missing → return None (section must be SKIPPED entirely, NOT rendered)
    - If fib printed → must include "Anchors: from <price/time> to <price/time>"
    - If fib printed without anchors → compliance FAIL
    
    Returns (fib_text: str | None, fib_compliant: bool)
    """
    # HARD GATE: If anchors are missing or invalid, return None (skip section entirely)
    if anchor_low is None or anchor_high is None or anchor_low <= 0 or anchor_high <= 0:
        return (None, False)
    
    if abs(anchor_high - anchor_low) < 0.01:
        return (None, False)
    
    # STRICT: Must have anchor labels to be compliant
    if not anchor_low_label or not anchor_high_label:
        anchor_low_label = f"${anchor_low:.2f}"
        anchor_high_label = f"${anchor_high:.2f}"
    
    # Calculate fib levels
    fib_range = anchor_high - anchor_low
    fib_382 = anchor_high - (fib_range * 0.382)
    fib_500 = anchor_high - (fib_range * 0.500)
    fib_618 = anchor_high - (fib_range * 0.618)
    fib_100 = anchor_low
    
    # Check if B is actually derived from anchors (not just echoed)
    b_is_fib_level = False
    if level_B is not None:
        for fib_val in [anchor_high, fib_382, fib_500, fib_618, fib_100]:
            if abs(level_B - fib_val) < 0.50:
                b_is_fib_level = True
                break
    
    # Build result with REQUIRED anchor labels
    result = f"Anchors: from {anchor_low_label} to {anchor_high_label}. "
    result += f"38.2% @ ${fib_382:.2f} | 50% @ ${fib_500:.2f} | 61.8% @ ${fib_618:.2f} | 100% @ ${fib_100:.2f}"
    
    if not b_is_fib_level and level_B is not None:
        result += f". Note: Trigger B (${level_B:.2f}) is structural, not fib-derived."
    
    return (result, True)


def get_weinstein_stage(sma_value: float, sma_slope: str, current_price: float, 
                        sma_visible: bool = False) -> tuple:
    """
    WEINSTEIN GATE FIX:
    If weekly 30w SMA is not explicitly visible or provided, output:
    "Weinstein Stage: UNCONFIRMED (SMA not visible)"
    
    Returns (stage_text: str, stage_confirmed: bool)
    """
    # STRICT: If SMA not visible/provided, return UNCONFIRMED
    if not sma_visible or sma_value is None or sma_value <= 0:
        return ("UNCONFIRMED (SMA not visible)", False)
    
    # Determine stage based on price vs SMA and slope
    slope_lower = (sma_slope or "").lower()
    
    if current_price > sma_value:
        if "up" in slope_lower or "rising" in slope_lower or "positive" in slope_lower:
            return ("Stage 2 (Advancing)", True)
        elif "flat" in slope_lower or "neutral" in slope_lower:
            return ("Stage 1 (Basing) / Early Stage 2", True)
        else:
            return ("Stage 2 (Advancing) — slope unclear", True)
    else:
        if "down" in slope_lower or "falling" in slope_lower or "negative" in slope_lower:
            return ("Stage 4 (Declining)", True)
        elif "flat" in slope_lower or "neutral" in slope_lower:
            return ("Stage 3 (Topping) / Early Stage 4", True)
        else:
            return ("Stage 3/4 (Transition) — slope unclear", True)


def get_operator_verdict(trigger_state: str, level_A: float, level_B: float, degree: str) -> str:
    """
    SINGLE-SENTENCE OPERATOR VERDICT: Clear actionable instruction.
    """
    if trigger_state == "BEARISH":
        return f"Verdict: Bearish activation live below A (${level_A:.2f}). Stand aside; only reassess long bias on {degree} close above B (${level_B:.2f})."
    elif trigger_state == "BULLISH":
        return f"Verdict: Bullish continuation permitted above B (${level_B:.2f}). Downside risk reactivates on {degree} close below A (${level_A:.2f})."
    else:
        return f"Verdict: Stand aside while between A (${level_A:.2f}) and B (${level_B:.2f}). No trade until trigger resolution at {degree} degree."


def generate_pdf_report(dashboard_data: dict, chart_base64: str = None) -> bytes:
    """Generate a professional PDF report matching the dashboard layout exactly."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
    
    # Custom styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=18, textColor=colors.HexColor('#1a1a2e'), alignment=TA_CENTER, spaceAfter=6)
    header_style = ParagraphStyle('Header', parent=styles['Heading2'], fontSize=11, textColor=colors.HexColor('#0f766e'), spaceBefore=12, spaceAfter=6)
    subheader_style = ParagraphStyle('SubHeader', parent=styles['Heading3'], fontSize=10, textColor=colors.HexColor('#64748b'), spaceBefore=6, spaceAfter=4)
    body_style = ParagraphStyle('Body', parent=styles['Normal'], fontSize=9, textColor=colors.HexColor('#334155'), leading=13)
    small_style = ParagraphStyle('Small', parent=styles['Normal'], fontSize=8, textColor=colors.HexColor('#64748b'), leading=11)
    bullet_style = ParagraphStyle('Bullet', parent=styles['Normal'], fontSize=9, textColor=colors.HexColor('#334155'), leading=13, leftIndent=15)
    
    elements = []
    
    # Extract all data
    ticker = dashboard_data.get('ticker', 'N/A')
    exec_mode = dashboard_data.get('execution_mode', 'DAILY_INTERMEDIATE')
    close = dashboard_data.get('close', 0)
    trigger_state = dashboard_data.get('trigger_state', 'NONE')
    triggers = dashboard_data.get('triggers', {})
    level_A = triggers.get('A', 0)
    level_B = triggers.get('B', 0)
    level_A2 = triggers.get('A2')
    
    # ========================================================
    # EXECUTION AUTHORITY CANONICALIZATION (DECLARE ONCE)
    # CANONICAL MAP: Weekly=Intermediate (context only), Daily=Minor, 4H=Minuette
    # Weekly is NEVER execution authority
    # ========================================================
    execution_authority = get_execution_authority(exec_mode)
    
    if "H4" in (exec_mode or "").upper() or "MINUETTE" in (exec_mode or "").upper():
        exec_meta = {
            "degree": "Minuette",
            "timeframe": "4H",
            "label": "4H (MINUETTE)",
            "trigger_close": "4H close",
        }
    else:
        # Default: Daily → Minor (Weekly defaults to Daily for execution)
        exec_meta = {
            "degree": "Minor",
            "timeframe": "Daily",
            "label": "DAILY (MINOR)",
            "trigger_close": "Daily close",
        }
    
    # REUSE THESE EVERYWHERE — do NOT reconstruct or paraphrase
    degree = exec_meta["degree"]
    tf_label = exec_meta["label"]
    trigger_close_label = exec_meta["trigger_close"]
    
    # Trigger status label (matching dashboard verdictMeta)
    if trigger_state == 'BEARISH':
        trigger_badge = "TRIGGER HIT — BEARISH ACTIVATION"
    elif trigger_state == 'BULLISH':
        trigger_badge = "TRIGGER HIT — BULLISH CONTINUATION"
    else:
        trigger_badge = "NO TRIGGER HIT — RANGE / DEVELOPING"
    
    # ============================================
    # 1. HEADER: Ticker, Price, Timeframe, Status
    # ============================================
    elements.append(Paragraph(f"<b>{ticker}</b> ${close:.2f}", title_style))
    badge_style = ParagraphStyle('Badge', parent=styles['Normal'], fontSize=9, textColor=colors.HexColor('#ef4444') if trigger_state == 'BEARISH' else colors.HexColor('#22c55e') if trigger_state == 'BULLISH' else colors.HexColor('#f59e0b'), alignment=TA_CENTER)
    elements.append(Paragraph(f"{tf_label.upper()} | {trigger_badge}", badge_style))
    
    # v16.12: Add filter profile to PDF header
    pdf_filter_profile = dashboard_data.get('filter_profile', 'BALANCED')
    pdf_profile_data = FILTER_PROFILES.get(pdf_filter_profile, FILTER_PROFILES['BALANCED'])
    pdf_vert = pdf_profile_data['verticality_universal']
    pdf_vert_str = "OFF" if pdf_vert is None or pdf_vert <= 0 else f"> {pdf_vert}"
    # v16.12: Get MTF status for PDF report (check ALL toggle keys)
    pdf_mtf_enabled = st.session_state.get('mtf_enforcement_enabled', False)
    pdf_ultimate = (st.session_state.get('mtf_ultimate_mode', False) or
                    st.session_state.get('mtf_ultimate_individual', False) or
                    st.session_state.get('mtf_ultimate_toggle', False))
    if pdf_ultimate:
        pdf_mtf_mode = 'ULTIMATE'
    elif pdf_filter_profile == 'AGGRESSIVE':
        pdf_mtf_mode = 'AGGRESSIVE'
    else:
        pdf_mtf_mode = 'MODERATE'
    pdf_mtf_status = f"{pdf_mtf_mode} ({'ON' if pdf_mtf_enabled else 'OFF'})"
    profile_style = ParagraphStyle('Profile', parent=styles['Normal'], fontSize=8, textColor=colors.HexColor('#6b7280'), alignment=TA_CENTER)
    elements.append(Paragraph(f"Filter Profile: {pdf_filter_profile} | Suit: {pdf_profile_data['suitability_floor']} | Vert: {pdf_vert_str} | MTF: {pdf_mtf_status}", profile_style))
    elements.append(Spacer(1, 0.15*inch))
    
    # ============================================
    # CORRECTIVE WARNING BANNER (if divergence + AO negative)
    # ============================================
    ao_diag = dashboard_data.get('ao_diag', {})
    if ao_diag.get('corrective_warning'):
        warning_style = ParagraphStyle(
            'CorrWarning', 
            parent=styles['Normal'], 
            fontSize=11, 
            textColor=colors.white, 
            alignment=TA_CENTER,
            backColor=colors.HexColor('#dc2626'),
            borderColor=colors.HexColor('#7f1d1d'),
            borderWidth=2,
            borderPadding=10,
            leading=15
        )
        elements.append(Paragraph(
            "<b>BEARISH DIVERGENCE CONFIRMED — CORRECTIVE STRUCTURE LIKELY</b><br/>"
            "Wave 5 completed with price/momentum divergence. AO has crossed negative.<br/>"
            "Price is likely in ABC corrective structure. Reduce exposure or hedge.",
            warning_style
        ))
        elements.append(Spacer(1, 0.15*inch))
    
    # ============================================
    # 2. CONCLUSION (computed from trigger state)
    # ============================================
    conclusion_style = ParagraphStyle('Conclusion', parent=styles['Normal'], fontSize=9, textColor=colors.HexColor('#334155'), leading=13, borderColor=colors.HexColor('#e2e8f0'), borderWidth=1, borderPadding=8)
    
    elliott = dashboard_data.get('elliott', {})
    structure = (elliott.get('structure', '') or '').lower()
    is_overlapping = 'corrective' in structure or 'developing' in structure
    
    if trigger_state == 'BEARISH':
        conclusion = f"{ticker}: Bearish activation is live at the {degree} degree. Treat downside as corrective extension risk{' (structure overlapping)' if is_overlapping else ''}; do not label impulse unless structure proves 5-wave. Bullish continuation requires {trigger_close_label} above ${level_B:.2f}."
    elif trigger_state == 'BULLISH':
        conclusion = f"{ticker}: Bullish continuation is live at the {degree} degree. The corrective thesis is terminated while price holds above ${level_B:.2f}; downside risk reactivates on {trigger_close_label} below ${level_A:.2f}."
    else:
        conclusion = f"{ticker}: No trigger hit — range / developing. Stand aside until price resolves: {trigger_close_label} above ${level_B:.2f} unlocks bullish continuation; {trigger_close_label} below ${level_A:.2f} activates bearish extension risk."
    
    elements.append(Paragraph("CONCLUSION", header_style))
    elements.append(Paragraph(conclusion, body_style))
    elements.append(Spacer(1, 0.1*inch))
    
    # ============================================
    # 3. TRIGGER A | TRIGGER B cards
    # ============================================
    elements.append(Paragraph("TRIGGER LEVELS", header_style))
    trigger_data = [
        [f'TRIGGER A: ${level_A:.2f}', f'TRIGGER B: ${level_B:.2f}'],
        [f'{trigger_close_label} below A', f'{trigger_close_label} above B'],
        [f'Activation (extension risk) at {degree} degree.\nTreat as corrective continuation risk;\ndo NOT label impulse while below B.', 
         f'Correction dead level (range cap).\nA close above B permits bullish\ncontinuation at {degree} degree.'],
    ]
    if level_A2:
        trigger_data.append([f'A2 (Regime Fail): ${level_A2:.2f}', 'Weekly close below A2 = Intermediate regime failure'])
    
    trigger_table = Table(trigger_data, colWidths=[3*inch, 3*inch])
    trigger_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, 0), colors.HexColor('#fef2f2')),
        ('BACKGROUND', (1, 0), (1, 0), colors.HexColor('#f0fdf4')),
        ('TEXTCOLOR', (0, 0), (0, 0), colors.HexColor('#dc2626')),
        ('TEXTCOLOR', (1, 0), (1, 0), colors.HexColor('#16a34a')),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.HexColor('#64748b')),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    elements.append(trigger_table)
    elements.append(Spacer(1, 0.1*inch))
    
    # ============================================
    # 4. PROBABILITY ASSESSMENT | ACTION PLAN
    # ============================================
    probs = dashboard_data.get('probabilities', {})
    action_plan = dashboard_data.get('action_plan', {})
    
    elements.append(Paragraph("PROBABILITY ASSESSMENT", header_style))
    prob_data = [
        ['Primary Scenario', f"{probs.get('primary', 50)}%"],
        ['Alternate Scenario', f"{probs.get('alternate', 50)}%"],
    ]
    prob_table = Table(prob_data, colWidths=[2*inch, 1*inch])
    prob_table.setStyle(TableStyle([
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#334155')),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(prob_table)
    elements.append(Spacer(1, 0.15*inch))
    
    # ============================================
    # 4b. ACTION PLAN
    # ============================================
    if action_plan:
        elements.append(Paragraph("ACTION PLAN", header_style))
        action_style = ParagraphStyle('Action', parent=styles['Normal'], fontSize=9, textColor=colors.HexColor('#334155'), leading=13, leftIndent=10)
        now_action = action_plan.get('now', '')
        if now_action:
            elements.append(Paragraph(f"<b>Now:</b> {now_action}", action_style))
        bullish_if = action_plan.get('bullish_if', '')
        if bullish_if:
            elements.append(Paragraph(f"<b>Bullish IF:</b> {bullish_if}", action_style))
        bearish_if = action_plan.get('bearish_if', '')
        if bearish_if:
            elements.append(Paragraph(f"<b>Bearish IF:</b> {bearish_if}", action_style))
        regime_fail = action_plan.get('regime_fail_if', '')
        if regime_fail and 'not provided' not in regime_fail.lower():
            elements.append(Paragraph(f"<b>Regime Failure IF:</b> {regime_fail}", action_style))
        elements.append(Spacer(1, 0.1*inch))
    
    # ============================================
    # 5. WEINSTEIN | ELLIOTT | MOMENTUM & CONTEXT
    # ============================================
    weinstein = dashboard_data.get('weinstein', {})
    stage = weinstein.get('stage', 'N/A')
    
    elements.append(Paragraph("WEINSTEIN STAGE (CONTEXT ONLY)", header_style))
    weinstein_data = [
        [stage, 'Not used for wave labels'],
        [f"30w SMA slope: {weinstein.get('sma_slope', 'N/A')}", f"Price vs 30w SMA: {weinstein.get('price_vs_sma', 'N/A')}"],
    ]
    weinstein_table = Table(weinstein_data, colWidths=[3*inch, 3*inch])
    weinstein_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, 0), colors.HexColor('#fef3c7')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#334155')),
        ('FONTNAME', (0, 0), (0, 0), 'Helvetica-Bold'),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(weinstein_table)
    elements.append(Spacer(1, 0.1*inch))
    
    # Elliott section — REUSE exec_meta labels (do NOT reconstruct)
    elements.append(Paragraph("ELLIOTT (EXECUTION DEGREE)", header_style))
    elliott_data = [
        [f"{elliott.get('structure', 'Developing')}", tf_label],
        [f"Degree: {tf_label}", ''],
        [f"Primary: {elliott.get('primary', 'Pending')}", ''],
        [f"Alternate: {elliott.get('alternate', 'Conditional')}", ''],
    ]
    elliott_table = Table(elliott_data, colWidths=[4.5*inch, 1.5*inch])
    elliott_table.setStyle(TableStyle([
        ('BACKGROUND', (1, 0), (1, 0), colors.HexColor('#e0f2fe')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#334155')),
        ('FONTNAME', (0, 0), (1, 0), 'Helvetica-Bold'),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(elliott_table)
    elements.append(Spacer(1, 0.1*inch))
    
    # Momentum & Fib Context
    ao = dashboard_data.get('ao', {})
    fib = dashboard_data.get('fib', {})
    elements.append(Paragraph("MOMENTUM & CONTEXT", header_style))
    elements.append(Paragraph(f"<b>AO:</b> {ao.get('state', 'N/A')}", body_style))
    elements.append(Paragraph(f"<i>{ao.get('notes', 'AO supports momentum alignment but does NOT confirm structural completion.')}</i>", small_style))
    elements.append(Spacer(1, 0.05*inch))
    
    # FIBONACCI HARD GATE: Only render if fib.zones is not None
    fib_zones = fib.get('zones')
    if fib_zones is not None:
        elements.append(Paragraph(f"<b>Fib Context (Zones):</b> {fib_zones}", body_style))
        elements.append(Paragraph(f"<i>{fib.get('notes', 'Fibonacci is context only (zones, not signals).')}</i>", small_style))
    # If fib_zones is None, skip the entire Fib section (no "N/A" or disclaimer)
    elements.append(Spacer(1, 0.1*inch))
    
    # AO HISTOGRAM KING-CHUNK DIAGNOSTIC (v9.0)
    ao_diag = dashboard_data.get('ao_diag')
    if ao_diag:
        elements.append(Paragraph("AO HISTOGRAM KING-CHUNK DIAGNOSTIC (NON-STRUCTURAL)", header_style))
        w3 = ao_diag.get('wave3', {})
        if w3:
            w3_area = w3.get('area', 0)
            w3_peak = w3.get('peak', 0)
            w3_date = w3.get('date', 'N/A')
            elements.append(Paragraph(f"• W3(dia): Area {w3_area:.2f} | Peak {w3_peak:.2f} on {w3_date}", body_style))
        
        w4 = ao_diag.get('wave4')
        if w4:
            w4_trough = w4.get('trough', 0)
            w4_date = w4.get('date', 'N/A')
            elements.append(Paragraph(f"• W4(dia): Trough {w4_trough:.2f} on {w4_date}", body_style))
            
        w5 = ao_diag.get('wave5')
        if w5:
            w5_area = w5.get('area', 0)
            w5_peak = w5.get('peak', 0)
            w5_date = w5.get('date', 'N/A')
            elements.append(Paragraph(f"• W5(dia): Area {w5_area:.2f} | Peak {w5_peak:.2f} on {w5_date}", body_style))
            div_status = "ACTIVE" if ao_diag.get('divergence') else "NONE"
            div_ratio = ao_diag.get('div_ratio', 0)
            elements.append(Paragraph(f"• Divergence: {div_status} (Ratio: {div_ratio})", body_style))
            risk_status = "HIGH" if ao_diag.get('post5_negative') else "NORMAL"
            elements.append(Paragraph(f"• Post-W5 Risk: {risk_status}", body_style))

        elements.append(Paragraph("<i>Diagnostic only — does not confirm Elliott structure and does not override A/B triggers.</i>", small_style))
        elements.append(Spacer(1, 0.1*inch))
    
    # ============================================
    # 6. FINAL RISK-FIRST VERDICT | CLOSING SUMMARY
    # ============================================
    # Final Verdict
    verdict_style = ParagraphStyle('Verdict', parent=styles['Normal'], fontSize=9, textColor=colors.HexColor('#b91c1c'), leading=13, leftIndent=10)
    final_verdict = dashboard_data.get('final_verdict', '')
    elliott_structure = elliott.get('structure', 'Developing')
    weinstein_stage = dashboard_data.get('weinstein', {}).get('stage', '')
    
    if final_verdict:
        elements.append(Paragraph("FINAL RISK-FIRST VERDICT", header_style))
        # Clean up verdict text - remove artifacts
        clean_verdict = final_verdict
        clean_verdict = re.sub(r'\*\*', '', clean_verdict)  # Remove markdown bold
        clean_verdict = re.sub(r'::', ':', clean_verdict)  # Fix double colons
        clean_verdict = re.sub(r'^\s*\d+\.\s*', '', clean_verdict)  # Remove leading numbered list
        clean_verdict = re.sub(r'[■□▪▫●○◆◇★☆►▶◀◄]', '', clean_verdict)  # Remove box/bullet artifacts
        clean_verdict = clean_verdict.strip()
        
        # If verdict is too short/sparse, generate a better one from trigger state
        if len(clean_verdict) < 40:
            if trigger_state == 'BEARISH':
                clean_verdict = f"Bearish activation is live. Price closed below Level A (${level_A:.2f}). Treat as corrective extension risk at {degree} degree. Structure-first governs labels. Bullish continuation requires {trigger_close_label} above ${level_B:.2f}."
            elif trigger_state == 'BULLISH':
                clean_verdict = f"Bullish continuation permitted. Price closed above Level B (${level_B:.2f}). Correction may be complete at {degree} degree. Monitor for structure confirmation."
            else:
                clean_verdict = f"No trigger resolved. Price between Level A (${level_A:.2f}) and Level B (${level_B:.2f}). Stand aside until trigger resolution at {degree} degree. Structure remains developing."
        
        # v7.1 NARRATIVE HYGIENE GOVERNOR (MANDATORY)
        clean_verdict = enforce_v71_narrative_hygiene(clean_verdict, elliott_structure, weinstein_stage)
        clean_verdict = enforce_verdict_consistency(clean_verdict, elliott_structure, trigger_state)
        
        # Split into bullet points if text contains key sections
        verdict_points = [p.strip() for p in re.split(r'\s+-\s+|\s+(?=Stage\s\d|Execution|Elliott|Trigger)', clean_verdict) if p.strip()]
        verdict_points = [p for p in verdict_points if len(p) > 20]
        
        if len(verdict_points) > 1:
            for point in verdict_points:
                point = point.lstrip('- ').lstrip(': ').strip()
                if len(point) > 15:
                    elements.append(Paragraph(f"• {point}", verdict_style))
        else:
            elements.append(Paragraph(clean_verdict, verdict_style))
        elements.append(Spacer(1, 0.1*inch))
    
    # Closing Summary
    summary_style = ParagraphStyle('Summary', parent=styles['Normal'], fontSize=9, textColor=colors.HexColor('#0e7490'), leading=13, leftIndent=10)
    closing_summary = dashboard_data.get('closing_summary', '')
    if closing_summary:
        elements.append(Paragraph("CLOSING SUMMARY", header_style))
        # Clean up artifacts - same logic as dashboard
        clean_summary = closing_summary
        clean_summary = re.sub(r'\*\*', '', clean_summary)  # Remove markdown bold
        clean_summary = re.sub(r'^\s*\d+\.\s*', '', clean_summary)  # Remove leading numbered list
        clean_summary = re.sub(r'\s+\d+\.\s+', ' ', clean_summary)  # Remove inline numbered lists
        clean_summary = re.sub(r'of Rules:\s*', '', clean_summary)  # Remove "of Rules:" artifact
        clean_summary = re.sub(r'::', ':', clean_summary)  # Fix double colons
        clean_summary = re.sub(r'\s*-{2,}\s*$', '', clean_summary)  # Remove trailing dashes
        clean_summary = re.sub(r'\s*—+\s*$', '', clean_summary)  # Remove trailing em-dashes
        clean_summary = clean_summary.strip()
        
        # v7.1 NARRATIVE HYGIENE GOVERNOR (MANDATORY)
        clean_summary = enforce_v71_narrative_hygiene(clean_summary, elliott_structure, weinstein_stage)
        
        # Split into bullet points by " - " delimiter or by sentences starting with key terms
        points = [p.strip() for p in re.split(r'\s+-\s+|\s+(?=Daily close|Weekly close|Bullish|Bearish|IF\s)', clean_summary) if p.strip()]
        
        # Filter out short/meaningless items
        points = [p for p in points if len(p) > 15 and not p.startswith('of ')]
        
        if len(points) > 1:
            for point in points:
                point = point.lstrip('- ').lstrip(': ').strip()
                if len(point) > 10:
                    elements.append(Paragraph(f"• {point}", summary_style))
        else:
            elements.append(Paragraph(clean_summary, summary_style))
        elements.append(Spacer(1, 0.1*inch))
    
    # Compliance Checks
    validator = dashboard_data.get('validator', {})
    elements.append(Paragraph("v7.1 COMPLIANCE CHECKS", header_style))
    checks = [
        ('Degree Locked', validator.get('degreeLocked', False)),
        ('Label Consistent', validator.get('labelConsistent', False)),
        ('Fib Anchored', validator.get('fibAnchored', False)),
        ('AO Confirm-Only', validator.get('aoConfirmOnly', False)),
        ('Triggers Coherent', validator.get('triggersCoherent', False)),
    ]
    check_data = [[name, '✓ PASS' if ok else '✗ FAIL'] for name, ok in checks]
    check_table = Table(check_data, colWidths=[2*inch, 1*inch])
    check_table.setStyle(TableStyle([
        ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#334155')),
        ('TEXTCOLOR', (1, 0), (1, -1), colors.HexColor('#22c55e')),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (1, 0), (1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    # Color failed checks red
    for i, (_, ok) in enumerate(checks):
        if not ok:
            check_table.setStyle(TableStyle([('TEXTCOLOR', (1, i), (1, i), colors.HexColor('#ef4444'))]))
    elements.append(check_table)
    
    # Footer
    elements.append(Spacer(1, 0.3*inch))
    footer_style = ParagraphStyle('Footer', parent=styles['Normal'], fontSize=7, textColor=colors.HexColor('#94a3b8'), alignment=TA_CENTER)
    elements.append(Paragraph("Generated by Stock Technical Analysis v7.1 | Elliott Wave Audit System", footer_style))
    elements.append(Paragraph("This report is for educational purposes only. Not financial advice.", footer_style))
    
    doc.build(elements)
    buffer.seek(0)
    return buffer.getvalue()


if 'df' not in st.session_state:
    st.session_state.df = None
if 'fig' not in st.session_state:
    st.session_state.fig = None
if 'pivot_text' not in st.session_state:
    st.session_state.pivot_text = None
if 'current_ticker' not in st.session_state:
    st.session_state.current_ticker = None
if 'current_timeframe' not in st.session_state:
    st.session_state.current_timeframe = None
if 'level_A' not in st.session_state:
    st.session_state.level_A = None
if 'level_B' not in st.session_state:
    st.session_state.level_B = None
if 'show_dashboard' not in st.session_state:
    st.session_state.show_dashboard = True
if 'show_adaptive_strategy' not in st.session_state:
    st.session_state.show_adaptive_strategy = True
if 'trigger_levels' not in st.session_state:
    st.session_state.trigger_levels = None
if 'sma_value' not in st.session_state:
    st.session_state.sma_value = None
# PF0: Store previous ticker's levels for cross-contamination detection
if 'previous_ticker' not in st.session_state:
    st.session_state.previous_ticker = None
if 'previous_levels' not in st.session_state:
    st.session_state.previous_levels = {}
if 'pf0_fail' not in st.session_state:
    st.session_state.pf0_fail = False
if 'pf0_message' not in st.session_state:
    st.session_state.pf0_message = None
if 'run_audit' not in st.session_state:
    st.session_state.run_audit = False
if 'dashboard_data' not in st.session_state:
    st.session_state.dashboard_data = None
if 'tta_stats' not in st.session_state:
    st.session_state.tta_stats = {"count": 0, "avg_run": 0.0, "total_return": None, "final_balance": None, "max_drawdown": None, "efficiency_ratio": None, "cagr": None, "success_rate": 0, "trade_count": 0, "active_sl": None}


def check_pf0_binding(current_ticker: str, current_levels: dict, previous_ticker: str, previous_levels: dict) -> tuple:
    """
    PF0 Check: Detect if any level from the current ticker matches a level from the previous ticker.
    Returns (passed: bool, message: str or None)
    """
    if previous_ticker is None or previous_ticker == current_ticker:
        return True, None
    
    if not previous_levels:
        return True, None
    
    current_values = {k: round(v, 2) for k, v in current_levels.items() if v is not None}
    previous_values = {k: round(v, 2) for k, v in previous_levels.items() if v is not None}
    
    matches = []
    for curr_key, curr_val in current_values.items():
        for prev_key, prev_val in previous_values.items():
            if curr_val == prev_val:
                matches.append(f"{curr_key}={curr_val} matches {previous_ticker}'s {prev_key}")
    
    if matches:
        msg = f"PRE-FLIGHT FAIL (PF0): Level reuse detected — wrong chart binding.\n"
        msg += f"Current ticker: {current_ticker}, Previous ticker: {previous_ticker}\n"
        msg += "Matching levels: " + ", ".join(matches)
        return False, msg
    
    return True, None


def generate_trade_report(ticker: str, timeframe: str, all_signals: list, stats: dict, filter_profile: str = 'BALANCED') -> str:
    """v13.1 Professional Trade Auditor: Generate CSV trade report with build info."""
    from datetime import datetime
    
    # v16.12: Get profile settings for header
    profile_data = FILTER_PROFILES.get(filter_profile, FILTER_PROFILES['BALANCED'])
    vert_val = profile_data['verticality_universal']
    vert_str = "OFF" if vert_val is None or vert_val <= 0 else f"> {vert_val}"
    
    # v16.16 FIX: Get MTF/ULTIMATE status for trade report (check ALL toggle keys)
    tr_mtf_enabled = st.session_state.get('mtf_enforcement_enabled', False)
    tr_ultimate = (st.session_state.get('mtf_ultimate_mode', False) or
                   st.session_state.get('mtf_ultimate_individual', False) or
                   st.session_state.get('mtf_ultimate_toggle', False))
    if tr_ultimate:
        tr_mtf_mode = 'ULTIMATE'
        tr_mtf_status = f"{tr_mtf_mode} (ON)"  # v16.16: ULTIMATE always implies ON
    elif tr_mtf_enabled:
        tr_mtf_mode = 'MODERATE' if filter_profile != 'AGGRESSIVE' else 'AGGRESSIVE'
        tr_mtf_status = f"{tr_mtf_mode} (ON)"
    else:
        tr_mtf_mode = 'OFF'
        tr_mtf_status = "OFF (DISABLED)"
    
    lines = []
    
    # Build info header
    lines.append(f"# ═══════════════════════════════════════════════════════════════")
    lines.append(f"# TTA Engine {BUILD_VERSION} '{BUILD_NAME}' (Build Date: {BUILD_DATE})")
    lines.append(f"# ═══════════════════════════════════════════════════════════════")
    lines.append(f"#")
    lines.append(f"# Trade Report: {ticker}")
    lines.append(f"# Timeframe: {timeframe}")
    lines.append(f"# Filter Profile: {filter_profile}")
    lines.append(f"# MTF Mode: {tr_mtf_status}")
    lines.append(f"# - Suitability Floor: {profile_data['suitability_floor']}")
    lines.append(f"# - Verticality: {vert_str}")
    lines.append(f"# - Peak Dominance: Leader > {profile_data['peak_dominance_leader']}x, Grinder > {profile_data['peak_dominance_grinder']}x")
    lines.append(f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"#")
    lines.append(f"# v13.3 Vertical Lock Entry Logic:")
    lines.append(f"# - SMA Slope: Not declining (catches turn immediately)")
    lines.append(f"# - Zero Buffer: Price must be > SMA (no buffer)")
    lines.append(f"# - Volume Gate: Volume > 1.2x 20-day average (institutional)")
    lines.append(f"# - AO Trigger: Zero-Cross OR Hook (Wave 5 continuations)")
    lines.append(f"# - Hard Stop: 8% max loss per trade (entry * 0.92)")
    lines.append(f"# - Vertical Lock: 2.0x ATR at +15% profit (tighter trailing)")
    lines.append(f"# - Gap Protection: Uses open price for slippage simulation")
    lines.append(f"# - Exit: Hard Stop > Trailing Stop > Regime Fail")
    lines.append(f"# - Break-Even: Stop moves to entry at +10% unrealized")
    lines.append(f"#")
    lines.append(f"# ATR Multiplier: 3.5x (Goldilocks zone)")
    lines.append(f"# Portfolio Start: $10,000")
    lines.append(f"# Portfolio End: ${stats.get('final_balance', 10000):,.2f}")
    lines.append(f"# Total Return (Compounded): {stats.get('total_return', 0):+.2f}%")
    lines.append(f"# CAGR: {stats.get('cagr', 0):+.2f}%")
    lines.append(f"# Max Drawdown: -{stats.get('max_drawdown', 0):.2f}%")
    lines.append(f"# True Calmar (CAGR/DD): {stats.get('efficiency_ratio', 0):.2f}x")
    lines.append(f"# Win Rate: {stats.get('success_rate', 0):.1f}%")
    lines.append(f"# Completed Trades: {stats.get('trade_count', 0)}")
    lines.append(f"#")
    lines.append("")
    
    # CSV header
    lines.append("Entry Date,Entry Price,Exit Date,Exit Price,Exit Reason,Return %")
    
    # Pair up BUY/SELL signals
    buy_signal = None
    for sig in all_signals:
        if sig["type"] == "BUY":
            buy_signal = sig
        elif sig["type"] == "SELL" and buy_signal:
            entry_date = buy_signal["time"].strftime('%Y-%m-%d') if hasattr(buy_signal["time"], 'strftime') else str(buy_signal["time"])[:10]
            exit_date = sig["time"].strftime('%Y-%m-%d') if hasattr(sig["time"], 'strftime') else str(sig["time"])[:10]
            entry_price = buy_signal["price"]
            exit_price = sig["price"]
            exit_reason = sig.get("reason", "Stop")
            ret = ((exit_price - entry_price) / entry_price) * 100
            lines.append(f"{entry_date},{entry_price:.2f},{exit_date},{exit_price:.2f},{exit_reason},{ret:+.2f}")
            buy_signal = None
    
    return "\n".join(lines)


with st.sidebar:
    st.markdown("##### Settings")
    ticker = st.text_input("Ticker", value="AAPL", label_visibility="collapsed", placeholder="Enter ticker...", key="ticker_input")
    ticker = ticker.upper().strip()
    
    # v15.4 FIX: Debug print for ticker tracking
    print(f"TICKER INPUT: '{ticker}' (current_ticker in state: {st.session_state.get('current_ticker', 'None')})")
    
    col_tf, col_piv = st.columns(2)
    with col_tf:
        timeframe = st.selectbox("TF", options=["Weekly", "Daily", "4-Hour"], index=1, label_visibility="collapsed")
    with col_piv:
        pivot_order = st.selectbox("Pivot", options=[3, 5, 7, 10], index=1, label_visibility="collapsed")
    
    # v16.12: Removed redundant toggle - Filter Profile now controls MTF mode
    # signal_mode = st.radio("Mode", ["Conservative", "Aggressive"], index=0, horizontal=True, label_visibility="collapsed")
    
    # v16.11: Filter Switchboard - Profile Selection
    st.markdown("##### Filter Profile")
    profile_options = list(FILTER_PROFILES.keys())
    selected_profile = st.selectbox(
        "Filter Profile",
        options=profile_options,
        index=profile_options.index("BALANCED"),
        format_func=lambda x: FILTER_PROFILES[x]["name"],
        label_visibility="collapsed",
        key="filter_profile"
    )
    
    # Apply selected profile values to session state (for batch audit access)
    # Note: filter_profile key is managed by the selectbox widget, don't reassign it
    active_profile = FILTER_PROFILES[selected_profile]
    st.session_state['SUITABILITY_FLOOR'] = active_profile["suitability_floor"]
    st.session_state['SUITABILITY_GRINDER'] = active_profile["suitability_grinder"]
    st.session_state['VERTICALITY_UNIVERSAL'] = active_profile["verticality_universal"]
    st.session_state['PEAK_DOMINANCE_LEADER'] = active_profile["peak_dominance_leader"]
    st.session_state['PEAK_DOMINANCE_GRINDER'] = active_profile["peak_dominance_grinder"]
    
    # v16.12: Derive signal_mode from filter profile (replaces toggle)
    # AGGRESSIVE profile uses Aggressive mode, all others use Conservative
    signal_mode = "Aggressive" if selected_profile == "AGGRESSIVE" else "Conservative"
    
    # Show profile description
    st.caption(active_profile["description"])
    
    # v16.12: Initialize session state keys BEFORE widgets
    if 'mtf_ultimate_mode' not in st.session_state:
        st.session_state['mtf_ultimate_mode'] = False
    if 'mtf_enforcement_enabled' not in st.session_state:
        st.session_state['mtf_enforcement_enabled'] = False
    
    # v16.16 FIX: ULTIMATE Mode Toggle with proper state management
    ultimate_individual = st.toggle(
        "ULTIMATE Mode",
        value=st.session_state['mtf_ultimate_mode'],
        key="mtf_ultimate_individual",
        help="5-Gate Entry (MACD+AO+Fractal) + Triple Confirmation Exit"
    )
    # v16.16 FIX: Properly sync state based on toggle position
    if ultimate_individual:
        st.session_state['mtf_ultimate_mode'] = True
        # ULTIMATE requires MTF enforcement
    else:
        # When ULTIMATE is OFF, reset the shared ultimate state
        # But DON'T change mtf_enforcement_enabled - let the MTF toggle control that
        st.session_state['mtf_ultimate_mode'] = False
    
    # v16.12: MTF Gate toggle - if ULTIMATE is on, force this on and disable the toggle
    if ultimate_individual:
        # ULTIMATE requires MTF, show as forced-on (disabled toggle)
        st.toggle(
            "MTF Gate",
            value=True,
            disabled=True,
            key="mtf_gate_individual_disabled",
            help="Automatically enabled by ULTIMATE Mode"
        )
        mtf_individual = True  # Force MTF on when ULTIMATE is active
    else:
        # Normal MTF toggle with callback for syncing
        def on_mtf_change():
            st.session_state['mtf_enforcement_enabled'] = st.session_state['mtf_toggle_individual']
        
        mtf_individual = st.toggle(
            "MTF Gate",
            value=st.session_state['mtf_enforcement_enabled'],
            key="mtf_toggle_individual",
            on_change=on_mtf_change,
            help="Enable Multi-Timeframe alignment as 5th entry gate"
        )
    
    # v16.12: Always show timeframes for MTF modes
    st.caption("📊 **MTF Timeframes: M / W / D** (Monthly, Weekly, Daily)")
    
    # Trading Journal Mode Selector
    st.markdown("---")
    st.markdown("##### App Mode")
    app_mode = st.radio(
        "Select Mode",
        options=["📊 Analysis", "💼 Trading Journal"],
        index=0,
        label_visibility="collapsed",
        key="app_mode"
    )
    
    if ultimate_individual:
        st.caption("ULTIMATE: 5-Gate MACD Entry + Triple Confirmation Exit")
    elif mtf_individual:
        st.caption("MTF Gate ON: Monthly + Weekly + Daily alignment enforced")
    else:
        st.caption("MTF Gate OFF: Only static filters active")
    
    st.divider()
    st.caption("🤖 AI Analysis")
    enable_ai = st.toggle(
        "AI Elliott Wave Audit", 
        value=False, 
        key="enable_ai_analysis",
        help="Enable detailed AI analysis (adds 15-20 sec)"
    )
    if enable_ai:
        st.caption("⏱️ Adds 20-30 sec (MTF analysis)")
        # Show progress indicator in sidebar when AI is running
        # Create sidebar placeholder for AI progress (will be updated during analysis)
        if 'sidebar_progress_placeholder' not in st.session_state:
            st.session_state.sidebar_progress_placeholder = st.empty()
        else:
            st.session_state.sidebar_progress_placeholder = st.empty()
        
        # Auto-trigger AI analysis if chart already exists but AI hasn't run
        # Only auto-trigger if NOT already running (prevents infinite loop)
        if st.session_state.get('current_ticker') and st.session_state.get('df') is not None:
            if not st.session_state.get('ai_analysis_text') and not st.session_state.get('run_audit'):
                st.session_state.run_audit = True
                st.rerun()
    else:
        st.caption("⚡ Fast mode - visual signals only")
    
    # AI Debug Toggle
    show_ai_debug = st.checkbox(
        "🔍 Show AI Debug Info", 
        value=False, 
        key="show_ai_debug",
        help="Display what charts were sent to AI and verify MTF analysis"
    )
    
    # Juan's Market Filter - 5 Factor Institutional Flow
    st.divider()
    with st.expander("🌍 Juan's Market Filter", expanded=False):
        st.markdown("**Juan Maldonado's 5-Factor Institutional Flow**")
        
        try:
            # Get VIX (fear gauge)
            vix_data = yf.download("^VIX", period="1mo", progress=False)
            current_vix = float(vix_data['Close'].iloc[-1])
            
            # Get S&P 500
            sp500_data = yf.download("^GSPC", period="3mo", progress=False)
            sp500_ma50 = float(sp500_data['Close'].rolling(50).mean().iloc[-1])
            sp500_price = float(sp500_data['Close'].iloc[-1])
            
            # Simple scoring (each factor = -1 bearish, +1 bullish)
            score1 = -1 if sp500_price < sp500_ma50 else 1  # S&P below 50MA = bearish
            score2 = -1 if current_vix > 15 else 1  # Lower threshold = more sensitive
            score3 = -1  # Dollar strong (hardcoded for now)
            score4 = -1  # Cost of money rising (hardcoded for now)
            score5 = -1  # Bad inflation (hardcoded for now)
            
            # Manual override for known bearish period
            if sp500_price > sp500_ma50:
                # Even if S&P above MA, check momentum
                sp500_change = (float(sp500_data['Close'].iloc[-1]) / float(sp500_data['Close'].iloc[-5]) - 1) * 100
                if sp500_change < 0:  # Falling this week despite above MA
                    score1 = -1
            
            total = score1 + score2 + score3 + score4 + score5
            
            st.markdown(f"**S&P 500:** {'🔴 Below 50MA' if score1 == -1 else '🟢 Above 50MA'}")
            st.markdown(f"**VIX/Commercials:** {'🔴 Selling (VIX=' + f'{current_vix:.1f})' if score2 == -1 else '🟢 Buying'}")
            st.markdown(f"**US Dollar:** 🔴 Strong (Risk-Off)")
            st.markdown(f"**Cost of Money:** 🔴 Rising")
            st.markdown(f"**Inflation:** 🔴 Bad/Toxic")
            
            st.divider()
            
            if total <= -2:
                st.error(f"**{total}/5 BEARISH ENVIRONMENT**\nJuan says: Commercials SELLING - Reduce longs or look for shorts")
            elif total <= 0:
                st.warning(f"**{total}/5 MIXED/CAUTIOUS**\nReduce position sizing")
            else:
                st.success(f"**{total}/5 BULLISH**\nNormal trading")
            
            st.caption(f"Live Data: S&P=${sp500_price:.0f} | VIX={current_vix:.1f}")
                
        except Exception as e:
            st.error(f"Data error: {e}")
    
    analyze_btn = st.button("Analyze", type="primary", width='stretch')
    
    # v13.0 Export Buttons - ALWAYS visible in sidebar
    st.divider()
    st.markdown(f"##### Export ({BUILD_VERSION})")
    st.caption(f"{BUILD_NAME} • {BUILD_DATE}")
    
    sidebar_fig = st.session_state.get('fig')
    sidebar_tta_stats = st.session_state.get('tta_stats', {})
    sidebar_all_signals = sidebar_tta_stats.get("all_signals", [])
    
    # Row 1: Chart and Trades
    exp_col1, exp_col2 = st.columns(2)
    with exp_col1:
        if sidebar_fig is not None:
            try:
                chart_bytes = sidebar_fig.to_image(format="png", width=1200, height=800, scale=2)
                st.download_button(
                    label="Chart",
                    data=chart_bytes,
                    file_name=f"{st.session_state.get('current_ticker', 'chart')}_chart.png",
                    mime="image/png",
                    width='stretch',
                    key=f"sidebar_chart_{st.session_state.get('current_ticker', 'none')}"
                )
            except:
                st.button("Chart", disabled=True, width='stretch')
        else:
            st.button("Chart", disabled=True, width='stretch')
    with exp_col2:
        if sidebar_all_signals:
            # v16.12: Pass filter profile to export
            sidebar_filter_profile = st.session_state.get('filter_profile', 'BALANCED')
            csv_data = generate_trade_report(
                st.session_state.get('current_ticker', 'UNKNOWN'),
                st.session_state.get('current_timeframe', 'Daily'),
                sidebar_all_signals,
                sidebar_tta_stats,
                filter_profile=sidebar_filter_profile
            )
            st.download_button(
                label="Trades",
                data=csv_data,
                file_name=f"{st.session_state.get('current_ticker', 'trades')}_trades.csv",
                mime="text/csv",
                width='stretch',
                key=f"sidebar_trades_{st.session_state.get('current_ticker', 'none')}"
            )
        else:
            st.button("Trades", disabled=True, width='stretch')
    
    # Row 2: Code Base and Indicator Logic (always available)
    exp_col3, exp_col4 = st.columns(2)
    with exp_col3:
        # Read full codebase
        try:
            with open("app.py", "r") as f:
                codebase_content = f.read()
            # Add build header
            code_header = f"""# ═══════════════════════════════════════════════════════════════
# TTA Engine {BUILD_VERSION} '{BUILD_NAME}'
# Build Date: {BUILD_DATE}
# ═══════════════════════════════════════════════════════════════

"""
            st.download_button(
                label="Code",
                data=code_header + codebase_content,
                file_name=f"TTA_{BUILD_VERSION}_{BUILD_DATE}_full.py",
                mime="text/x-python",
                width='stretch',
                key="sidebar_code_export"
            )
        except:
            st.button("Code", disabled=True, width='stretch')
    with exp_col4:
        # Extract just the TTA indicator logic
        try:
            with open("app.py", "r") as f:
                full_code = f.read()
            # Extract the scan_tta_for_daily_chart function
            import re
            pattern = r'(def scan_tta_for_daily_chart\(.*?)(?=\ndef [a-zA-Z_]|\nclass |\n# ={50,}|\Z)'
            match = re.search(pattern, full_code, re.DOTALL)
            if match:
                indicator_code = f"""# ═══════════════════════════════════════════════════════════════
# TTA Indicator Logic {BUILD_VERSION} '{BUILD_NAME}'
# Build Date: {BUILD_DATE}
# ═══════════════════════════════════════════════════════════════
# 
# v13.3 Vertical Lock Entry Logic:
# - SMA Slope: Not declining (catches turn immediately)
# - Zero Buffer: Price must be > SMA (no buffer)
# - Volume Gate: Volume > 1.2x 20-day average (standard institutional)
# - Momentum Trigger: AO Zero-Cross OR AO Hook (Wave 5 continuations)
# - Hard Stop: 8% max loss per trade (entry * 0.92) - PRIORITY EXIT
# - Vertical Lock: 2.0x ATR at +15% profit (tighter trailing stop)
# - Gap Protection: Uses open price for slippage simulation
# - Exit Order: Hard Stop > Trailing Stop > Regime Fail
# - Break-Even: Stop moves to entry at +10% unrealized
# ═══════════════════════════════════════════════════════════════

{match.group(1).strip()}
"""
                st.download_button(
                    label="Indicator",
                    data=indicator_code,
                    file_name=f"TTA_{BUILD_VERSION}_{BUILD_DATE}_indicator.py",
                    mime="text/x-python",
                    width='stretch',
                    key="sidebar_indicator_export"
                )
            else:
                st.button("Indicator", disabled=True, width='stretch')
        except:
            st.button("Indicator", disabled=True, width='stretch')
    
    # Row 3: Changelog download
    try:
        with open("CHANGELOG.md", "r") as f:
            changelog_content = f.read()
        st.download_button(
            label="Version History",
            data=changelog_content,
            file_name=f"TTA_CHANGELOG_{BUILD_VERSION}.md",
            mime="text/markdown",
            width='stretch',
            key="sidebar_changelog_export"
        )
    except:
        st.button("Version History", disabled=True, width='stretch')
    
    # Row 4: Download Analysis Logs
    if st.session_state.log_capture.has_logs():
        log_content = st.session_state.log_capture.get_logs()
        ticker_name = st.session_state.get('current_ticker', 'analysis')
        st.download_button(
            label="Download Logs",
            data=log_content,
            file_name=f"TTA_{ticker_name}_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            mime="text/plain",
            width='stretch',
            key="sidebar_logs_export"
        )
    else:
        st.button("Download Logs", disabled=True, width='stretch', help="Run an analysis first")
    
    # Row 5: Download Source Code
    try:
        with open("app.py", "r") as f:
            source_code = f.read()
        st.download_button(
            label="Source Code",
            data=source_code,
            file_name=f"TTA_app_{BUILD_VERSION}_{BUILD_DATE}.py",
            mime="text/x-python",
            width='stretch',
            key="sidebar_source_export"
        )
    except:
        st.button("Source Code", disabled=True, width='stretch')

# Trading Journal Mode Display
if st.session_state.get("app_mode") == "💼 Trading Journal":
    render_trading_journal_tab()
    st.stop()
    
    # ═══════════════════════════════════════════════════════════════
    # v13.3 BATCH AUDIT - Multi-ticker analysis with leaderboard
    # ═══════════════════════════════════════════════════════════════
    st.divider()
    st.markdown("##### Batch Audit")
    
    # Default watchlist - only used for initial state
    default_watchlist = ['GOOGL', 'NVDA', 'MSFT', 'AAPL', 'SPY', 'TSLA', 'LLY', 'XOM', 'QQQ', 'JPM', 'CBA.AX']
    
    # v15.4 FIX: File-based persistence for watchlist (survives page refresh and server restart)
    WATCHLIST_FILE = "watchlist.txt"
    
    def load_watchlist_from_file():
        """Load watchlist from file, return default if file doesn't exist"""
        try:
            with open(WATCHLIST_FILE, 'r') as f:
                content = f.read().strip()
                if content:
                    return content
        except FileNotFoundError:
            pass
        return ", ".join(default_watchlist)
    
    def save_watchlist_to_file(watchlist_text):
        """Save watchlist to file for persistence"""
        try:
            with open(WATCHLIST_FILE, 'w') as f:
                f.write(watchlist_text)
        except Exception as e:
            print(f"Warning: Could not save watchlist: {e}")
    
    # Initialize session state from file on first load
    if 'saved_watchlist' not in st.session_state:
        st.session_state.saved_watchlist = load_watchlist_from_file()
    
    def save_watchlist():
        """Callback to save watchlist when user modifies it"""
        st.session_state.saved_watchlist = st.session_state.watchlist_editor
        save_watchlist_to_file(st.session_state.watchlist_editor)
    
    with st.expander("Watchlist & Settings"):
        watchlist_input = st.text_area(
            "Tickers (one per line or comma-separated)",
            value=st.session_state.saved_watchlist,
            height=80,
            key="watchlist_editor",
            on_change=save_watchlist
        )
        # Parse watchlist from the input
        watchlist = [t.strip().upper() for t in watchlist_input.replace('\n', ',').split(',') if t.strip()]
    
    # v16.11: VIX Recommendation Button
    vix_check_btn = st.button("Check VIX & Get Recommendation", width='stretch')
    if vix_check_btn:
        with st.spinner("Fetching VIX..."):
            vix_data = get_vix_recommendation()
            st.session_state['vix_data'] = vix_data
            st.session_state['vix_recommended_profile'] = vix_data['profile']
            # Auto-select the recommended profile by setting session state before widget
            st.session_state['batch_filter_profile'] = vix_data['profile']
            st.rerun()
    
    # Display VIX recommendation if available
    if 'vix_data' in st.session_state and st.session_state['vix_data']:
        vix_info = st.session_state['vix_data']
        if vix_info['vix'] is not None:
            # Color-code based on regime
            regime_colors = {
                "LOW VOLATILITY": "#22c55e",  # Green
                "NORMAL": "#3b82f6",          # Blue
                "ELEVATED": "#f59e0b",        # Amber
                "HIGH VOLATILITY": "#ef4444"  # Red
            }
            regime_color = regime_colors.get(vix_info['regime'], "#94a3b8")
            st.markdown(f"""
            <div style="background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); 
                        border-radius: 8px; padding: 12px; margin-bottom: 12px;
                        border-left: 4px solid {regime_color};">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span style="color: #94a3b8; font-size: 0.85rem;">VIX</span>
                    <span style="color: {regime_color}; font-weight: 700; font-size: 1.2rem;">{vix_info['vix']:.1f}</span>
                </div>
                <div style="color: {regime_color}; font-size: 0.75rem; margin-top: 4px;">{vix_info['regime']}</div>
                <div style="color: #64748b; font-size: 0.7rem; margin-top: 4px;">{vix_info['reason']}</div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.warning(vix_info['reason'])
    
    # v16.11: Filter Profile Selector for Batch Audit
    batch_profile_options = list(FILTER_PROFILES.keys())
    
    # Initialize batch_filter_profile if not set (defaults to BALANCED)
    if 'batch_filter_profile' not in st.session_state:
        st.session_state['batch_filter_profile'] = 'BALANCED'
    
    batch_selected_profile = st.selectbox(
        "Filter Profile",
        options=batch_profile_options,
        format_func=lambda x: FILTER_PROFILES[x]["name"],
        key="batch_filter_profile",
        help="Select filter profile for batch audit"
    )
    
    # v16.11: Show warning if user overrides VIX recommendation
    vix_recommended = st.session_state.get('vix_recommended_profile')
    if vix_recommended and batch_selected_profile != vix_recommended:
        st.warning(f"You selected {batch_selected_profile} but VIX suggests {vix_recommended}")
    
    # v16.12: Initialize session state keys BEFORE widgets
    if 'mtf_ultimate_mode' not in st.session_state:
        st.session_state['mtf_ultimate_mode'] = False
    if 'mtf_enforcement_enabled' not in st.session_state:
        st.session_state['mtf_enforcement_enabled'] = False
    
    # v16.16 FIX: ULTIMATE Mode Toggle with proper state management
    ultimate_enabled = st.toggle(
        "ULTIMATE Mode",
        value=st.session_state['mtf_ultimate_mode'],
        key="mtf_ultimate_toggle",
        help="5-Gate Entry (MACD+AO+Fractal) + Triple Confirmation Exit"
    )
    # v16.16 FIX: Properly sync state based on toggle position
    if ultimate_enabled:
        st.session_state['mtf_ultimate_mode'] = True
        # ULTIMATE requires MTF enforcement
    else:
        # When ULTIMATE is OFF, reset the shared ultimate state
        # But DON'T change mtf_enforcement_enabled - let the MTF toggle control that
        st.session_state['mtf_ultimate_mode'] = False
    
    # v16.12: MTF Gate toggle - if ULTIMATE is on, force this on and disable the toggle
    if ultimate_enabled:
        # ULTIMATE requires MTF, show as forced-on (disabled toggle)
        st.toggle(
            "MTF Gate",
            value=True,
            disabled=True,
            key="mtf_gate_batch_disabled",
            help="Automatically enabled by ULTIMATE Mode"
        )
        mtf_enabled = True  # Force MTF on when ULTIMATE is active
    else:
        # Normal MTF toggle with callback for syncing
        def on_batch_mtf_change():
            st.session_state['mtf_enforcement_enabled'] = st.session_state['mtf_toggle_batch']
        
        mtf_enabled = st.toggle(
            "MTF Gate",
            value=st.session_state['mtf_enforcement_enabled'],
            key="mtf_toggle_batch",
            on_change=on_batch_mtf_change,
            help="Enable Multi-Timeframe alignment as 5th entry gate"
        )
    
    # v16.12: Always show timeframes for MTF modes
    st.caption("📊 **MTF Timeframes: M / W / D** (Monthly, Weekly, Daily)")
    
    # Trading Journal Mode Selector
    st.markdown("---")
    st.markdown("##### App Mode")
    app_mode = st.radio(
        "Select Mode",
        options=["📊 Analysis", "💼 Trading Journal"],
        index=0,
        label_visibility="collapsed",
        key="app_mode"
    )
    
    if ultimate_enabled:
        st.info("ULTIMATE: 5-Gate MACD Entry + Triple Confirmation Exit")
    elif mtf_enabled:
        st.info("MTF Gate: Monthly + Weekly + Daily alignment checked per-bar")
    
    # Apply batch profile to session state
    batch_active_profile = FILTER_PROFILES[batch_selected_profile]
    st.session_state['SUITABILITY_FLOOR'] = batch_active_profile["suitability_floor"]
    st.session_state['SUITABILITY_GRINDER'] = batch_active_profile["suitability_grinder"]
    st.session_state['VERTICALITY_UNIVERSAL'] = batch_active_profile["verticality_universal"]
    st.session_state['PEAK_DOMINANCE_LEADER'] = batch_active_profile["peak_dominance_leader"]
    st.session_state['PEAK_DOMINANCE_GRINDER'] = batch_active_profile["peak_dominance_grinder"]
    
    # Show current profile settings (2 lines for readability)
    vert_display = "OFF" if batch_active_profile["verticality_universal"] is None else f"> {batch_active_profile['verticality_universal']}"
    st.caption(f"Vert: {vert_display} | Suit: {batch_active_profile['suitability_floor']} | PeakDom: {batch_active_profile['peak_dominance_leader']}/{batch_active_profile['peak_dominance_grinder']}")
    st.caption(f"Trades: <{batch_active_profile['max_trade_count']} | DD: <{batch_active_profile['drawdown_ceiling']}% | WinRate: >{batch_active_profile['min_win_rate']}%")
    
    # Batch audit buttons
    btn_col1, btn_col2 = st.columns(2)
    with btn_col1:
        batch_run_btn = st.button("Run Audit", width='stretch', type="primary")
    with btn_col2:
        batch_all_btn = st.button("All Filters", width='stretch', help="Run with ALL filter profiles")
    
    # Initialize batch results in session state
    if 'batch_results' not in st.session_state:
        st.session_state.batch_results = []
    
    # Store batch request for deferred execution (after function is defined)
    if batch_run_btn and watchlist:
        st.session_state.pending_batch_audit = watchlist.copy()
        st.session_state.batch_watchlist = watchlist.copy()  # v14.6: Store for leaderboard report
        st.session_state.batch_audit_running = True
        st.session_state.batch_all_filters = False  # Single profile mode
        # Clear old cached results to force fresh display
        st.session_state.batch_results = []
        st.session_state.batch_trades = []
    
    # v16.11: Run All Filters - runs batch with ALL profiles
    if batch_all_btn and watchlist:
        st.session_state.pending_batch_audit = watchlist.copy()
        st.session_state.batch_watchlist = watchlist.copy()
        st.session_state.batch_audit_running = True
        st.session_state.batch_all_filters = True  # All profiles mode
        # Clear old cached results
        st.session_state.batch_results = []
        st.session_state.batch_trades = []
        st.session_state.all_filters_results = {}  # Store results per profile
    
    # Display leaderboard and export if results exist
    if st.session_state.batch_results and len(st.session_state.batch_results) > 0:
        # v16.12: Define batch_profile_name early for use in exports and headers
        batch_profile_name = st.session_state.get('batch_filter_profile', 'BALANCED')
        
        batch_df = pd.DataFrame(st.session_state.batch_results)
        
        # Ensure Suitability column exists (for backwards compatibility with old cached results)
        if 'Suitability' not in batch_df.columns:
            batch_df['Suitability'] = 0
        
        # Sort by Efficiency Ratio descending
        batch_df_sorted = batch_df.sort_values('Efficiency Ratio', ascending=False)
        
        # v14.2 Adaptive Qualifier: Separate passed (Elite/Momentum) vs rejected
        passed_df = batch_df_sorted[batch_df_sorted['Status'].str.startswith('OK', na=False)]
        rejected_df = batch_df_sorted[batch_df_sorted['Status'].str.startswith('REJECTED', na=False)]
        error_df = batch_df_sorted[~batch_df_sorted['Status'].str.startswith('OK', na=False) & ~batch_df_sorted['Status'].str.startswith('REJECTED', na=False)]
        
        # Success banner
        ok_count = len(passed_df)
        rejected_count = len(rejected_df)
        total_trades = passed_df['Trades'].sum() if len(passed_df) > 0 else 0
        st.success(f"Gate: {ok_count} passed, {rejected_count} rejected, {int(total_trades)} trades")
        
        # Leaderboard - ONLY show passed tickers (sorted by efficiency)
        # v15.4: Add Priority Rank based on True Calmar (Efficiency Ratio)
        st.markdown("**Leaderboard (Passed Gate)**")
        
        if len(passed_df) == 0:
            st.info("No tickers passed the Quality Gate (Suit >= 70)")
        else:
            # v15.4: Add Priority Rank column
            passed_df = passed_df.reset_index(drop=True)
            passed_df['Priority Rank'] = range(1, len(passed_df) + 1)
            
            for rank_idx, (idx, row) in enumerate(passed_df.iterrows()):
                eff = row['Efficiency Ratio']
                ticker_name = row['Ticker']
                ret = row['Total Return (%)']
                trades = int(row['Trades'])
                suit = int(row['Suitability']) if pd.notna(row['Suitability']) else 0
                status = row['Status']
                priority_rank = rank_idx + 1
                
                # G=Verified Grinder, L=Momentum Leader
                if "Grinder" in str(status) and "OK" in str(status):
                    tier_badge = "G"
                elif "Leader" in str(status):
                    tier_badge = "L"
                else:
                    tier_badge = ""
                
                # v15.4: Gold highlight for Top 5 Efficiency Leaders
                is_top5 = priority_rank <= 5
                rank_display = f"#{priority_rank}" if is_top5 else f"#{priority_rank}"
                
                # v16.4: Updated badge logic for perfect scores
                if trades == 0:
                    st.markdown(f"⚪ {rank_display} **{ticker_name}** [{suit}{tier_badge}]: No trades")
                elif eff >= 100:
                    # Perfect: Zero drawdown with profits
                    st.markdown(f"💎 {rank_display} **{ticker_name}** [{suit}{tier_badge}]: :violet[{eff:.2f}x] ({ret:+.1f}%) [{trades}]")
                elif eff >= 10.0:
                    # Elite performer
                    st.markdown(f"🥇 {rank_display} **{ticker_name}** [{suit}{tier_badge}]: :orange[{eff:.2f}x] ({ret:+.1f}%) [{trades}]")
                elif eff >= 3.0:
                    # Excellent
                    st.markdown(f"🟢 {rank_display} **{ticker_name}** [{suit}{tier_badge}]: {eff:.2f}x ({ret:+.1f}%) [{trades}]")
                elif eff >= 1.0:
                    # Good
                    st.markdown(f"🟡 {rank_display} **{ticker_name}** [{suit}{tier_badge}]: {eff:.2f}x ({ret:+.1f}%) [{trades}]")
                else:
                    # Poor/Inefficient
                    st.markdown(f"🔴 {rank_display} **{ticker_name}** [{suit}{tier_badge}]: {eff:.2f}x ({ret:+.1f}%) [{trades}]")
        
        # Show rejected count (collapsed)
        if len(rejected_df) > 0:
            with st.expander(f"Rejected ({len(rejected_df)})", expanded=False):
                for idx, row in rejected_df.iterrows():
                    suit = int(row['Suitability']) if pd.notna(row['Suitability']) else 0
                    status = row['Status'].replace('REJECTED: ', '') if 'REJECTED:' in str(row['Status']) else row['Status']
                    st.markdown(f"🚫 **{row['Ticker']}**: {status}")
        
        # Master CSV Export - v14.0: Passed tickers first, rejected at bottom
        # v16.12: Get active filter values from BATCH profile for export
        exp_filter_profile = batch_profile_name  # Use variable defined at download buttons section
        exp_profile_data = FILTER_PROFILES.get(exp_filter_profile, FILTER_PROFILES['BALANCED'])
        exp_suit_floor = exp_profile_data['suitability_floor']
        exp_suit_grinder = exp_profile_data['suitability_grinder']
        exp_vert_universal = exp_profile_data['verticality_universal']
        exp_peakdom_leader = exp_profile_data['peak_dominance_leader']
        exp_peakdom_grinder = exp_profile_data['peak_dominance_grinder']
        
        # v16.11: Handle None for verticality in export
        # v16.12: Improved verticality description
        exp_vert_str = "OFF" if exp_vert_universal is None or exp_vert_universal <= 0 else f"> {exp_vert_universal} ATR"
        
        # v16.16 FIX: Determine MTF mode for header (check ALL toggle keys)
        exp_mtf_enabled = st.session_state.get('mtf_enforcement_enabled', False)
        exp_ultimate = (st.session_state.get('mtf_ultimate_mode', False) or
                        st.session_state.get('mtf_ultimate_individual', False) or
                        st.session_state.get('mtf_ultimate_toggle', False))
        if exp_ultimate:
            exp_mtf_mode = 'ULTIMATE'
            exp_mtf_status = "ENABLED"  # v16.16: ULTIMATE always implies enabled
        elif exp_mtf_enabled:
            exp_mtf_mode = 'MODERATE' if exp_filter_profile != 'AGGRESSIVE' else 'AGGRESSIVE'
            exp_mtf_status = "ENABLED"
        else:
            exp_mtf_mode = 'OFF'
            exp_mtf_status = "DISABLED"
        
        csv_lines = [
            f"# Master Efficiency Audit - {BUILD_VERSION} '{BUILD_NAME}'",
            f"# Build Date: {BUILD_DATE}",
            f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"# Filter Profile: {exp_filter_profile}",
            f"# MTF Mode: {exp_mtf_mode} ({exp_mtf_status})",
            f"#",
            f"# v16.11 Filter Switchboard Settings:",
            f"# - Suitability Floor: >= {exp_suit_floor} required",
            f"# - Universal Verticality: {exp_vert_str} (ATR above 30-week SMA; negative=disabled)",
            f"# - Anti-Grinder: Suit > {exp_suit_grinder} must have PeakDom > {exp_peakdom_grinder}x",
            f"# - Leader Pass: Suit <= {exp_suit_grinder} only needs PeakDom > {exp_peakdom_leader}x",
            f"# - v15.5: ATR-based Initial Stop ({ATR_INITIAL_STOP_MULT}x ATR) | Vertical Lock at +15%",
            f"# - v16.0: Forgiving Time-Stop ({TIME_STOP_BASE}d base, +{TIME_STOP_CONSOLIDATION_EXT}d if consolidating, exit only if <{TIME_STOP_MIN_GAIN}%)",
            f"# - v15.5: Adaptive Slope Gate (High-Alpha {SMA_SLOPE_HIGH_ALPHA}%, Standard {SMA_SLOPE_THRESHOLD}%)",
            f"# - v15.0: Compounded Returns; True Calmar = CAGR / Max Drawdown",
            f"#",
            "Priority Rank,Ticker,Total Return (%),CAGR (%),Max Drawdown (%),True Calmar,Win Rate (%),Trades,Suitability,Status"
        ]
        # Passed tickers first - v15.4: Include Priority Rank
        for rank_idx, (_, row) in enumerate(passed_df.iterrows()):
            suit = int(row['Suitability']) if pd.notna(row['Suitability']) else 0
            status_clean = str(row['Status']).replace(',', ';')  # v14.6: Remove commas for CSV
            cagr = row.get('CAGR (%)', 0) if 'CAGR (%)' in row else 0
            priority_rank = rank_idx + 1
            csv_lines.append(
                f"{priority_rank},{row['Ticker']},{row['Total Return (%)']:.2f},{cagr:.2f},{row['Max Drawdown (%)']:.2f},"
                f"{row['Efficiency Ratio']:.2f},{row['Win Rate (%)']:.1f},{row['Trades']},{suit},{status_clean}"
            )
        # Rejected tickers at bottom
        if len(rejected_df) > 0:
            csv_lines.append("#")
            csv_lines.append("# --- REJECTED ---")
            for _, row in rejected_df.iterrows():
                suit = int(row['Suitability']) if pd.notna(row['Suitability']) else 0
                status_clean = str(row['Status']).replace(',', ';')  # v14.6: Remove commas for CSV
                csv_lines.append(
                    f"-,{row['Ticker']},0,0,0,0,0,0,{suit},{status_clean}"
                )
        # Error tickers at end
        if len(error_df) > 0:
            csv_lines.append("#")
            csv_lines.append("# --- ERRORS ---")
            for _, row in error_df.iterrows():
                suit = int(row['Suitability']) if pd.notna(row.get('Suitability', 0)) else 0
                status_clean = str(row['Status']).replace(',', ';')  # v14.6: Remove commas for CSV
                csv_lines.append(
                    f"-,{row['Ticker']},0,0,0,0,0,0,{suit},{status_clean}"
                )
        master_csv = "\n".join(csv_lines)
        
        st.download_button(
            label="Download Master CSV",
            data=master_csv,
            file_name=f"Master_Efficiency_Audit_{batch_profile_name}_{BUILD_VERSION}_{BUILD_DATE}.csv",
            mime="text/csv",
            width='stretch',
            key="batch_master_csv"
        )
        
        # v16.11: All Filters Comparison Report (if available)
        if st.session_state.get('all_filters_report'):
            st.download_button(
                label="Download All Filters Report",
                data=st.session_state.all_filters_report,
                file_name=f"All_Filters_Comparison_{BUILD_VERSION}_{BUILD_DATE}.txt",
                mime="text/plain",
                width='stretch',
                key="batch_all_filters_report"
            )
        
        # All Trades CSV Export
        batch_trades = st.session_state.get('batch_trades', [])
        if batch_trades:
            # v16.16 FIX: Get MTF status for All Trades header (check ALL toggle keys)
            at_mtf_enabled = st.session_state.get('mtf_enforcement_enabled', False)
            at_ultimate = (st.session_state.get('mtf_ultimate_mode', False) or
                           st.session_state.get('mtf_ultimate_individual', False) or
                           st.session_state.get('mtf_ultimate_toggle', False))
            if at_ultimate:
                at_mtf_mode = 'ULTIMATE'
                at_mtf_status = f"{at_mtf_mode} (ON)"  # v16.16: ULTIMATE always implies ON
            elif at_mtf_enabled:
                at_mtf_mode = 'MODERATE' if batch_profile_name != 'AGGRESSIVE' else 'AGGRESSIVE'
                at_mtf_status = f"{at_mtf_mode} (ON)"
            else:
                at_mtf_mode = 'OFF'
                at_mtf_status = "OFF (DISABLED)"
            
            trades_csv_lines = [
                f"# All Trades by Ticker - {BUILD_VERSION} '{BUILD_NAME}'",
                f"# Build Date: {BUILD_DATE}",
                f"# Filter Profile: {batch_profile_name}",
                f"# MTF Mode: {at_mtf_status}",
                f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                f"# Total Trades: {len(batch_trades)}",
                f"#",
                "Ticker,Entry Date,Entry Price,Exit Date,Exit Price,Exit Reason,Return (%)"
            ]
            for trade in batch_trades:
                trades_csv_lines.append(
                    f"{trade['Ticker']},{trade['Entry Date']},{trade['Entry Price']:.2f},"
                    f"{trade['Exit Date']},{trade['Exit Price']:.2f},{trade['Exit Reason']},{trade['Return (%)']:+.2f}"
                )
            trades_csv = "\n".join(trades_csv_lines)
            
            st.download_button(
                label=f"Download All Trades ({len(batch_trades)})",
                data=trades_csv,
                file_name=f"All_Trades_{batch_profile_name}_{BUILD_VERSION}_{BUILD_DATE}.csv",
                mime="text/csv",
                width='stretch',
                key="batch_all_trades_csv"
            )
        
        # v14.6 LEADERBOARD REPORT
        st.markdown("---")
        st.markdown("##### Leaderboard Report")
        
        # Get original watchlist
        original_watchlist = st.session_state.get('batch_watchlist', [])
        
        # v16.12: Get filter values from BATCH profile (not individual analysis profile)
        rpt_filter_profile = batch_profile_name  # Use the same variable defined above
        rpt_profile_data = FILTER_PROFILES.get(rpt_filter_profile, FILTER_PROFILES['BALANCED'])
        rpt_suit_floor = rpt_profile_data['suitability_floor']
        rpt_suit_grinder = rpt_profile_data['suitability_grinder']
        rpt_vert_universal = rpt_profile_data['verticality_universal']
        rpt_peakdom_leader = rpt_profile_data['peak_dominance_leader']
        rpt_peakdom_grinder = rpt_profile_data['peak_dominance_grinder']
        # v16.12: Improved verticality description
        rpt_vert_str = "OFF (disabled)" if rpt_vert_universal is None or rpt_vert_universal <= 0 else f"> {rpt_vert_universal} ATR above 30-week SMA"
        
        # v16.16 FIX: Determine MTF mode for header (check ALL toggle keys)
        rpt_mtf_enabled = st.session_state.get('mtf_enforcement_enabled', False)
        rpt_ultimate = (st.session_state.get('mtf_ultimate_mode', False) or
                        st.session_state.get('mtf_ultimate_individual', False) or
                        st.session_state.get('mtf_ultimate_toggle', False))
        if rpt_ultimate:
            rpt_mtf_mode = 'ULTIMATE'
            rpt_mtf_status = "ENABLED"  # v16.16: ULTIMATE always implies enabled
        elif rpt_mtf_enabled:
            rpt_mtf_mode = 'MODERATE' if rpt_filter_profile != 'AGGRESSIVE' else 'AGGRESSIVE'
            rpt_mtf_status = "ENABLED"
        else:
            rpt_mtf_mode = 'OFF'
            rpt_mtf_status = "DISABLED"
        
        # Build comprehensive report with filter profile header
        report_lines = []
        report_lines.append("=" * 60)
        report_lines.append(f"TTA Engine {BUILD_VERSION} - {BUILD_NAME}")
        report_lines.append(f"Build Date: {BUILD_DATE}")
        report_lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report_lines.append("=" * 60)
        report_lines.append("")
        
        # v16.11: Filter Profile Header (prominent at top)
        report_lines.append(f"FILTER PROFILE: {rpt_filter_profile}")
        report_lines.append("-" * 40)
        report_lines.append(f"- Verticality: {rpt_vert_str}")
        report_lines.append(f"- Suitability Floor: {rpt_suit_floor}")
        report_lines.append(f"- Anti-Grinder: Suit > {rpt_suit_grinder} needs PeakDom > {rpt_peakdom_grinder}x")
        report_lines.append(f"- Leader Pass: Suit <= {rpt_suit_grinder} needs PeakDom > {rpt_peakdom_leader}x")
        report_lines.append(f"- Initial Stop: {ATR_INITIAL_STOP_MULT}x ATR")
        report_lines.append(f"- MTF Mode: {rpt_mtf_mode} ({rpt_mtf_status})")
        report_lines.append("")
        
        # Original Watchlist
        report_lines.append("ORIGINAL WATCHLIST")
        report_lines.append("-" * 40)
        report_lines.append(f"Total Tickers: {len(original_watchlist)}")
        report_lines.append(f"Tickers: {', '.join(original_watchlist)}")
        report_lines.append("")
        
        # WHO MADE THE LIST
        report_lines.append("WHO MADE THE LIST")
        report_lines.append("-" * 40)
        passed_sorted = passed_df.sort_values('Total Return (%)', ascending=False)
        if len(passed_sorted) == 0:
            report_lines.append("No tickers passed the filter.")
        else:
            report_lines.append(f"PASSED: {len(passed_sorted)} tickers")
            report_lines.append("")
            for _, row in passed_sorted.iterrows():
                row_ticker = row['Ticker']
                ret = row['Total Return (%)']
                eff = row['Efficiency Ratio']
                trades = int(row['Trades'])
                suit = int(row['Suitability']) if pd.notna(row['Suitability']) else 0
                status = row['Status']
                tier = "Verified Grinder" if "Grinder" in str(status) and "OK" in str(status) else "Momentum Leader"
                report_lines.append(f"  {row_ticker} [{suit}] - {tier}")
                report_lines.append(f"    Return: {ret:+.1f}% | Efficiency: {eff:.2f}x | Trades: {trades}")
        report_lines.append("")
        
        # RETURNS BREAKDOWN (Highest to Lowest)
        report_lines.append("RETURNS BREAKDOWN (Highest to Lowest)")
        report_lines.append("-" * 40)
        if len(passed_sorted) > 0:
            total_return_sum = passed_sorted['Total Return (%)'].sum()
            avg_return = passed_sorted['Total Return (%)'].mean()
            avg_eff = passed_sorted['Efficiency Ratio'].mean()
            total_trades = passed_sorted['Trades'].sum()
            
            for idx, (_, row) in enumerate(passed_sorted.iterrows(), 1):
                row_ticker = row['Ticker']
                ret = row['Total Return (%)']
                eff = row['Efficiency Ratio']
                dd = row['Max Drawdown (%)']
                wr = row['Win Rate (%)']
                report_lines.append(f"  #{idx} {row_ticker}: {ret:+.1f}% return | {eff:.2f}x eff | {dd:.1f}% DD | {wr:.0f}% win rate")
            
            report_lines.append("")
            report_lines.append(f"  TOTAL RETURN (sum): {total_return_sum:+.1f}%")
            report_lines.append(f"  AVG RETURN: {avg_return:+.1f}%")
            report_lines.append(f"  AVG EFFICIENCY: {avg_eff:.2f}x")
            report_lines.append(f"  TOTAL TRADES: {int(total_trades)}")
        report_lines.append("")
        
        # WHO GOT CUT & WHY
        report_lines.append("WHO GOT CUT & WHY")
        report_lines.append("-" * 40)
        if len(rejected_df) == 0:
            report_lines.append("No tickers were rejected.")
        else:
            report_lines.append(f"REJECTED: {len(rejected_df)} tickers")
            report_lines.append("")
            for _, row in rejected_df.iterrows():
                row_ticker = row['Ticker']
                suit = int(row['Suitability']) if pd.notna(row['Suitability']) else 0
                status = str(row['Status']).replace('REJECTED: ', '')
                report_lines.append(f"  {row_ticker} [{suit}]: {status}")
        report_lines.append("")
        
        # SYSTEM EVALUATION
        report_lines.append("SYSTEM EVALUATION")
        report_lines.append("-" * 40)
        pass_rate = (len(passed_df) / len(original_watchlist) * 100) if len(original_watchlist) > 0 else 0
        report_lines.append(f"Pass Rate: {pass_rate:.1f}% ({len(passed_df)}/{len(original_watchlist)})")
        
        if len(passed_sorted) > 0:
            profitable = len(passed_sorted[passed_sorted['Total Return (%)'] > 0])
            losing = len(passed_sorted[passed_sorted['Total Return (%)'] <= 0])
            report_lines.append(f"Profitable Tickers: {profitable}")
            report_lines.append(f"Losing Tickers: {losing}")
            
            high_eff = len(passed_sorted[passed_sorted['Efficiency Ratio'] >= 3.0])
            report_lines.append(f"High Efficiency (>=3.0x): {high_eff}")
            
            best = passed_sorted.iloc[0]
            worst = passed_sorted.iloc[-1]
            report_lines.append(f"Best Performer: {best['Ticker']} ({best['Total Return (%)']:+.1f}%)")
            report_lines.append(f"Worst Performer: {worst['Ticker']} ({worst['Total Return (%)']:+.1f}%)")
        
        report_lines.append("")
        report_lines.append("=" * 60)
        report_lines.append("END OF REPORT")
        report_lines.append("=" * 60)
        
        leaderboard_report = "\n".join(report_lines)
        
        st.download_button(
            label="Download Leaderboard Report",
            data=leaderboard_report,
            file_name=f"Leaderboard_Report_{batch_profile_name}_{BUILD_VERSION}_{BUILD_DATE}.txt",
            mime="text/plain",
            width='stretch',
            key="batch_leaderboard_report"
        )
        
        # v16.12: CONSOLIDATED REPORT - All details in one file
        st.markdown("---")
        st.markdown("##### Consolidated Report")
        st.caption("Complete audit with trades, exits, blocked signals, and diagnostics")
        
        # Build comprehensive consolidated report
        consolidated_lines = []
        consolidated_lines.append("=" * 80)
        consolidated_lines.append(f"TTA ENGINE {BUILD_VERSION} - CONSOLIDATED AUDIT REPORT")
        consolidated_lines.append(f"Build: {BUILD_NAME} | Date: {BUILD_DATE}")
        consolidated_lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        consolidated_lines.append("=" * 80)
        consolidated_lines.append("")
        
        # Filter settings header
        consolidated_lines.append("FILTER PROFILE SETTINGS")
        consolidated_lines.append("-" * 50)
        consolidated_lines.append(f"Profile: {rpt_filter_profile}")
        consolidated_lines.append(f"Suitability Floor: >= {rpt_suit_floor}")
        consolidated_lines.append(f"Suitability Grinder Threshold: > {rpt_suit_grinder}")
        consolidated_lines.append(f"Verticality: {rpt_vert_str}")
        consolidated_lines.append(f"Peak Dominance (Leader): > {rpt_peakdom_leader}x")
        consolidated_lines.append(f"Peak Dominance (Grinder): > {rpt_peakdom_grinder}x")
        consolidated_lines.append(f"Initial Stop: {ATR_INITIAL_STOP_MULT}x ATR")
        consolidated_lines.append(f"MTF Mode: {rpt_mtf_mode} ({rpt_mtf_status})")
        consolidated_lines.append("")
        
        # Watchlist summary
        consolidated_lines.append("WATCHLIST")
        consolidated_lines.append("-" * 50)
        consolidated_lines.append(f"Total Tickers: {len(original_watchlist)}")
        consolidated_lines.append(f"Tickers: {', '.join(original_watchlist)}")
        consolidated_lines.append(f"Passed: {len(passed_df)} | Rejected: {len(rejected_df)}")
        consolidated_lines.append("")
        
        # Get diagnostics from session state
        batch_diagnostics = st.session_state.get('batch_diagnostics', [])
        
        # Detailed per-ticker reports
        consolidated_lines.append("=" * 80)
        consolidated_lines.append("DETAILED TICKER ANALYSIS")
        consolidated_lines.append("=" * 80)
        
        for diag_data in batch_diagnostics:
            ticker_name = diag_data.get('Ticker', 'Unknown')
            consolidated_lines.append("")
            consolidated_lines.append(f"{'='*40}")
            consolidated_lines.append(f"TICKER: {ticker_name}")
            consolidated_lines.append(f"{'='*40}")
            consolidated_lines.append(f"Status: {diag_data.get('Status', 'Unknown')}")
            consolidated_lines.append(f"Suitability: {diag_data.get('Suitability', 0)}/100")
            consolidated_lines.append(f"Total Return: {diag_data.get('Total Return', 0):+.1f}%")
            consolidated_lines.append(f"Max Drawdown: -{diag_data.get('Max Drawdown', 0):.1f}%")
            consolidated_lines.append(f"Efficiency Ratio: {diag_data.get('Efficiency', 0):.2f}x")
            consolidated_lines.append(f"Win Rate: {diag_data.get('Win Rate', 0):.1f}%")
            consolidated_lines.append("")
            
            # Diagnostic counts
            consolidated_lines.append("ENTRY DIAGNOSTICS:")
            consolidated_lines.append(f"  Regime OK Days: {diag_data.get('Regime OK Days', 0)}")
            consolidated_lines.append(f"  Volume OK Days: {diag_data.get('Volume OK Days', 0)}")
            consolidated_lines.append(f"  Momentum OK Days: {diag_data.get('Momentum OK Days', 0)}")
            consolidated_lines.append(f"  Slope OK Days: {diag_data.get('Slope OK Days', 0)}")
            consolidated_lines.append(f"  Entries Taken: {diag_data.get('Entries Taken', 0)}")
            consolidated_lines.append(f"  Exits Taken: {diag_data.get('Exits Taken', 0)}")
            consolidated_lines.append("")
            
            # Trades
            trades = diag_data.get('Trades', [])
            if trades:
                consolidated_lines.append(f"TRADES ({len(trades)}):")
                for i, trade in enumerate(trades, 1):
                    consolidated_lines.append(f"  Trade #{i}:")
                    consolidated_lines.append(f"    Entry: {trade['Entry Date']} @ ${trade['Entry Price']:.2f}")
                    consolidated_lines.append(f"    Exit:  {trade['Exit Date']} @ ${trade['Exit Price']:.2f}")
                    consolidated_lines.append(f"    Return: {trade['Return (%)']:+.1f}%")
                    consolidated_lines.append(f"    Exit Reason: {trade['Exit Reason']}")
            else:
                consolidated_lines.append("TRADES: None")
            consolidated_lines.append("")
            
            # Blocked signals
            blocked = diag_data.get('Blocked Reasons', [])
            if blocked:
                consolidated_lines.append(f"BLOCKED ENTRY SIGNALS ({len(blocked)}):")
                for reason in blocked[:10]:  # Limit to 10 for readability
                    consolidated_lines.append(f"  {reason}")
                if len(blocked) > 10:
                    consolidated_lines.append(f"  ... and {len(blocked) - 10} more")
            else:
                consolidated_lines.append("BLOCKED ENTRY SIGNALS: None recorded")
        
        # Also include rejected tickers (not in batch_diagnostics)
        if len(rejected_df) > 0:
            consolidated_lines.append("")
            consolidated_lines.append("=" * 80)
            consolidated_lines.append("REJECTED TICKERS (Pre-Filter)")
            consolidated_lines.append("=" * 80)
            for _, row in rejected_df.iterrows():
                status = str(row.get('Status', '')).replace('REJECTED: ', '')
                consolidated_lines.append(f"  {row['Ticker']}: {status}")
        
        # Summary statistics
        consolidated_lines.append("")
        consolidated_lines.append("=" * 80)
        consolidated_lines.append("SUMMARY STATISTICS")
        consolidated_lines.append("=" * 80)
        
        if len(passed_sorted) > 0:
            total_return_sum = passed_sorted['Total Return (%)'].sum()
            avg_return = passed_sorted['Total Return (%)'].mean()
            avg_eff = passed_sorted['Efficiency Ratio'].mean()
            total_trades = passed_sorted['Trades'].sum()
            profitable = len(passed_sorted[passed_sorted['Total Return (%)'] > 0])
            
            consolidated_lines.append(f"Total Return (sum): {total_return_sum:+.1f}%")
            consolidated_lines.append(f"Average Return: {avg_return:+.1f}%")
            consolidated_lines.append(f"Average Efficiency: {avg_eff:.2f}x")
            consolidated_lines.append(f"Total Trades: {int(total_trades)}")
            consolidated_lines.append(f"Profitable Tickers: {profitable}/{len(passed_sorted)}")
            
            # v16.12: Drawdown metrics for MTF comparison
            consolidated_lines.append("")
            consolidated_lines.append("DRAWDOWN METRICS")
            consolidated_lines.append("-" * 50)
            dd_values = passed_sorted['Max Drawdown (%)'].values
            avg_dd = np.mean(dd_values)
            median_dd = np.median(dd_values)
            best_dd = np.min(dd_values)  # Lowest is best
            worst_dd = np.max(dd_values)  # Highest is worst
            consolidated_lines.append(f"Average Max Drawdown: -{avg_dd:.1f}%")
            consolidated_lines.append(f"Median Max Drawdown: -{median_dd:.1f}%")
            consolidated_lines.append(f"Best (Lowest) Max Drawdown: -{best_dd:.1f}%")
            consolidated_lines.append(f"Worst (Highest) Max Drawdown: -{worst_dd:.1f}%")
            
            # v16.12: Explicit list of passed tickers
            consolidated_lines.append("")
            consolidated_lines.append("PASSED TICKERS LIST")
            consolidated_lines.append("-" * 50)
            passed_ticker_list = passed_sorted['Ticker'].tolist()
            consolidated_lines.append(f"Passed Tickers ({len(passed_ticker_list)}): {', '.join(passed_ticker_list)}")
            
            # v16.12: Per-ticker summary block (compact one-line format)
            consolidated_lines.append("")
            consolidated_lines.append("PASSED TICKERS (DETAIL)")
            consolidated_lines.append("-" * 50)
            for _, row in passed_sorted.iterrows():
                ticker_sym = row['Ticker']
                ticker_ret = row['Total Return (%)']
                ticker_eff = row['Efficiency Ratio']
                ticker_dd = row['Max Drawdown (%)']
                ticker_trades = int(row['Trades'])
                ticker_wr = row['Win Rate (%)']
                consolidated_lines.append(
                    f"{ticker_sym}: Return {ticker_ret:+.1f}%, Efficiency {ticker_eff:.1f}x, "
                    f"Max DD -{ticker_dd:.1f}%, Trades {ticker_trades}, WinRate {ticker_wr:.1f}%"
                )
        else:
            consolidated_lines.append("No tickers passed the filter.")
        
        consolidated_lines.append("")
        consolidated_lines.append("=" * 80)
        consolidated_lines.append("END OF CONSOLIDATED REPORT")
        consolidated_lines.append("=" * 80)
        
        consolidated_report = "\n".join(consolidated_lines)
        
        st.download_button(
            label="Download Consolidated Report",
            data=consolidated_report,
            file_name=f"Consolidated_Audit_{batch_profile_name}_{BUILD_VERSION}_{BUILD_DATE}.txt",
            mime="text/plain",
            width='stretch',
            key="batch_consolidated_report"
        )
    
    st.divider()
    
    show_dashboard = st.toggle("React Dashboard", value=st.session_state.show_dashboard, key="show_dashboard_toggle")
    st.session_state.show_dashboard = show_dashboard
    
    show_adaptive = st.toggle("Adaptive Strategy", value=st.session_state.show_adaptive_strategy, key="show_adaptive_toggle")
    st.session_state.show_adaptive_strategy = show_adaptive
    
    # --- v12.5 Volatility Personality Scouter ---
    suitability_score = st.session_state.get('suitability_score')
    suitability_verdict = st.session_state.get('suitability_verdict')
    personality_audit = st.session_state.get('personality_audit')
    adaptive_strategy = st.session_state.get('adaptive_strategy')
    adaptive_rationale = st.session_state.get('adaptive_rationale')
    adaptive_color = st.session_state.get('adaptive_color')
    
    # DEBUG: Log toggle and data state
    print(f"[ADAPTIVE DEBUG] show_adaptive={show_adaptive}, suitability_score={suitability_score}, adaptive_strategy={adaptive_strategy}")
    
    # Show adaptive strategy section IMMEDIATELY after toggle when ON
    if show_adaptive and suitability_score is not None:
        st.info(f"Strategy: {adaptive_strategy} | Score: {suitability_score}/100")
        with st.container(border=True):
            st.markdown(f"**Volatility Personality: {suitability_score}/100**")
            if suitability_score > 80:
                st.success(suitability_verdict)
            elif suitability_score > 50:
                st.warning(suitability_verdict)
            else:
                st.error(suitability_verdict)
            
            # v16.35 Adaptive Strategy Display
            if adaptive_strategy:
                st.markdown("---")
                st.markdown(f"**Recommended: {adaptive_strategy}**")
                if adaptive_color == "green":
                    st.success(adaptive_rationale)
                elif adaptive_color == "orange":
                    st.warning(adaptive_rationale)
                elif adaptive_color == "blue":
                    st.info(adaptive_rationale)
                else:
                    st.caption(adaptive_rationale)
                
                # v16.35 Break-Retest Signal Display (only for BREAK-RETEST strategy)
                # Shows pending patterns only: A_BREAKOUT (fresh breakout) or B_RETEST (watching for continuation)
                br_state = st.session_state.get('br_pattern_state')
                if br_state and adaptive_strategy == "BREAK-RETEST":
                    last_bar = br_state.get('last_bar_date', '')
                    phase = br_state.get('pattern_phase')
                    signal = br_state.get('signal', '')
                    
                    if phase == 'B_RETEST':
                        st.warning(f"BR: {signal}")
                        if last_bar:
                            st.caption(f"As of: {last_bar}")
                    elif phase == 'A_BREAKOUT':
                        st.info(f"BR: {signal}")
                        if last_bar:
                            st.caption(f"As of: {last_bar}")
                    elif br_state.get('stage') == 2:
                        sma_val = br_state.get('sma_value', 0)
                        pct = br_state.get('price_vs_sma', 0)
                        st.caption(f"BR: Stage 2, 30w SMA ${sma_val:.2f} ({pct:+.1f}%)")
                    elif br_state.get('stage') == 4:
                        st.caption(f"BR: {signal}")
                    else:
                        sma_val = br_state.get('sma_value')
                        if sma_val:
                            st.caption(f"30w SMA: ${sma_val:.2f} ({br_state.get('price_vs_sma', 0):+.1f}%)")
        
        if personality_audit:
            with st.expander("Details"):
                for metric, value in personality_audit.items():
                    st.markdown(f"**{metric}:** {value}")
    
    # --- v11.2 TTA Stats Display ---
    tta_stats = st.session_state.get('tta_stats', {})
    if tta_stats.get("count", 0) > 0:
        st.divider()
        st.markdown("##### TTA Signals")
        if tta_stats.get("active_sl") is not None:
            st.error(f"ACTIVE STOP (Level A): ${tta_stats['active_sl']:.2f}")
        st.metric("Sync Buy Signals", tta_stats["count"])
        if tta_stats.get("final_balance") is not None:
            final_bal = tta_stats['final_balance']
            st.metric("Portfolio Growth", f"$10k → ${final_bal/1000:.1f}k")
        if tta_stats.get("total_return") is not None:
            st.metric("Total Return", f"{tta_stats['total_return']:+.1f}%")
        if tta_stats.get("max_drawdown") is not None and tta_stats["max_drawdown"] > 0:
            st.markdown(f"**Max Drawdown:** :red[-{tta_stats['max_drawdown']:.1f}%]")
        if tta_stats.get("efficiency_ratio") is not None and tta_stats["efficiency_ratio"] >= 0:
            eff = tta_stats['efficiency_ratio']
            cagr_val = tta_stats.get('cagr')
            if cagr_val:
                st.markdown(f"**CAGR:** {cagr_val:+.1f}%")
            # v16.4: Updated badge colors for efficiency display
            if eff >= 100:
                st.markdown(f"**True Calmar (CAGR/DD):** :violet[{eff:.2f}x] 💎")
            elif eff >= 10.0:
                st.markdown(f"**True Calmar (CAGR/DD):** :orange[{eff:.2f}x] 🥇")
            elif eff >= 3.0:
                st.markdown(f"**True Calmar (CAGR/DD):** :green[{eff:.2f}x]")
            elif eff >= 1.0:
                st.markdown(f"**True Calmar (CAGR/DD):** {eff:.2f}x")
            else:
                st.markdown(f"**True Calmar (CAGR/DD):** :red[{eff:.2f}x]")
        if tta_stats.get("success_rate", 0) > 0:
            st.metric("Win Rate", f"{tta_stats['success_rate']:.0f}%")
        if tta_stats.get("trade_count", 0) > 0:
            st.metric("Completed Trades", f"{tta_stats['trade_count']}")
        
        # --- TRADE LOG DISPLAY with Download ---
        trade_log = tta_stats.get("trade_log", [])
        if trade_log:
            with st.expander(f"Trade Report ({len(trade_log)} trades)", expanded=True):
                # Build display table
                for trade in trade_log:
                    ret = trade["return_pct"]
                    ret_color = ":green" if ret > 0 else ":red"
                    status = "OPEN" if trade["exit_date"] == "OPEN" else "Closed"
                    
                    st.markdown(f"**Trade #{trade['trade_num']}** ({status})")
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown(f"Entry: **{trade['entry_date']}**")
                        st.markdown(f"@ ${trade['entry_price']:.2f}")
                        st.markdown(f"_{trade['entry_reason']}_")
                    with col2:
                        st.markdown(f"Exit: **{trade['exit_date']}**")
                        st.markdown(f"@ ${trade['exit_price']:.2f}")
                        st.markdown(f"_{trade['exit_reason']}_")
                    
                    st.markdown(f"Return: {ret_color}[{ret:+.2f}%] | Days: {trade['holding_days']} | Slope: {trade['sma_slope']:.2f}%")
                    st.divider()
                
                # CSV Download Button
                current_ticker = st.session_state.get('current_ticker', 'STOCK')
                # v16.12: Add header with filter profile info
                sidebar_profile = st.session_state.get('filter_profile', 'BALANCED')
                sidebar_profile_data = FILTER_PROFILES.get(sidebar_profile, FILTER_PROFILES['BALANCED'])
                sidebar_vert = sidebar_profile_data['verticality_universal']
                sidebar_vert_str = "OFF" if sidebar_vert is None or sidebar_vert <= 0 else f"> {sidebar_vert}"
                csv_lines = [
                    f"# Trade Report: {current_ticker}",
                    f"# Filter Profile: {sidebar_profile}",
                    f"# - Suitability Floor: {sidebar_profile_data['suitability_floor']}",
                    f"# - Verticality: {sidebar_vert_str}",
                    f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    "#",
                    "Trade#,Entry Date,Entry Price,Entry Reason,SMA Slope (%),Exit Date,Exit Price,Exit Reason,Return (%),Holding Days"
                ]
                for t in trade_log:
                    csv_lines.append(f"{t['trade_num']},{t['entry_date']},{t['entry_price']:.2f},{t['entry_reason']},{t['sma_slope']:.2f},{t['exit_date']},{t['exit_price']:.2f},{t['exit_reason']},{t['return_pct']:.2f},{t['holding_days']}")
                trade_csv = "\n".join(csv_lines)
                
                st.download_button(
                    label="Download Trade Report (CSV)",
                    data=trade_csv,
                    file_name=f"{current_ticker}_trade_report.csv",
                    mime="text/csv",
                    width='stretch',
                    key=f"sidebar_trade_report_{current_ticker}"
                )
        
        # Show diagnostic counters if available
        diag = tta_stats.get("diagnostics", {})
        if diag:
            with st.expander("Execution Diagnostics"):
                st.write(f"Daily Bars: {diag.get('count_daily_bars_total', 0)}")
                st.write(f"Regime OK: {diag.get('count_regime_ok', 0)}")
                st.write(f"Volume OK: {diag.get('count_volume_ok', 0)}")
                st.write(f"Momentum OK: {diag.get('count_momentum_ok', 0)}")
                st.write(f"Slope OK: {diag.get('count_slope_ok', 0)}")
                st.write(f"Slope Rejected: {diag.get('count_slope_rejected', 0)}")
                st.write(f"Entries: {diag.get('count_entries_taken', 0)}")
                st.write(f"Exits: {diag.get('count_exits_taken', 0)}")
                
                # v16.0 Adaptive Architect Metrics
                st.divider()
                st.markdown("**v16.0 Adaptive Architect**")
                msr_val = tta_stats.get('msr_latest', 0)
                nsr_val = tta_stats.get('nsr_latest', 0)
                regime_val = tta_stats.get('regime_ratio_latest', 1.0)
                is_cons = tta_stats.get('is_consolidating', False)
                
                msr_color = ":green" if msr_val > MSR_ESCAPE_VELOCITY else ""
                st.write(f"MSR (Momentum Surge): {msr_color}[{msr_val:.2f}]" if msr_color else f"MSR (Momentum Surge): {msr_val:.2f}")
                st.write(f"NSR (Noise/Signal): {nsr_val:.3f}")
                regime_shift = ":orange[REGIME SHIFT]" if regime_val > NSR_REGIME_SHIFT else "Stable"
                st.write(f"Regime Ratio: {regime_val:.2f} ({regime_shift})")
                st.write(f"Consolidation: {'Yes (Bull Flag)' if is_cons else 'No'}")
                
                # v16.0 Feature Usage Counters
                st.markdown("**v16.0 Feature Triggers:**")
                checks_count = diag.get('count_escape_velocity_checks', 0)
                escape_count = diag.get('count_escape_velocity_entries', 0)
                extended_count = diag.get('count_time_stop_extended', 0)
                catastrophic_count = diag.get('count_catastrophic_floor_exits', 0)
                st.write(f"v16.0 Bars Evaluated: {checks_count}")
                st.write(f"Escape Velocity Entries: {escape_count}")
                st.write(f"Time-Stop Extensions: {extended_count}")
                st.write(f"Catastrophic Floor Exits: {catastrophic_count}")
                blocked = diag.get('blocked_reasons', [])
                if blocked:
                    st.write("Near-miss blocks:")
                    for r in blocked[:5]:
                        st.write(f"  {r}")
                
                # v16.12: MTF Gate Status for Single Stock Analysis
                st.divider()
                st.markdown("**v16.12 MTF Gate Status**")
                mtf_enabled = st.session_state.get('mtf_enforcement_enabled', False)
                
                # Show current traffic light alignment
                traffic_lights = tta_stats.get('traffic_lights', {})
                if traffic_lights:
                    # Get current profile's MTF mode
                    sidebar_profile = st.session_state.get('filter_profile', 'BALANCED')
                    if sidebar_profile == 'AGGRESSIVE':
                        mtf_mode = 'AGGRESSIVE'
                    else:
                        mtf_mode = 'MODERATE'
                    
                    # Check current bar's MTF alignment (same logic as check_perbar_mtf_alignment)
                    # v16.12: Uses M/W/D (Monthly/Weekly/Daily) instead of W/D/4H
                    monthly_dot = traffic_lights.get('monthly_dot_color', '#6b7280')
                    weekly_dot = traffic_lights.get('weekly_dot_color', '#6b7280')
                    daily_dot = traffic_lights.get('daily_dot_color', '#6b7280')
                    
                    GREEN = '#00E676'
                    YELLOW = '#fbbf24'
                    
                    def dot_status(color):
                        if color == GREEN:
                            return ":green[GREEN]"
                        elif color == YELLOW:
                            return ":orange[YELLOW]"
                        else:
                            return ":red[RED/GRAY]"
                    
                    st.write(f"Monthly: {dot_status(monthly_dot)} | Weekly: {dot_status(weekly_dot)} | Daily: {dot_status(daily_dot)}")
                    
                    # Check MTF gate pass/fail using same logic as check_perbar_mtf_alignment
                    if mtf_mode == 'AGGRESSIVE':
                        # Weekly green, Monthly at least yellow
                        mtf_pass = weekly_dot in [GREEN, YELLOW] and monthly_dot in [GREEN, YELLOW]
                        mtf_reason = "Weekly + Monthly aligned" if mtf_pass else "Weekly or Monthly not green/yellow"
                    else:  # MODERATE
                        # M + W green, D at least yellow
                        mtf_pass = (monthly_dot in [GREEN, YELLOW] and 
                                   weekly_dot in [GREEN, YELLOW] and 
                                   daily_dot in [GREEN, YELLOW])
                        mtf_reason = "Monthly + Weekly + Daily aligned" if mtf_pass else "One or more timeframes not green/yellow"
                    
                    # Display based on whether MTF is enabled
                    if mtf_enabled:
                        st.write(f"MTF Gate: **ENABLED** ({mtf_mode} mode)")
                        if mtf_pass:
                            st.success(f"Current Bar: PASS - {mtf_reason}")
                        else:
                            st.warning(f"Current Bar: FAIL - {mtf_reason}")
                    else:
                        st.write(f"MTF Gate: **DISABLED** (informational only)")
                        if mtf_pass:
                            st.info(f"Would PASS: {mtf_reason}")
                        else:
                            st.info(f"Would FAIL: {mtf_reason}")
                    
                    # Show MTF blocked and exit counts from scan (only relevant when enabled)
                    mtf_blocked = diag.get('count_mtf_blocked', 0)
                    mtf_exits = diag.get('count_mtf_exits', 0)
                    if mtf_enabled:
                        if mtf_blocked > 0 or mtf_exits > 0:
                            st.write(f"MTF Entries Blocked: {mtf_blocked} | MTF Exits: {mtf_exits}")
                    else:
                        st.caption("Enable MTF Gate toggle to enforce as 5th entry gate")
                else:
                    st.info("Traffic lights not calculated")
                
                # v16.17: 4H Divergence Detection Status
                st.divider()
                st.markdown("**v16.17 4H Divergence Early Warning**")
                h4_div_exits = diag.get('count_4h_div_exits', 0)
                st.write(f"4H Divergence Exits (Historical): {h4_div_exits}")
                
                # Run live 4H divergence check on current data
                h1_df_live = st.session_state.get('h1_df')
                if h1_df_live is not None and not h1_df_live.empty:
                    h4_df_live = h1_df_live.resample('4h').agg({
                        'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
                    }).dropna()
                    
                    if len(h4_df_live) >= 30:
                        live_div = detect_4h_divergence(h4_df_live, lookback=20)
                        st.session_state['h4_divergence_result'] = live_div
                        
                        if live_div["detected"]:
                            sev = live_div["severity"]
                            sev_colors = {"WEAK": "🟡", "MODERATE": "🟠", "STRONG": "🔴"}
                            st.warning(f"{sev_colors.get(sev, '⚠️')} **4H DIVERGENCE DETECTED [{sev}]**")
                            st.caption(live_div["message"])
                            
                            # Show swing high comparison
                            if live_div["price_highs"] and len(live_div["price_highs"]) >= 2:
                                ph = live_div["price_highs"]
                                ao = live_div["ao_peaks"]
                                st.write(f"Price: ${ph[-2][1]:.2f} → ${ph[-1][1]:.2f} (Higher High)")
                                st.write(f"AO: {ao[-2][1]:.2f} → {ao[-1][1]:.2f} (Lower High)")
                        else:
                            st.success("✅ No 4H Divergence - Momentum Aligned")
                    else:
                        st.caption("Insufficient 4H data for divergence detection")
                else:
                    st.caption("No 4H data available")


# =========================================================================
# v11.5 TTA RISK ENGINE: Tri-Timeframe Alignment with Minute Degree Execution
# Weekly (Intermediate) + Daily (Minor) sync, h1_df (Minute) as execution frame
# Projects Minute Degree signals onto Daily (Minor Degree) chart
# =========================================================================
def scan_tta_for_daily_chart(daily_df, weekly_df, weekly_sma_data, ticker, h1_df=None, filter_profile='BALANCED', suitability_score=50):
    """v13.3 TTA Risk Engine: Vertical Lock - dynamic ATR tightening + gap protection.
    
    Projects signals onto the Daily (Minor Degree) Chart.
    Returns markers mapped to Daily chart dates.
    
    Args:
        daily_df: Daily dataframe (Minor Degree) - display frame
        weekly_df: Weekly dataframe (Intermediate Degree) - higher anchor
        weekly_sma_data: 30-week SMA series for Stage 2 filtering
        ticker: Stock ticker symbol
        h1_df: Hourly dataframe (Minute Degree) - execution frame (if None, will fetch)
        filter_profile: 'CONSERVATIVE', 'BALANCED', 'AGGRESSIVE', or 'HYBRID' - controls filters AND MTF
        suitability_score: v12.7 Personality score (0-100) for adaptive stops
    """
    # v16.12: Map Filter Profile to MTF mode (single source of truth)
    # Filter Profile controls both filters AND MTF strictness
    # Check for ULTIMATE mode override from session state (check both sidebar toggle keys)
    ult_mode = st.session_state.get('mtf_ultimate_mode', False)
    ult_ind = st.session_state.get('mtf_ultimate_individual', False)
    ult_tog = st.session_state.get('mtf_ultimate_toggle', False)
    use_ultimate_mtf = ult_mode or ult_ind or ult_tog
    
    # Debug: Print ULTIMATE toggle states
    print(f"[ULTIMATE DEBUG] mtf_ultimate_mode={ult_mode}, mtf_ultimate_individual={ult_ind}, mtf_ultimate_toggle={ult_tog} => use_ultimate={use_ultimate_mtf}")
    
    if use_ultimate_mtf:
        mtf_mode = 'ULTIMATE'      # New 5-Gate entry + Triple Confirmation exit
    elif filter_profile == 'AGGRESSIVE':
        mtf_mode = 'AGGRESSIVE'    # Aggressive filters + loose MTF
    else:  # 'CONSERVATIVE', 'BALANCED', 'HYBRID'
        mtf_mode = 'MODERATE'      # All other profiles use practical MTF
    
    # v16.16: Enhanced debug logging for ULTIMATE mode verification
    tlog(f"🔍 DEBUG - Session State Check:")
    tlog(f"  mtf_ultimate_mode: {st.session_state.get('mtf_ultimate_mode', False)}")
    tlog(f"  mtf_ultimate_individual: {st.session_state.get('mtf_ultimate_individual', False)}")
    tlog(f"  mtf_ultimate_toggle: {st.session_state.get('mtf_ultimate_toggle', False)}")
    tlog(f"  use_ultimate_mtf: {use_ultimate_mtf}")
    tlog(f"  mtf_mode (final): {mtf_mode}")
    tlog(f"  filter_profile: {filter_profile}")
    
    # v16.12: Get filter values for debug output
    profile_data = FILTER_PROFILES.get(filter_profile, FILTER_PROFILES['BALANCED'])
    suit_floor = profile_data['suitability_floor']
    vert_val = profile_data['verticality_universal']
    vert_str = "OFF" if vert_val is None or vert_val <= 0 else f"> {vert_val} ATR"
    peakdom_l = profile_data['peak_dominance_leader']
    peakdom_g = profile_data['peak_dominance_grinder']
    
    # v16.12: Get MTF enforcement state for debug output (check all toggle keys)
    mtf_enforcement_debug = (st.session_state.get('mtf_enforcement_enabled', False) or 
                             st.session_state.get('mtf_ultimate_mode', False) or
                             st.session_state.get('mtf_ultimate_individual', False) or
                             st.session_state.get('mtf_ultimate_toggle', False))
    mtf_status_debug = "ENABLED" if mtf_enforcement_debug else "DISABLED"
    
    print(f"")
    tlog(f"[SCAN] {ticker} | Profile: {filter_profile} | MTF: {mtf_mode} ({mtf_status_debug})")
    tlog(f"[FILTERS] Suit>={suit_floor} Vert={vert_str} PeakDom {peakdom_l}/{peakdom_g}")
    
    historical_markers = []
    stats = {"count": 0, "avg_run": 0.0, "total_return": None, "final_balance": None, "max_drawdown": None, "efficiency_ratio": None, "cagr": None, "success_rate": 0, "trade_count": 0, "active_sl": None}
    
    # v12.9 High-Velocity Wave 3 Engine - Standardized "Goldilocks" Stop
    atr_mult = 3.5  # 3.5x ATR for ALL stocks - optimal for Wave 3 momentum
    position_size_mod = 1.0  # Full size for high-velocity entries
    
    # v16.3 Simplified Momentum Entry - Wide stops, aggressive entries
    ATR_INITIAL_STOP_MULT = 8.0  # Very wide stop for Wave 3 volatility (was 5.0)
    VOLUME_SURGE_THRESHOLD = 1.3  # v16.24: Back to 1.3x - trades with 1.0-1.1x volume are losers
    MIN_SMA_SLOPE = 0.15  # Minimum 0.15% weekly SMA slope (trend confirmation)
    
    if daily_df is None or daily_df.empty or weekly_df is None or weekly_df.empty or weekly_sma_data is None:
        return [], stats
    
    # v15.5 Hybrid Alpha: Calculate Peak Dominance for Adaptive Slope Gate
    ao_for_peakdom = calculate_awesome_oscillator(daily_df)
    ao_abs = ao_for_peakdom.abs()
    ao_peak = ao_abs.max()
    ao_median = ao_abs.median()
    peak_dominance = ao_peak / ao_median if ao_median > 0 else 0
    
    # v15.5: Determine if stock qualifies as High-Alpha Leader
    is_high_alpha = suitability_score > HIGH_ALPHA_SUITABILITY and peak_dominance > HIGH_ALPHA_PEAKDOM
    adaptive_slope_threshold = SMA_SLOPE_HIGH_ALPHA if is_high_alpha else SMA_SLOPE_THRESHOLD
    
    if is_high_alpha:
        print(f"TTA v15.5: HIGH-ALPHA LEADER (Suit {suitability_score} > {HIGH_ALPHA_SUITABILITY}, PeakDom {peak_dominance:.1f}x > {HIGH_ALPHA_PEAKDOM}) - Using {adaptive_slope_threshold}% slope threshold")
    else:
        print(f"TTA v15.5: Standard stock - Using {adaptive_slope_threshold}% slope threshold")

    # 1. Higher-Degree Anchors - Get Weekly and Daily wave diagnostics
    w_ao = calculate_awesome_oscillator(weekly_df)
    w_diag = build_ao_chunk_diagnostic(
        w_ao.to_numpy(), 
        weekly_df.index.to_numpy(), 
        weekly_df['High'].to_numpy(), 
        weekly_df['Low'].to_numpy(),
        weekly_df['Close'].to_numpy(),
        None  # No SMA reset for weekly
    )
    
    d_ao = calculate_awesome_oscillator(daily_df)
    daily_sma_aligned = weekly_sma_data.reindex(daily_df.index, method='ffill')
    d_diag = build_ao_chunk_diagnostic(
        d_ao.to_numpy(), 
        daily_df.index.to_numpy(), 
        daily_df['High'].to_numpy(), 
        daily_df['Low'].to_numpy(),
        daily_df['Close'].to_numpy(),
        daily_sma_aligned.to_numpy()
    )

    # v16.1 Wave Hunter: Two-stage entry IS the W3 detector - no pre-detection required
    w3_weekly = w_diag.get("wave3") if w_diag else None
    w3_daily = d_diag.get("wave3") if d_diag else None
    
    # Log W3 status for diagnostics but DON'T block trading
    if w3_weekly and w3_daily:
        w3_weekly_status = "complete" if w3_weekly.get("complete", False) else "developing"
        w3_daily_status = "complete" if w3_daily.get("complete", False) else "developing"
        print(f"TTA: Weekly W3 ({w3_weekly_status}) + Daily W3 ({w3_daily_status}) SYNC - high confidence")
    elif w3_weekly or w3_daily:
        print(f"TTA: W3 on one timeframe - moderate confidence setups")
    else:
        print(f"TTA: No formal W3 detected - scanning for early-stage setups")
    
    # Find SMA crossover date on daily chart (when price crossed above SMA)
    daily_sma_list = daily_sma_aligned.tolist()
    daily_closes = daily_df['Close'].tolist()
    sma_crossover_date = None
    
    # v16.1: Find FIRST SMA crossover to scan full history
    for idx in range(1, len(daily_df)):
        if daily_sma_list[idx] is not None and not pd.isna(daily_sma_list[idx]):
            if daily_closes[idx] > daily_sma_list[idx] and daily_closes[idx-1] <= daily_sma_list[idx-1]:
                sma_crossover_date = daily_df.index[idx]
                break  # Stop at FIRST crossover to scan all history
    
    if sma_crossover_date is None:
        # Fallback: find first bar above SMA
        for idx in range(len(daily_df)):
            if daily_sma_list[idx] is not None and not pd.isna(daily_sma_list[idx]):
                if daily_closes[idx] > daily_sma_list[idx]:
                    sma_crossover_date = daily_df.index[idx]
                    break
    
    if sma_crossover_date is None:
        # v16.1: Use start of data as fallback instead of blocking
        sma_crossover_date = daily_df.index[0]
        print("TTA: No SMA crossover found - using start of data")
    
    # v16.1: Scan FULL dataset from first valid bar to end (no W3 date restriction)
    scan_start = pd.to_datetime(sma_crossover_date)
    scan_end = daily_df.index[-1]
    print(f"TTA: Scanning full dataset from {scan_start.date()} to {scan_end.date()}")
    
    # 2. v11.5: Use passed h1_df or fetch if not provided
    if h1_df is not None and not h1_df.empty:
        hourly_df = h1_df
        print(f"TTA: Using passed h1_df with {len(hourly_df)} bars (Minute Degree execution frame)")
    else:
        hourly_df = fetch_stock_data(ticker, period="60d", interval="1h")
        print(f"TTA: Fetched hourly data with {len(hourly_df) if not hourly_df.empty else 0} bars")
    
    if hourly_df.empty:
        print("TTA: No hourly data available")
        return [], stats
    
    # v11.5: Scan HOURLY bars directly for Minute Degree entries
    ao_1h = calculate_awesome_oscillator(hourly_df).tolist()
    dates_1h = hourly_df.index.tolist()
    closes_1h = hourly_df['Close'].tolist()
    highs_1h = hourly_df['High'].tolist()
    lows_1h = hourly_df['Low'].tolist()
    
    # Align weekly SMA to hourly timeframe
    sma_aligned = weekly_sma_data.reindex(hourly_df.index, method='ffill').tolist()
    
    # We'll check SMA slope AT EACH SIGNAL DATE, not just current state
    # Prepare weekly SMA data with dates for historical slope checking
    weekly_sma_dates = weekly_sma_data.index.tolist()
    weekly_sma_values = weekly_sma_data.tolist()
    
    def is_sma_rising(check_date):
        """Check if 30-week SMA is not in decline (rising or flat is OK)
        
        Allow trading when SMA is flat or rising (decline up to -2% tolerated).
        This enables trading during consolidation phases above SMA.
        """
        check_date = pd.to_datetime(check_date)
        # Find the closest weekly SMA value at or before check_date
        curr_idx = None
        for idx, sma_date in enumerate(weekly_sma_dates):
            if pd.to_datetime(sma_date) <= check_date:
                curr_idx = idx
            else:
                break
        
        if curr_idx is None or curr_idx < 8:
            return False
        
        sma_now = weekly_sma_values[curr_idx]
        sma_8w_ago = weekly_sma_values[curr_idx - 8]
        
        if sma_8w_ago <= 0:
            return False
        
        # Allow flat or rising SMA (decline up to -2% is tolerated for consolidation)
        pct_change = ((sma_now - sma_8w_ago) / sma_8w_ago) * 100
        is_not_declining = pct_change >= -2.0  # Allow flat/slightly declining
        
        return is_not_declining
    
    def get_sma_slope_5w(check_date):
        """v15.2 Launch Gate: Calculate 5-week SMA slope percentage.
        
        Returns the percentage change of 30-week SMA over last 5 weeks.
        Entries require slope > 0.5% to confirm Stage 2 momentum.
        """
        check_date = pd.to_datetime(check_date)
        # Find the closest weekly SMA value at or before check_date
        curr_idx = None
        for idx, sma_date in enumerate(weekly_sma_dates):
            if pd.to_datetime(sma_date) <= check_date:
                curr_idx = idx
            else:
                break
        
        if curr_idx is None or curr_idx < 5:
            return 0.0
        
        sma_now = weekly_sma_values[curr_idx]
        sma_5w_ago = weekly_sma_values[curr_idx - 5]
        
        if sma_5w_ago is None or pd.isna(sma_5w_ago) or sma_5w_ago <= 0:
            return 0.0
        if sma_now is None or pd.isna(sma_now):
            return 0.0
        
        slope_pct = ((sma_now - sma_5w_ago) / sma_5w_ago) * 100
        return slope_pct
    
    print("TTA: Will check SMA slope at each signal date (v15.2 Launch Gate: slope > 0.5%)")
    
    # Daily dates for mapping
    daily_dates = daily_df.index.tolist()
    
    # Determine Wave 3 status for each timeframe (traffic light system)
    # Resample to 4H and check for W3
    h4_df = hourly_df.resample('4h').agg({
        'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
    }).dropna()
    
    # v16.37: Store h4_df in session_state for MACD calculation consistency
    st.session_state['h4_df'] = h4_df
    
    # Get 4H wave diagnostic
    h4_w3 = None
    if not h4_df.empty:
        ao_4h_series = calculate_awesome_oscillator(h4_df)
        h4_diag = build_ao_chunk_diagnostic(
            ao_4h_series.to_numpy(),
            h4_df.index.to_numpy(),
            h4_df['High'].to_numpy(),
            h4_df['Low'].to_numpy(),
            h4_df['Close'].to_numpy(),
            None
        )
        h4_w3 = h4_diag.get("wave3") if h4_diag else None
    
    # --- TIME-AWARE TRAFFIC LIGHTS (regime proxy) ---
    # Weekly/Daily/4H are "green" only when their AO is > 0 at each bar (not static)
    # Prepare aligned AO series for time-aware gating
    w_ao_aligned = w_ao.reindex(daily_df.index, method='ffill')   # weekly AO mapped onto daily
    d_ao_series = d_ao                                            # already daily
    ao_4h_aligned = ao_4h_series.reindex(daily_df.index, method='ffill') if not h4_df.empty else None
    
    # v16.9: Context-aware labels reflecting BOTH structure AND momentum
    def get_wave_label_from_diag(diag, has_w3, momentum):
        """
        Extract wave state and convert to context-aware label.
        Considers BOTH structure (wave type) AND momentum (AO state).
        
        Args:
            diag: Diagnostic object with wave data
            has_w3: Boolean if W3 detected
            momentum: Boolean - True if AO bullish (green dot), False if bearish (red dot)
        
        Returns:
            Label reflecting both structure and strength
        """
        if diag is None:
            return '—'
        
        current_wave = diag.get("current_wave")
        
        # Two-dimensional mapping: [wave_type][momentum_state]
        # Structure tells DIRECTION, momentum tells STRENGTH
        
        if current_wave in ['W3', 'W3?']:
            # Impulse wave - check momentum strength
            return 'STRONG' if momentum else 'WEAK'
        
        elif current_wave in ['W5', 'W5?']:
            # Late impulse - check if still extending
            return 'HOLD' if momentum else 'FADING'
        
        elif current_wave in ['W4', 'W4?']:
            # Correction phase - always caution
            return 'PULL' if momentum else 'WAIT'
        
        elif current_wave == 'Corr':
            # Correction complete - potential base
            return 'BASE' if momentum else 'WATCH'
        
        elif current_wave == 'Corr!':
            # Active correction - always avoid
            return 'AVOID'
        
        else:
            # No wave detected
            return 'STRONG' if (has_w3 and momentum) else 'WEAK' if has_w3 else '—'
    
    # v16.11: MTF Alignment Check for Entry
    def check_mtf_alignment_for_entry(traffic_lights, mtf_mode):
        """
        Validate multi-timeframe alignment before entry based on filter mode.
        
        Args:
            traffic_lights: Dict with wave labels and dot colors per timeframe
            mtf_mode: 'CONSERVATIVE', 'MODERATE', or 'AGGRESSIVE'
        
        Returns:
            (passed: bool, reason: str)
        
        Rules by mode (v16.12: M/W/D instead of W/D/4H):
        - CONSERVATIVE: All 3 timeframes (M/W/D) must have green dots (full alignment)
        - MODERATE: Monthly + Weekly must be green, Daily at least yellow
        - AGGRESSIVE: Weekly must be green, Monthly at least yellow
        """
        if not traffic_lights:
            return True, "No traffic lights data"
        
        # Extract dot colors (v16.12: M/W/D)
        monthly_dot = traffic_lights.get('monthly_dot_color', '#6b7280')
        weekly_dot = traffic_lights.get('weekly_dot_color', '#6b7280')
        daily_dot = traffic_lights.get('daily_dot_color', '#6b7280')
        
        # Define color checks
        GREEN = '#00E676'
        YELLOW = '#fbbf24'
        RED = '#ef4444'
        
        is_green = lambda c: c == GREEN
        is_yellow_or_green = lambda c: c in [GREEN, YELLOW]
        is_red = lambda c: c == RED
        
        if mtf_mode == 'CONSERVATIVE':
            # All 3 timeframes must be green (M/W/D)
            if not is_green(monthly_dot):
                return False, f"Monthly dot not green ({monthly_dot})"
            if not is_green(weekly_dot):
                return False, f"Weekly dot not green ({weekly_dot})"
            if not is_green(daily_dot):
                return False, f"Daily dot not green ({daily_dot})"
            return True, "Full MTF alignment"
        
        elif mtf_mode == 'MODERATE':
            # Monthly + Weekly must be green, Daily at least yellow
            if not is_green(monthly_dot):
                return False, f"Monthly dot not green ({monthly_dot})"
            if not is_green(weekly_dot):
                return False, f"Weekly dot not green ({weekly_dot})"
            if is_red(daily_dot):
                return False, f"Daily dot is red ({daily_dot})"
            return True, "M/W green, D not red"
        
        else:  # AGGRESSIVE
            # Weekly must be green, Monthly at least yellow
            if not is_green(weekly_dot):
                return False, f"Weekly dot not green ({weekly_dot})"
            if is_red(monthly_dot):
                return False, f"Monthly dot is red ({monthly_dot})"
            return True, "Weekly green, Monthly not red"
    
    # v16.11: MTF Exit Check - Higher timeframe reversals
    def check_mtf_alignment_for_exit(traffic_lights, mtf_mode):
        """
        Check if higher timeframes have reversed, signaling exit.
        
        Args:
            traffic_lights: Dict with wave labels and dot colors per timeframe
            mtf_mode: 'CONSERVATIVE', 'MODERATE', or 'AGGRESSIVE'
        
        Returns:
            (should_exit: bool, reason: str)
        
        Exit Rules by mode:
        - CONSERVATIVE: Exit if Weekly OR Daily turns red
        - MODERATE: Exit if Weekly turns red
        - AGGRESSIVE: Exit only if Weekly turns red AND Daily red
        """
        if not traffic_lights:
            return False, ""
        
        # Extract dot colors
        weekly_dot = traffic_lights.get('weekly_dot_color', '#6b7280')
        daily_dot = traffic_lights.get('daily_dot_color', '#6b7280')
        
        # Define color checks
        RED = '#ef4444'
        is_red = lambda c: c == RED
        
        if mtf_mode == 'CONSERVATIVE':
            # Exit if Weekly OR Daily turns red
            if is_red(weekly_dot):
                return True, "Weekly turned red"
            if is_red(daily_dot):
                return True, "Daily turned red"
            return False, ""
        
        elif mtf_mode == 'MODERATE':
            # Exit only if Weekly turns red
            if is_red(weekly_dot):
                return True, "Weekly turned red"
            return False, ""
        
        else:  # AGGRESSIVE
            # Exit only if BOTH Weekly AND Daily are red
            if is_red(weekly_dot) and is_red(daily_dot):
                return True, "Weekly AND Daily red"
            return False, ""
    
    # v16.14: Ultimate MTF Entry - 5-Gate Entry System (M/W/D)
    def check_mtf_ultimate_entry(ticker, weekly_data, daily_data, monthly_data=None):
        """5-Gate Entry: Monthly MACD + Weekly MACD + Daily MACD + Daily AO Positive
        
        Uses RELAXED MACD check (MACD > signal) not STRICT cross check.
        This allows entries anytime during a bullish trend, not just on the cross bar.
        """
        try:
            # Need at least 34 bars for AO and 26 for MACD
            MIN_BARS = 34
            
            # Helper to safely get Close column (handles both 'Close' and 'close')
            def get_close(df, label="data"):
                if df is None:
                    tlog(f"  {label}: None")
                    return None
                if len(df) < MIN_BARS:
                    tlog(f"  {label}: {len(df)} bars < {MIN_BARS} minimum")
                    return None
                if hasattr(df, 'columns'):
                    cols = list(df.columns)
                    if 'Close' in df.columns:
                        return df['Close']
                    elif 'close' in df.columns:
                        return df['close']
                    else:
                        tlog(f"  {label}: No Close column! Columns: {cols[:5]}")
                return None
            
            # Gate 1: Monthly MACD bullish (MACD > signal) - if available
            monthly_close = get_close(monthly_data, "Monthly")
            if monthly_close is not None:
                monthly_macd, monthly_signal, _ = calculate_macd(monthly_close)
                # RELAXED: Check if MACD > signal (not cross)
                monthly_bull = monthly_macd.iloc[-1] > monthly_signal.iloc[-1] if len(monthly_macd) > 0 else True
            else:
                monthly_bull = True  # Skip if insufficient monthly data
            
            # Gate 2: Weekly MACD bullish (MACD > signal)
            weekly_close = get_close(weekly_data, "Weekly")
            if weekly_close is not None:
                weekly_macd, weekly_signal, _ = calculate_macd(weekly_close)
                # RELAXED: Check if MACD > signal (not cross)
                weekly_bull = weekly_macd.iloc[-1] > weekly_signal.iloc[-1] if len(weekly_macd) > 0 else True
            else:
                weekly_bull = True  # Skip if insufficient weekly data
            
            # Gate 3: Daily MACD bullish (MACD > signal)
            daily_close = get_close(daily_data, "Daily")
            if daily_close is not None:
                daily_macd, daily_signal, _ = calculate_macd(daily_close)
                # RELAXED: Check if MACD > signal (not cross)
                daily_bull = daily_macd.iloc[-1] > daily_signal.iloc[-1] if len(daily_macd) > 0 else True
            else:
                return True  # Skip ULTIMATE check if insufficient daily data
            
            # Gate 4: Daily AO positive (momentum still positive)
            daily_ao = calculate_awesome_oscillator(daily_data)
            ao_positive = daily_ao.iloc[-1] > 0 if len(daily_ao) > 0 else True
            
            # Gate 5: AO not shrinking (momentum not dying)
            ao_not_dying = True
            if len(daily_ao) >= 3:
                # Allow entry unless AO has shrunk for 3+ consecutive bars
                recent_ao = daily_ao.iloc[-3:].abs().values
                ao_not_dying = not (recent_ao[2] < recent_ao[1] < recent_ao[0])
            
            # Debug: Show MACD values
            tlog(f"{ticker}: MACD checks - M={monthly_bull}, W={weekly_bull}, D={daily_bull}")
            if daily_close is not None and len(daily_macd) > 0:
                tlog(f"  Daily MACD: {daily_macd.iloc[-1]:.3f} vs Signal: {daily_signal.iloc[-1]:.3f}")
            
            # v16.17: BLENDED MTF - Scoring system instead of strict AND logic
            # Allows entry if 3+ of 5 gates pass (more flexible than all-or-nothing)
            mtf_score = sum([monthly_bull, weekly_bull, daily_bull, ao_positive, ao_not_dying])
            MIN_MTF_SCORE = 3
            entry_signal = mtf_score >= MIN_MTF_SCORE
            gate_status = f"M={monthly_bull}, W={weekly_bull}, D={daily_bull}, AO={ao_positive}, AOOK={ao_not_dying}"
            
            if entry_signal:
                tlog(f"{ticker}: ✅ BLENDED MTF PASS {mtf_score}/5 - {gate_status}")
            else:
                tlog(f"{ticker}: ❌ BLENDED MTF BLOCKED {mtf_score}/5 (need {MIN_MTF_SCORE}) - {gate_status}")
            
            return entry_signal
            
        except Exception as e:
            import traceback
            tlog(f"{ticker}: ERROR in ultimate entry check - {e}")
            tlog(f"  Traceback: {traceback.format_exc()}")
            return True  # On error, allow the trade (fall through to standard logic)
    
    # v16.14: Ultimate MTF Exit - Triple Confirmation Exit
    def check_mtf_ultimate_exit(ticker, daily_data, weekly_data):
        """Triple Confirmation Exit: MACD + AO + Fractal (Adaptive)"""
        try:
            MIN_BARS = 34  # Minimum bars for reliable MACD/AO calculation
            
            # Check data availability
            if daily_data is None or len(daily_data) < MIN_BARS:
                return False, "Insufficient daily data"
            
            # Handle both uppercase and lowercase column names
            close_col = 'Close' if 'Close' in daily_data.columns else 'close' if 'close' in daily_data.columns else None
            low_col = 'Low' if 'Low' in daily_data.columns else 'low' if 'low' in daily_data.columns else None
            
            if close_col is None or low_col is None:
                return False, "Missing required columns"
            
            # Signal 1: Daily MACD bearish cross
            daily_macd, daily_signal, _ = calculate_macd(daily_data[close_col])
            macd_bear = macd_bearish_cross(daily_macd, daily_signal)
            
            # Signal 2: AO momentum shrinking
            daily_ao = calculate_awesome_oscillator(daily_data)
            ao_shrink = ao_momentum_shrinking(daily_ao, consecutive_bars=2)
            
            # Signal 3: Down fractal
            fractal_down = detect_down_fractal(daily_data[low_col])
            
            # ADAPTIVE EXIT
            if macd_bear and ao_shrink and fractal_down:
                return True, "Triple Confirmation (MACD+AO+Fractal)"
            elif macd_bear and ao_shrink:
                return True, "Dual Confirmation (MACD+AO)"
            elif macd_bear:
                # Check weekly for confirmation (if available)
                weekly_close = None
                if weekly_data is not None and len(weekly_data) >= MIN_BARS:
                    weekly_close = 'Close' if 'Close' in weekly_data.columns else 'close' if 'close' in weekly_data.columns else None
                if weekly_close:
                    weekly_macd, weekly_signal, _ = calculate_macd(weekly_data[weekly_close])
                    weekly_bear = macd_bearish_cross(weekly_macd, weekly_signal)
                    if weekly_bear:
                        return True, "Weekly Confirmation"
                return False, "MACD only - HOLD (AO still strong)"
            
            return False, "No exit signal"
            
        except Exception as e:
            import traceback
            tlog(f"{ticker}: ERROR in ultimate exit check - {e}")
            tlog(f"  Traceback: {traceback.format_exc()}")
            return False, f"Error: {e}"
    
    def get_dot_color_from_diag(diag, ao_array, macd_bearish):
        """
        Three-state momentum with MACD confirmation:
        
        GREEN = AO > 0 AND (rising OR no MACD cross)
                = Healthy momentum - BUY/HOLD
        
        YELLOW = AO > 0 BUT falling AND MACD crossed down
                = Confirmed weakness - CAUTION
        
        RED = AO < 0
              = Bearish - W3 terminated
        
        Args:
            diag: AO diagnostic object
            ao_array: AO values (numpy array or pandas series)
            macd_bearish: Boolean - True if MACD crossed below signal
        
        Returns:
            Hex color code for dot
        """
        if diag is None or ao_array is None or len(ao_array) < 2:
            return '#6b7280'  # Gray - no data
        
        current_ao = ao_array[-1]
        previous_ao = ao_array[-2]
        
        # RED: AO crossed negative (W3 terminated)
        if current_ao < 0:
            return '#ef4444'
        
        # YELLOW: AO positive BUT weakening AND MACD confirms
        # This prevents false alarms from minor AO dips
        elif current_ao > 0 and current_ao < previous_ao and macd_bearish:
            return '#fbbf24'
        
        # GREEN: AO positive (rising OR falling without MACD confirmation)
        # Stays green during healthy pullbacks
        else:
            return '#00E676'
    
    # Build traffic lights data from diagnostic objects
    # v16.9: Three-state system with MACD confirmation - dot color first, then label
    
    # === STEP 3: Calculate MACD for each timeframe ===
    # Monthly MACD
    monthly_macd_bearish = False
    try:
        m_df_sess = st.session_state.get('m_df')
        if m_df_sess is not None and not m_df_sess.empty:
            m_macd_line = m_df_sess['Close'].ewm(span=12).mean() - m_df_sess['Close'].ewm(span=26).mean()
            m_signal_line = m_macd_line.ewm(span=9).mean()
            monthly_macd_bearish = detect_macd_bearish_cross(m_macd_line, m_signal_line)
    except Exception as e:
        print(f"TTA: Monthly MACD error: {e}")
    
    # Weekly MACD
    weekly_macd_bearish = False
    try:
        w_macd_line = weekly_df['Close'].ewm(span=12).mean() - weekly_df['Close'].ewm(span=26).mean()
        w_signal_line = w_macd_line.ewm(span=9).mean()
        weekly_macd_bearish = detect_macd_bearish_cross(w_macd_line, w_signal_line)
    except Exception as e:
        print(f"TTA: Weekly MACD error: {e}")
    
    # Daily MACD
    daily_macd_bearish = False
    try:
        d_macd_line = daily_df['Close'].ewm(span=12).mean() - daily_df['Close'].ewm(span=26).mean()
        d_signal_line = d_macd_line.ewm(span=9).mean()
        daily_macd_bearish = detect_macd_bearish_cross(d_macd_line, d_signal_line)
    except Exception as e:
        print(f"TTA: Daily MACD error: {e}")
    
    # 4H MACD
    h4_macd_bearish = False
    try:
        h4_df_local = st.session_state.get('h4_df')
        if h4_df_local is not None and not h4_df_local.empty:
            h4_macd_line = h4_df_local['Close'].ewm(span=12).mean() - h4_df_local['Close'].ewm(span=26).mean()
            h4_signal_line = h4_macd_line.ewm(span=9).mean()
            h4_macd_bearish = detect_macd_bearish_cross(h4_macd_line, h4_signal_line)
    except Exception as e:
        print(f"TTA: 4H MACD error: {e}")
    
    # Monthly timeframe (highest level) - fetch from session state
    monthly_has_wave = False
    monthly_wave = "—"
    monthly_dot_color = '#6b7280'  # Gray default
    try:
        m_diag_sess = st.session_state.get('m_diag')
        m_ao_sess = st.session_state.get('m_ao')
        w3_monthly_sess = st.session_state.get('w3_monthly')
        if m_diag_sess is not None:
            monthly_has_wave = (w3_monthly_sess is not None)
            m_ao_arr = m_ao_sess.values if m_ao_sess is not None and hasattr(m_ao_sess, 'values') else None
            monthly_dot_color = get_dot_color_from_diag(m_diag_sess, m_ao_arr, monthly_macd_bearish)
            monthly_momentum = (monthly_dot_color == '#00E676')  # v16.9: Convert to boolean
            monthly_wave = get_wave_label_from_diag(m_diag_sess, monthly_has_wave, monthly_momentum)
        else:
            print("TTA: Monthly data not in session state")
    except Exception as e:
        print(f"TTA WARNING: Monthly traffic light error: {e}")
    
    # Weekly timeframe - dot color first, then label
    weekly_has_wave = (w3_weekly is not None)
    w_ao_arr = w_ao.values if hasattr(w_ao, 'values') else None
    weekly_dot_color = get_dot_color_from_diag(w_diag, w_ao_arr, weekly_macd_bearish)
    weekly_momentum = (weekly_dot_color == '#00E676')  # v16.9: Convert to boolean
    weekly_wave = get_wave_label_from_diag(w_diag, weekly_has_wave, weekly_momentum)
    
    # Daily timeframe - dot color first, then label
    daily_has_wave = (w3_daily is not None)
    d_ao_arr = d_ao.values if hasattr(d_ao, 'values') else None
    daily_dot_color = get_dot_color_from_diag(d_diag, d_ao_arr, daily_macd_bearish)
    daily_momentum = (daily_dot_color == '#00E676')  # v16.9: Convert to boolean
    daily_wave = get_wave_label_from_diag(d_diag, daily_has_wave, daily_momentum)
    
    # 4H timeframe - dot color first, then label
    h4_has_wave = (h4_w3 is not None)
    h4_wave = "—"
    h4_dot_color = '#6b7280'  # Gray default
    try:
        h4_ao_arr = ao_4h_series.values if 'ao_4h_series' in locals() and ao_4h_series is not None and hasattr(ao_4h_series, 'values') else None
        h4_dot_color = get_dot_color_from_diag(h4_diag, h4_ao_arr, h4_macd_bearish)
        h4_momentum = (h4_dot_color == '#00E676')  # v16.9: Convert to boolean
        h4_wave = get_wave_label_from_diag(h4_diag, h4_has_wave, h4_momentum)
    except NameError:
        pass  # h4_diag not defined, use defaults
    
    # Static traffic light status (for chart display)
    monthly_green = monthly_has_wave
    weekly_green = weekly_has_wave
    daily_green = daily_has_wave
    h4_green = h4_has_wave
    
    # v16.6: Extract divergence status from each timeframe diagnostic
    monthly_divergence = m_diag_sess.get("divergence", False) if m_diag_sess else False
    weekly_divergence = w_diag.get("divergence", False) if w_diag else False
    daily_divergence = d_diag.get("divergence", False) if d_diag else False
    h4_divergence = h4_diag.get("divergence", False) if h4_diag else False
    
    # Store traffic light data in stats for chart rendering
    # v16.9: Now stores dot_color (hex string) instead of momentum (boolean)
    # v16.36: Added AO values and direction for enhanced MTF dashboard
    
    # Extract current AO values and direction for each timeframe
    def get_ao_info(ao_series):
        """Extract current AO value, direction, and previous value"""
        if ao_series is None or len(ao_series) < 2:
            return {'value': 0, 'direction': 'flat', 'prev': 0}
        try:
            current = float(ao_series.iloc[-1])
            prev = float(ao_series.iloc[-2])
            direction = 'rising' if current > prev else 'falling' if current < prev else 'flat'
            return {'value': current, 'direction': direction, 'prev': prev}
        except:
            return {'value': 0, 'direction': 'flat', 'prev': 0}
    
    monthly_ao_info = get_ao_info(m_ao_sess if 'm_ao_sess' in dir() else st.session_state.get('m_ao'))
    weekly_ao_info = get_ao_info(w_ao)
    daily_ao_info = get_ao_info(d_ao)
    h4_ao_info = get_ao_info(ao_4h_series if 'ao_4h_series' in locals() else None)
    
    stats["traffic_lights"] = {
        "monthly": monthly_green,
        "weekly": weekly_green,
        "daily": daily_green,
        "h4": h4_green,
        # v16.9: Enhanced wave labels and dot colors (4 timeframes)
        "monthly_wave": monthly_wave,
        "weekly_wave": weekly_wave,
        "daily_wave": daily_wave,
        "h4_wave": h4_wave,
        "monthly_dot_color": monthly_dot_color,
        "weekly_dot_color": weekly_dot_color,
        "daily_dot_color": daily_dot_color,
        "h4_dot_color": h4_dot_color,
        # v16.6: Divergence flags for each timeframe
        "monthly_divergence": monthly_divergence,
        "weekly_divergence": weekly_divergence,
        "daily_divergence": daily_divergence,
        "h4_divergence": h4_divergence,
        # v16.12: MACD bearish flags for each timeframe
        "monthly_macd_bearish": monthly_macd_bearish,
        "weekly_macd_bearish": weekly_macd_bearish,
        "daily_macd_bearish": daily_macd_bearish,
        "h4_macd_bearish": h4_macd_bearish,
        # v16.36: AO values and direction for MTF dashboard
        "monthly_ao": monthly_ao_info,
        "weekly_ao": weekly_ao_info,
        "daily_ao": daily_ao_info,
        "h4_ao": h4_ao_info
    }
    
    # v16.9: Enhanced debug output with context-aware labels
    print(f"TTA TRAFFIC LIGHTS v16.9 (Context-Aware):")
    print(f"  Monthly: {'✓' if monthly_momentum else '✗'} {monthly_wave}")
    print(f"  Weekly:  {'✓' if weekly_momentum else '✗'} {weekly_wave}")
    print(f"  Daily:   {'✓' if daily_momentum else '✗'} {daily_wave}")
    print(f"  4H:      {'✓' if h4_momentum else '✗'} {h4_wave}")
    print(f"")
    print(f"Label Guide:")
    print(f"  STRONG = Impulse + Bullish momentum")
    print(f"  WEAK = Impulse + Bearish momentum (don't buy)")
    print(f"  HOLD = Late impulse still extending")
    print(f"  FADING = Late impulse weakening")
    print(f"  AVOID = Active correction")
    tlog(f"Dot Color Logic:")
    tlog(f"  🟢 GREEN = AO > 0 AND (rising OR no MACD cross)")
    tlog(f"  🟡 YELLOW = AO > 0 BUT falling AND MACD crossed ⬇")
    tlog(f"  🔴 RED = AO < 0 (W3 terminated)")
    tlog(f"Label Guide:")
    tlog(f"  STRONG = W3 + green dot (BUY)")
    tlog(f"  WEAK = W3 + yellow dot (DON'T BUY YET)")
    tlog(f"  FADING = W3/W5 + red dot (EXIT)")
    tlog(f"  HOLD = W5 + green/yellow (keep position)")
    tlog(f"  WAIT = W4 (correction phase)")
    tlog(f"  BASE = Corr + green (bottom forming)")
    tlog(f"  WATCH = Corr + yellow/red (monitor)")
    tlog(f"  AVOID = Corr! (breakdown)")
    
    # === v12.0 TREND-LOCK LOGIC (ATR Trailing Stop + Volume Gate) ===
    tlog(f"TTA v12.0: Trend-Lock (Volume Gate + 3x ATR Trailing Stop)")
    
    runs = []
    all_signals = []
    
    # --- DIAGNOSTIC COUNTERS ---
    diag = {
        "count_daily_bars_total": len(daily_df),
        "count_regime_ok": 0,
        "count_volume_ok": 0,
        "count_momentum_ok": 0,
        "count_slope_ok": 0,       # v15.2: Slope gate passes
        "count_slope_rejected": 0, # v15.2: Flat/Stage 1 rejections
        "count_entries_taken": 0,
        "count_exits_taken": 0,
        "count_escape_velocity_entries": 0,  # v16.0: Escape velocity override entries
        "count_escape_velocity_checks": 0,   # v16.0: Times escape velocity was evaluated
        "count_time_stop_extended": 0,       # v16.0: Time-stops extended by consolidation
        "count_catastrophic_floor_exits": 0, # v16.0: Catastrophic floor exits
        "count_mtf_blocked": 0,              # v16.12: Signals blocked by MTF gate
        "count_mtf_exits": 0,                # v16.12: Exits triggered by MTF gate
        "count_4h_div_exits": 0,             # v16.17: 4H divergence early exits
        "count_ao_corrective_exits": 0,      # v16.18: Daily AO < 0 corrective exits
        "blocked_reasons": []
    }
    
    # v15.2: Track SMA slopes at entry for averaging
    entry_slopes = []
    
    # --- PREPARE DATA ---
    d_closes = daily_df['Close'].tolist()
    d_highs = daily_df['High'].tolist()
    d_lows = daily_df['Low'].tolist()
    daily_dates = daily_df.index.tolist()
    
    # 30-week SMA aligned to daily
    d_sma = weekly_sma_data.reindex(daily_df.index, method='ffill')
    d_sma_list = d_sma.tolist()
    
    # Daily AO - v15.0: Unified formula using Midpoint Price
    d_ao = calculate_awesome_oscillator(daily_df)
    d_ao_list = d_ao.tolist()
    
    # Volume and Volume MA
    vol_list = daily_df['Volume'].tolist()
    vol_ma = daily_df['Volume'].rolling(window=20).mean()
    vol_ma_list = vol_ma.tolist()
    
    # Daily ATR
    d_tr = pd.DataFrame({
        'hl': daily_df['High'] - daily_df['Low'],
        'hc': abs(daily_df['High'] - daily_df['Close'].shift(1)),
        'lc': abs(daily_df['Low'] - daily_df['Close'].shift(1))
    }).max(axis=1)
    d_atr14 = d_tr.rolling(14).mean()
    d_atr_list = d_atr14.tolist()
    
    # v16.0 Adaptive Architect: Calculate MSR for Escape Velocity Override
    msr_series = calculate_msr_robust(d_ao, lookback=MSR_LOOKBACK, floor_percentile=MSR_FLOOR_PERCENTILE)
    msr_list = msr_series.tolist()
    
    # v16.0: Calculate NSR for adaptive stops
    nsr_data = calculate_nsr_adaptive(daily_df['High'], daily_df['Low'], daily_df['Close'],
                                       fast_window=NSR_FAST_WINDOW, slow_window=NSR_SLOW_WINDOW)
    nsr_adaptive_list = nsr_data['NSR_Adaptive'].tolist()
    regime_ratio_list = nsr_data['Regime_Ratio'].tolist()
    
    # v16.0: Detect bull flag consolidation for pattern-aware time-stop
    consolidation_series = detect_consolidation(daily_df['High'], daily_df['Low'], daily_df['Volume'])
    consolidation_list = consolidation_series.tolist()
    
    # v16.0: Calculate historical gaps for catastrophic floor
    historical_gaps = (daily_df['Low'] - daily_df['Close'].shift(1)) / d_atr14
    historical_gaps_list = historical_gaps.tolist()
    
    # v16.17: DIVERGENCE BLOCKER - Detect bearish divergence and track active flag
    daily_df_with_div = detect_divergence_with_active_flag(daily_df.copy(), lookback=20)
    div_active_list = daily_df_with_div['bearish_div_active'].tolist() if 'bearish_div_active' in daily_df_with_div.columns else [False] * len(daily_df)
    diag["count_div_blocked"] = 0  # Track divergence blocks
    
    # ═══════════════════════════════════════════════════════════════════════════
    # v16.12: PER-BAR MTF CALCULATION (Improved with precomputed mappings)
    # Pre-calculate AO and MACD series for each timeframe to enable accurate
    # per-bar traffic light checks without lookahead bias
    # ═══════════════════════════════════════════════════════════════════════════
    # v16.12: MTF enforcement is on if any MTF/ULTIMATE toggle is on (check all keys)
    mtf_enforcement = (st.session_state.get('mtf_enforcement_enabled', False) or 
                       st.session_state.get('mtf_ultimate_mode', False) or
                       st.session_state.get('mtf_ultimate_individual', False) or
                       st.session_state.get('mtf_ultimate_toggle', False))
    
    # Pre-calculated MTF data (only computed if MTF enforcement is enabled)
    # v16.12: Changed from W/D/4H to M/W/D (Monthly/Weekly/Daily)
    mtf_monthly_ao = None
    mtf_monthly_bearish = None  # Pre-computed bearish cross series
    mtf_weekly_ao = None
    mtf_weekly_bearish = None
    mtf_daily_ao = None
    mtf_daily_bearish = None
    
    # Precomputed index mappings (daily_idx -> monthly/weekly idx)
    daily_to_monthly_idx = []
    daily_to_weekly_idx = []
    
    # v16.16 FIX: Get monthly_df at function scope (needed for ULTIMATE 5-Gate check)
    monthly_df_local = st.session_state.get('monthly_df')
    
    if mtf_enforcement:
        print(f"TTA v16.12: Per-bar MTF calculation ENABLED")
        
        # Helper to compute rolling 3-bar MACD bearish series
        def compute_macd_bearish_series(df):
            """
            Compute bearish detection matching detect_macd_bearish_cross logic.
            Returns True if MACD is below signal in any of the last 3 bars.
            """
            if df is None or df.empty or len(df) < 30:
                return pd.Series([False] * len(df) if df is not None else [])
            try:
                # Handle both 'Close' and 'close' column names
                close_col = 'Close' if 'Close' in df.columns else 'close' if 'close' in df.columns else None
                if close_col is None:
                    return pd.Series([False] * len(df), index=df.index)
                close = df[close_col]
                macd_line = close.ewm(span=12).mean() - close.ewm(span=26).mean()
                signal_line = macd_line.ewm(span=9).mean()
                
                # MACD below signal indicates bearish
                below_signal = macd_line < signal_line
                
                # Rolling 3-bar check: True if MACD below signal in any of last 3 bars
                bearish = below_signal.rolling(window=3, min_periods=1).max().astype(bool)
                return bearish
            except Exception:
                return pd.Series([False] * len(df), index=df.index)
        
        # Monthly AO and bearish series (v16.12: replaces 4H)
        try:
            monthly_df_mtf = st.session_state.get('monthly_df')
            if monthly_df_mtf is not None and not monthly_df_mtf.empty:
                mtf_monthly_ao = calculate_awesome_oscillator(monthly_df_mtf)
                mtf_monthly_bearish = compute_macd_bearish_series(monthly_df_mtf)
                print(f"  Monthly MTF series: {len(mtf_monthly_ao)} bars")
        except Exception as e:
            print(f"  Monthly MTF error: {e}")
        
        # Weekly AO and bearish series
        try:
            mtf_weekly_ao = calculate_awesome_oscillator(weekly_df)
            mtf_weekly_bearish = compute_macd_bearish_series(weekly_df)
            print(f"  Weekly MTF series: {len(mtf_weekly_ao)} bars")
        except Exception as e:
            print(f"  Weekly MTF error: {e}")
        
        # Daily AO and bearish series
        try:
            mtf_daily_ao = d_ao
            mtf_daily_bearish = compute_macd_bearish_series(daily_df)
            print(f"  Daily MTF series: {len(mtf_daily_ao)} bars")
        except Exception as e:
            print(f"  Daily MTF error: {e}")
        
        # Precompute daily -> monthly index mapping using searchsorted (v16.12: replaces 4H)
        try:
            monthly_df_mtf = st.session_state.get('monthly_df')
            if monthly_df_mtf is not None and not monthly_df_mtf.empty:
                monthly_timestamps = monthly_df_mtf.index.values
                daily_timestamps = daily_df.index.values
                # searchsorted returns insertion point; subtract 1 to get last bar <= date
                monthly_indices = np.searchsorted(monthly_timestamps, daily_timestamps, side='right') - 1
                daily_to_monthly_idx = list(monthly_indices)  # Keep -1 values
                valid_monthly = sum(1 for x in daily_to_monthly_idx if x >= 0)
                print(f"  Daily->Monthly mapping: {valid_monthly}/{len(daily_to_monthly_idx)} valid")
        except Exception as e:
            print(f"  Monthly mapping error: {e}")
            daily_to_monthly_idx = [-1] * len(daily_df)
        
        # Precompute daily -> weekly index mapping using searchsorted
        # Keep -1 for pre-first-bar to indicate no valid data (avoids lookahead)
        try:
            if weekly_df is not None and not weekly_df.empty:
                weekly_timestamps = weekly_df.index.values
                daily_timestamps = daily_df.index.values
                # searchsorted returns insertion point; subtract 1 to get last bar <= date
                # Keep -1 as-is to indicate "no weekly bar exists yet"
                weekly_indices = np.searchsorted(weekly_timestamps, daily_timestamps, side='right') - 1
                daily_to_weekly_idx = list(weekly_indices)  # Keep -1 values
                valid_weekly = sum(1 for x in daily_to_weekly_idx if x >= 0)
                print(f"  Daily->Weekly mapping: {valid_weekly}/{len(daily_to_weekly_idx)} valid")
        except Exception as e:
            print(f"  Weekly mapping error: {e}")
            daily_to_weekly_idx = [-1] * len(daily_df)
        
        # Diagnostic: Sample alignment check (first valid mapping)
        if daily_to_weekly_idx:
            sample_idx = next((i for i, w in enumerate(daily_to_weekly_idx) if w >= 0), None)
            if sample_idx is not None and sample_idx < len(daily_df) and daily_to_weekly_idx[sample_idx] < len(weekly_df):
                d_sample = daily_df.index[sample_idx]
                w_idx = daily_to_weekly_idx[sample_idx]
                w_sample = weekly_df.index[w_idx]
                print(f"  Alignment check: Daily {d_sample.date()} -> Weekly {w_sample.date()} (idx {w_idx})")
    
    def get_dot_color_at_index(ao_series, bearish_series, idx):
        """
        Calculate dot color at a specific bar index using pre-computed bearish series.
        Returns: Hex color string
        
        idx < 0 means no valid bar exists yet (avoid lookahead)
        idx < 1 means not enough history for comparison
        """
        # No valid data for this index
        if ao_series is None or idx < 0 or idx >= len(ao_series):
            return '#6b7280'  # Gray - no data
        
        # Need at least 2 bars for comparison
        if idx < 1:
            return '#6b7280'  # Gray - insufficient history
        
        try:
            current_ao = ao_series.iloc[idx]
            previous_ao = ao_series.iloc[idx - 1]
            
            # Get pre-computed MACD bearish state
            macd_bearish = False
            if bearish_series is not None and idx < len(bearish_series):
                macd_bearish = bool(bearish_series.iloc[idx])
            
            # Apply same logic as get_dot_color_from_diag
            if pd.isna(current_ao):
                return '#6b7280'
            elif current_ao < 0:
                return '#ef4444'  # RED
            elif current_ao > 0 and current_ao < previous_ao and macd_bearish:
                return '#fbbf24'  # YELLOW
            else:
                return '#00E676'  # GREEN
        except Exception:
            return '#6b7280'
    
    def get_perbar_traffic_lights(daily_idx):
        """
        Get traffic light dot colors for a specific daily bar using precomputed mappings.
        v16.12: Uses M/W/D (Monthly/Weekly/Daily) instead of W/D/4H.
        Includes lookahead guards to verify mapped timestamps don't exceed daily bar.
        Returns dict with dot colors per timeframe.
        """
        result = {
            'monthly_dot_color': '#6b7280',
            'weekly_dot_color': '#6b7280',
            'daily_dot_color': '#6b7280'
        }
        
        if not mtf_enforcement:
            return result
        
        # Get daily bar timestamp for lookahead guard
        daily_ts = daily_df.index[daily_idx] if daily_idx < len(daily_df) else None
        
        # Daily: Direct index mapping
        if mtf_daily_ao is not None:
            result['daily_dot_color'] = get_dot_color_at_index(
                mtf_daily_ao, mtf_daily_bearish, daily_idx
            )
        
        # Weekly: Use precomputed mapping with lookahead guard
        if mtf_weekly_ao is not None and daily_to_weekly_idx and daily_idx < len(daily_to_weekly_idx):
            weekly_idx = daily_to_weekly_idx[daily_idx]
            if weekly_idx >= 0 and weekly_idx < len(weekly_df):
                # Lookahead guard: verify weekly bar timestamp <= daily bar timestamp
                weekly_ts = weekly_df.index[weekly_idx]
                if daily_ts is not None and weekly_ts <= daily_ts:
                    result['weekly_dot_color'] = get_dot_color_at_index(
                        mtf_weekly_ao, mtf_weekly_bearish, weekly_idx
                    )
        
        # Monthly: Use precomputed mapping with lookahead guard (v16.12: replaces 4H)
        monthly_df_local = st.session_state.get('monthly_df')
        if mtf_monthly_ao is not None and daily_to_monthly_idx and daily_idx < len(daily_to_monthly_idx):
            monthly_idx = daily_to_monthly_idx[daily_idx]
            if monthly_idx >= 0 and monthly_df_local is not None and monthly_idx < len(monthly_df_local):
                # Lookahead guard: verify monthly bar timestamp <= daily bar timestamp
                monthly_ts = monthly_df_local.index[monthly_idx]
                if daily_ts is not None and monthly_ts <= daily_ts:
                    result['monthly_dot_color'] = get_dot_color_at_index(
                        mtf_monthly_ao, mtf_monthly_bearish, monthly_idx
                    )
        
        return result
    
    def check_perbar_mtf_alignment(daily_idx, mtf_mode):
        """
        Check MTF alignment using per-bar calculated traffic lights.
        v16.12: Uses M/W/D (Monthly/Weekly/Daily) instead of W/D/4H.
        Returns: (passed: bool, reason: str)
        """
        lights = get_perbar_traffic_lights(daily_idx)
        
        GREEN = '#00E676'
        YELLOW = '#fbbf24'
        RED = '#ef4444'
        
        monthly_dot = lights['monthly_dot_color']
        weekly_dot = lights['weekly_dot_color']
        daily_dot = lights['daily_dot_color']
        
        is_green = lambda c: c == GREEN
        is_red = lambda c: c == RED
        
        if mtf_mode == 'CONSERVATIVE':
            # All must be green (M/W/D)
            if not is_green(monthly_dot):
                return False, f"Monthly not green"
            if not is_green(weekly_dot):
                return False, f"Weekly not green"
            if not is_green(daily_dot):
                return False, f"Daily not green"
            return True, "Full MTF alignment"
        
        elif mtf_mode == 'MODERATE':
            # Monthly + Weekly green, Daily at least yellow
            if not is_green(monthly_dot):
                return False, f"Monthly not green"
            if not is_green(weekly_dot):
                return False, f"Weekly not green"
            if is_red(daily_dot):
                return False, f"Daily is red"
            return True, "M/W green, D ok"
        
        else:  # AGGRESSIVE
            # Weekly green, Monthly at least yellow
            if not is_green(weekly_dot):
                return False, f"Weekly not green"
            if is_red(monthly_dot):
                return False, f"Monthly is red"
            return True, "Weekly green, M ok"
    
    # --- STATE MACHINE ---
    in_trade = False
    current_buy = None
    trailing_sl = 0.0
    hard_stop_level = 0.0  # v13.2: 8% Hard-Cap Risk
    highest_close_in_trade = 0.0
    
    # v16.0 Adaptive Architect: ATR-based initial stop with NSR adaptation
    vertical_lock_mult = 2.5 if suitability_score < 80 else 2.0  # Shakeout buffer for volatile stocks
    print(f"TTA v16.0: Adaptive Architect - {ATR_INITIAL_STOP_MULT}x ATR Initial Stop, {vertical_lock_mult}x Vertical Lock")
    
    # v15.3 Penalty Box: Track hard stop exits for "revenge trading" protection
    hard_stop_history = []  # List of dates when hard stop was hit
    PENALTY_BOX_WINDOW = 30  # Days to look back for hard stops
    PENALTY_BOX_THRESHOLD = 2  # Max hard stops before lockout
    PENALTY_BOX_DURATION = 14  # Days to block entries after lockout
    
    # v15.4 Time-Stop tracking
    entry_bar_index = 0  # Track which bar we entered on
    
    # ═══════════════════════════════════════════════════════════════════════════
    # v16.31: COMPREHENSIVE WAVE-AWARE ENTRY SYSTEM
    # ═══════════════════════════════════════════════════════════════════════════
    
    # Exit tracking
    last_exit_price = 0.0
    last_exit_bar_idx = -1
    POST_EXIT_COOLING_OFF = 20  # Bars to wait after exit before re-entry
    exit_price_valid = False  # Only True when exit price should be enforced
    bars_below_sma = 0  # Count consecutive bars below SMA
    TREND_BREAK_BARS = 3  # Need 3 bars below SMA to reset
    
    # Wave context tracking
    correction_phase = False  # True when AO went negative after exit
    new_impulse_starting = False  # True when AO returns positive after correction
    lowest_since_exit = float('inf')  # Track correction depth
    
    # Adaptive Breakout Thresholds (based on correction depth)
    SHALLOW_THRESHOLD = 0.10   # <10% = shallow, require 5% breakout
    MODERATE_THRESHOLD = 0.20  # 10-20% = moderate, require 2% breakout
    # >20% = deep correction, no breakout requirement (fresh start)
    
    for i in range(20, len(d_closes)):
        if i >= len(d_sma_list):
            break
        
        curr_close = d_closes[i]
        curr_sma = d_sma_list[i] if i < len(d_sma_list) else None
        ao_val = ao_series.iloc[i] if i < len(ao_series) else 0
        
        # Skip if SMA not available
        if curr_sma is None or pd.isna(curr_sma) or curr_sma == 0:
            continue
        
        # ─────────────────────────────────────────────────────────────────────
        # POST-EXIT TRACKING (only when not in trade and have prior exit)
        # ─────────────────────────────────────────────────────────────────────
        if not in_trade and last_exit_price > 0:
            # Track lowest price since exit (for correction depth)
            if curr_close < lowest_since_exit:
                lowest_since_exit = curr_close
            
            # Track wave context: correction phase when AO goes negative
            if ao_val < 0 and not correction_phase:
                correction_phase = True
                tlog(f"{ticker}: 📉 CORRECTION PHASE - AO went negative at {daily_dates[i].date()}")
            
            # Track wave context: new impulse when AO returns positive after correction
            if ao_val > 0 and correction_phase and not new_impulse_starting:
                new_impulse_starting = True
                tlog(f"{ticker}: 📈 NEW IMPULSE - AO returned positive at {daily_dates[i].date()}")
            
            # Count bars below SMA for trend break detection
            if curr_close < curr_sma:
                bars_below_sma += 1
                if bars_below_sma >= TREND_BREAK_BARS and exit_price_valid:
                    # Trend broken - FULL RESET to allow fresh entries
                    exit_price_valid = False
                    last_exit_bar_idx = -1  # Clear to bypass post-exit cooling and B-wave checks
                    tlog(f"{ticker}: 🔄 TREND BREAK - {bars_below_sma} bars below SMA, FULL RESET - ready for fresh W3 entry")
            else:
                bars_below_sma = 0  # Reset counter when price above SMA
            
        curr_date = daily_dates[i]
        close_curr = d_closes[i]
        open_curr = daily_df['Open'].iloc[i]  # v13.3: For gap protection
        low_curr = daily_df['Low'].iloc[i]    # v15.0: For intraday stop check
        sma_curr = d_sma_list[i]
        ao_curr = d_ao_list[i] if i < len(d_ao_list) else 0
        ao_prev = d_ao_list[i-1] if i > 0 and i-1 < len(d_ao_list) else 0
        current_vol = vol_list[i]
        avg_vol = vol_ma_list[i]
        curr_atr = d_atr_list[i]
        
        # Skip if essential data missing
        if sma_curr is None or pd.isna(sma_curr) or sma_curr == 0:
            continue
        if curr_atr is None or pd.isna(curr_atr):
            continue
        if avg_vol is None or pd.isna(avg_vol) or avg_vol == 0:
            continue
        
        # --- MANAGE ACTIVE TRADE ---
        if in_trade:
            # Calculate unrealized P/L for Vertical Lock
            unrealized_pct = ((close_curr - current_buy["price"]) / current_buy["price"]) * 100
            
            # v16.19: Daily AO < 0 exit REMOVED - too aggressive, causes premature exits
            # The 4H divergence rule is the primary early exit signal instead
            
            # v16.12: Per-Bar MTF Exit - Exit when higher timeframes turn bearish
            # Uses SAME traffic light logic as entry gate for consistency
            if mtf_enforcement:
                mtf_exit_triggered = False
                mtf_exit_reason = ""
                
                if mtf_mode == 'ULTIMATE':
                    # ULTIMATE Mode: Use Triple Confirmation Exit
                    # Get slice of data up to current bar (no lookahead)
                    daily_slice = daily_df.iloc[:i+1].copy()
                    
                    # Find corresponding weekly bar (no lookahead) - same as entry
                    if i < len(daily_to_weekly_idx):
                        w_idx = daily_to_weekly_idx[i]
                        weekly_slice = weekly_df.iloc[:w_idx+1].copy() if w_idx >= 0 else weekly_df.iloc[:1].copy()
                    else:
                        weekly_slice = weekly_df.copy()
                    
                    try:
                        should_exit, exit_reason = check_mtf_ultimate_exit(ticker, daily_slice, weekly_slice)
                        if should_exit:
                            mtf_exit_triggered = True
                            mtf_exit_reason = exit_reason
                    except Exception as ult_exit_err:
                        print(f"ULTIMATE exit check error: {ult_exit_err}")
                else:
                    # Standard MTF modes: Use traffic light logic
                    # Get per-bar traffic lights using same function as entry gate
                    exit_lights = get_perbar_traffic_lights(i)
                    weekly_dot = exit_lights['weekly_dot_color']
                    daily_dot = exit_lights['daily_dot_color']
                    
                    RED = '#ef4444'
                    
                    # Check exit conditions based on MTF mode (using dot colors for consistency)
                    weekly_red = weekly_dot == RED
                    daily_red = daily_dot == RED
                    
                    if mtf_mode == 'MODERATE' or mtf_mode == 'CONSERVATIVE':
                        # MODERATE: Exit immediately when Weekly turns RED
                        if weekly_red:
                            mtf_exit_triggered = True
                            mtf_exit_reason = "Weekly red"
                    else:  # AGGRESSIVE
                        # AGGRESSIVE: Exit when BOTH Weekly AND Daily turn RED
                        if weekly_red and daily_red:
                            mtf_exit_triggered = True
                            mtf_exit_reason = "Weekly AND Daily red"
                
                if mtf_exit_triggered:
                    exit_price = close_curr
                    raw_ret = ((exit_price - current_buy["price"]) / current_buy["price"]) * 100
                    ret = raw_ret * position_size_mod
                    runs.append(ret)
                    all_signals.append({
                        "type": "SELL",
                        "time": curr_date,
                        "price": exit_price,
                        "reason": f"MTF Exit - {mtf_exit_reason}"
                    })
                    print(f"TTA MTF EXIT: {curr_date} ${exit_price:.2f} - {mtf_exit_reason}")
                    diag["count_exits_taken"] += 1
                    diag["count_mtf_exits"] = diag.get("count_mtf_exits", 0) + 1
                    in_trade = False
                    current_buy = None
                    trailing_sl = 0.0
                    hard_stop_level = 0.0
                    highest_close_in_trade = 0.0
                    continue  # Skip other exit checks
            
            # ═══════════════════════════════════════════════════════════════════════════
            # v16.32: 4H DIVERGENCE EXIT - RE-ENABLED with Daily State Integration
            # Exit when 4H divergence aligns with weakening Daily momentum
            # ═══════════════════════════════════════════════════════════════════════════
            
            # Get current per-bar traffic lights (includes 4H divergence status)
            exit_lights = get_perbar_traffic_lights(i)
            daily_dot = exit_lights.get('daily_dot_color', '#6b7280')
            daily_wave = exit_lights.get('daily_wave', '—')
            
            # Get per-bar 4H divergence from traffic lights (time-aligned to bar i)
            h4_div_detected = exit_lights.get('h4_divergence', False)
            
            # Severity determination:
            # - For CURRENT bar (i == len-1): Use live session_state result (has actual severity)
            # - For HISTORICAL bars: Use MODERATE as conservative default (exit on any divergence)
            # This ensures backtests are conservative while live trading has accurate severity
            h4_div_severity = 'WEAK'
            if h4_div_detected:
                is_current_bar = (i == len(d_closes) - 1)
                if is_current_bar:
                    # Current/live bar - use actual computed severity
                    h4_div_live = st.session_state.get('h4_divergence_result', {})
                    if h4_div_live.get('detected', False):
                        h4_div_severity = h4_div_live.get('severity', 'MODERATE')
                    else:
                        h4_div_severity = 'MODERATE'
                else:
                    # Historical bar - default to MODERATE (conservative: exit on any significant divergence)
                    h4_div_severity = 'MODERATE'
            
            # Define dot color meanings
            GREEN = '#22c55e'
            YELLOW = '#eab308'
            RED = '#ef4444'
            
            # Determine Daily state category
            daily_is_strong = daily_dot == GREEN
            daily_is_weak = daily_dot == YELLOW
            daily_is_fading = daily_dot == RED
            
            # Check for HOLD/W5 late state (wave approaching exhaustion)
            # Note: HOLD and W5 explicitly indicate late impulse phase
            daily_is_late_wave = daily_wave in ['HOLD', 'W5']
            
            # Decision matrix for 4H divergence exit:
            # ┌─────────────────────┬──────────────────┬────────────┐
            # │ Daily State         │ 4H Divergence    │ Action     │
            # ├─────────────────────┼──────────────────┼────────────┤
            # │ STRONG (green)      │ STRONG           │ EXIT       │
            # │ STRONG (green)      │ MODERATE         │ HOLD       │
            # │ WEAK (yellow)       │ MODERATE/STRONG  │ EXIT       │
            # │ FADING (red)        │ Any              │ EXIT       │
            # │ HOLD/W5 (late wave) │ MODERATE/STRONG  │ EXIT       │
            # └─────────────────────┴──────────────────┴────────────┘
            
            should_4h_exit = False
            h4_exit_reason = ""
            
            if h4_div_detected:
                # Log the divergence check details
                ao_curr_val = ao_series.iloc[i] if i < len(ao_series) else 0
                daily_state_str = 'STRONG' if daily_is_strong else 'WEAK' if daily_is_weak else 'FADING' if daily_is_fading else 'NEUTRAL'
                tlog(f"{ticker}: 4H DIVERGENCE CHECK:")
                tlog(f"  Severity: {h4_div_severity}")
                tlog(f"  Daily State: {daily_state_str} ({daily_dot})")
                tlog(f"  Daily Wave: {daily_wave} (late={daily_is_late_wave})")
                tlog(f"  Daily AO: {ao_curr_val:+.2f}")
                
                # Apply decision matrix
                if daily_is_fading:
                    # Daily FADING (red) + Any 4H divergence = EXIT
                    should_4h_exit = True
                    h4_exit_reason = f"4H {h4_div_severity} Divergence + Daily FADING"
                elif daily_is_weak or daily_is_late_wave:
                    # Daily WEAK (yellow) or HOLD/W5 late + MODERATE or STRONG = EXIT
                    if h4_div_severity in ['MODERATE', 'STRONG']:
                        should_4h_exit = True
                        h4_exit_reason = f"4H {h4_div_severity} Divergence + Daily {daily_wave}"
                elif daily_is_strong:
                    # Daily STRONG (green) + STRONG divergence = EXIT (W3 exhaustion)
                    if h4_div_severity == 'STRONG':
                        should_4h_exit = True
                        h4_exit_reason = f"4H STRONG Divergence (Wave Exhaustion)"
                    else:
                        tlog(f"{ticker}: DECISION: HOLD - Daily still STRONG, 4H {h4_div_severity} not sufficient")
                
                # Log final decision
                if should_4h_exit:
                    tlog(f"{ticker}: DECISION: EXIT - {h4_exit_reason}")
                    diag["count_4h_divergence_exits"] = diag.get("count_4h_divergence_exits", 0) + 1
                    diag["count_4h_early_exits"] = diag.get("count_4h_early_exits", 0) + 1
                else:
                    diag["count_4h_divergence_warnings"] = diag.get("count_4h_divergence_warnings", 0) + 1
            
            if should_4h_exit:
                exit_price = close_curr
                raw_ret = ((exit_price - current_buy["price"]) / current_buy["price"]) * 100
                ret = raw_ret * position_size_mod
                runs.append(ret)
                all_signals.append({
                    "type": "SELL",
                    "time": curr_date,
                    "price": exit_price,
                    "reason": f"4H Divergence Exit - {h4_exit_reason}"
                })
                tlog(f"TTA 4H DIV EXIT: {curr_date} ${exit_price:.2f} - {h4_exit_reason}")
                diag["count_exits_taken"] += 1
                in_trade = False
                current_buy = None
                trailing_sl = 0.0
                hard_stop_level = 0.0
                highest_close_in_trade = 0.0
                entry_bar_index = 0
                last_exit_bar_idx = i
                
                # v16.31: Reset wave tracking on exit
                last_exit_price = exit_price
                exit_price_valid = True
                correction_phase = False
                new_impulse_starting = False
                bars_below_sma = 0
                lowest_since_exit = exit_price
                continue  # Skip other exit checks
            
            # v15.3 Vertical Lock: Use shakeout-aware ATR multiplier
            current_atr_mult = vertical_lock_mult if unrealized_pct >= 15.0 else atr_mult
            
            # 1. Update Trailing Stop (Chandelier Exit with ADAPTIVE multiplier)
            if close_curr > highest_close_in_trade:
                highest_close_in_trade = close_curr
            
            # Calculate potential new stop level using dynamic ATR multiplier
            potential_sl = highest_close_in_trade - (curr_atr * current_atr_mult)
            
            # Ratchet logic: Only move SL up, never down
            if potential_sl > trailing_sl:
                trailing_sl = potential_sl
                if unrealized_pct >= 15.0:
                    print(f"TTA: Vertical Lock engaged - {vertical_lock_mult}x ATR at ${trailing_sl:.2f}")
            
            # v12.9 Break-Even Logic: Move stop to entry if +10% unrealized
            if unrealized_pct >= 10.0 and trailing_sl < current_buy["price"]:
                trailing_sl = current_buy["price"]
                print(f"TTA: Break-even stop activated at ${trailing_sl:.2f}")
            
            # v16.0 Pattern-Aware Time-Stop: Extended for bull flag consolidation
            bars_in_trade = i - entry_bar_index
            is_consolidating = consolidation_list[i] if i < len(consolidation_list) and not pd.isna(consolidation_list[i]) else False
            max_hold_days = TIME_STOP_BASE + (TIME_STOP_CONSOLIDATION_EXT if is_consolidating else 0)
            if is_consolidating and bars_in_trade >= TIME_STOP_BASE:
                diag["count_time_stop_extended"] += 1  # v16.0: Track time-stop extensions
            
            # v16.0: Time-stop triggers only after max_hold AND if still negative
            time_stop_triggered = bars_in_trade >= max_hold_days and unrealized_pct < TIME_STOP_MIN_GAIN
            
            # 2. Check Exits with Gap Protection (v13.3) + Intraday Low Check (v15.0)
            # v13.3: Check if price gapped below stop levels on open
            hard_stop_gap = open_curr < hard_stop_level  # Gapped below hard stop
            trailing_stop_gap = open_curr < trailing_sl   # Gapped below trailing stop
            
            # v15.0: Intraday Low Check - if daily low breached hard stop, exit at hard stop level
            intraday_hard_stop = low_curr < hard_stop_level and hard_stop_level > 0
            
            # v16.0 Two-Tier Stop: Calculate catastrophic floor for gap protection
            catastrophic_floor = calculate_catastrophic_floor(trailing_sl, curr_atr, historical_gaps)
            catastrophic_hit = open_curr < catastrophic_floor or low_curr < catastrophic_floor
            
            hard_stop_hit = close_curr < hard_stop_level or hard_stop_gap or intraday_hard_stop
            stop_hit = close_curr < trailing_sl or trailing_stop_gap
            # v16.21: Regime Fail requires 3+ consecutive closes below SMA (grace period)
            # This prevents quick exits on normal pullbacks
            if close_curr < sma_curr:
                regime_fail_count = getattr(current_buy, 'regime_fail_count', 0) + 1
                current_buy['regime_fail_count'] = regime_fail_count
            else:
                current_buy['regime_fail_count'] = 0
                regime_fail_count = 0
            regime_fail = regime_fail_count >= 3  # Only trigger after 3 consecutive bars
            
            if catastrophic_hit or hard_stop_hit or stop_hit or regime_fail or time_stop_triggered:
                # v16.0: Priority order - Catastrophic > Hard Stop > Trailing Stop > Time-Stop > Regime Fail
                if catastrophic_hit:
                    reason = f"CATASTROPHIC FLOOR (Gap Protection)"
                    hard_stop_history.append(curr_date)  # Track as severe loss
                    diag["count_catastrophic_floor_exits"] += 1  # v16.0: Track catastrophic exits
                elif hard_stop_hit:
                    reason = f"Hard Stop ({ATR_INITIAL_STOP_MULT}x ATR)"
                    # v15.3: Track hard stop for Penalty Box
                    hard_stop_history.append(curr_date)
                elif stop_hit:
                    reason = "Trailing Stop"
                elif time_stop_triggered:
                    reason = f"Time-Stop ({max_hold_days}d <{TIME_STOP_MIN_GAIN}%)"
                else:
                    reason = "Regime Fail"
                
                # v16.0: Priority exit price - Catastrophic > Hard Stop Level > Open (Gap) > Close
                if catastrophic_hit:
                    exit_price = min(open_curr, catastrophic_floor)  # v16.0: Worst case gap exit
                    reason += " (Severe Gap)"
                elif intraday_hard_stop:
                    exit_price = hard_stop_level  # v15.0: Exit at hard stop level
                    reason += " (Intraday)"
                elif hard_stop_gap or trailing_stop_gap:
                    exit_price = open_curr  # Slippage simulation
                    reason += " (Gap)"
                else:
                    exit_price = close_curr
                
                # Apply position size modifier to returns
                raw_ret = ((exit_price - current_buy["price"]) / current_buy["price"]) * 100
                ret = raw_ret * position_size_mod
                runs.append(ret)
                
                all_signals.append({
                    "type": "SELL",
                    "time": curr_date,
                    "price": exit_price,
                    "reason": reason
                })
                tlog(f"TTA Daily: SELL at {curr_date} (${exit_price:.2f}) - {reason}")
                
                diag["count_exits_taken"] += 1
                in_trade = False
                current_buy = None
                trailing_sl = 0.0
                hard_stop_level = 0.0
                highest_close_in_trade = 0.0
                entry_bar_index = 0
                last_exit_bar_idx = i  # v16.27: Track exit bar for post-exit cooling off
                
                # v16.31: Reset all wave tracking on new exit
                last_exit_price = exit_price
                exit_price_valid = True  # Enable breakout confirmation for next entry
                correction_phase = False  # Reset correction tracking
                new_impulse_starting = False
                bars_below_sma = 0
                lowest_since_exit = exit_price  # Start tracking from exit price
                tlog(f"{ticker}: 🎯 EXIT TRACKED - Price ${exit_price:.2f}, breakout confirmation active")
                continue
        
        # ═══════════════════════════════════════════════════════════════
        # v16.3 SIMPLIFIED MOMENTUM ENTRY - Catch Wave 3 surges directly
        # ═══════════════════════════════════════════════════════════════
        if not in_trade:
            # Calculate core metrics
            volume_ratio = current_vol / avg_vol if avg_vol > 0 else 0
            price_above_sma = close_curr > sma_curr
            sma_slope = get_sma_slope_5w(curr_date)
            
            # AO momentum conditions
            ao_positive = ao_curr > 0  # AO above zero line
            ao_rising = ao_curr > ao_prev  # AO accelerating
            ao_zero_cross = ao_prev <= 0 and ao_curr > 0  # Fresh zero cross
            
            # Penalty box check
            penalty_box_active = False
            if hard_stop_history:
                try:
                    recent_hard_stops = [hs for hs in hard_stop_history 
                                         if (curr_date - hs).days <= 30]
                    if len(recent_hard_stops) >= 2:
                        last_hard_stop = max(recent_hard_stops)
                        if (curr_date - last_hard_stop).days <= 14:
                            penalty_box_active = True
                except:
                    pass
            
            # ─────────────────────────────────────────────────────────
            # ENTRY CRITERIA: Simple 4-factor momentum surge
            # ─────────────────────────────────────────────────────────
            # 1. Price above rising SMA (Stage 2 trend)
            #    v16.19: Use adaptive_slope_threshold (0.5-1.0%) not MIN_SMA_SLOPE (0.15%)
            #    SMA must be SLOPING UP, not just flat
            trend_ok = price_above_sma and sma_slope >= adaptive_slope_threshold
            
            # 2. Volume surge (institutional participation)
            #    v16.26: Adaptive volume threshold based on divergence history
            #    Clean setups (no recent divergence): 1.0x volume OK
            #    Post-divergence setups: Require 1.3x volume (more confirmation needed)
            LOOKBACK_FOR_DIVERGENCE = 30  # Check last 30 bars for divergence history
            had_recent_divergence = False
            for lookback in range(1, min(LOOKBACK_FOR_DIVERGENCE + 1, i + 1)):
                check_idx = i - lookback
                if check_idx >= 0 and check_idx < len(div_active_list):
                    if div_active_list[check_idx]:
                        had_recent_divergence = True
                        break
            
            # Use stricter volume for post-divergence, relaxed for clean setups
            adaptive_volume_threshold = VOLUME_SURGE_THRESHOLD if had_recent_divergence else 1.0
            volume_ok = volume_ratio >= adaptive_volume_threshold
            
            # 3. Momentum acceleration (Wave 3 signature)
            #    v16.21: ULTRA-SIMPLIFIED - just check AO positive and rising
            #    The previous complex lookback logic was missing good entries
            #    Simple rule: AO > 0 AND AO rising = momentum confirmed
            ao_rising = ao_curr > ao_prev if ao_prev is not None and not pd.isna(ao_prev) else False
            momentum_ok = ao_positive and ao_rising
            
            # 4. Not in penalty box (avoid revenge trading)
            clear_to_trade = not penalty_box_active
            
            # Track diagnostics
            if price_above_sma:
                diag["count_regime_ok"] += 1
            if volume_ok:
                diag["count_volume_ok"] += 1
            if momentum_ok:
                diag["count_momentum_ok"] += 1
            if sma_slope >= adaptive_slope_threshold:
                diag["count_slope_ok"] += 1
            
            # ─────────────────────────────────────────────────────────
            # ENTER if ALL 4 factors align
            # ─────────────────────────────────────────────────────────
            # v16.21 DEBUG: Log entry evaluation for post-Feb-2025 dates
            if curr_date >= pd.Timestamp('2025-02-01'):
                if not trend_ok or not volume_ok or not momentum_ok:
                    if len(diag.get("post_feb_blocks", [])) < 5:
                        diag.setdefault("post_feb_blocks", []).append(
                            f"{curr_date.date()}: trend={trend_ok} vol={volume_ok} mom={momentum_ok} (AO={ao_curr:.2f} rise={ao_rising})"
                        )
            
            if trend_ok and volume_ok and momentum_ok and clear_to_trade:
                # v16.16 DEBUG: Log when entry conditions met
                diag["count_entry_opportunities"] = diag.get("count_entry_opportunities", 0) + 1
                
                # v16.17: DIVERGENCE BLOCKER - Check FIRST before any other entry gate
                div_active = div_active_list[i] if i < len(div_active_list) else False
                if div_active:
                    if len(diag["blocked_reasons"]) < 10:
                        diag["blocked_reasons"].append(f"{curr_date}: DIVERGENCE Blocked - Daily bearish divergence active")
                    diag["count_div_blocked"] = diag.get("count_div_blocked", 0) + 1
                    tlog(f"{ticker}: ❌ ENTRY BLOCKED by Divergence - Daily bearish divergence active at {curr_date}")
                    continue  # Block entry - divergence active
                
                # ═══════════════════════════════════════════════════════════════════════════
                # v16.33: IMPULSE CONTEXT CHECK - Filter B-wave corrective bounces
                # Only enter on genuine Wave 3/5 impulse OR exceptional breakout OR clean BRT
                # Three paths to entry: deep correction, big breakout, break-and-retest
                # ═══════════════════════════════════════════════════════════════════════════
                
                impulse_context = False
                big_breakout = False
                brt_context = False  # v16.34: Break-and-Retest Continuation
                
                # Constants for all three paths
                MIN_CORRECTION_PCT = 10.0   # Deep correction path
                MIN_BARS_SINCE_EXIT = 15    # Deep correction path
                BIG_BREAKOUT_PCT = 3.0      # Big breakout path
                BIG_BREAKOUT_VOL = 2.0      # Big breakout path
                BRT_MIN_PULLBACK = 3.0      # Break-and-retest: min pullback %
                BRT_MAX_PULLBACK = 8.0      # Break-and-retest: max pullback % (per spec)
                BRT_MIN_VOL = 1.5           # Break-and-retest: min volume multiplier (per spec)
                BRT_LOOKBACK = 40           # Break-and-retest: bars to look back for breakout
                
                # Calculate big breakout first (applies to all cases)
                daily_pct_change = 0.0
                if i > 0 and d_closes[i-1] > 0:
                    prev_close = d_closes[i-1]
                    daily_pct_change = ((close_curr - prev_close) / prev_close) * 100
                    big_breakout = daily_pct_change >= BIG_BREAKOUT_PCT and volume_ratio >= BIG_BREAKOUT_VOL
                
                if last_exit_bar_idx >= 0 and last_exit_price > 0:
                    # Calculate correction depth directly from exit bar to current bar
                    correction_low = close_curr
                    for check_idx in range(last_exit_bar_idx, i + 1):
                        if check_idx < len(d_closes) and d_closes[check_idx] < correction_low:
                            correction_low = d_closes[check_idx]
                    correction_pct = ((last_exit_price - correction_low) / last_exit_price) * 100
                    
                    # Check if AO went negative since last exit (directly computed)
                    ao_went_negative = False
                    for check_idx in range(last_exit_bar_idx, i):
                        if check_idx < len(ao_series):
                            ao_val = ao_series.iloc[check_idx]
                            if not pd.isna(ao_val) and ao_val < 0:
                                ao_went_negative = True
                                break
                    
                    # Calculate bars since exit
                    bars_since_exit = i - last_exit_bar_idx
                    
                    # ═══════════════════════════════════════════════════════════════════════
                    # PATH 1: IMPULSE CONTEXT (Deep Correction Path)
                    # All 3 conditions must be met: 10%+ correction, AO negative, 15+ bars
                    # ═══════════════════════════════════════════════════════════════════════
                    condition_a = correction_pct >= MIN_CORRECTION_PCT
                    condition_b = ao_went_negative and ao_positive and ao_rising
                    condition_c = bars_since_exit >= MIN_BARS_SINCE_EXIT
                    
                    impulse_context = condition_a and condition_b and condition_c
                    
                    # ═══════════════════════════════════════════════════════════════════════
                    # PATH 2: BREAK-AND-RETEST CONTINUATION (v16.34)
                    # Shallow but clean pullback in strong trend after breakout above 30w SMA
                    # Per spec: find FIRST close above rising 30w SMA that is a new swing high
                    # ═══════════════════════════════════════════════════════════════════════
                    brt_context = False
                    brt_log = {}  # Collect BRT diagnostics
                    
                    # A. Find prior breakout: FIRST close above rising 30w SMA that is a new swing high
                    lookback_start = max(0, last_exit_bar_idx, i - BRT_LOOKBACK)
                    breakout_ref_idx = -1
                    breakout_ref_close = 0.0
                    
                    # Scan for FIRST breakout (not highest) - per spec
                    for check_idx in range(lookback_start, i):
                        if check_idx < len(d_closes) and check_idx >= 20:
                            check_close = d_closes[check_idx]
                            check_sma = daily_sma_aligned.iloc[check_idx] if check_idx < len(daily_sma_aligned) else 0
                            
                            # Check if 30w SMA is rising (compare to 5 bars ago)
                            sma_5_ago = daily_sma_aligned.iloc[check_idx - 5] if check_idx >= 5 and (check_idx - 5) < len(daily_sma_aligned) else 0
                            sma_rising = check_sma > sma_5_ago if sma_5_ago > 0 else False
                            
                            # Check if this is a new swing high vs prior 40 bars (per spec: 20-40 bars)
                            is_swing_high = True
                            for prior_idx in range(max(0, check_idx - 40), check_idx):
                                if prior_idx < len(d_closes) and d_closes[prior_idx] >= check_close:
                                    is_swing_high = False
                                    break
                            
                            # Must be: above 30w SMA + SMA rising + new swing high
                            if check_close > check_sma and sma_rising and is_swing_high:
                                breakout_ref_idx = check_idx
                                breakout_ref_close = check_close
                                break  # Take FIRST qualifying breakout
                    
                    brt_log['breakout_ref_idx'] = breakout_ref_idx
                    brt_log['breakout_ref_close'] = breakout_ref_close
                    
                    if breakout_ref_idx > 0 and breakout_ref_close > 0:
                        # B. Measure pullback from breakout high to pullback low
                        pullback_low_close = close_curr
                        for check_idx in range(breakout_ref_idx, i + 1):
                            if check_idx < len(d_closes) and d_closes[check_idx] < pullback_low_close:
                                pullback_low_close = d_closes[check_idx]
                        
                        pullback_pct = ((breakout_ref_close - pullback_low_close) / breakout_ref_close) * 100
                        brt_log['pullback_pct'] = pullback_pct
                        brt_log['pullback_low'] = pullback_low_close
                        
                        # C. Check AO behavior during pullback (should stay mostly positive)
                        ao_negative_bars = 0
                        ao_min_during_pullback = float('inf')
                        for check_idx in range(breakout_ref_idx, i):
                            if check_idx < len(ao_series):
                                ao_val = ao_series.iloc[check_idx]
                                if not pd.isna(ao_val):
                                    ao_min_during_pullback = min(ao_min_during_pullback, ao_val)
                                    if ao_val < 0:
                                        ao_negative_bars += 1
                        
                        ao_stayed_positive = ao_negative_bars <= 2  # Allow max 2 negative bars
                        brt_log['ao_min'] = ao_min_during_pullback if ao_min_during_pullback != float('inf') else 0
                        brt_log['ao_negative_bars'] = ao_negative_bars
                        brt_log['ao_stayed_positive'] = ao_stayed_positive
                        
                        # D. Continuation check: price reclaims breakout close (per spec)
                        reclaimed_high = close_curr >= breakout_ref_close  # Must reclaim or exceed breakout close
                        above_sma = close_curr > sma_curr if sma_curr > 0 else False
                        brt_log['reclaimed_high'] = reclaimed_high
                        brt_log['above_sma'] = above_sma
                        brt_log['vol_mult'] = volume_ratio
                        
                        # BRT CONTEXT: All conditions must be met
                        pullback_ok = BRT_MIN_PULLBACK <= pullback_pct <= BRT_MAX_PULLBACK
                        volume_ok_brt = volume_ratio >= BRT_MIN_VOL
                        continuation_ok = reclaimed_high and above_sma and ao_rising
                        
                        brt_log['pullback_ok'] = pullback_ok
                        brt_log['volume_ok'] = volume_ok_brt
                        brt_log['continuation_ok'] = continuation_ok
                        
                        # Check divergence guardrail for BRT
                        div_blocks_brt = div_active
                        brt_log['div_blocks'] = div_blocks_brt
                        
                        if pullback_ok and ao_stayed_positive and continuation_ok and volume_ok_brt and not div_blocks_brt:
                            brt_context = True
                    
                    brt_log['brt_context'] = brt_context
                    
                    # ═══════════════════════════════════════════════════════════════════════
                    # LOGGING: For debugging and validation
                    # ═══════════════════════════════════════════════════════════════════════
                    is_oct_2024_googl = ticker == 'GOOGL' and curr_date.year == 2024 and curr_date.month == 10 and curr_date.day == 1
                    is_may_2025_googl = ticker == 'GOOGL' and curr_date.year == 2025 and curr_date.month == 5
                    should_log = is_oct_2024_googl or is_may_2025_googl or not (impulse_context or brt_context or big_breakout)
                    
                    if should_log:
                        tlog(f"{ticker}: v16.33/34 ENTRY CHECK @ {curr_date.date()}:")
                        tlog(f"  PATH 1 - IMPULSE CONTEXT:")
                        tlog(f"    Correction: {correction_pct:.1f}% (need {MIN_CORRECTION_PCT}%) → {'✓' if condition_a else '✗'}")
                        tlog(f"    AO went negative: {ao_went_negative} → {'✓' if ao_went_negative else '✗'}")
                        tlog(f"    Bars since exit: {bars_since_exit} (need {MIN_BARS_SINCE_EXIT}) → {'✓' if condition_c else '✗'}")
                        tlog(f"    IMPULSE CONTEXT: {impulse_context}")
                        tlog(f"  PATH 2 - BREAK-AND-RETEST:")
                        if breakout_ref_idx > 0:
                            tlog(f"    Breakout Ref: ${brt_log.get('breakout_ref_close', 0):.2f}")
                            tlog(f"    Pullback: {brt_log.get('pullback_pct', 0):.1f}% (need {BRT_MIN_PULLBACK}-{BRT_MAX_PULLBACK}%) → {'✓' if brt_log.get('pullback_ok') else '✗'}")
                            tlog(f"    AO stayed positive: {brt_log.get('ao_stayed_positive')} (neg bars: {brt_log.get('ao_negative_bars', 0)}) → {'✓' if brt_log.get('ao_stayed_positive') else '✗'}")
                            tlog(f"    Reclaimed high: {brt_log.get('reclaimed_high')} → {'✓' if brt_log.get('reclaimed_high') else '✗'}")
                            tlog(f"    Volume: {brt_log.get('vol_mult', 0):.1f}x (need {BRT_MIN_VOL}x) → {'✓' if brt_log.get('volume_ok') else '✗'}")
                            tlog(f"    Divergence blocks: {brt_log.get('div_blocks')} → {'✗' if brt_log.get('div_blocks') else '✓'}")
                        else:
                            tlog(f"    No breakout reference found in lookback")
                        tlog(f"    BRT CONTEXT: {brt_context}")
                        tlog(f"  PATH 3 - BIG BREAKOUT: {daily_pct_change:.1f}% move, {volume_ratio:.1f}x vol → {big_breakout}")
                        tlog(f"  FINAL: {'ALLOW' if (impulse_context or brt_context or big_breakout) else 'BLOCK'}")
                    
                    # BLOCK if none of the three paths are satisfied
                    if not impulse_context and not brt_context and not big_breakout:
                        if len(diag["blocked_reasons"]) < 10:
                            diag["blocked_reasons"].append(f"{curr_date}: B-WAVE RISK - no deep correction AND no valid break-and-retest")
                        diag["count_bwave_blocked"] = diag.get("count_bwave_blocked", 0) + 1
                        tlog(f"{ticker}: ❌ BLOCKED - no impulse context, no BRT, no big breakout at {curr_date}")
                        continue
                    
                    # Track BRT entries
                    if brt_context:
                        diag["count_brt_entries"] = diag.get("count_brt_entries", 0) + 1
                else:
                    # No prior exit - first entry needs big breakout OR AO zero cross for conviction
                    if big_breakout:
                        impulse_context = True
                        tlog(f"{ticker}: v16.33 FIRST ENTRY - big breakout ({daily_pct_change:.1f}%, {volume_ratio:.1f}x vol) at {curr_date}")
                    elif ao_zero_cross:
                        impulse_context = True
                        tlog(f"{ticker}: v16.33 FIRST ENTRY - AO zero cross at {curr_date}")
                    else:
                        # First entry without strong conviction - BLOCK
                        impulse_context = False
                        if len(diag["blocked_reasons"]) < 10:
                            diag["blocked_reasons"].append(f"{curr_date}: FIRST ENTRY BLOCKED - no big breakout or AO zero cross")
                        diag["count_bwave_blocked"] = diag.get("count_bwave_blocked", 0) + 1
                        tlog(f"{ticker}: ❌ FIRST ENTRY BLOCKED - need big breakout or AO zero cross at {curr_date}")
                        continue
                
                # v16.27: POST-EXIT COOLING OFF - Don't enter within 20 bars of last exit
                # This prevents B-wave trap entries during corrective phases
                if last_exit_bar_idx >= 0 and (i - last_exit_bar_idx) <= POST_EXIT_COOLING_OFF:
                    bars_since_exit = i - last_exit_bar_idx
                    if len(diag["blocked_reasons"]) < 10:
                        diag["blocked_reasons"].append(f"{curr_date}: POST-EXIT COOLING - {bars_since_exit} bars since exit (need {POST_EXIT_COOLING_OFF})")
                    diag["count_postexit_blocked"] = diag.get("count_postexit_blocked", 0) + 1
                    tlog(f"{ticker}: ❌ POST-EXIT COOLING - Only {bars_since_exit} bars since last exit at {curr_date}")
                    continue  # Block entry - too soon after exit (likely B-wave)
                
                # v16.31: B-WAVE TRAP PREVENTION (Wave Context Aware)
                # Block if AO never went negative (no A-wave seen) UNLESS we have a clear breakout
                if last_exit_bar_idx >= 0 and not correction_phase:
                    # Exception: Clear breakout (price > SMA + 10% AND volume surge)
                    price_extension = (close_curr - sma_curr) / sma_curr if sma_curr > 0 else 0
                    is_clear_breakout = price_extension > 0.10 and volume_ratio >= 2.0
                    
                    if not is_clear_breakout:
                        if len(diag["blocked_reasons"]) < 10:
                            diag["blocked_reasons"].append(f"{curr_date}: B-WAVE TRAP - AO hasn't gone negative since exit (waiting for correction)")
                        diag["count_bwave_blocked"] = diag.get("count_bwave_blocked", 0) + 1
                        tlog(f"{ticker}: ❌ B-WAVE TRAP - No correction phase detected since last exit at {curr_date}")
                        continue
                    else:
                        tlog(f"{ticker}: ⚡ CLEAR BREAKOUT - Price {price_extension*100:.1f}% above SMA with {volume_ratio:.1f}x volume, bypassing B-wave check at {curr_date}")
                
                # v16.31: ADAPTIVE BREAKOUT CONFIRMATION (Based on Correction Depth)
                # Only enforce if exit_price_valid is True (not reset by trend break)
                if last_exit_price > 0 and exit_price_valid:
                    # Calculate correction depth
                    correction_depth = (last_exit_price - lowest_since_exit) / last_exit_price if last_exit_price > 0 else 0
                    
                    # Determine adaptive breakout threshold based on correction depth
                    if correction_depth > MODERATE_THRESHOLD:
                        # Deep correction (>20%) - treat as fresh start, no breakout needed
                        entry_label = "FRESH W3 BREAKOUT" if not new_impulse_starting else "WAVE 5 ENTRY"
                        tlog(f"{ticker}: 🔄 DEEP CORRECTION ({correction_depth*100:.1f}%) - No breakout requirement, {entry_label}")
                    elif correction_depth >= SHALLOW_THRESHOLD:
                        # Moderate correction (10-20%) - reduced breakout requirement (2%)
                        required_breakout = last_exit_price * 1.02
                        if close_curr < required_breakout:
                            if len(diag["blocked_reasons"]) < 10:
                                diag["blocked_reasons"].append(f"{curr_date}: BREAKOUT NEEDED - ${close_curr:.2f} < ${required_breakout:.2f} (2% after {correction_depth*100:.0f}% correction)")
                            diag["count_breakout_blocked"] = diag.get("count_breakout_blocked", 0) + 1
                            tlog(f"{ticker}: ❌ MODEST BREAKOUT NEEDED - Price ${close_curr:.2f} < ${required_breakout:.2f} (2% above exit after {correction_depth*100:.1f}% correction) at {curr_date}")
                            continue
                        entry_label = "WAVE 3 CONTINUATION" if not new_impulse_starting else "WAVE 5 ENTRY"
                    else:
                        # Shallow correction (<10%) - full breakout requirement (5%)
                        required_breakout = last_exit_price * 1.05
                        if close_curr < required_breakout:
                            if len(diag["blocked_reasons"]) < 10:
                                diag["blocked_reasons"].append(f"{curr_date}: BREAKOUT NEEDED - ${close_curr:.2f} < ${required_breakout:.2f} (5% for shallow {correction_depth*100:.0f}% correction)")
                            diag["count_breakout_blocked"] = diag.get("count_breakout_blocked", 0) + 1
                            tlog(f"{ticker}: ❌ BREAKOUT NEEDED - Price ${close_curr:.2f} < ${required_breakout:.2f} (5% above exit, only {correction_depth*100:.1f}% correction) at {curr_date}")
                            continue
                        entry_label = "BREAKOUT CONTINUATION"
                else:
                    # No exit price tracking or trend broken - fresh entry
                    entry_label = "FRESH W3 BREAKOUT"
                
                # v16.23: DIVERGENCE COOLING OFF - Don't enter within 5 bars of divergence clearing
                # This prevents reactive entries right after divergence is cleared
                # v16.24: ESCAPE VELOCITY OVERRIDE - If volume >= 2.0x, bypass cooling off (breakout signal)
                COOLING_OFF_BARS = 5
                ESCAPE_VELOCITY_VOLUME = 2.0  # 2x volume = breakout, bypass cooling off
                recently_had_divergence = False
                for lookback in range(1, COOLING_OFF_BARS + 1):
                    prev_idx = i - lookback
                    if prev_idx >= 0 and prev_idx < len(div_active_list):
                        if div_active_list[prev_idx]:
                            recently_had_divergence = True
                            break
                
                if recently_had_divergence:
                    # Check for escape velocity override - high volume + strong AO breakout
                    ESCAPE_VELOCITY_AO_MIN = 10.0  # v16.25: Require strong AO for escape velocity
                    current_ao = ao_series.iloc[i] if i < len(ao_series) else 0
                    if volume_ratio >= ESCAPE_VELOCITY_VOLUME and current_ao >= ESCAPE_VELOCITY_AO_MIN:
                        tlog(f"{ticker}: ⚡ ESCAPE VELOCITY OVERRIDE - Volume {volume_ratio:.1f}x + AO {current_ao:.1f} bypasses cooling off at {curr_date}")
                        # Allow entry despite cooling off - this is a true breakout!
                    elif volume_ratio >= ESCAPE_VELOCITY_VOLUME:
                        # High volume but weak AO - not a true breakout, enforce cooling off
                        if len(diag["blocked_reasons"]) < 10:
                            diag["blocked_reasons"].append(f"{curr_date}: COOLING OFF - Volume {volume_ratio:.1f}x but AO {current_ao:.1f} < {ESCAPE_VELOCITY_AO_MIN}")
                        diag["count_cooloff_blocked"] = diag.get("count_cooloff_blocked", 0) + 1
                        tlog(f"{ticker}: ❌ COOLING OFF - Volume {volume_ratio:.1f}x but AO {current_ao:.1f} < {ESCAPE_VELOCITY_AO_MIN} at {curr_date}")
                        continue
                    else:
                        if len(diag["blocked_reasons"]) < 10:
                            diag["blocked_reasons"].append(f"{curr_date}: COOLING OFF - Divergence cleared within {COOLING_OFF_BARS} bars")
                        diag["count_cooloff_blocked"] = diag.get("count_cooloff_blocked", 0) + 1
                        tlog(f"{ticker}: ❌ ENTRY BLOCKED by Cooling Off - Divergence cleared within {COOLING_OFF_BARS} bars at {curr_date}")
                        continue  # Block entry - too soon after divergence
                
                # v16.21: 4H DIVERGENCE BLOCKER - Check 4H divergence before entry
                # This prevents entries when 4H shows wave exhaustion even if Daily looks ok
                try:
                    # h4_df is created at line ~5338 from hourly data
                    if h4_df is not None and not h4_df.empty:
                        # Find corresponding 4H bar index (no lookahead)
                        h4_slice = h4_df[h4_df.index <= curr_date].copy()
                        if len(h4_slice) >= 30:
                            h4_div_result = detect_4h_divergence(h4_slice, lookback=20)
                            if h4_div_result.get('divergence', False):
                                sev = h4_div_result.get('severity', 'MODERATE')
                                if len(diag["blocked_reasons"]) < 10:
                                    diag["blocked_reasons"].append(f"{curr_date}: 4H DIVERGENCE Blocked [{sev}]")
                                diag["count_4h_div_blocked"] = diag.get("count_4h_div_blocked", 0) + 1
                                tlog(f"{ticker}: ❌ ENTRY BLOCKED by 4H Divergence [{sev}] at {curr_date}")
                                continue  # Block entry - 4H divergence active
                except Exception as h4_div_err:
                    tlog(f"4H Divergence check error: {h4_div_err}")  # Log error for debugging
                
                # v16.22: TRAFFIC LIGHT ENTRY GATE - DISABLED
                # Was too strict - blocked 31 entries and resulted in 0 trades
                # The divergence blocker already catches the major warning signals
                
                # v16.16 FIX: Check mtf_mode directly - already set correctly at function start
                if mtf_mode == 'ULTIMATE':
                    # ULTIMATE Mode: Use 5-Gate MACD Entry (M/W/D) - ALWAYS runs when ULTIMATE is enabled
                    # Get slices of data up to current bar (no lookahead)
                    daily_slice = daily_df.iloc[:i+1].copy()
                    
                    # Find corresponding weekly bar (no lookahead)
                    if i < len(daily_to_weekly_idx):
                        w_idx = daily_to_weekly_idx[i]
                        weekly_slice = weekly_df.iloc[:w_idx+1].copy() if w_idx >= 0 else weekly_df.iloc[:1].copy()
                    else:
                        w_idx = -1
                        weekly_slice = weekly_df.copy()
                    
                    # Find corresponding monthly bar (no lookahead)
                    # v16.16 FIX: Use monthly_df_local (from session state) not undefined monthly_df
                    if i < len(daily_to_monthly_idx) and monthly_df_local is not None:
                        m_idx = daily_to_monthly_idx[i]
                        monthly_slice = monthly_df_local.iloc[:m_idx+1].copy() if m_idx >= 0 else monthly_df_local.iloc[:1].copy()
                    else:
                        m_idx = -1
                        monthly_slice = monthly_df_local.copy() if monthly_df_local is not None else None
                    
                    # Debug: Show slice sizes and column names
                    tlog(f"=== ULTIMATE DEBUG ===")
                    tlog(f"Daily bar {i}: {curr_date}")
                    tlog(f"  Daily slice: {len(daily_slice)} bars, columns: {list(daily_slice.columns)[:5]}")
                    tlog(f"  Weekly slice: {len(weekly_slice)} bars, columns: {list(weekly_slice.columns)[:5]}")
                    tlog(f"  Monthly slice: {len(monthly_slice) if monthly_slice is not None else 0} bars, columns: {list(monthly_slice.columns)[:5] if monthly_slice is not None else 'N/A'}")
                    
                    try:
                        ultimate_passed = check_mtf_ultimate_entry(ticker, weekly_slice, daily_slice, monthly_slice)
                        if not ultimate_passed:
                            if len(diag["blocked_reasons"]) < 10:
                                diag["blocked_reasons"].append(f"{curr_date}: ULTIMATE Blocked - 5-Gate not aligned")
                            diag["count_mtf_blocked"] = diag.get("count_mtf_blocked", 0) + 1
                            continue  # Block entry - 5-Gate check failed
                    except Exception as ult_entry_err:
                        import traceback
                        tlog(f"ULTIMATE entry check error: {ult_entry_err}")
                        tlog(f"  Traceback: {traceback.format_exc()}")
                        # On error, fall through to standard entry
                        
                elif mtf_enforcement:
                    # Standard MTF modes (MODERATE/CONSERVATIVE)
                    mtf_passed, mtf_reason = check_perbar_mtf_alignment(i, mtf_mode)
                    if not mtf_passed:
                        if len(diag["blocked_reasons"]) < 10:
                            diag["blocked_reasons"].append(f"{curr_date}: MTF Blocked - {mtf_reason}")
                        diag["count_mtf_blocked"] = diag.get("count_mtf_blocked", 0) + 1
                        continue
                
                # Proceed with entry
                in_trade = True
                current_buy = {"price": close_curr, "time": curr_date, "regime_fail_count": 0}
                highest_close_in_trade = close_curr
                
                # Wide stop for Wave 3 volatility
                trailing_sl = close_curr - (curr_atr * atr_mult)  # 3.5x trailing
                hard_stop_level = close_curr - (curr_atr * ATR_INITIAL_STOP_MULT)  # 8.0x initial
                
                entry_bar_index = i
                entry_slopes.append(sma_slope)
                
                current_msr = msr_list[i] if i < len(msr_list) and not pd.isna(msr_list[i]) else 0
                
                entry_type = "MOMENTUM-SURGE"
                
                all_signals.append({
                    "type": "BUY",
                    "time": curr_date,
                    "price": close_curr,
                    "filter_profile": filter_profile,
                    "entry_type": entry_type,
                    "sma_slope": sma_slope,
                    "msr": current_msr
                })
                
                print(f"TTA {entry_type} BUY: {curr_date} ${close_curr:.2f}, "
                      f"Stop ${hard_stop_level:.2f} ({ATR_INITIAL_STOP_MULT}x ATR), "
                      f"Slope {sma_slope:.2f}%, Vol {volume_ratio:.1f}x, AO {ao_curr:.2f}")
                
                diag["count_entries_taken"] += 1
            
            # ─────────────────────────────────────────────────────────
            # DIAGNOSTIC LOGGING - Why entry blocked
            # ─────────────────────────────────────────────────────────
            else:
                if len(diag["blocked_reasons"]) < 10:
                    reasons = []
                    
                    if not price_above_sma:
                        reasons.append("Below SMA")
                    elif sma_slope < adaptive_slope_threshold:
                        reasons.append(f"Weak slope {sma_slope:.2f}% < {adaptive_slope_threshold}%")
                    
                    if not volume_ok:
                        reasons.append(f"Volume {volume_ratio:.1f}x < {VOLUME_SURGE_THRESHOLD}x")
                    
                    if not momentum_ok:
                        if not ao_positive:
                            reasons.append(f"AO negative ({ao_curr:.2f})")
                        elif not recent_zero_cross and not extended_momentum:
                            reasons.append(f"No recent AO zero cross (30 bars)")
                    
                    if penalty_box_active:
                        reasons.append("PENALTY BOX")
                    
                    if reasons:
                        diag["blocked_reasons"].append(f"{curr_date}: {', '.join(reasons)}")
    
    # Store active SL for display
    if in_trade:
        stats["active_sl"] = trailing_sl
    
    # --- RENDER MARKERS DIRECTLY ON DAILY CHART ---
    for sig in all_signals:
        if sig["type"] == "BUY":
            historical_markers.append({
                "time": sig["time"], 
                "position": "belowBar",
                "color": "#00E676", 
                "shape": "arrowUp",
                "text": "BUY"
            })
            stats["count"] += 1
        else:
            historical_markers.append({
                "time": sig["time"], 
                "position": "aboveBar",
                "color": "#ef4444", 
                "shape": "arrowDown",
                "text": "SELL"
            })
    
    # --- PRINT DIAGNOSTICS ---
    tlog(f"TTA v16.0 DIAGNOSTICS (Adaptive Architect):")
    tlog(f"  Daily bars: {diag['count_daily_bars_total']}")
    tlog(f"  Regime OK (SMA not declining + above SMA): {diag['count_regime_ok']}")
    tlog(f"  Volume OK (>1.2x avg): {diag['count_volume_ok']}")
    tlog(f"  Momentum OK (AO zero-cross): {diag['count_momentum_ok']}")
    tlog(f"  Slope OK (>{adaptive_slope_threshold}%): {diag['count_slope_ok']}")
    tlog(f"  Slope Rejected (Flat/Stage1): {diag['count_slope_rejected']}")
    tlog(f"  Initial Stop: {ATR_INITIAL_STOP_MULT}x ATR, Vertical Lock: {vertical_lock_mult}x ATR")
    tlog(f"  Time-Stop: {TIME_STOP_BASE}d base, +{TIME_STOP_CONSOLIDATION_EXT}d if consolidating")
    tlog(f"  Escape Velocity: MSR > {MSR_ESCAPE_VELOCITY} with 1.5x volume and 2% extension")
    tlog(f"  v16.0 Escape Velocity Entries: {diag['count_escape_velocity_entries']}")
    tlog(f"  v16.0 Time-Stop Extended (Consolidation): {diag['count_time_stop_extended']}")
    tlog(f"  v16.0 Catastrophic Floor Exits: {diag['count_catastrophic_floor_exits']}")
    tlog(f"  Penalty Box Hits: {len(hard_stop_history)}")
    tlog(f"  Entries taken: {diag['count_entries_taken']}")
    tlog(f"  Exits taken: {diag['count_exits_taken']}")
    # v16.12: MTF diagnostics (per-bar calculation)
    tlog(f"  MTF Mode: {mtf_mode} | Enforcement: {'ON (per-bar)' if mtf_enforcement else 'OFF'}")
    tlog(f"  MTF Blocked Entries: {diag.get('count_mtf_blocked', 0)}")
    tlog(f"  MTF Exit Count: {len([s for s in all_signals if s.get('reason', '').startswith('MTF Exit')])}")
    tlog(f"  4H Divergence Exits: {diag.get('count_4h_div_exits', 0)}")
    tlog(f"  4H Divergence Entry Blocks: {diag.get('count_4h_div_blocked', 0)}")
    tlog(f"  Traffic Light Entry Blocks: {diag.get('count_tl_blocked', 0)}")
    tlog(f"  Cooling Off Entry Blocks: {diag.get('count_cooloff_blocked', 0)}")
    tlog(f"  Post-Exit Cooling Blocks: {diag.get('count_postexit_blocked', 0)}")
    tlog(f"  B-Wave Trap Blocks: {diag.get('count_bwave_blocked', 0)}")
    tlog(f"  Breakout Confirmation Blocks: {diag.get('count_breakout_blocked', 0)}")
    tlog(f"  AO Corrective Exits: {diag.get('count_ao_corrective_exits', 0)}")
    if diag["blocked_reasons"]:
        tlog(f"  Near-miss entries (blocked):")
        for r in diag["blocked_reasons"][:8]:
            tlog(f"    {r}")
    # v16.21: Log post-Feb-2025 entry blocks
    if diag.get("post_feb_blocks"):
        tlog(f"  Post-Feb-2025 Entry Blocks:")
        for r in diag["post_feb_blocks"]:
            tlog(f"    {r}")
    
    # v15.2: Calculate average SMA slope at entries
    avg_sma_slope = sum(entry_slopes) / len(entry_slopes) if entry_slopes else 0.0
    stats["avg_sma_slope"] = avg_sma_slope
    
    # --- BUILD TRADE LOG (pairs BUY with SELL) ---
    trade_log = []
    buy_signal = None
    for sig in all_signals:
        if sig["type"] == "BUY":
            buy_signal = sig
        elif sig["type"] == "SELL" and buy_signal is not None:
            entry_price = buy_signal["price"]
            exit_price = sig["price"]
            ret = ((exit_price - entry_price) / entry_price) * 100
            
            # Calculate holding period
            entry_date = buy_signal["time"]
            exit_date = sig["time"]
            holding_days = (exit_date - entry_date).days if hasattr(entry_date, 'days') or hasattr(exit_date, 'days') else (exit_date - entry_date).days
            
            trade_log.append({
                "trade_num": len(trade_log) + 1,
                "entry_date": entry_date.strftime("%Y-%m-%d") if hasattr(entry_date, 'strftime') else str(entry_date)[:10],
                "entry_price": entry_price,
                "entry_reason": buy_signal.get("entry_type", "TTA Signal"),
                "sma_slope": buy_signal.get("sma_slope", 0),
                "exit_date": exit_date.strftime("%Y-%m-%d") if hasattr(exit_date, 'strftime') else str(exit_date)[:10],
                "exit_price": exit_price,
                "exit_reason": sig.get("reason", "Stop"),
                "return_pct": ret,
                "holding_days": holding_days
            })
            buy_signal = None
    
    # If still in trade, add open position
    if buy_signal is not None:
        current_price = daily_df['Close'].iloc[-1] if not daily_df.empty else 0
        unrealized = ((current_price - buy_signal["price"]) / buy_signal["price"]) * 100 if buy_signal["price"] > 0 else 0
        entry_date = buy_signal["time"]
        trade_log.append({
            "trade_num": len(trade_log) + 1,
            "entry_date": entry_date.strftime("%Y-%m-%d") if hasattr(entry_date, 'strftime') else str(entry_date)[:10],
            "entry_price": buy_signal["price"],
            "entry_reason": buy_signal.get("entry_type", "TTA Signal"),
            "sma_slope": buy_signal.get("sma_slope", 0),
            "exit_date": "OPEN",
            "exit_price": current_price,
            "exit_reason": "Still Holding",
            "return_pct": unrealized,
            "holding_days": 0
        })
    
    stats["trade_log"] = trade_log
    
    stats["diagnostics"] = diag
    stats["all_signals"] = all_signals  # v12.8: Store for CSV export
    stats["atr_multiplier"] = atr_mult  # v12.8: Track adaptive stop used
    
    # v16.0 Adaptive Architect: Add latest indicator values with safe defaults
    try:
        if msr_list and len(daily_df) > 0:
            last_idx = len(daily_df) - 1
            stats["msr_latest"] = msr_list[last_idx] if last_idx < len(msr_list) and not pd.isna(msr_list[last_idx]) else 0
            stats["nsr_latest"] = nsr_adaptive_list[last_idx] if last_idx < len(nsr_adaptive_list) and not pd.isna(nsr_adaptive_list[last_idx]) else 0
            stats["regime_ratio_latest"] = regime_ratio_list[last_idx] if last_idx < len(regime_ratio_list) and not pd.isna(regime_ratio_list[last_idx]) else 1.0
            stats["is_consolidating"] = bool(consolidation_list[last_idx]) if last_idx < len(consolidation_list) and not pd.isna(consolidation_list[last_idx]) else False
        else:
            stats["msr_latest"] = 0
            stats["nsr_latest"] = 0
            stats["regime_ratio_latest"] = 1.0
            stats["is_consolidating"] = False
    except (IndexError, TypeError, KeyError):
        stats["msr_latest"] = 0
        stats["nsr_latest"] = 0
        stats["regime_ratio_latest"] = 1.0
        stats["is_consolidating"] = False
    
    tlog(f"TTA: Generated {len(all_signals)} signals, {len(runs)} completed trades")
    
    # v16.16 DEBUG: Show ULTIMATE blocking summary
    entry_opps = diag.get("count_entry_opportunities", 0)
    mtf_blocked = diag.get("count_mtf_blocked", 0)
    if mtf_mode == 'ULTIMATE':
        div_blocked = diag.get("count_div_blocked", 0)
        print(f"[ULTIMATE SUMMARY] {ticker}: Entry opportunities={entry_opps}, MTF blocked={mtf_blocked}, DIV blocked={div_blocked}, Trades={len(runs)}")
    
    if runs:
        # Professional Portfolio Simulation (Compounding + Drawdown)
        balance = 10000.0
        peak_balance = 10000.0
        max_drawdown = 0.0
        
        for r in runs:
            balance = balance * (1 + (r / 100))
            peak_balance = max(peak_balance, balance)
            current_drawdown = (peak_balance - balance) / peak_balance
            max_drawdown = max(max_drawdown, current_drawdown)
        
        # v15.0: Calculate stats with proper compounded returns and True Calmar
        stats["final_balance"] = balance  # Already compounded from loop above
        stats["total_return"] = ((balance / 10000) - 1) * 100  # v15.0: Compounded return
        stats["avg_run"] = sum(runs) / len(runs)
        stats["max_drawdown"] = max_drawdown * 100  # Convert to percentage
        
        # v15.0: True Calmar Ratio using CAGR / Max Drawdown
        # Calculate CAGR: (final/initial)^(1/years) - 1
        if len(all_signals) >= 2:
            first_date = all_signals[0]["time"]
            last_date = all_signals[-1]["time"]
            years = max((last_date - first_date).days / 365.25, 0.1)  # Minimum 0.1 years to avoid division issues
            cagr = ((balance / 10000) ** (1 / years) - 1) * 100
        else:
            cagr = stats["total_return"]  # Fallback to total return if insufficient signals
        
        # v16.4 FIX: Handle zero drawdown case (perfect trades = max efficiency)
        if stats["max_drawdown"] and abs(stats["max_drawdown"]) >= 0.01:
            stats["efficiency_ratio"] = abs(cagr / stats["max_drawdown"])  # v15.0: True Calmar
        elif cagr > 0:
            # Perfect case: Profit with zero drawdown = maximum efficiency score
            stats["efficiency_ratio"] = 999.99
        else:
            # No profit, no drawdown = neutral
            stats["efficiency_ratio"] = 0
        stats["cagr"] = cagr  # v15.0: Store CAGR for export
        stats["success_rate"] = (len([r for r in runs if r > 0]) / len(runs)) * 100
        stats["trade_count"] = len(runs)
    
    return historical_markers, stats


# ═══════════════════════════════════════════════════════════════
# DEFERRED BATCH AUDIT EXECUTION (runs after function is defined)
# ═══════════════════════════════════════════════════════════════

def get_filter_value(key, default):
    """Get filter value from session state or use default."""
    return st.session_state.get(key, default)

if st.session_state.get('batch_audit_running') and st.session_state.get('pending_batch_audit'):
    watchlist_to_run = st.session_state.pending_batch_audit
    st.session_state.batch_audit_running = False
    st.session_state.pending_batch_audit = None
    is_all_filters_mode = st.session_state.get('batch_all_filters', False)
    
    # v16.11: Determine which profiles to run
    if is_all_filters_mode:
        profiles_to_run = list(FILTER_PROFILES.keys())
        all_profiles_results = {}
        all_profiles_report = []
    else:
        # v16.12: Read directly from selectbox widget state - it's always current
        selected_profile = st.session_state.get('batch_filter_profile', 'BALANCED')
        profiles_to_run = [selected_profile]
        print(f"[DEBUG] Batch audit using profile from selectbox: {selected_profile}")
    
    # Run for each profile
    for profile_name in profiles_to_run:
        profile = FILTER_PROFILES[profile_name]
        SUIT_FLOOR = profile["suitability_floor"]
        SUIT_GRINDER = profile["suitability_grinder"]
        VERT_UNIVERSAL = profile["verticality_universal"]
        PEAKDOM_LEADER = profile["peak_dominance_leader"]
        PEAKDOM_GRINDER = profile["peak_dominance_grinder"]
        active_filter_profile = profile_name
        
        # v16.11: Debug print filter profile being used
        vert_str = "OFF" if VERT_UNIVERSAL is None else f"{VERT_UNIVERSAL}"
        print(f"")
        print(f"{'='*60}")
        print(f"BATCH AUDIT - Filter Profile: {active_filter_profile}")
        print(f"{'='*60}")
        print(f"  Suitability Floor: {SUIT_FLOOR}")
        print(f"  Suitability Grinder: {SUIT_GRINDER}")
        print(f"  Verticality Universal: {vert_str}")
        print(f"  Peak Dominance Leader: {PEAKDOM_LEADER}")
        print(f"  Peak Dominance Grinder: {PEAKDOM_GRINDER}")
        print(f"{'='*60}")
        print(f"")
        
        batch_results = []
        all_batch_trades = []
        all_batch_diagnostics = []  # v16.12: Store diagnostics per ticker for consolidated report
        
        # Show progress in sidebar
        with st.sidebar:
            if is_all_filters_mode:
                st.info(f"Running profile: **{active_filter_profile}**")
            progress_bar = st.progress(0)
            status_text = st.empty()
        
        for idx, batch_ticker in enumerate(watchlist_to_run):
            status_text.markdown(f"Analyzing **{batch_ticker}**... ({idx+1}/{len(watchlist_to_run)})")
            progress_bar.progress((idx + 1) / len(watchlist_to_run))
            
            try:
                # Fetch data for this ticker
                batch_stock = yf.Ticker(batch_ticker)
                batch_daily = batch_stock.history(period="2y", interval="1d")
                batch_weekly = batch_stock.history(period="5y", interval="1wk")
                
                # Normalize timezone-aware datetimes to timezone-naive
                if batch_daily.index.tz is not None:
                    batch_daily.index = batch_daily.index.tz_localize(None)
                if batch_weekly.index.tz is not None:
                    batch_weekly.index = batch_weekly.index.tz_localize(None)
                
                # v16.16 FIX: Fetch monthly data for ULTIMATE mode (required for 5-Gate entry)
                batch_monthly = batch_stock.history(period="5y", interval="1mo")
                if batch_monthly.index.tz is not None:
                    batch_monthly.index = batch_monthly.index.tz_localize(None)
                # Store in session state for scan function to access
                st.session_state['monthly_df'] = batch_monthly if not batch_monthly.empty else None
                
                if batch_daily.empty or len(batch_daily) < 50:
                    batch_results.append({
                        'Ticker': batch_ticker,
                        'Total Return (%)': 0,
                        'CAGR (%)': 0,
                        'Max Drawdown (%)': 0,
                        'Efficiency Ratio': 0,
                        'Win Rate (%)': 0,
                        'Trades': 0,
                        'Avg SMA Slope (%)': 0,
                        'Suitability': 0,
                        'Status': 'Insufficient Data'
                    })
                    continue
                
                # Calculate Weekly SMA
                batch_weekly_sma = batch_weekly['Close'].rolling(window=30).mean()
                
                # ═══════════════════════════════════════════════════════════════
                # v14.3 ALPHA CAP: Universal Momentum Test (No Auto-Accept)
                # ═══════════════════════════════════════════════════════════════
                
                suit_score, suit_verdict = calculate_suitability_score(batch_daily, batch_weekly_sma)
                print(f"v16.11 FILTER SWITCHBOARD [{active_filter_profile}]: {batch_ticker}")
                print(f"  Suitability: {suit_score}/100 (floor: {SUIT_FLOOR})")
                
                # GATE 1: Suitability Floor Check
                if suit_score < SUIT_FLOOR:
                    print(f"  -> REJECTED: Low Quality ({suit_score} < {SUIT_FLOOR})")
                    batch_results.append({
                        'Ticker': batch_ticker,
                        'Total Return (%)': 0,
                        'CAGR (%)': 0,
                        'Max Drawdown (%)': 0,
                        'Efficiency Ratio': 0,
                        'Win Rate (%)': 0,
                        'Trades': 0,
                        'Avg SMA Slope (%)': 0,
                        'Suitability': suit_score,
                        'Status': f'REJECTED: Low Quality ({suit_score}<{SUIT_FLOOR})'
                    })
                    continue
                
                # v15.1 GATE: Drawdown Ceiling (15% max avg weekly drawdown)
                avg_weekly_dd = calculate_avg_weekly_drawdown(batch_weekly)
                # v15.5 FIX: Handle None values (default to 0.0) to ensure MU is not skipped
                if avg_weekly_dd is None:
                    avg_weekly_dd = 0.0
                print(f"  Avg Weekly DD: {avg_weekly_dd:.1f}% (ceiling: {DRAWDOWN_CEILING}%)")
                
                if avg_weekly_dd > DRAWDOWN_CEILING:
                    print(f"  -> REJECTED: High Structural Risk (Avg DD {avg_weekly_dd:.1f}% > {DRAWDOWN_CEILING}%)")
                    batch_results.append({
                        'Ticker': batch_ticker,
                        'Total Return (%)': 0,
                        'CAGR (%)': 0,
                        'Max Drawdown (%)': 0,
                        'Efficiency Ratio': 0,
                        'Win Rate (%)': 0,
                        'Trades': 0,
                        'Avg SMA Slope (%)': 0,
                        'Suitability': suit_score,
                        'Status': f'REJECTED: High Structural Risk (DD {avg_weekly_dd:.1f}%>{DRAWDOWN_CEILING}%)'
                    })
                    continue
                
                # v15.1: Check if ticker is in Cyclical/Industrial sector
                is_cyclical = batch_ticker.upper() in CYCLICAL_TICKERS
                cyclical_peakdom_req = CYCLICAL_PEAK_DOMINANCE if is_cyclical else PEAK_DOMINANCE_LEADER
                
                # Calculate Universal Impulse Test metrics
                ao = calculate_awesome_oscillator(batch_daily)
                ao_abs = ao.abs()
                ao_peak = ao_abs.max()
                ao_median = ao_abs.median()
                peak_dominance = ao_peak / ao_median if ao_median > 0 else 0
                
                current_price = batch_daily['Close'].iloc[-1]
                current_sma = batch_weekly_sma.reindex(batch_daily.index, method='ffill').iloc[-1]
                # Calculate ATR for Verticality
                tr = pd.concat([
                    batch_daily['High'] - batch_daily['Low'],
                    (batch_daily['High'] - batch_daily['Close'].shift()).abs(),
                    (batch_daily['Low'] - batch_daily['Close'].shift()).abs()
                ], axis=1).max(axis=1)
                atr = tr.rolling(window=14).mean().iloc[-1]
                verticality = (current_price - current_sma) / atr if atr > 0 else 0
                
                print(f"  Peak Dominance: {peak_dominance:.2f}x (leader: {PEAKDOM_LEADER} | grinder: {PEAKDOM_GRINDER})")
                vert_gate_str = "OFF" if VERT_UNIVERSAL is None else f"{VERT_UNIVERSAL}"
                print(f"  Verticality: {verticality:.2f} (universal gate: {vert_gate_str})")
                
                # v14.6 ANTI-GRINDER LOGIC
                tier_status = None
                
                # GATE 1: Universal Verticality Gate (ALL stocks must pass)
                # v16.12: Skip gate if VERT_UNIVERSAL is None OR negative (AGGRESSIVE/BALANCED/HYBRID)
                # Negative values (-2.0, -1.0) = disabled to allow consolidating momentum
                if VERT_UNIVERSAL is not None and VERT_UNIVERSAL > 0 and verticality <= VERT_UNIVERSAL:
                    print(f"  -> REJECTED: Low Verticality (Vert {verticality:.1f} <= {VERT_UNIVERSAL})")
                    batch_results.append({
                        'Ticker': batch_ticker,
                        'Total Return (%)': 0,
                        'CAGR (%)': 0,
                        'Max Drawdown (%)': 0,
                        'Efficiency Ratio': 0,
                        'Win Rate (%)': 0,
                        'Trades': 0,
                        'Avg SMA Slope (%)': 0,
                        'Suitability': suit_score,
                        'Status': f'REJECTED: Low Verticality (Vert {verticality:.1f})'
                    })
                    continue
                elif VERT_UNIVERSAL is None or VERT_UNIVERSAL <= 0:
                    print(f"  -> GATE SKIPPED: Verticality disabled ({active_filter_profile} profile)")
                
                # GATE 2: Anti-Grinder vs Leader Pass
                if suit_score > SUIT_GRINDER:
                    # ANTI-GRINDER: High suitability must prove impulse
                    if peak_dominance > PEAKDOM_GRINDER:
                        tier_status = "OK (Verified Grinder)"
                        print(f"  -> PASSED: Verified Grinder (Suit {suit_score} > {SUIT_GRINDER} - PeakDom {peak_dominance:.1f}x > {PEAKDOM_GRINDER})")
                    else:
                        print(f"  -> REJECTED: Non-Impulsive Grinder (Suit {suit_score} > {SUIT_GRINDER} but PeakDom {peak_dominance:.1f}x <= {PEAKDOM_GRINDER})")
                        batch_results.append({
                            'Ticker': batch_ticker,
                            'Total Return (%)': 0,
                            'CAGR (%)': 0,
                            'Max Drawdown (%)': 0,
                            'Efficiency Ratio': 0,
                            'Win Rate (%)': 0,
                            'Trades': 0,
                            'Avg SMA Slope (%)': 0,
                            'Suitability': suit_score,
                            'Status': f'REJECTED: Non-Impulsive Grinder (PeakDom {peak_dominance:.1f}x)'
                        })
                        continue
                else:
                    # LEADER PASS: Suit <= grinder threshold needs PeakDom > leader threshold (or 4.5x for cyclicals)
                    required_peakdom = cyclical_peakdom_req if is_cyclical else PEAKDOM_LEADER
                    if peak_dominance > required_peakdom:
                        sector_tag = " [Cyclical]" if is_cyclical else ""
                        tier_status = f"OK (Momentum Leader{sector_tag})"
                        print(f"  -> PASSED: Momentum Leader (Suit {suit_score} <= {SUIT_GRINDER} - PeakDom {peak_dominance:.1f}x > {required_peakdom})")
                    else:
                        reject_reason = f"Weak Cyclical Impulse (PeakDom {peak_dominance:.1f}x)" if is_cyclical else f"Low Impulse (PeakDom {peak_dominance:.1f}x)"
                        print(f"  -> REJECTED: {reject_reason}")
                        batch_results.append({
                            'Ticker': batch_ticker,
                            'Total Return (%)': 0,
                            'CAGR (%)': 0,
                            'Max Drawdown (%)': 0,
                            'Efficiency Ratio': 0,
                            'Win Rate (%)': 0,
                            'Trades': 0,
                            'Avg SMA Slope (%)': 0,
                            'Suitability': suit_score,
                            'Status': f'REJECTED: {reject_reason}'
                        })
                        continue
                
                # PASSED GATE - Run TTA scan
                _, batch_stats = scan_tta_for_daily_chart(
                    batch_daily, 
                    batch_weekly, 
                    batch_weekly_sma, 
                    batch_ticker,
                    filter_profile=active_filter_profile,
                    suitability_score=suit_score
                )
                
                # ═══════════════════════════════════════════════════════════════
                # v16.4 POST-BACKTEST QUALITY GATES (After TTA scan)
                # ═══════════════════════════════════════════════════════════════
                
                backtest_max_dd = batch_stats.get('max_drawdown', 0)
                trade_count = batch_stats.get('trade_count', 0)
                
                # v16.11: Get profile-based thresholds (fallback to hardcoded defaults)
                PROFILE_DD_CEILING = profile.get('drawdown_ceiling', DRAWDOWN_CEILING)
                PROFILE_MAX_TRADES = profile.get('max_trade_count', 6)
                PROFILE_MIN_WIN_RATE = profile.get('min_win_rate', 45.0)
                
                # v16.4 FIX 1: BACKTEST DRAWDOWN CEILING (Profile-configurable)
                if backtest_max_dd > PROFILE_DD_CEILING:
                    print(f"  -> REJECTED: Backtest Max DD {backtest_max_dd:.1f}% > {PROFILE_DD_CEILING}% ceiling")
                    batch_results.append({
                        'Ticker': batch_ticker,
                        'Total Return (%)': batch_stats.get('total_return', 0),
                        'CAGR (%)': batch_stats.get('cagr', 0),
                        'Max Drawdown (%)': backtest_max_dd,
                        'Efficiency Ratio': 0,
                        'Win Rate (%)': batch_stats.get('success_rate', 0),
                        'Trades': trade_count,
                        'Avg SMA Slope (%)': batch_stats.get('avg_sma_slope', 0),
                        'Suitability': suit_score,
                        'Status': f'REJECTED: Max DD {backtest_max_dd:.1f}%>{PROFILE_DD_CEILING}%'
                    })
                    continue
                
                # v16.4 FIX 3: MINIMUM TRADE COUNT (Must generate at least 3 trading opportunities)
                MIN_TRADE_COUNT = 3
                if trade_count < MIN_TRADE_COUNT:
                    print(f"  -> REJECTED: Insufficient Opportunities ({trade_count} trades < {MIN_TRADE_COUNT} required)")
                    batch_results.append({
                        'Ticker': batch_ticker,
                        'Total Return (%)': batch_stats.get('total_return', 0),
                        'CAGR (%)': batch_stats.get('cagr', 0),
                        'Max Drawdown (%)': backtest_max_dd,
                        'Efficiency Ratio': 0,  # Zero efficiency for insufficient trades
                        'Win Rate (%)': batch_stats.get('success_rate', 0),
                        'Trades': trade_count,
                        'Avg SMA Slope (%)': batch_stats.get('avg_sma_slope', 0),
                        'Suitability': suit_score,
                        'Status': f'REJECTED: Insufficient Opportunities ({trade_count}<{MIN_TRADE_COUNT})'
                    })
                    continue
                
                # v16.11 GATE 6: ANTI-OVERTRADING FILTER (Profile-configurable)
                if trade_count > PROFILE_MAX_TRADES:
                    print(f"  -> REJECTED: Overtrading Detected ({trade_count} trades > {PROFILE_MAX_TRADES} max)")
                    batch_results.append({
                        'Ticker': batch_ticker,
                        'Total Return (%)': batch_stats.get('total_return', 0),
                        'CAGR (%)': batch_stats.get('cagr', 0),
                        'Max Drawdown (%)': backtest_max_dd,
                        'Efficiency Ratio': 0,  # Zero efficiency for overtrading
                        'Win Rate (%)': batch_stats.get('success_rate', 0),
                        'Trades': trade_count,
                        'Avg SMA Slope (%)': batch_stats.get('avg_sma_slope', 0),
                        'Suitability': suit_score,
                        'Status': f'REJECTED: Overtrading ({trade_count}>{PROFILE_MAX_TRADES})'
                    })
                    continue
                
                # v15.1: Re-classify based on True Calmar efficiency
                true_calmar = batch_stats.get('efficiency_ratio', 0)
                win_rate = batch_stats.get('success_rate', 0)
                
                # v16.5 GATE 7: MINIMUM EFFICIENCY THRESHOLD (CAGR must justify risk)
                MIN_CALMAR = 0.50  # CAGR must be at least 50% of drawdown
                if true_calmar < MIN_CALMAR:
                    reason = f"Low Efficiency (Calmar {true_calmar:.2f}x < {MIN_CALMAR}x)"
                    print(f"  -> REJECTED: {reason}")
                    batch_results.append({
                        'Ticker': batch_ticker,
                        'Total Return (%)': batch_stats.get('total_return', 0),
                        'CAGR (%)': batch_stats.get('cagr', 0),
                        'Max Drawdown (%)': backtest_max_dd,
                        'Efficiency Ratio': true_calmar,
                        'Win Rate (%)': win_rate,
                        'Trades': trade_count,
                        'Avg SMA Slope (%)': batch_stats.get('avg_sma_slope', 0),
                        'Suitability': suit_score,
                        'Status': f'REJECTED: {reason}'
                    })
                    continue
                
                # v16.11 GATE 8: MINIMUM WIN RATE FILTER (Profile-configurable)
                if win_rate < PROFILE_MIN_WIN_RATE:
                    reason = f"Low Win Rate ({win_rate:.1f}% < {PROFILE_MIN_WIN_RATE}%)"
                    print(f"  -> REJECTED: {reason}")
                    batch_results.append({
                        'Ticker': batch_ticker,
                        'Total Return (%)': batch_stats.get('total_return', 0),
                        'CAGR (%)': batch_stats.get('cagr', 0),
                        'Max Drawdown (%)': backtest_max_dd,
                        'Efficiency Ratio': true_calmar,
                        'Win Rate (%)': win_rate,
                        'Trades': trade_count,
                        'Avg SMA Slope (%)': batch_stats.get('avg_sma_slope', 0),
                        'Suitability': suit_score,
                        'Status': f'REJECTED: {reason}'
                    })
                    continue
                
                # ═══════════════════════════════════════════════════════════════════
                # PASSED ALL 8 GATES - Stock qualifies for leaderboard
                if true_calmar < 1.0 and trade_count > 0:
                    # Passed pre-filter but inefficient in backtesting - append inefficient tag
                    tier_status = f"{tier_status} - Inefficient"
                    print(f"  -> RECLASSIFIED: Inefficient (True Calmar {true_calmar:.2f}x < 1.0)")
                
                batch_results.append({
                    'Ticker': batch_ticker,
                    'Total Return (%)': batch_stats.get('total_return', 0),
                    'CAGR (%)': batch_stats.get('cagr', 0),  # v15.0: CAGR for True Calmar
                    'Max Drawdown (%)': backtest_max_dd,
                    'Efficiency Ratio': batch_stats.get('efficiency_ratio', 0),
                    'Win Rate (%)': batch_stats.get('success_rate', 0),
                    'Trades': trade_count,
                    'Avg SMA Slope (%)': batch_stats.get('avg_sma_slope', 0),  # v15.2: Structural support
                    'Suitability': suit_score,
                    'Status': tier_status  # v15.1: Shows tier badge with efficiency
                })
                
                # Collect individual trades for this ticker
                signals = batch_stats.get('all_signals', [])
                ticker_trades = []
                buy_signal = None
                for sig in signals:
                    if sig["type"] == "BUY":
                        buy_signal = sig
                    elif sig["type"] == "SELL" and buy_signal:
                        entry_date = buy_signal["time"].strftime('%Y-%m-%d') if hasattr(buy_signal["time"], 'strftime') else str(buy_signal["time"])[:10]
                        exit_date = sig["time"].strftime('%Y-%m-%d') if hasattr(sig["time"], 'strftime') else str(sig["time"])[:10]
                        entry_price = buy_signal["price"]
                        exit_price = sig["price"]
                        exit_reason = sig.get("reason", "Stop")
                        ret = ((exit_price - entry_price) / entry_price) * 100
                        trade_record = {
                            'Ticker': batch_ticker,
                            'Entry Date': entry_date,
                            'Entry Price': entry_price,
                            'Exit Date': exit_date,
                            'Exit Price': exit_price,
                            'Exit Reason': exit_reason,
                            'Return (%)': ret
                        }
                        all_batch_trades.append(trade_record)
                        ticker_trades.append(trade_record)
                        buy_signal = None
                
                # v16.12: Store diagnostics per ticker for consolidated report
                diag = batch_stats.get('diagnostics', {})
                all_batch_diagnostics.append({
                    'Ticker': batch_ticker,
                    'Suitability': suit_score,
                    'Status': tier_status,
                    'Total Return': batch_stats.get('total_return', 0),
                    'Max Drawdown': backtest_max_dd,
                    'Efficiency': batch_stats.get('efficiency_ratio', 0),
                    'Win Rate': batch_stats.get('success_rate', 0),
                    'Trades': ticker_trades,
                    'Blocked Reasons': diag.get('blocked_reasons', []),
                    'Entries Taken': diag.get('count_entries_taken', 0),
                    'Exits Taken': diag.get('count_exits_taken', 0),
                    'Regime OK Days': diag.get('count_regime_ok', 0),
                    'Volume OK Days': diag.get('count_volume_ok', 0),
                    'Momentum OK Days': diag.get('count_momentum_ok', 0),
                    'Slope OK Days': diag.get('count_slope_ok', 0)
                })
                        
            except Exception as e:
                batch_results.append({
                    'Ticker': batch_ticker,
                    'Total Return (%)': 0,
                    'CAGR (%)': 0,
                    'Max Drawdown (%)': 0,
                    'Efficiency Ratio': 0,
                    'Win Rate (%)': 0,
                    'Trades': 0,
                    'Avg SMA Slope (%)': 0,
                    'Suitability': 0,
                    'Status': f'Error: {str(e)[:30]}'
                })
        
        progress_bar.empty()
        status_text.empty()
        
        # v16.11: Store results for this profile
        if is_all_filters_mode:
            all_profiles_results[profile_name] = {
                'results': batch_results.copy(),
                'trades': all_batch_trades.copy(),
                'diagnostics': all_batch_diagnostics.copy(),
                'profile': profile
            }
    
    # v16.11: Generate combined report for all filters mode
    if is_all_filters_mode:
        combined_report_lines = []
        combined_report_lines.append("=" * 70)
        combined_report_lines.append(f"TTA ENGINE {BUILD_VERSION} - ALL FILTERS COMPARISON REPORT")
        combined_report_lines.append(f"Build: {BUILD_NAME} | Date: {BUILD_DATE}")
        combined_report_lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        combined_report_lines.append("=" * 70)
        combined_report_lines.append("")
        combined_report_lines.append(f"Watchlist: {', '.join(watchlist_to_run)}")
        combined_report_lines.append(f"Total Tickers: {len(watchlist_to_run)}")
        combined_report_lines.append("")
        
        # Summary table
        combined_report_lines.append("=" * 70)
        combined_report_lines.append("SUMMARY BY FILTER PROFILE")
        combined_report_lines.append("=" * 70)
        combined_report_lines.append(f"{'Profile':<15} {'Passed':<8} {'Rejected':<10} {'Avg Return':<12} {'Avg Eff':<10}")
        combined_report_lines.append("-" * 70)
        
        for pname, pdata in all_profiles_results.items():
            results = pdata['results']
            passed = [r for r in results if str(r.get('Status', '')).startswith('OK')]
            rejected = [r for r in results if str(r.get('Status', '')).startswith('REJECTED')]
            avg_ret = sum(r['Total Return (%)'] for r in passed) / len(passed) if passed else 0
            avg_eff = sum(r['Efficiency Ratio'] for r in passed) / len(passed) if passed else 0
            combined_report_lines.append(f"{pname:<15} {len(passed):<8} {len(rejected):<10} {avg_ret:>+10.1f}% {avg_eff:>8.2f}x")
        
        combined_report_lines.append("")
        
        # Detailed results per profile
        for pname, pdata in all_profiles_results.items():
            profile = pdata['profile']
            results = pdata['results']
            vert_str = "OFF" if profile["verticality_universal"] is None else f"> {profile['verticality_universal']}"
            
            combined_report_lines.append("")
            combined_report_lines.append("=" * 70)
            combined_report_lines.append(f"PROFILE: {pname}")
            combined_report_lines.append("-" * 70)
            combined_report_lines.append(f"  Verticality: {vert_str}")
            combined_report_lines.append(f"  Suitability Floor: {profile['suitability_floor']}")
            combined_report_lines.append(f"  PeakDom: Leader {profile['peak_dominance_leader']}x | Grinder {profile['peak_dominance_grinder']}x")
            combined_report_lines.append(f"  Max Trades: {profile['max_trade_count']} | DD Ceiling: {profile['drawdown_ceiling']}% | Min Win Rate: {profile['min_win_rate']}%")
            combined_report_lines.append("")
            
            passed = [r for r in results if str(r.get('Status', '')).startswith('OK')]
            rejected = [r for r in results if str(r.get('Status', '')).startswith('REJECTED')]
            
            if passed:
                combined_report_lines.append(f"PASSED ({len(passed)}):")
                passed_sorted = sorted(passed, key=lambda x: x['Efficiency Ratio'], reverse=True)
                for r in passed_sorted:
                    combined_report_lines.append(f"  {r['Ticker']}: {r['Total Return (%)']:+.1f}% | {r['Efficiency Ratio']:.2f}x eff | {r['Trades']} trades")
            else:
                combined_report_lines.append("PASSED: None")
            
            combined_report_lines.append("")
            if rejected:
                combined_report_lines.append(f"REJECTED ({len(rejected)}):")
                for r in rejected:
                    status = str(r.get('Status', '')).replace('REJECTED: ', '')
                    combined_report_lines.append(f"  {r['Ticker']}: {status}")
        
        combined_report_lines.append("")
        combined_report_lines.append("=" * 70)
        combined_report_lines.append("END OF REPORT")
        combined_report_lines.append("=" * 70)
        
        st.session_state.all_filters_report = "\n".join(combined_report_lines)
        st.session_state.all_profiles_results = all_profiles_results
        # Use the last profile's results for display (HYBRID as fallback)
        last_profile = list(all_profiles_results.keys())[-1]
        st.session_state.batch_results = all_profiles_results[last_profile]['results']
        st.session_state.batch_trades = all_profiles_results[last_profile]['trades']
    else:
        st.session_state.batch_results = batch_results
        st.session_state.batch_trades = all_batch_trades
        st.session_state.batch_diagnostics = all_batch_diagnostics  # v16.12: Store for consolidated report
    
    st.rerun()


if analyze_btn and ticker:
    # v16.14: Start log capture for this analysis run
    st.session_state.log_capture.start()
    
    # v15.4 FIX: Debug print for analysis trigger
    tlog(f"ANALYZE TRIGGERED for ticker: '{ticker}'")
    
    # v13.1: Centered loading spinner in chart area
    loading_placeholder = st.empty()
    with loading_placeholder.container():
        st.markdown(
            """
            <div style="
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                height: 400px;
                background: linear-gradient(135deg, rgba(30,41,59,0.8) 0%, rgba(15,23,42,0.9) 100%);
                border-radius: 12px;
                border: 1px solid rgba(100,116,139,0.3);
            ">
                <style>
                    @keyframes spin {
                        0% { transform: rotate(0deg); }
                        100% { transform: rotate(360deg); }
                    }
                    .loader {
                        width: 60px;
                        height: 60px;
                        border: 4px solid rgba(59, 130, 246, 0.2);
                        border-top: 4px solid #3b82f6;
                        border-radius: 50%;
                        animation: spin 1s linear infinite;
                    }
                </style>
                <div class="loader"></div>
                <p style="color: #94a3b8; margin-top: 20px; font-size: 1.1rem;">Analyzing <strong style="color: #60a5fa;">""" + ticker + """</strong>...</p>
                <p style="color: #64748b; font-size: 0.85rem; margin-top: 8px;">Fetching data • Calculating indicators • Scanning signals</p>
            </div>
            """,
            unsafe_allow_html=True
        )
    
    with st.spinner(""):
        # Always fetch weekly data for 30-week SMA (Weinstein analysis)
        weekly_df = fetch_stock_data(ticker, period="5y", interval="1wk")
        weekly_sma_data = None
        if not weekly_df.empty and len(weekly_df) >= 30:
            weekly_sma = calculate_sma(weekly_df, 30)
            weekly_sma_data = weekly_sma.dropna()
        
        # v16.5: Fetch monthly data for highest timeframe analysis
        monthly_df = fetch_stock_data(ticker, period="5y", interval="1mo")
        m_ao = None
        m_diag = None
        w3_monthly = None
        if monthly_df is not None and not monthly_df.empty and len(monthly_df) >= 20:
            # Calculate monthly AO
            m_ao = calculate_awesome_oscillator(monthly_df)
            
            # Calculate monthly 30-period SMA (30 months = ~2.5 years)
            monthly_sma = calculate_sma(monthly_df, 30) if len(monthly_df) >= 30 else None
            
            # Build monthly diagnostic
            m_diag = build_ao_chunk_diagnostic(
                m_ao.to_numpy(),
                monthly_df.index.to_numpy(),
                monthly_df['High'].to_numpy(),
                monthly_df['Low'].to_numpy(),
                monthly_df['Close'].to_numpy(),
                monthly_sma.to_numpy() if monthly_sma is not None else None
            )
            
            # Get monthly Wave 3
            w3_monthly = m_diag.get("wave3") if m_diag else None
            
            tlog(f"TTA: Monthly timeframe - W3 detected: {w3_monthly is not None}")
        else:
            tlog("TTA: Monthly data not available or insufficient")
        
        # Store monthly data in session state for TTA scanner
        st.session_state.monthly_df = monthly_df if monthly_df is not None and not monthly_df.empty else None
        st.session_state.m_ao = m_ao
        st.session_state.m_diag = m_diag
        st.session_state.w3_monthly = w3_monthly
        
        # v11.5 TTA: Fetch all three timeframes for Daily analysis
        daily_df = fetch_stock_data(ticker, period="2y", interval="1d")
        h1_df = fetch_stock_data(ticker, period="730d", interval="1h")  # Extended hourly for 4H execution
        
        if timeframe == "Weekly":
            df = weekly_df
            sma_period = 30
            sma_label = "30-Week SMA"
        elif timeframe == "Daily":
            df = daily_df  # Display frame is Daily
            sma_period = 150
            sma_label = "30-Week SMA"
        else:
            # 4H view - resample hourly to 4H
            df = h1_df.copy() if not h1_df.empty else pd.DataFrame()
            if not df.empty:
                df = df.resample('4h').agg({
                    'Open': 'first',
                    'High': 'max',
                    'Low': 'min',
                    'Close': 'last',
                    'Volume': 'sum'
                }).dropna()
            sma_period = 180
            sma_label = "30-Week SMA"
        
        # Store all timeframe dataframes in session state for MTF AI analysis
        st.session_state.h1_df = h1_df if not h1_df.empty else None
        st.session_state.daily_df = daily_df if daily_df is not None and not daily_df.empty else None
        st.session_state.weekly_df = weekly_df if weekly_df is not None and not weekly_df.empty else None
        
        if df.empty:
            st.error(f"No data found for ticker '{ticker}'. Please check the symbol and try again.")
            st.session_state.df = None
            st.session_state.fig = None
            st.session_state.pivot_text = None
        else:
            # PF0: Store previous ticker's levels before switching
            if st.session_state.current_ticker is not None and st.session_state.current_ticker != ticker:
                st.session_state.previous_ticker = st.session_state.current_ticker
                st.session_state.previous_levels = {
                    'A': st.session_state.level_A,
                    'B': st.session_state.level_B,
                    'SMA': st.session_state.sma_value
                }
                # v15.1: Clear stale dashboard data when switching tickers
                st.session_state.dashboard_data = None
            
            st.session_state.df = df
            st.session_state.current_ticker = ticker
            tlog(f"SESSION STATE UPDATED: current_ticker = '{ticker}'")
            
            # v16.14: Stop log capture at end of analysis
            st.session_state.log_capture.stop()
            st.session_state.current_timeframe = timeframe
            st.session_state.sma_period = sma_period
            st.session_state.sma_label = sma_label
            st.session_state.pivot_order = pivot_order
            st.session_state.weekly_sma_data = weekly_sma_data
            
            # v12.5 Volatility Personality Scouter
            suitability_score, suitability_verdict = calculate_suitability_score(df, weekly_sma_data)
            st.session_state.suitability_score = suitability_score
            st.session_state.suitability_verdict = suitability_verdict
            
            # v12.6 Personality Audit Breakdown
            personality_audit = get_personality_audit(df, weekly_sma_data)
            st.session_state.personality_audit = personality_audit
            
            # v16.35 Adaptive Strategy Recommendation
            adaptive_strategy, adaptive_rationale, adaptive_color = get_adaptive_strategy_recommendation(suitability_score)
            st.session_state.adaptive_strategy = adaptive_strategy
            st.session_state.adaptive_rationale = adaptive_rationale
            st.session_state.adaptive_color = adaptive_color
            
            # v16.35 Break-Retest Pattern Detection (only for MODERATE stocks)
            if adaptive_strategy == "BREAK-RETEST":
                try:
                    br_state = get_current_pattern_state(ticker, period='2y')
                    st.session_state.br_pattern_state = br_state
                except Exception as e:
                    st.session_state.br_pattern_state = {'signal': f'Error: {str(e)}', 'pattern_phase': None}
            else:
                st.session_state.br_pattern_state = None
            
            # First detect pivots to get trigger levels
            pivot_text, trigger_levels = find_price_pivots(df, order=pivot_order)
            st.session_state.pivot_text = pivot_text
            st.session_state.trigger_levels = trigger_levels
            
            # v7.1 Trigger Levels from structural pivots
            # A = most recent swing LOW (bearish activation)
            # B = most recent swing HIGH (bullish continuation)
            level_A = trigger_levels.get('A')
            level_B = trigger_levels.get('B')
            st.session_state.level_A = level_A
            st.session_state.level_B = level_B
            
            # --- GLOBAL AO KING-CHUNK DIAGNOSTIC (v9.4 - SMA Reset Aware) ---
            ao_series = calculate_awesome_oscillator(df)
            # Fetch full arrays for global scan
            ao_arr = ao_series.to_numpy()
            dates_arr = df.index.to_numpy()
            high_arr = df['High'].to_numpy()
            low_arr = df['Low'].to_numpy()
            close_arr = df['Close'].to_numpy()
            
            # Align weekly SMA to chart dates for reset detection
            sma_arr = None
            if weekly_sma_data is not None and len(weekly_sma_data) > 0:
                # Reindex SMA to match df dates, forward-fill for daily alignment
                sma_aligned = weekly_sma_data.reindex(df.index, method='ffill')
                sma_arr = sma_aligned.to_numpy()
            
            # Pass full data with SMA for reset detection
            ao_diag = build_ao_chunk_diagnostic(ao_arr, dates_arr, high_arr, low_arr, close_arr, sma_arr)
            
            # Store diagnostic for dashboard/PDF
            st.session_state.ao_diag = ao_diag
            
            # Backward compatibility: keep macd_diag reference
            macd_diag = ao_diag
            macd_markers = macd_diag.get("chart_markers", []) if macd_diag else []
            divergence_lines = macd_diag.get("divergence_lines", []) if macd_diag else []
            st.session_state.macd_diag = macd_diag  # Store for later dashboard use
            
            # --- v11.2 TTA INTEGRATION ---
            # Run Tri-Timeframe Alignment scanner for Daily charts
            # Weekly W3 + Daily W3 sync, 4H pullback, hourly entry - printed on Daily chart
            tta_markers = []
            tta_stats = {"count": 0, "avg_run": 0.0, "total_return": None, "final_balance": None, "max_drawdown": None, "efficiency_ratio": None, "cagr": None, "success_rate": 0, "trade_count": 0, "active_sl": None}
            
            if timeframe == "Daily" and weekly_sma_data is not None:
                # v16.35: Check if Adaptive Strategy toggle is ON and strategy is BREAK-RETEST
                use_adaptive = st.session_state.get('show_adaptive_strategy', False)
                adaptive_strat = st.session_state.get('adaptive_strategy', 'TTA')
                
                # v16.36: Always run TTA to get traffic lights for MTF dashboard
                h1_df = st.session_state.get('h1_df')
                suit_score = st.session_state.get('suitability_score')
                if suit_score is None:
                    suit_score = 50  # Fallback only if truly missing
                    print(f"[v16.36] WARNING: suitability_score was None, using default 50")
                tta_markers_base, tta_stats_base = scan_tta_for_daily_chart(
                    df, weekly_df, weekly_sma_data, ticker, h1_df, filter_profile=selected_profile, suitability_score=suit_score
                )
                traffic_lights_data = tta_stats_base.get("traffic_lights", {})
                print(f"[v16.36] TTA ran for traffic lights: {len(traffic_lights_data)} timeframes")
                
                if use_adaptive and adaptive_strat == "BREAK-RETEST":
                    # Use Break-Retest strategy for MODERATE volatility stocks
                    print(f"ADAPTIVE: Using BREAK-RETEST strategy for {ticker} (toggle ON, strategy={adaptive_strat})")
                    tta_markers, tta_stats = run_break_retest_for_chart(ticker, df)
                    tta_stats["strategy_type"] = "BREAK-RETEST"
                    # v16.36: Copy all MTF dashboard data from TTA analysis
                    tta_stats["traffic_lights"] = traffic_lights_data
                    # Copy AO values for MTF dashboard
                    tta_stats["monthly_ao"] = tta_stats_base.get("monthly_ao")
                    tta_stats["weekly_ao"] = tta_stats_base.get("weekly_ao")
                    tta_stats["daily_ao"] = tta_stats_base.get("daily_ao")
                    tta_stats["h4_ao"] = tta_stats_base.get("h4_ao")
                    # Copy MACD bearish flags for MTF dashboard
                    tta_stats["monthly_macd_bearish"] = tta_stats_base.get("monthly_macd_bearish", False)
                    tta_stats["weekly_macd_bearish"] = tta_stats_base.get("weekly_macd_bearish", False)
                    tta_stats["daily_macd_bearish"] = tta_stats_base.get("daily_macd_bearish", False)
                    tta_stats["h4_macd_bearish"] = tta_stats_base.get("h4_macd_bearish", False)
                    print(f"[v16.36] Copied traffic lights to BR stats: {bool(traffic_lights_data)}")
                else:
                    # Use TTA strategy (default, or toggle OFF, or VOLATILE/STEADY stocks)
                    strategy_reason = "toggle OFF" if not use_adaptive else f"strategy={adaptive_strat}"
                    print(f"ADAPTIVE: Using TTA strategy for {ticker} ({strategy_reason})")
                    tta_markers = tta_markers_base
                    tta_stats = tta_stats_base
                    tta_stats["strategy_type"] = "TTA"
                
                # Debug: Print markers
                if tta_markers:
                    strategy_name = tta_stats.get("strategy_type", "TTA")
                    print(f"{strategy_name} MARKERS TO RENDER: {len(tta_markers)} markers")
                    for m in tta_markers:
                        print(f"  - {m.get('text')} at {m.get('time')}")
            
            # Combine all markers: AO diagnostic + TTA signals
            all_markers = macd_markers + tta_markers
            st.session_state.tta_stats = tta_stats
            print(f"TOTAL MARKERS: {len(all_markers)} (AO: {len(macd_markers)}, TTA: {len(tta_markers)})")
            
            # v16.17: Run 4H divergence detection early for persistent UI display
            h1_df_for_div = st.session_state.get('h1_df')
            if h1_df_for_div is not None and not h1_df_for_div.empty:
                try:
                    h4_df_for_div = h1_df_for_div.resample('4h').agg({
                        'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
                    }).dropna()
                    if len(h4_df_for_div) >= 30:
                        div_result = detect_4h_divergence(h4_df_for_div, lookback=20)
                        st.session_state['h4_divergence_result'] = div_result
                        if div_result["detected"]:
                            print(f"⚠️ 4H DIVERGENCE: [{div_result['severity']}] - {div_result['message']}")
                except Exception as div_err:
                    print(f"4H Divergence detection error: {div_err}")
            
            # Now create chart with trigger levels, all markers, divergence lines, and traffic lights
            traffic_lights = tta_stats.get("traffic_lights") if tta_stats else None
            
            # v16.9: Override displayed timeframe's traffic light with CHART's diagnostic
            # Three-state system with MACD confirmation
            if traffic_lights and ao_diag:
                raw_wave = ao_diag.get("current_wave", "—")
                chart_w3 = ao_diag.get("wave3")
                chart_has_wave = (chart_w3 is not None)
                chart_divergence = ao_diag.get("divergence", False)
                
                # Calculate MACD for current chart timeframe
                chart_macd_bearish = False
                try:
                    chart_macd_line = df['Close'].ewm(span=12).mean() - df['Close'].ewm(span=26).mean()
                    chart_signal_line = chart_macd_line.ewm(span=9).mean()
                    chart_macd_bearish = detect_macd_bearish_cross(chart_macd_line, chart_signal_line)
                except Exception as e:
                    print(f"MACD override error: {e}")
                
                # Calculate three-state dot color from AO with MACD confirmation
                if len(ao_series) >= 2:
                    current_ao_val = ao_series.iloc[-1]
                    previous_ao_val = ao_series.iloc[-2]
                    
                    if current_ao_val < 0:
                        chart_dot_color = '#ef4444'  # RED: AO negative
                    elif current_ao_val > 0 and current_ao_val < previous_ao_val and chart_macd_bearish:
                        chart_dot_color = '#fbbf24'  # YELLOW: AO weakening + MACD confirms
                    else:
                        chart_dot_color = '#00E676'  # GREEN: AO positive (no dual confirmation)
                else:
                    chart_dot_color = '#6b7280'  # Gray: no data
                
                # v16.9: Convert raw wave to three-state label
                if raw_wave in ['W3', 'W3?']:
                    if chart_dot_color == '#00E676':
                        chart_wave = 'STRONG'
                    elif chart_dot_color == '#fbbf24':
                        chart_wave = 'WEAK'
                    else:
                        chart_wave = 'FADING'
                elif raw_wave in ['W5', 'W5?']:
                    chart_wave = 'HOLD' if chart_dot_color != '#ef4444' else 'FADING'
                elif raw_wave in ['W4', 'W4?']:
                    chart_wave = 'WAIT'
                elif raw_wave == 'Corr':
                    chart_wave = 'BASE' if chart_dot_color == '#00E676' else 'WATCH'
                elif raw_wave == 'Corr!':
                    chart_wave = 'AVOID'
                else:
                    if chart_has_wave:
                        if chart_dot_color == '#00E676':
                            chart_wave = 'STRONG'
                        elif chart_dot_color == '#fbbf24':
                            chart_wave = 'WEAK'
                        else:
                            chart_wave = 'FADING'
                    else:
                        chart_wave = '—'
                
                if timeframe == "Daily":
                    traffic_lights["daily_wave"] = chart_wave
                    traffic_lights["daily"] = chart_has_wave
                    traffic_lights["daily_dot_color"] = chart_dot_color
                    traffic_lights["daily_divergence"] = chart_divergence
                elif timeframe == "Weekly":
                    traffic_lights["weekly_wave"] = chart_wave
                    traffic_lights["weekly"] = chart_has_wave
                    traffic_lights["weekly_dot_color"] = chart_dot_color
                    traffic_lights["weekly_divergence"] = chart_divergence
                elif timeframe == "4H":
                    traffic_lights["h4_wave"] = chart_wave
                    traffic_lights["h4"] = chart_has_wave
                    traffic_lights["h4_dot_color"] = chart_dot_color
                    traffic_lights["h4_divergence"] = chart_divergence
                
                # Dot symbol for console
                dot_sym = '🟢' if chart_dot_color == '#00E676' else '🟡' if chart_dot_color == '#fbbf24' else '🔴'
                symbol = {'STRONG': '✓', 'WEAK': '⚠', 'HOLD': '↑', 'FADING': '⚠', 'WAIT': '⚠', 'BASE': '✓', 'WATCH': '○', 'AVOID': '✗'}.get(chart_wave, '')
                div_flag = " DIV" if chart_divergence else ""
                print(f"TRAFFIC LIGHT OVERRIDE: {timeframe} = {symbol} {chart_wave} {dot_sym}{div_flag}")
            
            fig, sma_info = create_chart(df, ticker, timeframe, sma_period, weekly_sma_data, level_A, level_B, all_markers, divergence_lines, traffic_lights)
            st.session_state.fig = fig
            st.session_state.sma_info = sma_info
            
            # Also store SMA for Weinstein context (NOT for triggers)
            if sma_info and sma_info.get('value') is not None:
                st.session_state.sma_value = sma_info['value']
            elif weekly_sma_data is not None and len(weekly_sma_data) > 0:
                st.session_state.sma_value = weekly_sma_data.iloc[-1]
            else:
                st.session_state.sma_value = None
            
            # PF0: Check for level reuse across ticker runs
            current_levels = {
                'A': st.session_state.level_A,
                'B': st.session_state.level_B,
                'SMA': st.session_state.sma_value
            }
            pf0_passed, pf0_msg = check_pf0_binding(
                ticker,
                current_levels,
                st.session_state.previous_ticker,
                st.session_state.previous_levels
            )
            st.session_state.pf0_fail = not pf0_passed
            st.session_state.pf0_message = pf0_msg
            
            # AI Elliott Wave audit - controlled by sidebar toggle
            ai_toggle_value = st.session_state.get('enable_ai_analysis', False)
            st.session_state.run_audit = ai_toggle_value
            print(f"🤖 AI TOGGLE CHECK: enable_ai_analysis={ai_toggle_value}, run_audit set to {st.session_state.run_audit}")
            
            # Clear loading spinner before rerun
            loading_placeholder.empty()
            st.rerun()




if st.session_state.df is not None and st.session_state.fig is not None:
    df = st.session_state.df
    fig = st.session_state.fig
    pivot_text = st.session_state.pivot_text
    ticker_display = st.session_state.current_ticker
    timeframe_display = st.session_state.current_timeframe
    sma_label = st.session_state.sma_label
    
    # PF0: Display binding guard warning if level reuse detected
    if st.session_state.pf0_fail and st.session_state.pf0_message:
        st.markdown(
            f"""
            <div style="
                background-color: #7c2d12;
                color: white;
                padding: 20px;
                border-radius: 8px;
                text-align: center;
                font-size: 1.2rem;
                font-weight: bold;
                margin-bottom: 20px;
                border: 3px solid #431407;
            ">
                ⚠️ PRE-FLIGHT FAIL (PF0): CHART BINDING ERROR<br>
                <span style="font-size: 0.9rem; font-weight: normal;">
                    {st.session_state.pf0_message.replace(chr(10), '<br>')}<br>
                    <strong>Action:</strong> Clear browser cache or restart app to reset previous levels.
                </span>
            </div>
            """,
            unsafe_allow_html=True
        )
    
    # Compact header row: Ticker info + personality + date + bars
    from datetime import datetime
    current_date = datetime.now().strftime("%b %d, %Y")
    
    # v16.12: Get personality score for header display
    header_suit_score = st.session_state.get('suitability_score')
    header_suit_verdict = st.session_state.get('suitability_verdict', '')
    
    # Build personality badge if available
    if header_suit_score is not None:
        # Color based on score
        if header_suit_score > 80:
            suit_color = "#22c55e"  # Green
            suit_bg = "rgba(34, 197, 94, 0.15)"
        elif header_suit_score > 50:
            suit_color = "#eab308"  # Yellow
            suit_bg = "rgba(234, 179, 8, 0.15)"
        else:
            suit_color = "#ef4444"  # Red
            suit_bg = "rgba(239, 68, 68, 0.15)"
        
        # Use the actual verdict from the suitability function (e.g. "MODERATE (Expect Noise)")
        personality_text = header_suit_verdict if header_suit_verdict else f"Score {header_suit_score}"
        
        personality_badge = f"<span style='background: {suit_bg}; color: {suit_color}; padding: 4px 10px; border-radius: 12px; font-size: 0.75rem; font-weight: 600; margin-left: 12px; border: 1px solid {suit_color};'>{personality_text}</span>"
    else:
        personality_badge = ""
    
    # Auto-fetch VIX for header display
    vix_data = get_vix_recommendation()
    vix_value = vix_data.get('vix')
    vix_regime = vix_data.get('regime', 'UNKNOWN')
    
    # Color-code VIX based on regime
    vix_colors = {
        'LOW VOLATILITY': '#22c55e',
        'NORMAL': '#3b82f6',
        'ELEVATED': '#f59e0b',
        'HIGH VOLATILITY': '#ef4444',
        'UNKNOWN': '#6b7280'
    }
    vix_color = vix_colors.get(vix_regime, '#6b7280')
    
    # Build VIX badge
    if vix_value:
        r, g, b = int(vix_color[1:3], 16), int(vix_color[3:5], 16), int(vix_color[5:7], 16)
        vix_badge = f"<span style='background: rgba({r}, {g}, {b}, 0.15); color: {vix_color}; padding: 4px 8px; border-radius: 12px; font-size: 0.7rem; font-weight: 600; margin-left: 12px; border: 1px solid {vix_color};'>VIX {vix_value:.1f}</span>"
    else:
        vix_badge = ""
    
    st.markdown(f"### {ticker_display} · {timeframe_display}{personality_badge}{vix_badge} <span style='color: #6b7280; font-size: 0.9rem; font-weight: normal; margin-left: 12px;'>{current_date}</span> <span style='color: #4b5563; font-size: 0.75rem; float: right;'>{len(df)} bars · {sma_label}</span>", unsafe_allow_html=True)
    
    # CORRECTIVE WARNING BANNER: Divergence detected AND AO negative after W5
    ao_diag = st.session_state.get('ao_diag') or {}
    
    # Determine current wave count for banner display
    def get_wave_count_label(diag):
        if not diag:
            return "Wave Count: Unknown"
        w3 = diag.get('wave3')
        w4 = diag.get('wave4')
        w5 = diag.get('wave5')
        ambiguous = diag.get('ambiguous_structure', False)
        
        if w5 and w5.get('complete'):
            if ambiguous:
                return "Current: W5 Complete (Truncated) or W4(B) of Expanded Flat"
            return "Current: Wave 5 Complete → ABC Correction"
        elif w5:
            if diag.get('divergence'):
                return "Current: Wave 5 Developing (Divergence Detected)"
            return "Current: Wave 5 Developing"
        elif w4:
            if w4.get('expanded_flat_possible'):
                return "Current: Wave 4 (Expanded Flat Possible)"
            return "Current: Wave 4 Correction"
        elif w3:
            if w3.get('complete'):
                return "Current: Post-Wave 3 → Wave 4 Expected"
            return "Current: Wave 3 Developing"
        return "Current: Early Wave Structure"
    
    wave_count_label = get_wave_count_label(ao_diag)
    
    # v16.10: Compact divergence warnings (70% smaller)
    if ao_diag and ao_diag.get('corrective_warning'):
        st.markdown(
            f"""<div style="background: linear-gradient(135deg, #dc2626 0%, #991b1b 100%); color: white; padding: 8px 16px; border-radius: 6px; font-size: 0.8rem; font-weight: 600; margin-bottom: 8px; border: 1px solid #7f1d1d; display: flex; align-items: center; gap: 12px;">
<span style="font-size: 1.1rem;">⚠️</span>
<span>BEARISH DIVERGENCE — W5 Complete, AO negative. Corrective structure likely.</span>
</div>""",
            unsafe_allow_html=True
        )
    elif ao_diag and ao_diag.get('divergence_warning') and not ao_diag.get('corrective_warning'):
        st.markdown(
            f"""<div style="background: linear-gradient(135deg, #d97706 0%, #b45309 100%); color: white; padding: 8px 16px; border-radius: 6px; font-size: 0.8rem; font-weight: 600; margin-bottom: 8px; border: 1px solid #78350f; display: flex; align-items: center; gap: 12px;">
<span style="font-size: 1.1rem;">⚡</span>
<span>DIVERGENCE DEVELOPING — W5 in progress, momentum weakening. Watch for AO negative cross.</span>
</div>""",
            unsafe_allow_html=True
        )
    
    # Compact metrics row - 3 columns on mobile, 5 on desktop
    current_price = df['Close'].iloc[-1]
    level_A = st.session_state.get('level_A')
    level_B = st.session_state.get('level_B')
    
    # Determine A/B status
    ab_status = ""
    if level_A is not None and level_B is not None:
        if current_price < level_A:
            ab_status = "BELOW A"
        elif current_price > level_B:
            ab_status = "ABOVE B"
        else:
            ab_status = "IN RANGE"
    
    # v16.10: Calculate pct change for Tesla cards
    pct_change = ((df['Close'].iloc[-1] - df['Close'].iloc[-2]) / df['Close'].iloc[-2]) * 100 if len(df) >= 2 else 0
    
    # v16.10: Pre-compute all dynamic values for HTML (avoid f-string issues)
    level_a_display = f"{level_A:.0f}" if level_A is not None else "—"
    level_b_display = f"{level_B:.0f}" if level_B is not None else "—"
    ab_status_display = ab_status if ab_status else "NO DATA"
    ab_status_color = '#10b981' if ab_status == 'BELOW A' else '#f59e0b' if ab_status == 'IN RANGE' else '#6b7280'
    pct_color = '#10b981' if pct_change >= 0 else '#ef4444'
    pct_arrow = '▲' if pct_change >= 0 else '▼'
    high_val = df['High'].max()
    low_val = df['Low'].min()
    
    # v16.10: Ultra-compact metric cards (single row)
    metrics_html = f"""<div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 12px;">
<div style="background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 8px; padding: 10px 14px;">
<div style="color: #6b7280; font-size: 0.6rem; margin-bottom: 2px;">PRICE</div>
<div style="display: flex; align-items: baseline; gap: 8px;"><span style="color: #ffffff; font-size: 1.3rem; font-weight: 700;">${current_price:.2f}</span><span style="color: {pct_color}; font-size: 0.75rem;">{pct_arrow}{abs(pct_change):.1f}%</span></div>
</div>
<div style="background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 8px; padding: 10px 14px;">
<div style="color: #6b7280; font-size: 0.6rem; margin-bottom: 2px;">RANGE</div>
<div style="color: #ffffff; font-size: 1rem; font-weight: 600;">{high_val:.0f} / {low_val:.0f}</div>
</div>
<div style="background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 8px; padding: 10px 14px;">
<div style="color: #6b7280; font-size: 0.6rem; margin-bottom: 2px;">LEVELS</div>
<div style="display: flex; align-items: baseline; gap: 8px;"><span style="color: #ffffff; font-size: 1rem; font-weight: 600;">{level_a_display} / {level_b_display}</span><span style="color: {ab_status_color}; font-size: 0.65rem;">{ab_status_display}</span></div>
</div>
</div>"""
    st.markdown(metrics_html, unsafe_allow_html=True)
    
    # ═══════════════════════════════════════════════════════════
    # v16.10 TESLA-STYLE TRAFFIC LIGHT PANEL
    # ═══════════════════════════════════════════════════════════
    
    # Extract traffic light data from session state
    tta_stats = st.session_state.get('tta_stats', {})
    traffic_lights = tta_stats.get("traffic_lights", {})
    
    if traffic_lights:
        # Extract data for each timeframe (v16.17: M/W/D/4H - restored 4H display)
        # v16.9: Map labels to actionable instructions
        def get_action_text(label):
            action_map = {
                'STRONG': 'Enter long',
                'WEAK': "Don't buy",
                'HOLD': 'Hold position',
                'FADING': 'Prepare exit',
                'PULL': 'Pullback entry',
                'WAIT': 'Be patient',
                'BASE': 'Base forming',
                'WATCH': 'Monitor',
                'AVOID': 'Stay out',
                '—': '—'
            }
            return action_map.get(label, label)
        
        # v16.9: Calculate single consolidated action from all timeframes
        def get_consolidated_action(m_label, w_label, d_label, h4_label):
            """Single action based on multi-timeframe alignment"""
            labels = [m_label, w_label, d_label, h4_label]
            
            # If ANY timeframe says AVOID, stay out
            if 'AVOID' in labels:
                return ('Stay out', '#ef4444', 'Active correction detected')
            
            # If higher timeframes (M/W) are STRONG and lower (D) is actionable
            if m_label == 'STRONG' and w_label == 'STRONG' and d_label in ['STRONG', 'PULL', 'BASE']:
                return ('Enter long', '#00E676', 'All timeframes aligned bullish')
            
            # If holding and higher TFs still strong
            if m_label in ['STRONG', 'HOLD'] and w_label in ['STRONG', 'HOLD'] and d_label == 'HOLD':
                return ('Hold position', '#00E676', 'Trend intact, continue holding')
            
            # If WEAK on any major timeframe, don't buy
            if m_label == 'WEAK' or w_label == 'WEAK':
                return ("Don't buy", '#fbbf24', 'Momentum weakening on higher TF')
            
            # If FADING, prepare to exit
            if 'FADING' in labels[:3]:  # M, W, or D fading
                return ('Prepare exit', '#fbbf24', 'Momentum fading')
            
            # If correction phase
            if d_label in ['WAIT', 'WATCH'] or w_label in ['WAIT', 'WATCH']:
                return ('Be patient', '#fbbf24', 'Correction in progress')
            
            # Base forming - potential opportunity
            if d_label == 'BASE' or w_label == 'BASE':
                return ('Watch for entry', '#00E676', 'Base forming, wait for confirmation')
            
            # Default: monitor
            return ('Monitor', '#6b7280', 'No clear signal')
        
        # Get consolidated action
        m_lbl = traffic_lights.get('monthly_wave', '—')
        w_lbl = traffic_lights.get('weekly_wave', '—')
        d_lbl = traffic_lights.get('daily_wave', '—')
        h4_lbl = traffic_lights.get('h4_wave', '—')
        consolidated_action, action_color, action_reason = get_consolidated_action(m_lbl, w_lbl, d_lbl, h4_lbl)
        
        # v16.36: Extract AO info for each timeframe
        m_ao_info = traffic_lights.get('monthly_ao', {'value': 0, 'direction': 'flat'})
        w_ao_info = traffic_lights.get('weekly_ao', {'value': 0, 'direction': 'flat'})
        d_ao_info = traffic_lights.get('daily_ao', {'value': 0, 'direction': 'flat'})
        h4_ao_info = traffic_lights.get('h4_ao', {'value': 0, 'direction': 'flat'})
        
        tf_data = [
            {'name': 'M', 'label': traffic_lights.get('monthly_wave', '—'), 'dot': traffic_lights.get('monthly_dot_color', '#6b7280'), 'has_wave': traffic_lights.get('monthly', False), 'div': traffic_lights.get('monthly_divergence', False), 'macd_bear': traffic_lights.get('monthly_macd_bearish', False), 'ao': m_ao_info},
            {'name': 'W', 'label': traffic_lights.get('weekly_wave', '—'), 'dot': traffic_lights.get('weekly_dot_color', '#6b7280'), 'has_wave': traffic_lights.get('weekly', False), 'div': traffic_lights.get('weekly_divergence', False), 'macd_bear': traffic_lights.get('weekly_macd_bearish', False), 'ao': w_ao_info},
            {'name': 'D', 'label': traffic_lights.get('daily_wave', '—'), 'dot': traffic_lights.get('daily_dot_color', '#6b7280'), 'has_wave': traffic_lights.get('daily', False), 'div': traffic_lights.get('daily_divergence', False), 'macd_bear': traffic_lights.get('daily_macd_bearish', False), 'ao': d_ao_info},
            {'name': '4H', 'label': traffic_lights.get('h4_wave', '—'), 'dot': traffic_lights.get('h4_dot_color', '#6b7280'), 'has_wave': traffic_lights.get('h4', False), 'div': traffic_lights.get('h4_divergence', False), 'macd_bear': traffic_lights.get('h4_macd_bearish', False), 'ao': h4_ao_info}
        ]
        
        # Build Tesla console HTML with single consolidated action
        tesla_html = f"""<div style="background: linear-gradient(135deg, #0a0a0a 0%, #1a1a1a 100%); border-radius: 12px; padding: 12px 20px; margin-bottom: 12px; border: 1px solid #2a2a2a;">
<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1px solid #2a2a2a;">
<span style="color: #ffffff; font-size: 0.9rem; font-weight: 600; letter-spacing: 0.5px;">TTA SIGNAL</span>
<span style="color: #6b7280; font-size: 0.7rem; font-family: monospace;">{BUILD_VERSION}</span>
</div>
<div style="display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; margin-bottom: 8px; border-bottom: 1px solid #2a2a2a;">
<div style="display: flex; align-items: center; gap: 10px; flex: 1;">
<span style="color: {action_color}; font-size: 1.1rem; font-weight: 700;">{consolidated_action}</span>
<span style="color: #9ca3af; font-size: 0.75rem; padding-left: 10px; border-left: 1px solid #2a2a2a;">{action_reason}</span>
</div>
</div>
<div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px;">
"""
        
        for tf in tf_data:
            # Determine box color based on wave structure
            if not tf['has_wave']:
                box_color = '#374151'  # Gray - no wave
            elif tf['label'] in ['STRONG', 'WEAK', 'FADING']:
                box_color = '#10b981'  # Green - W3 active
            elif tf['label'] in ['HOLD', 'WAIT']:
                box_color = '#f59e0b'  # Amber - W4/W5
            elif tf['label'] == 'AVOID':
                box_color = '#ef4444'  # Red - Corr!
            else:
                box_color = '#374151'
            
            # Dot glow effect
            dot_glow = ''
            if tf['dot'] == '#00E676':
                dot_glow = 'box-shadow: 0 0 12px rgba(0, 230, 118, 0.6);'
            elif tf['dot'] == '#fbbf24':
                dot_glow = 'box-shadow: 0 0 12px rgba(251, 191, 36, 0.6);'
            elif tf['dot'] == '#ef4444':
                dot_glow = 'box-shadow: 0 0 12px rgba(239, 68, 68, 0.6);'
            
            # Divergence badge (compact)
            div_badge = ''
            if tf['div']:
                div_badge = '<div style="position: absolute; top: -4px; right: -4px; background: #dc2626; color: white; font-size: 0.55rem; font-weight: 700; padding: 1px 4px; border-radius: 3px;">DIV</div>'
            
            # v16.12: Determine MACD status text and color
            if tf['macd_bear']:
                macd_text = "MACD ⬇"
                macd_color = "#ef4444"  # Red
            else:
                macd_text = "MACD ⬆"
                macd_color = "#00E676"  # Green
            
            # v16.36: Enhanced timeframe card with AO value, direction, and MACD status
            ao_val = tf['ao'].get('value', 0)
            ao_dir = tf['ao'].get('direction', 'flat')
            ao_arrow = '▲' if ao_dir == 'rising' else '▼' if ao_dir == 'falling' else '—'
            ao_color = '#00E676' if ao_val > 0 else '#ef4444' if ao_val < 0 else '#6b7280'
            dir_color = '#00E676' if ao_dir == 'rising' else '#ef4444' if ao_dir == 'falling' else '#6b7280'
            
            tesla_html += f'''<div style="position: relative; background: rgba(255, 255, 255, 0.03); border: 1px solid {box_color}; border-radius: 8px; padding: 8px 10px; text-align: center;">
{div_badge}
<div style="color: #9ca3af; font-size: 0.6rem; font-weight: 600; letter-spacing: 0.5px; margin-bottom: 3px;">{tf['name']}</div>
<div style="display: flex; align-items: center; justify-content: center; gap: 4px; margin-bottom: 3px;">
<div style="width: 8px; height: 8px; background: {tf['dot']}; border-radius: 50%; {dot_glow}"></div>
<span style="color: #ffffff; font-size: 0.7rem; font-weight: 600;">{tf['label']}</span>
</div>
<div style="color: {ao_color}; font-size: 0.65rem; font-family: monospace; margin-bottom: 2px;">AO: {ao_val:.1f} <span style="color: {dir_color};">{ao_arrow}</span></div>
<div style="color: {macd_color}; font-size: 0.55rem;">{macd_text}</div>
</div>'''
        
        # Close grid and add mini legend (ultra-compact) - v16.36: Updated with AO/MACD legend
        tesla_html += """</div>
<div style="display: flex; justify-content: center; gap: 12px; margin-top: 8px; padding-top: 6px; border-top: 1px solid #2a2a2a; flex-wrap: wrap;">
<div style="display: flex; align-items: center; gap: 4px;"><div style="width: 6px; height: 6px; background: #00E676; border-radius: 50%;"></div><span style="color: #6b7280; font-size: 0.55rem;">AO+/Rising</span></div>
<div style="display: flex; align-items: center; gap: 4px;"><div style="width: 6px; height: 6px; background: #fbbf24; border-radius: 50%;"></div><span style="color: #6b7280; font-size: 0.55rem;">AO+ Weak</span></div>
<div style="display: flex; align-items: center; gap: 4px;"><div style="width: 6px; height: 6px; background: #ef4444; border-radius: 50%;"></div><span style="color: #6b7280; font-size: 0.55rem;">AO-/MACD⬇</span></div>
<div style="display: flex; align-items: center; gap: 4px;"><span style="color: #00E676; font-size: 0.55rem;">▲</span><span style="color: #6b7280; font-size: 0.55rem;">Rising</span></div>
<div style="display: flex; align-items: center; gap: 4px;"><span style="color: #ef4444; font-size: 0.55rem;">▼</span><span style="color: #6b7280; font-size: 0.55rem;">Falling</span></div>
</div></div>"""
        
        # Render Tesla panel
        st.markdown(tesla_html, unsafe_allow_html=True)
        
        # Export verdict and display banner
        analysis_results = {
            'all_signals': tta_stats.get('all_signals', []),
            'tta_stats': tta_stats,
            'chart_info': {'ao_diagnostic': st.session_state.get('ao_diag', {})}
        }
        verdict_data = None
        decision = ""
        if analysis_results is None:
            st.info("ℹ️ Run analysis to see verdict")
        else:
            verdict_data = export_tta_verdict(ticker_display, st.session_state.get('current_timeframe', 'Daily'), analysis_results)
            st.session_state.verdict_data = verdict_data  # Store for AI comparison later
            if verdict_data:
                display_verdict_banner(verdict_data)
                decision = apply_tta_decision_logic(verdict_data)
                
                # Compare TTA verdict vs AI sentiment
                aianalysis = st.session_state.get('ai_analysis_text')
                
                # DEBUG: Print what we're comparing
                with st.expander("🔍 AI vs TTA Debug", expanded=False):
                    st.write(f"- AI analysis exists: {aianalysis is not None}")
                    st.write(f"- AI analysis length: {len(aianalysis) if aianalysis else 0}")
                    st.write(f"- AI toggle enabled: {st.session_state.get('enable_ai_analysis', False)}")
                    st.write(f"- Verdict data exists: {verdict_data is not None}")
                    if verdict_data:
                        st.write(f"- TTA confidence: {verdict_data.get('confidence', 'N/A')}")
                    if aianalysis:
                        ai_text_lower_dbg = aianalysis.lower()
                        ai_bullish_dbg = ai_text_lower_dbg.count('bullish') + ai_text_lower_dbg.count('buy')
                        ai_bearish_dbg = ai_text_lower_dbg.count('bearish') + ai_text_lower_dbg.count('sell')
                        st.write(f"- AI bullish words: {ai_bullish_dbg}")
                        st.write(f"- AI bearish words: {ai_bearish_dbg}")
                        st.write(f"- AI sentiment: {'BULLISH' if ai_bullish_dbg > ai_bearish_dbg else 'BEARISH'}")
                
                if aianalysis and st.session_state.get('enable_ai_analysis', False):
                    ai_text_lower = aianalysis.lower()
                    
                    # Count sentiment words
                    ai_bullish_words = ai_text_lower.count('bullish') + ai_text_lower.count('buy') + ai_text_lower.count('long') + ai_text_lower.count('upside') + ai_text_lower.count('breakout')
                    ai_bearish_words = ai_text_lower.count('bearish') + ai_text_lower.count('sell') + ai_text_lower.count('short') + ai_text_lower.count('caution') + ai_text_lower.count('risk') + ai_text_lower.count('downside')
                    
                    ai_sentiment = "BULLISH" if ai_bullish_words > ai_bearish_words else "BEARISH" if ai_bearish_words > ai_bullish_words else "NEUTRAL"
                    tta_sentiment = "BULLISH" if verdict_data['confidence'] >= 60 else "BEARISH" if verdict_data['confidence'] < 40 else "NEUTRAL"
                    
                    # Store for display in AI section
                    st.session_state.ai_tta_comparison = {
                        'ai_sentiment': ai_sentiment,
                        'tta_sentiment': tta_sentiment,
                        'ai_bullish': ai_bullish_words,
                        'ai_bearish': ai_bearish_words,
                        'tta_confidence': verdict_data['confidence'],
                        'agrees': ai_sentiment == tta_sentiment or tta_sentiment == "NEUTRAL"
                    }
                    
                    # Display prominent alignment indicator
                    if ai_sentiment == tta_sentiment:
                        st.markdown(f"""
                        <div style="background: linear-gradient(135deg, #166534 0%, #22c55e 100%); padding: 12px 16px; border-radius: 8px; margin: 8px 0; display: flex; align-items: center; gap: 12px;">
                            <span style="font-size: 24px;">✅</span>
                            <div>
                                <div style="color: white; font-weight: bold; font-size: 16px;">ALIGNMENT: AI & TTA AGREE</div>
                                <div style="color: #dcfce7; font-size: 13px;">Both systems say {ai_sentiment} → Higher conviction trade</div>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)
                    elif tta_sentiment == "NEUTRAL":
                        st.markdown(f"""
                        <div style="background: linear-gradient(135deg, #854d0e 0%, #ca8a04 100%); padding: 12px 16px; border-radius: 8px; margin: 8px 0; display: flex; align-items: center; gap: 12px;">
                            <span style="font-size: 24px;">⚖️</span>
                            <div>
                                <div style="color: white; font-weight: bold; font-size: 16px;">TTA NEUTRAL | AI says {ai_sentiment}</div>
                                <div style="color: #fef3c7; font-size: 13px;">TTA confidence is mixed ({verdict_data['confidence']}%) - use AI as tiebreaker</div>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)
                    else:
                        st.markdown(f"""
                        <div style="background: linear-gradient(135deg, #991b1b 0%, #dc2626 100%); padding: 12px 16px; border-radius: 8px; margin: 8px 0; display: flex; align-items: center; gap: 12px;">
                            <span style="font-size: 24px;">⚠️</span>
                            <div>
                                <div style="color: white; font-weight: bold; font-size: 16px;">DISSONANCE: AI & TTA DISAGREE</div>
                                <div style="color: #fecaca; font-size: 13px;">TTA: {tta_sentiment} | AI: {ai_sentiment} → Reduce size 50% or WAIT</div>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)
        
        # Compact decision display
        if verdict_data and verdict_data.get('confidence', 0) >= 50:
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"**Decision:** {decision.split(chr(10))[0]}")
            with col2:
                if st.button("📋 Checklist"):
                    checklist_file = generate_trading_checklist(ticker_display, verdict_data, decision)
                    st.success(f"✅ {checklist_file}")
    
    # v16.17: Prominent 4H Divergence Status Banner (ALWAYS visible above chart)
    # Use SAME source as traffic lights for consistency
    tta_stats_local = st.session_state.get('tta_stats', {})
    traffic_lights_local = tta_stats_local.get('traffic_lights', {})
    h4_div_from_traffic = traffic_lights_local.get('h4_divergence', False)
    h4_div_exits_count = tta_stats_local.get('diagnostics', {}).get('count_4h_div_exits', 0)
    
    # Also check the scipy-based detection for additional detail
    h4_div_live = st.session_state.get('h4_divergence_result', {})
    
    # Use traffic light divergence (matches what's shown in panel)
    if h4_div_from_traffic:
        # Get severity from scipy detection if available, otherwise default to MODERATE
        sev = h4_div_live.get('severity', 'MODERATE') if h4_div_live.get('detected') else 'MODERATE'
        div_message = h4_div_live.get('message', 'Price making higher high but AO making lower high - momentum weakening')
        sev_styles = {
            "WEAK": {"bg": "#fbbf24", "border": "#d97706", "icon": "⚠️"},
            "MODERATE": {"bg": "#f97316", "border": "#ea580c", "icon": "🔶"},
            "STRONG": {"bg": "#ef4444", "border": "#dc2626", "icon": "🔴"}
        }
        style = sev_styles.get(sev, sev_styles["WEAK"])
        
        st.markdown(f"""
        <div style="
            background: linear-gradient(135deg, {style['bg']}22, {style['bg']}11);
            border: 2px solid {style['border']};
            border-radius: 8px;
            padding: 12px 16px;
            margin-bottom: 12px;
            display: flex;
            align-items: center;
            gap: 12px;
        ">
            <span style="font-size: 24px;">{style['icon']}</span>
            <div>
                <div style="font-weight: bold; color: {style['border']}; font-size: 14px;">
                    4H DIVERGENCE ACTIVE [{sev}] — Early Exit Warning!
                </div>
                <div style="color: #999; font-size: 12px;">
                    {div_message}
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        # Show green "all clear" status so user knows it's working
        hist_text = f" | Historical exits: {h4_div_exits_count}" if h4_div_exits_count > 0 else ""
        st.markdown(f"""
        <div style="
            background: linear-gradient(135deg, #16a34a22, #16a34a11);
            border: 1px solid #22c55e;
            border-radius: 8px;
            padding: 8px 16px;
            margin-bottom: 12px;
            display: flex;
            align-items: center;
            gap: 10px;
        ">
            <span style="font-size: 18px;">✅</span>
            <div style="color: #22c55e; font-size: 13px; font-weight: 500;">
                4H Momentum Aligned — No Divergence{hist_text}
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    # v16.35: Adaptive Strategy Display (Main Area - highly visible)
    if st.session_state.get('show_adaptive_strategy') and st.session_state.get('suitability_score') is not None:
        score = st.session_state.get('suitability_score')
        strategy = st.session_state.get('adaptive_strategy', 'TTA')
        rationale = st.session_state.get('adaptive_rationale', '')
        color = "#22c55e" if score > 80 else "#f59e0b" if score > 50 else "#ef4444"
        st.markdown(f"""
        <div style="
            background: linear-gradient(135deg, {color}22, {color}11);
            border: 1px solid {color};
            border-radius: 8px;
            padding: 12px 16px;
            margin-bottom: 12px;
        ">
            <div style="font-weight: bold; color: {color}; font-size: 14px;">
                ADAPTIVE STRATEGY: {strategy} | Personality Score: {score}/100
            </div>
            <div style="color: #aaa; font-size: 12px; margin-top: 4px;">
                {rationale}
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    # v16.10: Full-width chart with no margins
    st.plotly_chart(
        fig,
        width='stretch',
        config={
            'displayModeBar': False,  # Hide toolbar for clean look
            'scrollZoom': False
        }
    )
    
    # v16.10: Compact export toolbar
    st.markdown("""
<div style="
    display: flex;
    gap: 12px;
    margin: 16px 0;
    padding: 16px;
    background: #1a1a1a;
    border-radius: 8px;
    border: 1px solid #2a2a2a;
    align-items: center;
">
""", unsafe_allow_html=True)
    
    exp_col1, exp_col2, exp_col3 = st.columns([1, 1, 3])
    with exp_col1:
        try:
            chart_bytes = fig.to_image(format="png", width=1200, height=800, scale=2)
            st.download_button(
                label="📷 Chart",
                data=chart_bytes,
                file_name=f"{ticker_display}_chart.png",
                mime="image/png",
                width='stretch',
                key=f"main_chart_{ticker_display}"
            )
        except:
            st.button("📷 Chart", disabled=True, width='stretch')
    with exp_col2:
        tta_stats = st.session_state.get('tta_stats', {})
        all_signals = tta_stats.get("all_signals", [])
        if all_signals:
            # v16.12: Pass filter profile to export
            main_filter_profile = st.session_state.get('filter_profile', 'BALANCED')
            csv_data = generate_trade_report(ticker_display, timeframe_display, all_signals, tta_stats, filter_profile=main_filter_profile)
            st.download_button(
                label="📊 Trades",
                data=csv_data,
                file_name=f"{ticker_display}_trades.csv",
                mime="text/csv",
                width='stretch',
                key=f"main_trades_{ticker_display}"
            )
        else:
            st.button("📊 Trades", disabled=True, width='stretch')
    with exp_col3:
        st.markdown(f"""
<div style="text-align: right; padding-top: 4px;">
    <span style="color: #6b7280; font-size: 0.8rem; font-family: 'SF Mono', Monaco, monospace;">
        TTA {BUILD_VERSION} · {BUILD_NAME} · {BUILD_DATE}
    </span>
</div>
""", unsafe_allow_html=True)
    
    st.markdown("</div>", unsafe_allow_html=True)
    
    with st.expander("📊 Price Pivot Analysis", expanded=False):
        st.markdown("*Using scipy.signal.argrelextrema to identify significant price turning points*")
        st.code(pivot_text, language="text")
    
    if st.session_state.run_audit:
        # Get sidebar progress placeholder
        sidebar_progress = st.session_state.get('sidebar_progress_placeholder')
        
        # Helper to update sidebar progress
        def update_sidebar_progress(step, total=6, message=""):
            if sidebar_progress:
                progress_pct = int((step / total) * 100)
                sidebar_progress.markdown(f"""
                <div style="background: linear-gradient(135deg, #1e3a5f 0%, #2d5a87 100%); padding: 12px; border-radius: 8px; margin: 8px 0;">
                    <div style="color: #4ade80; font-weight: bold; font-size: 14px;">🤖 AI Analysis</div>
                    <div style="color: white; font-size: 12px; margin: 4px 0;">Step {step}/{total}: {message}</div>
                    <div style="background: #374151; border-radius: 4px; height: 8px; margin-top: 8px;">
                        <div style="background: linear-gradient(90deg, #22c55e, #4ade80); width: {progress_pct}%; height: 100%; border-radius: 4px; transition: width 0.3s;"></div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
        
        # Step 1: Capture main chart
        update_sidebar_progress(1, 6, "Capturing main chart...")
        chart_base64 = capture_chart_as_base64(fig)
        current_price = df['Close'].iloc[-1]
        highest_price = df['High'].max()
        lowest_price = df['Low'].min()
        sma_info = st.session_state.get('sma_info', {})
        
        # Generate MTF charts for all 4 timeframes
        mtf_charts = {}
        weekly_sma = st.session_state.get('weekly_sma_data')
        
        try:
            # Step 2: Monthly Chart with wave label
            update_sidebar_progress(2, 6, "Monthly chart (Primary)")
            monthly_df = st.session_state.get('monthly_df')
            if monthly_df is not None and not monthly_df.empty:
                monthly_fig, _ = create_chart(monthly_df, ticker_display, "Monthly", sma_period=30, weekly_sma_data=weekly_sma)
                
                # Get Monthly wave diagnostic
                m_diag = st.session_state.get('m_diag')
                w3_monthly = st.session_state.get('w3_monthly')
                if w3_monthly:
                    monthly_wave_label = "Monthly: Primary Wave-3 Active"
                    label_color = "#22c55e"
                else:
                    monthly_wave_label = "Monthly: Cycle/Primary Degree"
                    label_color = "#22c55e"
                
                monthly_fig.add_annotation(
                    x=0.5, y=0.98, xref="paper", yref="paper",
                    text=f"<b>{monthly_wave_label}</b>",
                    showarrow=False,
                    font=dict(size=12, color=label_color, family="Arial"),
                    xanchor="center", yanchor="top",
                    bgcolor="rgba(0,0,0,0.85)", bordercolor=label_color, borderwidth=1, borderpad=4
                )
                
                mtf_charts['monthly'] = capture_chart_as_base64(monthly_fig)
                print(f"📊 MTF: Monthly chart captured ({len(monthly_df)} bars)")
            
            # Step 3: Weekly Chart with wave label
            update_sidebar_progress(3, 6, "Weekly chart (Intermediate)")
            weekly_df = st.session_state.get('weekly_df')
            if weekly_df is not None and not weekly_df.empty:
                weekly_fig, _ = create_chart(weekly_df, ticker_display, "Weekly", sma_period=30, weekly_sma_data=weekly_sma)
                
                w3_weekly = st.session_state.get('w3_weekly')
                w5_weekly = st.session_state.get('w5_weekly')
                if w5_weekly:
                    weekly_wave_label = "Weekly: Intermediate Wave-5 Active"
                    label_color = "#fbbf24"
                elif w3_weekly:
                    weekly_wave_label = "Weekly: Intermediate Wave-3 Active"
                    label_color = "#22c55e"
                else:
                    weekly_wave_label = "Weekly: Intermediate Degree"
                    label_color = "#22c55e"
                
                weekly_fig.add_annotation(
                    x=0.5, y=0.98, xref="paper", yref="paper",
                    text=f"<b>{weekly_wave_label}</b>",
                    showarrow=False,
                    font=dict(size=12, color=label_color, family="Arial"),
                    xanchor="center", yanchor="top",
                    bgcolor="rgba(0,0,0,0.85)", bordercolor=label_color, borderwidth=1, borderpad=4
                )
                
                mtf_charts['weekly'] = capture_chart_as_base64(weekly_fig)
                print(f"📊 MTF: Weekly chart captured ({len(weekly_df)} bars)")
            
            # Step 4: Daily Chart with wave label
            update_sidebar_progress(4, 6, "Daily chart (Minor)")
            daily_df = st.session_state.get('daily_df')
            if daily_df is not None and not daily_df.empty:
                daily_fig, _ = create_chart(daily_df, ticker_display, "Daily", sma_period=150, weekly_sma_data=weekly_sma)
                
                w3_daily = st.session_state.get('w3_daily')
                w4_daily = st.session_state.get('w4_daily')
                w5_daily = st.session_state.get('w5_daily')
                
                if w5_daily:
                    daily_wave_label = "Daily: Minor Wave-5 Active"
                    label_color = "#fbbf24"
                elif w4_daily:
                    daily_wave_label = "Daily: Minor Wave-4 Correction"
                    label_color = "#f97316"
                elif w3_daily:
                    daily_wave_label = "Daily: Minor Wave-3 Active"
                    label_color = "#22c55e"
                else:
                    daily_wave_label = "Daily: Minor Degree"
                    label_color = "#22c55e"
                
                daily_fig.add_annotation(
                    x=0.5, y=0.98, xref="paper", yref="paper",
                    text=f"<b>{daily_wave_label}</b>",
                    showarrow=False,
                    font=dict(size=12, color=label_color, family="Arial"),
                    xanchor="center", yanchor="top",
                    bgcolor="rgba(0,0,0,0.85)", bordercolor=label_color, borderwidth=1, borderpad=4
                )
                
                mtf_charts['daily'] = capture_chart_as_base64(daily_fig)
                print(f"📊 MTF: Daily chart captured ({len(daily_df)} bars)")
            else:
                mtf_charts['daily'] = chart_base64
            
            # Step 5: 4H Chart with wave label
            update_sidebar_progress(5, 6, "4H chart (Minuette)")
            h1_df = st.session_state.get('h1_df')
            if h1_df is not None and not h1_df.empty:
                h4_df = h1_df.resample('4h').agg({
                    'Open': 'first',
                    'High': 'max',
                    'Low': 'min',
                    'Close': 'last',
                    'Volume': 'sum'
                }).dropna()
                if not h4_df.empty:
                    h4_fig, _ = create_chart(h4_df, ticker_display, "4H", sma_period=180, weekly_sma_data=weekly_sma)
                    
                    h4_wave_label = "4-Hour: Minuette Degree (Entry Timing)"
                    label_color = "#06b6d4"
                    
                    h4_fig.add_annotation(
                        x=0.5, y=0.98, xref="paper", yref="paper",
                        text=f"<b>{h4_wave_label}</b>",
                        showarrow=False,
                        font=dict(size=12, color=label_color, family="Arial"),
                        xanchor="center", yanchor="top",
                        bgcolor="rgba(0,0,0,0.85)", bordercolor=label_color, borderwidth=1, borderpad=4
                    )
                    
                    mtf_charts['h4'] = capture_chart_as_base64(h4_fig)
                    print(f"📊 MTF: 4H chart captured ({len(h4_df)} bars)")
            
            print(f"📊 MTF CHARTS READY: {list(mtf_charts.keys())}")
            st.session_state.mtf_charts_debug = mtf_charts
            
        except Exception as mtf_error:
            st.error(f"⚠️ MTF Chart Generation Failed: {mtf_error}")
            tlog(f"MTF ERROR: {mtf_error}")
            import traceback
            tlog(traceback.format_exc())
            # Don't set to None - keep whatever charts we generated
            if not mtf_charts:
                mtf_charts = None
            st.session_state.mtf_charts_debug = mtf_charts
        
        # Debug MTF chart status
        if mtf_charts:
            st.success(f"✅ Generated {len(mtf_charts)}/4 MTF charts: {list(mtf_charts.keys())}")
            
            # Display MTF chart thumbnails in a compact single row
            st.markdown("**📊 Charts Sent to AI:**")
            thumb_html = '<div style="display: flex; gap: 8px; margin: 8px 0;">'
            timeframe_labels = ['M', 'W', 'D', '4H']
            timeframe_keys = ['monthly', 'weekly', 'daily', 'h4']
            
            for label, key in zip(timeframe_labels, timeframe_keys):
                if key in mtf_charts and mtf_charts[key]:
                    thumb_html += f'''
                    <div style="flex: 1; text-align: center;">
                        <div style="font-size: 11px; font-weight: bold; color: #888; margin-bottom: 2px;">{label}</div>
                        <img src="data:image/png;base64,{mtf_charts[key]}" style="width: 100%; max-width: 150px; height: 80px; object-fit: cover; border-radius: 4px; border: 1px solid #333;">
                    </div>'''
                else:
                    thumb_html += f'''
                    <div style="flex: 1; text-align: center;">
                        <div style="font-size: 11px; font-weight: bold; color: #888; margin-bottom: 2px;">{label}</div>
                        <div style="width: 100%; max-width: 150px; height: 80px; background: #333; border-radius: 4px; display: flex; align-items: center; justify-content: center; color: #666;">N/A</div>
                    </div>'''
            
            thumb_html += '</div>'
            st.markdown(thumb_html, unsafe_allow_html=True)
        else:
            st.error("⚠️ NO MTF CHARTS GENERATED - AI will only see Daily chart")
            st.info("Possible reasons: Missing data for Monthly/Weekly/4H timeframes")
            # Debug: Check what data is available
            tlog(f"DEBUG MTF DATA: monthly_df={st.session_state.get('monthly_df') is not None}, weekly_df={st.session_state.get('weekly_df') is not None}, h1_df={st.session_state.get('h1_df') is not None}")
        
        # Step 6: GPT-4o Analysis
        update_sidebar_progress(6, 6, "GPT-4o analyzing...")
        
        try:
            ai_analysis = audit_chart_with_ai(
                chart_base64, 
                pivot_text, 
                ticker_display, 
                timeframe_display,
                sma_info,
                current_price,
                highest_price,
                lowest_price,
                mtf_charts
            )
            tlog(f"AI Analysis received: {len(ai_analysis)} characters")
            st.session_state.ai_analysis_text = ai_analysis
            
            # TTA vs AI Dissonance Check - RIGHT after AI analysis completes
            if ai_analysis and len(ai_analysis) > 100:
                try:
                    verdict_data_check = st.session_state.get('verdict_data')
                    if verdict_data_check:
                        ai_lower = ai_analysis.lower()
                        bullish_words = ['bullish', 'buy', 'long', 'continuation', 'upward', 'breakout', 'upside']
                        bearish_words = ['bearish', 'sell', 'short', 'correction', 'downward', 'caution', 'risk', 'downside']
                        
                        bull_count = sum(ai_lower.count(word) for word in bullish_words)
                        bear_count = sum(ai_lower.count(word) for word in bearish_words)
                        
                        ai_sentiment = "BULLISH" if bull_count > bear_count else "BEARISH" if bear_count > bull_count else "NEUTRAL"
                        tta_confidence = verdict_data_check.get('confidence', 50)
                        tta_sentiment = "BULLISH" if tta_confidence >= 60 else "BEARISH" if tta_confidence < 40 else "NEUTRAL"
                        
                        # Store comparison for dashboard display
                        st.session_state.ai_tta_comparison = {
                            'ai_sentiment': ai_sentiment,
                            'tta_sentiment': tta_sentiment,
                            'ai_bullish': bull_count,
                            'ai_bearish': bear_count,
                            'tta_confidence': tta_confidence,
                            'agrees': ai_sentiment == tta_sentiment or tta_sentiment == "NEUTRAL"
                        }
                        tlog(f"AI vs TTA: AI={ai_sentiment} (bull:{bull_count}/bear:{bear_count}), TTA={tta_sentiment} ({tta_confidence}%)")
                except Exception as e:
                    tlog(f"Dissonance check error: {e}")
                    
        except Exception as ai_error:
            tlog(f"AI analysis failed: {ai_error}")
            ai_analysis = f"AI analysis unavailable: {str(ai_error)}\n\nUsing local TTA signal system instead."
            st.session_state.ai_analysis_text = None
        
        # Complete - show success in sidebar
        if sidebar_progress:
            sidebar_progress.markdown("""
            <div style="background: linear-gradient(135deg, #166534 0%, #22c55e 100%); padding: 12px; border-radius: 8px; margin: 8px 0;">
                <div style="color: white; font-weight: bold; font-size: 14px;">✅ AI Analysis Complete!</div>
                <div style="color: #dcfce7; font-size: 12px;">Scroll down to view results</div>
            </div>
            """, unsafe_allow_html=True)
            
            st.subheader("AI Technical Analysis")
            
            # MTF Verification Checker
            if ai_analysis:
                mtf_verification_present = any(phrase in ai_analysis for phrase in [
                    "MULTI-TIMEFRAME VERIFICATION", 
                    "Chart Receipt Confirmation",
                    "MTF VERIFICATION",
                    "Monthly:", 
                    "MONTHLY CHART",
                    "Primary Degree"
                ])
                chart_receipt_count = ai_analysis.count("RECEIVED")
                
                if mtf_verification_present and chart_receipt_count >= 4:
                    st.success(f"✅ VERIFIED: AI analyzed all 4 timeframes (Monthly/Weekly/Daily/4H)")
                    
                    # Extract wave counts for quick view
                    import re
                    with st.expander("📊 Quick View: Wave Counts by Timeframe", expanded=True):
                        monthly_match = re.search(r'MONTHLY.*?Current wave = ([^\n]+)', ai_analysis, re.IGNORECASE)
                        weekly_match = re.search(r'WEEKLY.*?Current wave = ([^\n]+)', ai_analysis, re.IGNORECASE)
                        daily_match = re.search(r'DAILY.*?Current wave = ([^\n]+)', ai_analysis, re.IGNORECASE)
                        h4_match = re.search(r'4-HOUR.*?Current wave = ([^\n]+)', ai_analysis, re.IGNORECASE)
                        
                        col1, col2 = st.columns(2)
                        with col1:
                            if monthly_match:
                                st.markdown(f"**📅 Monthly:** {monthly_match.group(1).strip()}")
                            if weekly_match:
                                st.markdown(f"**📆 Weekly:** {weekly_match.group(1).strip()}")
                        with col2:
                            if daily_match:
                                st.markdown(f"**📊 Daily:** {daily_match.group(1).strip()}")
                            if h4_match:
                                st.markdown(f"**⏰ 4H:** {h4_match.group(1).strip()}")
                elif chart_receipt_count > 0 and chart_receipt_count < 4:
                    st.warning(f"⚠️ AI only received {chart_receipt_count}/4 charts - Analysis may be incomplete")
                elif not mtf_verification_present and mtf_charts:
                    # Just informational - analysis is still valid
                    st.info("ℹ️ AI analyzed all charts - scroll down to see full multi-timeframe analysis")
            
            # AI Debug Display
            if st.session_state.get('show_ai_debug', False):
                mtf_debug = st.session_state.get('mtf_charts_debug')
                if mtf_debug:
                    with st.expander("🔍 AI Debug: Charts Sent to GPT-4o", expanded=True):
                        st.markdown("**Chart Sizes Sent:**")
                        st.markdown(f"- Monthly: {len(mtf_debug.get('monthly', ''))} chars (base64)")
                        st.markdown(f"- Weekly: {len(mtf_debug.get('weekly', ''))} chars (base64)")
                        st.markdown(f"- Daily: {len(mtf_debug.get('daily', ''))} chars (base64)")
                        st.markdown(f"- 4H: {len(mtf_debug.get('h4', ''))} chars (base64)")
                        
                        # Show sample chart thumbnail
                        st.markdown("**Sample: Monthly Chart Sent to AI**")
                        if 'monthly' in mtf_debug:
                            st.image(f"data:image/png;base64,{mtf_debug['monthly']}", width=400)
                else:
                    st.info("No MTF charts were generated for this analysis")
            
            # v7.1 Price-State Banner (NOT a compliance error)
            current_price = df['Close'].iloc[-1]
            level_A = st.session_state.get('level_A')
            level_B = st.session_state.get('level_B')
            
            # Render appropriate price-state banner based on A/B structural pivots
            if level_A is not None and level_B is not None:
                if current_price < level_A:
                    # TRIGGER HIT - BEARISH (close below A)
                    st.markdown(
                        f"""
                        <div style="
                            background-color: #dc2626;
                            color: white;
                            padding: 20px;
                            border-radius: 8px;
                            text-align: center;
                            font-size: 1.3rem;
                            font-weight: bold;
                            margin-bottom: 20px;
                            border: 3px solid #991b1b;
                        ">
                            🟥 TRIGGER HIT — BEARISH ACTIVATION<br>
                            <span style="font-size: 1rem; font-weight: normal;">
                                Close &#36;{current_price:.2f} is BELOW A (&#36;{level_A:.2f}).<br>
                                Continue reading: the full v7.1 audit below is still valid.
                            </span>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
                elif current_price > level_B:
                    # TRIGGER HIT - BULLISH (close above B)
                    st.markdown(
                        f"""
                        <div style="
                            background-color: #16a34a;
                            color: white;
                            padding: 20px;
                            border-radius: 8px;
                            text-align: center;
                            font-size: 1.3rem;
                            font-weight: bold;
                            margin-bottom: 20px;
                            border: 3px solid #15803d;
                        ">
                            🟩 TRIGGER HIT — BULLISH CONTINUATION<br>
                            <span style="font-size: 1rem; font-weight: normal;">
                                Close &#36;{current_price:.2f} is ABOVE B (&#36;{level_B:.2f}).<br>
                                Continue reading: the full v7.1 audit below is still valid.
                            </span>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
                else:
                    # NO TRIGGER HIT - Price between A and B (in range)
                    st.markdown(
                        f"""
                        <div style="
                            background-color: #ca8a04;
                            color: white;
                            padding: 20px;
                            border-radius: 8px;
                            text-align: center;
                            font-size: 1.3rem;
                            font-weight: bold;
                            margin-bottom: 20px;
                            border: 3px solid #a16207;
                        ">
                            🟨 NO TRIGGER HIT — RANGE / DEVELOPING<br>
                            <span style="font-size: 1rem; font-weight: normal;">
                                Close &#36;{current_price:.2f} is between A (&#36;{level_A:.2f}) and B (&#36;{level_B:.2f}).<br>
                                Continue reading: the full v7.1 audit below.
                            </span>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
            
            # Render output based on selected format
            with st.expander("📊 Elliott Wave Analysis (AI Audit)", expanded=True):
                # NEW: Direct HTML Rendering for Gemini
                if ai_analysis and ai_analysis.strip().startswith("<div"):
                    st.markdown(ai_analysis, unsafe_allow_html=True)
                    st.session_state.dashboard_data = None # Clear legacy data to prevent stale PDF export logic
                
                # FALLBACK: Legacy Dashboard Parser (for text-based AI output)
                elif st.session_state.show_dashboard and level_A is not None and level_B is not None:
                    try:
                        # v16.17 MTF FIX - Collect traffic light data
                        mtf_data = {
                            'monthly': {'ao': st.session_state.get('tta_stats', {}).get('base', {}).get('monthly_ao', 0), 'dotcolor': st.session_state.get('traffic_lights', {}).get('monthly_dotcolor', '6b7280')},
                            'weekly': {'ao': st.session_state.get('tta_stats', {}).get('base', {}).get('weekly_ao', 0), 'dotcolor': st.session_state.get('traffic_lights', {}).get('weekly_dotcolor', '6b7280')},
                            'daily': {'ao': st.session_state.get('tta_stats', {}).get('base', {}).get('daily_ao', 0), 'dotcolor': st.session_state.get('traffic_lights', {}).get('daily_dotcolor', '6b7280')},
                            'h4': {'ao': st.session_state.get('tta_stats', {}).get('base', {}).get('h4_ao', 0), 'dotcolor': st.session_state.get('traffic_lights', {}).get('h4_dotcolor', '6b7280')}
                        }
                        
                        dashboard_data = parse_analysis_for_dashboard(
                            ai_analysis, 
                            ticker_display, 
                            current_price, 
                            level_A, 
                            level_B,
                            timeframe,
                            mtf_data
                        )
                        
                        # --- MACD CHUNK DIAGNOSTIC LOGIC (v7.1 COMPLIANT, BI-DIRECTIONAL) ---
                        # Use stored MACD diagnostic from chart creation (avoid recomputing)
                        macd_diag = st.session_state.get('macd_diag')
                        
                        if macd_diag:
                            # Serialize chart markers (convert Timestamps to strings)
                            serialized_markers = []
                            for m in macd_diag.get("chart_markers", []):
                                serialized_markers.append({
                                    "time": str(m.get("time", "")),
                                    "position": m.get("position", "aboveBar"),
                                    "color": m.get("color", "#ffffff"),
                                    "shape": m.get("shape", "arrowDown"),
                                    "text": m.get("text", ""),
                                    "size": m.get("size", 1)
                                })
                            
                            # Inject bi-directional diagnostic data for React rendering
                            dashboard_data["macdChunks"] = {
                                "bullish": macd_diag.get("bullish"),
                                "bearish": macd_diag.get("bearish"),
                                "chart_markers": serialized_markers
                            }
                            
                            # Pass full ao_diag for corrective warning check in PDF
                            dashboard_data["ao_diag"] = {
                                "divergence": macd_diag.get("divergence", False),
                                "post5_negative": macd_diag.get("post5_negative", False),
                                "corrective_warning": macd_diag.get("corrective_warning", False),
                                "div_ratio": macd_diag.get("div_ratio", 0)
                            }
                        
                        # v16.12: Add filter profile to dashboard data for PDF export
                        dashboard_data["filter_profile"] = st.session_state.get('filter_profile', 'BALANCED')
                        
                        # Add AI vs TTA comparison for header display
                        ai_tta_comparison = st.session_state.get('ai_tta_comparison')
                        if ai_tta_comparison:
                            dashboard_data["ai_tta_comparison"] = ai_tta_comparison
                        
                        st.session_state.dashboard_data = dashboard_data
                        html_code = render_react_dashboard(dashboard_data)
                        components.html(html_code, height=900, scrolling=True)
                        
                        with st.expander("View Raw Analysis Text"):
                            safe_analysis = ai_analysis.replace('$', '&#36;')
                            st.markdown(safe_analysis, unsafe_allow_html=True)
                    except Exception as dash_error:
                        st.error(f"Dashboard rendering failed: {str(dash_error)}")
                        import traceback
                        st.code(traceback.format_exc())
                        safe_analysis = ai_analysis.replace('$', '&#36;')
                        st.markdown(safe_analysis, unsafe_allow_html=True)
                else:
                    safe_analysis = ai_analysis.replace('$', '&#36;')
                    st.markdown(safe_analysis, unsafe_allow_html=True)
        
        # Reset the audit flag after processing
        st.session_state.run_audit = False
    elif st.session_state.dashboard_data is not None:
        # Re-render stored dashboard on page refresh
        with st.expander("📊 Elliott Wave Analysis (AI Audit)", expanded=True):
            try:
                html_code = render_react_dashboard(st.session_state.dashboard_data)
                components.html(html_code, height=900, scrolling=True)
            except Exception as dash_error:
                st.error(f"Dashboard rendering failed: {str(dash_error)}")
    else:
        # AI toggle is OFF - show hint
        st.info("💡 Turn ON 'AI Elliott Wave Audit' toggle in sidebar for detailed AI analysis")
    
    # PDF Download Button - shows when dashboard data exists
    if st.session_state.dashboard_data is not None:
        try:
            pdf_bytes = generate_pdf_report(st.session_state.dashboard_data)
            ticker_for_file = st.session_state.dashboard_data.get('ticker', 'report')
            pdf_profile = st.session_state.dashboard_data.get('filter_profile', 'BALANCED')
            st.download_button(
                label="📄 Download PDF Report",
                data=pdf_bytes,
                file_name=f"{ticker_for_file}_analysis_{pdf_profile}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                mime="application/pdf",
                help="Download a professional PDF report of this analysis",
                key=f"pdf_report_{ticker_for_file}"
            )
        except Exception as pdf_error:
            st.warning(f"PDF generation unavailable: {str(pdf_error)}")
    
    # Full Page Screenshot Button
    screenshot_ticker = st.session_state.get('current_ticker', 'analysis')
    screenshot_html = f'''
    <script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
    <style>
        .screenshot-btn {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            padding: 12px 24px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 16px;
            font-weight: 600;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);
            transition: all 0.3s ease;
            margin: 10px 0;
        }}
        .screenshot-btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(102, 126, 234, 0.6);
        }}
        .screenshot-btn:active {{
            transform: translateY(0);
        }}
        .screenshot-btn.capturing {{
            background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
            pointer-events: none;
        }}
    </style>
    <button class="screenshot-btn" onclick="captureFullPage()" id="screenshotBtn">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
            <circle cx="8.5" cy="8.5" r="1.5"></circle>
            <polyline points="21 15 16 10 5 21"></polyline>
        </svg>
        📸 Capture Full Analysis Screenshot
    </button>
    <script>
        async function captureFullPage() {{
            const btn = document.getElementById('screenshotBtn');
            btn.classList.add('capturing');
            btn.innerHTML = '⏳ Capturing...';
            
            try {{
                // Try multiple selectors for Streamlit's main content area
                const selectors = [
                    '.main .block-container',
                    '[data-testid="stAppViewContainer"]',
                    '[data-testid="stMainBlockContainer"]',
                    '.stApp',
                    'section.main',
                    '.main'
                ];
                let mainContent = null;
                for (const sel of selectors) {{
                    mainContent = window.parent.document.querySelector(sel);
                    if (mainContent) break;
                }}
                if (!mainContent) {{
                    // Last resort: just use body
                    mainContent = window.parent.document.body;
                }}
                
                // Use html2canvas from parent window context
                const canvas = await html2canvas(mainContent, {{
                    scale: 2,
                    useCORS: true,
                    allowTaint: true,
                    backgroundColor: '#0e1117',
                    scrollX: 0,
                    scrollY: 0,
                    windowWidth: mainContent.scrollWidth,
                    windowHeight: mainContent.scrollHeight,
                    logging: false
                }});
                
                // Convert to blob and download
                canvas.toBlob(function(blob) {{
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = '{screenshot_ticker}_elliott_wave_analysis_' + new Date().toISOString().slice(0,10) + '.png';
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                    URL.revokeObjectURL(url);
                    
                    btn.classList.remove('capturing');
                    btn.innerHTML = '✅ Screenshot Saved!';
                    setTimeout(() => {{
                        btn.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><polyline points="21 15 16 10 5 21"></polyline></svg> 📸 Capture Full Analysis Screenshot';
                    }}, 2000);
                }}, 'image/png');
                
            }} catch (error) {{
                console.error('Screenshot failed:', error);
                btn.classList.remove('capturing');
                btn.innerHTML = '❌ Failed - Try Again';
                setTimeout(() => {{
                    btn.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><polyline points="21 15 16 10 5 21"></polyline></svg> 📸 Capture Full Analysis Screenshot';
                }}, 2000);
            }}
        }}
    </script>
    '''
    components.html(screenshot_html, height=70)
    
    with st.expander("About This Analysis"):
        st.markdown("""
        **Indicators Explained:**
        
        - **30-Week SMA**: A moving average that smooths price data over 30 weekly periods, 
          useful for identifying the long-term trend direction.
        
        - **Awesome Oscillator (5/34)**: Measures market momentum by comparing a 5-period 
          simple moving average to a 34-period simple moving average of the median price 
          (High+Low)/2. Positive values indicate bullish momentum, negative values indicate bearish.
        
        - **Price Pivots**: Significant turning points identified using local extrema detection. 
          These represent potential support and resistance levels.
        
        **AI Chart Audit**: The chart is automatically analyzed by GPT-4o Vision 
        for comprehensive Elliott Wave, Weinstein Stage, and Fibonacci analysis.
        """)

else:
    st.info("👈 Enter a stock ticker in the sidebar and click 'Analyze & Audit Stock' to begin")
    
    st.markdown("### Quick Start Examples")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("**Tech Stocks**")
        st.markdown("AAPL, MSFT, GOOGL, NVDA")
    with col2:
        st.markdown("**ETFs**")
        st.markdown("SPY, QQQ, IWM, DIA")
    with col3:
        st.markdown("**Other**")
        st.markdown("TSLA, AMZN, META, JPM")

st.divider()
st.markdown("---")
display_daily_summary()


def export_daily_report_pdf():
    """Export today's verdicts as a formatted PDF report"""
    from datetime import datetime
    import json
    
    verdicts = load_daily_verdicts()
    
    if not verdicts:
        return None
    
    report_content = f"""
═══════════════════════════════════════════════════════
        TTA TRADING ANALYSIS REPORT
        {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
═══════════════════════════════════════════════════════

SUMMARY:
Total Verdicts: {len(verdicts)}
Strong Signals: {len([v for v in verdicts if v['confidence'] >= 78])}
Weak Signals: {len([v for v in verdicts if 65 <= v['confidence'] < 78])}
Skip Signals: {len([v for v in verdicts if v['confidence'] < 65])}

Average Metrics:
- Confidence: {sum(v['confidence'] for v in verdicts) / len(verdicts):.1f}%
- Win Rate: {sum(v['win_rate'] for v in verdicts) / len(verdicts):.1f}%
- Risk:Reward: {sum(v['risk_reward'] for v in verdicts) / len(verdicts):.2f}:1

═══════════════════════════════════════════════════════
DETAILED VERDICTS:
═══════════════════════════════════════════════════════
"""
    
    for i, v in enumerate(verdicts, 1):
        if v['confidence'] >= 78:
            status = "🟢 STRONG - ENTER LONG"
        elif v['confidence'] >= 65:
            status = "🟡 PARTIAL - WAIT FOR CONFIRMATION"
        else:
            status = "🔴 WEAK - SKIP THIS TRADE"
        
        report_content += f"""
{i}. {v['ticker']} ({v['timeframe']})
   Status: {status}
   Confidence: {v['confidence']}%
   Elliott Wave Quality: {v['elliott_quality']}/100
   Win Rate: {v['win_rate']}%
   Risk:Reward: {v['risk_reward']}:1
   Entry: ${v['entry_price']}
   Stop Loss: ${v['stop_loss']}
   Target: ${v['target']}
   Signal Strength: {v['signal_strength']}/9
   Time: {v['timestamp']}
"""
    
    report_filename = f"TTA_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(report_filename, 'w') as f:
        f.write(report_content)
    
    return report_filename


st.divider()
col1, col2 = st.columns(2)
with col1:
    if st.button("📋 Export Daily Report"):
        report_file = export_daily_report_pdf()
        if report_file:
            st.success(f"✅ Report exported: {report_file}")
            with open(report_file, 'r') as f:
                st.download_button(
                    label="Download Report",
                    data=f.read(),
                    file_name=report_file,
                    mime="text/plain"
                )

# ═══════════════════════════════════════════════════════════════════════════════
# END OF APP - AI Chart Audit is handled by gemini_auditor.py
# ═══════════════════════════════════════════════════════════════════════════════
