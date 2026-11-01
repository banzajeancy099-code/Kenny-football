#!/usr/bin/env python3
"""Test l'impact d'une couche en la désactivant.

Usage:
    python scripts/test_layer_impact.py --layer 34
"""
import os
import sys
import json
import argparse
import subprocess

WEIGHTS_PATH = "config/weights.json"
BACKUP_PATH = "config/weights.json.test_backup"


def load_weights():
    with open(WEIGHTS_PATH, "r") as f:
        return json.load(f)


def save_weights(w):
    with open(WEIGHTS_PATH, "w") as f:
        json.dump(w, f, indent=2)


def run_backtest():
    """Lance le backtest et retourne le résultat."""
    print("Lancement du backtest...")
    env = os.environ.copy()
    result = subprocess.run(
        ["python", "scripts/backtest.py"],
        capture_output=True,
        text=True,
        env=env,
        timeout=7200,
    )
    return result.returncode == 0


def analyze_results():
    """Analyse les résultats du backtest."""
    with open("data/backtest_results.json", "r") as f:
        data = json.load(f)
    
    results = data.get("results", [])
    retenus = [m for m in results if m.get("retenu")]
    
    if not retenus:
        return {
            "total": len(results),
            "paris": 0,
            "precision": 0,
            "roi": 0,
            "profit": 0,
            "mise": 0,
        }
    
    correct = sum(1 for m in retenus if m.get("correct"))
    profit = 0
    mise = 0
    for m in retenus:
        mm = m.get("mise_kelly", 0)
        c = m.get("cote", 1.5) or 1.5
        mise += mm
        profit += (mm*c - mm) if m.get("correct") else -mm
    
    return {
        "total": len(results),
        "paris": len(retenus),
        "precision": correct / len(retenus) * 100,
        "roi": (profit / mise * 100) if mise else 0,
        "profit": profit,
        "mise": mise,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--layer", type=int, required=True, help="ID de la couche à désactiver")
    args = parser.parse_args()
    
    layer_id = str(args.layer)
    
    # 1. Sauvegarder les poids
    weights = load_weights()
    if layer_id not in weights:
        print(f"ATTENTION L{layer_id} absente de weights.json")
        print(f"Couches actuelles : {list(weights.keys())}")
        sys.exit(1)
    
    original_weight = weights[layer_id]
    with open(BACKUP_PATH, "w") as f:
        json.dump(weights, f, indent=2)
    
    print(f"Couche L{layer_id} (poids actuel = {original_weight})")
    print(f"=" * 60)
    
    # 2. Désactiver la couche
    weights[layer_id] = 0
    save_weights(weights)
    print(f"L{layer_id} désactivée (poids 0)")
    
    # 3. Lancer le backtest
    if not run_backtest():
        print("ECHEC du backtest")
        # Restaurer
        save_weights(json.load(open(BACKUP_PATH)))
        return
    
    # 4. Analyser
    result = analyze_results()
    
    print()
    print("=" * 60)
    print(f"RESULTATS SANS L{layer_id}")
    print("=" * 60)
    print(f"Matchs    : {result['total']}")
    print(f"Paris     : {result['paris']}")
    print(f"Précision : {result['precision']:.1f}%")
    print(f"ROI       : {result['roi']:+.1f}%")
    print(f"Profit    : {result['profit']:+.2f}€")
    
    # 5. Restaurer
    save_weights(json.load(open(BACKUP_PATH)))
    print()
    print(f"L{layer_id} restaurée (poids {original_weight})")


if __name__ == "__main__":
    main()
