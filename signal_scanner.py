"""
SignalScanner v7 — Asymmetric Alt Opportunity Bot
Scoring: 70% ATH Discount + 20% RSI + 10% OBV × Market Multiplier
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
            req = Request(url, headers={"User-Agent": "SignalScanner/7.0", "Accept": "application/json"})
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
 
 
def fmt_rsi(rsi):
    if rsi is None: return "?"
    return f"{rsi:.0f}"
 
 
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
                    "ath_date": coin.get("ath_date", ""),
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
 
 
# ═══ MARKET GRADE ═══
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
    return {"score": score, "grade": g, "multiplier": m, "regime": regime}
 
 
# ═══ TOKEN SCORING (v7) ═══
def score_ath_discount(pct_off):
    discount = abs(pct_off)
    if discount >= 90: return 100
    if discount >= 80: return 92
    if discount >= 70: return 82
    if discount >= 60: return 72
    if discount >= 50: return 60
    if discount >= 40: return 48
    if discount >= 30: return 35
    if discount >= 20: return 22
    if discount >= 10: return 12
    return 5
 
def score_rsi(r):
    if r is None: return 50
    thresholds = [(20,95),(30,80),(40,65),(50,50),(60,35),(70,20)]
    for t, s in thresholds:
        if r <= t: return s
    return 10
 
def score_obv(s):
    return {"ACCUMULATING": 90, "DISTRIBUTING": 10}.get(s, 50)
 
def token_score(ath_pct, rsi, obv, mult):
    ath_s = score_ath_discount(ath_pct)
    rsi_s = score_rsi(rsi)
    obv_s = score_obv(obv)
    raw = ath_s * 0.70 + rsi_s * 0.20 + obv_s * 0.10
    composite = min(100, round(raw * mult))
    return {"ath_score": ath_s, "rsi_score": rsi_s, "obv_score": obv_s, "raw": round(raw), "composite": composite}
 
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
 
 
# ═══ ANALYSIS ═══
def generate_analysis(fg, gd, grade, tokens):
    actionable = [t for t in tokens if t["composite"] >= ALERT_THRESHOLD]
    deep_discount = [t for t in tokens if abs(t.get("ath_change_pct", 0)) >= 80]
    oversold = [t for t in tokens if t.get("rsi") and t["rsi"] <= 35]
    accumulating = [t for t in tokens if t["obv_signal"] == "ACCUMULATING"]
    rsi_vals = [t["rsi"] for t in tokens if t["rsi"]]
    avg_rsi = sum(rsi_vals) / max(1, len(rsi_vals))
    avg_discount = sum(abs(t.get("ath_change_pct", 0)) for t in tokens) / max(1, len(tokens))
 
    lines = []
 
    if grade["score"] >= 75:
        lines.append("Market conditions are strongly aligned for alt accumulation. Multiple signals point to asymmetric upside.")
    elif grade["score"] >= 60:
        lines.append("Conditions lean favorable for selective buying. Not full green light, but constructive.")
    elif grade["score"] >= 45:
        lines.append("Mixed signals. Wait-and-see mode for alt buyers.")
    elif grade["score"] >= 30:
        lines.append("Unfavorable for new alt positions. Headwinds outweigh tailwinds.")
    else:
        lines.append("Worst-case for alt buying. Capital flowing away from alts.")
 
    lines.append(f"Your watchlist averages {avg_discount:.0f}% off all-time highs.")
    if avg_discount >= 80:
        lines.append("Deep cycle discount territory. Historically, buying utility tokens 80%+ off ATH with a multi-year hold produces outsized returns.")
    elif avg_discount >= 60:
        lines.append("Significant discount from peak. Well below euphoria levels \u2014 this is where you want to accumulate.")
    elif avg_discount >= 40:
        lines.append("Moderate discount. Selective entries could work.")
    else:
        lines.append("Relatively close to highs. Less asymmetric upside available.")
 
    if deep_discount:
        names = ", ".join(f"{t['symbol']} ({abs(t['ath_change_pct']):.0f}% off)" for t in deep_discount)
        lines.append(f"Deepest discounts: {names}.")
 
    if fg["value"] <= 20:
        lines.append(f"Extreme fear at {fg['value']} \u2014 historically where sharpest reversals happen.")
    elif fg["value"] <= 35:
        lines.append(f"Fear at {fg['value']} is elevated. Good DCA backdrop.")
    elif fg["value"] >= 70:
        lines.append(f"Greed at {fg['value']} \u2014 terrible time for new positions.")
 
    bd = gd["btc_dominance"]
    if bd >= 60:
        lines.append(f"BTC dom {bd}% is a major alt headwind.")
    elif bd >= 55:
        lines.append(f"BTC dom {bd}% elevated. BTC still absorbing most inflows.")
    elif bd <= 48:
        lines.append(f"BTC dom {bd}% \u2014 active alt rotation. Utility tokens outperform here.")
 
    if accumulating:
        names = ", ".join(t["symbol"] for t in accumulating)
        lines.append(f"OBV accumulation in {names} \u2014 smart money building positions.")
 
    if oversold:
        names = ", ".join(t["symbol"] for t in oversold)
        lines.append(f"RSI oversold: {names}.")
 
    if actionable:
        names = ", ".join(t["symbol"] for t in actionable)
        lines.append(f"BOTTOM LINE: {len(actionable)} actionable \u2014 {names}. Deep discount + favorable conditions = asymmetric setup.")
    elif avg_discount >= 70 and grade["score"] >= 50:
        lines.append("BOTTOM LINE: Deeply discounted but signals haven't converged. Watch for fear spikes or RSI drops as entry triggers.")
    else:
        lines.append("BOTTOM LINE: No rush. Let the setup come to you.")
 
    return " ".join(lines)
 
 
def gen_summary(fg, bd, sd):
    parts = []
    if fg["value"] <= 30: parts.append(f"Fear at {fg['value']} creates buying backdrop")
    elif fg["value"] >= 60: parts.append(f"Greed at {fg['value']} dampens setups")
    else: parts.append(f"Neutral sentiment at {fg['value']}")
    if bd >= 58: parts.append(f"BTC dom {bd}% \u2014 capital hasn't rotated to alts")
    elif bd <= 48: parts.append(f"BTC dom {bd}% \u2014 alt rotation underway")
    if sd >= 12: parts.append(f"{sd}% stables = dry powder")
    elif sd < 8: parts.append(f"{sd}% stables \u2014 capital deployed")
    return ". ".join(parts) + "."
 
 
# ═══ TELEGRAM ═══
def send_telegram(fg, btc, grade, tokens, freq, summary):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("No Telegram credentials, skipping")
        return
    actionable = [t for t in tokens if t["composite"] >= ALERT_THRESHOLD]
    if grade["score"] >= 65: dot = "\U0001f7e2"
    elif grade["score"] >= 50: dot = "\U0001f7e1"
    elif grade["score"] >= 35: dot = "\U0001f7e0"
    else: dot = "\U0001f534"
    token_preview = " \u00b7 ".join(f"{t['symbol']} {t['composite']}" for t in tokens[:5])
    msg = f"""{dot} <b>Grade {grade['grade']}</b> \u00b7 {grade['score']}/100 \u00b7 {grade['multiplier']}x
{token_preview}"""
    if actionable:
        targets = " ".join(f"\u26a1{t['symbol']}" for t in actionable)
        msg += f"\n\n\U0001f525 <b>TARGETS:</b> {targets}"
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
 
 
# ═══ DASHBOARD ═══
def generate_dashboard(fg, btc, gd, grade, tokens, freq, summary, analysis, scan_time):
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
    def dc(pct):
        d = abs(pct)
        if d >= 80: return "#00ffc8"
        if d >= 60: return "#7ae8c4"
        if d >= 40: return "#d4a853"
        return "#d47a53"
 
    gc = sc(grade["score"])
 
    cards = ""
    for i, t in enumerate(tokens):
        tc = sc(t["composite"])
        chc = cc(t["change_24h"])
        obc = oc(t["obv_signal"])
        arrow = "\u25b2" if t["change_24h"] >= 0 else "\u25bc"
        label = signal_label(t["composite"])
        rp = (t["rsi"] / 100 * 100) if t["rsi"] else 50
        rsi_display = fmt_rsi(t["rsi"])
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
        ath_c = dc(t.get("ath_change_pct", 0))
        ath_bar_w = min(100, ath_pct)
        ath_price = fp(ath_val) if ath_val else "?"
 
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
            <div class="m"><div class="mla">SCORE</div><div class="mval sb" style="color:{tc}">{t["composite"]}</div></div>
          </div>
        </div>'''
 
    tgt = ""
    if actionable:
        items = ""
        for t in actionable:
            tc = sc(t["composite"])
            rsi_display = fmt_rsi(t["rsi"])
            ath_pct = abs(t.get("ath_change_pct", 0))
            items += f'<div class="ti"><span class="tis" style="color:{tc}">{t["symbol"]}</span><span class="tic" style="color:{tc}">Score {t["composite"]}</span><span class="tid">{ath_pct:.0f}% off ATH \u00b7 RSI {rsi_display}</span></div>'
        tgt = f'<div class="sl" style="color:#00ffc8">\u26a1 TARGETS DETECTED</div><div class="tg2">{items}</div>'
 
    fc = "#e84057" if fg["value"]<=25 else "#d47a53" if fg["value"]<=45 else "#d4a853" if fg["value"]<=55 else "#7ae8c4" if fg["value"]<=75 else "#00ffc8"
    bcc = cc(btc["change_24h"])
    ba = "\u25b2" if btc["change_24h"] >= 0 else "\u25bc"
    bdc = "#e84057" if gd["btc_dominance"]>=60 else "#d47a53" if gd["btc_dominance"]>=55 else "#d4a853" if gd["btc_dominance"]>=50 else "#00ffc8"
    sdc = "#00ffc8" if gd["stablecoin_dominance"]>=12 else "#d4a853" if gd["stablecoin_dominance"]>=8 else "#e84057"
    rc = "#e84057" if grade["regime"]=="RISK-OFF" else "#00ffc8" if grade["regime"]=="RISK-ON" else "#d4a853"
    bd_label = "ALT HEADWIND" if gd["btc_dominance"]>=58 else "LEANING BTC" if gd["btc_dominance"]>=55 else "MIXED" if gd["btc_dominance"]>=50 else "ALT TAILWIND"
    sd_label = "DRY POWDER" if gd["stablecoin_dominance"]>=12 else "MODERATE" if gd["stablecoin_dominance"]>=8 else "DEPLOYED"
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
.aw{{margin:20px 0;text-align:center}}
.ab-btn{{background:rgba(255,255,255,0.04);border:1px solid #1a2540;color:#5a6480;padding:10px 20px;border-radius:10px;font-size:12px;font-family:'JetBrains Mono',monospace;cursor:pointer;letter-spacing:1px;transition:all 0.2s}}
.ab-btn:hover{{border-color:#3d465e;color:#8892a8}}
.ab-body{{display:none;text-align:left;background:linear-gradient(145deg,#0c1222,#101828);border:1px solid #1a2540;border-radius:14px;padding:20px;margin-top:12px;font-size:13px;color:#7a84a0;line-height:1.8}}
.ab-body.open{{display:block}}
.sl{{font-size:10px;letter-spacing:3px;color:#3d465e;font-family:'JetBrains Mono',monospace;font-weight:600;margin:24px 0 12px;padding-bottom:8px;border-bottom:1px solid #111827}}
.mg{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}
.mc{{background:linear-gradient(145deg,#0c1222,#101828);border:1px solid #1a2540;border-radius:14px;padding:16px;text-align:center}}
.mc.w{{grid-column:1/-1}}
.ml{{font-size:9px;letter-spacing:2px;color:#3d465e;font-family:'JetBrains Mono',monospace;margin-bottom:8px}}
.mv{{font-size:24px;font-weight:800;font-family:'JetBrains Mono',monospace}}
.ms{{font-size:10px;color:#3d465e;margin-top:4px;font-family:'JetBrains Mono',monospace;letter-spacing:1px}}
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
 
  <div class="aw">
    <button class="ab-btn" id="abtn" onclick="var b=document.getElementById('abody');b.classList.toggle('open');document.getElementById('abtn').textContent=b.classList.contains('open')?'\\u25b4 HIDE ANALYSIS':'\\u25be MARKET ANALYSIS'">&#9662; MARKET ANALYSIS</button>
    <div class="ab-body" id="abody">{analysis_safe}</div>
  </div>
 
  <div class="sl">MARKET CONDITIONS</div>
  <div class="mg">
    <div class="mc">
      <div class="ml">&#129504; FEAR &amp; GREED</div>
      <div class="mv" style="color:{fc}">{fg["value"]}</div>
      <div class="ms">{fg["label"].upper()}</div>
    </div>
    <div class="mc">
      <div class="ml">&#8383; BITCOIN</div>
      <div class="mv" style="color:#d4a853">${btc["price"]:,.0f}</div>
      <div class="ms" style="color:{bcc}">{ba} {btc["change_24h"]:+.1f}%</div>
    </div>
    <div class="mc">
      <div class="ml">&#128202; BTC DOMINANCE</div>
      <div class="mv" style="color:{bdc}">{gd["btc_dominance"]}%</div>
      <div class="ms">{bd_label}</div>
    </div>
    <div class="mc">
      <div class="ml">&#129689; STABLECOIN DOM</div>
      <div class="mv" style="color:{sdc}">{gd["stablecoin_dominance"]}%</div>
      <div class="ms">{sd_label}</div>
    </div>
    <div class="mc w">
      <div class="ml">&#9889; REGIME</div>
      <div class="mv" style="color:{rc}">{grade["regime"]}</div>
    </div>
  </div>
 
  {tgt}
 
  <div class="sl">UTILITY TOKEN SIGNALS &middot; {len(actionable)} ACTIONABLE</div>
  <div class="tg">{cards}</div>
 
  <div class="fb">
    <div class="fl">&#9201; NEXT SCAN</div>
    <div class="fv">{freq[0]} &middot; {freq[1]}</div>
  </div>
  <div class="ft">SIGNALSCANNER v7.0 &middot; NOT FINANCIAL ADVICE</div>
</div>
</body>
</html>'''
    return html
 
 
# ═══ ADAPTIVE FREQUENCY ═══
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
 
 
# ═══ MAIN ═══
def run_scan():
    scan_time = datetime.now(timezone.utc).strftime("%b %d, %Y \u00b7 %H:%M UTC")
    print(f"SIGNALSCANNER v7.0 - {scan_time}\n")
 
    fg = get_fear_greed()
    print(f"  Fear & Greed: {fg['value']} ({fg['label']})")
 
    gd = get_global_data()
    print(f"  BTC Dom: {gd['btc_dominance']}% | Stable Dom: {gd['stablecoin_dominance']}%")
 
    btc = get_btc_price()
    print(f"  BTC: ${btc['price']:,.2f} ({btc['change_24h']:+.1f}%)")
 
    time.sleep(1.5)
    token_data = get_token_data()
    print(f"  Got {len(token_data)} token prices + ATH data")
 
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
        td = token_data.get(sym, {"price": 0, "change_24h": 0, "image": "", "ath": 0, "ath_change_pct": 0})
        scores = token_score(td.get("ath_change_pct", 0), rsi, obv, grade["multiplier"])
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
        })
        ath_off = abs(td.get("ath_change_pct", 0))
        print(f"ATH -{ath_off:.0f}% RSI={fmt_rsi(rsi)} OBV={obv} Score={scores['composite']}")
 
    tokens.sort(key=lambda x: x["composite"], reverse=True)
    freq = recommend_freq(tokens)
    print(f"\n  Scan frequency: {freq[0]} - {freq[1]}")
 
    analysis = generate_analysis(fg, gd, grade, tokens)
    print(f"  Analysis: {analysis[:100]}...")
 
    os.makedirs("docs", exist_ok=True)
    html = generate_dashboard(fg, btc, gd, grade, tokens, freq, summary, analysis, scan_time)
    with open("docs/index.html", "w") as f:
        f.write(html)
    print("  Dashboard written to docs/index.html")
 
    send_telegram(fg, btc, grade, tokens, freq, summary)
 
    result = {"timestamp": datetime.now(timezone.utc).isoformat(), "market": {"fear_greed": fg, "btc": btc, "global": gd, "grade": grade, "summary": summary, "analysis": analysis}, "tokens": tokens, "frequency": freq[0]}
    with open("docs/data.json", "w") as f:
        json.dump(result, f, indent=2)
 
    actionable = [t for t in tokens if t["composite"] >= ALERT_THRESHOLD]
    print(f"\n{'='*50}")
    if actionable:
        print(f"{len(actionable)} ACTIONABLE:")
        for t in actionable:
            ath_off = abs(t.get("ath_change_pct", 0))
            print(f"  {t['symbol']} - Score {t['composite']} ({ath_off:.0f}% off ATH)")
    else:
        print("No actionable setups")
    print("="*50)
 
if __name__ == "__main__":
    if should_run():
        run_scan()
