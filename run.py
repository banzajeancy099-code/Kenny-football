"""Lanceur Flask Kenny Football."""
import os
import sys

from app import app

if __name__ == "__main__":
    if not os.environ.get("BZZOIRO_API_KEY"):
        print("❌ BZZOIRO_API_KEY manquante")
        sys.exit(1)

    port = int(os.environ.get("PORT", 3000))
    print(f"🚀 Kenny Football sur http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
