# SignalScanner v5 — Asymmetric Alt Opportunity Bot

Automated scanner that monitors 9 utility tokens for asymmetric buy opportunities. Runs on GitHub Actions and sends alerts to Discord.

## How It Works

### Market Conditions → Asymmetry Grade (A+ through D)
Five market signals are scored and blended into a composite grade:

| Signal | Weight | Logic |
|--------|--------|-------|
| Fear & Greed | 30% | Extreme fear = opportunity (inverted) |
| BTC Dominance | 25% | Lower BTC dom = capital rotating to alts |
| Stablecoin Dominance | 20% | Higher = more dry powder on sidelines |
| Social Sentiment | 15% | Contrarian — bearish crowd = opportunity |
| Market Regime | 10% | RISK-OFF = contrarian buy signal |

Grade → Multiplier: **A+ (1.3x)** → A (1.2x) → B (1.0x) → C (0.85x) → **D (0.7x)**

### Per-Token Scoring
| Indicator | Weight | Source |
|-----------|--------|--------|
| RSI-14 | 60% | CoinGecko 30-day daily prices |
| OBV Divergence | 40% | CoinGecko daily price + volume |

**Final Score** = (RSI×0.6 + OBV×0.4) × Market Multiplier

### Tokens Tracked
ETH, LINK, XRP, IOTA, XLM, HBAR, QNT, XDC, ONDO

BTC is used as a **market indicator** (price + dominance), not scored.

### Adaptive Scan Frequency
The cron runs hourly, but only alerts based on signal intensity:
- **Score 80+**: Alert every hour
- **Score 65-79**: Alert every 4 hours  
- **Score 50-64**: Alert every 6 hours
- **Below 50**: Daily summary only

## Setup

### 1. Create a Discord Webhook
- Server Settings → Integrations → Webhooks → New Webhook
- Copy the URL

### 2. Create GitHub Repo
```bash
git init signal-scanner
cd signal-scanner
# Copy signal_scanner.py and .github/workflows/scan.yml
```

### 3. Add Discord Webhook Secret
- Repo Settings → Secrets and Variables → Actions
- New secret: `DISCORD_WEBHOOK` = your webhook URL

### 4. Push & Enable
```bash
git add .
git commit -m "Initial scanner setup"
git push origin main
```
The workflow runs automatically every hour. You can also trigger manually from the Actions tab.

## Data Sources (all free, no API keys)
- **CoinGecko**: Prices, 30-day history (RSI/OBV computation), BTC dominance
- **Alternative.me**: Crypto Fear & Greed Index

## Cost
- **GitHub Actions**: Free tier = 2,000 min/month. Each scan takes ~30 seconds. Running hourly = ~15 hours/month. Well within free tier.
- **All APIs**: Free, no keys required.

## Not Financial Advice
This is an informational tool for signal detection only. Always do your own research.
