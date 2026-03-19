"""
SignalScanner v8 — Asymmetric Opportunity Bot + Risk Thermometer
 
BUY MODEL (unchanged from v7):
  Market Grade: 60% BTC ATH Discount + 40% Fear & Greed + Momentum modifier
  Token Score:  70% ATH Discount + 20% RSI + 10% OBV × Multiplier
 
RISK THERMOMETER (new):
  Signal 1: ATH Proximity        (20%) — how close to ATH
  Signal 2: 50MA Overextension   (20%) — parabolic acceleration
  Signal 3: Fear & Greed         (20%) — sentiment (inverted for risk)
  Signal 4: STH-MVRV Proxy       (20%) — price / 155-day MA
  Gate:     20WMA Regime          (multiplier) — bull/bear trend classifier
 
  0 = DEEP VALUE, 100 = DISTRIBUTION
 
GitHub Actions + Telegram + GitHub Pages dashboard
"""
 
import json, os, time
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.error import HTTPError
 
TOKENS = {
    "ethereum": {"symbol": "ETH", "name": "Ethereum"},
    "chainlink": {"symbol": "LINK", "name": "Chainlink"},
    "ripple": {"symbol": "XRP", "name": "XRP"},
    "iota": {"symbol": "IOTA", "name": "IOTA"},
    "stellar": {"symbol": "XLM", "name": "Stellar"},
    "hedera-hashgraph": {"symbol": "HBAR", "name": "Hedera"},
    "quant-network": {"symbol": "QNT", "name": "Quant"},
    "xdce-crowd-sale": {"symbol": "XDC", "name": "XDC Network"},
    "ondo-finance": {"symbol": "ONDO", "name": "Ondo Finance"},
}
 
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "")
ALERT_THRESHOLD = 65
 
 
def fetch_json(url, retries=3):
    for attempt in range(retries):
        try:
            req = Request(url, headers={"User-Agent": "SignalScanner/8.0", "Accept": "application/json"})
            with urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except HTTPError as e:
            if e.code == 429:
                wait = 30 * (attempt + 1)
                print(f"  Rate limited, waiting {wait}s...")
                time.sleep(wait)
            else:
                print(f"  HTTP {e.code} for {url}")
                if attempt < retries - 1: time.sleep(5)
        except Exception as e:
            print(f"  Error: {e}")
            if attempt < retries - 1: time.sleep(5)
    return None
 
def fmt(v, decimals=0):
    if v is None: return "?"
    return f"{v:.{decimals}f}"
 
 
# ═══════════════════════════════════════════════════════════════
# DATA FETCHING
# ═══════════════════════════════════════════════════════════════
 
def get_fear_greed():
    print("Fetching Fear & Greed...")
    data = fetch_json("https://api.alternative.me/fng/?limit=1")
    if data and "data" in data and data["data"]:
        e = data["data"][0]
        return {"value": int(e["value"]), "label": e["value_classification"]}
    return {"value": 50, "label": "Unknown"}
 
def get_global_data():
    print("Fetching global data...")
    data = fetch_json("https://api.coingecko.com/api/v3/global")
    if data and "data" in data:
        d = data["data"]
        btc_dom = round(d.get("market_cap_percentage", {}).get("btc", 0), 1)
        stable_dom = round(sum(d.get("market_cap_percentage", {}).get(s, 0) for s in ["usdt", "usdc", "dai", "busd"]), 2)
        return {"btc_dominance": btc_dom, "stablecoin_dominance": stable_dom}
    return {"btc_dominance": 55, "stablecoin_dominance": 10}
 
def get_btc_data():
    print("Fetching BTC price + ATH...")
    data = fetch_json("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids=bitcoin&order=market_cap_desc&sparkline=false")
    if data and len(data) > 0:
        coin = data[0]
        return {
            "price": round(coin.get("current_price", 0) or 0, 2),
            "change_24h": round(coin.get("price_change_percentage_24h", 0) or 0, 2),
            "ath": coin.get("ath", 0) or 0,
            "ath_change_pct": round(coin.get("ath_change_percentage", 0) or 0, 1),
        }
    return {"price": 0, "change_24h": 0, "ath": 0, "ath_change_pct": 0}
 
def get_token_data():
    ids = ",".join(TOKENS.keys())
    print(f"Fetching prices + ATH for {len(TOKENS)} tokens...")
    data = fetch_json(f"https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids={ids}&order=market_cap_desc&sparkline=false")
    result = {}
    if data:
        for coin in data:
            cg_id = coin.get("id", "")
            if cg_id in TOKENS:
                sym = TOKENS[cg_id]["symbol"]
                result[sym] = {
                    "price": coin.get("current_price", 0) or 0,
                    "change_24h": round(coin.get("price_change_percentage_24h", 0) or 0, 2),
                    "image": coin.get("image", ""),
                    "ath": coin.get("ath", 0) or 0,
                    "ath_change_pct": round(coin.get("ath_change_percentage", 0) or 0, 1),
                }
    return result
 
def get_market_chart(cg_id, days=200):
    """Fetch price + volume history. 200 days needed for 155MA and 140MA."""
    data = fetch_json(f"https://api.coingecko.com/api/v3/coins/{cg_id}/market_chart?vs_currency=usd&days={days}&interval=daily")
    if data and "prices" in data and "total_volumes" in data:
        p = [x[1] for x in data["prices"]]
        v = [x[1] for x in data["total_volumes"]]
        n = min(len(p), len(v))
        return p[:n], v[:n]
    return [], []
 
 
# ═══════════════════════════════════════════════════════════════
# TECHNICALS (buy model — unchanged)
# ═══════════════════════════════════════════════════════════════
 
def compute_rsi(prices, period=14):
    if len(prices) < period + 1: return None
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        ag = (ag * (period-1) + gains[i]) / period
        al = (al * (period-1) + losses[i]) / period
    if al == 0: return 100.0
    return round(100 - (100 / (1 + ag/al)), 1)
 
def compute_obv_signal(prices, volumes, lookback=7):
    if len(prices) < lookback + 1: return "NEUTRAL"
    obv = [0]
    for i in range(1, len(prices)):
        if prices[i] > prices[i-1]: obv.append(obv[-1] + volumes[i])
        elif prices[i] < prices[i-1]: obv.append(obv[-1] - volumes[i])
        else: obv.append(obv[-1])
    pp = prices[-lookback:]
    oo = obv[-lookback:]
    pct = (pp[-1] - pp[0]) / pp[0] if pp[0] != 0 else 0
    ot = oo[-1] - oo[0]
    if pct <= 0.02 and ot > 0: return "ACCUMULATING"
    elif pct >= -0.02 and ot < 0: return "DISTRIBUTING"
    return "NEUTRAL"
 
def compute_sma(prices, period):
    """Compute simple moving average from the last N prices."""
    if len(prices) < period: return None
    return sum(prices[-period:]) / period
 
 
# ═══════════════════════════════════════════════════════════════
# BUY MODEL — Market Grade (unchanged from v7)
# ═══════════════════════════════════════════════════════════════
 
def score_btc_ath_discount(pct_off):
    d = abs(pct_off)
    if d >= 70: return 100
    if d >= 60: return 95
    if d >= 50: return 88
    if d >= 40: return 78
    if d >= 30: return 65
    if d >= 20: return 50
    if d >= 10: return 30
    if d >= 5: return 15
    return 5
 
def score_fg_buy(v):
    """Fear & Greed for BUY model — high fear = high score (contrarian)."""
    if v <= 10: return 100
    if v <= 20: return 90
    if v <= 25: return 80
    if v <= 30: return 75
    if v <= 40: return 60
    if v <= 50: return 50
    if v <= 60: return 40
    if v <= 70: return 25
    if v <= 80: return 15
    return 5
 
def momentum_modifier(pct_vs_ma):
    if pct_vs_ma >= 3: return 5
    if pct_vs_ma >= 0: return 3
    if pct_vs_ma >= -5: return 0
    if pct_vs_ma >= -15: return -3
    return -5
 
def compute_btc_momentum(prices):
    """Compute 20-day MA momentum from price history."""
    if len(prices) < 20:
        return {"ma20": 0, "current": 0, "pct_vs_ma": 0, "status": "UNKNOWN"}
    ma20 = sum(prices[-20:]) / 20
    current = prices[-1]
    pct_vs_ma = ((current - ma20) / ma20) * 100
    status = "RECOVERING" if pct_vs_ma >= 3 else "STABILIZING" if pct_vs_ma >= 0 else "DIPPING" if pct_vs_ma >= -5 else "FALLING" if pct_vs_ma >= -15 else "FREEFALL"
    return {"ma20": round(ma20, 2), "current": round(current, 2), "pct_vs_ma": round(pct_vs_ma, 1), "status": status}
 
def market_grade(btc_ath_pct, fg_value, btc_momentum):
    btc_s = score_btc_ath_discount(btc_ath_pct)
    fg_s = score_fg_buy(fg_value)
    raw = round(btc_s * 0.60 + fg_s * 0.40)
    mod = momentum_modifier(btc_momentum.get("pct_vs_ma", 0))
    score = max(0, min(100, raw + mod))
    if score >= 80: g, m = "A+", 1.3
    elif score >= 65: g, m = "A", 1.2
    elif score >= 50: g, m = "B", 1.0
    elif score >= 35: g, m = "C", 0.85
    else: g, m = "D", 0.7
    return {"score": score, "grade": g, "multiplier": m, "btc_score": btc_s, "fg_score": fg_s, "momentum_mod": mod, "momentum_status": btc_momentum.get("status", "UNKNOWN")}
 
 
# ═══════════════════════════════════════════════════════════════
# BUY MODEL — Token Scoring (unchanged from v7)
# ═══════════════════════════════════════════════════════════════
 
def score_ath_discount(pct_off):
    d = abs(pct_off)
    if d >= 90: return 100
    if d >= 80: return 92
    if d >= 70: return 82
    if d >= 60: return 72
    if d >= 50: return 60
    if d >= 40: return 48
    if d >= 30: return 35
    if d >= 20: return 22
    if d >= 10: return 12
    return 5
 
def score_rsi(r):
    if r is None: return 50
    if r <= 20: return 95
    if r <= 30: return 80
    if r <= 40: return 65
    if r <= 50: return 50
    if r <= 60: return 35
    if r <= 70: return 20
    return 10
 
def score_obv(s):
    return {"ACCUMULATING": 90, "DISTRIBUTING": 10}.get(s, 50)
 
def token_buy_score(ath_pct, rsi, obv, mult):
    ath_s = score_ath_discount(ath_pct)
    rsi_s = score_rsi(rsi)
    obv_s = score_obv(obv)
    raw = ath_s * 0.70 + rsi_s * 0.20 + obv_s * 0.10
    composite = min(100, round(raw * mult))
    return {"ath_score": ath_s, "rsi_score": rsi_s, "obv_score": obv_s, "raw": round(raw), "composite": composite}
 
def buy_signal_label(s):
    if s >= 80: return "STRONG BUY"
    if s >= 65: return "ACCUMULATE"
    if s >= 45: return "NEUTRAL"
    if s >= 30: return "CAUTION"
    return "AVOID"
 
 
# ═══════════════════════════════════════════════════════════════
# RISK THERMOMETER — 5-Signal Model (NEW in v8)
# ═══════════════════════════════════════════════════════════════
 
# --- Signal 1: ATH Proximity (0=far off, 100=at ATH) ---
def risk_ath_proximity(pct_off_ath):
    d = abs(pct_off_ath)
    if d <= 5: return 100
    if d <= 10: return 80
    if d <= 15: return 60
    if d <= 20: return 45
    if d <= 30: return 25
    if d <= 40: return 12
    if d <= 50: return 5
    return 0
 
# --- Signal 2: 50MA Overextension (0=below MA, 100=parabolic) ---
def risk_50ma_extension(prices):
    ma50 = compute_sma(prices, 50)
    if ma50 is None or ma50 == 0: return 0, None, None
    current = prices[-1]
    pct = ((current - ma50) / ma50) * 100
    if pct >= 30: score = 100
    elif pct >= 20: score = 90
    elif pct >= 15: score = 75
    elif pct >= 10: score = 55
    elif pct >= 5: score = 30
    elif pct >= 0: score = 10
    else: score = 0
    return score, round(ma50, 2), round(pct, 1)
 
# --- Signal 3: Fear & Greed for RISK (0=fear, 100=euphoria) ---
def risk_fg(fg_value):
    if fg_value >= 85: return 100
    if fg_value >= 75: return 80
    if fg_value >= 65: return 55
    if fg_value >= 55: return 35
    if fg_value >= 45: return 18
    if fg_value >= 35: return 8
    return 0
 
# --- Signal 4: STH-MVRV Proxy (price / 155-day SMA) ---
def risk_sth_mvrv(prices):
    ma155 = compute_sma(prices, 155)
    if ma155 is None or ma155 == 0: return 0, None, None
    current = prices[-1]
    ratio = current / ma155
    if ratio >= 1.40: score = 100
    elif ratio >= 1.30: score = 85 + (ratio - 1.30) / 0.10 * 15
    elif ratio >= 1.10: score = 55 + (ratio - 1.10) / 0.20 * 30
    elif ratio >= 0.95: score = 35 + (ratio - 0.95) / 0.15 * 20
    elif ratio >= 0.90: score = 15 + (ratio - 0.90) / 0.05 * 20
    else: score = max(0, ratio / 0.90 * 15)
    return round(min(100, max(0, score))), round(ma155, 2), round(ratio, 3)
 
# --- Signal 5 (Gate): 20-Week MA Regime ---
def compute_regime(prices):
    """Classify bull/bear regime using 140-day (20-week) MA."""
    if len(prices) < 147:  # need 140 + 7 for slope check
        return {"regime": "unknown", "multiplier": 1.0, "ma140": None, "ma140_rising": None}
    ma140_now = sum(prices[-140:]) / 140
    ma140_7d_ago = sum(prices[-147:-7]) / 140
    rising = ma140_now > ma140_7d_ago
    above = prices[-1] > ma140_now
    if above and rising:
        regime, mult = "bull_strong", 0.6
    elif above and not rising:
        regime, mult = "bull_weak", 0.85
    elif not above and rising:
        regime, mult = "bear_weak", 1.15
    else:
        regime, mult = "bear_strong", 1.3
    return {"regime": regime, "multiplier": mult, "ma140": round(ma140_now, 2), "ma140_rising": rising}
 
# --- Composite Risk Score ---
def compute_risk_thermometer(ath_pct, prices, fg_value):
    """Compute the 5-signal risk thermometer. Returns dict with all components."""
    s1 = risk_ath_proximity(ath_pct)
    s2, ma50, pct_50ma = risk_50ma_extension(prices)
    s3 = risk_fg(fg_value)
    s4, ma155, sth_ratio = risk_sth_mvrv(prices)
    regime = compute_regime(prices)
 
    composite_raw = round(s1 * 0.25 + s2 * 0.25 + s3 * 0.25 + s4 * 0.25)
    composite_final = max(0, min(100, round(composite_raw * regime["multiplier"])))
 
    if composite_final <= 20: label = "DEEP VALUE"
    elif composite_final <= 35: label = "ACCUMULATION"
    elif composite_final <= 50: label = "NEUTRAL"
    elif composite_final <= 65: label = "WARMING"
    elif composite_final <= 80: label = "ELEVATED"
    else: label = "DISTRIBUTION"
 
    return {
        "ath_proximity_score": s1,
        "ma50_extension_score": s2,
        "ma50_value": ma50,
        "pct_vs_50ma": pct_50ma,
        "fg_risk_score": s3,
        "sth_mvrv_score": s4,
        "sth_mvrv_ratio": sth_ratio,
        "ma155_value": ma155,
        "regime": regime["regime"],
        "regime_multiplier": regime["multiplier"],
        "ma140_value": regime["ma140"],
        "ma140_rising": regime["ma140_rising"],
        "composite_raw": composite_raw,
        "composite_final": composite_final,
        "label": label,
    }
 
 
# ═══════════════════════════════════════════════════════════════
# SCAN FREQUENCY
# ═══════════════════════════════════════════════════════════════
 
def recommend_freq(tokens):
    if not tokens: return "DAILY", "No data"
    mx = max(t["composite"] for t in tokens)
    if mx >= 80: return "HOURLY", "High-conviction asymmetry"
    if mx >= 65: return "4-HOUR", "Signals converging"
    if mx >= 50: return "6-HOUR", "Moderate setups"
    return "DAILY", "No actionable signals"
 
 
# ═══════════════════════════════════════════════════════════════
# ANALYSIS TEXT
# ═══════════════════════════════════════════════════════════════
 
def generate_analysis(fg, btc, gd, grade, btc_mom, btc_risk, tokens):
    actionable = [t for t in tokens if t["composite"] >= ALERT_THRESHOLD]
    btc_off = abs(btc.get("ath_change_pct", 0))
    lines = []
 
    # BTC cycle position
    if btc_off >= 50:
        lines.append(f"Bitcoin is {btc_off:.0f}% off its ${btc['ath']:,.0f} cycle high. Deep bear territory.")
    elif btc_off >= 30:
        lines.append(f"Bitcoin is {btc_off:.0f}% off its ${btc['ath']:,.0f} cycle high. Significant correction.")
    elif btc_off >= 15:
        lines.append(f"Bitcoin is {btc_off:.0f}% off its high. Meaningful pullback.")
    else:
        lines.append(f"Bitcoin is only {btc_off:.0f}% off its high. Limited asymmetry.")
 
    # Momentum
    mom_status = btc_mom.get("status", "UNKNOWN")
    pct_ma = btc_mom.get("pct_vs_ma", 0)
    if mom_status in ("RECOVERING", "STABILIZING"):
        lines.append(f"BTC is {pct_ma:+.1f}% vs 20MA. Bleeding has stopped.")
    elif mom_status in ("FALLING", "FREEFALL"):
        lines.append(f"BTC is {abs(pct_ma):.1f}% below its 20MA and still falling. Consider waiting for stabilization.")
 
    # Risk thermometer
    rl = btc_risk["label"]
    rs = btc_risk["composite_final"]
    reg = btc_risk["regime"].replace("_", " ").upper()
    lines.append(f"Risk thermometer: {rs}/100 ({rl}). Regime: {reg}.")
 
    if btc_risk["sth_mvrv_ratio"]:
        r = btc_risk["sth_mvrv_ratio"]
        if r < 0.90:
            lines.append(f"STH-MVRV proxy at {r:.2f} — recent buyers deeply underwater. Capitulation zone.")
        elif r < 1.0:
            lines.append(f"STH-MVRV proxy at {r:.2f} — recent buyers in loss. Selling exhaustion likely.")
        elif r > 1.30:
            lines.append(f"STH-MVRV proxy at {r:.2f} — recent buyers up 30%+. Profit-taking pressure building.")
 
    # Fear context
    if fg["value"] <= 20:
        lines.append(f"Extreme fear at {fg['value']}. Historically the best time to accumulate.")
    elif fg["value"] >= 70:
        lines.append(f"Greed at {fg['value']}. Worst time for new positions.")
 
    # Token landscape
    if actionable:
        names = ", ".join(t["symbol"] for t in actionable)
        lines.append(f"BOTTOM LINE: {len(actionable)} actionable — {names}.")
    else:
        lines.append("BOTTOM LINE: No actionable buy setups right now.")
 
    return " ".join(lines)
 
 
def gen_summary(fg, btc_off, mom_status, risk_label, risk_score):
    parts = []
    parts.append(f"Risk {risk_score}/100 ({risk_label})")
    parts.append(f"BTC {btc_off:.0f}% off ATH")
    if fg["value"] <= 30: parts.append(f"F&G {fg['value']} (fear)")
    elif fg["value"] >= 60: parts.append(f"F&G {fg['value']} (greed)")
    return ". ".join(parts) + "."
 
 
# ═══════════════════════════════════════════════════════════════
# TELEGRAM
# ═══════════════════════════════════════════════════════════════
 
def send_telegram(fg, btc, grade, btc_risk, tokens, freq, summary):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("No Telegram credentials, skipping")
        return
    actionable = [t for t in tokens if t["composite"] >= ALERT_THRESHOLD]
    rs = btc_risk["composite_final"]
    rl = btc_risk["label"]
 
    if grade["score"] >= 65: dot = "\U0001f7e2"
    elif grade["score"] >= 50: dot = "\U0001f7e1"
    elif grade["score"] >= 35: dot = "\U0001f7e0"
    else: dot = "\U0001f534"
 
    # Risk dot (inverted — low risk = green)
    if rs <= 30: rdot = "\U0001f7e2"
    elif rs <= 50: rdot = "\U0001f7e1"
    elif rs <= 70: rdot = "\U0001f7e0"
    else: rdot = "\U0001f534"
 
    token_preview = " \u00b7 ".join(f"{t['symbol']} {t['composite']}" for t in tokens[:5])
    msg = f"""{dot} <b>Buy Grade {grade['grade']}</b> \u00b7 {grade['score']}/100
{rdot} <b>Risk {rs}</b> \u00b7 {rl} \u00b7 {btc_risk['regime'].replace('_',' ')}
{token_preview}"""
 
    if actionable:
        targets = " ".join(f"\u26a1{t['symbol']}" for t in actionable)
        msg += f"\n\n\U0001f525 <b>TARGETS:</b> {targets}"
 
    if rs >= 70:
        msg += f"\n\n\U0001f534 <b>RISK ELEVATED</b> \u2014 consider trimming"
 
    if DASHBOARD_URL:
        msg += f'\n\n\U0001f449 <a href="{DASHBOARD_URL}">Open Dashboard</a>'
 
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": True}).encode()
    req = Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(req, timeout=10) as resp:
            print(f"Telegram sent (status {resp.status})")
    except Exception as e:
        print(f"Telegram error: {e}")
 
 
# ═══════════════════════════════════════════════════════════════
# DASHBOARD
# ═══════════════════════════════════════════════════════════════
 
def generate_dashboard(fg, btc, gd, grade, btc_mom, btc_risk, tokens, freq, summary, analysis, scan_time):
    actionable = [t for t in tokens if t["composite"] >= ALERT_THRESHOLD]
 
    def sc(s):
        if s >= 80: return "#00ffc8"
        if s >= 65: return "#7ae8c4"
        if s >= 45: return "#d4a853"
        if s >= 30: return "#d47a53"
        return "#e84057"
    def cc(v): return "#00ffc8" if v >= 0 else "#e84057"
    def oc(s):
        if s == "ACCUMULATING": return "#00ffc8"
        if s == "DISTRIBUTING": return "#e84057"
        return "#555d75"
    def fp(p):
        if not p: return "?"
        if p >= 100: return f"${p:,.2f}"
        if p >= 1: return f"${p:.2f}"
        return f"${p:.4f}"
    def dsc(pct):
        d = abs(pct)
        if d >= 80: return "#00ffc8"
        if d >= 60: return "#7ae8c4"
        if d >= 40: return "#d4a853"
        return "#d47a53"
 
    # Risk thermometer colors (inverted — low = green/good, high = red/danger)
    def rc(s):
        if s <= 20: return "#00ffc8"
        if s <= 35: return "#7ae8c4"
        if s <= 50: return "#d4a853"
        if s <= 65: return "#d47a53"
        return "#e84057"
 
    gc = sc(grade["score"])
    btc_off = abs(btc.get("ath_change_pct", 0))
    rs = btc_risk["composite_final"]
    risk_color = rc(rs)
    rl = btc_risk["label"]
    regime_display = btc_risk["regime"].replace("_", " ").upper()
    regime_color = "#00ffc8" if "bull" in btc_risk["regime"] else "#e84057"
 
    # Momentum display
    mom_status = btc_mom.get("status", "UNKNOWN")
    mom_pct = btc_mom.get("pct_vs_ma", 0)
    mom_color = "#00ffc8" if mom_status in ("RECOVERING", "STABILIZING") else "#d4a853" if mom_status == "DIPPING" else "#e84057"
    mom_arrow = "\u25b2" if mom_pct >= 0 else "\u25bc"
    mom_label = f"{mom_arrow} {mom_status}"
 
    # Token cards
    cards = ""
    for i, t in enumerate(tokens):
        tc = sc(t["composite"])
        chc = cc(t["change_24h"])
        obc = oc(t["obv_signal"])
        arrow = "\u25b2" if t["change_24h"] >= 0 else "\u25bc"
        label = buy_signal_label(t["composite"])
        rp = (t["rsi"] / 100 * 100) if t["rsi"] else 50
        rsi_display = fmt(t["rsi"])
        ol = "ACCUM" if t["obv_signal"] == "ACCUMULATING" else "DISTR" if t["obv_signal"] == "DISTRIBUTING" else "FLAT"
        img_html = f'<img class="ci-img" src="{t["image"]}" onerror="this.style.display=\'none\'">' if t.get("image") else ""
        cg_id = ""
        for k, v in TOKENS.items():
            if v["symbol"] == t["symbol"]:
                cg_id = k
                break
        name = TOKENS.get(cg_id, {}).get("name", t["symbol"])
        fb_letters = t["symbol"][:2]
        border_color = "rgba(0,255,200,0.15)" if t["composite"] >= 65 else "rgba(26,37,64,0.8)"
        ath_pct = abs(t.get("ath_change_pct", 0))
        ath_val = t.get("ath", 0)
        ath_c = dsc(t.get("ath_change_pct", 0))
        ath_bar_w = min(100, ath_pct)
        ath_price = fp(ath_val) if ath_val else "?"
 
        # Token risk
        tr = t.get("risk", {})
        tr_score = tr.get("composite_final", 0)
        tr_label = tr.get("label", "?")
        tr_color = rc(tr_score)
 
        cards += f'''
        <div class="tc" style="animation-delay:{i*0.06}s;border-color:{border_color}">
          <div class="th">
            <div class="thl">
              <div class="coin-wrap"><div class="coin-fb" style="background:#131f2e;color:{tc}">{fb_letters}</div>{img_html}</div>
              <div><span class="ts" style="color:{tc}">{t["symbol"]}</span> <span class="tn">{name}</span></div>
            </div>
            <div class="tb" style="color:{tc};background:{tc}18;border-color:{tc}33">{label}</div>
          </div>
          <div class="tp">
            <span class="pv">{fp(t["price"])}</span>
            <span class="pc" style="color:{chc}">{arrow} {t["change_24h"]:+.1f}%</span>
          </div>
          <div class="ath-row">
            <div class="ath-label">ATH DISCOUNT</div>
            <div class="ath-bar-bg"><div class="ath-bar" style="width:{ath_bar_w}%;background:{ath_c}"></div></div>
            <div class="ath-val" style="color:{ath_c}">{ath_pct:.0f}% off</div>
          </div>
          <div class="ath-detail">ATH {ath_price}</div>
          <div class="tm">
            <div class="m"><div class="mla">RSI</div><div class="mbg"><div class="mb" style="width:{rp}%;background:{tc}"></div></div><div class="mval" style="color:{tc}">{rsi_display}</div></div>
            <div class="m"><div class="mla">OBV</div><div class="mval" style="color:{obc}">{ol}</div></div>
            <div class="m"><div class="mla">BUY</div><div class="mval sb" style="color:{tc}">{t["composite"]}</div></div>
            <div class="m"><div class="mla">RISK</div><div class="mval" style="color:{tr_color};font-size:13px">{tr_score}</div></div>
          </div>
        </div>'''
 
    # Targets section
    tgt = ""
    if actionable:
        items = ""
        for t in actionable:
            tc = sc(t["composite"])
            rsi_display = fmt(t["rsi"])
            ath_pct = abs(t.get("ath_change_pct", 0))
            items += f'<div class="ti"><span class="tis" style="color:{tc}">{t["symbol"]}</span><span class="tic" style="color:{tc}">Score {t["composite"]}</span><span class="tid">{ath_pct:.0f}% off ATH \u00b7 RSI {rsi_display}</span></div>'
        tgt = f'<div class="sl" style="color:#00ffc8">\u26a1 TARGETS DETECTED</div><div class="tg2">{items}</div>'
 
    fc = "#e84057" if fg["value"]<=25 else "#d47a53" if fg["value"]<=45 else "#d4a853" if fg["value"]<=55 else "#7ae8c4" if fg["value"]<=75 else "#00ffc8"
    btc_disc_color = dsc(btc.get("ath_change_pct", 0))
 
    # Risk thermometer bar segments
    risk_bar_pos = min(100, max(0, rs))
 
    # STH-MVRV display
    sth_ratio = btc_risk.get("sth_mvrv_ratio")
    sth_display = f"{sth_ratio:.2f}x" if sth_ratio else "?"
    sth_color = "#e84057" if sth_ratio and sth_ratio > 1.3 else "#d4a853" if sth_ratio and sth_ratio > 1.1 else "#00ffc8" if sth_ratio and sth_ratio < 0.95 else "#7ae8c4"
 
    analysis_safe = analysis.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
 
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>SignalScanner</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#060a14;color:#c8cfe0;font-family:'Outfit',sans-serif;min-height:100vh;padding:20px 16px}}
.ctr{{max-width:520px;margin:0 auto}}
.hdr{{text-align:center;margin-bottom:28px}}
.logo{{font-size:11px;letter-spacing:6px;color:#3d465e;font-family:'JetBrains Mono',monospace;margin-bottom:6px}}
.dual{{display:flex;justify-content:center;gap:24px;margin:16px 0}}
.ring{{width:90px;height:90px;border-radius:50%;border:3px solid {gc};display:flex;flex-direction:column;align-items:center;justify-content:center;background:{gc}0a;box-shadow:0 0 20px {gc}15}}
.ring-r{{width:90px;height:90px;border-radius:50%;border:3px solid {risk_color};display:flex;flex-direction:column;align-items:center;justify-content:center;background:{risk_color}0a;box-shadow:0 0 20px {risk_color}15}}
.gl{{font-size:28px;font-weight:900;font-family:'JetBrains Mono',monospace}}
.gl-sub{{font-size:8px;letter-spacing:2px;color:#5a6480;font-family:'JetBrains Mono',monospace;margin-top:2px}}
.gm{{font-size:12px;color:#8892a8;margin-top:8px;font-family:'JetBrains Mono',monospace}}
.gm b{{color:{gc}}}
.sum{{font-size:13px;color:#5a6480;line-height:1.6;margin-top:10px;font-style:italic;max-width:400px;margin-left:auto;margin-right:auto}}
.st{{font-size:10px;color:#2a3045;margin-top:10px;font-family:'JetBrains Mono',monospace;letter-spacing:1px}}
.thermo{{margin:16px 0;background:linear-gradient(145deg,#0c1222,#101828);border:1px solid #1a2540;border-radius:14px;padding:16px}}
.thermo-title{{font-size:9px;letter-spacing:2px;color:#3d465e;font-family:'JetBrains Mono',monospace;margin-bottom:10px;text-align:center}}
.thermo-bar{{height:8px;background:#151d30;border-radius:4px;position:relative;overflow:visible;margin:0 4px}}
.thermo-fill{{height:100%;border-radius:4px;background:linear-gradient(90deg,#00ffc8 0%,#7ae8c4 25%,#d4a853 50%,#d47a53 75%,#e84057 100%);opacity:0.3}}
.thermo-marker{{position:absolute;top:-4px;width:4px;height:16px;background:{risk_color};border-radius:2px;left:{risk_bar_pos}%;transform:translateX(-50%);box-shadow:0 0 8px {risk_color}88}}
.thermo-labels{{display:flex;justify-content:space-between;margin-top:6px;font-size:8px;font-family:'JetBrains Mono',monospace;color:#3d465e;letter-spacing:0.5px}}
.thermo-reading{{text-align:center;margin-top:10px;font-family:'JetBrains Mono',monospace}}
.thermo-score{{font-size:28px;font-weight:800;color:{risk_color}}}
.thermo-label{{font-size:11px;color:{risk_color};letter-spacing:2px;margin-top:2px}}
.regime-badge{{display:inline-block;font-size:9px;letter-spacing:1.5px;padding:4px 12px;border-radius:6px;border:1px solid {regime_color}33;background:{regime_color}12;color:{regime_color};font-family:'JetBrains Mono',monospace;margin-top:8px}}
.risk-signals{{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:12px}}
.rs{{text-align:center;padding:8px;background:#0a1018;border-radius:8px}}
.rs-l{{font-size:7px;letter-spacing:1.5px;color:#3d465e;font-family:'JetBrains Mono',monospace}}
.rs-v{{font-size:16px;font-weight:700;font-family:'JetBrains Mono',monospace;margin-top:2px}}
.aw{{margin:16px 0;text-align:center}}
.ab-btn{{background:rgba(255,255,255,0.04);border:1px solid #1a2540;color:#5a6480;padding:10px 20px;border-radius:10px;font-size:12px;font-family:'JetBrains Mono',monospace;cursor:pointer;letter-spacing:1px;transition:all 0.2s}}
.ab-btn:hover{{border-color:#3d465e;color:#8892a8}}
.ab-body{{display:none;text-align:left;background:linear-gradient(145deg,#0c1222,#101828);border:1px solid #1a2540;border-radius:14px;padding:20px;margin-top:12px;font-size:13px;color:#7a84a0;line-height:1.8}}
.ab-body.open{{display:block}}
.sl{{font-size:10px;letter-spacing:3px;color:#3d465e;font-family:'JetBrains Mono',monospace;font-weight:600;margin:24px 0 12px;padding-bottom:8px;border-bottom:1px solid #111827}}
.mg{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}
.mc{{background:linear-gradient(145deg,#0c1222,#101828);border:1px solid #1a2540;border-radius:14px;padding:14px;text-align:center}}
.mc.w{{grid-column:1/-1}}
.ml{{font-size:9px;letter-spacing:2px;color:#3d465e;font-family:'JetBrains Mono',monospace;margin-bottom:6px}}
.mv{{font-size:22px;font-weight:800;font-family:'JetBrains Mono',monospace}}
.ms{{font-size:10px;color:#3d465e;margin-top:3px;font-family:'JetBrains Mono',monospace;letter-spacing:1px}}
.tg2{{display:flex;flex-direction:column;gap:8px;margin-bottom:8px}}
.ti{{background:#00ffc808;border:1px solid #00ffc820;border-radius:10px;padding:12px 16px;display:flex;align-items:center;gap:12px}}
.tis{{font-weight:800;font-size:16px;font-family:'JetBrains Mono',monospace}}
.tic{{font-weight:700;font-size:13px;font-family:'JetBrains Mono',monospace}}
.tid{{font-size:11px;color:#5a6480;margin-left:auto}}
.tg{{display:flex;flex-direction:column;gap:8px}}
.tc{{background:linear-gradient(145deg,#0c1222,#101828);border:1px solid #1a2540;border-radius:14px;padding:16px;animation:si 0.3s ease both}}
@keyframes si{{from{{opacity:0;transform:translateY(8px)}}to{{opacity:1;transform:translateY(0)}}}}
.th{{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}}
.thl{{display:flex;align-items:center;gap:10px}}
.coin-wrap{{width:32px;height:32px;border-radius:50%;position:relative;flex-shrink:0}}
.ci-img{{width:32px;height:32px;border-radius:50%;position:absolute;top:0;left:0;object-fit:contain;z-index:2}}
.coin-fb{{width:32px;height:32px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:800;font-family:'JetBrains Mono',monospace;position:absolute;top:0;left:0;z-index:1}}
.ts{{font-size:18px;font-weight:800;font-family:'JetBrains Mono',monospace}}
.tn{{font-size:11px;color:#555d75;font-weight:400}}
.tb{{font-size:9px;font-weight:700;letter-spacing:1px;padding:4px 10px;border-radius:6px;border:1px solid;font-family:'JetBrains Mono',monospace}}
.tp{{display:flex;align-items:baseline;gap:10px;margin-bottom:8px}}
.pv{{font-size:15px;font-weight:600;color:#e8ecf4;font-family:'JetBrains Mono',monospace}}
.pc{{font-size:12px;font-weight:600;font-family:'JetBrains Mono',monospace}}
.ath-row{{display:flex;align-items:center;gap:8px;margin-bottom:4px}}
.ath-label{{font-size:8px;letter-spacing:1.5px;color:#3d465e;font-family:'JetBrains Mono',monospace;min-width:80px}}
.ath-bar-bg{{height:6px;background:#151d30;border-radius:3px;flex:1;overflow:hidden}}
.ath-bar{{height:100%;border-radius:3px}}
.ath-val{{font-size:13px;font-weight:700;font-family:'JetBrains Mono',monospace;min-width:65px;text-align:right}}
.ath-detail{{font-size:10px;color:#2a3045;font-family:'JetBrains Mono',monospace;margin-bottom:12px}}
.tm{{display:grid;grid-template-columns:1fr auto auto auto;gap:10px;align-items:center}}
.m{{text-align:center}}
.m:first-child{{text-align:left;display:flex;align-items:center;gap:8px}}
.mla{{font-size:8px;letter-spacing:1.5px;color:#3d465e;font-family:'JetBrains Mono',monospace;margin-bottom:2px}}
.m:first-child .mla{{margin-bottom:0;min-width:22px}}
.mbg{{height:4px;background:#151d30;border-radius:2px;flex:1;min-width:60px;overflow:hidden}}
.mb{{height:100%;border-radius:2px}}
.mval{{font-size:14px;font-weight:700;font-family:'JetBrains Mono',monospace}}
.sb{{font-size:18px;font-weight:800}}
.fb{{background:linear-gradient(145deg,#0c1222,#101828);border:1px solid #1a2540;border-radius:14px;padding:14px 20px;margin-top:20px;display:flex;justify-content:space-between;align-items:center}}
.fl{{font-size:10px;color:#3d465e;letter-spacing:2px;font-family:'JetBrains Mono',monospace}}
.fv{{font-size:14px;font-weight:700;color:#5a6480;font-family:'JetBrains Mono',monospace}}
.ft{{text-align:center;margin-top:28px;font-size:9px;color:#1a2540;letter-spacing:1.5px;font-family:'JetBrains Mono',monospace}}
</style>
</head>
<body>
<div class="ctr">
  <div class="hdr">
    <div class="logo">SIGNAL SCANNER</div>
    <div class="dual">
      <div>
        <div class="ring"><div class="gl" style="color:{gc}">{grade["grade"]}</div><div class="gl-sub">BUY</div></div>
      </div>
      <div>
        <div class="ring-r"><div class="gl" style="color:{risk_color}">{rs}</div><div class="gl-sub">RISK</div></div>
      </div>
    </div>
    <div class="gm">Buy <b>{grade["score"]}</b>/100 \u00b7 {grade["multiplier"]}x &nbsp;|&nbsp; Risk <b style="color:{risk_color}">{rs}</b>/100 \u00b7 {rl}</div>
    <div class="sum">{summary}</div>
    <div class="st">{scan_time}</div>
  </div>
 
  <div class="thermo">
    <div class="thermo-title">RISK THERMOMETER</div>
    <div class="thermo-bar">
      <div class="thermo-fill"></div>
      <div class="thermo-marker"></div>
    </div>
    <div class="thermo-labels"><span>DEEP VALUE</span><span>ACCUMULATE</span><span>NEUTRAL</span><span>WARMING</span><span>ELEVATED</span><span>DISTRIB</span></div>
    <div class="thermo-reading">
      <div class="thermo-score">{rs}</div>
      <div class="thermo-label">{rl}</div>
      <div class="regime-badge">{regime_display}</div>
    </div>
    <div class="risk-signals">
      <div class="rs"><div class="rs-l">ATH PROX</div><div class="rs-v" style="color:{rc(btc_risk['ath_proximity_score'])}">{btc_risk['ath_proximity_score']}</div></div>
      <div class="rs"><div class="rs-l">50MA EXT</div><div class="rs-v" style="color:{rc(btc_risk['ma50_extension_score'])}">{btc_risk['ma50_extension_score']}</div></div>
      <div class="rs"><div class="rs-l">F&amp;G RISK</div><div class="rs-v" style="color:{rc(btc_risk['fg_risk_score'])}">{btc_risk['fg_risk_score']}</div></div>
      <div class="rs"><div class="rs-l">STH-MVRV</div><div class="rs-v" style="color:{rc(btc_risk['sth_mvrv_score'])}">{btc_risk['sth_mvrv_score']}</div></div>
    </div>
  </div>
 
  <div class="aw">
    <button class="ab-btn" id="abtn" onclick="var b=document.getElementById('abody');b.classList.toggle('open');document.getElementById('abtn').textContent=b.classList.contains('open')?'\\u25b4 HIDE ANALYSIS':'\\u25be MARKET ANALYSIS'">&#9662; MARKET ANALYSIS</button>
    <div class="ab-body" id="abody">{analysis_safe}</div>
  </div>
 
  <div class="sl">MARKET CONDITIONS</div>
  <div class="mg">
    <div class="mc">
      <div class="ml">&#8383; BTC vs ATH</div>
      <div class="mv" style="color:{btc_disc_color}">{btc_off:.0f}% off</div>
      <div class="ms">${btc["price"]:,.0f} &middot; ATH ${btc["ath"]:,.0f}</div>
    </div>
    <div class="mc">
      <div class="ml">&#129504; FEAR &amp; GREED</div>
      <div class="mv" style="color:{fc}">{fg["value"]}</div>
      <div class="ms">{fg["label"].upper()}</div>
    </div>
    <div class="mc">
      <div class="ml">&#128200; BTC MOMENTUM</div>
      <div class="mv" style="color:{mom_color};font-size:18px">{mom_label}</div>
      <div class="ms">20MA ${btc_mom['ma20']:,.0f} &middot; {mom_pct:+.1f}%</div>
    </div>
    <div class="mc">
      <div class="ml">&#128201; STH-MVRV PROXY</div>
      <div class="mv" style="color:{sth_color};font-size:18px">{sth_display}</div>
      <div class="ms">155MA ${btc_risk.get('ma155_value',0):,.0f}</div>
    </div>
  </div>
 
  {tgt}
 
  <div class="sl">UTILITY TOKEN SIGNALS &middot; {len(actionable)} ACTIONABLE</div>
  <div class="tg">{cards}</div>
 
  <div class="fb">
    <div class="fl">&#9201; NEXT SCAN</div>
    <div class="fv">{freq[0]} &middot; {freq[1]}</div>
  </div>
  <div class="ft">SIGNALSCANNER v8.0 &middot; NOT FINANCIAL ADVICE</div>
</div>
</body>
</html>'''
    return html
 
 
# ═══════════════════════════════════════════════════════════════
# ADAPTIVE FREQUENCY
# ═══════════════════════════════════════════════════════════════
 
def should_run():
    try:
        with open("docs/data.json", "r") as f:
            last = json.load(f)
        last_time = datetime.fromisoformat(last["timestamp"])
        freq = last.get("frequency", "DAILY")
        now = datetime.now(timezone.utc)
        hours_since = (now - last_time).total_seconds() / 3600
        if freq == "HOURLY": return True
        if freq == "4-HOUR" and hours_since >= 4: return True
        if freq == "6-HOUR" and hours_since >= 6: return True
        if freq == "DAILY" and hours_since >= 24: return True
        print(f"Skipping \u2014 last scan {hours_since:.1f}h ago, frequency is {freq}")
        return False
    except Exception:
        return True
 
 
# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
 
def run_scan():
    scan_time = datetime.now(timezone.utc).strftime("%b %d, %Y \u00b7 %H:%M UTC")
    print(f"SIGNALSCANNER v8.0 - {scan_time}\n")
 
    # --- Fetch market data ---
    fg = get_fear_greed()
    print(f"  Fear & Greed: {fg['value']} ({fg['label']})")
 
    gd = get_global_data()
    print(f"  BTC Dom: {gd['btc_dominance']}% | Stable Dom: {gd['stablecoin_dominance']}%")
 
    time.sleep(1.5)
    btc = get_btc_data()
    btc_off = abs(btc.get("ath_change_pct", 0))
    print(f"  BTC: ${btc['price']:,.2f} ({btc['change_24h']:+.1f}%) | ATH ${btc['ath']:,.0f} | {btc_off:.1f}% off")
 
    # --- Fetch BTC 200-day history (for momentum + risk thermometer) ---
    time.sleep(1.5)
    print("Fetching BTC 200-day history...")
    btc_prices, btc_volumes = get_market_chart("bitcoin", 200)
    print(f"  Got {len(btc_prices)} daily prices")
 
    btc_mom = compute_btc_momentum(btc_prices)
    print(f"  Momentum: {btc_mom['status']} ({btc_mom['pct_vs_ma']:+.1f}% vs 20MA)")
 
    # --- BTC Risk Thermometer ---
    btc_risk = compute_risk_thermometer(btc.get("ath_change_pct", 0), btc_prices, fg["value"])
    print(f"  Risk: {btc_risk['composite_final']}/100 ({btc_risk['label']}) | Regime: {btc_risk['regime']} ({btc_risk['regime_multiplier']}x)")
    if btc_risk["sth_mvrv_ratio"]:
        print(f"  STH-MVRV proxy: {btc_risk['sth_mvrv_ratio']:.3f} | 155MA: ${btc_risk['ma155_value']:,.0f}")
    if btc_risk["ma140_value"]:
        print(f"  140MA (20WMA): ${btc_risk['ma140_value']:,.0f} | Rising: {btc_risk['ma140_rising']}")
 
    # --- Buy-side market grade ---
    grade = market_grade(btc.get("ath_change_pct", 0), fg["value"], btc_mom)
    print(f"  Buy Grade: {grade['grade']} ({grade['score']}/100) -> {grade['multiplier']}x")
 
    summary = gen_summary(fg, btc_off, btc_mom.get("status", "UNKNOWN"), btc_risk["label"], btc_risk["composite_final"])
 
    # --- Fetch token data ---
    time.sleep(1.5)
    token_data = get_token_data()
    print(f"  Got {len(token_data)} token prices")
 
    print(f"\nComputing token technicals + risk...")
    tokens = []
    for cg_id, info in TOKENS.items():
        sym = info["symbol"]
        print(f"  {sym}...", end=" ")
        time.sleep(1.5)
        hp, hv = get_market_chart(cg_id, 200)
        rsi = compute_rsi(hp)
        obv = compute_obv_signal(hp, hv)
        td = token_data.get(sym, {"price": 0, "change_24h": 0, "image": "", "ath": 0, "ath_change_pct": 0})
 
        # Buy score
        scores = token_buy_score(td.get("ath_change_pct", 0), rsi, obv, grade["multiplier"])
 
        # Token-level risk thermometer
        token_risk = compute_risk_thermometer(td.get("ath_change_pct", 0), hp, fg["value"]) if len(hp) >= 50 else {"composite_final": 0, "label": "?", "regime": "unknown", "sth_mvrv_ratio": None}
 
        tokens.append({
            "symbol": sym,
            "price": td["price"],
            "change_24h": td["change_24h"],
            "image": td.get("image", ""),
            "ath": td.get("ath", 0),
            "ath_change_pct": td.get("ath_change_pct", 0),
            "rsi": rsi,
            "obv_signal": obv,
            "ath_score": scores["ath_score"],
            "rsi_score": scores["rsi_score"],
            "obv_score": scores["obv_score"],
            "raw_score": scores["raw"],
            "composite": scores["composite"],
            "risk": token_risk,
        })
        ath_off_t = abs(td.get("ath_change_pct", 0))
        tr = token_risk.get("composite_final", 0)
        print(f"ATH -{ath_off_t:.0f}% RSI={fmt(rsi)} OBV={obv} Buy={scores['composite']} Risk={tr}")
 
    tokens.sort(key=lambda x: x["composite"], reverse=True)
    freq = recommend_freq(tokens)
    print(f"\n  Scan frequency: {freq[0]} - {freq[1]}")
 
    analysis = generate_analysis(fg, btc, gd, grade, btc_mom, btc_risk, tokens)
    print(f"  Analysis: {analysis[:120]}...")
 
    # --- Write dashboard ---
    os.makedirs("docs", exist_ok=True)
    html = generate_dashboard(fg, btc, gd, grade, btc_mom, btc_risk, tokens, freq, summary, analysis, scan_time)
    with open("docs/index.html", "w") as f:
        f.write(html)
    print("  Dashboard written to docs/index.html")
 
    # --- Send Telegram ---
    send_telegram(fg, btc, grade, btc_risk, tokens, freq, summary)
 
    # --- Write data JSON ---
    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "market": {
            "fear_greed": fg,
            "btc": btc,
            "btc_momentum": btc_mom,
            "btc_risk": btc_risk,
            "global": gd,
            "grade": grade,
            "summary": summary,
            "analysis": analysis,
        },
        "tokens": [{k: v for k, v in t.items()} for t in tokens],
        "frequency": freq[0],
    }
    with open("docs/data.json", "w") as f:
        json.dump(result, f, indent=2, default=str)
 
    # --- Print summary ---
    actionable = [t for t in tokens if t["composite"] >= ALERT_THRESHOLD]
    print(f"\n{'='*60}")
    print(f"BUY: Grade {grade['grade']} ({grade['score']}/100)")
    print(f"RISK: {btc_risk['composite_final']}/100 ({btc_risk['label']}) | {btc_risk['regime']}")
    if actionable:
        print(f"\n{len(actionable)} ACTIONABLE:")
        for t in actionable:
            ath_off_t = abs(t.get("ath_change_pct", 0))
            print(f"  {t['symbol']} - Buy {t['composite']} | Risk {t['risk'].get('composite_final',0)} ({ath_off_t:.0f}% off ATH)")
    else:
        print("No actionable buy setups")
    print("="*60)
 
if __name__ == "__main__":
    if should_run():
        run_scan()
