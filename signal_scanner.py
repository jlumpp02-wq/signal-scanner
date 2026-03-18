"""
SignalScanner v6.1 — Asymmetric Alt Opportunity Bot
GitHub Actions + Telegram notification + GitHub Pages dashboard
Dynamic coin logos from CoinGecko API + expandable market analysis
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
            req = Request(url, headers={"User-Agent": "SignalScanner/6.1", "Accept": "application/json"})
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


# ═══ DATA ═══
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

def get_btc_price():
    print("Fetching BTC price...")
    data = fetch_json("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd&include_24hr_change=true")
    if data and "bitcoin" in data:
        return {"price": round(data["bitcoin"]["usd"], 2), "change_24h": round(data["bitcoin"].get("usd_24h_change", 0), 2)}
    return {"price": 0, "change_24h": 0}

def get_token_data():
    """Fetch prices AND image URLs for all tokens from CoinGecko markets endpoint"""
    ids = ",".join(TOKENS.keys())
    print(f"Fetching prices + images for {len(TOKENS)} tokens...")
    data = fetch_json(f"https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids={ids}&order=market_cap_desc&sparkline=false")
    result = {}
    if data:
        for coin in data:
            cg_id = coin.get("id", "")
            if cg_id in TOKENS:
                sym = TOKENS[cg_id]["symbol"]
                result[sym] = {
                    "price": coin.get("current_price", 0),
                    "change_24h": round(coin.get("price_change_percentage_24h", 0) or 0, 2),
                    "image": coin.get("image", ""),
                }
    return result

def get_market_chart(cg_id, days=30):
    data = fetch_json(f"https://api.coingecko.com/api/v3/coins/{cg_id}/market_chart?vs_currency=usd&days={days}&interval=daily")
    if data and "prices" in data and "total_volumes" in data:
        p = [x[1] for x in data["prices"]]
        v = [x[1] for x in data["total_volumes"]]
        n = min(len(p), len(v))
        return p[:n], v[:n]
    return [], []


# ═══ TECHNICALS ═══
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


# ═══ SCORING ═══
def score_fg(v):
    thresholds = [(10,100),(20,90),(30,75),(40,60),(50,50),(60,40),(70,25),(80,15)]
    for t, s in thresholds:
        if v <= t: return s
    return 5

def score_social(s):
    if s <= 30: return 85
    if s <= 50: return 65
    if s <= 70: return 30
    return 10

def score_btcdom(d):
    if d <= 45: return 90
    if d <= 50: return 70
    if d <= 55: return 50
    if d <= 60: return 30
    return 10

def score_stabledom(d):
    if d >= 14: return 90
    if d >= 12: return 75
    if d >= 10: return 55
    if d >= 8: return 35
    return 15

def score_regime(fg, bd):
    if fg <= 35 and bd >= 55: return 80, "RISK-OFF"
    elif fg >= 55: return 25, "RISK-ON"
    return 50, "NEUTRAL"

def market_grade(fg, social, btcdom, stabledom):
    a = score_fg(fg)
    b = score_social(social)
    c = score_btcdom(btcdom)
    d = score_stabledom(stabledom)
    e, regime = score_regime(fg, btcdom)
    score = round(a*0.30 + b*0.15 + c*0.25 + d*0.20 + e*0.10)
    if score >= 80: g, m = "A+", 1.3
    elif score >= 65: g, m = "A", 1.2
    elif score >= 50: g, m = "B", 1.0
    elif score >= 35: g, m = "C", 0.85
    else: g, m = "D", 0.7
    return {"score": score, "grade": g, "multiplier": m, "regime": regime, "components": {"fg": a, "social": b, "btcdom": c, "stabledom": d, "regime": e}}

def score_rsi(r):
    if r is None: return 50
    thresholds = [(20,95),(30,80),(40,65),(50,50),(60,35),(70,20)]
    for t, s in thresholds:
        if r <= t: return s
    return 10

def score_obv(s):
    return {"ACCUMULATING": 90, "DISTRIBUTING": 10}.get(s, 50)

def token_score(rsi, obv, mult):
    return min(100, round((score_rsi(rsi) * 0.6 + score_obv(obv) * 0.4) * mult))

def signal_label(s):
    if s >= 80: return "STRONG BUY"
    if s >= 65: return "ACCUMULATE"
    if s >= 45: return "NEUTRAL"
    if s >= 30: return "CAUTION"
    return "AVOID"

def recommend_freq(tokens):
    if not tokens: return "DAILY", "No data"
    mx = max(t["composite"] for t in tokens)
    if mx >= 80: return "HOURLY", "High-conviction asymmetry"
    if mx >= 65: return "4-HOUR", "Signals converging"
    if mx >= 50: return "6-HOUR", "Moderate setups"
    return "DAILY", "No actionable signals"


# ═══ MARKET ANALYSIS ═══
def generate_analysis(fg, gd, grade, tokens):
    """Generate detailed market analysis for the expandable summary"""
    actionable = [t for t in tokens if t["composite"] >= ALERT_THRESHOLD]
    oversold = [t for t in tokens if t.get("rsi") and t["rsi"] <= 35]
    accumulating = [t for t in tokens if t["obv_signal"] == "ACCUMULATING"]
    avg_rsi = sum(t["rsi"] for t in tokens if t["rsi"]) / max(1, sum(1 for t in tokens if t["rsi"]))

    lines = []

    # Overall verdict
    if grade["score"] >= 75:
        lines.append("Market conditions are strongly aligned for alt accumulation. Multiple signals point to asymmetric upside.")
    elif grade["score"] >= 60:
        lines.append("Conditions are leaning favorable for selective alt buying. Not a full green light, but the backdrop is constructive.")
    elif grade["score"] >= 45:
        lines.append("Mixed signals across the board. The market is in a wait-and-see mode for alt buyers.")
    elif grade["score"] >= 30:
        lines.append("Conditions are unfavorable for new alt positions. Headwinds outweigh tailwinds right now.")
    else:
        lines.append("Worst-case environment for alt buying. Capital is flowing away from alts and risk appetite is minimal.")

    # Fear & Greed context
    if fg["value"] <= 20:
        lines.append(f"Extreme fear at {fg['value']} is historically where the sharpest reversals happen. This is prime contrarian territory.")
    elif fg["value"] <= 35:
        lines.append(f"Fear at {fg['value']} is elevated but not capitulation-level. Good backdrop for dollar-cost averaging into positions.")
    elif fg["value"] >= 70:
        lines.append(f"Greed at {fg['value']} means the crowd is euphoric. Historically a terrible time to open new positions.")
    else:
        lines.append(f"Sentiment at {fg['value']} is neutral — no strong contrarian signal either way.")

    # BTC dominance read
    bd = gd["btc_dominance"]
    if bd >= 60:
        lines.append(f"BTC dominance at {bd}% is a major headwind. Money is hiding in Bitcoin, not rotating to alts. Wait for this to break below 55% before getting aggressive.")
    elif bd >= 55:
        lines.append(f"BTC dominance at {bd}% is elevated. Some alt rotation may be beginning but BTC is still absorbing most inflows.")
    elif bd <= 48:
        lines.append(f"BTC dominance at {bd}% signals active capital rotation into alts. This is the environment where utility tokens outperform.")
    else:
        lines.append(f"BTC dominance at {bd}% is in the transition zone. Watch for a sustained break below 50% as the signal to get aggressive.")

    # Stablecoin read
    sd = gd["stablecoin_dominance"]
    if sd >= 14:
        lines.append(f"Stablecoin dominance at {sd}% means massive dry powder on the sidelines. When this capital deploys, it hits alts hard.")
    elif sd >= 10:
        lines.append(f"Stablecoin dominance at {sd}% shows moderate sidelined capital. Some fuel for a rally but not a powder keg.")
    else:
        lines.append(f"Stablecoin dominance at {sd}% is low. Most capital is already deployed — limited ammunition for further buying.")

    # Technical picture
    if avg_rsi <= 35:
        lines.append(f"Average RSI across your tokens is {avg_rsi:.0f} — deeply oversold. This is the technical setup you want to see for asymmetric entries.")
    elif avg_rsi >= 65:
        lines.append(f"Average RSI is {avg_rsi:.0f} — approaching overbought territory. Chasing here carries reversal risk.")
    else:
        lines.append(f"Average RSI is {avg_rsi:.0f} — mid-range with no strong directional signal from the technicals.")

    if accumulating:
        names = ", ".join(t["symbol"] for t in accumulating)
        lines.append(f"OBV shows accumulation in {names} — smart money may be building positions while price is flat or down.")

    if oversold:
        names = ", ".join(t["symbol"] for t in oversold)
        lines.append(f"Oversold tokens: {names}. These deserve the closest watch for reversal setups.")

    # Bottom line
    if actionable:
        names = ", ".join(t["symbol"] for t in actionable)
        lines.append(f"BOTTOM LINE: {len(actionable)} actionable setup(s) — {names}. The combination of market conditions and technicals warrants attention.")
    elif grade["score"] >= 50 and any(t["rsi"] and t["rsi"] <= 40 for t in tokens):
        lines.append("BOTTOM LINE: No tokens hit the full actionable threshold yet, but the backdrop is constructive. Watch for RSI dips below 30 on any pullback — those would be the entry points.")
    else:
        lines.append("BOTTOM LINE: No rush. The setup isn't there yet. Keep scanning, let the signals come to you.")

    return " ".join(lines)


def gen_summary(fg, bd, sd):
    parts = []
    if fg["value"] <= 30: parts.append(f"Fear at {fg['value']} creates buying backdrop")
    elif fg["value"] >= 60: parts.append(f"Greed at {fg['value']} dampens setups")
    else: parts.append(f"Neutral sentiment at {fg['value']}")
    if bd >= 58: parts.append(f"BTC dom {bd}% — capital hasn't rotated to alts")
    elif bd <= 48: parts.append(f"BTC dom {bd}% — alt rotation underway")
    if sd >= 12: parts.append(f"{sd}% stables = dry powder")
    elif sd < 8: parts.append(f"{sd}% stables — capital deployed")
    return ". ".join(parts) + "."


# ═══ TELEGRAM ═══
def send_telegram(fg, btc, grade, tokens, freq, summary):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("No Telegram credentials, skipping")
        return
    actionable = [t for t in tokens if t["composite"] >= ALERT_THRESHOLD]
    dot = "\xf0\x9f\x9f\xa2" if grade["score"] >= 65 else "\xf0\x9f\x9f\xa1" if grade["score"] >= 50 else "\xf0\x9f\x9f\xa0" if grade["score"] >= 35 else "\xf0\x9f\x94\xb4"
    token_preview = " \xc2\xb7 ".join(f"{t['symbol']} {t['composite']}" for t in tokens[:5])
    msg = f"""{dot} <b>Grade {grade['grade']}</b> \xc2\xb7 {grade['score']}/100 \xc2\xb7 {grade['multiplier']}x
{token_preview}"""
    if actionable:
        targets = " ".join(f"\xe2\x9a\xa1{t['symbol']}" for t in actionable)
        msg += f"\n\n\xf0\x9f\x94\xa5 <b>TARGETS:</b> {targets}"
    if DASHBOARD_URL:
        msg += f"\n\n\xf0\x9f\x91\x89 <a href=\"{DASHBOARD_URL}\">Open Dashboard</a>"
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": True}).encode()
    req = Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(req, timeout=10) as resp:
            print(f"Telegram sent (status {resp.status})")
    except Exception as e:
        print(f"Telegram error: {e}")


# ═══ HTML DASHBOARD ═══
def generate_dashboard(fg, btc, gd, grade, tokens, freq, summary, analysis, scan_time):
    actionable = [t for t in tokens if t["composite"] >= ALERT_THRESHOLD]

    def sc(s): return "#00ffc8" if s >= 80 else "#7ae8c4" if s >= 65 else "#d4a853" if s >= 45 else "#d47a53" if s >= 30 else "#e84057"
    def cc(v): return "#00ffc8" if v >= 0 else "#e84057"
    def oc(s): return "#00ffc8" if s == "ACCUMULATING" else "#e84057" if s == "DISTRIBUTING" else "#555d75"
    def fp(p):
        if not p: return "?"
        if p >= 100: return f"${p:,.2f}"
        if p >= 1: return f"${p:.2f}"
        return f"${p:.4f}"

    gc = sc(grade["score"])

    # Token cards
    cards = ""
    for i, t in enumerate(tokens):
        tc = sc(t["composite"])
        chc = cc(t["change_24h"])
        obc = oc(t["obv_signal"])
        arrow = "\u25b2" if t["change_24h"] >= 0 else "\u25bc"
        label = signal_label(t["composite"])
        rp = (t["rsi"] / 100 * 100) if t["rsi"] else 50
        ol = "ACCUM" if t["obv_signal"] == "ACCUMULATING" else "DISTR" if t["obv_signal"] == "DISTRIBUTING" else "FLAT"
        img_html = f'<img class="ci" src="{t["image"]}" alt="{t["symbol"]}" onerror="this.style.display=\'none\'">' if t.get("image") else ""
        cg_id = ""
        for k, v in TOKENS.items():
            if v["symbol"] == t["symbol"]:
                cg_id = k
                break
        name = TOKENS.get(cg_id, {}).get("name", t["symbol"])

        cards += f'''
        <div class="tc" style="animation-delay:{i*0.06}s;border-color:{'rgba(0,255,200,0.15)' if t['composite']>=65 else 'rgba(26,37,64,0.8)'}">
          <div class="th">
            <div class="thl">
              {img_html}
              <div><span class="ts" style="color:{tc}">{t["symbol"]}</span> <span class="tn">{name}</span></div>
            </div>
            <div class="tb" style="color:{tc};background:{tc}18;border-color:{tc}33">{label}</div>
          </div>
          <div class="tp">
            <span class="pv">{fp(t["price"])}</span>
            <span class="pc" style="color:{chc}">{arrow} {t["change_24h"]:+.1f}%</span>
          </div>
          <div class="tm">
            <div class="m"><div class="mla">RSI</div><div class="mbg"><div class="mb" style="width:{rp}%;background:{tc}"></div></div><div class="mval" style="color:{tc}">{t["rsi"]:.0f if t["rsi"] else "?"}</div></div>
            <div class="m"><div class="mla">OBV</div><div class="mval" style="color:{obc}">{ol}</div></div>
            <div class="m"><div class="mla">SCORE</div><div class="mval sb" style="color:{tc}">{t["composite"]}</div></div>
          </div>
        </div>'''

    # Targets section
    tgt = ""
    if actionable:
        items = ""
        for t in actionable:
            tc = sc(t["composite"])
            items += f'<div class="ti"><span class="tis" style="color:{tc}">{t["symbol"]}</span><span class="tic" style="color:{tc}">Score {t["composite"]}</span><span class="tid">RSI {t["rsi"]:.0f} \u00b7 {t["obv_signal"]}</span></div>'
        tgt = f'<div class="sl" style="color:#00ffc8">\u26a1 TARGETS DETECTED</div><div class="tg2">{items}</div>'

    fc = "#e84057" if fg["value"]<=25 else "#d47a53" if fg["value"]<=45 else "#d4a853" if fg["value"]<=55 else "#7ae8c4" if fg["value"]<=75 else "#00ffc8"
    bcc = cc(btc["change_24h"])
    ba = "\u25b2" if btc["change_24h"] >= 0 else "\u25bc"
    bdc = "#e84057" if gd["btc_dominance"]>=60 else "#d47a53" if gd["btc_dominance"]>=55 else "#d4a853" if gd["btc_dominance"]>=50 else "#00ffc8"
    sdc = "#00ffc8" if gd["stablecoin_dominance"]>=12 else "#d4a853" if gd["stablecoin_dominance"]>=8 else "#e84057"
    rc = "#e84057" if grade["regime"]=="RISK-OFF" else "#00ffc8" if grade["regime"]=="RISK-ON" else "#d4a853"
    bd_label = "ALT HEADWIND" if gd["btc_dominance"]>=58 else "LEANING BTC" if gd["btc_dominance"]>=55 else "MIXED" if gd["btc_dominance"]>=50 else "ALT TAILWIND"
    sd_label = "DRY POWDER" if gd["stablecoin_dominance"]>=12 else "MODERATE" if gd["stablecoin_dominance"]>=8 else "DEPLOYED"

    # Escape HTML in analysis
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
.ring{{width:100px;height:100px;border-radius:50%;border:3px solid {gc};display:flex;align-items:center;justify-content:center;margin:16px auto;background:{gc}0a;box-shadow:0 0 30px {gc}15,inset 0 0 20px {gc}08}}
.gl{{font-size:36px;font-weight:900;color:{gc};font-family:'JetBrains Mono',monospace}}
.gm{{font-size:13px;color:#8892a8;margin-top:8px;font-family:'JetBrains Mono',monospace}}
.gm b{{color:{gc}}}
.sum{{font-size:13px;color:#5a6480;line-height:1.6;margin-top:12px;font-style:italic;max-width:400px;margin-left:auto;margin-right:auto}}
.st{{font-size:10px;color:#2a3045;margin-top:10px;font-family:'JetBrains Mono',monospace;letter-spacing:1px}}

/* Analysis toggle */
.analysis-wrap{{margin:20px 0;text-align:center}}
.analysis-btn{{background:rgba(255,255,255,0.04);border:1px solid #1a2540;color:#5a6480;padding:10px 20px;border-radius:10px;font-size:12px;font-family:'JetBrains Mono',monospace;cursor:pointer;letter-spacing:1px;transition:all 0.2s}}
.analysis-btn:hover{{border-color:#3d465e;color:#8892a8}}
.analysis-body{{display:none;text-align:left;background:linear-gradient(145deg,#0c1222,#101828);border:1px solid #1a2540;border-radius:14px;padding:20px;margin-top:12px;font-size:13px;color:#7a84a0;line-height:1.8}}
.analysis-body.open{{display:block}}

.sl{{font-size:10px;letter-spacing:3px;color:#3d465e;font-family:'JetBrains Mono',monospace;font-weight:600;margin:24px 0 12px;padding-bottom:8px;border-bottom:1px solid #111827}}
.mg{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}
.mc{{background:linear-gradient(145deg,#0c1222,#101828);border:1px solid #1a2540;border-radius:14px;padding:16px;text-align:center}}
.mc.w{{grid-column:1/-1}}
.ml{{font-size:9px;letter-spacing:2px;color:#3d465e;font-family:'JetBrains Mono',monospace;margin-bottom:8px}}
.mv{{font-size:24px;font-weight:800;font-family:'JetBrains Mono',monospace}}
.ms{{font-size:10px;color:#3d465e;margin-top:4px;font-family:'JetBrains Mono',monospace;letter-spacing:1px}}

/* Targets */
.tg2{{display:flex;flex-direction:column;gap:8px;margin-bottom:8px}}
.ti{{background:#00ffc808;border:1px solid #00ffc820;border-radius:10px;padding:12px 16px;display:flex;align-items:center;gap:12px}}
.tis{{font-weight:800;font-size:16px;font-family:'JetBrains Mono',monospace}}
.tic{{font-weight:700;font-size:13px;font-family:'JetBrains Mono',monospace}}
.tid{{font-size:11px;color:#5a6480;margin-left:auto}}

/* Token cards */
.tg{{display:flex;flex-direction:column;gap:8px}}
.tc{{background:linear-gradient(145deg,#0c1222,#101828);border:1px solid #1a2540;border-radius:14px;padding:16px;animation:si 0.3s ease both}}
@keyframes si{{from{{opacity:0;transform:translateY(8px)}}to{{opacity:1;transform:translateY(0)}}}}
.th{{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}}
.thl{{display:flex;align-items:center;gap:10px}}
.ci{{width:28px;height:28px;border-radius:50%;object-fit:contain;background:#151d30;flex-shrink:0}}
.ts{{font-size:18px;font-weight:800;font-family:'JetBrains Mono',monospace}}
.tn{{font-size:11px;color:#555d75;font-weight:400}}
.tb{{font-size:9px;font-weight:700;letter-spacing:1px;padding:4px 10px;border-radius:6px;border:1px solid;font-family:'JetBrains Mono',monospace}}
.tp{{display:flex;align-items:baseline;gap:10px;margin-bottom:12px}}
.pv{{font-size:15px;font-weight:600;color:#e8ecf4;font-family:'JetBrains Mono',monospace}}
.pc{{font-size:12px;font-weight:600;font-family:'JetBrains Mono',monospace}}
.tm{{display:grid;grid-template-columns:1fr auto auto;gap:12px;align-items:center}}
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
    <div class="ring"><div class="gl">{grade["grade"]}</div></div>
    <div class="gm"><b>{grade["score"]}</b>/100 &middot; <b>{grade["multiplier"]}x</b> multiplier &middot; {grade["regime"]}</div>
    <div class="sum">{summary}</div>
    <div class="st">{scan_time}</div>
  </div>

  <div class="analysis-wrap">
    <button class="analysis-btn" onclick="let b=document.getElementById('ab');b.classList.toggle('open');this.textContent=b.classList.contains('open')?'\u25b4 HIDE ANALYSIS':'\u25be MARKET ANALYSIS'">\u25be MARKET ANALYSIS</button>
    <div class="analysis-body" id="ab">{analysis_safe}</div>
  </div>

  <div class="sl">MARKET CONDITIONS</div>
  <div class="mg">
    <div class="mc">
      <div class="ml">\U0001f9e0 FEAR & GREED</div>
      <div class="mv" style="color:{fc}">{fg["value"]}</div>
      <div class="ms">{fg["label"].upper()}</div>
    </div>
    <div class="mc">
      <div class="ml">\u20bf BITCOIN</div>
      <div class="mv" style="color:#d4a853">${btc["price"]:,.0f}</div>
      <div class="ms" style="color:{bcc}">{ba} {btc["change_24h"]:+.1f}%</div>
    </div>
    <div class="mc">
      <div class="ml">\U0001f4ca BTC DOMINANCE</div>
      <div class="mv" style="color:{bdc}">{gd["btc_dominance"]}%</div>
      <div class="ms">{bd_label}</div>
    </div>
    <div class="mc">
      <div class="ml">\U0001fa99 STABLECOIN DOM</div>
      <div class="mv" style="color:{sdc}">{gd["stablecoin_dominance"]}%</div>
      <div class="ms">{sd_label}</div>
    </div>
    <div class="mc w">
      <div class="ml">\u26a1 REGIME</div>
      <div class="mv" style="color:{rc}">{grade["regime"]}</div>
    </div>
  </div>

  {tgt}

  <div class="sl">UTILITY TOKEN SIGNALS &middot; {len(actionable)} ACTIONABLE</div>
  <div class="tg">{cards}</div>

  <div class="fb">
    <div class="fl">\u23f1 NEXT SCAN</div>
    <div class="fv">{freq[0]} &middot; {freq[1]}</div>
  </div>
  <div class="ft">SIGNALSCANNER v6.1 &middot; NOT FINANCIAL ADVICE</div>
</div>
</body>
</html>'''
    return html


# ═══ MAIN ═══
def run_scan():
    scan_time = datetime.now(timezone.utc).strftime("%b %d, %Y \u00b7 %H:%M UTC")
    print(f"SIGNALSCANNER v6.1 - {scan_time}\n")

    fg = get_fear_greed()
    print(f"  Fear & Greed: {fg['value']} ({fg['label']})")

    gd = get_global_data()
    print(f"  BTC Dom: {gd['btc_dominance']}% | Stable Dom: {gd['stablecoin_dominance']}%")

    btc = get_btc_price()
    print(f"  BTC: ${btc['price']:,.2f} ({btc['change_24h']:+.1f}%)")

    time.sleep(1.5)
    token_data = get_token_data()
    print(f"  Got {len(token_data)} token prices + images")

    social = max(20, min(90, 100 - fg["value"]))
    grade = market_grade(fg["value"], social, gd["btc_dominance"], gd["stablecoin_dominance"])
    print(f"  Grade: {grade['grade']} ({grade['score']}/100) -> {grade['multiplier']}x | {grade['regime']}")

    summary = gen_summary(fg, gd["btc_dominance"], gd["stablecoin_dominance"])

    print(f"\nComputing technicals...")
    tokens = []
    for cg_id, info in TOKENS.items():
        sym = info["symbol"]
        print(f"  {sym}...", end=" ")
        time.sleep(1.5)
        hp, hv = get_market_chart(cg_id, 30)
        rsi = compute_rsi(hp)
        obv = compute_obv_signal(hp, hv)
        comp = token_score(rsi, obv, grade["multiplier"])
        td = token_data.get(sym, {"price": 0, "change_24h": 0, "image": ""})
        tokens.append({"symbol": sym, "price": td["price"], "change_24h": td["change_24h"], "image": td.get("image", ""), "rsi": rsi, "obv_signal": obv, "composite": comp})
        print(f"RSI={rsi or '?'} OBV={obv} Score={comp}")

    tokens.sort(key=lambda x: x["composite"], reverse=True)
    freq = recommend_freq(tokens)
    print(f"\n  Scan frequency: {freq[0]} - {freq[1]}")

    # Generate analysis
    analysis = generate_analysis(fg, gd, grade, tokens)
    print(f"  Analysis: {analysis[:100]}...")

    # Dashboard
    os.makedirs("docs", exist_ok=True)
    html = generate_dashboard(fg, btc, gd, grade, tokens, freq, summary, analysis, scan_time)
    with open("docs/index.html", "w") as f:
        f.write(html)
    print("  Dashboard written to docs/index.html")

    # Telegram
    send_telegram(fg, btc, grade, tokens, freq, summary)

    # JSON
    result = {"timestamp": datetime.now(timezone.utc).isoformat(), "market": {"fear_greed": fg, "btc": btc, "global": gd, "grade": grade, "summary": summary, "analysis": analysis}, "tokens": tokens, "frequency": freq[0]}
    with open("docs/data.json", "w") as f:
        json.dump(result, f, indent=2)

    actionable = [t for t in tokens if t["composite"] >= ALERT_THRESHOLD]
    print(f"\n{'='*50}")
    if actionable:
        print(f"{len(actionable)} ACTIONABLE:")
        for t in actionable: print(f"  {t['symbol']} - Score {t['composite']}")
    else:
        print("No actionable setups")
    print("="*50)

if __name__ == "__main__":
    run_scan()
