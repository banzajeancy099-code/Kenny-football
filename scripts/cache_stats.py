#!/usr/bin/env python3
"""Affiche les stats du cache Bzzoiro."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.clients.cache import stats

s = stats("bzzoiro")
print(f"Fichiers : {s['files']}")
print(f"Taille   : {s['size_mb']} MB")
