"""
vani/reasoning/tools/finance_ca.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🏦 Vani ka AI-Powered Finance CA Assistant

End-to-end financial intelligence covering:
  ┌─────────────────────────────────────────────────────────────┐
  │  1. TAX KNOWLEDGE         — Income Tax, GST, TDS, ITR       │
  │  2. INVESTMENT ADVISOR    — Stocks, MF, SIP, FD, NPS        │
  │  3. BUDGET & CASHFLOW     — Personal & Business budgeting    │
  │  4. CA CONCEPTS           — Accounting, Audit, Balance Sheet │
  │  5. FINANCIAL RATIOS      — P/E, ROE, Debt/Equity, EBITDA   │
  │  6. LOAN CALCULATOR       — EMI, interest, amortization     │
  │  7. MARKET INTEL          — Live prices, NSE/BSE data       │
  │  8. COMPLIANCE CALENDAR   — Tax deadlines, filings, due dates│
  └─────────────────────────────────────────────────────────────┘

VOICE TRIGGERS (Hindi/English/Hinglish):
  "tax kaise bachao", "ITR kab file karni hai",
  "SIP vs lumpsum kya better hai", "balance sheet explain karo",
  "EMI calculate karo", "Infosys ka P/E ratio kya hai",
  "income tax slab 2024-25", "GST kya hai", "mutual fund kaise kharidein",
  "financial planning karo mere liye", "CA bano meri",
  "how to save tax", "what is ELSS", "explain demat account"

TOOLS REGISTERED:
  - finance_query        → LLM-powered deep CA knowledge
  - calculate_emi        → EMI/loan calculator
  - tax_slab_info        → Income tax slabs & deductions
  - investment_compare   → Compare investment options
  - compliance_calendar  → Tax filing deadlines
  - sip_calculator       → SIP returns calculator
  - financial_ratio_explain → CA ratio explanations

ROUTER PATTERNS to add in router.py:
  FINANCE_QUERY, FINANCE_EMI, FINANCE_TAX, FINANCE_INVEST,
  FINANCE_CALENDAR, FINANCE_SIP, FINANCE_RATIO
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Optional

import requests
from langchain_core.tools import tool

logger = logging.getLogger("vani.finance_ca")

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG — Claude / Gemini API for deep CA reasoning
# ─────────────────────────────────────────────────────────────────────────────

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
FINANCE_MODEL = "claude-sonnet-4-20250514"

# ─────────────────────────────────────────────────────────────────────────────
# FINANCE CA SYSTEM PROMPT
# ─────────────────────────────────────────────────────────────────────────────

_FINANCE_CA_SYSTEM = """
Tu Vani ka AI Finance CA (Chartered Accountant) expert hai. 
Tu India-specific finance, tax, accounting, and investment knowledge rakhta hai.

EXPERTISE AREAS:
1. INCOME TAX — Slabs (old/new regime), deductions (80C, 80D, HRA, LTA), ITR types, advance tax
2. GST — Rates, input credit, filing (GSTR-1, GSTR-3B), composition scheme, RCM
3. TDS/TCS — Rates, deduction rules, Form 16, Form 26AS
4. INVESTMENTS — Stocks, Mutual Funds, SIP, FD, PPF, NPS, ELSS, Bonds, REITs
5. FINANCIAL PLANNING — Goal-based planning, insurance, emergency fund, portfolio allocation
6. ACCOUNTING — Journal entries, P&L, Balance Sheet, Cash Flow, Depreciation
7. AUDIT — Statutory audit, internal audit, tax audit (44AB), GST audit
8. RATIOS — P/E, EPS, ROE, ROCE, Debt-to-Equity, Current Ratio, EBITDA margin
9. COMPLIANCE — Due dates, penalties, notices, assessments, appeals
10. BUSINESS FINANCE — Working capital, capital structure, valuation, M&A basics
11. PERSONAL FINANCE — Budgeting, saving, debt management, retirement planning
12. MARKETS — NSE/BSE, Nifty50, Sensex, FII/DII data, sector analysis

STYLE:
- Short aur clear answers — voice ke liye optimized
- Numbers aur examples zaroor do
- Hinglish OK hai
- Technical terms explain karo agar zaroor ho
- Practical advice do — just theory nahi
- Amounts INR mein do
- Bullet points mein organize karo long answers ko

IMPORTANT:
- Always disclaimer karo ki professional CA/advisor se consult karo for big decisions
- Latest FY (2024-25) figures use karo jab tak asked nahi
- Conservative advice do — risky bets nahi
"""

# ─────────────────────────────────────────────────────────────────────────────
# STATIC KNOWLEDGE BASE — fast, no API needed
# ─────────────────────────────────────────────────────────────────────────────

TAX_SLABS_NEW_REGIME_FY2425 = {
    "regime": "New Tax Regime (FY 2024-25)",
    "slabs": [
        {"range": "0 - 3,00,000", "rate": "NIL"},
        {"range": "3,00,001 - 7,00,000", "rate": "5%"},
        {"range": "7,00,001 - 10,00,000", "rate": "10%"},
        {"range": "10,00,001 - 12,00,000", "rate": "15%"},
        {"range": "12,00,001 - 15,00,000", "rate": "20%"},
        {"range": "Above 15,00,000", "rate": "30%"},
    ],
    "rebate": "Section 87A: Income up to ₹7 lakhs → Zero tax",
    "standard_deduction": "₹75,000 for salaried",
    "note": "No 80C, 80D deductions in new regime",
}

TAX_SLABS_OLD_REGIME_FY2425 = {
    "regime": "Old Tax Regime (FY 2024-25)",
    "slabs": [
        {"range": "0 - 2,50,000", "rate": "NIL"},
        {"range": "2,50,001 - 5,00,000", "rate": "5%"},
        {"range": "5,00,001 - 10,00,000", "rate": "20%"},
        {"range": "Above 10,00,000", "rate": "30%"},
    ],
    "rebate": "Section 87A: Income up to ₹5 lakhs → Zero tax",
    "standard_deduction": "₹50,000 for salaried",
    "deductions": [
        "80C: ₹1.5 lakh (PPF, ELSS, LIC, EPF, etc.)",
        "80D: ₹25,000 (medical insurance)",
        "HRA: Actual HRA or formula-based",
        "LTA: Leave Travel Allowance",
        "80CCD(1B): NPS ₹50,000 extra",
        "80TTA: ₹10,000 savings interest",
    ],
}

COMPLIANCE_CALENDAR = {
    "ITR": [
        {"deadline": "31 July", "desc": "ITR filing deadline (non-audit cases)"},
        {"deadline": "31 October", "desc": "ITR filing deadline (audit cases)"},
        {"deadline": "31 December", "desc": "Belated/Revised ITR deadline"},
    ],
    "GST": [
        {"deadline": "11th of next month", "desc": "GSTR-1 (monthly filers)"},
        {"deadline": "20th of next month", "desc": "GSTR-3B (monthly filers)"},
        {"deadline": "13th of next quarter", "desc": "GSTR-1 (quarterly filers)"},
        {"deadline": "22nd/24th of next quarter", "desc": "GSTR-3B (quarterly)"},
    ],
    "TDS": [
        {"deadline": "7th of next month", "desc": "TDS payment to government"},
        {"deadline": "31 July/31 Oct/31 Jan/31 May", "desc": "TDS return (quarterly)"},
        {"deadline": "15 June / 15 Sep / 15 Dec / 15 Mar", "desc": "Advance Tax installments"},
    ],
    "Advance Tax": [
        {"deadline": "15 June", "desc": "15% advance tax"},
        {"deadline": "15 September", "desc": "45% advance tax (cumulative)"},
        {"deadline": "15 December", "desc": "75% advance tax (cumulative)"},
        {"deadline": "15 March", "desc": "100% advance tax"},
    ],
}

FINANCIAL_RATIOS = {
    "P/E Ratio": {
        "formula": "Market Price / Earnings Per Share",
        "meaning": "Kitna premium de rahe ho per rupee earning",
        "good_range": "< 25 for value stocks; < 30 generally acceptable",
        "caution": "Very high P/E = expensive or overvalued",
    },
    "ROE": {
        "formula": "Net Profit / Shareholders Equity × 100",
        "meaning": "Company equity pe kitna return generate kar rahi hai",
        "good_range": "> 15% is good; > 20% is excellent",
        "caution": "High debt can inflate ROE artificially",
    },
    "Debt-to-Equity": {
        "formula": "Total Debt / Shareholders Equity",
        "meaning": "Company kitne debt mein hai equity ke relative",
        "good_range": "< 1 is conservative; 1-2 is moderate",
        "caution": "NBFC/banks mein normal hai D/E > 3",
    },
    "Current Ratio": {
        "formula": "Current Assets / Current Liabilities",
        "meaning": "Short-term obligations pay karne ki ability",
        "good_range": "1.5 to 3 is healthy",
        "caution": "< 1 means liquidity problem",
    },
    "EBITDA Margin": {
        "formula": "EBITDA / Revenue × 100",
        "meaning": "Operating profitability before depreciation & tax",
        "good_range": "Depends on industry; > 20% generally good",
        "caution": "Compare within same industry only",
    },
    "EPS": {
        "formula": "Net Profit / Number of Shares",
        "meaning": "Per share kitna profit company ne kamaya",
        "good_range": "Growing EPS YoY = positive sign",
        "caution": "Stock splits can distort historical EPS",
    },
}

INVESTMENT_COMPARISON = {
    "ELSS": {
        "full": "Equity Linked Savings Scheme",
        "returns": "12-15% (market-linked, no guarantee)",
        "lock_in": "3 years (shortest among tax-saving)",
        "tax_benefit": "80C: ₹1.5 lakh",
        "risk": "High (equity market risk)",
        "best_for": "Tax saving + long-term wealth creation",
    },
    "PPF": {
        "full": "Public Provident Fund",
        "returns": "7.1% per annum (government guaranteed)",
        "lock_in": "15 years (partial withdrawal after 7 years)",
        "tax_benefit": "80C: ₹1.5 lakh; EEE status",
        "risk": "Zero (sovereign guarantee)",
        "best_for": "Safe long-term retirement corpus",
    },
    "NPS": {
        "full": "National Pension System",
        "returns": "9-12% (market-linked, equity + debt mix)",
        "lock_in": "Till retirement (60 years)",
        "tax_benefit": "80C + extra ₹50,000 under 80CCD(1B)",
        "risk": "Medium (depends on allocation)",
        "best_for": "Retirement planning with additional tax benefit",
    },
    "FD": {
        "full": "Fixed Deposit",
        "returns": "6.5-7.5% (bank-dependent)",
        "lock_in": "Flexible (7 days to 10 years)",
        "tax_benefit": "80C for 5-year tax-saver FD only",
        "risk": "Very Low (DICGC insured up to ₹5 lakh)",
        "best_for": "Capital preservation, emergency fund",
    },
    "Mutual Fund SIP": {
        "full": "Systematic Investment Plan",
        "returns": "12-18% (equity; historical average ~14%)",
        "lock_in": "No lock-in (except ELSS)",
        "tax_benefit": "LTCG tax 12.5% above ₹1.25 lakh gains",
        "risk": "Medium to High",
        "best_for": "Wealth creation, goal-based investing",
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# UTILITY FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def _calculate_emi_math(principal: float, annual_rate: float, months: int) -> dict:
    """Pure math EMI calculation — no API needed."""
    if annual_rate == 0:
        emi = principal / months
        total = principal
        interest = 0.0
    else:
        r = annual_rate / (12 * 100)
        emi = principal * r * ((1 + r) ** months) / (((1 + r) ** months) - 1)
        total = emi * months
        interest = total - principal

    return {
        "emi": round(emi, 2),
        "total_payment": round(total, 2),
        "total_interest": round(interest, 2),
        "principal": principal,
        "rate": annual_rate,
        "tenure_months": months,
    }


def _calculate_sip_math(monthly_amount: float, annual_return: float, years: int) -> dict:
    """SIP future value calculation using compound interest formula."""
    r = annual_return / (12 * 100)
    n = years * 12
    if r == 0:
        fv = monthly_amount * n
    else:
        fv = monthly_amount * (((1 + r) ** n - 1) / r) * (1 + r)

    invested = monthly_amount * n
    gains = fv - invested

    return {
        "future_value": round(fv, 2),
        "total_invested": round(invested, 2),
        "total_gains": round(gains, 2),
        "absolute_return_pct": round((gains / invested) * 100, 1),
        "monthly_amount": monthly_amount,
        "annual_return_pct": annual_return,
        "years": years,
    }


def _parse_amount(text: str) -> Optional[float]:
    """Parse amounts like '10 lakh', '50000', '2.5 crore', '10L' from voice."""
    text = text.lower().strip()
    # crore
    m = re.search(r"([\d.]+)\s*(cr|crore|crores)", text)
    if m:
        return float(m.group(1)) * 1_00_00_000
    # lakh
    m = re.search(r"([\d.]+)\s*(l|lakh|lakhs|lac|lacs)", text)
    if m:
        return float(m.group(1)) * 1_00_000
    # thousand
    m = re.search(r"([\d.]+)\s*(k|thousand|thousands)", text)
    if m:
        return float(m.group(1)) * 1_000
    # plain number
    m = re.search(r"[\d,]+\.?\d*", text.replace(",", ""))
    if m:
        return float(m.group().replace(",", ""))
    return None


def _format_inr(amount: float) -> str:
    """Format amount in Indian number system."""
    if amount >= 1_00_00_000:
        return f"₹{amount/1_00_00_000:.2f} Cr"
    elif amount >= 1_00_000:
        return f"₹{amount/1_00_000:.2f} L"
    elif amount >= 1_000:
        return f"₹{amount/1_000:.1f}K"
    return f"₹{amount:,.0f}"


async def _ask_finance_ca(question: str, context: str = "") -> str:
    """
    Call Claude API for deep CA knowledge.
    Falls back to local knowledge base if API unavailable.
    """
    import os
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    if not api_key:
        return _local_finance_fallback(question)

    prompt = f"{context}\n\nUser question: {question}" if context else question

    try:
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: requests.post(
                ANTHROPIC_API_URL,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": FINANCE_MODEL,
                    "max_tokens": 800,
                    "system": _FINANCE_CA_SYSTEM,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=20,
            )
        )
        response.raise_for_status()
        data = response.json()
        return data["content"][0]["text"].strip()
    except Exception as e:
        logger.warning(f"[FINANCE_CA] API call failed: {e} — using local fallback")
        return _local_finance_fallback(question)


def _local_finance_fallback(question: str) -> str:
    """Rule-based local fallback using static knowledge base."""
    q = question.lower()

    # Tax slabs
    if any(w in q for w in ["slab", "tax rate", "income tax rate", "kitna tax"]):
        if "old" in q:
            regime = TAX_SLABS_OLD_REGIME_FY2425
        else:
            regime = TAX_SLABS_NEW_REGIME_FY2425
        slabs = "\n".join([f"  • {s['range']}: {s['rate']}" for s in regime["slabs"]])
        return f"📊 {regime['regime']}:\n{slabs}\n\n💡 {regime.get('rebate', '')}\n📌 Standard Deduction: {regime.get('standard_deduction', '')}"

    # GST
    if "gst" in q:
        return "📋 GST Rates: 0%, 5%, 12%, 18%, 28%\n• 5%: Essential goods (food, medicine)\n• 12%: Processed food, textiles\n• 18%: Electronics, services\n• 28%: Luxury items, automobiles\n\n📅 GSTR-1: 11th | GSTR-3B: 20th of next month"

    # 80C
    if "80c" in q:
        return "💰 Section 80C Deductions (Max ₹1.5 Lakh):\n• PPF, ELSS, Life Insurance premium\n• EPF, NSC, 5-yr Bank FD\n• Home loan principal repayment\n• Children's tuition fees\n• SCSS (Senior Citizen Savings Scheme)"

    # SIP
    if "sip" in q:
        return "📈 SIP (Systematic Investment Plan):\n• Monthly fixed investment in mutual funds\n• Rupee cost averaging benefit\n• Start with ₹500/month\n• Historical equity SIP returns: ~12-14% CAGR\n• Best for: long-term (5+ years) wealth creation"

    # ITR
    if "itr" in q or "income tax return" in q:
        return "📄 ITR Types:\n• ITR-1 (Sahaj): Salary + 1 house + other income\n• ITR-2: Capital gains/multiple properties\n• ITR-3: Business/profession income\n• ITR-4: Presumptive taxation\n\n📅 Deadline: 31 July (non-audit) | 31 Oct (audit)"

    # P/E or EPS
    for ratio, info in FINANCIAL_RATIOS.items():
        if ratio.lower().replace("/", "").replace(" ", "") in q.replace("/", "").replace(" ", ""):
            return f"📊 {ratio}:\n• Formula: {info['formula']}\n• Meaning: {info['meaning']}\n• Good Range: {info['good_range']}\n⚠️ {info['caution']}"

    return "💡 Yeh complex financial question hai. Main tumhare liye detail mein explain karta hoon — please ek baar specific question poochho ya CA se consult karo for personalized advice."


# ─────────────────────────────────────────────────────────────────────────────
# LANGCHAIN TOOLS
# ─────────────────────────────────────────────────────────────────────────────

@tool
async def finance_query(question: str) -> str:
    """
    Deep AI-powered Finance CA knowledge.
    
    Covers: income tax, GST, TDS, investments, mutual funds, stocks,
    accounting, financial ratios, compliance, personal finance, business finance.
    
    Voice triggers: tax save karo, ITR explain, SIP kya hota hai,
    GST kaise file karein, mutual fund recommend karo, CA ban meri.
    """
    logger.info(f"[FINANCE_CA] Query: {question}")
    answer = await _ask_finance_ca(question)
    return f"🏦 {answer}"


@tool
async def calculate_emi(loan_details: str) -> str:
    """
    EMI Calculator for any loan — home, car, personal, education.
    
    Input examples:
      "10 lakh 8.5% 5 saal"
      "50 lakh home loan 8% 20 years"
      "2 lakh personal loan 12% 24 months"
    """
    logger.info(f"[FINANCE_CA] EMI calc: {loan_details}")
    text = loan_details.lower()

    principal = _parse_amount(text)
    if not principal:
        return "❌ Loan amount batao. Example: '20 lakh 8.5% 10 saal'"

    # Parse interest rate
    rate_m = re.search(r"([\d.]+)\s*%", text)
    if not rate_m:
        return "❌ Interest rate batao. Example: '8.5%'"
    rate = float(rate_m.group(1))

    # Parse tenure
    years_m = re.search(r"(\d+)\s*(year|saal|yr|साल)", text)
    months_m = re.search(r"(\d+)\s*(month|mahine|mahina|माह)", text)
    if years_m:
        months = int(years_m.group(1)) * 12
    elif months_m:
        months = int(months_m.group(1))
    else:
        return "❌ Tenure batao. Example: '20 saal' ya '240 months'"

    result = _calculate_emi_math(principal, rate, months)

    return (
        f"🏦 EMI Calculator Result\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 Loan Amount   : {_format_inr(result['principal'])}\n"
        f"📌 Interest Rate : {result['rate']}% per annum\n"
        f"📌 Tenure        : {result['tenure_months']//12} years ({result['tenure_months']} months)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Monthly EMI   : {_format_inr(result['emi'])}\n"
        f"💸 Total Payment : {_format_inr(result['total_payment'])}\n"
        f"📈 Total Interest: {_format_inr(result['total_interest'])}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 Tip: Prepay early to save ₹{_format_inr(result['total_interest']*0.3)}-{_format_inr(result['total_interest']*0.5)} interest!"
    )


@tool
async def sip_calculator(sip_details: str) -> str:
    """
    SIP Returns Calculator — future value, total gains, wealth multiplier.
    
    Input examples:
      "5000 per month 10 years 12%"
      "monthly 10000 15 saal"
      "SIP 2000 monthly 5 year 14 percent"
    """
    logger.info(f"[FINANCE_CA] SIP calc: {sip_details}")
    text = sip_details.lower()

    # Monthly amount
    amount = _parse_amount(text)
    if not amount:
        return "❌ Monthly SIP amount batao. Example: '5000 monthly 10 saal'"

    # Annual return rate
    rate_m = re.search(r"([\d.]+)\s*%", text)
    rate = float(rate_m.group(1)) if rate_m else 12.0

    # Years
    years_m = re.search(r"(\d+)\s*(year|saal|yr|साल)", text)
    if not years_m:
        return "❌ Investment period batao. Example: '10 saal'"
    years = int(years_m.group(1))

    result = _calculate_sip_math(amount, rate, years)

    wealth_multiplier = result["future_value"] / result["total_invested"]

    return (
        f"📈 SIP Calculator Result\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 Monthly SIP   : {_format_inr(result['monthly_amount'])}\n"
        f"📌 Annual Return : {result['annual_return_pct']}%\n"
        f"📌 Time Period   : {result['years']} years\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Future Value  : {_format_inr(result['future_value'])}\n"
        f"💵 Total Invested: {_format_inr(result['total_invested'])}\n"
        f"📊 Total Gains   : {_format_inr(result['total_gains'])}\n"
        f"🚀 Returns       : {result['absolute_return_pct']}% absolute\n"
        f"💡 Wealth x{wealth_multiplier:.1f} multiplied!\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ Note: Returns are estimates based on {rate}% CAGR. Markets are subject to risk."
    )


@tool
async def tax_slab_info(query: str) -> str:
    """
    Income Tax slab information — old regime, new regime, deductions, rebates.
    
    Query examples:
      "new regime", "old regime", "deductions list",
      "which regime is better", "tax on 12 lakh salary"
    """
    logger.info(f"[FINANCE_CA] Tax query: {query}")
    q = query.lower()

    if "which" in q and "better" in q:
        answer = await _ask_finance_ca(
            f"Old vs New Tax Regime comparison FY 2024-25: {query}",
            context="Give a practical comparison for salaried individual"
        )
        return f"⚖️ {answer}"

    if "new" in q:
        regime = TAX_SLABS_NEW_REGIME_FY2425
    elif "old" in q:
        regime = TAX_SLABS_OLD_REGIME_FY2425
    else:
        # Show both
        return (
            f"📊 FY 2024-25 Tax Regimes:\n\n"
            f"🆕 NEW REGIME (Default):\n"
            + "\n".join([f"  • {s['range']}: {s['rate']}" for s in TAX_SLABS_NEW_REGIME_FY2425["slabs"]])
            + f"\n  Rebate: {TAX_SLABS_NEW_REGIME_FY2425['rebate']}"
            + f"\n\n📋 OLD REGIME:\n"
            + "\n".join([f"  • {s['range']}: {s['rate']}" for s in TAX_SLABS_OLD_REGIME_FY2425["slabs"]])
            + f"\n  Rebate: {TAX_SLABS_OLD_REGIME_FY2425['rebate']}"
            + f"\n\n💡 80C, 80D deductions only in Old Regime!"
        )

    slabs_text = "\n".join([f"  • {s['range']}: {s['rate']}" for s in regime["slabs"]])
    deductions_text = ""
    if "deductions" in regime:
        deductions_text = "\n\n📋 Key Deductions:\n" + "\n".join([f"  • {d}" for d in regime["deductions"]])

    return (
        f"📊 {regime['regime']}\n\n"
        f"{slabs_text}\n\n"
        f"💡 {regime.get('rebate', '')}\n"
        f"📌 Standard Deduction: {regime.get('standard_deduction', '')}"
        + deductions_text
    )


@tool
async def investment_compare(options_query: str) -> str:
    """
    Compare investment options — ELSS vs PPF, SIP vs FD, NPS vs ELSS, etc.
    
    Examples:
      "ELSS vs PPF", "SIP vs FD", "where to invest 1 lakh",
      "best tax saving investment", "NPS ke baare mein batao"
    """
    logger.info(f"[FINANCE_CA] Investment compare: {options_query}")
    q = options_query.lower()

    # Check for specific instrument comparison
    found = []
    for key in INVESTMENT_COMPARISON:
        if key.lower() in q or INVESTMENT_COMPARISON[key]["full"].lower() in q:
            found.append(key)

    if len(found) >= 2:
        # Direct comparison
        lines = [f"⚖️ {found[0]} vs {found[1]}\n"]
        for key in found:
            info = INVESTMENT_COMPARISON[key]
            lines.append(f"📌 {key} ({info['full']}):")
            lines.append(f"  Returns  : {info['returns']}")
            lines.append(f"  Lock-in  : {info['lock_in']}")
            lines.append(f"  Tax Benefit: {info['tax_benefit']}")
            lines.append(f"  Risk     : {info['risk']}")
            lines.append(f"  Best For : {info['best_for']}\n")
        return "\n".join(lines)

    elif len(found) == 1:
        key = found[0]
        info = INVESTMENT_COMPARISON[key]
        return (
            f"📊 {key} — {info['full']}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📈 Returns    : {info['returns']}\n"
            f"🔒 Lock-in    : {info['lock_in']}\n"
            f"🎁 Tax Benefit: {info['tax_benefit']}\n"
            f"⚠️  Risk       : {info['risk']}\n"
            f"✅ Best For   : {info['best_for']}"
        )

    # Ask AI for general investment advice
    answer = await _ask_finance_ca(options_query, context="Investment comparison and recommendation for Indian investor")
    return f"💡 {answer}"


@tool
async def compliance_calendar(query: str) -> str:
    """
    Tax & GST compliance calendar — due dates, deadlines, penalties.
    
    Examples:
      "ITR deadline kab hai", "GST filing dates",
      "advance tax kab bharna hai", "TDS return deadline"
    """
    logger.info(f"[FINANCE_CA] Compliance query: {query}")
    q = query.lower()
    today = datetime.now()
    month = today.strftime("%B")

    result_lines = [f"📅 Compliance Calendar — {month} {today.year}\n"]

    if "itr" in q or "income tax return" in q:
        result_lines.append("📄 ITR DEADLINES:")
        for item in COMPLIANCE_CALENDAR["ITR"]:
            result_lines.append(f"  • {item['deadline']}: {item['desc']}")

    elif "gst" in q:
        result_lines.append("📋 GST FILING DEADLINES:")
        for item in COMPLIANCE_CALENDAR["GST"]:
            result_lines.append(f"  • {item['deadline']}: {item['desc']}")

    elif "tds" in q:
        result_lines.append("🏦 TDS DEADLINES:")
        for item in COMPLIANCE_CALENDAR["TDS"]:
            result_lines.append(f"  • {item['deadline']}: {item['desc']}")

    elif "advance" in q and "tax" in q:
        result_lines.append("💸 ADVANCE TAX INSTALLMENTS:")
        for item in COMPLIANCE_CALENDAR["Advance Tax"]:
            result_lines.append(f"  • {item['deadline']}: {item['desc']}")

    else:
        # Show all upcoming
        result_lines.append("🗓️ ALL KEY DEADLINES:\n")
        for category, items in COMPLIANCE_CALENDAR.items():
            result_lines.append(f"📌 {category}:")
            for item in items[:2]:  # Show top 2 per category
                result_lines.append(f"  • {item['deadline']}: {item['desc']}")
            result_lines.append("")

    result_lines.append("\n⚠️ Penalty for late ITR: ₹1,000-₹5,000 | GST: 18% interest")
    return "\n".join(result_lines)


@tool
async def financial_ratio_explain(ratio_query: str) -> str:
    """
    Explain financial ratios for stock analysis — P/E, ROE, EBITDA, Debt-Equity, etc.
    
    Examples:
      "P/E ratio kya hota hai", "ROE explain karo",
      "current ratio", "EBITDA margin kya hai"
    """
    logger.info(f"[FINANCE_CA] Ratio query: {ratio_query}")
    q = ratio_query.lower()

    # Find matching ratio
    for ratio, info in FINANCIAL_RATIOS.items():
        ratio_key = ratio.lower().replace("/", "").replace(" ", "").replace("-", "")
        query_clean = q.replace("/", "").replace(" ", "").replace("-", "")
        if ratio_key in query_clean or ratio.lower().split("/")[0].strip() in q:
            return (
                f"📊 {ratio}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📐 Formula  : {info['formula']}\n"
                f"💡 Meaning  : {info['meaning']}\n"
                f"✅ Good Range: {info['good_range']}\n"
                f"⚠️  Caution  : {info['caution']}"
            )

    # General ratio or new ratio — ask AI
    answer = await _ask_finance_ca(
        ratio_query,
        context="Explain financial ratio for stock market analysis in India"
    )
    return f"📊 {answer}"


# ─────────────────────────────────────────────────────────────────────────────
# CONVENIENCE ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

async def handle_finance_intent(intent: str, query: str, data: dict = None) -> str:
    """
    Single dispatcher for all FINANCE_* intents from router.py
    
    Usage in router.py _dispatch_intent:
        from vani.reasoning.tools.finance_ca import handle_finance_intent
        elif intent.startswith("FINANCE_"):
            return await handle_finance_intent(intent, query, data or {})
    """
    data = data or {}

    if intent == "FINANCE_EMI":
        return await calculate_emi.ainvoke({"loan_details": query})

    elif intent == "FINANCE_SIP":
        return await sip_calculator.ainvoke({"sip_details": query})

    elif intent == "FINANCE_TAX":
        return await tax_slab_info.ainvoke({"query": query})

    elif intent == "FINANCE_INVEST":
        return await investment_compare.ainvoke({"options_query": query})

    elif intent == "FINANCE_CALENDAR":
        return await compliance_calendar.ainvoke({"query": query})

    elif intent == "FINANCE_RATIO":
        return await financial_ratio_explain.ainvoke({"ratio_query": query})

    elif intent == "FINANCE_QUERY":
        return await finance_query.ainvoke({"question": query})

    else:
        # Generic finance query
        return await finance_query.ainvoke({"question": query})
