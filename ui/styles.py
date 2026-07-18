# ui/styles.py
# Design system — Linear.app spec (DESIGN.md)
# Canvas: #010102  Surface-1: #0f1011  Surface-2: #141516  Surface-3: #18191a
# Accent: #5e6ad2 (lavender-blue, scarce)
# Font: Inter (Google Fonts) / JetBrains Mono
# Rules:
#   - Dark theme only. No light mode.
#   - Lavender ONLY for: active tabs, primary button, focus ring.
#   - Semantic risk/severity colours are product data — preserved.
#   - inject_styles() called once at top of app.py only.
#   - No inline styles in ui/*.py — use CSS classes only.

from __future__ import annotations

import streamlit as st

CUSTOM_CSS = """
<style>

/* ── Fonts ─────────────────────────────────────────────────── */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

:root {
    /* ── Linear colour tokens ─────────────────────────────── */
    --canvas:            #010102;
    --surface-1:         #0f1011;
    --surface-2:         #141516;
    --surface-3:         #18191a;
    --surface-4:         #191a1b;
    --hairline:          #23252a;
    --hairline-strong:   #34343a;
    --hairline-tertiary: #3e3e44;
    --ink:               #f7f8f8;
    --ink-muted:         #d0d6e0;
    --ink-subtle:        #8a8f98;
    --ink-tertiary:      #62666d;
    --primary:           #5e6ad2;
    --primary-hover:     #828fff;
    --primary-focus:     #5e6ad2;

    /* ── Semantic (product data — not marketing chrome) ────── */
    --color-critical: #EF4444;
    --color-high:     #F97316;
    --color-moderate: #FBBF24;
    --color-low:      #22C55E;
    --color-info:     #38BDF8;
    --color-purple:   #A855F7;

    /* ── Typography ───────────────────────────────────────── */
    --font-display: 'Inter', 'SF Pro Display', -apple-system, system-ui, Segoe UI, Roboto, sans-serif;
    --font-body:    'Inter', -apple-system, system-ui, Segoe UI, Roboto, sans-serif;
    --font-mono:    'JetBrains Mono', 'SF Mono', ui-monospace, Menlo, monospace;

    /* ── Border radius ────────────────────────────────────── */
    --r-xs:   4px;
    --r-sm:   6px;
    --r-md:   8px;
    --r-lg:   12px;
    --r-xl:   16px;
    --r-pill: 9999px;

    /* ── Spacing ──────────────────────────────────────────── */
    --sp-xxs: 4px;
    --sp-xs:  8px;
    --sp-sm:  12px;
    --sp-md:  16px;
    --sp-lg:  24px;
    --sp-xl:  32px;
    --sp-xxl: 48px;
}

/* ── Base ───────────────────────────────────────────────────── */
html, body, .stApp {
    background-color: var(--canvas) !important;
    color: var(--ink) !important;
    font-family: var(--font-body) !important;
    font-size: 16px;
    font-weight: 400;
    line-height: 1.50;
    letter-spacing: -0.05px;
}

/* ── Sidebar ────────────────────────────────────────────────── */
section[data-testid="stSidebar"] {
    background-color: var(--surface-1) !important;
    border-right: 1px solid var(--hairline) !important;
}

section[data-testid="stSidebar"] * {
    color: var(--ink-muted) !important;
}

section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 {
    color: var(--ink) !important;
    font-weight: 600;
    letter-spacing: -0.4px;
}

/* ── Headings ───────────────────────────────────────────────── */
h1, h2, h3, h4 {
    font-family: var(--font-display) !important;
    color: var(--ink) !important;
}
h1 { font-size: 40px; font-weight: 600; letter-spacing: -1.0px; line-height: 1.15; }
h2 { font-size: 28px; font-weight: 600; letter-spacing: -0.6px; line-height: 1.20; }
h3 { font-size: 22px; font-weight: 500; letter-spacing: -0.4px; line-height: 1.25; }
h4 { font-size: 20px; font-weight: 400; letter-spacing: -0.2px; line-height: 1.40; }

p, li { color: var(--ink-muted); }

/* ── Metric cards ───────────────────────────────────────────── */
div[data-testid="metric-container"] {
    background-color: var(--surface-1) !important;
    border: 1px solid var(--hairline) !important;
    border-radius: var(--r-lg) !important;
    padding: var(--sp-md) var(--sp-lg) !important;
}

div[data-testid="metric-container"] label {
    color: var(--ink-subtle) !important;
    font-size: 12px !important;
    font-weight: 500 !important;
    letter-spacing: 0.4px !important;
    text-transform: uppercase !important;
}

div[data-testid="metric-container"] div[data-testid="stMetricValue"] {
    color: var(--ink) !important;
    font-size: 28px !important;
    font-weight: 600 !important;
    letter-spacing: -0.6px !important;
}

div[data-testid="metric-container"] div[data-testid="stMetricDelta"] {
    font-size: 12px !important;
}

/* ── Buttons ────────────────────────────────────────────────── */
.stButton > button {
    background-color: var(--surface-1) !important;
    color: var(--ink) !important;
    border: 1px solid var(--hairline) !important;
    border-radius: var(--r-md) !important;
    font-family: var(--font-body) !important;
    font-size: 14px !important;
    font-weight: 500 !important;
    padding: 8px 14px !important;
    transition: background-color 0.15s ease, border-color 0.15s ease !important;
}

.stButton > button:hover {
    background-color: var(--surface-2) !important;
    border-color: var(--hairline-strong) !important;
}

.stButton > button[kind="primary"] {
    background-color: var(--primary) !important;
    color: #ffffff !important;
    border-color: var(--primary) !important;
}

.stButton > button[kind="primary"]:hover {
    background-color: var(--primary-hover) !important;
    border-color: var(--primary-hover) !important;
}

/* ── Selectbox / inputs ─────────────────────────────────────── */
.stSelectbox > div > div,
.stTextInput > div > div > input,
.stTextArea > div > div > textarea {
    background-color: var(--surface-1) !important;
    color: var(--ink) !important;
    border: 1px solid var(--hairline) !important;
    border-radius: var(--r-md) !important;
    font-family: var(--font-body) !important;
    padding: 8px 12px !important;
}

.stSelectbox > div > div:focus-within,
.stTextInput > div > div > input:focus,
.stTextArea > div > div > textarea:focus {
    border-color: var(--primary-focus) !important;
    box-shadow: 0 0 0 2px rgba(94, 106, 210, 0.30) !important;
    outline: none !important;
}

/* ── Expanders ──────────────────────────────────────────────── */
details[data-testid="stExpander"] {
    background-color: var(--surface-1) !important;
    border: 1px solid var(--hairline) !important;
    border-radius: var(--r-lg) !important;
    padding: 0 !important;
    margin: var(--sp-xs) 0 !important;
}

details[data-testid="stExpander"] summary {
    color: var(--ink) !important;
    font-weight: 500 !important;
    font-size: 14px !important;
    padding: var(--sp-sm) var(--sp-md) !important;
    border-radius: var(--r-lg) !important;
}

details[data-testid="stExpander"] summary:hover {
    background-color: var(--surface-2) !important;
}

details[data-testid="stExpander"][open] summary {
    border-bottom: 1px solid var(--hairline) !important;
    border-radius: var(--r-lg) var(--r-lg) 0 0 !important;
}

/* ── Tab styling ────────────────────────────────────────────── */
button[data-baseweb="tab"] {
    color: var(--ink-subtle) !important;
    font-family: var(--font-body) !important;
    font-size: 14px !important;
    font-weight: 500 !important;
    background-color: transparent !important;
    border-bottom: 2px solid transparent !important;
    transition: color 0.15s ease, border-color 0.15s ease !important;
}

button[data-baseweb="tab"]:hover {
    color: var(--ink-muted) !important;
}

button[data-baseweb="tab"][aria-selected="true"] {
    color: var(--ink) !important;
    border-bottom-color: var(--primary) !important;
}

div[data-testid="stTabs"] [data-baseweb="tab-list"] {
    border-bottom: 1px solid var(--hairline) !important;
    gap: 0 !important;
}

/* ── Divider ────────────────────────────────────────────────── */
hr {
    border: none !important;
    border-top: 1px solid var(--hairline) !important;
    margin: var(--sp-lg) 0 !important;
}

/* ── Spinner / progress ─────────────────────────────────────── */
div[data-testid="stStatusWidget"] {
    background-color: var(--surface-1) !important;
    border: 1px solid var(--hairline) !important;
    border-radius: var(--r-md) !important;
}

/* ── Info / warning / success Streamlit alerts ──────────────── */
div[data-testid="stAlert"] {
    border-radius: var(--r-md) !important;
    border-width: 1px !important;
}

/* ── Caption / markdown small text ─────────────────────────── */
small, .stCaption, div[data-testid="stCaptionContainer"] {
    color: var(--ink-subtle) !important;
    font-size: 12px !important;
    letter-spacing: 0 !important;
}

/* ───────────────────────────────────────────────────────────── */
/*  PRODUCT-SPECIFIC CLASSES                                      */
/*  Semantic: tied to financial data severity, not marketing.     */
/* ───────────────────────────────────────────────────────────── */

/* ── Risk level badge ───────────────────────────────────────── */
.risk-badge {
    font-size: 2rem;
    font-weight: 700;
    letter-spacing: -0.05em;
    font-family: var(--font-display);
    padding: 8px 0;
    margin-bottom: 4px;
}

.risk-CRITICAL { color: var(--color-critical); }
.risk-HIGH     { color: var(--color-high); }
.risk-MODERATE { color: var(--color-moderate); }
.risk-LOW      { color: var(--color-low); }

/* ── Anomaly severity rows ──────────────────────────────────── */
.severity-row {
    padding: var(--sp-sm) var(--sp-md);
    border-radius: var(--r-sm);
    margin: var(--sp-xxs) 0;
    font-size: 14px;
    line-height: 1.50;
    color: var(--ink-muted);
}

.severity-ANOMALY {
    background: #1a0808;
    border-left: 3px solid var(--color-critical);
}

.severity-WATCH {
    background: #1a0e06;
    border-left: 3px solid var(--color-high);
}

.severity-NORMAL {
    background: #06120a;
    border-left: 3px solid var(--color-low);
}

/* ── Payment action rows ────────────────────────────────────── */
.payment-row {
    padding: var(--sp-sm) var(--sp-md);
    border-radius: var(--r-sm);
    margin: var(--sp-xxs) 0;
    font-size: 14px;
    color: var(--ink-muted);
}

.pay-PAY_NOW {
    background: #061209;
    border-left: 3px solid var(--color-low);
}

.pay-SCHEDULED {
    background: #1a0e06;
    border-left: 3px solid var(--color-high);
}

.pay-DEFER {
    background: var(--surface-1);
    border-left: 3px solid var(--hairline-strong);
    color: var(--ink-tertiary);
}

/* ── Narrative card ─────────────────────────────────────────── */
.narrative-card {
    background: var(--surface-1);
    border: 1px solid var(--hairline);
    border-radius: var(--r-lg);
    padding: var(--sp-md) var(--sp-lg);
    margin: var(--sp-xs) 0;
    line-height: 1.60;
    color: var(--ink-muted);
    font-size: 15px;
}

/* ── Fallback badge ─────────────────────────────────────────── */
.fallback-badge {
    font-size: 11px;
    color: var(--ink-tertiary);
    font-style: italic;
    margin-bottom: var(--sp-xs);
    font-family: var(--font-mono);
}

/* ── Grounding audit panel ──────────────────────────────────── */
.grounding-pass {
    color: var(--color-low);
    font-family: var(--font-mono);
    font-size: 12px;
    letter-spacing: 0;
}

.grounding-fail {
    color: var(--color-critical);
    font-family: var(--font-mono);
    font-size: 12px;
    letter-spacing: 0;
}

/* ── One collection / intervention box ─────────────────────── */
.intervention-box {
    background: var(--surface-2);
    border: 1px solid var(--primary);
    border-radius: var(--r-lg);
    padding: var(--sp-md) var(--sp-lg);
    margin: var(--sp-sm) 0;
}

/* ── Section eyebrow label ──────────────────────────────────── */
.section-label {
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 0.4px;
    text-transform: uppercase;
    color: var(--ink-subtle);
    margin: var(--sp-md) 0 var(--sp-xxs) 0;
    font-family: var(--font-body);
}

/* ── Typewriter cursor ──────────────────────────────────────── */
.tw-cursor {
    animation: blink 1s step-end infinite;
}

@keyframes blink {
    50% { opacity: 0; }
}

/* ── GST Calendar ───────────────────────────────────────────── */
.gst-event {
    padding: var(--sp-sm) var(--sp-md);
    border-radius: var(--r-sm);
    margin: var(--sp-xxs) 0;
    font-size: 13px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    color: var(--ink-muted);
    line-height: 1.50;
}

.gst-urgent  { background: #160606; border-left: 3px solid var(--color-critical); }
.gst-upcoming{ background: #160d05; border-left: 3px solid var(--color-moderate); }
.gst-future  { background: var(--surface-1); border-left: 3px solid var(--primary); }
.gst-overdue { background: #120616; border-left: 3px solid var(--color-purple); }

.gst-badge {
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.4px;
    padding: 2px var(--sp-xs);
    border-radius: var(--r-xs);
    text-transform: uppercase;
    font-family: var(--font-body);
    flex-shrink: 0;
}

.gst-badge-URGENT   { background: var(--color-critical); color: #fff; }
.gst-badge-UPCOMING { background: var(--color-moderate); color: #000; }
.gst-badge-FUTURE   { background: var(--primary);        color: #fff; }
.gst-badge-OVERDUE  { background: var(--color-purple);   color: #fff; }

/* ── Bankability ────────────────────────────────────────────── */
.bankability-card {
    background: var(--surface-1);
    border: 1px solid var(--hairline);
    border-radius: var(--r-lg);
    padding: var(--sp-md) var(--sp-lg);
    margin: var(--sp-xs) 0;
}

.bankability-grade {
    font-size: 3rem;
    font-weight: 700;
    letter-spacing: -0.05em;
    font-family: var(--font-display);
    line-height: 1;
}

.bankability-A { color: var(--color-low); }
.bankability-B { color: var(--color-info); }
.bankability-C { color: var(--color-moderate); }
.bankability-D { color: var(--color-high); }
.bankability-F { color: var(--color-critical); }

.bankability-blocker {
    background: #160d05;
    border-left: 3px solid var(--color-high);
    border-radius: var(--r-xs);
    padding: var(--sp-xs) var(--sp-sm);
    margin: var(--sp-xxs) 0;
    font-size: 13px;
    color: var(--ink-muted);
}

.bankability-scheme {
    display: inline-block;
    background: #06120a;
    color: var(--color-low);
    border: 1px solid rgba(39, 166, 68, 0.40);
    border-radius: var(--r-xs);
    padding: 2px var(--sp-xs);
    margin: 2px 3px;
    font-size: 12px;
    font-weight: 500;
    font-family: var(--font-body);
    letter-spacing: 0;
}

/* ── What-If result ─────────────────────────────────────────── */
.whatif-result-box {
    background: var(--surface-2);
    border: 1px solid var(--primary);
    border-radius: var(--r-lg);
    padding: var(--sp-md) var(--sp-lg);
    margin: var(--sp-sm) 0;
}

.whatif-label {
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 0.4px;
    text-transform: uppercase;
    color: var(--primary-hover);
    margin-bottom: var(--sp-xs);
    font-family: var(--font-body);
}

/* ── Plotly chart background ────────────────────────────────── */
.js-plotly-plot .plotly,
.js-plotly-plot .plotly .bg {
    background: var(--canvas) !important;
}

</style>
"""


def inject_styles() -> None:
    """
    Inject Linear design system CSS into the Streamlit app.
    Call exactly once at the top of app.py.
    """
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def risk_badge_html(risk_level: str, risk_score: int) -> str:
    """
    Return HTML for the hero risk badge.
    risk_level must be one of: CRITICAL, HIGH, MODERATE, LOW
    """
    return (
        f'<div class="risk-badge risk-{risk_level}">'
        f'{risk_level}&nbsp;&nbsp;{risk_score}/100'
        f'</div>'
    )


def severity_row_html(content: str, severity: str) -> str:
    """
    Wrap content HTML in a severity-coloured row div.
    severity must be one of: ANOMALY, WATCH, NORMAL
    """
    return (
        f'<div class="severity-row severity-{severity}">'
        f'{content}'
        f'</div>'
    )


def payment_row_html(content: str, action: str) -> str:
    """
    Wrap content HTML in a payment-action-coloured row div.
    action must be one of: PAY_NOW, SCHEDULED, DEFER
    """
    return (
        f'<div class="payment-row pay-{action}">'
        f'{content}'
        f'</div>'
    )
