from flask import Flask, render_template, request, jsonify
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from functools import lru_cache
import json
import warnings
warnings.filterwarnings('ignore')

app = Flask(__name__)

# --- PURE YAHOO FINANCE DATA PULLER ---
def get_hist_data(ticker, period="10y"):
    """Pulls directly from Yahoo Finance using the safest history method."""
    try:
        df = yf.Ticker(ticker).history(period=period)
        if not df.empty and 'Close' in df.columns:
            df.index = pd.to_datetime(df.index, utc=True).tz_localize(None)
            return df[['Close']].dropna()
    except Exception as e: 
        print(f"[DEBUG] YFinance Error for {ticker}: {e}")
    return pd.DataFrame()

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def create_sparkline(series, color, height=40):
    if series is None or len(series) < 2: return ""
    vals = series.values
    min_val, max_val = min(vals), max(vals)
    rng = max_val - min_val if max_val != min_val else 1
    pts = [f"{(i / (len(vals) - 1)) * 100:.1f},{40 - ((val - min_val) / rng) * 36 - 2:.1f}" for i, val in enumerate(vals)]
    path_points = " ".join(pts)
    r, g, b = tuple(int(color.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))
    fill_color = f"rgba({r},{g},{b},0.15)"
    return f'''<svg width="100%" height="{height}px" viewBox="0 0 100 40" preserveAspectRatio="none" style="display:block;"><polygon points="0,40 {path_points} 100,40" fill="{fill_color}" /><polyline fill="none" stroke="{color}" stroke-width="2" points="{path_points}" /></svg>'''

@lru_cache(maxsize=32)
def fetch_screener_data(tickers):
    data_list = []
    for ticker in tickers:
        df = get_hist_data(ticker, period="3mo")
        if df.empty or 'Close' not in df.columns: continue
        series = df['Close']
        if len(series) < 2: continue
        
        curr, prev = float(series.iloc[-1]), float(series.iloc[-2])
        pct_change = ((curr - prev) / prev * 100) if prev != 0 else 0
        rsi_value = calculate_rsi(series).iloc[-1] if len(series) > 14 else 50
        sparkline_html = create_sparkline(series.tail(30), "#39FF14" if curr >= series.iloc[0] else "#FF007F", 35)
        
        try:
            info = {"shortName": "IBEX 35 Index"} if ticker == '^IBEX' else yf.Ticker(ticker).info
        except:
            info = {"shortName": ticker}
            
        signal = "🔴 Overbought" if rsi_value > 70 else "🟢 Oversold" if rsi_value < 30 else "↗️ Bullish" if rsi_value > 55 else "↘️ Bearish" if rsi_value < 45 else "➖ Neutral"

        data_list.append({
            "Ticker": ticker, "Company Name": info.get('shortName', ticker), "Sector": info.get('sector', 'Unknown'), 
            "Price": f"{curr:,.2f}", "CHG %": f"{pct_change:+.2f}%", "30-Day Trend": sparkline_html,
            "Momentum": f"{rsi_value:.1f}", "Rating": signal,
            "Vol (M)": f"{(info.get('volume', 0) / 1e6):,.1f}" if info.get('volume') else "N/A", 
            "Mkt Cap (B)": f"{(info.get('marketCap', 0) / 1e9):,.1f}" if info.get('marketCap') else "N/A",
            "P/E": str(round(info.get('trailingPE', 0), 2)) if info.get('trailingPE') else "N/A", 
            "Div Yield": f"{(info.get('dividendYield', 0) * 100):.1f}%" if info.get('dividendYield') else "0%"
        })
    return pd.DataFrame(data_list)

def build_card_data(ticker, title, symbol, currency):
    df = get_hist_data(ticker, period="3mo")
    if df.empty: return None
    series = df['Close']
    if len(series) < 2: return None
    curr, prev = float(series.iloc[-1]), float(series.iloc[-2])
    chg = curr - prev
    pct = (chg / prev) * 100 if prev != 0 else 0
    return {
        "title": title, "symbol": symbol, "currency": currency,
        "price": f"{curr:,.2f}", "change": f"{chg:+.2f}", "pct": f"{pct:+.2f}%",
        "color_class": "pos" if chg >= 0 else "neg",
        "chart": create_sparkline(series.tail(30), "#39FF14" if chg >= 0 else "#FF007F", 60)
    }

# --- EVENT STUDY METHODOLOGY (DATA TABLES & CHARTS) ---
def generate_trump_analysis():
    # Adjusted labels to match final dashboard terminology
    events_era1 = [
        {"Date": "2018-03-01", "Label": "Steel Tariffs", "Event": "Blanket 25% industrial import tariffs implemented", "Type": "Threat"},
        {"Date": "2018-07-25", "Label": "Car Retraction", "Event": "Transatlantic trade baseline frozen amicably", "Type": "Relief"},
        {"Date": "2019-10-18", "Label": "Olive Oil Tariff", "Event": "Direct 25% tariff on specific regional goods", "Type": "Threat"}
    ]
    events_era2 = [
        {"Date": "2025-04-15", "Label": "Structural Caps", "Event": "Import value boundaries legislated", "Type": "Threat"},
        {"Date": "2025-06-04", "Label": "50% Metal Tariffs", "Event": "Targeted manufacturing duties increased to 50%", "Type": "Threat"},
        {"Date": "2026-03-03", "Label": "Trade Cutoff Threat", "Event": "Trade corridors restricted over defense log-ins", "Type": "Threat"}
    ]

    master_df = get_hist_data('^IBEX', period="10y")
    sp500_df = get_hist_data('^GSPC', period="10y")

    def process_era_tables(start, end, events):
        df = master_df.copy()
        if df.empty: return ""
        
        if start: df = df[df.index >= pd.to_datetime(start)]
        if end: df = df[df.index <= pd.to_datetime(end)]
        if df.empty: return ""

        results = []
        for e in events:
            event_dt = pd.to_datetime(e["Date"])
            avail = df.index[df.index >= event_dt]
            if len(avail) == 0: continue
            
            matched = avail[0]
            try:
                idx = df.index.get_loc(matched)
                if not isinstance(idx, int): idx = int(np.where(df.index == matched)[0][0])
                
                def get_t_val(offset):
                    t_idx = min(idx + offset, len(df) - 1)
                    return float(df['Close'].iloc[t_idx])
                
                p0 = get_t_val(0)
                p3, p10, p30, p60 = get_t_val(3), get_t_val(10), get_t_val(30), get_t_val(60)
                
                calc_imp = lambda px: ((px - p0) / p0) * 100 if p0 != 0 else 0
                
                results.append({
                    "Date": matched.strftime("%Y-%m-%d"), "Policy Milestone": e["Label"],
                    "Price Before": f"€{p0:,.0f}", "Pts Lost (T+3)": f"{p3 - p0:+.0f}",
                    "T+3": f"{calc_imp(p3):+.2f}%", "T+10": f"{calc_imp(p10):+.2f}%",
                    "T+30": f"{calc_imp(p30):+.2f}%", "T+60": f"{calc_imp(p60):+.2f}%"
                })
            except Exception as ex: 
                print(f"[DEBUG] Error indexing {e['Label']}: {ex}")
                pass

        return pd.DataFrame(results).to_html(classes="cyber-table", index=False) if results else ""

    def process_era_chart(start, end, events):
        df = master_df.copy()
        if df.empty: return {}
        if start: df = df[df.index >= pd.to_datetime(start)]
        if end: df = df[df.index <= pd.to_datetime(end)]
        if df.empty: return {}

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df.index.astype(str).tolist(), y=df['Close'].tolist(), 
                                 mode='lines', name='IBEX 35', line=dict(color='#00FFFF', width=2)))

        for e in events:
            color = "#FF007F" if e["Type"] == "Threat" else "#39FF14"
            fig.add_vline(x=e["Date"], line_width=2, line_dash="dash", line_color=color)
            
            fig.add_annotation(x=e["Date"], y=1.05, yref="paper", text=e["Label"], showarrow=False, 
                               font=dict(color=color, size=11, family="Space Grotesk"), 
                               bgcolor="rgba(0,0,0,0.8)", bordercolor=color, borderwidth=1)

        fig.update_layout(
            plot_bgcolor='#050505', paper_bgcolor='#050505', font=dict(color='#E0E0E0', family="Space Grotesk"), 
            xaxis=dict(showgrid=True, gridcolor='#333', zeroline=False), yaxis=dict(showgrid=True, gridcolor='#333', zeroline=False), 
            margin=dict(l=20, r=20, t=50, b=20)
        )
        return json.loads(fig.to_json())

    def process_scatter_matrix(events):
        df_i = master_df.copy()
        df_s = sp500_df.copy()
        if df_i.empty or df_s.empty: return {}
        
        scatter_data = []
        for e in events:
            edt = pd.to_datetime(e["Date"])
            av_i = df_i.index[df_i.index >= edt]
            av_s = df_s.index[df_s.index >= edt]
            if len(av_i) == 0 or len(av_s) == 0: continue
            
            match_i = av_i[0]
            match_s = av_s[0]
            
            try:
                idx_i = df_i.index.get_loc(match_i)
                idx_s = df_s.index.get_loc(match_s)
                if not isinstance(idx_i, int): idx_i = int(np.where(df_i.index == match_i)[0][0])
                if not isinstance(idx_s, int): idx_s = int(np.where(df_s.index == match_s)[0][0])
                
                # T+3 calculation
                p0i = float(df_i['Close'].iloc[idx_i])
                p3i = float(df_i['Close'].iloc[min(idx_i + 3, len(df_i) - 1)])
                pct_i = ((p3i - p0i) / p0i) * 100 if p0i else 0
                
                p0s = float(df_s['Close'].iloc[idx_s])
                p3s = float(df_s['Close'].iloc[min(idx_s + 3, len(df_s) - 1)])
                pct_s = ((p3s - p0s) / p0s) * 100 if p0s else 0
                
                scatter_data.append({"label": e["Label"], "type": e["Type"], "x": pct_s, "y": pct_i})
            except: pass
                
        if not scatter_data: return {}
        
        x_v = [d["x"] for d in scatter_data]
        y_v = [d["y"] for d in scatter_data]
        lbls = [d["label"] for d in scatter_data]
        cols = ["#FF007F" if d["type"] == "Threat" else "#39FF14" for d in scatter_data]
        
        fig = go.Figure()
        
        # Plot event points
        fig.add_trace(go.Scatter(
            x=x_v, y=y_v, mode='markers+text', text=lbls, textposition='top center',
            marker=dict(size=12, color=cols, line=dict(width=1, color='white')),
            name='Political Events', textfont=dict(color='#E0E0E0', family="Space Grotesk")
        ))
        
        # Plot dynamic trendline and calculate R^2
        if len(x_v) > 1:
            slope, intercept = np.polyfit(x_v, y_v, 1)
            lx = np.array([min(x_v)-1, max(x_v)+1])
            ly = slope * lx + intercept
            
            # Correlation coefficients
            r_mat = np.corrcoef(x_v, y_v)
            r_val = r_mat[0,1] if not np.isnan(r_mat[0,1]) else 0
            r2 = r_val**2
            
            fig.add_trace(go.Scatter(
                x=lx.tolist(), y=ly.tolist(), mode='lines', 
                line=dict(color='#E0E0E0', dash='dash', width=1),
                name=f'Trendline (R² = {r2:.2f})'
            ))
            fig.update_layout(title=dict(text=f'Contagion Correlation (Pearson r = {r_val:.2f})', font=dict(color='#E0E0E0', size=14), x=0.5))

        fig.update_layout(
            plot_bgcolor='#050505', paper_bgcolor='#050505', font=dict(color='#E0E0E0', family="Space Grotesk"),
            xaxis=dict(title='US Sneeze: S&P 500 Reaction (%)', showgrid=True, gridcolor='#333', zeroline=True, zerolinecolor='#555'),
            yaxis=dict(title='Spanish Flu: IBEX 35 Reaction (%)', showgrid=True, gridcolor='#333', zeroline=True, zerolinecolor='#555'),
            margin=dict(l=60, r=20, t=50, b=50),
            legend=dict(yanchor="top", y=0.99, xanchor="right", x=0.99, bgcolor="rgba(0,0,0,0.5)", bordercolor="#FF007F", borderwidth=1)
        )
        return json.loads(fig.to_json())

    # Build everything
    table1 = process_era_tables('2016-01-01', '2021-01-01', events_era1)
    table2 = process_era_tables('2024-01-01', '2026-12-31', events_era2)
    
    chart1 = process_era_chart('2016-01-01', '2021-01-01', events_era1)
    chart2 = process_era_chart('2024-01-01', '2026-12-31', events_era2)
    chart3 = process_scatter_matrix(events_era1 + events_era2)
    
    return {"table1": table1, "table2": table2, "chart1": chart1, "chart2": chart2, "chart3": chart3}

@app.route('/')
def index():
    us_bb = [build_card_data('^GSPC', "S&P 500 Index", "500", "$"), build_card_data('^DJI', "Dow Jones", "30", "$"), build_card_data('^NDX', "Nasdaq 100", "100", "$")]
    us_mom = [build_card_data('AAPL', "Apple Inc", "AAPL", "$"), build_card_data('MSFT', "Microsoft", "MSFT", "$"), build_card_data('NVDA', "Nvidia", "NVDA", "$"), build_card_data('TSLA', "Tesla", "TSLA", "$")]
    df_us = fetch_screener_data(('AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'TSLA', 'AVGO', 'LLY', 'JPM', 'XOM', 'WMT'))
    us_tbl = df_us.to_html(classes="cyber-table", index=False, escape=False) if not df_us.empty else ""

    es_bb = [build_card_data('^IBEX', "IBEX 35", "35", "€")]
    es_mom = [build_card_data('ITX.MC', "Inditex", "ITX", "€"), build_card_data('SAN.MC', "Santander", "SAN", "€"), build_card_data('IBE.MC', "Iberdrola", "IBE", "€"), build_card_data('BBVA.MC', "BBVA", "BBVA", "€")]
    df_es = fetch_screener_data(('^IBEX', 'ITX.MC', 'SAN.MC', 'IBE.MC', 'BBVA.MC', 'TEF.MC', 'REP.MC', 'AENA.MC', 'FER.MC', 'CABK.MC', 'AMS.MC'))
    es_tbl = df_es.to_html(classes="cyber-table", index=False, escape=False) if not df_es.empty else ""

    trump_data = generate_trump_analysis()

    return render_template('index.html', 
                           us_bigboard=[c for c in us_bb if c], us_momentum=[c for c in us_mom if c], us_table=us_tbl,
                           es_bigboard=[c for c in es_bb if c], es_momentum=[c for c in es_mom if c], es_table=es_tbl,
                           trump=trump_data)

@app.route('/api/predict', methods=['POST'])
def api_predict():
    data = request.json
    mood = data.get('mood', "Normal"); risk = data.get('risk', "Mild"); time_frame = int(data.get('time', 2))
    if "Strong" in mood: ret, vol = 0.08, 0.10
    elif "Normal" in mood: ret, vol = 0.04, 0.12
    else: ret, vol = -0.02, 0.18
    if "Calm" in risk: ret += 0.02; vol -= 0.02
    elif "Mild" in risk: ret -= 0.03; vol += 0.04
    else: ret -= 0.08; vol += 0.10

    S0 = 11500.0
    months = int(time_frame * 12)
    t_ax = np.linspace(0, time_frame, months + 1)
    exp_p, opt_p, dng_p = [S0], [S0], [S0]
    dt = 1/12
    for _ in range(months):
        gf = np.exp((ret - 0.5 * vol**2) * dt)
        exp_p.append(exp_p[-1] * gf)
        opt_p.append(opt_p[-1] * gf * np.exp(vol * np.sqrt(dt) * 1.0))
        dng_p.append(dng_p[-1] * gf * np.exp(vol * np.sqrt(dt) * -1.5))

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=t_ax, y=opt_p, mode='lines+markers', name='Target Ceiling', line=dict(color='#39FF14', width=3)))
    fig.add_trace(go.Scatter(x=t_ax, y=exp_p, mode='lines+markers', name='Baseline Expected Trend', line=dict(color='#00FFFF', width=4)))
    fig.add_trace(go.Scatter(x=t_ax, y=dng_p, mode='lines+markers', name='Structural Risk Boundary', line=dict(color='#FF007F', width=3)))
    
    fig.update_layout(
        plot_bgcolor='#050505', paper_bgcolor='#050505', font=dict(color='#E0E0E0', family="Space Grotesk"), 
        xaxis=dict(showgrid=True, gridcolor='#333', zeroline=False), yaxis=dict(showgrid=True, gridcolor='#333', zeroline=False), 
        margin=dict(l=20, r=20, t=20, b=20)
    )
    return jsonify({"chart": json.loads(fig.to_json()), "expected": f"€{exp_p[-1]:,.0f}", "danger": f"€{dng_p[-1]:,.0f}"})

@app.route('/api/bias', methods=['POST'])
def api_bias():
    data = request.json
    lookback = data.get('lookback', "Post-2016"); swan = data.get('swan', "None"); rate = int(data.get('rate', 100)) / 100.0
    
    S0, N = 1000000, 15000
    np.random.seed(42)
    b_ret = np.random.normal(0.08, 0.10, N)
    b_var = np.percentile(S0 * (1 + b_ret), 5)
    
    if "Post-2016" in lookback: mu, sig = 0.08, 0.10
    elif "20-Year" in lookback: mu, sig = 0.05, 0.16 
    else: mu, sig = 0.04, 0.22 
        
    np.random.seed(42)
    s_ret = np.random.normal(mu, sig, N)
    if "Pandemic" in swan: s_ret[np.random.choice(N, int(N*0.02*rate), False)] -= 0.25
    elif "Bank" in swan: s_ret[np.random.choice(N, int(N*0.03*rate), False)] -= 0.35
    elif "Blockade" in swan: s_ret[np.random.choice(N, int(N*0.015*rate), False)] -= 0.45

    s_vals = S0 * (1 + s_ret)
    t_var = np.percentile(s_vals, 5)

    fig = go.Figure()
    fig.add_trace(go.Histogram(x=s_vals.tolist(), nbinsx=100, marker_color='#00FFFF', opacity=0.6))
    fig.add_vline(x=b_var, line_width=3, line_dash="dash", line_color="#39FF14")
    fig.add_vline(x=t_var, line_width=3, line_dash="dash", line_color="#FF007F")
    
    fig.update_layout(
        plot_bgcolor='#050505', paper_bgcolor='#050505', font=dict(color='#E0E0E0', family="Space Grotesk"), 
        xaxis=dict(showgrid=True, gridcolor='#333', zeroline=False), yaxis=dict(showticklabels=False, showgrid=False, zeroline=False), 
        margin=dict(l=20, r=20, t=20, b=20)
    )
    
    blind_spot = abs(t_var - b_var) if t_var < b_var else 0
    return jsonify({"chart": json.loads(fig.to_json()), "r_var": f"€{b_var:,.0f}", "t_var": f"€{t_var:,.0f}", "blind": f"€{blind_spot:,.0f}"})

if __name__ == '__main__':
    app.run(debug=True)