"""
Apex Quant: Momentum Breakout & Volume Surge Scanner
Scans high-momentum smallcaps, midcaps, and cash breakout stocks.
Captures explosive moves like CUPID.NS and KALYANKJIL.NS.
"""

import yfinance as yf
import pandas as pd
import datetime

# High-beta cash & midcap universe
MOMENTUM_UNIVERSE = [
    # Retail, Gems, Jewellery & Consumption
    "KALYANKJIL.NS", "CUPID.NS", "SENCO.NS", "PCJEWELLER.NS", "THANGAMAYL.NS", "TITAN.NS",
    # Capital Markets, Fintech & Wealth
    "BSE.NS", "CDSL.NS", "MCX.NS", "ANGELONE.NS", "MOTILALOFS.NS", "ANANDRATHI.NS", "KFINTECH.NS", "CAMS.NS",
    # Green Energy, Wind & Solar
    "SUZLON.NS", "INOXWIND.NS", "PREMIERENE.NS", "IREDA.NS", "SJVN.NS",
    # Defense, Aerospace & High-Tech EMS
    "KAYNES.NS", "DATAPATTNS.NS", "ZENTEC.NS", "TEJASNET.NS", "PARAS.NS", "AVANTEL.NS", "CYIENT.NS", "COCHINSHIP.NS", "GRSE.NS",
    # Real Estate & Infra high-flyers
    "PRESTIGE.NS", "BRIGADE.NS", "SOBHA.NS", "SIGNATURE.NS", "NCC.NS", "HUDCO.NS", "NBCC.NS",
    # Retail & Consumer High-Growth
    "DOMS.NS", "JUBLFOOD.NS", "DEVYANI.NS", "WESTLIFE.NS", "HONASA.NS", "CAMPUS.NS",
    # Power & PSU Momentum
    "RECLTD.NS", "PFC.NS", "NATIONALUM.NS", "BHEL.NS", "BEL.NS", "TATAPOWER.NS"
]

def scan_explosive_breakouts(capital: float = 15550.0, max_price: float = 850.0):
    print(f"[{datetime.datetime.now()}] Scanning {len(MOMENTUM_UNIVERSE)} momentum candidates...")
    results = []
    
    for s in MOMENTUM_UNIVERSE:
        try:
            t = yf.Ticker(s)
            df = t.history(period="1mo", interval="1d")
            if df.empty or len(df) < 10: continue
            
            today = df.iloc[-1]
            prev = df.iloc[-2]
            
            c = float(today['Close'])
            o = float(today['Open'])
            h = float(today['High'])
            l = float(today['Low'])
            v = float(today['Volume'])
            
            # Filter price: ₹140 to ₹850
            if c < 140 or c > max_price: continue
            
            # Sizing: must buy at least 18 shares
            qty = int(capital // c)
            if qty < 18: continue
            
            # Volume surge ratio: today's volume vs 15-day average
            v_avg = float(df['Volume'].tail(15).mean())
            vol_ratio = v / (v_avg + 1e-6)
            
            day_chg = ((c - float(prev['Close'])) / float(prev['Close'])) * 100
            
            # 20 EMA
            ema20 = float(df['Close'].ewm(span=20, adjust=False).mean().iloc[-1])
            dist_ema20 = ((c - ema20) / ema20) * 100
            
            # Consolidation check: was previous 3 days range tight?
            prev_3d_high = float(df['High'].iloc[-4:-1].max())
            prev_3d_low = float(df['Low'].iloc[-4:-1].min())
            consolidation_range = ((prev_3d_high - prev_3d_low) / prev_3d_low) * 100
            
            results.append({
                "symbol": s,
                "price": round(c, 2),
                "day_chg": round(day_chg, 2),
                "vol_ratio": round(vol_ratio, 2),
                "dist_ema20": round(dist_ema20, 2),
                "consolidation_3d": round(consolidation_range, 2),
                "qty": qty,
                "is_green": c >= o
            })
        except Exception:
            pass
            
    df_res = pd.DataFrame(results)
    if not df_res.empty:
        # Sort by volume surge & price momentum
        top = df_res.sort_values(by=["vol_ratio", "day_chg"], ascending=[False, False])
        return top
    return pd.DataFrame()

if __name__ == "__main__":
    df = scan_explosive_breakouts()
    print("\n=== TOP MOMENTUM BREAKOUTS (VOLUME EXPANSION) ===")
    print(df.head(10).to_string(index=False))

