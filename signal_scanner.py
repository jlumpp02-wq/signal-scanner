"""
SignalScanner v5 — Asymmetric Alt Opportunity Bot
Runs on GitHub Actions. Sends Discord alerts.

Data sources:
  - CoinGecko (free API): prices, 30-day history → RSI-14, OBV
  - Alternative.me: Fear & Greed Index
  - CoinGecko: BTC dominance, stablecoin market cap
  
No API keys required for any data source.
"""

import json, math, os, sys, time
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.error import HTTPError

# ─── Config ───────────────────────────────────────────────
TOKENS = {
    "ethereum": "ETH",
    "chainlink": "LINK",
    "ripple": "XRP",
    "iota": "IOTA",
    "stellar": "XLM",
    "hedera-hashgraph": "HBAR",
    "quant-network": "QNT",
    "xdce-crowd-sale": "XDC",
    "ondo-finance": "ONDO",
}

DISCORD_WEBHOOK = "https://api.telegram.org/bot8616504560:AAEEHOv317P0PsOmRbDqlWn7RZKl71KzFb0/getUpdates"
ALERT_THRESHOLD = 65  # composite score to trigger alert
SCAN_LOG_FILE = "last_scan.json"


# ─── HTTP Helper ──────────────────────────────────────────
def fetch_json(url, retries=3):
    """Fetch JSON from URL with retries and rate-limit handling."""
    for attempt in range(retries):
        try:
            req = Request(url, headers={"User-Agent": "SignalScanner/5.0", "Accept": "application/json"})
            with urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except HTTPError as e:
            if e.code == 429:
                wait = 30 * (attempt + 1)
                print(f"  Rate limited, waiting {wait}s...")
                time.sleep(wait)
            else:
                print(f"  HTTP {e.code} for {url}")
                if attempt < retries - 1:
                    time.sleep(5)
        except Exception as e:
            print(f"  Error: {e}")
            if attempt < retries - 1:
                time.sleep(5)
    return None


# ─── Data Fetchers ────────────────────────────────────────
def get_fear_greed():
    """Fetch Fear & Greed Index from Alternative.me"""
    print("📊 Fetching Fear & Greed Index...")
    data = fetch_json("https://api.alternative.me/fng/?limit=1")
    if data and "data" in data and len(data["data"]) > 0:
        entry = data["data"][0]
        return {
            "value": int(entry["value"]),
            "label": entry["value_classification"],
        }
    return {"value": 50, "label": "Unknown"}


def get_global_data():
    """Fetch BTC dominance and total market data from CoinGecko"""
    print("🌍 Fetching global market data...")
    data = fetch_json("https://api.coingecko.com/api/v3/global")
    if data and "data" in data:
        d = data["data"]
        btc_dom = round(d.get("market_cap_percentage", {}).get("btc", 0), 1)
        # Sum stablecoin dominance (USDT + USDC + DAI + BUSD)
        stables = ["usdt", "usdc", "dai", "busd"]
        stable_dom = round(sum(d.get("market_cap_percentage", {}).get(s, 0) for s in stables), 2)
        total_mcap = d.get("total_market_cap", {}).get("usd", 0)
        return {
            "btc_dominance": btc_dom,
            "stablecoin_dominance": stable_dom,
            "total_market_cap": total_mcap,
        }
    return {"btc_dominance": 55, "stablecoin_dominance": 10, "total_market_cap": 0}


def get_btc_price():
    """Fetch BTC current price from CoinGecko"""
    print("₿ Fetching BTC price...")
    data = fetch_json(
        "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd&include_24hr_change=true"
    )
    if data and "bitcoin" in data:
        return {
            "price": round(data["bitcoin"]["usd"], 2),
            "change_24h": round(data["bitcoin"].get("usd_24h_change", 0), 2),
        }
    return {"price": 0, "change_24h": 0}


def get_token_prices():
    """Fetch current prices for all alt tokens from CoinGecko"""
    ids = ",".join(TOKENS.keys())
    print(f"💰 Fetching prices for {len(TOKENS)} tokens...")
    data = fetch_json(
        f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd&include_24hr_change=true"
    )
    prices = {}
    if data:
        for cg_id, symbol in TOKENS.items():
            if cg_id in data:
                prices[symbol] = {
                    "price": data[cg_id]["usd"],
                    "change_24h": round(data[cg_id].get("usd_24h_change", 0), 2),
                }
    return prices


def get_market_chart(cg_id, days=30):
    """Fetch daily OHLC/price history for RSI and OBV computation"""
    data = fetch_json(
        f"https://api.coingecko.com/api/v3/coins/{cg_id}/market_chart?vs_currency=usd&days={days}&interval=daily"
    )
    if data and "prices" in data and "total_volumes" in data:
        prices = [p[1] for p in data["prices"]]
        volumes = [v[1] for v in data["total_volumes"]]
        # Align lengths
        min_len = min(len(prices), len(volumes))
        return prices[:min_len], volumes[:min_len]
    return [], []


# ─── Technical Indicators ─────────────────────────────────
def compute_rsi(prices, period=14):
    """Standard RSI-14 from daily close prices"""
    if len(prices) < period + 1:
        return None

    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return round(rsi, 1)


def compute_obv_signal(prices, volumes, lookback=7):
    """
    Compute OBV direction vs price direction over last N days.
    Returns: ACCUMULATING, DISTRIBUTING, or NEUTRAL
    """
    if len(prices) < lookback + 1 or len(volumes) < lookback + 1:
        return "NEUTRAL"

    # Compute OBV series
    obv = [0]
    for i in range(1, len(prices)):
        if prices[i] > prices[i - 1]:
            obv.append(obv[-1] + volumes[i])
        elif prices[i] < prices[i - 1]:
            obv.append(obv[-1] - volumes[i])
        else:
            obv.append(obv[-1])

    # Compare 7-day trends
    recent_prices = prices[-lookback:]
    recent_obv = obv[-lookback:]

    price_trend = recent_prices[-1] - recent_prices[0]
    obv_trend = recent_obv[-1] - recent_obv[0]

    # Normalize: is price going down/flat while OBV rises?
    price_pct = price_trend / recent_prices[0] if recent_prices[0] != 0 else 0

    if price_pct <= 0.02 and obv_trend > 0:
        return "ACCUMULATING"
    elif price_pct >= -0.02 and obv_trend < 0:
        return "DISTRIBUTING"
    return "NEUTRAL"


# ─── Scoring Engine ───────────────────────────────────────
def score_fear_greed(fg_value):
    """Fear & Greed → opportunity score (inverted). 30% weight."""
    if fg_value <= 10: return 100
    if fg_value <= 20: return 90
    if fg_value <= 30: return 75
    if fg_value <= 40: return 60
    if fg_value <= 50: return 50
    if fg_value <= 60: return 40
    if fg_value <= 70: return 25
    if fg_value <= 80: return 15
    return 5


def score_social_sentiment(overall_sentiment):
    """Contrarian social score. Bearish crowd = opportunity. 15% weight."""
    if overall_sentiment <= 30: return 85
    if overall_sentiment <= 50: return 65
    if overall_sentiment <= 70: return 30
    return 10


def score_btc_dominance(btc_dom):
    """BTC dominance → alt opportunity. Lower dom = better for alts. 25% weight."""
    if btc_dom <= 45: return 90
    if btc_dom <= 50: return 70
    if btc_dom <= 55: return 50
    if btc_dom <= 60: return 30
    return 10


def score_stablecoin_dominance(stable_dom):
    """Higher stablecoin dom = more dry powder. 20% weight."""
    if stable_dom >= 14: return 90
    if stable_dom >= 12: return 75
    if stable_dom >= 10: return 55
    if stable_dom >= 8: return 35
    return 15


def score_regime(fg_value, btc_dom):
    """Market regime: RISK-OFF (contrarian good) / NEUTRAL / RISK-ON. 10% weight."""
    if fg_value <= 35 and btc_dom >= 55:
        return 80, "RISK-OFF"
    elif fg_value >= 55:
        return 25, "RISK-ON"
    return 50, "NEUTRAL"


def compute_market_grade(fg, social_sent, btc_dom, stable_dom):
    """Compute Market Asymmetry Grade from all signals."""
    a = score_fear_greed(fg)
    b = score_social_sentiment(social_sent)
    c = score_btc_dominance(btc_dom)
    d = score_stablecoin_dominance(stable_dom)
    e_score, regime = score_regime(fg, btc_dom)

    asymmetry_score = round(a * 0.30 + b * 0.15 + c * 0.25 + d * 0.20 + e_score * 0.10)

    if asymmetry_score >= 80:
        grade, multiplier = "A+", 1.3
    elif asymmetry_score >= 65:
        grade, multiplier = "A", 1.2
    elif asymmetry_score >= 50:
        grade, multiplier = "B", 1.0
    elif asymmetry_score >= 35:
        grade, multiplier = "C", 0.85
    else:
        grade, multiplier = "D", 0.7

    return {
        "asymmetry_score": asymmetry_score,
        "grade": grade,
        "multiplier": multiplier,
        "regime": regime,
        "components": {"fear_greed": a, "social": b, "btc_dom": c, "stable_dom": d, "regime": e_score},
    }


def score_rsi(rsi):
    """RSI → opportunity score. Oversold = high. 60% weight."""
    if rsi is None: return 50
    if rsi <= 20: return 95
    if rsi <= 30: return 80
    if rsi <= 40: return 65
    if rsi <= 50: return 50
    if rsi <= 60: return 35
    if rsi <= 70: return 20
    return 10


def score_obv(signal):
    """OBV signal → score. 40% weight."""
    if signal == "ACCUMULATING": return 90
    if signal == "DISTRIBUTING": return 10
    return 50


def compute_token_score(rsi, obv_signal, multiplier):
    """Final token composite: (RSI*0.6 + OBV*0.4) × market multiplier"""
    rsi_s = score_rsi(rsi)
    obv_s = score_obv(obv_signal)
    raw = rsi_s * 0.6 + obv_s * 0.4
    composite = min(100, round(raw * multiplier))
    return {
        "rsi_score": rsi_s,
        "obv_score": obv_s,
        "raw_score": round(raw),
        "composite_score": composite,
    }


def signal_label(score):
    if score >= 80: return "🟢 STRONG BUY"
    if score >= 65: return "🟢 ACCUMULATE"
    if score >= 45: return "🟡 NEUTRAL"
    if score >= 30: return "🟠 CAUTION"
    return "🔴 AVOID"


# ─── Adaptive Frequency ──────────────────────────────────
def recommend_frequency(token_scores):
    if not token_scores:
        return "DAILY", "No data"
    max_score = max(t["composite_score"] for t in token_scores)
    if max_score >= 80:
        return "HOURLY", "High-conviction asymmetry detected"
    if max_score >= 65:
        return "4-HOUR", "Signals converging — watch closely"
    if max_score >= 50:
        return "6-HOUR", "Moderate setups forming"
    return "DAILY", "No actionable signals"


# ─── Market Summary ──────────────────────────────────────
def generate_summary(fg, btc_dom, stable_dom, grade_data):
    parts = []
    if fg["value"] <= 30:
        parts.append(f"Fear at {fg['value']} ({fg['label']}) creates buying opportunity backdrop")
    elif fg["value"] >= 60:
        parts.append(f"Greed at {fg['value']} dampens asymmetric setups")
    else:
        parts.append(f"Neutral fear/greed at {fg['value']}")

    if btc_dom >= 58:
        parts.append(f"BTC dominance at {btc_dom}% means capital hasn't rotated to alts yet")
    elif btc_dom <= 48:
        parts.append(f"BTC dominance at {btc_dom}% signals alt rotation underway")

    if stable_dom >= 12:
        parts.append(f"{stable_dom}% stablecoin dominance = significant dry powder on sidelines")
    elif stable_dom < 8:
        parts.append(f"only {stable_dom}% in stables — most capital already deployed")

    return ". ".join(parts) + "."


# ─── Discord Webhook ─────────────────────────────────────
def send_discord_alert(market, btc, token_results, grade_data, freq):
    if not DISCORD_WEBHOOK:
        print("⚠️  No DISCORD_WEBHOOK set, skipping alert")
        return

    # Build embed
    actionable = [t for t in token_results if t["composite_score"] >= ALERT_THRESHOLD]

    grade_emoji = {"A+": "🟢", "A": "🟢", "B": "🟡", "C": "🟠", "D": "🔴"}.get(grade_data["grade"], "⚪")

    # Market conditions field
    market_text = (
        f"**Fear & Greed:** {market['fg']['value']} ({market['fg']['label']})\n"
        f"**BTC:** ${btc['price']:,.0f} ({btc['change_24h']:+.1f}%)\n"
        f"**BTC Dominance:** {market['global']['btc_dominance']}%\n"
        f"**Stablecoin Dom:** {market['global']['stablecoin_dominance']}%\n"
        f"**Regime:** {grade_data['regime']}"
    )

    # Token signals
    token_lines = []
    for t in token_results[:9]:
        label = signal_label(t["composite_score"])
        token_lines.append(
            f"**{t['symbol']}** ${t['price']:.4g} ({t['change_24h']:+.1f}%) "
            f"| RSI {t['rsi'] or '?'} | OBV {t['obv_signal']} | Score **{t['composite_score']}** {label}"
        )

    embed = {
        "title": f"{grade_emoji} SignalScanner — Grade {grade_data['grade']} ({grade_data['asymmetry_score']}/100) — {grade_data['multiplier']}x",
        "description": market.get("summary", ""),
        "color": 0x00FFC8 if grade_data["asymmetry_score"] >= 65 else 0xFFAB00 if grade_data["asymmetry_score"] >= 50 else 0xFF1744,
        "fields": [
            {"name": "📊 Market Conditions", "value": market_text, "inline": False},
            {"name": f"📈 Token Signals ({len(actionable)} actionable)", "value": "\n".join(token_lines), "inline": False},
            {"name": "⏱ Recommended Scan", "value": f"**{freq[0]}** — {freq[1]}", "inline": False},
        ],
        "footer": {"text": f"SignalScanner v5.0 • {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} • Not financial advice"},
    }

    # Add highlight for actionable setups
    if actionable:
        highlight = "\n".join(f"🎯 **{t['symbol']}** — Score {t['composite_score']}, RSI {t['rsi']}, {t['obv_signal']}" for t in actionable)
        embed["fields"].insert(1, {"name": "🔥 Asymmetric Opportunities", "value": highlight, "inline": False})

    payload = json.dumps({"embeds": [embed]}).encode()
    req = Request(DISCORD_WEBHOOK, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(req, timeout=10) as resp:
            print(f"✅ Discord alert sent (status {resp.status})")
    except Exception as e:
        print(f"❌ Discord error: {e}")


# ─── Main Scan ────────────────────────────────────────────
def run_scan():
    print("=" * 60)
    print(f"🔍 SIGNALSCANNER v5.0 — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)

    # 1. Market data
    fg = get_fear_greed()
    print(f"   Fear & Greed: {fg['value']} ({fg['label']})")

    global_data = get_global_data()
    print(f"   BTC Dominance: {global_data['btc_dominance']}%")
    print(f"   Stablecoin Dominance: {global_data['stablecoin_dominance']}%")

    btc = get_btc_price()
    print(f"   BTC Price: ${btc['price']:,.2f} ({btc['change_24h']:+.1f}%)")

    # 2. Token prices
    prices = get_token_prices()
    print(f"   Got prices for {len(prices)} tokens")

    # 3. Market Asymmetry Grade
    # Using Fear & Greed index sentiment as a proxy for overall social sentiment
    # (In production, you'd pull from LunarCrush API with a key)
    social_sentiment = max(20, min(90, 100 - fg["value"]))  # Rough inverse of fear/greed as proxy

    grade_data = compute_market_grade(
        fg["value"], social_sentiment,
        global_data["btc_dominance"], global_data["stablecoin_dominance"]
    )
    print(f"\n   📊 MARKET GRADE: {grade_data['grade']} ({grade_data['asymmetry_score']}/100) → {grade_data['multiplier']}x multiplier")
    print(f"   Regime: {grade_data['regime']}")

    summary = generate_summary(fg, global_data["btc_dominance"], global_data["stablecoin_dominance"], grade_data)
    print(f"   Summary: {summary}")

    # 4. Per-token TA
    print(f"\n📈 Computing technicals for {len(TOKENS)} tokens...")
    token_results = []

    for cg_id, symbol in TOKENS.items():
        print(f"   {symbol}...", end=" ")
        time.sleep(1.5)  # Rate limit CoinGecko free tier

        history_prices, history_volumes = get_market_chart(cg_id, days=30)
        rsi = compute_rsi(history_prices)
        obv_signal = compute_obv_signal(history_prices, history_volumes)
        scores = compute_token_score(rsi, obv_signal, grade_data["multiplier"])

        price_data = prices.get(symbol, {"price": 0, "change_24h": 0})

        result = {
            "symbol": symbol,
            "price": price_data["price"],
            "change_24h": price_data["change_24h"],
            "rsi": rsi,
            "obv_signal": obv_signal,
            **scores,
        }
        token_results.append(result)
        print(f"RSI={rsi or '?'} OBV={obv_signal} Score={scores['composite_score']} {signal_label(scores['composite_score'])}")

    # Sort by composite score
    token_results.sort(key=lambda x: x["composite_score"], reverse=True)

    # 5. Frequency recommendation
    freq = recommend_frequency(token_results)
    print(f"\n⏱  Recommended scan frequency: {freq[0]} — {freq[1]}")

    # 6. Discord alert
    market_data = {"fg": fg, "global": global_data, "summary": summary}
    send_discord_alert(market_data, btc, token_results, grade_data, freq)

    # 7. Save scan results
    scan_result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "market": {
            "fear_greed": fg,
            "btc": btc,
            "btc_dominance": global_data["btc_dominance"],
            "stablecoin_dominance": global_data["stablecoin_dominance"],
            "grade": grade_data,
            "regime": grade_data["regime"],
            "summary": summary,
        },
        "tokens": token_results,
        "frequency": freq[0],
    }

    with open(SCAN_LOG_FILE, "w") as f:
        json.dump(scan_result, f, indent=2)
    print(f"\n💾 Results saved to {SCAN_LOG_FILE}")

    # 8. Print final summary
    print("\n" + "=" * 60)
    actionable = [t for t in token_results if t["composite_score"] >= ALERT_THRESHOLD]
    if actionable:
        print(f"🔥 {len(actionable)} ACTIONABLE SETUP(S):")
        for t in actionable:
            print(f"   {t['symbol']} — Score {t['composite_score']}, RSI {t['rsi']}, {t['obv_signal']}")
    else:
        print("😴 No actionable setups right now")
    print("=" * 60)

    return scan_result


if __name__ == "__main__":
    run_scan()
