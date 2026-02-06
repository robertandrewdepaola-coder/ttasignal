# TTA Engine v16.37 - Stock Technical Analysis Dashboard

AI-powered stock technical analysis using Elliott Wave theory and Weinstein Stage analysis with multi-timeframe traffic light system.

## Features

- **Multi-Timeframe Traffic Light System**: Monthly, Weekly, Daily, 4H alignment signals
- **Elliott Wave Detection**: Automated W3/W4/W5 identification via AO histogram analysis
- **Divergence Detection**: Bar-by-bar and wave-based bearish divergence alerts
- **Adaptive Strategy Router**: Automatically routes to TTA or Break-Retest based on stock volatility
- **AI-Powered Analysis**: GPT-4 generated technical audits with v7.1 methodology

## Traffic Light Logic

| Dot Color | Condition |
|-----------|-----------|
| 🟢 GREEN | AO > 0 AND (rising OR no MACD cross) |
| 🟡 YELLOW | AO > 0 BUT falling AND MACD crossed down |
| 🔴 RED | AO < 0 |

| Wave State | + Green Momentum | + Yellow/Red Momentum |
|------------|------------------|----------------------|
| W3 | STRONG | WEAK |
| W5 | HOLD | FADING |
| W4 | PULL | WAIT |
| Corr! | AVOID | AVOID |

## Deployment to Streamlit Community Cloud

1. Push this folder to a GitHub repository
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Connect your GitHub repo
4. Set `app.py` as the main file
5. Add your `OPENAI_API_KEY` in Streamlit Secrets

## Secrets Configuration

In Streamlit Community Cloud, add these secrets:

```toml
OPENAI_API_KEY = "sk-your-key-here"
```

## Local Development

```bash
pip install -r requirements.txt
streamlit run app.py
```

## File Structure

```
├── app.py                    # Main Streamlit application
├── strategy_break_retest.py  # Break-Retest strategy module
├── requirements.txt          # Python dependencies
├── utils/
│   ├── __init__.py
│   └── react_bridge.py       # React dashboard bridge
└── .streamlit/
    └── config.toml           # Streamlit configuration
```

## Requirements

- Python 3.10+
- OpenAI API key (for AI analysis)

## License

Private - All rights reserved
# Trigger Streamlit rebuild - Fri Feb  6 13:20:34 AEST 2026
