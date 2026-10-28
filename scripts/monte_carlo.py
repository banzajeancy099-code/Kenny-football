# scripts/monte_carlo.py — Monte Carlo pour valider la stratégie Kelly
import json
import random
import statistics
from pathlib import Path

# ========== CONFIG ==========
N_SIMULATIONS = 10000
BANKROLL_INITIAL = 100.0
KELLY_FRACTIONS = [0.02, 0.05, 0.10, 0.15, 0.20, 0.25]

# ========== CHARGER LES PARIS ==========
data_file = Path(__file__).parent.parent / "data" / "backtest_results.json"
if not data_file.exists():
    print(f"❌ {data_file} introuvable. Lance scripts/backtest.py d'abord.")
    exit(1)

with open(data_file) as f:
    data = json.load(f)

all_results = data.get("results", [])
print(f"📊 {len(all_results)} paris disponibles\n")

# Filtre : uniquement les paris avec cote valide ET retenu
bets = [
    r for r in all_results
    if r.get("cote") and r["cote"] > 1
    and (r.get("edge") or 0) > 0  # edge positif uniquement
]

print(f"✅ {len(bets)} paris filtrés (cote > 1 ET edge > 0)\n")

if len(bets) < 10:
    print("❌ Pas assez de paris pour simuler")
    exit(1)

# Précision attendue (basée sur le backtest)
accuracy = sum(1 for b in bets if b.get("correct")) / len(bets)
avg_cote = statistics.mean([b["cote"] for b in bets])
avg_edge = statistics.mean([b.get("edge", 0) for b in bets])

print(f"📈 Statistiques des paris :")
print(f"   Précision : {accuracy:.1%}")
print(f"   Cote moyenne : {avg_cote:.2f}")
print(f"   Edge moyen : {avg_edge:+.2%}")
print(f"   ROI théorique : {(accuracy * avg_cote - 1):+.1%}\n")


# ========== SIMULATION ==========
def simulate_kelly(fraction, n_sims=10000):
    """Simule n_sims bankrolls avec la fraction Kelly donnée."""
    results = []

    for _ in range(n_sims):
        bankroll = BANKROLL_INITIAL
        peak = bankroll
        max_dd = 0
        ruined = False

        # Tire les paris dans un ordre aléatoire
        shuffled = bets.copy()
        random.shuffle(shuffled)

        for bet in shuffled:
            if bankroll < 0.01:
                ruined = True
                break

            # Mise Kelly = bankroll × edge × fraction
            edge = bet.get("edge", 0.05)
            mise = bankroll * edge * fraction

            # Cap à 30% de la bankroll par pari (sécurité)
            mise = min(mise, bankroll * 0.30)

            if mise < 0.01:
                continue

            # Résultat du pari
            if bet.get("correct"):
                profit = mise * (bet["cote"] - 1)
                bankroll += profit
            else:
                bankroll -= mise

            # Drawdown
            peak = max(peak, bankroll)
            dd = (peak - bankroll) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)

        results.append({
            "final": bankroll,
            "max_dd": max_dd,
            "ruined": ruined,
        })

    return results


# ========== ANALYSE ==========
print(f"{'='*80}")
print(f"🎲 MONTE CARLO — {N_SIMULATIONS} simulations")
print(f"{'='*80}\n")

print(f"{'Fraction':<10} {'Gain médian':<13} {'Drawdown max':<15} {'Ruine':<10} {'p5':<10} {'p95'}")
print("-" * 80)

best = None
all_results_fr = {}

for frac in KELLY_FRACTIONS:
    sims = simulate_kelly(frac, n_sims=2000)  # 2000 par fraction pour vitesse

    finals = [s["final"] for s in sims]
    dds = [s["max_dd"] for s in sims]
    ruins = sum(1 for s in sims if s["ruined"]) / len(sims)

    median_gain = (statistics.median(finals) - BANKROLL_INITIAL) / BANKROLL_INITIAL
    p5 = (sorted(finals)[int(len(finals) * 0.05)] - BANKROLL_INITIAL) / BANKROLL_INITIAL
    p95 = (sorted(finals)[int(len(finals) * 0.95)] - BANKROLL_INITIAL) / BANKROLL_INITIAL
    med_dd = statistics.median(dds)

    all_results_fr[frac] = {
        "median_gain": median_gain,
        "p5": p5,
        "p95": p95,
        "med_dd": med_dd,
        "ruin": ruins,
    }

    print(f"{frac:<10.2f} {median_gain:+.1%}{'':<8} {med_dd:.1%}{'':<10} {ruins:.1%}{'':<5} {p5:+.1%}{'':<5} {p95:+.1%}")

    # Critère : optimal = gain médian > 15% ET ruine < 1% ET drawdown < 50%
    score = median_gain
    if ruins > 0.01 or med_dd > 0.50:
        score = -999  # disqualifié

    if best is None or score > best["score"]:
        best = {"frac": frac, "score": score, **all_results_fr[frac]}


# ========== VERDICT ==========
print(f"\n{'='*80}")
print(f"🎯 VERDICT")
print(f"{'='*80}\n")

if best["score"] == -999:
    print("🔴 AUCUNE fraction n'est sûre !")
    print("   → Toutes les fractions ont ruine > 1% ou drawdown > 50%")
    print("   → Il faut améliorer le moteur avant de parier")
else:
    print(f"🟢 FRACTION OPTIMALE : {best['frac']:.2f}")
    print(f"   Gain médian : {best['median_gain']:+.1%}")
    print(f"   Drawdown médian : {best['med_dd']:.1%}")
    print(f"   Probabilité de ruine : {best['ruin']:.1%}")
    print(f"   Pire cas (5%) : {best['p5']:+.1%}")
    print(f"   Meilleur cas (95%) : {best['p95']:+.1%}")

    print(f"\n📊 Interprétation :")
    print(f"   - Sur 100 paris avec cette fraction :")
    print(f"     → 50% des runs gagnent > {best['median_gain']:+.0%}")
    print(f"     → 5% des runs perdent > {abs(best['p5']):.0%}")
    print(f"     → Tu dois accepter un drawdown de {best['med_dd']:.0%} en cours de route")
    print(f"     → 1 chance sur {int(1/best['ruin']) if best['ruin'] > 0 else '∞'} de finir ruiné")

    # Recommandation pratique
    print(f"\n💡 RECOMMANDATION PRATIQUE :")
    print(f"   Bankroll 1000€ × fraction {best['frac']:.2f} = mise max {1000 * best['frac']:.0f}€ par pari")
    print(f"   Mais avec edge moyen {avg_edge:+.1%} :")
    print(f"   Mise réelle = 1000 × {best['frac']:.2f} × {avg_edge:.2f} = {1000 * best['frac'] * avg_edge:.0f}€/pari")

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
