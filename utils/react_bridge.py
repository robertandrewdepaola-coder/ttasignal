"""
React Bridge for Streamlit - TradingView Pro Dashboard v7.1
- Monospace for numbers
- Explicit conclusion + action plan
- Strict: AO never "confirms completion"
- v7.1 NARRATIVE HYGIENE enforced
"""
import json
import re
import math


def check_mtf_verdict_alignment(monthly_status, weekly_status, daily_status, fourhour_status, mtf_mode="MODERATE"):
    """Validate MTF alignment before issuing entry verdict."""
    if mtf_mode == "MODERATE":
        all_ok = all(status in ["STRONG", "WEAK"] for status in [monthly_status, weekly_status, daily_status, fourhour_status])
        if all_ok:
            return True, "M/W/D/4H aligned"
        else:
            avoid_tfs = []
            if monthly_status == "AVOID": avoid_tfs.append("M")
            if weekly_status == "AVOID": avoid_tfs.append("W")
            if daily_status == "AVOID": avoid_tfs.append("D")
            if fourhour_status == "AVOID": avoid_tfs.append("4H")
            return False, f"Timeframes in AVOID: {', '.join(avoid_tfs)}"
    return False, "Invalid MTF mode"


def get_ao_macd_status(ao_value, macd_value=None, ao_prev=None):
    """Determine traffic light status. Returns: STRONG, WEAK, or AVOID"""
    if ao_value is None or ao_value < 0:
        return "AVOID"
    if ao_prev is not None and ao_value < ao_prev:
        return "WEAK"
    return "STRONG"


def enforce_v71_narrative_hygiene(text: str, structure_state: str, weinstein_stage: str) -> str:
    """
    v7.1 NARRATIVE HYGIENE GOVERNOR (MANDATORY)
    This function MUST run before PDF + React rendering.
    
    Rules:
    1. STRUCTURE-FIRST VETO: If structure != "Impulsive", forbid impulse language
    2. WEINSTEIN ELIGIBILITY GATE: If stage == "UNCONFIRMED", no "trend-trading eligible"
    3. Downgrade certainty words where structure is unconfirmed
    """
    if not text:
        return text
    
    result = text
    is_impulsive = "impulsive" in (structure_state or "").lower()
    is_unconfirmed_weinstein = "unconfirmed" in (weinstein_stage or "").lower()
    
    # ========================================================
    # 1. STRUCTURE-FIRST VETO (MANDATORY)
    # If structure != "Impulsive", forbid ALL impulse language
    # ========================================================
    if not is_impulsive:
        # Forbidden phrases when structure is NOT impulsive
        impulse_forbidden = [
            (r'\bwave[- ]?5\b', 'upside continuation (conditional)'),
            (r'\bwave[- ]?3\b', 'corrective structure'),
            (r'\bwave[- ]?iii\b', 'corrective structure'),
            (r'\bwave[- ]?v\b', 'corrective structure'),
            (r'\bimpulse developing\b', 'structure developing'),
            (r'\bimpulse underway\b', 'structure developing'),
            (r'\bimpulsive move\b', 'directional move'),
            (r'\bimpulsive rally\b', 'corrective rally'),
            (r'\bimpulse confirmed\b', 'structure unconfirmed'),
            (r'\b5-wave impulse\b', 'overlapping structure'),
            (r'\bfive-wave impulse\b', 'overlapping structure'),
        ]
        for pattern, replacement in impulse_forbidden:
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    
    # ========================================================
    # 2. WEINSTEIN ELIGIBILITY GATE (BINARY)
    # If Weinstein == "UNCONFIRMED", no trend-trading language
    # ========================================================
    if is_unconfirmed_weinstein:
        trend_forbidden = [
            (r'\btrend[- ]?trading eligible\b', 'Trend eligibility unconfirmed from provided evidence'),
            (r'\btrend eligible\b', 'Trend eligibility unconfirmed'),
            (r'\bstage 2 confirmed\b', 'Stage unconfirmed'),
            (r'\bstage 2 trending\b', 'Stage unconfirmed'),
        ]
        for pattern, replacement in trend_forbidden:
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    
    # ========================================================
    # 3. DOWNGRADE CERTAINTY WORDS when structure is unconfirmed
    # ========================================================
    if not is_impulsive:
        certainty_downgrades = [
            (r'\bconfirmed impulse\b', 'unconfirmed structure'),
            (r'\bwave complete\b', 'structure developing'),
            (r'\bwave is complete\b', 'structure is developing'),
            (r'\bimpulse complete\b', 'structure developing'),
        ]
        for pattern, replacement in certainty_downgrades:
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    
    return result


def validate_fib_numeric_sanity(anchor_low, anchor_high, fib_zones) -> str:
    """
    FIB NUMERIC SANITY CHECK (HARD GATE)
    Before allowing fib_zones to render:
    - Validate that: high > low
    - Validate that fib levels are numeric and within range
    If ANY value is None, NaN, 0, or placeholder → return None
    """
    # If fib_zones is already None, keep it None
    if fib_zones is None:
        return None
    
    # Validate anchors
    try:
        low_val = float(anchor_low) if anchor_low is not None else None
        high_val = float(anchor_high) if anchor_high is not None else None
    except (ValueError, TypeError):
        return None
    
    # Check for invalid values
    if low_val is None or high_val is None:
        return None
    if low_val <= 0 or high_val <= 0:
        return None
    if math.isnan(low_val) or math.isnan(high_val):
        return None
    if high_val <= low_val:
        return None
    
    # Check for placeholder patterns in fib_zones string
    placeholder_patterns = [
        r'\$0\.00', r'\$0\.0', r'N/A', r'nan', r'NaN', r'None',
        r'\$30\.00',  # Known placeholder
    ]
    for pattern in placeholder_patterns:
        if re.search(pattern, str(fib_zones), re.IGNORECASE):
            return None
    
    return fib_zones


def enforce_verdict_consistency(verdict: str, structure_state: str, trigger_state: str) -> str:
    """
    FINAL VERDICT CONSISTENCY CHECK
    If structure == "Corrective / Developing":
    - MUST NOT reference any specific Elliott wave number
    - Verdict must reference ONLY: structure + triggers + AO (confirmation-only)
    """
    if not verdict:
        return verdict
    
    is_developing = any(term in (structure_state or "").lower() for term in ["developing", "corrective", "overlapping"])
    
    if not is_developing:
        return verdict
    
    result = verdict
    
    # Remove specific wave number references when developing
    wave_number_patterns = [
        (r'\bwave[- ]?[1-5]\b', ''),
        (r'\bwave[- ]?[iv]+\b', ''),
        (r'\b[iv]+[- ]?wave\b', ''),
        (r'\bW[1-5]\b', ''),
    ]
    for pattern, replacement in wave_number_patterns:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    
    # Clean up any double spaces left behind
    result = re.sub(r'\s+', ' ', result).strip()
    
    return result

def render_react_dashboard(analysis_data_dict: dict) -> str:
    """Generate complete HTML with embedded React TradingView Pro dashboard."""
    
    json_data = json.dumps(analysis_data_dict, ensure_ascii=False)
    
    html_template = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>v7.1 TradingView Pro Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script crossorigin src="https://unpkg.com/react@18/umd/react.development.js"></script>
    <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.development.js"></script>
    <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600;700&display=swap');
        
        * { box-sizing: border-box; }
        body { 
            margin: 0; 
            padding: 0; 
            background: #070A12;
            font-family: 'Inter', system-ui, -apple-system, sans-serif;
            min-height: 100vh;
        }
        .font-mono { font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, monospace; }
    </style>
    <script>
        tailwind.config = {
            theme: {
                extend: {
                    fontFamily: {
                        mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'monospace'],
                    }
                }
            }
        }
    </script>
</head>
<body>
    <div id="react-root"></div>
    
    <script type="text/babel">
        /**
         * TradingView-Pro Dashboard (v7.1 UI)
         * Do not change any Python logic, parsing, IDs, prop names, or data structure. Only replace the JSX/CSS.
         * Execution authority must be derived strictly from execution_mode (DAILY_MINOR or H4_MINUETTE). Weekly is context only.
         * Keep A/B/A2 labels and values exactly as passed in—no recomputation.
         */
        const analysisData = ''' + json_data + ''';
        
        const cn = (...xs) => xs.filter(Boolean).join(" ");
        
        function fmtMoney(n) {
            if (n === null || n === undefined || Number.isNaN(Number(n))) return "—";
            const x = Number(n);
            return "$" + x.toFixed(2);
        }
        
        function clamp(n, a, b) {
            return Math.max(a, Math.min(b, n));
        }
        
        // SINGLE SOURCE OF TRUTH: MODE_META mapping (CANONICAL DEGREE MAP)
        // v7.1 CANONICAL DEGREE MAP:
        // - Weekly = Intermediate (Regime context + A2 ONLY — NEVER execution authority)
        // - Daily = Minor (Execution if user chooses Daily)
        // - 4H = Minuette (Execution if user chooses 4H)
        // - 60m = Minute (Entry timing only)
        // EXECUTION AUTHORITY CAN ONLY BE: DAILY (MINOR) OR 4H (MINUETTE)
        const MODE_META = {
            DAILY: {
                execAuthorityLabel: "DAILY (MINOR)",
                execDegreeLabel: "Minor (Daily)",
                triggerCloseLabel: "Daily close",
                tf: "Daily",
                degree: "Minor",
                weeklyRole: "Weekly (Intermediate) is regime context only"
            },
            DAILY_MINOR: {
                execAuthorityLabel: "DAILY (MINOR)",
                execDegreeLabel: "Minor (Daily)",
                triggerCloseLabel: "Daily close",
                tf: "Daily",
                degree: "Minor",
                weeklyRole: "Weekly (Intermediate) is regime context only"
            },
            H4: {
                execAuthorityLabel: "4H (MINUETTE)",
                execDegreeLabel: "Minuette (4H)",
                triggerCloseLabel: "4H close",
                tf: "4H",
                degree: "Minuette",
                weeklyRole: "Weekly (Intermediate) is regime context only"
            },
            H4_MINUETTE: {
                execAuthorityLabel: "4H (MINUETTE)",
                execDegreeLabel: "Minuette (4H)",
                triggerCloseLabel: "4H close",
                tf: "4H",
                degree: "Minuette",
                weeklyRole: "Weekly (Intermediate) is regime context only"
            }
            // NOTE: No WEEKLY entry — Weekly is NEVER execution authority
        };
        
        function getModeMeta(executionMode) {
            // Derive ONLY from execution_mode - default is DAILY_MINOR
            // Weekly is NEVER allowed as execution authority
            let mode = (executionMode || "DAILY_MINOR").toUpperCase().replace(/[^A-Z0-9_]/g, "_");
            // Block any Weekly mode - default to Daily
            if (mode.includes("WEEKLY") || mode.includes("INTERMEDIATE")) {
                mode = "DAILY_MINOR";
            }
            return MODE_META[mode] || MODE_META.DAILY_MINOR;
        }
        
        // TRADER STATE: derive from triggers (A, B, A2)
        function getTraderState(data) {
            const { trigger_state, triggers } = data || {};
            const modeMeta = getModeMeta(data?.execution_mode);
            const A = triggers?.A, B = triggers?.B, A2 = triggers?.A2;
            const t = (trigger_state || "NONE").toUpperCase();
            
            let state = { label: "", sub: "", tone: "amber" };
            
            if (t === "BEARISH") {
                state = {
                    label: "BEARISH ACTIVATION LIVE",
                    sub: modeMeta.degree + " corrective extension risk. Stand aside or manage risk.",
                    tone: "red"
                };
            } else if (t === "BULLISH") {
                state = {
                    label: "BULLISH CONTINUATION PERMITTED",
                    sub: "Correction dead at " + modeMeta.degree + " degree. Long setups allowed.",
                    tone: "green"
                };
            } else {
                state = {
                    label: "RANGE / DEVELOPING",
                    sub: "No trigger. No trade until " + modeMeta.triggerCloseLabel + " breaks A or B.",
                    tone: "amber"
                };
            }
            
            // Check for A2 regime failure
            if (A2 && data?.current_price < A2) {
                state.sub += " REGIME FAILURE (A2). Alternate promoted.";
            }
            
            return state;
        }
        
        function verdictMeta(triggerState, verdictText) {
            const v = (verdictText || "").toLowerCase();
            const t = (triggerState || "NONE").toUpperCase();
            
            // If a trigger is hit, prefer that framing
            if (t === "BEARISH") return { label: "TRIGGER HIT — BEARISH ACTIVATION", tone: "red" };
            if (t === "BULLISH") return { label: "TRIGGER HIT — BULLISH CONTINUATION", tone: "green" };
            
            // Otherwise infer from verdict text
            if (v.includes("no trade") || v.includes("corrective")) return { label: "NO TRIGGER HIT — RANGE / CORRECTIVE", tone: "amber" };
            if (v.includes("bullish continuation")) return { label: "BULLISH CONTINUATION (CONDITIONAL)", tone: "green" };
            if (v.includes("bearish activation")) return { label: "BEARISH ACTIVATION (CONDITIONAL)", tone: "red" };
            return { label: "NO TRIGGER HIT — RANGE / DEVELOPING", tone: "amber" };
        }
        
        function buildConclusion(data, meta) {
            const { ticker, trigger_state, triggers, elliott } = data || {};
            const A = triggers?.A, B = triggers?.B, A2 = triggers?.A2;
            const t = (trigger_state || "NONE").toUpperCase();
            const structure = (elliott?.structure || "").toLowerCase();
            const isOverlapping = structure.includes("corrective") || structure.includes("developing");
            
            if (t === "BEARISH") {
                return ticker + ": Bearish activation is live at " + meta.degree + " degree. Treat downside as corrective extension risk" + (isOverlapping ? " (structure overlapping)" : "") + "; do not label impulse unless structure proves 5-wave. Bullish continuation requires " + meta.triggerCloseLabel + " above " + fmtMoney(B) + ".";
            }
            if (t === "BULLISH") {
                return ticker + ": Bullish continuation is live at " + meta.degree + " degree. The corrective thesis is terminated while price holds above " + fmtMoney(B) + "; downside risk reactivates on " + meta.triggerCloseLabel + " below " + fmtMoney(A) + ".";
            }
            // No trigger hit
            return ticker + ": No trigger hit — range / developing. Stand aside until price resolves: " + meta.triggerCloseLabel + " above " + fmtMoney(B) + " unlocks bullish continuation; " + meta.triggerCloseLabel + " below " + fmtMoney(A) + " activates bearish extension risk." + (A2 ? " Weekly close below " + fmtMoney(A2) + " = Primary regime failure." : "");
        }
        
        // Compact semi-circle probability gauge
        function ProbabilityGauge({ primary, alternate }) {
            const pct = clamp(primary || 50, 0, 100);
            const angle = -90 + (pct / 100) * 180; // -90 to 90
            
            return (
                <div className="relative w-full h-24 flex flex-col items-center justify-end">
                    <svg viewBox="0 0 100 55" className="w-full max-w-[180px]">
                        {/* Background arc */}
                        <path
                            d="M 5 50 A 45 45 0 0 1 95 50"
                            fill="none"
                            stroke="rgba(255,255,255,0.1)"
                            strokeWidth="8"
                            strokeLinecap="round"
                        />
                        {/* Primary (left side - green) */}
                        <path
                            d="M 5 50 A 45 45 0 0 1 50 5"
                            fill="none"
                            stroke="rgba(16,185,129,0.4)"
                            strokeWidth="8"
                            strokeLinecap="round"
                        />
                        {/* Alternate (right side - amber) */}
                        <path
                            d="M 50 5 A 45 45 0 0 1 95 50"
                            fill="none"
                            stroke="rgba(245,158,11,0.4)"
                            strokeWidth="8"
                            strokeLinecap="round"
                        />
                        {/* Needle */}
                        <line
                            x1="50"
                            y1="50"
                            x2={50 + 35 * Math.cos((angle - 90) * Math.PI / 180)}
                            y2={50 + 35 * Math.sin((angle - 90) * Math.PI / 180)}
                            stroke="white"
                            strokeWidth="2"
                            strokeLinecap="round"
                        />
                        <circle cx="50" cy="50" r="4" fill="white" />
                        {/* Labels */}
                        <text x="8" y="52" fill="rgba(255,255,255,0.5)" fontSize="6">0%</text>
                        <text x="46" y="8" fill="rgba(255,255,255,0.5)" fontSize="6">50%</text>
                        <text x="85" y="52" fill="rgba(255,255,255,0.5)" fontSize="6">100%</text>
                    </svg>
                </div>
            );
        }
        
        // Format report text with bullets and highlights
        function FormatReportText({ text, accentColor }) {
            if (!text) return null;
            
            // Highlight prices ($ followed by numbers)
            const highlightPrices = (str) => {
                return str.replace(/\$[\d,]+\.?\d*/g, match => 
                    '<span class="font-mono font-semibold text-cyan-300">' + match + '</span>'
                );
            };
            
            // Clean up text first - remove numbered list artifacts and clean markdown
            let cleanedText = text
                .replace(/\*\*/g, '')           // Remove markdown bold
                .replace(/^\s*\d+\.\s*/gm, '')  // Remove numbered list markers
                .replace(/^[-•]\s*/gm, '')      // Remove bullet markers
                .replace(/^:\s*/gm, '')         // Remove leading colons
                .replace(/of Rules:/gi, '')     // Remove "of Rules:" artifact
                .replace(/^[A-Z]{1,5}:\s*/gm, '') // Remove ticker prefixes
                .replace(/::/g, ':')            // Fix double colons
                .trim();
            
            // Split by " - " which is our delimiter for fallback summaries
            let items = cleanedText.split(/\s+-\s+/).filter(p => p.trim().length > 10);
            
            // If that didn't work well, try splitting by sentences with key terms
            if (items.length <= 1) {
                items = cleanedText.split(/(?<=[.!])\s+(?=[A-Z])/).filter(p => p.trim().length > 15);
            }
            
            // Filter out short/meaningless items
            items = items.filter(item => {
                const trimmed = item.trim();
                return trimmed.length > 10 && 
                       !trimmed.match(/^[0-9.]+$/) &&
                       !trimmed.match(/^of\s/i);
            });
            
            if (items.length <= 1) {
                // Single paragraph - just highlight prices
                return (
                    <div className="text-sm leading-relaxed text-white/85" 
                         dangerouslySetInnerHTML={{ __html: highlightPrices(cleanedText) }} />
                );
            }
            
            return (
                <div className="space-y-2.5">
                    {items.map((item, i) => {
                        const trimmed = item.trim();
                        // Check if item has a header pattern like "Label: content"
                        const colonIdx = trimmed.indexOf(':');
                        let header = null;
                        let content = trimmed;
                        
                        if (colonIdx > 0 && colonIdx < 40) {
                            const possibleHeader = trimmed.slice(0, colonIdx).trim();
                            // Only treat as header if it looks like one (no spaces or short)
                            if (possibleHeader.split(' ').length <= 4) {
                                header = possibleHeader;
                                content = trimmed.slice(colonIdx + 1).trim();
                            }
                        }
                        
                        return (
                            <div key={i} className="flex gap-2">
                                <span className={cn("mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full", accentColor)} />
                                <div className="text-sm leading-relaxed">
                                    {header && (
                                        <span className="font-semibold text-white/95">{header}: </span>
                                    )}
                                    <span className="text-white/75" dangerouslySetInnerHTML={{ __html: highlightPrices(content) }} />
                                </div>
                            </div>
                        );
                    })}
                </div>
            );
        }
        
        // Panel component
        function Panel({ title, icon: Icon, right, children, className }) {
            return (
                <div className={cn(
                    "relative overflow-hidden rounded-2xl border border-white/10",
                    "bg-gradient-to-b from-slate-900/70 to-slate-950/70",
                    "shadow-[0_0_0_1px_rgba(255,255,255,0.04),0_20px_60px_rgba(0,0,0,0.55)]",
                    className
                )}>
                    <div className="flex items-center justify-between px-5 pt-4">
                        <div className="flex items-center gap-2">
                            {Icon ? (
                                <div className="grid h-8 w-8 place-items-center rounded-xl border border-white/10 bg-white/5">
                                    <span className="h-4 w-4 text-white/80">{Icon}</span>
                                </div>
                            ) : null}
                            <div className="text-xs font-semibold tracking-widest text-white/60">{title}</div>
                        </div>
                        {right}
                    </div>
                    <div className="px-5 pb-5 pt-3">{children}</div>
                    <div className="pointer-events-none absolute -right-20 -top-20 h-56 w-56 rounded-full bg-white/5 blur-3xl" />
                </div>
            );
        }
        
        // Trigger Card component (compact)
        function TriggerCard({ kind, level, text, condition }) {
            const isBear = kind === "bear";
            const tone = isBear ? "red" : "green";
            
            const toneClasses = tone === "red"
                ? "border-red-500/25 shadow-[0_0_0_1px_rgba(239,68,68,0.12)]"
                : "border-emerald-500/25 shadow-[0_0_0_1px_rgba(16,185,129,0.12)]";
            
            const glow = tone === "red"
                ? "bg-gradient-to-b from-red-950/40 via-slate-950/50 to-slate-950/60"
                : "bg-gradient-to-b from-emerald-950/35 via-slate-950/50 to-slate-950/60";
            
            return (
                <div className={cn("relative overflow-hidden rounded-xl border", toneClasses, glow)}>
                    <div className="flex items-center justify-between px-4 py-3">
                        <div className="flex items-center gap-2">
                            <div className={cn("grid h-7 w-7 place-items-center rounded-lg border border-white/10 bg-white/5")}>
                                <span className={cn("text-base", isBear ? "text-red-300" : "text-emerald-200")}>
                                    {isBear ? "↓" : "↑"}
                                </span>
                            </div>
                            <div>
                                <div className="text-[10px] font-semibold tracking-widest text-white/55">
                                    {isBear ? "TRIGGER A" : "TRIGGER B"}
                                </div>
                                <div className={cn("font-mono text-lg font-semibold", isBear ? "text-red-200" : "text-emerald-200")}>
                                    {fmtMoney(level)}
                                </div>
                            </div>
                        </div>
                        <div className="text-[10px] font-semibold text-white/45">{condition}</div>
                    </div>
                    <div className="border-t border-white/5 px-4 py-2">
                        <div className="text-xs text-white/70 leading-relaxed">{text}</div>
                    </div>
                </div>
            );
        }
        
        // Scenario Bar component
        function ScenarioBar({ label, pct, tone }) {
            const p = clamp(Number(pct) || 0, 0, 100);
            const bar = tone === "primary"
                ? "from-amber-400/70 via-orange-400/70 to-red-400/70"
                : "from-emerald-400/70 via-cyan-400/60 to-sky-400/70";
            
            return (
                <div className="rounded-xl border border-white/10 bg-white/5 px-4 py-3">
                    <div className="flex items-center justify-between">
                        <div className="text-sm font-semibold text-white/85">{label}</div>
                        <div className={cn("font-mono text-sm font-semibold", tone === "primary" ? "text-amber-200" : "text-emerald-200")}>
                            {p.toFixed(0)}%
                        </div>
                    </div>
                    <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-black/30">
                        <div className={cn("h-full rounded-full bg-gradient-to-r", bar)} style={{ width: p + "%" }} />
                    </div>
                </div>
            );
        }
        
        // 180-degree gauge
        function Gauge180({ value = 65, label = "PRIMARY" }) {
            const v = clamp(Number(value) || 0, 0, 100);
            const angle = -90 + (v / 100) * 180;
            
            const ticks = [];
            for (let i = 0; i < 11; i++) {
                const a = (-90 + i * 18) * (Math.PI / 180);
                const x1 = 180 + Math.cos(a) * 150;
                const y1 = 180 + Math.sin(a) * 150;
                const x2 = 180 + Math.cos(a) * 160;
                const y2 = 180 + Math.sin(a) * 160;
                ticks.push(
                    <line key={i} x1={x1} y1={y1} x2={x2} y2={y2}
                        stroke="rgba(255,255,255,0.16)" strokeWidth={i % 5 === 0 ? 2 : 1} />
                );
            }
            
            return (
                <div className="flex h-full flex-col items-center justify-center gap-2">
                    <div className="relative h-44 w-full max-w-[360px]">
                        <svg viewBox="0 0 360 220" className="h-full w-full">
                            <path d="M 40 180 A 140 140 0 0 1 320 180" fill="none"
                                stroke="rgba(255,255,255,0.10)" strokeWidth="18" strokeLinecap="round" />
                            <defs>
                                <linearGradient id="gaugeGrad" x1="40" y1="180" x2="320" y2="180" gradientUnits="userSpaceOnUse">
                                    <stop offset="0%" stopColor="rgba(34,197,94,0.85)" />
                                    <stop offset="50%" stopColor="rgba(245,158,11,0.85)" />
                                    <stop offset="100%" stopColor="rgba(239,68,68,0.85)" />
                                </linearGradient>
                                <filter id="softGlow" x="-50%" y="-50%" width="200%" height="200%">
                                    <feGaussianBlur stdDeviation="3" result="blur" />
                                    <feMerge>
                                        <feMergeNode in="blur" />
                                        <feMergeNode in="SourceGraphic" />
                                    </feMerge>
                                </filter>
                            </defs>
                            <path d="M 40 180 A 140 140 0 0 1 320 180" fill="none"
                                stroke="url(#gaugeGrad)" strokeWidth="18" strokeLinecap="round"
                                filter="url(#softGlow)" opacity="0.9" />
                            {ticks}
                            <g transform={"rotate(" + angle + " 180 180)"} filter="url(#softGlow)">
                                <line x1="180" y1="180" x2="180" y2="58" stroke="rgba(255,255,255,0.92)" strokeWidth="3" />
                                <line x1="180" y1="180" x2="180" y2="70" stroke="rgba(59,130,246,0.85)" strokeWidth="2" />
                            </g>
                            <circle cx="180" cy="180" r="10" fill="rgba(15,23,42,0.9)" stroke="rgba(255,255,255,0.25)" />
                            <circle cx="180" cy="180" r="4" fill="rgba(255,255,255,0.85)" />
                            <text x="180" y="150" textAnchor="middle" className="fill-white"
                                style={{ fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", fontSize: 36, fontWeight: 700 }}>
                                {v.toFixed(0)}%
                            </text>
                            <text x="180" y="175" textAnchor="middle" className="fill-white/60"
                                style={{ fontFamily: "ui-sans-serif, system-ui", fontSize: 12, fontWeight: 700, letterSpacing: 2 }}>
                                {label}
                            </text>
                            <text x="40" y="205" textAnchor="start" className="fill-white/45"
                                style={{ fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", fontSize: 11 }}>0%</text>
                            <text x="320" y="205" textAnchor="end" className="fill-white/45"
                                style={{ fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", fontSize: 11 }}>100%</text>
                        </svg>
                    </div>
                </div>
            );
        }
        
        // Modal component
        function Modal({ open, title, onClose, children }) {
            if (!open) return null;
            return (
                <div className="fixed inset-0 z-50 grid place-items-center bg-black/70 p-4">
                    <div className="w-full max-w-4xl overflow-hidden rounded-2xl border border-white/10 bg-slate-950 shadow-2xl">
                        <div className="flex items-center justify-between border-b border-white/10 px-5 py-4">
                            <div className="flex items-center gap-2">
                                <span className="h-4 w-4 text-white/75">📄</span>
                                <div className="text-sm font-semibold text-white/85">{title}</div>
                            </div>
                            <button onClick={onClose}
                                className="rounded-xl border border-white/10 bg-white/5 p-2 text-white/70 hover:bg-white/10">
                                ✕
                            </button>
                        </div>
                        <div className="max-h-[75vh] overflow-auto p-5">
                            <div className="whitespace-pre-wrap font-mono text-[12px] leading-relaxed text-slate-100/90">
                                {children}
                            </div>
                        </div>
                    </div>
                </div>
            );
        }
        
        // Main Dashboard
        function TradingViewProDashboard() {
            const [open, setOpen] = React.useState(false);
            const data = analysisData;
            
            // SINGLE SOURCE OF TRUTH: Use MODE_META from execution_mode
            // Weekly is CONTEXT ONLY — never execution authority
            const modeMeta = getModeMeta(data.execution_mode);
            const triggerMeta = verdictMeta(data.trigger_state, data?.verdict?.sentence || "");
            const traderState = getTraderState(data);
            const Conclusion = buildConclusion(data, modeMeta);
            
            // Use A/B/A2 exactly as passed
            const A = data?.triggers?.A;
            const B = data?.triggers?.B;
            const A2 = data?.triggers?.A2;
            
            const primary = clamp(data?.probabilities?.primary ?? 65, 0, 100);
            const alternate = clamp(data?.probabilities?.alternate ?? (100 - primary), 0, 100);
            
            // Rationale bullets for probability panel
            const structure = data?.elliott?.structure || "";
            const isStructureDeveloping = structure.toLowerCase().includes("developing") || structure.toLowerCase().includes("corrective");
            const rationaleBullets = [
                isStructureDeveloping ? "Structure developing / unconfirmed" : "Structure confirmed at " + modeMeta.degree + " degree",
                "Triggers define bias — stand aside until A or B resolves",
                "AO is momentum-only; cannot confirm completion"
            ];
            
            const v = data?.validator || {};
            const checks = [
                { k: "Degree-locked", ok: !!v.degreeLocked },
                { k: "Label-consistent", ok: !!v.labelConsistent },
                { k: "Fib anchored", ok: !!v.fibAnchored },
                { k: "AO confirm-only", ok: !!v.aoConfirmOnly },
                { k: "Triggers coherent", ok: !!v.triggersCoherent },
            ];
            
            return (
                <div className="min-h-screen bg-[#070A12] text-white">
                    {/* Background */}
                    <div className="pointer-events-none fixed inset-0">
                        <div className="absolute inset-0 bg-[radial-gradient(circle_at_15%_20%,rgba(59,130,246,0.18),transparent_38%),radial-gradient(circle_at_80%_10%,rgba(239,68,68,0.16),transparent_40%),radial-gradient(circle_at_50%_85%,rgba(16,185,129,0.10),transparent_45%)]" />
                        <div className="absolute inset-0 bg-[linear-gradient(to_bottom,rgba(0,0,0,0.2),rgba(0,0,0,0.85))]" />
                    </div>
                    
                    <div className="relative mx-auto max-w-6xl px-5 py-6">
                        {/* Header */}
                        <div className={cn(
                            "mb-4 overflow-hidden rounded-3xl border border-white/10",
                            "bg-gradient-to-b from-slate-900/60 to-slate-950/60",
                            "shadow-[0_0_0_1px_rgba(255,255,255,0.04),0_30px_90px_rgba(0,0,0,0.55)]"
                        )}>
                            <div className="flex flex-col gap-4 px-6 py-5 md:flex-row md:items-center md:justify-between">
                                <div className="flex items-baseline gap-4">
                                    <div className="text-4xl font-bold tracking-tight">{data.ticker || "TICKER"}</div>
                                    <div className="font-mono text-3xl font-semibold text-white/90">{fmtMoney(data.close)}</div>
                                    <div className="ml-1 text-xs font-semibold tracking-widest text-white/50">
                                        {modeMeta.execAuthorityLabel.toUpperCase()}
                                    </div>
                                </div>
                                
                                <div className="flex items-center gap-3 flex-wrap">
                                    {/* AI vs TTA Comparison Badge */}
                                    {data.ai_tta_comparison && (
                                        <div className={cn(
                                            "flex items-center gap-2 rounded-2xl border px-4 py-2 text-xs font-semibold tracking-widest",
                                            data.ai_tta_comparison.agrees 
                                                ? "border-emerald-500/25 bg-emerald-950/25 text-emerald-200"
                                                : "border-red-500/25 bg-red-950/35 text-red-200"
                                        )}>
                                            <span className="text-sm">{data.ai_tta_comparison.agrees ? "✅" : "⚠️"}</span>
                                            {data.ai_tta_comparison.agrees 
                                                ? "AI & TTA AGREE" 
                                                : `AI: ${data.ai_tta_comparison.ai_sentiment} ≠ TTA`
                                            }
                                        </div>
                                    )}
                                    <div className={cn(
                                        "flex items-center gap-2 rounded-2xl border px-4 py-2 text-xs font-semibold tracking-widest",
                                        triggerMeta.tone === "red" && "border-red-500/25 bg-red-950/35 text-red-200",
                                        triggerMeta.tone === "green" && "border-emerald-500/25 bg-emerald-950/25 text-emerald-200",
                                        triggerMeta.tone === "amber" && "border-amber-500/25 bg-amber-950/20 text-amber-200"
                                    )}>
                                        <span className="h-2 w-2 rounded-full bg-current opacity-80" />
                                        {triggerMeta.label}
                                    </div>
                                    <button onClick={() => setOpen(true)}
                                        className="rounded-2xl border border-white/10 bg-white/5 px-4 py-2 text-xs font-semibold tracking-widest text-white/80 hover:bg-white/10">
                                        Full Report
                                    </button>
                                </div>
                            </div>
                            
                            {/* TRADER STATE block */}
                            <div className={cn(
                                "border-t border-white/10 px-6 py-3",
                                traderState.tone === "red" && "bg-red-950/20",
                                traderState.tone === "green" && "bg-emerald-950/15",
                                traderState.tone === "amber" && "bg-amber-950/15"
                            )}>
                                <div className="flex items-center gap-3">
                                    <div className={cn(
                                        "h-3 w-3 rounded-full",
                                        traderState.tone === "red" && "bg-red-400 animate-pulse",
                                        traderState.tone === "green" && "bg-emerald-400",
                                        traderState.tone === "amber" && "bg-amber-400"
                                    )} />
                                    <div className={cn(
                                        "text-sm font-bold tracking-wide",
                                        traderState.tone === "red" && "text-red-200",
                                        traderState.tone === "green" && "text-emerald-200",
                                        traderState.tone === "amber" && "text-amber-200"
                                    )}>
                                        {traderState.label}
                                    </div>
                                </div>
                                <div className="mt-1 text-xs text-white/70">{traderState.sub}</div>
                            </div>
                            
                            {/* Conclusion strip */}
                            <div className="border-t border-white/10 px-6 py-3">
                                <div className="text-[11px] font-semibold tracking-widest text-white/50">CONCLUSION</div>
                                <div className="mt-1 text-sm leading-relaxed text-white/85">{Conclusion}</div>
                            </div>
                        </div>
                        
                        {/* Triggers row */}
                        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                            <TriggerCard
                                kind="bear"
                                level={A}
                                condition={modeMeta.triggerCloseLabel + " below A"}
                                text={"Activation (extension risk) at " + modeMeta.degree + " degree. Treat as corrective continuation risk; do NOT label impulse while below B."}
                            />
                            <TriggerCard
                                kind="bull"
                                level={B}
                                condition={modeMeta.triggerCloseLabel + " above B"}
                                text={"Correction dead level (range cap). A close above B permits bullish continuation at " + modeMeta.degree + " degree."}
                            />
                        </div>
                        
                        {/* Probability + Action Plan - tightened layout */}
                        <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
                            <Panel title="PROBABILITY ASSESSMENT" icon="📊" className="lg:col-span-2"
                                right={<div className="text-[11px] font-semibold tracking-widest text-white/40">Primary vs Alternate</div>}>
                                <div className="grid grid-cols-2 gap-4 items-start">
                                    <div className="rounded-2xl border border-white/10 bg-black/20 p-3" style={{ maxHeight: "200px" }}>
                                        <Gauge180 value={primary} label="PRIMARY" />
                                    </div>
                                    <div className="flex flex-col gap-2">
                                        <ScenarioBar label={data?.probabilities?.primary_label || "Primary Scenario"} pct={primary} tone="primary" />
                                        <ScenarioBar label={data?.probabilities?.alternate_label || "Alternate Scenario"} pct={alternate} tone="alt" />
                                        <div className="mt-1 space-y-1">
                                            {rationaleBullets.map((b, i) => (
                                                <div key={i} className="flex items-start gap-1.5 text-[11px] text-white/50">
                                                    <span className="text-cyan-400/70 mt-px">•</span>
                                                    <span>{b}</span>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                </div>
                            </Panel>
                            
                            <Panel title="ACTION PLAN" icon="⚡" className="border-red-500/15">
                                <div className="text-sm font-semibold text-white/85">
                                    {data?.action_plan?.now || "Stand aside. No trigger resolved."}
                                </div>
                                
                                <div className="mt-3 space-y-2">
                                    <div className="rounded-xl border border-white/10 bg-white/5 p-3">
                                        <div className="text-[11px] font-semibold tracking-widest text-white/60">BULLISH IF</div>
                                        <div className="mt-1 text-sm text-white/80">
                                            {data?.action_plan?.bullish_if || ("IF " + modeMeta.triggerCloseLabel + " above " + fmtMoney(B) + " → bullish continuation permitted at " + modeMeta.degree + " degree.")}
                                        </div>
                                    </div>
                                    
                                    <div className="rounded-xl border border-white/10 bg-white/5 p-3">
                                        <div className="text-[11px] font-semibold tracking-widest text-white/60">BEARISH IF</div>
                                        <div className="mt-1 text-sm text-white/80">
                                            {data?.action_plan?.bearish_if || ("IF " + modeMeta.triggerCloseLabel + " below " + fmtMoney(A) + " → treat as corrective extension risk; do NOT label impulse.")}
                                        </div>
                                    </div>
                                    
                                    {A2 ? (
                                        <div className="rounded-xl border border-white/10 bg-white/5 p-3">
                                            <div className="text-[11px] font-semibold tracking-widest text-white/60">REGIME FAILURE IF</div>
                                            <div className="mt-1 text-sm text-white/80">
                                                {data?.action_plan?.regime_fail_if || ("IF Weekly close below " + fmtMoney(A2) + " → Intermediate regime failure; deeper alternate promoted.")}
                                            </div>
                                        </div>
                                    ) : null}
                                </div>
                            </Panel>
                        </div>
                        
                        {/* Cards row */}
                        <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
                            <Panel title="WEINSTEIN STAGE (CONTEXT ONLY)" icon="📈">
                                <div className="flex items-center justify-between">
                                    <div className="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm font-semibold text-white/85">
                                        {data?.weinstein?.stage || "—"}
                                    </div>
                                    <div className="text-xs text-white/50">Not used for wave labels</div>
                                </div>
                                <div className="mt-3 space-y-2 text-sm text-white/75">
                                    <div className="flex items-center justify-between">
                                        <span className="text-white/55">30w SMA slope</span>
                                        <span className="font-mono">{data?.weinstein?.sma_slope || "—"}</span>
                                    </div>
                                    <div className="flex items-center justify-between">
                                        <span className="text-white/55">Price vs 30w SMA</span>
                                        <span className="font-mono">{data?.weinstein?.price_vs_sma || "—"}</span>
                                    </div>
                                    <div className="text-xs text-white/50">{data?.weinstein?.notes || ""}</div>
                                </div>
                            </Panel>
                            
                            <Panel title="ELLIOTT (EXECUTION DEGREE)" icon="〰️">
                                <div className="flex items-center justify-between">
                                    <div className="text-sm font-semibold text-white/85">{data?.elliott?.structure || "—"}</div>
                                    <div className="rounded-xl border border-white/10 bg-white/5 px-3 py-1 text-xs font-semibold tracking-widest text-white/60">
                                        {modeMeta.degree.toUpperCase()} • {modeMeta.tf.toUpperCase()}
                                    </div>
                                </div>
                                <div className="mt-3 space-y-2 text-sm text-white/75">
                                    <div><span className="text-white/55">Degree:</span> <span className="font-mono">{modeMeta.execDegreeLabel}</span></div>
                                    <div><span className="text-white/55">Primary:</span> {data?.elliott?.primary || "Developing"}</div>
                                    <div><span className="text-white/55">Alternate:</span> {data?.elliott?.alternate || "Conditional"}</div>
                                </div>
                            </Panel>
                            
                            <Panel title="MOMENTUM & CONTEXT" icon="⚡">
                                <div className="text-sm text-white/85">
                                    AO: <span className="font-mono">{data?.ao?.state || "—"}</span>
                                </div>
                                <div className="mt-2 text-xs text-white/60">
                                    {data?.ao?.notes || "AO supports/warns but does NOT confirm structural completion."}
                                </div>
                                {/* FIBONACCI HARD GATE: Only render if zones is not null */}
                                {data?.fib?.zones && (
                                    <div className="mt-4 rounded-xl border border-white/10 bg-white/5 p-3">
                                        <div className="text-[11px] font-semibold tracking-widest text-white/60">FIB CONTEXT (ZONES)</div>
                                        <div className="mt-1 text-xs text-white/80">{data.fib.zones}</div>
                                        <div className="mt-1 text-[10px] text-white/45">{data?.fib?.notes || "Fibonacci is context only (zones, not signals)."}</div>
                                    </div>
                                )}
                            </Panel>
                        </div>
                        
                        {/* MACD MOMENTUM DIAGNOSTIC (v7.1 COMPLIANT - BI-DIRECTIONAL) */}
                        {data?.macdChunks && (data.macdChunks.bullish || data.macdChunks.bearish) && (
                            <div className="mt-4 rounded-2xl border border-slate-700/50 bg-gradient-to-b from-slate-800/70 to-slate-900/70 p-5 shadow-sm">
                                <div className="flex items-center justify-between mb-4">
                                    <div className="flex items-center gap-2">
                                        <span className="text-[11px] font-semibold tracking-widest text-slate-300/80">MACD MOMENTUM DIAGNOSTIC</span>
                                        <span className="px-2 py-0.5 rounded-full bg-slate-700/60 text-[9px] text-slate-400 tracking-wider">HEURISTIC</span>
                                    </div>
                                    <div className="flex gap-2">
                                        {data.macdChunks.bullish?.divergence && (
                                            <span className="bg-red-900/50 text-red-200 text-[10px] px-2 py-1 rounded-lg border border-red-700/50 font-medium">BEARISH DIV</span>
                                        )}
                                        {data.macdChunks.bearish?.divergence && (
                                            <span className="bg-cyan-900/50 text-cyan-200 text-[10px] px-2 py-1 rounded-lg border border-cyan-700/50 font-medium">BULLISH DIV</span>
                                        )}
                                    </div>
                                </div>
                                
                                {/* BULLISH IMPULSE SECTION (W3 → W4 → W5) */}
                                {data.macdChunks.bullish && (
                                    <div className="mb-4">
                                        <div className="text-[10px] text-green-400/80 font-semibold tracking-wider mb-2 flex items-center gap-2">
                                            <span className="h-1.5 w-1.5 rounded-full bg-green-400"></span>
                                            BULLISH IMPULSE (W3 → W4 → W5)
                                        </div>
                                        <div className="grid grid-cols-5 gap-2 text-center">
                                            <div className="p-2 bg-slate-900/50 rounded-xl border border-slate-700/30">
                                                <div className="text-[9px] text-slate-500 mb-1 uppercase">W3 Peak</div>
                                                <div className="text-green-400 font-mono text-xs font-semibold">{data.macdChunks.bullish.w3_peak?.toFixed(3)}</div>
                                            </div>
                                            <div className="p-2 bg-slate-900/50 rounded-xl border border-yellow-700/30">
                                                <div className="text-[9px] text-slate-500 mb-1 uppercase">W4 Corr</div>
                                                <div className="text-yellow-400 font-mono text-xs font-semibold">{data.macdChunks.bullish.w4_trough?.toFixed(3)}</div>
                                            </div>
                                            <div className="p-2 bg-slate-900/50 rounded-xl border border-slate-700/30">
                                                <div className="text-[9px] text-slate-500 mb-1 uppercase">W5 Peak</div>
                                                <div className="text-blue-400 font-mono text-xs font-semibold">{data.macdChunks.bullish.w5_peak?.toFixed(3)}</div>
                                            </div>
                                            <div className="p-2 bg-slate-900/50 rounded-xl border border-slate-700/30">
                                                <div className="text-[9px] text-slate-500 mb-1 uppercase">Ratio</div>
                                                <div className={cn("font-mono text-xs font-semibold", data.macdChunks.bullish.divergence ? "text-red-400" : "text-slate-300")}>
                                                    {data.macdChunks.bullish.div_ratio}x
                                                </div>
                                            </div>
                                            <div className="p-2 bg-slate-900/50 rounded-xl border border-slate-700/30">
                                                <div className="text-[9px] text-slate-500 mb-1 uppercase">Status</div>
                                                <div className={cn("text-xs font-semibold", data.macdChunks.bullish.divergence ? "text-red-400" : "text-slate-400")}>
                                                    {data.macdChunks.bullish.divergence ? "DIV" : "OK"}
                                                </div>
                                            </div>
                                        </div>
                                        {data.macdChunks.bullish.divergence && (
                                            <div className="mt-2 text-[10px] text-red-300/80 bg-red-900/20 p-2 rounded-lg border border-red-800/30">
                                                W5 Divergence: Price made NEW HIGH but MACD peak LOWER → Trend nearing end
                                            </div>
                                        )}
                                        {!data.macdChunks.bullish.divergence && data.macdChunks.bullish.price_new_high === false && (
                                            <div className="mt-2 text-[10px] text-slate-400/80 bg-slate-800/50 p-2 rounded-lg border border-slate-700/30">
                                                No divergence detected (W5 price did not exceed W3 price)
                                            </div>
                                        )}
                                    </div>
                                )}
                                
                                {/* BEARISH ZIGZAG SECTION (WA → WB → WC) */}
                                {data.macdChunks.bearish && (
                                    <div className="mb-3">
                                        <div className="text-[10px] text-orange-400/80 font-semibold tracking-wider mb-2 flex items-center gap-2">
                                            <span className="h-1.5 w-1.5 rounded-full bg-orange-400"></span>
                                            BEARISH SEQUENCE (WA → WB → WC)
                                        </div>
                                        <div className="grid grid-cols-5 gap-2 text-center">
                                            <div className="p-2 bg-slate-900/50 rounded-xl border border-slate-700/30">
                                                <div className="text-[9px] text-slate-500 mb-1 uppercase">WA Trough</div>
                                                <div className="text-orange-400 font-mono text-xs font-semibold">{data.macdChunks.bearish.wa_trough?.toFixed(3)}</div>
                                            </div>
                                            <div className="p-2 bg-slate-900/50 rounded-xl border border-yellow-700/30">
                                                <div className="text-[9px] text-slate-500 mb-1 uppercase">WB Corr</div>
                                                <div className="text-yellow-400 font-mono text-xs font-semibold">{data.macdChunks.bearish.wb_peak?.toFixed(3)}</div>
                                            </div>
                                            <div className="p-2 bg-slate-900/50 rounded-xl border border-slate-700/30">
                                                <div className="text-[9px] text-slate-500 mb-1 uppercase">WC Trough</div>
                                                <div className="text-slate-400 font-mono text-xs font-semibold">{data.macdChunks.bearish.wc_trough?.toFixed(3)}</div>
                                            </div>
                                            <div className="p-2 bg-slate-900/50 rounded-xl border border-slate-700/30">
                                                <div className="text-[9px] text-slate-500 mb-1 uppercase">Ratio</div>
                                                <div className={cn("font-mono text-xs font-semibold", data.macdChunks.bearish.divergence ? "text-cyan-400" : "text-slate-300")}>
                                                    {data.macdChunks.bearish.div_ratio}x
                                                </div>
                                            </div>
                                            <div className="p-2 bg-slate-900/50 rounded-xl border border-slate-700/30">
                                                <div className="text-[9px] text-slate-500 mb-1 uppercase">Status</div>
                                                <div className={cn("text-xs font-semibold", data.macdChunks.bearish.divergence ? "text-cyan-400" : "text-slate-400")}>
                                                    {data.macdChunks.bearish.divergence ? "DIV" : "OK"}
                                                </div>
                                            </div>
                                        </div>
                                        {data.macdChunks.bearish.divergence && (
                                            <div className="mt-2 text-[10px] text-cyan-300/80 bg-cyan-900/20 p-2 rounded-lg border border-cyan-800/30">
                                                Price made lower low but MACD momentum weaker → Bullish divergence (potential reversal)
                                            </div>
                                        )}
                                    </div>
                                )}
                                
                                <div className="text-[10px] text-slate-500 italic border-t border-slate-700/30 pt-2 mt-2">
                                    Diagnostic only — does not confirm Elliott structure and does not override A/B/A2 triggers.
                                </div>
                            </div>
                        )}
                        
                        {/* Final Risk-First Verdict + Closing Summary */}
                        <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
                            {data?.final_verdict && (
                                <div className="rounded-2xl border border-red-500/20 bg-gradient-to-b from-red-950/20 to-slate-950/70 p-5">
                                    <div className="flex items-center gap-2 mb-3">
                                        <div className="h-2 w-2 rounded-full bg-red-400 animate-pulse" />
                                        <div className="text-[11px] font-semibold tracking-widest text-red-300/80">FINAL RISK-FIRST VERDICT</div>
                                    </div>
                                    <FormatReportText text={data.final_verdict} accentColor="bg-red-400" />
                                </div>
                            )}
                            {data?.closing_summary && (
                                <div className="rounded-2xl border border-cyan-500/20 bg-gradient-to-b from-cyan-950/20 to-slate-950/70 p-5">
                                    <div className="flex items-center gap-2 mb-3">
                                        <div className="h-2 w-2 rounded-full bg-cyan-400" />
                                        <div className="text-[11px] font-semibold tracking-widest text-cyan-300/80">CLOSING SUMMARY</div>
                                    </div>
                                    <FormatReportText text={data.closing_summary} accentColor="bg-cyan-400" />
                                </div>
                            )}
                        </div>
                        
                        {/* Validator Checks */}
                        <div className="mt-4 rounded-2xl border border-white/10 bg-gradient-to-b from-slate-900/70 to-slate-950/70 p-5">
                            <div className="text-[11px] font-semibold tracking-widest text-white/50 mb-3">v7.1 COMPLIANCE CHECKS</div>
                            <div className="flex flex-wrap gap-3">
                                {checks.map((c, i) => (
                                    <div key={i} className={cn(
                                        "px-3 py-1.5 rounded-xl border text-xs font-medium",
                                        c.ok ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200" : "border-red-500/30 bg-red-500/10 text-red-200"
                                    )}>
                                        {c.ok ? "✓" : "✗"} {c.k}
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>
                    
                    <Modal open={open} onClose={() => setOpen(false)} title="Full v7.1 Report">
                        {data.report_text || "Full report text not available."}
                    </Modal>
                </div>
            );
        }
        
        const container = document.getElementById('react-root');
        const root = ReactDOM.createRoot(container);
        root.render(<TradingViewProDashboard />);
    </script>
</body>
</html>'''
    
    return html_template


def parse_analysis_for_dashboard(ai_analysis: str, ticker: str, current_price: float, level_A: float, level_B: float, timeframe: str = "Daily") -> dict:
    """
    Parse AI analysis text and extract structured data for TradingView Pro dashboard.
    Returns a dictionary matching the new v7.1 data contract.
    
    CANONICAL DEGREE MAP (Weekly is NEVER execution authority):
      - Weekly → Intermediate (Regime context + A2 ONLY)
      - Daily → Minor (Execution if Daily selected)
      - 4H → Minuette (Execution if 4H selected)
      - 60m → Minute (Entry timing only)
    """
    
    # Determine trigger state
    if current_price < level_A:
        trigger_state = "BEARISH"
    elif current_price > level_B:
        trigger_state = "BULLISH"
    else:
        trigger_state = "NONE"
    
    # Extract A2 (Intermediate regime failure level)
    # A2 MUST be a valid Weekly pivot — reject invalid placeholders like $30.00
    a2_match = re.search(r'A2.*?[\$]?([\d,]+\.?\d*)', ai_analysis, re.IGNORECASE)
    a2_value = None
    if a2_match:
        raw_a2 = float(a2_match.group(1).replace(',', ''))
        # VALIDATION: A2 must be at least 20% of level_A to be considered valid
        # This prevents placeholder values like $30.00 from being used
        min_valid_a2 = level_A * 0.2 if level_A and level_A > 0 else 50.0
        if raw_a2 >= min_valid_a2 and raw_a2 < level_A:
            a2_value = raw_a2
        # If A2 is invalid (too low or above A), it remains None
    
    # Extract probabilities
    primary_match = re.search(r'Primary.*?(\d+)%', ai_analysis, re.IGNORECASE)
    alt_match = re.search(r'Alternate.*?(\d+)%', ai_analysis, re.IGNORECASE)
    primary_prob = int(primary_match.group(1)) if primary_match else 65
    alt_prob = int(alt_match.group(1)) if alt_match else 35
    
    # WEINSTEIN GATE FIX: If weekly 30w SMA is not explicitly visible, output UNCONFIRMED
    # Extract SMA info FIRST to determine if Weinstein Stage can be confirmed
    sma_match = re.search(r'30.?(?:week|w).*?SMA.*?[\$]?([\d,]+\.?\d*)', ai_analysis, re.IGNORECASE)
    sma_value = sma_match.group(1).replace(',', '') if sma_match else None
    sma_visible = sma_match is not None
    
    if "above" in ai_analysis.lower() and "sma" in ai_analysis.lower():
        price_vs_sma = "Above"
        sma_slope = "Rising" if "rising" in ai_analysis.lower() or "bullish" in ai_analysis.lower() else "Neutral"
    elif "below" in ai_analysis.lower() and "sma" in ai_analysis.lower():
        price_vs_sma = "Below"
        sma_slope = "Declining" if "declining" in ai_analysis.lower() or "bearish" in ai_analysis.lower() else "Neutral"
    else:
        price_vs_sma = "NOT PROVIDED"
        sma_slope = "NOT PROVIDED"
    
    # Extract Weinstein Stage with GATE FIX
    # If SMA is NOT visible/provided → "UNCONFIRMED (SMA not visible)"
    stage_match = re.search(r'Stage\s*[:\s]*(\d)', ai_analysis, re.IGNORECASE)
    stage_num = stage_match.group(1) if stage_match else None
    stage_names = {"1": "Accumulation", "2": "Advancing", "3": "Distribution", "4": "Declining"}
    
    if not sma_visible or sma_value is None:
        # GATE FIX: SMA not visible → UNCONFIRMED
        weinstein_stage = "UNCONFIRMED (SMA not visible)"
        weinstein_confirmed = False
    elif stage_num:
        weinstein_stage = f"Stage {stage_num} ({stage_names.get(stage_num, 'Advancing')})"
        weinstein_confirmed = True
    else:
        weinstein_stage = "UNCONFIRMED (stage not stated)"
        weinstein_confirmed = False
    
    # Extract Elliott structure
    if "impulse" in ai_analysis.lower() and "developing" not in ai_analysis.lower():
        elliott_structure = "Impulse (Developing)"
    elif "correction" in ai_analysis.lower() or "corrective" in ai_analysis.lower():
        elliott_structure = "Corrective (Developing)"
    else:
        elliott_structure = "Structure Developing"
    
    # v7.1 CRITICAL: Determine execution_mode
    # CANONICAL DEGREE MAP (Weekly is NEVER execution authority):
    # - Weekly = Intermediate (Regime context + A2 ONLY)
    # - Daily = Minor (Execution if user chooses Daily)
    # - 4H = Minuette (Execution if user chooses 4H)
    # - 60m = Minute (Entry timing only)
    timeframe_lower = timeframe.lower() if timeframe else "daily"
    
    if timeframe_lower in ["4h", "4-hour", "4 hour", "h4"]:
        execution_mode = "H4_MINUETTE"
        elliott_degree = "Minuette (4H)"
        execution_authority_label = "4H (MINUETTE)"
    else:
        # Default: Daily → Minor (Weekly is regime context only)
        # Even if user selects Weekly, execution authority defaults to Daily
        execution_mode = "DAILY_MINOR"
        elliott_degree = "Minor (Daily)"
        execution_authority_label = "DAILY (MINOR)"
    
    # NOTE: Weekly is regime context only; lower timeframes are diagnostics
    
    # DEVELOPING GATE: If trigger_state is NONE (range/developing), forbid "confirmed" phrases
    # RULE: When structure is overlapping/unclear, default Primary = "Corrective (developing), W-X-Y preferred"
    # Alternate must NOT use ABC language unless 5-wave C leg is explicitly detected on execution timeframe
    is_overlapping = "corrective" in elliott_structure.lower() or "developing" in elliott_structure.lower()
    is_developing_state = trigger_state == "NONE"  # No trigger hit = range / developing
    
    # STRICT: Only allow 5-wave C if NOT in developing state
    has_5wave_c = False
    if not is_developing_state:
        has_5wave_c = any(phrase in ai_analysis.lower() for phrase in [
            "5-wave c", "five-wave c", "5 wave c", "c-leg is 5-wave", 
            "c subdivides into 5", "c-leg subdivides into 5", "impulsive c"
        ])
    
    # DEVELOPING GATE: If developing state, force W-X-Y preferred and forbid confirmed language
    if is_developing_state or (is_overlapping and not has_5wave_c):
        # DEFAULT when developing: W-X-Y preferred, no ABC, no "confirmed" language
        elliott_primary = "Corrective (Developing) — W-X-Y preferred unless 5-wave proof exists on execution timeframe."
        elliott_alternate = "Complex correction promoted only on regime failure (A2)."
    elif "wave-4" in ai_analysis.lower() or "wave 4" in ai_analysis.lower():
        elliott_primary = "Wave-4 correction developing; structure-first analysis."
        elliott_alternate = "Wave-4 failure / truncation promoted on regime break (A2)."
    elif has_5wave_c:
        # Only allow ABC if 5-wave C is confirmed AND not in developing state
        elliott_primary = "ABC correction developing (5-wave C-leg confirmed). Structure-first."
        elliott_alternate = "W-X-Y promoted if C-leg subdivides into 3 waves."
    else:
        elliott_primary = "Corrective (Developing) — W-X-Y preferred unless 5-wave proof exists on execution timeframe."
        elliott_alternate = "Complex correction promoted only on regime failure (A2)."
    
    # Extract AO state
    if "bullish" in ai_analysis.lower() and "momentum" in ai_analysis.lower():
        ao_state = "Bullish / Expanding"
    elif "bearish" in ai_analysis.lower() and "momentum" in ai_analysis.lower():
        ao_state = "Bearish / Contracting"
    elif "reset" in ai_analysis.lower() or "neutral" in ai_analysis.lower():
        ao_state = "Resetting / Neutral"
    else:
        ao_state = "NOT PROVIDED"
    
    # FIBONACCI HARD GATE (PF7 STRICT ENFORCEMENT)
    # If anchors are missing → fib_zones = None (section MUST be skipped entirely, NOT rendered)
    # If fib printed → must include "Anchors: from <price/time> to <price/time>"
    fib_zones = None  # HARD GATE: Default to None (skip section)
    fib_compliant = False
    
    # Try to extract fib anchor information from AI analysis
    fib_anchor_match = re.search(r'(?:anchor|from|measured from)[:\s]*\$?([\d,]+\.?\d*).*?(?:to|through|→)\s*\$?([\d,]+\.?\d*)', ai_analysis, re.IGNORECASE)
    fib_100 = re.search(r'100%.*?[\$]?([\d,]+\.?\d*)', ai_analysis)
    fib_161 = re.search(r'161\.?8?%.*?[\$]?([\d,]+\.?\d*)', ai_analysis)
    
    if fib_anchor_match and (fib_100 or fib_161):
        # Anchors are explicit — compliant, render fib section
        anchor_low = fib_anchor_match.group(1).replace(',', '')
        anchor_high = fib_anchor_match.group(2).replace(',', '')
        zones = [f"Anchors: ${anchor_low} → ${anchor_high}"]
        if fib_100:
            zones.append(f"100% @ ${fib_100.group(1).replace(',', '')}")
        if fib_161:
            zones.append(f"161.8% @ ${fib_161.group(1).replace(',', '')}")
        fib_zones = " | ".join(zones)
        fib_compliant = True
    # NOTE: If no fib_anchor_match OR no fib_100/fib_161, fib_zones stays None
    # The renderer MUST skip the fib section entirely (no "N/A", no disclaimer)
    
    # Extract verdict
    verdict_match = re.search(r'(?:VERDICT|FINAL|CONCLUSION).*?[:]\s*(.+?)(?:\n\n|\Z)', ai_analysis, re.IGNORECASE | re.DOTALL)
    verdict_sentence = verdict_match.group(1).strip()[:400] if verdict_match else "See full report for complete analysis."
    
    verdict_headline = "Analysis Complete"
    if trigger_state == "BEARISH":
        verdict_headline = "❌ Bearish Activation — Corrective Extension Risk"
    elif trigger_state == "BULLISH":
        verdict_headline = "✅ Bullish Continuation — Correction Terminated"
    else:
        verdict_headline = "⏸️ No Trigger — Range / Developing"
    
    # Extract FINAL RISK-FIRST VERDICT section from AI analysis (multiple patterns)
    final_verdict = None
    final_verdict_patterns = [
        r'(?:FINAL\s+)?RISK[- ]FIRST\s+VERDICT[:\s]*\n?(.+?)(?=\n\s*(?:CLOSING|SUMMARY|$|\n\n[A-Z]))',
        r'VERDICT[:\s]*\n?(.+?)(?=\n\n|\Z)',
        r'FINAL\s+(?:ANALYSIS|ASSESSMENT)[:\s]*\n?(.+?)(?=\n\n|\Z)',
        r'0️⃣\s*RISK[- ]FIRST[:\s]*\n?(.+?)(?=\n\n|\n1️⃣|\Z)',
    ]
    for pattern in final_verdict_patterns:
        match = re.search(pattern, ai_analysis, re.IGNORECASE | re.DOTALL)
        if match and len(match.group(1).strip()) > 20:
            final_verdict = match.group(1).strip()[:600]
            break
    
    # Fallback: generate from trigger state if no match or too short
    if not final_verdict or len(final_verdict) < 20:
        if trigger_state == "BEARISH":
            final_verdict = f"Bearish activation is live. Price closed below A (${level_A:.2f}). Treat as corrective extension risk at {execution_authority_label} degree. Do NOT label impulse while below B."
                elif trigger_state == "BULLISH":
            # v16.17 MTF FIX
            m_st = "WEAK" if ("Monthly" in ai_analysis and "WEAK" in ai_analysis) else "STRONG"
            w_st = "WEAK" if ("Weekly" in ai_analysis and "WEAK" in ai_analysis) else "STRONG"
            d_st = "WEAK" if ("Daily" in ai_analysis and "WEAK" in ai_analysis) else "STRONG"
            h4_st = "WEAK" if ("4H" in ai_analysis and "WEAK" in ai_analysis) else "STRONG"
            mtf_ok, mtf_msg = check_mtf_verdict_alignment(m_st, w_st, d_st, h4_st)
            if mtf_ok:
                final_verdict = f"Enter long - All timeframes aligned. Price closed above B (${level_B:.2f}). Correction may be complete at {execution_authority_label} degree."
            else:
                final_verdict = f"STAY OUT - Price above B (${level_B:.2f}) but MTF misaligned ({mtf_msg}). Wait for alignment."

        else:
            final_verdict = f"No trigger resolved. Price between A (${level_A:.2f}) and B (${level_B:.2f}). Stand aside until trigger resolution at {execution_authority_label} degree."
    
    # Extract CLOSING SUMMARY section from AI analysis (multiple patterns)
    closing_summary = None
    closing_summary_patterns = [
        r'CLOSING\s+SUMMARY[:\s]*\n?(.+?)(?=\n\n[A-Z]|\Z)',
        r'(?:IN\s+)?SUMMARY[:\s]*\n?(.+?)(?=\n\n|\Z)',
        r'CONCLUSION[:\s]*\n?(.+?)(?=\n\n|\Z)',
        r'8️⃣\s*(?:CLOSING|SUMMARY)[:\s]*\n?(.+?)(?=\n\n|\Z)',
    ]
    for pattern in closing_summary_patterns:
        match = re.search(pattern, ai_analysis, re.IGNORECASE | re.DOTALL)
        if match and len(match.group(1).strip()) > 50:
            closing_summary = match.group(1).strip()[:600]
            break
    
    # Fallback: generate detailed closing summary from key analysis points
    if not closing_summary or len(closing_summary) < 50:
        summary_parts = []
        summary_parts.append(f"**Execution authority:** {execution_authority_label}")
        summary_parts.append(f"**Weinstein Stage:** {weinstein_stage}")
        summary_parts.append(f"**Elliott Structure:** {elliott_structure}")
        summary_parts.append(f"**Momentum (AO):** {ao_state}")
        if trigger_state == "BEARISH":
            summary_parts.append(f"**Trigger Status:** Bearish activation below ${level_A:.2f}")
        elif trigger_state == "BULLISH":
            summary_parts.append(f"**Trigger Status:** Bullish continuation above ${level_B:.2f}")
        else:
            summary_parts.append(f"**Trigger Status:** No trigger — price between ${level_A:.2f} and ${level_B:.2f}")
        if a2_value:
            summary_parts.append(f"**Regime Failure Level:** Weekly close below ${a2_value:.2f}")
        closing_summary = " - ".join(summary_parts)
    
    # Build observations - extract from AI analysis or use smart defaults
    observations = []
    
    # Try to extract observation-like sentences from the analysis
    obs_patterns = [
        r'(?:Note|Important|Key|Observation|Warning|Reminder)[:\s]+([^\.]+\.)',
        r'(?:Must|Should|Cannot|Never)[^\.]+\.',
    ]
    
    for pattern in obs_patterns:
        matches = re.findall(pattern, ai_analysis, re.IGNORECASE)
        for m in matches[:2]:  # Limit per pattern
            clean = m.strip()
            if len(clean) > 20 and len(clean) < 200 and clean not in observations:
                observations.append(clean)
    
    # Add contextual observations based on extracted data (using MODE-AWARE execution authority)
    # Execution authority can ONLY be Daily (Intermediate) or 4H (Minor) — NEVER Weekly
    observations.append(f"Execution Authority: {execution_authority_label}. Weekly is regime context only.")
    
    if trigger_state == "BEARISH":
        observations.append(f"Price closed below A (${level_A:.2f}) — bearish activation is live.")
    elif trigger_state == "BULLISH":
        observations.append(f"Price closed above B (${level_B:.2f}) — bullish continuation permitted.")
    else:
        observations.append(f"Price is between A (${level_A:.2f}) and B (${level_B:.2f}) — no trade until trigger resolution.")
    
    if "overlapping" in ai_analysis.lower():
        observations.append("Structure is overlapping → default corrective; avoid ABC unless final leg is a clear 5-wave.")
    else:
        observations.append("Structure-first governs labels; W-X-Y default unless impulse is confirmed.")
    
    observations.append("AO is momentum-only: it may support/warn, but never confirms structural completion.")
    
    if a2_value and a2_value > 0:
        observations.append(f"A2 (${a2_value:.2f}) = Intermediate regime failure level — use 'invalidation' language only here.")
    else:
        observations.append("A2 (Regime Fail): NOT PROVIDED / NOT VISIBLE")
    
    # Limit to 7 observations max
    observations = observations[:7]
    
    # Validator checks - try to validate from analysis content (ensure Python bools)
    validator = {
        "degreeLocked": bool("degree" in ai_analysis.lower() and ("minor" in ai_analysis.lower() or "intermediate" in ai_analysis.lower())),
        "labelConsistent": bool(not ("wave-5" in ai_analysis.lower() and "developing" in ai_analysis.lower() and "confirmed" not in ai_analysis.lower())),
        "fibAnchored": fib_compliant,  # PF7 STRICT: Only True if anchors are explicit
        "aoConfirmOnly": bool(
            # FAIL only if AO is explicitly confirming structural completion (not allowed)
            # PASS if AO is used for support/momentum only, or "cannot confirm" language
            not any(phrase in ai_analysis.lower() for phrase in [
                "ao confirms wave",
                "ao confirms the wave",
                "ao confirms completion",
                "ao confirms structural",
                "ao has confirmed wave",
                "ao has confirmed the wave",
                "oscillator confirms wave",
                "oscillator confirms completion",
                "ao confirms the end",
                "ao confirms the bottom",
                "ao confirms the top",
            ])
        ),
        "triggersCoherent": bool(level_A is not None and level_B is not None and float(level_A) < float(level_B))
    }
    
    # Ensure all numeric values are JSON-serializable Python types
    close_val = float(current_price) if current_price is not None else 0.0
    a_val = float(level_A) if level_A is not None else 0.0
    b_val = float(level_B) if level_B is not None else 0.0
    a2_val = float(a2_value) if a2_value is not None else None
    
    # execution_mode: DAILY_MINOR or H4_MINUETTE (CANONICAL DEGREE MAP)
    # Weekly is NEVER execution authority — it is regime context only
    # DEGREE_MAP = {"W": "Intermediate", "D": "Minor", "4H": "Minuette", "60m": "Minute"}
    
    # CANONICAL DEGREE MAP labels (Weekly CANNOT be execution authority)
    if execution_mode == "H4_MINUETTE" or "H4" in (execution_mode or "").upper():
        tf_label = "4H"
        exec_auth_label = "4H (MINUETTE)"
        trigger_close = "4H close"
    else:
        # DAILY_MINOR is default
        tf_label = "Daily"
        exec_auth_label = "DAILY (MINOR)"
        trigger_close = "Daily close"
    
    # ========================================================
    # v7.1 NARRATIVE HYGIENE GOVERNOR (MANDATORY FINAL PASS)
    # ========================================================
    
    # 1. FIB NUMERIC SANITY CHECK — validate before rendering
    fib_anchor_low = None
    fib_anchor_high = None
    if fib_anchor_match:
        try:
            fib_anchor_low = float(fib_anchor_match.group(1).replace(',', ''))
            fib_anchor_high = float(fib_anchor_match.group(2).replace(',', ''))
        except (ValueError, TypeError):
            pass
    fib_zones = validate_fib_numeric_sanity(fib_anchor_low, fib_anchor_high, fib_zones)
    
    # 2. Apply narrative hygiene to final_verdict
    if final_verdict:
        final_verdict = enforce_v71_narrative_hygiene(final_verdict, elliott_structure, weinstein_stage)
        final_verdict = enforce_verdict_consistency(final_verdict, elliott_structure, trigger_state)
    
    # 3. Apply narrative hygiene to closing_summary
    if closing_summary:
        closing_summary = enforce_v71_narrative_hygiene(closing_summary, elliott_structure, weinstein_stage)
    
    # 4. Apply narrative hygiene to elliott_primary/alternate
    elliott_primary = enforce_v71_narrative_hygiene(elliott_primary, elliott_structure, weinstein_stage)
    elliott_alternate = enforce_v71_narrative_hygiene(elliott_alternate, elliott_structure, weinstein_stage)
    
    # 5. WEINSTEIN ELIGIBILITY GATE — if unconfirmed, set note
    weinstein_note = f"30w SMA @ ${sma_value}" if sma_value else "Weekly context only."
    if "unconfirmed" in weinstein_stage.lower():
        weinstein_note = "Trend eligibility unconfirmed from provided evidence."
    
    return {
        "ticker": str(ticker),
        "timeframe_label": tf_label,
        "execution_authority": exec_auth_label,
        "execution_mode": execution_mode,  # Critical for MODE_META lookup in JS
        "close": close_val,
        "trigger_state": str(trigger_state),
        "triggers": {
            "A": a_val,
            "B": b_val,
            "A2": a2_val,
            "A_label": "Bearish Activation",
            "B_label": "Bullish Continuation",
            "A2_label": "Intermediate Regime Failure (Weekly close only)"
        },
        "probabilities": {
            "primary": int(primary_prob),
            "alternate": int(alt_prob),
            "primary_label": "Primary Scenario",
            "alternate_label": "Alternate Scenario"
        },
        "weinstein": {
            "stage": weinstein_stage,
            "sma_slope": sma_slope,
            "price_vs_sma": price_vs_sma,
            "notes": weinstein_note
        },
        "elliott": {
            "degree": elliott_degree,
            "structure": elliott_structure,
            "primary": elliott_primary,
            "alternate": elliott_alternate,
            "notes": "Structure-first governs labels."
        },
        "ao": {
            "state": ao_state,
            "notes": "AO supports momentum alignment but does NOT confirm structural completion."
        },
        "fib": {
            "anchors": "Anchors derived from structural pivots.",
            "zones": fib_zones,
            "notes": "Fibonacci is context only (zones, not signals)."
        },
        "verdict": {
            "headline": verdict_headline,
            "sentence": verdict_sentence
        },
        "action_plan": {
            "now": "Stand aside. Bearish activation is live." if trigger_state == "BEARISH" else "Bullish continuation permitted." if trigger_state == "BULLISH" else "No trade. Wait for trigger resolution.",
            "bullish_if": f"IF {trigger_close} above B (${level_B:.2f}) → bullish continuation permitted at {elliott_degree} degree.",
            "bearish_if": f"IF {trigger_close} below A (${level_A:.2f}) → treat as corrective extension risk; do NOT label impulse.",
            "regime_fail_if": f"IF Weekly close below A2 (${a2_value:.2f}) → Intermediate regime failure; deeper alternate promoted." if a2_value and a2_value > 0 else "A2: NOT PROVIDED / NOT VISIBLE",
            "invalidation_language": "Use 'extends' for A breaks; use 'invalidation' only for A2 (Weekly)."
        },
        "observations": observations,
        "final_verdict": final_verdict,
        "closing_summary": closing_summary,
        "report_text": ai_analysis,
        "validator": validator
    }
