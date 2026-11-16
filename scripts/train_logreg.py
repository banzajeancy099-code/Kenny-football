"""
Régression logistique manuelle (NumPy) pour prédire over_target.
Pas de scikit-learn, pas de XGBoost, pas de LightGBM.
"""
import os
import sys
import pickle
import numpy as np
import psycopg2
import psycopg2.extras

sys.path.insert(0, 'src')


def sigmoid(z):
    return 1 / (1 + np.exp(-np.clip(z, -500, 500)))


def train_logreg(X, y, lr=0.01, epochs=1000):
    """Entraîne une régression logistique par gradient descent."""
    n_samples, n_features = X.shape
    weights = np.zeros(n_features)
    bias = 0.0
    
    for epoch in range(epochs):
        z = X @ weights + bias
        y_pred = sigmoid(z)
        
        # Gradient
        dw = (1 / n_samples) * (X.T @ (y_pred - y))
        db = (1 / n_samples) * np.sum(y_pred - y)
        
        # Update
        weights -= lr * dw
        bias -= lr * db
        
        if epoch % 200 == 0:
            loss = -np.mean(y * np.log(y_pred + 1e-15) + (1 - y) * np.log(1 - y_pred + 1e-15))
            print(f"  Epoch {epoch} : loss={loss:.4f}", flush=True)
    
    return weights, bias


def predict_proba(X, weights, bias):
    return sigmoid(X @ weights + bias)


def roc_auc_manual(y_true, y_score):
    """Calcule l'AUC manuellement."""
    pos = y_score[y_true == 1]
    neg = y_score[y_true == 0]
    if len(pos) == 0 or len(neg) == 0:
        return 0.5
    # Compare toutes les paires (pos vs neg)
    auc = 0
    for p in pos:
        auc += np.sum(p > neg) + 0.5 * np.sum(p == neg)
    return auc / (len(pos) * len(neg))


def main():
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT 
            form_gf_5_home,
            form_gf_5_away,
            form_ga_5_home,
            form_ga_5_away,
            proba_poisson,
            over_target,
            date
        FROM k_features
        WHERE form_gf_5_home IS NOT NULL
          AND form_gf_5_away IS NOT NULL
          AND over_target IS NOT NULL
        ORDER BY date
    """)
    rows = cur.fetchall()
    print(f"=== {len(rows)} matchs chargés ===\n", flush=True)

    X = []
    y = []
    dates = []
    for r in rows:
        X.append([
            r["form_gf_5_home"] or 0,
            r["form_gf_5_away"] or 0,
            r["form_ga_5_home"] or 0,
            r["form_ga_5_away"] or 0,
        ])
        y.append(r["over_target"])
        dates.append(r["date"])

    X = np.array(X)
    y = np.array(y)
    dates = np.array(dates)

    # Normalise
    X_mean = X.mean(axis=0)
    X_std = X.std(axis=0) + 1e-8
    X_norm = (X - X_mean) / X_std

    # Split
    split_idx = int(len(rows) * 0.7)
    X_train, X_test = X_norm[:split_idx], X_norm[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]
    
    print(f"Train : {len(X_train)} matchs")
    print(f"Test : {len(X_test)} matchs\n")

    # Entraîne
    print("Entraînement...", flush=True)
    weights, bias = train_logreg(X_train, y_train, lr=0.1, epochs=1000)

    # Prédictions
    y_pred_proba = predict_proba(X_test, weights, bias)
    y_pred = (y_pred_proba > 0.5).astype(int)

    # Métriques
    auc = roc_auc_manual(y_test, y_pred_proba)
    acc = np.mean(y_pred == y_test)

    print(f"\n=== Métriques ===")
    print(f"  AUC : {auc:.3f}")
    print(f"  Accuracy : {acc:.1%}")

    # Pas de comparaison Poisson (retiré pour éviter data leakage)

    # Sauvegarde
    os.makedirs("models", exist_ok=True)
    with open("models/logreg_over.pkl", "wb") as f:
        pickle.dump({"weights": weights, "bias": bias, "mean": X_mean, "std": X_std}, f)
    print(f"\n✅ Modèle sauvegardé : models/logreg_over.pkl")

    conn.close()


if __name__ == "__main__":
    main()
