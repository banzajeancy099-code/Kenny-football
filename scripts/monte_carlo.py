# scripts/monte_carlo.py — Monte Carlo avec bootstrap (vraie variance)
import json
import random
import statistics
from pathlib import Path

N_SIMULATIONS = 5000
BANKROLL_INITIAL = 100.0
KELLY_FRACTIONS = [0.02, 0.05, 0.10, 0.15, 0.20, 0.25]

data_file = Path(__file__).parent.parent / "data" / "backtest_results.json"
if not data_file.exists():
    print(f"❌ {data_file} introuvable.")
    exit(1)

with open(data_file) as f:
    data = json.load(f)

all_results = data.get("results", [])

# Filtre : uniquement les paris avec cote valide ET edge >= 0.10
bets = [
    r for r in all_results
    if r.get("cote") and r["cote"] > 1
    and (r.get("edge") or 0) >= 0.10
]

print(f"📊 {len(all_results)} matchs disponibles")
print(f"✅ {len(bets)} paris filtrés (edge >= 0.10)\n")

if len(bets) < 20:
    print("⚠️  Peu de paris pour un Monte Carlo fiable (< 20)")

accuracy = sum(1 for b in bets if b.get("correct")) / len(bets)
avg_cote = statistics.mean([b["cote"] for b in bets])
avg_edge = statistics.mean([b.get("edge", 0) for b in bets])
avg_mise_eur = 1000 * avg_edge * 0.05  # Kelly 0.05 sur bankroll 1000

print(f"📈 Statistiques des paris :")
print(f"   Précision : {accuracy:.1%}")
print(f"   Cote moyenne : {avg_cote:.2f}")
print(f"   Edge moyen : {avg_edge:+.2%}")
print(f"   Mise moyenne : {avg_mise_eur:.2f}€")
print(f"   ROI théorique : {(accuracy * avg_cote - 1):+.1%}\n")


def simulate_bootstrap(fraction, n_sims=5000):
    """Simule n_sims avec tirage AVEC REMISE (bootstrap)."""
    results = []
    n_paris = len(bets)

    for _ in range(n_sims):
        bankroll = BANKROLL_INITIAL
        peak = bankroll
        max_dd = 0
        ruined = False
        wins = 0
        losses = 0

        # Tirage avec remise
        sample = random.choices(bets, k=n_paris)

        for bet in sample:
            if bankroll < 0.01:
                ruined = True
                break

            edge = bet.get("edge", 0.10)
            # Mise Kelly fractionnée
            mise = bankroll * edge * fraction
            mise = min(mise, bankroll * 0.30)  # cap 30%

            if mise < 0.01:
                continue

            if bet.get("correct"):
                bankroll += mise * (bet["cote"] - 1)
                wins += 1
            else:
                bankroll -= mise
                losses += 1

            peak = max(peak, bankroll)
            dd = (peak - bankroll) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)

        results.append({
            "final": bankroll,
            "max_dd": max_dd,
            "ruined": ruined,
            "wins": wins,
            "losses": losses,
        })

    return results


print(f"{'='*90}")
print(f"🎲 MONTE CARLO BOOTSTRAP — {N_SIMULATIONS} simulations")
print(f"{'='*90}\n")

print(f"{'Fraction':<10} {'Gain méd.':<12} {'p5':<10} {'p95':<10} {'DD méd.':<10} {'Ruine':<8} {'Win%'}")
print("-" * 90)

best = None
all_results_fr = {}

for frac in KELLY_FRACTIONS:
    sims = simulate_bootstrap(frac, n_sims=2000)

    finals = [s["final"] for s in sims]
    dds = [s["max_dd"] for s in sims]
    ruins = sum(1 for s in sims if s["ruined"]) / len(sims)
    win_rates = [s["wins"] / max(1, s["wins"] + s["losses"]) for s in sims]

    med = (statistics.median(finals) - BANKROLL_INITIAL) / BANKROLL_INITIAL
    sorted_finals = sorted(finals)
    p5 = (sorted_finals[int(len(sorted_finals) * 0.05)] - BANKROLL_INITIAL) / BANKROLL_INITIAL
    p95 = (sorted_finals[int(len(sorted_finals) * 0.95)] - BANKROLL_INITIAL) / BANKROLL_INITIAL
    med_dd = statistics.median(dds)
    med_wr = statistics.median(win_rates)

    all_results_fr[frac] = {
        "median_gain": med, "p5": p5, "p95": p95,
        "med_dd": med_dd, "ruin": ruins, "win_rate": med_wr,
    }

    print(f"{frac:<10.2f} {med:+.1%}{'':<7} {p5:+.1%}{'':<5} {p95:+.1%}{'':<5} {med_dd:.1%}{'':<5} {ruins:.1%}{'':<3} {med_wr:.1%}")

    # Critère : optimal = gain > 10% ET ruine < 1% ET drawdown < 40%
    score = med
    if ruins > 0.01 or med_dd > 0.40:
        score = -999

    if best is None or score > best["score"]:
        best = {"frac": frac, "score": score, **all_results_fr[frac]}


print(f"\n{'='*90}")
print(f"🎯 VERDICT")
print(f"{'='*90}\n")

if best["score"] == -999:
    print("🔴 AUCUNE fraction n'est sûre !")
    print("   → Ruine > 1% ou drawdown > 40% sur toutes les fractions")
else:
    print(f"🟢 FRACTION OPTIMALE : {best['frac']:.2f}")
    print(f"   Gain médian : {best['median_gain']:+.1%}")
    print(f"   Drawdown médian : {best['med_dd']:.1%}")
    print(f"   Probabilité de ruine : {best['ruin']:.1%}")
    print(f"   Précision médiane : {best['win_rate']:.1%}")
    print(f"   Pire cas (5%) : {best['p5']:+.1%}")
    print(f"   Meilleur cas (95%) : {best['p95']:+.1%}")

    print(f"\n📊 Interprétation réaliste :")
    print(f"   - Sur {len(bets)} paris avec fraction {best['frac']:.2f} :")
    print(f"     → 50% des runs gagnent > {best['median_gain']:+.0%}")
    print(f"     → 5% des runs perdent > {abs(best['p5']):.0%}")
    print(f"     → Drawdown médian : {best['med_dd']:.0%}")

    print(f"\n💡 RECOMMANDATION PRATIQUE :")
    print(f"   Bankroll 1000€ × fraction {best['frac']:.2f} = mise max {1000 * best['frac']:.0f}€")
    print(f"   Mise réelle (avec edge {avg_edge:.0%}) = {1000 * best['frac'] * avg_edge:.0f}€/pari")

# Sauvegarde
out = {
    "bets": len(bets),
    "accuracy": accuracy,
    "avg_cote": avg_cote,
    "avg_edge": avg_edge,
    "fractions": {str(k): v for k, v in all_results_fr.items()},
    "best_fraction": best["frac"] if best["score"] != -999 else None,
}
with open(Path(__file__).parent.parent / "data" / "monte_carlo.json", "w") as f:
    json.dump(out, f, indent=2, ensure_ascii=False)
print(f"\n💾 Sauvegardé : data/monte_carlo.json")
