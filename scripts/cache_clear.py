#!/usr/bin/env python3
"""Vide le cache Bzzoiro. Usage: python scripts/cache_clear.py [--older-than 24]"""
import sys, os, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.clients.cache import clear

parser = argparse.ArgumentParser()
parser.add_argument("--older-than", type=int, default=None, help="Heures (défaut: tout)")
args = parser.parse_args()

clear("bzzoiro", older_than_hours=args.older_than)
print("✅ Cache vidé")
