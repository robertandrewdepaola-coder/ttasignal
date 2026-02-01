"""
TTA Engine v16.16 - Utils Module
Provides React dashboard rendering and analysis parsing utilities.
"""

# Export all public functions from react_bridge
from utils.react_bridge import (
    render_react_dashboard,
    parse_analysis_for_dashboard,
    enforce_v71_narrative_hygiene,
    enforce_verdict_consistency,
    validate_fib_numeric_sanity
)

__all__ = [
    'render_react_dashboard',
    'parse_analysis_for_dashboard',
    'enforce_v71_narrative_hygiene',
    'enforce_verdict_consistency',
    'validate_fib_numeric_sanity'
]
 "Add utils/init.py to fix module imports"
