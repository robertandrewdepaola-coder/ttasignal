# TTA Signal Detection Bug Fix

## 🐛 The Problem

The dashboard signals are wrong because the AO zero-cross check is implemented differently than the backtester.

### Backtester Logic (CORRECT) - Lines 338-345

```python
# Look BACKWARDS from the signal bar (not including today)
ao_cross_found = False
lookback = min(i, entry_window)  # entry_window = 20

for j in range(1, lookback):  # Start at 1, not 0
    # Check bars BEFORE today
    if daily['AO'].iloc[i-j] <= 0 and daily['AO'].iloc[i-j+1] > 0:
        ao_cross_found = True
        break
```

**Key points:**
- `j` starts at 1 (yesterday), not 0 (today)
- Looks at `i-j` and `i-j+1` (past bars only)
- Does NOT include today's potential cross as the qualifying event

### Dashboard Logic (BROKEN)

```python
ao_recent = ao.iloc[-20:]  # Last 20 bars INCLUDING today
ao_recent_cross = any((ao_recent.shift(1) <= 0) & (ao_recent > 0))
```

**Problems:**
1. Includes today in the window
2. If AO crosses zero TODAY and MACD also crosses TODAY, it would trigger
3. But this isn't a "pullback recovery" - it's catching the move too early

---

## 🔑 The Key Insight

The backtester requires a **sequence**:

```
Day -15: AO crosses from negative to positive (pullback recovery begins)
   ↓
Day -10 to -1: AO stays positive (building momentum)
   ↓
Day 0 (TODAY): MACD crosses up + AO still positive
   = VALID ENTRY SIGNAL ✅
```

The broken dashboard allows:

```
Day 0 (TODAY): AO crosses zero AND MACD crosses up simultaneously
   = FALSE SIGNAL ❌ (catching it too early, before confirmation)
```

---

## ✅ The Fix

### Option 1: Drop-in Replacement Function

Add this to your scanner or create a new module:

```python
def check_ao_zero_cross_in_lookback(ao_series: pd.Series, entry_window: int = 20) -> Tuple[bool, Optional[str]]:
    """
    Check if AO crossed from ≤0 to >0 in the PRIOR entry_window days.
    Does NOT include today's cross.
    
    Returns: (cross_found: bool, cross_date: Optional[str])
    """
    i = len(ao_series) - 1  # Today's index
    
    if i < entry_window + 1:
        return False, None
    
    # Look backwards from yesterday
    for j in range(1, entry_window + 1):
        past_idx = i - j
        
        if past_idx < 1:
            break
        
        ao_before = ao_series.iloc[past_idx - 1]
        ao_after = ao_series.iloc[past_idx]
        
        if ao_before <= 0 and ao_after > 0:
            return True, ao_series.index[past_idx].strftime('%Y-%m-%d')
    
    return False, None
```

### Option 2: Replace the Entire Check in Your Scanner

Find this in your `ml_reversal_scanner.py` or entry validation code:

```python
# ❌ BROKEN CODE - REMOVE THIS:
ao_recent = ao.iloc[-20:]
ao_recent_cross = any((ao_recent.shift(1) <= 0) & (ao_recent > 0))
```

Replace with:

```python
# ✅ FIXED CODE - ADD THIS:
ao_cross_found = False
i = len(ao) - 1  # Today

for j in range(1, 21):  # Look back 20 days, starting yesterday
    past_idx = i - j
    if past_idx < 1:
        break
    
    if ao.iloc[past_idx - 1] <= 0 and ao.iloc[past_idx] > 0:
        ao_cross_found = True
        break

checks['ao_recent_cross'] = ao_cross_found
```

---

## 📋 Complete Entry Logic Checklist

All four conditions must be TRUE on the **same day**:

| # | Condition | Check |
|---|-----------|-------|
| 1 | Daily MACD crossover **today** | `macd[-1] > signal[-1]` AND `macd[-2] <= signal[-2]` |
| 2 | Daily AO positive **today** | `ao[-1] > 0` |
| 3 | AO crossed zero in **prior** 20 days | Loop through `ao[-21:-1]` looking for zero-cross |
| 4 | Market filter passes | `SPY > SPY_200SMA` AND `VIX < 30` |

---

## 📁 Files Provided

1. **`tta_signal_detector.py`** - Complete corrected signal detection module
   - Drop-in replacement for your scanner
   - Exact match to backtester logic
   - Includes all helper functions

---

## 🧪 Testing

After applying the fix, test with:

```python
from tta_signal_detector import check_tta_entry_signal

result = check_tta_entry_signal('AAPL')

print(f"Signal: {result['signal']}")
print(f"Checks: {result['checks']}")
print(f"Reason: {result['reason']}")
```

The output should now match what your backtester would show for the same ticker on the same date.
