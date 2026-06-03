# 🏦 Vani Finance CA Feature — Integration Guide

## Overview

Vani ab ek **AI-Powered Chartered Accountant** hai — end-to-end financial knowledge with voice triggers in Hindi, English, aur Hinglish.

---

## Files Added

| File | Description |
|------|-------------|
| `src/vani/reasoning/tools/finance_ca.py` | Core finance CA tool with 7 LangChain tools |
| `src/vani/ui/finance_ca.html` | Beautiful standalone finance dashboard UI |
| `modes/finance_ca_mode.txt` | Finance CA system prompt mode |
| `modes/core_mode.txt` | Updated with finance capabilities |

## Files Modified

| File | What Changed |
|------|-------------|
| `src/vani/reasoning/router.py` | Added 7 FINANCE_* intent regex patterns + dispatch handlers |
| `src/vani/planner/task_planner.py` | Added `("FINANCE_", "finance")` to agent map |

---

## Feature Coverage

### 1. 📊 Tax Knowledge
- Income Tax slabs — Old Regime & New Regime (FY 2024-25)
- ITR types (ITR-1 through ITR-7) and filing deadlines
- GST rates, GSTR-1, GSTR-3B filing
- TDS/TCS rules, Form 16, Form 26AS
- Deductions: 80C, 80D, HRA, LTA, 80CCD(1B)
- Advance tax installment schedule
- Capital gains (LTCG/STCG) taxation

### 2. 💰 Investment Advisor
- Mutual Funds: SIP, Lumpsum, ELSS, Debt, Hybrid
- Stock analysis with fundamental ratios
- PPF, NPS, FD, Bonds, REITs, SGBs comparison
- Risk-based portfolio recommendations
- Goal-based financial planning

### 3. 🧮 Calculators (Voice-Activated)
- **EMI Calculator**: Loan amount, rate, tenure → Monthly EMI + total interest
- **SIP Calculator**: Monthly amount, return, years → Future value + wealth multiplier
- **Tax Estimator**: Income, deductions, regime → Tax payable + in-hand salary
- **Lumpsum Calculator**: One-time investment returns

### 4. 📅 Compliance Calendar
- ITR deadlines (July 31, October 31, December 31)
- GST due dates (GSTR-1: 11th, GSTR-3B: 20th)
- Advance tax dates (June 15, Sep 15, Dec 15, Mar 15)
- TDS deposit (7th) and return dates
- Penalty information

### 5. 📈 Financial Ratios (12 ratios)
- P/E, EPS, ROE, ROCE, P/B, Debt/Equity
- Current Ratio, EBITDA Margin, Interest Coverage
- PEG Ratio, Dividend Yield, Free Cash Flow

### 6. 🤖 AI CA Chat
- Powered by Claude Sonnet via Anthropic API
- Full conversation history (last 10 turns)
- Quick prompts for common queries
- Hinglish support

---

## Voice Trigger Examples

```
# Tax
"income tax slab kya hai 2024-25"
"tax kaise bachao mujhe"
"ITR kab file karni hai"
"80C mein kya deductions milti hain"
"new regime vs old regime better kya hai"
"GST kya hota hai explain karo"
"TDS kaise deduct hota hai"

# Calculators
"EMI calculate karo 20 lakh 8.5% 20 saal"
"SIP returns nikalo 5000 monthly 15 saal 12%"
"home loan EMI kya hoga"

# Investments
"ELSS vs PPF kya better hai"
"mutual fund kaise kharidein"
"NPS ke baare mein batao"
"best investment for 1 lakh"
"paise kahan lagao"

# Compliance
"GST filing deadline kab hai"
"advance tax kab bharna hai"
"ITR last date kya hai"

# Ratios
"P/E ratio kya hota hai"
"ROE explain karo"
"EBITDA margin kya hai"
"balance sheet ratio samjhao"

# General CA
"CA ban meri"
"financial planning karo mere liye"
"capital gain tax explain karo"
"mujhe finance samjhao"
```

---

## How Intent Routing Works

```
User speaks → intent_classifier → router.py
    └─ FINANCE_EMI_RE matches "emi calculate karo 20 lakh"
         └─ _dispatch_intent("FINANCE_EMI", query, data)
              └─ handle_finance_intent() in finance_ca.py
                   └─ calculate_emi.ainvoke(loan_details=query)
                        └─ Pure math calculation → instant result
```

For complex queries that don't match regex:
```
User: "budget kaise banao"
    → No regex match
    → Falls through to Qwen/LLM
    → LLM has finance context from system prompt (updated core_mode.txt)
```

---

## API Requirements

Finance AI CA feature needs `ANTHROPIC_API_KEY` in `.env`:

```env
# .env file mein add karo:
ANTHROPIC_API_KEY=sk-ant-api...
```

Without API key, the tool falls back to static knowledge base (tax slabs, ratios, compliance dates work offline).

---

## UI Access

Open `src/vani/ui/finance_ca.html` in browser for the full Finance CA dashboard:

```bash
# Simple way to open:
open src/vani/ui/finance_ca.html

# Or add a route in your server:
# GET /finance → serve finance_ca.html
```

The UI includes:
- AI CA Chat (with Claude API)
- All 4 calculators with instant results
- Tax slab comparison (old/new regime toggle)
- Investment comparison cards
- Compliance calendar
- 12 financial ratio explanations

---

## Testing

```python
# Test finance intents directly:
import asyncio
from src.vani.reasoning.tools.finance_ca import (
    calculate_emi,
    sip_calculator,
    tax_slab_info,
    investment_compare,
    compliance_calendar,
    financial_ratio_explain,
    finance_query,
)

# EMI test
result = asyncio.run(calculate_emi.ainvoke({"loan_details": "20 lakh 8.5% 20 saal"}))
print(result)

# SIP test
result = asyncio.run(sip_calculator.ainvoke({"sip_details": "5000 monthly 15 years 12%"}))
print(result)

# Tax test
result = asyncio.run(tax_slab_info.ainvoke({"query": "new regime"}))
print(result)
```

---

## Architecture Notes

1. **Static Knowledge Base** — Tax slabs, ratios, compliance dates are hardcoded (no API needed, instant response)
2. **LangChain Tools** — All 7 tools use `@tool` decorator for LangChain compatibility
3. **Graceful Fallback** — If Anthropic API unavailable, regex-based local fallback kicks in
4. **Voice-Optimized** — All responses formatted for text-to-speech (short, bullet-pointed)
5. **INR Formatting** — Amounts displayed in Indian format (₹X Cr, ₹X L, ₹XK)
6. **Hinglish Support** — Both Hindi keywords and English accepted by regex

---

## Future Enhancements (TODO)

- [ ] Live NSE/BSE stock prices via API
- [ ] Portfolio tracker with P&L
- [ ] Automated ITR form filling guidance
- [ ] GST invoice generator
- [ ] Mutual Fund NAV lookup
- [ ] Credit score explainer
- [ ] Budget planner with expense tracking
- [ ] WhatsApp integration — send finance reports
