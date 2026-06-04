"""
vani/agents/finance_agent.py — Evolved Finance Agent

Handles all financial planning, tax slabs, due dates, loan EMIs, SIPs,
and fetches real-time keyless stock prices from Yahoo Finance.
"""

from __future__ import annotations

import logging
import re
import asyncio
from typing import Any
from vani.agents.base_agent import BaseAgent

logger = logging.getLogger("vani.agents.finance")


class FinanceAgent(BaseAgent):
    name = "finance"
    description = (
        "Indian income tax due dates, GST due dates, tax slab queries, investment advice, "
        "SIP return calculation, loan monthly EMIs, and real-time stock price lookup."
    )
    owned_tools = [
        "finance_query",
        "calculate_emi",
        "sip_calculator",
        "tax_slab_info",
        "investment_compare",
        "compliance_calendar",
        "financial_ratio_explain",
        "fetch_stock_price",
    ]

    def __init__(self) -> None:
        super().__init__()
        # Dynamically register the fetch_stock_price tool
        try:
            from vani.reasoning.registry import register_tool
            register_tool(
                "fetch_stock_price",
                self.fetch_stock_price,
                "fetch_stock_price(ticker) - Get real-time stock price from Yahoo Finance keylessly (e.g. AAPL, RELIANCE, INFY)"
            )
        except Exception as e:
            self.logger.warning(f"Could not register fetch_stock_price dynamically: {e}")

    async def fetch_stock_price(self, ticker: str) -> str:
        """
        Fetch real-time stock price and market metrics keylessly from Yahoo Finance.
        Supports international tickers (e.g., AAPL, GOOG) and Indian markets (e.g., RELIANCE.NS).
        """
        import requests
        
        # Normalize symbol mapping for common Indian equities
        tick = ticker.upper().strip()
        indian_mappings = {
            "RELIANCE": "RELIANCE.NS",
            "INFOSYS": "INFY.NS",
            "INFY": "INFY.NS",
            "TCS": "TCS.NS",
            "HDFC": "HDFCBANK.NS",
            "HDFCBANK": "HDFCBANK.NS",
            "ICICI": "ICICIBANK.NS",
            "SBI": "SBIN.NS",
            "SBIN": "SBIN.NS",
            "WIPRO": "WIPRO.NS",
        }
        tick = indian_mappings.get(tick, tick)

        # Check stock_cache
        try:
            from vani.core.cache import stock_cache
            cached_result = stock_cache.get(tick)
            if cached_result:
                self.logger.info("Stock cache hit for ticker: %s", tick)
                return cached_result
        except Exception as e:
            self.logger.warning(f"Could not access stock cache: {e}")

        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{tick}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        def _fetch_sync() -> str:
            try:
                r = requests.get(url, headers=headers, timeout=10)
                if r.status_code == 200:
                    data = r.json()
                    result = data.get("chart", {}).get("result", [])
                    if not result:
                        return f"❌ Stock '{tick}' nahi mila. Check spelling."
                    
                    meta = result[0].get("meta", {})
                    current_price = meta.get("regularMarketPrice")
                    prev_close = meta.get("previousClose")
                    currency = meta.get("currency", "USD")
                    
                    if current_price is None or prev_close is None:
                        return f"❌ Stock '{tick}' ka price data available nahi hai right now."
                    
                    change = current_price - prev_close
                    pct_change = (change / prev_close) * 100 if prev_close else 0.0
                    sign = "+" if change >= 0 else ""
                    symbol = "₹" if currency == "INR" else "$"

                    return (
                        f"📊 Stock Price Info ({tick}):\n"
                        f"💵 Live Price   : {symbol}{current_price:.2f} {currency}\n"
                        f"📈 Daily Change : {sign}{change:.2f} ({sign}{pct_change:.2f}%)\n"
                        f"🕒 Previous Close: {symbol}{prev_close:.2f} {currency}"
                    )
                else:
                    return f"❌ Connection issue: API returned status code {r.status_code}"
            except Exception as e:
                logger.error(f"Error fetching Yahoo Finance data for {tick}: {e}")
                return f"❌ Error fetching stock data: {e}"

        loop = asyncio.get_running_loop()
        res = await loop.run_in_executor(None, _fetch_sync)
        if not res.startswith("❌"):
            try:
                stock_cache.set(tick, res, ttl_seconds=60)  # 1 minute
            except Exception as e:
                self.logger.warning(f"Could not save to stock cache: {e}")
        return res

    async def handle(self, intent: str, data: Any, query: str) -> str:
        """
        Legacy handler forwarding to finance_ca intent dispatcher.
        """
        from vani.reasoning.tools.finance_ca import handle_finance_intent
        return await handle_finance_intent(intent, query, data if isinstance(data, dict) else {})
