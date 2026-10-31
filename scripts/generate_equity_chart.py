import json
import matplotlib.pyplot as plt
import numpy as np

def generate_chart():
    with open("docs/portfolio_backtest_results.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    equity = data["portfolio_equity_curve"]
    summary = data["performance_metrics"]
    cap = data["capital_summary"]

    plt.style.use("dark_background")
    fig, ax = plt.subplots(figsize=(10, 5), dpi=150)

    final_cap = cap["final_capital_inr"]
    init_cap = cap["initial_capital_inr"]
    win_rate = summary["win_rate_pct"]
    pf = summary["profit_factor"]
    total_trades = summary.get("total_trades", len(data.get("trades", [])))

    ax.plot(equity, color="#00E676", linewidth=2.0, label=f"Apex Quant Portfolio (Final: INR {final_cap:,.2f})")
    ax.axhline(init_cap, color="#757575", linestyle="--", alpha=0.7, label=f"Initial Capital (INR {init_cap:,.2f})")

    ax.set_title(f"Apex Quant Out-of-Sample Portfolio Equity Curve (50 Equities, {total_trades} Trades, Win Rate {win_rate}%, PF {pf})", fontsize=11, fontweight="bold", color="#E0E0E0", pad=12)
    ax.set_xlabel("Bar Sequence (Out-of-Sample Time Horizon)", fontsize=10, color="#B0B0B0")
    ax.set_ylabel("Portfolio Equity (INR)", fontsize=10, color="#B0B0B0")
    ax.grid(True, linestyle=":", alpha=0.3, color="#424242")
    ax.legend(loc="upper left", frameon=True, facecolor="#1E1E1E", edgecolor="#333333")

    ax.get_yaxis().set_major_formatter(plt.FuncFormatter(lambda x, loc: f"INR {x:,.0f}"))

    plt.tight_layout()
    from pathlib import Path
    try:
        plt.savefig("assets/equity_curve.png", dpi=150, facecolor="#121212")
        print("assets/equity_curve.png generated successfully!")
    except PermissionError:
        scratch_png = Path(r"C:\Users\ayush\.gemini\antigravity\brain\2e7c8686-c335-4738-b15b-91c1b2fee4e7\scratch\equity_curve.png")
        scratch_png.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(str(scratch_png), dpi=150, facecolor="#121212")
        print(f"Saved chart to scratch: {scratch_png}")

if __name__ == "__main__":
    generate_chart()

