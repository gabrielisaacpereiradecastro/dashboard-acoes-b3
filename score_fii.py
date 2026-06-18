"""
Classificação e score para Fundos de Investimento Imobiliário (FIIs).
"""
from __future__ import annotations
from typing import Optional
from config import BG_COLORS

FII_WEIGHTS: dict[str, float] = {
    "dividend_yield": 0.30,
    "pvp":            0.25,
    "vacancy_pct":    0.20,
    "liquidity":      0.15,
    "delinquency_pct":0.10,
}

FII_CLASS_POINTS: dict[str, int] = {
    "Excelente":  100,
    "Bom":        75,
    "Razoável":   50,
    "Atenção":    25,
    "Proibitivo": 0,
}

FII_SCORE_LEVELS = [
    (80, 101, "Excelente"),
    (60,  80, "Bom"),
    (40,  60, "Razoável"),
    (20,  40, "Atenção"),
    (0,   20, "Evitar"),
]


def classify_fii_dy(value) -> tuple[str, str]:
    if value is None or value > 100:  # DY acima de 100% é dado corrompido
        return "ND", "N/D"
    d = f"{value:.1f}%"
    if value >= 12:    return "Excelente", d
    elif value >= 8:   return "Bom", d
    elif value >= 6:   return "Razoável", d
    elif value >= 4:   return "Atenção", d
    else:              return "Proibitivo", d


def classify_fii_pvp(value) -> tuple[str, str]:
    if value is None:
        return "ND", "N/D"
    d = f"{value:.2f}x"
    if value < 0.90:     return "Excelente", d
    elif value <= 1.05:  return "Bom", d
    elif value <= 1.15:  return "Razoável", d
    elif value <= 1.30:  return "Atenção", d
    else:                return "Proibitivo", d


def classify_fii_vacancy(value) -> tuple[str, str]:
    if value is None:
        return "ND", "N/D"
    d = f"{value:.1f}%"
    if value < 3:       return "Excelente", d
    elif value < 8:     return "Bom", d
    elif value < 15:    return "Razoável", d
    elif value < 25:    return "Atenção", d
    else:               return "Proibitivo", d


def classify_fii_delinquency(value) -> tuple[str, str]:
    if value is None:
        return "ND", "N/D"
    d = f"{value:.1f}%"
    if value < 1:       return "Excelente", d
    elif value < 3:     return "Bom", d
    elif value < 6:     return "Razoável", d
    elif value < 10:    return "Atenção", d
    else:               return "Proibitivo", d


def _fmt_brl(v: float) -> str:
    if v >= 1_000_000:
        return f"R$ {v / 1_000_000:.1f}M"
    elif v >= 1_000:
        return f"R$ {v / 1_000:.0f}k"
    return f"R$ {v:.0f}"


def classify_fii_liquidity(value) -> tuple[str, str]:
    if value is None:
        return "ND", "N/D"
    d = _fmt_brl(value)
    if value > 5_000_000:    return "Excelente", d
    elif value > 3_000_000:  return "Bom", d
    elif value > 1_000_000:  return "Razoável", d
    elif value > 500_000:    return "Atenção", d
    else:                    return "Proibitivo", d


FII_CLASSIFIERS = {
    "dividend_yield":  classify_fii_dy,
    "pvp":             classify_fii_pvp,
    "vacancy_pct":     classify_fii_vacancy,
    "liquidity":       classify_fii_liquidity,
    "delinquency_pct": classify_fii_delinquency,
}


def classify_all_fii(fii: dict) -> dict[str, tuple[str, str]]:
    return {
        ind: fn(fii.get(ind))
        for ind, fn in FII_CLASSIFIERS.items()
    }


def calculate_fii_score(fii: dict) -> tuple[Optional[float], str, dict]:
    """Retorna (score, label, breakdown) para um FII."""
    classifications = classify_all_fii(fii)
    breakdown: dict = {}
    weighted_sum = 0.0
    total_weight = 0.0

    for ind, (cls, disp) in classifications.items():
        w = FII_WEIGHTS[ind]
        if cls in ("ND", "NA"):
            breakdown[ind] = {"classification": cls, "display": disp,
                               "points": None, "weight": w, "contribution": None}
            continue
        pts = FII_CLASS_POINTS.get(cls, 0)
        contribution = pts * w
        weighted_sum += contribution
        total_weight += w
        breakdown[ind] = {"classification": cls, "display": disp,
                           "points": pts, "weight": w, "contribution": contribution}

    if total_weight == 0:
        return 0.0, "Sem dados", breakdown

    score = weighted_sum / total_weight
    label = "Evitar"
    for low, high, lbl in FII_SCORE_LEVELS:
        if low <= score < high:
            label = lbl
            break
    return round(score, 1), label, breakdown
