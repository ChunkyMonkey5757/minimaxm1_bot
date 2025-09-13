# analyze_trades.py
import csv
import matplotlib.pyplot as plt

def analyze_trades(file_path="data/trades.csv", out_file="equity_curve.png"):
    trades = []
    with open(file_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            trades.append(row)

    if not trades:
        print("No trades found.")
        return

    wins, losses = 0, 0
    total_pnl = 0.0
    equity = []

    for row in trades:
        pnl = float(row["pnl"])
        total_pnl += pnl
        equity.append(float(row["equity"]))
        if pnl > 0:
            wins += 1
        elif pnl < 0:
            losses += 1

    # Print stats
    print("📊 Trade Summary")
    print(f"Total trades: {len(trades)}")
    print(f"Wins: {wins} | Losses: {losses}")
    print(f"Net PnL: {total_pnl:.2f}")
    print(f"Final Equity: {equity[-1]:.2f}")
    print(f"Max Equity: {max(equity):.2f} | Min Equity: {min(equity):.2f}")

    # Plot equity curve
    plt.figure(figsize=(10, 5))
    plt.plot(equity, label="Equity Curve", linewidth=2)
    plt.xlabel("Trade #")
    plt.ylabel("Equity")
    plt.title("MiniMax Bot – Equity Curve")
    plt.legend()
    plt.grid(True)

    # Save chart to file
    plt.savefig(out_file, dpi=150)
    print(f"✅ Equity curve saved to {out_file}")

    # Also show interactively (if supported)
    plt.show()

if __name__ == "__main__":
    analyze_trades()
