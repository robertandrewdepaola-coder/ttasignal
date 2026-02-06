"""
TTA Signal - Custom CSS Styles
Professional dark theme inspired by modern trading platforms
"""

# =============================================================================
# PREMIUM DARK THEME CSS - Mometic-inspired clean professional look
# =============================================================================

TTA_CUSTOM_CSS = """
<style>
    /* ═══════════════════════════════════════════════════════════════════════
       GLOBAL THEME - Dark Professional Trading Platform
       ═══════════════════════════════════════════════════════════════════════ */
    
    /* Import Google Font */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
    
    /* ═══════════════════════════════════════════════════════════════════════
       AGGRESSIVE STREAMLIT OVERRIDES - Force our styles
       ═══════════════════════════════════════════════════════════════════════ */
    
    /* Primary action buttons - Green gradient */
    .stButton > button[kind="primary"],
    .stButton > button[data-testid="baseButton-primary"],
    button[kind="primary"],
    .stFormSubmitButton > button {
        background: linear-gradient(135deg, #238636 0%, #2EA043 100%) !important;
        background-color: #238636 !important;
        color: white !important;
        border: none !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
        font-family: 'Inter', sans-serif !important;
        padding: 0.5rem 1.5rem !important;
        transition: all 0.2s ease !important;
        box-shadow: 0 2px 8px rgba(35, 134, 54, 0.3) !important;
    }
    
    .stButton > button[kind="primary"]:hover,
    .stButton > button[data-testid="baseButton-primary"]:hover,
    .stFormSubmitButton > button:hover {
        background: linear-gradient(135deg, #2EA043 0%, #3FB950 100%) !important;
        transform: translateY(-1px) !important;
        box-shadow: 0 4px 12px rgba(46, 160, 67, 0.4) !important;
    }
    
    /* Secondary buttons - Outline style */
    .stButton > button[kind="secondary"],
    .stButton > button:not([kind="primary"]):not([data-testid="baseButton-primary"]) {
        background: transparent !important;
        background-color: transparent !important;
        color: #58A6FF !important;
        border: 1px solid #30363D !important;
        border-radius: 8px !important;
        font-weight: 500 !important;
    }
    
    .stButton > button[kind="secondary"]:hover,
    .stButton > button:not([kind="primary"]):not([data-testid="baseButton-primary"]):hover {
        background: rgba(88, 166, 255, 0.1) !important;
        border-color: #58A6FF !important;
    }
    
    /* Tab styling */
    .stTabs [data-baseweb="tab-list"] {
        background: transparent !important;
        gap: 0 !important;
        border-bottom: 1px solid #30363D !important;
    }
    
    .stTabs [data-baseweb="tab"] {
        color: #8B949E !important;
        background: transparent !important;
        border-radius: 0 !important;
        padding: 12px 20px !important;
        font-weight: 500 !important;
        border-bottom: 2px solid transparent !important;
    }
    
    .stTabs [data-baseweb="tab"]:hover {
        color: #F0F6FC !important;
    }
    
    .stTabs [aria-selected="true"] {
        color: #58A6FF !important;
        border-bottom: 2px solid #58A6FF !important;
        background: transparent !important;
    }
    
    /* Form inputs */
    .stTextInput > div > div > input,
    .stTextArea > div > div > textarea,
    .stNumberInput > div > div > input {
        background-color: #161B22 !important;
        border: 1px solid #30363D !important;
        border-radius: 6px !important;
        color: #F0F6FC !important;
    }
    
    .stTextInput > div > div > input:focus,
    .stTextArea > div > div > textarea:focus {
        border-color: #58A6FF !important;
        box-shadow: 0 0 0 3px rgba(88, 166, 255, 0.15) !important;
    }
    
    /* Selectbox */
    .stSelectbox > div > div {
        background-color: #161B22 !important;
        border: 1px solid #30363D !important;
        border-radius: 6px !important;
    }
    
    /* Caption styling - make it visible */
    .stCaption, [data-testid="stCaptionContainer"] {
        color: #8B949E !important;
    }
    
    /* Version badge styling */
    [data-testid="stCaptionContainer"] p {
        color: #58A6FF !important;
        background: rgba(88, 166, 255, 0.1) !important;
        padding: 4px 12px !important;
        border-radius: 20px !important;
        display: inline-block !important;
        font-size: 12px !important;
        border: 1px solid rgba(88, 166, 255, 0.3) !important;
    }
    
    /* Expanders */
    .stExpander {
        border: 1px solid #30363D !important;
        border-radius: 8px !important;
        background: #161B22 !important;
    }
    
    /* DataFrames */
    .stDataFrame {
        border-radius: 8px !important;
        overflow: hidden !important;
    }
    
    .stDataFrame [data-testid="stDataFrameContainer"] {
        background: #161B22 !important;
    }
    
    /* Info/Success/Warning/Error boxes */
    .stAlert {
        border-radius: 8px !important;
    }
    
    /* Hide Streamlit branding for cleaner look */
    #MainMenu {visibility: hidden !important;}
    footer {visibility: hidden !important;}
    
    /* ═══════════════════════════════════════════════════════════════════════
       NUCLEAR OPTION - Force button colors with maximum specificity
       ═══════════════════════════════════════════════════════════════════════ */
    
    /* Target ALL buttons in Streamlit using data-testid */
    [data-testid="stFormSubmitButton"] > button,
    [data-testid="baseButton-primary"],
    button[data-testid="baseButton-primary"],
    div[data-testid="stFormSubmitButton"] button,
    .stFormSubmitButton button {
        background: linear-gradient(135deg, #238636 0%, #2EA043 100%) !important;
        background-color: #238636 !important;
        color: #FFFFFF !important;
        border: none !important;
        border-color: transparent !important;
    }
    
    /* Coral/Red buttons - override to green */
    button[style*="background-color: rgb(255, 75, 75)"],
    button[style*="background-color: rgb(255,75,75)"],
    button[style*="#FF4B4B"],
    button[style*="ff4b4b"] {
        background: linear-gradient(135deg, #238636 0%, #2EA043 100%) !important;
        background-color: #238636 !important;
    }
    
    /* Super specific targeting for form submit */
    .stForm [data-testid="stFormSubmitButton"] button[kind="primary"],
    .stForm button[kind="primary"],
    div.stForm button {
        background: linear-gradient(135deg, #238636 0%, #2EA043 100%) !important;
        color: white !important;
    }
    
    /* Root variables - for our custom components */
    :root {
        --bg-primary: #0D1117;
        --bg-secondary: #161B22;
        --bg-tertiary: #21262D;
        --bg-card: #1C2128;
        --border-color: #30363D;
        --border-subtle: #21262D;
        
        --text-primary: #F0F6FC;
        --text-secondary: #8B949E;
        --text-muted: #6E7681;
        
        --accent-green: #3FB950;
        --accent-green-glow: rgba(63, 185, 80, 0.15);
        --accent-blue: #58A6FF;
        --accent-blue-glow: rgba(88, 166, 255, 0.15);
        --accent-yellow: #D29922;
        --accent-yellow-glow: rgba(210, 153, 34, 0.15);
        --accent-red: #F85149;
        --accent-red-glow: rgba(248, 81, 73, 0.15);
        --accent-purple: #A371F7;
        
        --radius-sm: 6px;
        --radius-md: 8px;
        --radius-lg: 12px;
        
        --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.3);
        --shadow-md: 0 4px 12px rgba(0, 0, 0, 0.4);
        --shadow-lg: 0 8px 24px rgba(0, 0, 0, 0.5);
    }
    
    /* Base font */
    .stApp, .stApp * {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
    }
    
    /* ═══════════════════════════════════════════════════════════════════════
       TEXT CONTRAST - Make all text bright and readable
       ═══════════════════════════════════════════════════════════════════════ */
    
    /* Main content text - bright white */
    .stApp p, .stApp span, .stApp li, .stApp div {
        color: #E6EDF3 !important;
    }
    
    /* Headers - pure white */
    .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6 {
        color: #FFFFFF !important;
    }
    
    /* Subheader styling */
    [data-testid="stSubheader"], .stSubheader {
        color: #FFFFFF !important;
    }
    
    /* Markdown text */
    .stMarkdown, .stMarkdown p, .stMarkdown span, .stMarkdown li {
        color: #E6EDF3 !important;
    }
    
    /* Labels */
    .stTextInput label, .stSelectbox label, .stTextArea label, 
    .stNumberInput label, .stDateInput label, .stCheckbox label,
    [data-testid="stWidgetLabel"] {
        color: #C9D1D9 !important;
    }
    
    /* Caption text - slightly muted but still readable */
    .stCaption, [data-testid="stCaptionContainer"] p {
        color: #8B949E !important;
    }
    
    /* Table text */
    .stDataFrame, .stDataFrame td, .stDataFrame th,
    [data-testid="stDataFrame"] td, [data-testid="stDataFrame"] th,
    .stTable td, .stTable th {
        color: #E6EDF3 !important;
    }
    
    /* Table headers - brighter */
    .stDataFrame th, [data-testid="stDataFrame"] th {
        color: #FFFFFF !important;
        font-weight: 600 !important;
    }
    
    /* Info/Warning boxes - Complete override for readability */
    /* Warning - Yellow/Amber theme */
    [data-testid="stAlert"][data-baseweb="notification"][kind="warning"],
    .stAlert > div[role="alert"],
    div[data-testid="stNotificationContentWarning"] {
        background-color: #FEF3CD !important;
        border: 1px solid #FFCA2C !important;
        border-left: 4px solid #FFCA2C !important;
    }
    
    [data-testid="stNotificationContentWarning"] p,
    .stAlert[kind="warning"] p,
    div[data-baseweb="notification"] p {
        color: #664D03 !important;
        font-weight: 500 !important;
    }
    
    /* Info - Blue theme */
    [data-testid="stNotificationContentInfo"] {
        background-color: #CFE2FF !important;
        border-left: 4px solid #0D6EFD !important;
    }
    
    [data-testid="stNotificationContentInfo"] p {
        color: #084298 !important;
    }
    
    /* Success - Green theme */
    [data-testid="stNotificationContentSuccess"] {
        background-color: #D1E7DD !important;
        border-left: 4px solid #198754 !important;
    }
    
    [data-testid="stNotificationContentSuccess"] p {
        color: #0F5132 !important;
    }
    
    /* Error - Red theme */
    [data-testid="stNotificationContentError"] {
        background-color: #F8D7DA !important;
        border-left: 4px solid #DC3545 !important;
    }
    
    [data-testid="stNotificationContentError"] p {
        color: #842029 !important;
    }
    
    /* Bullet points and lists */
    .stMarkdown ul li, .stMarkdown ol li {
        color: #E6EDF3 !important;
    }
    
    /* Expander headers - clean styling */
    .stExpander, [data-testid="stExpander"] {
        background: #161B22 !important;
        border: 1px solid #30363D !important;
        border-radius: 8px !important;
    }
    
    .stExpander summary, [data-testid="stExpander"] summary,
    .stExpander [data-testid="stExpanderToggleIcon"],
    .stExpander span {
        color: #FFFFFF !important;
    }
    
    /* Selectbox text */
    .stSelectbox [data-baseweb="select"] span,
    .stSelectbox div[role="listbox"] li {
        color: #E6EDF3 !important;
    }
    
    
    /* ═══════════════════════════════════════════════════════════════════════
       SIGNAL STATUS CARDS - Clean modular design
       ═══════════════════════════════════════════════════════════════════════ */
    
    .signal-card {
        background: var(--bg-card);
        border: 1px solid var(--border-color);
        border-radius: var(--radius-lg);
        padding: 20px;
        margin: 12px 0;
        transition: all 0.2s ease;
    }
    
    .signal-card:hover {
        border-color: var(--accent-blue);
        box-shadow: var(--shadow-md);
    }
    
    .signal-card-ready {
        border-left: 4px solid var(--accent-green);
        background: linear-gradient(135deg, var(--bg-card) 0%, var(--accent-green-glow) 100%);
    }
    
    .signal-card-caution {
        border-left: 4px solid var(--accent-yellow);
        background: linear-gradient(135deg, var(--bg-card) 0%, var(--accent-yellow-glow) 100%);
    }
    
    .signal-card-skip {
        border-left: 4px solid var(--accent-red);
        background: linear-gradient(135deg, var(--bg-card) 0%, var(--accent-red-glow) 100%);
    }
    
    .signal-card-ao {
        border-left: 4px solid var(--accent-blue);
        background: linear-gradient(135deg, var(--bg-card) 0%, var(--accent-blue-glow) 100%);
    }
    
    /* ═══════════════════════════════════════════════════════════════════════
       METRIC CARDS - Clean data display
       ═══════════════════════════════════════════════════════════════════════ */
    
    .metric-container {
        display: flex;
        gap: 16px;
        flex-wrap: wrap;
        margin: 16px 0;
    }
    
    .metric-card {
        background: var(--bg-card);
        border: 1px solid var(--border-color);
        border-radius: var(--radius-md);
        padding: 16px 20px;
        min-width: 140px;
        flex: 1;
    }
    
    .metric-label {
        font-size: 12px;
        font-weight: 500;
        color: var(--text-secondary);
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-bottom: 6px;
    }
    
    .metric-value {
        font-size: 24px;
        font-weight: 600;
        color: var(--text-primary);
    }
    
    .metric-value-positive {
        color: var(--accent-green);
    }
    
    .metric-value-negative {
        color: var(--accent-red);
    }
    
    /* ═══════════════════════════════════════════════════════════════════════
       STATUS BADGES - Pill-shaped clean indicators
       ═══════════════════════════════════════════════════════════════════════ */
    
    .status-badge {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 12px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.3px;
    }
    
    .status-ready {
        background: var(--accent-green-glow);
        color: var(--accent-green);
        border: 1px solid var(--accent-green);
    }
    
    .status-caution {
        background: var(--accent-yellow-glow);
        color: var(--accent-yellow);
        border: 1px solid var(--accent-yellow);
    }
    
    .status-skip {
        background: var(--accent-red-glow);
        color: var(--accent-red);
        border: 1px solid var(--accent-red);
    }
    
    .status-ao {
        background: var(--accent-blue-glow);
        color: var(--accent-blue);
        border: 1px solid var(--accent-blue);
    }
    
    .status-watch {
        background: var(--accent-purple);
        background: rgba(163, 113, 247, 0.15);
        color: var(--accent-purple);
        border: 1px solid var(--accent-purple);
    }
    
    /* ═══════════════════════════════════════════════════════════════════════
       SECTION HEADERS - Clean typography
       ═══════════════════════════════════════════════════════════════════════ */
    
    .section-header {
        display: flex;
        align-items: center;
        gap: 12px;
        margin: 24px 0 16px 0;
        padding-bottom: 12px;
        border-bottom: 1px solid var(--border-subtle);
    }
    
    .section-title {
        font-size: 18px;
        font-weight: 600;
        color: var(--text-primary);
        margin: 0;
    }
    
    .section-subtitle {
        font-size: 14px;
        color: var(--text-secondary);
        margin: 0;
    }
    
    /* ═══════════════════════════════════════════════════════════════════════
       CHECK ITEMS - Clean validation display
       ═══════════════════════════════════════════════════════════════════════ */
    
    .check-list {
        display: flex;
        flex-direction: column;
        gap: 8px;
        margin: 12px 0;
    }
    
    .check-item {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 10px 14px;
        background: var(--bg-secondary);
        border-radius: var(--radius-sm);
        font-size: 14px;
    }
    
    .check-item-pass {
        border-left: 3px solid var(--accent-green);
    }
    
    .check-item-fail {
        border-left: 3px solid var(--accent-red);
    }
    
    .check-icon {
        font-size: 16px;
    }
    
    .check-label {
        color: var(--text-secondary);
        flex: 1;
    }
    
    .check-value {
        color: var(--text-primary);
        font-weight: 500;
    }
    
    /* ═══════════════════════════════════════════════════════════════════════
       AI ASSESSMENT BOX - Premium glow effect
       ═══════════════════════════════════════════════════════════════════════ */
    
    .ai-box {
        background: linear-gradient(135deg, var(--bg-secondary) 0%, rgba(88, 166, 255, 0.05) 100%);
        border: 1px solid var(--accent-blue);
        border-radius: var(--radius-lg);
        padding: 24px;
        margin: 16px 0;
        position: relative;
        overflow: hidden;
    }
    
    .ai-box::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        height: 2px;
        background: linear-gradient(90deg, var(--accent-blue), var(--accent-purple), var(--accent-blue));
    }
    
    .ai-header {
        display: flex;
        align-items: center;
        gap: 12px;
        margin-bottom: 16px;
    }
    
    .ai-icon {
        font-size: 24px;
    }
    
    .ai-title {
        font-size: 16px;
        font-weight: 600;
        color: var(--text-primary);
    }
    
    .ai-powered {
        font-size: 11px;
        color: var(--text-muted);
        margin-left: auto;
    }
    
    /* ═══════════════════════════════════════════════════════════════════════
       TRADE SETUP BOX - Entry/Stop/Target display
       ═══════════════════════════════════════════════════════════════════════ */
    
    .trade-setup {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
        gap: 12px;
        margin: 16px 0;
    }
    
    .trade-item {
        background: var(--bg-secondary);
        border: 1px solid var(--border-color);
        border-radius: var(--radius-md);
        padding: 14px;
        text-align: center;
    }
    
    .trade-item-label {
        font-size: 11px;
        font-weight: 500;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-bottom: 6px;
    }
    
    .trade-item-value {
        font-size: 18px;
        font-weight: 600;
        color: var(--text-primary);
    }
    
    .trade-item-entry .trade-item-value {
        color: var(--accent-blue);
    }
    
    .trade-item-stop .trade-item-value {
        color: var(--accent-red);
    }
    
    .trade-item-target .trade-item-value {
        color: var(--accent-green);
    }
    
    /* ═══════════════════════════════════════════════════════════════════════
       RECOMMENDATION BANNER - Clear action guidance
       ═══════════════════════════════════════════════════════════════════════ */
    
    .recommendation-banner {
        display: flex;
        align-items: center;
        gap: 16px;
        padding: 20px 24px;
        border-radius: var(--radius-lg);
        margin: 16px 0;
    }
    
    .recommendation-buy {
        background: linear-gradient(135deg, var(--accent-green-glow) 0%, var(--bg-secondary) 100%);
        border: 1px solid var(--accent-green);
    }
    
    .recommendation-caution {
        background: linear-gradient(135deg, var(--accent-yellow-glow) 0%, var(--bg-secondary) 100%);
        border: 1px solid var(--accent-yellow);
    }
    
    .recommendation-skip {
        background: linear-gradient(135deg, var(--accent-red-glow) 0%, var(--bg-secondary) 100%);
        border: 1px solid var(--accent-red);
    }
    
    .recommendation-watch {
        background: linear-gradient(135deg, var(--accent-blue-glow) 0%, var(--bg-secondary) 100%);
        border: 1px solid var(--accent-blue);
    }
    
    .recommendation-icon {
        font-size: 32px;
    }
    
    .recommendation-content {
        flex: 1;
    }
    
    .recommendation-action {
        font-size: 18px;
        font-weight: 700;
        margin-bottom: 4px;
    }
    
    .recommendation-buy .recommendation-action {
        color: var(--accent-green);
    }
    
    .recommendation-caution .recommendation-action {
        color: var(--accent-yellow);
    }
    
    .recommendation-skip .recommendation-action {
        color: var(--accent-red);
    }
    
    .recommendation-watch .recommendation-action {
        color: var(--accent-blue);
    }
    
    .recommendation-reason {
        font-size: 14px;
        color: var(--text-secondary);
    }
    
    /* ═══════════════════════════════════════════════════════════════════════
       SUMMARY STATS - Clean overview display
       ═══════════════════════════════════════════════════════════════════════ */
    
    .summary-stats {
        display: flex;
        gap: 24px;
        flex-wrap: wrap;
        padding: 16px 0;
        border-bottom: 1px solid var(--border-subtle);
        margin-bottom: 20px;
    }
    
    .summary-stat {
        display: flex;
        align-items: center;
        gap: 8px;
    }
    
    .summary-stat-count {
        font-size: 20px;
        font-weight: 700;
    }
    
    .summary-stat-label {
        font-size: 13px;
        color: var(--text-secondary);
    }
    
    /* ═══════════════════════════════════════════════════════════════════════
       DATA TABLE STYLING - Clean professional tables
       ═══════════════════════════════════════════════════════════════════════ */
    
    .stDataFrame {
        border-radius: var(--radius-md) !important;
        overflow: hidden !important;
    }
    
    .stDataFrame table {
        border-collapse: separate !important;
        border-spacing: 0 !important;
    }
    
    .stDataFrame th {
        background: var(--bg-tertiary) !important;
        font-weight: 600 !important;
        text-transform: uppercase !important;
        letter-spacing: 0.3px !important;
        font-size: 11px !important;
    }
    
    .stDataFrame td {
        font-size: 13px !important;
    }
    
    /* ═══════════════════════════════════════════════════════════════════════
       BUTTON STYLING - Premium buttons
       ═══════════════════════════════════════════════════════════════════════ */
    
    .stButton > button {
        border-radius: var(--radius-md) !important;
        font-weight: 600 !important;
        letter-spacing: 0.3px !important;
        transition: all 0.2s ease !important;
    }
    
    .stButton > button:hover {
        transform: translateY(-1px) !important;
        box-shadow: var(--shadow-md) !important;
    }
    
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, var(--accent-blue), #4A9EFF) !important;
        border: none !important;
    }
    
    /* AI Button special styling */
    .ai-button > button {
        background: linear-gradient(135deg, #6366F1, #8B5CF6) !important;
        border: none !important;
        color: white !important;
    }
    
    .ai-button > button:hover {
        background: linear-gradient(135deg, #7C7FF2, #9D6FFF) !important;
    }
    
    /* ═══════════════════════════════════════════════════════════════════════
       EXPANDER STYLING - Clean expandable sections
       ═══════════════════════════════════════════════════════════════════════ */
    
    .stExpander {
        border: 1px solid var(--border-color) !important;
        border-radius: var(--radius-md) !important;
        background: var(--bg-card) !important;
    }
    
    .stExpander summary {
        font-weight: 600 !important;
    }
    
    /* ═══════════════════════════════════════════════════════════════════════
       FORM STYLING - Clean input forms
       ═══════════════════════════════════════════════════════════════════════ */
    
    .stTextInput input, .stNumberInput input, .stSelectbox select {
        border-radius: var(--radius-sm) !important;
        border: 1px solid var(--border-color) !important;
        background: var(--bg-secondary) !important;
    }
    
    .stTextInput input:focus, .stNumberInput input:focus {
        border-color: var(--accent-blue) !important;
        box-shadow: 0 0 0 2px var(--accent-blue-glow) !important;
    }
    
    /* ═══════════════════════════════════════════════════════════════════════
       DIVIDERS - Subtle separators
       ═══════════════════════════════════════════════════════════════════════ */
    
    hr {
        border: none !important;
        border-top: 1px solid var(--border-subtle) !important;
        margin: 24px 0 !important;
    }
    
    /* ═══════════════════════════════════════════════════════════════════════
       HIDE DEFAULT STREAMLIT ELEMENTS FOR CLEANER LOOK
       ═══════════════════════════════════════════════════════════════════════ */
    
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
</style>
"""


def inject_custom_css():
    """Inject custom CSS into the Streamlit app."""
    import streamlit as st
    st.markdown(TTA_CUSTOM_CSS, unsafe_allow_html=True)


# =============================================================================
# HTML COMPONENT BUILDERS - Clean modular components
# =============================================================================

def render_signal_card(ticker: str, status: str, grade: str, win_rate: float, 
                       avg_return: float, signal_type: str = None) -> str:
    """Render a clean signal card component."""
    
    status_class = {
        'READY': 'signal-card-ready',
        'CAUTION': 'signal-card-caution',
        'SKIP': 'signal-card-skip',
        'AO CONFIRM': 'signal-card-ao',
    }.get(status.upper().split()[0] if status else '', 'signal-card')
    
    badge_class = {
        'READY': 'status-ready',
        'CAUTION': 'status-caution',
        'SKIP': 'status-skip',
        'AO CONFIRM': 'status-ao',
        'WATCH': 'status-watch',
    }.get(status.upper().split()[0] if status else '', 'status-watch')
    
    return f"""
    <div class="signal-card {status_class}">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
            <span style="font-size: 20px; font-weight: 700; color: var(--text-primary);">{ticker}</span>
            <span class="status-badge {badge_class}">{status}</span>
        </div>
        <div style="display: flex; gap: 24px;">
            <div>
                <div class="metric-label">Grade</div>
                <div class="metric-value">{grade}</div>
            </div>
            <div>
                <div class="metric-label">Win Rate</div>
                <div class="metric-value">{win_rate:.0f}%</div>
            </div>
            <div>
                <div class="metric-label">Avg Return</div>
                <div class="metric-value {'metric-value-positive' if avg_return >= 0 else 'metric-value-negative'}">{avg_return:+.1f}%</div>
            </div>
            {f'<div><div class="metric-label">Type</div><div class="metric-value" style="font-size: 14px;">{signal_type}</div></div>' if signal_type else ''}
        </div>
    </div>
    """


def render_check_list(checks: dict) -> str:
    """Render a clean check list component."""
    check_items = [
        ('daily_macd_cross', 'MACD Cross Today', checks.get('daily_macd_cross')),
        ('macd_bullish', 'MACD Bullish', checks.get('macd_bullish')),
        ('ao_positive', 'AO Positive', checks.get('ao_positive')),
        ('ao_recent_cross', 'AO Zero Cross', checks.get('ao_recent_cross')),
        ('spy_above_200', 'SPY > 200 SMA', checks.get('spy_above_200')),
        ('vix_below_30', 'VIX < 30', checks.get('vix_below_30')),
    ]
    
    items_html = ""
    for key, label, passed in check_items:
        if key in checks:
            icon = "✓" if passed else "✗"
            item_class = "check-item-pass" if passed else "check-item-fail"
            color = "var(--accent-green)" if passed else "var(--accent-red)"
            items_html += f"""
            <div class="check-item {item_class}">
                <span class="check-icon" style="color: {color};">{icon}</span>
                <span class="check-label">{label}</span>
            </div>
            """
    
    return f'<div class="check-list">{items_html}</div>'


def render_trade_setup(entry: float, stop: float, target: float, 
                       risk_pct: float = None, rr_ratio: float = None) -> str:
    """Render a clean trade setup display."""
    return f"""
    <div class="trade-setup">
        <div class="trade-item trade-item-entry">
            <div class="trade-item-label">Entry</div>
            <div class="trade-item-value">${entry:.2f}</div>
        </div>
        <div class="trade-item trade-item-stop">
            <div class="trade-item-label">Stop Loss</div>
            <div class="trade-item-value">${stop:.2f}</div>
            {f'<div style="font-size: 11px; color: var(--text-muted);">{risk_pct:.1f}% risk</div>' if risk_pct else ''}
        </div>
        <div class="trade-item trade-item-target">
            <div class="trade-item-label">Target</div>
            <div class="trade-item-value">${target:.2f}</div>
        </div>
        {f'<div class="trade-item"><div class="trade-item-label">R:R</div><div class="trade-item-value">1:{rr_ratio:.1f}</div></div>' if rr_ratio else ''}
    </div>
    """


def render_recommendation_banner(recommendation: str, reason: str = "") -> str:
    """Render a clean recommendation banner."""
    
    rec_upper = recommendation.upper()
    
    if 'STRONG BUY' in rec_upper or 'BUY' in rec_upper:
        banner_class = 'recommendation-buy'
        icon = '🎯'
    elif 'CAUTION' in rec_upper:
        banner_class = 'recommendation-caution'
        icon = '⚠️'
    elif 'WATCH' in rec_upper:
        banner_class = 'recommendation-watch'
        icon = '👀'
    else:
        banner_class = 'recommendation-skip'
        icon = '🚫'
    
    return f"""
    <div class="recommendation-banner {banner_class}">
        <span class="recommendation-icon">{icon}</span>
        <div class="recommendation-content">
            <div class="recommendation-action">{recommendation}</div>
            <div class="recommendation-reason">{reason}</div>
        </div>
    </div>
    """


def render_summary_stats(ready: int, ao_confirm: int, late: int, 
                         watch: int, quality_wait: int, skip: int) -> str:
    """Render scan summary statistics."""
    return f"""
    <div class="summary-stats">
        <div class="summary-stat">
            <span class="summary-stat-count" style="color: var(--accent-green);">{ready}</span>
            <span class="summary-stat-label">Ready</span>
        </div>
        <div class="summary-stat">
            <span class="summary-stat-count" style="color: var(--accent-blue);">{ao_confirm}</span>
            <span class="summary-stat-label">AO Confirm</span>
        </div>
        <div class="summary-stat">
            <span class="summary-stat-count" style="color: var(--accent-purple);">{late}</span>
            <span class="summary-stat-label">Late Entry</span>
        </div>
        <div class="summary-stat">
            <span class="summary-stat-count" style="color: var(--accent-yellow);">{watch}</span>
            <span class="summary-stat-label">Watch</span>
        </div>
        <div class="summary-stat">
            <span class="summary-stat-count" style="color: var(--text-secondary);">{quality_wait}</span>
            <span class="summary-stat-label">Quality Wait</span>
        </div>
        <div class="summary-stat">
            <span class="summary-stat-count" style="color: var(--accent-red);">{skip}</span>
            <span class="summary-stat-label">Skip</span>
        </div>
    </div>
    """


def render_ai_box(content: str, recommendation: str = "", confidence: str = "") -> str:
    """Render a premium AI assessment box."""
    
    rec_color = {
        'STRONG BUY': 'var(--accent-green)',
        'BUY': 'var(--accent-green)',
        'CAUTIOUS ENTRY': 'var(--accent-yellow)',
        'WATCH': 'var(--accent-blue)',
        'SKIP': 'var(--accent-red)'
    }.get(recommendation.upper() if recommendation else '', 'var(--accent-blue)')
    
    return f"""
    <div class="ai-box">
        <div class="ai-header">
            <span class="ai-icon">🤖</span>
            <span class="ai-title">AI Trade Assessment</span>
            {f'<span class="status-badge" style="background: {rec_color}20; color: {rec_color}; border-color: {rec_color};">{recommendation}</span>' if recommendation else ''}
            <span class="ai-powered">Powered by GPT-4</span>
        </div>
        <div style="color: var(--text-secondary); line-height: 1.6;">
            {content}
        </div>
    </div>
    """


def render_section_header(icon: str, title: str, subtitle: str = "") -> str:
    """Render a clean section header."""
    return f"""
    <div class="section-header">
        <span style="font-size: 24px;">{icon}</span>
        <div>
            <h3 class="section-title">{title}</h3>
            {f'<p class="section-subtitle">{subtitle}</p>' if subtitle else ''}
        </div>
    </div>
    """
