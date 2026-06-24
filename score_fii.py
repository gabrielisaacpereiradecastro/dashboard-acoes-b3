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
    if value is None or value < 0 or value > 50:  # fora de [0,50] = dado corrompido
        return "ND", "N/D"
    d = f"{value:.1f}%"
    if value >= 12:    return "Excelente", d
    elif value >= 8:   return "Bom", d
    elif value >= 6:   return "Razoável", d
    elif value >= 4:   return "Atenção", d
    else:              return "Proibitivo", d


def classify_fii_pvp(value) -> tuple[str, str]:
    if value is None or value <= 0:  # P/VP <= 0 = dado corrompido
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


# ════════════════════════════════════════════════════════════════
# Scores DUAIS de FII: Qualidade × Preço (split tijolo/papel)
# ════════════════════════════════════════════════════════════════

# Detecção de tipo. Papel = recebíveis/CRI (sem imóvel físico → vacância
# e inadimplência vêm vazias; API não fornece dados de crédito).
_PAPER_KEYWORDS = [
    "papel", "recebíveis", "recebiveis", "crédito", "credito", "cri",
    "high yield", "high grade", "títulos", "titulos",
]


def is_paper_fii(fund_type) -> bool:
    s = (fund_type or "").lower()
    return any(k in s for k in _PAPER_KEYWORDS)


# Curvas contínuas (valor, score 0-100). Score alto = melhor (qualidade
# alta ou preço atrativo/barato). Interpolação linear, clamp nas pontas.
_FII_CURVES = {
    # Preço/atratividade
    "pvp":             [(0.75, 100), (0.90, 90), (1.00, 70), (1.10, 50),
                        (1.20, 33), (1.35, 12), (1.50, 0)],
    "dividend_yield":  [(4, 15), (6, 40), (8, 62), (10, 80), (12, 93), (14, 100)],
    # Qualidade (tijolo) — vacância/inadimplência são "menor = melhor"
    "vacancy_pct":     [(3, 100), (8, 78), (15, 52), (22, 28), (35, 0)],
    "delinquency_pct": [(1, 100), (3, 78), (6, 52), (10, 22), (15, 0)],
    "liquidity":       [(500_000, 12), (1_000_000, 40), (3_000_000, 70),
                        (5_000_000, 90), (10_000_000, 100)],
}


def _fii_interp(value: float, anchors: list) -> float:
    if value <= anchors[0][0]:
        return float(anchors[0][1])
    if value >= anchors[-1][0]:
        return float(anchors[-1][1])
    for (v0, s0), (v1, s1) in zip(anchors, anchors[1:]):
        if v0 <= value <= v1:
            t = (value - v0) / (v1 - v0) if v1 != v0 else 0.0
            return s0 + t * (s1 - s0)
    return float(anchors[-1][1])


def score_fii_indicator(ind: str, value) -> Optional[float]:
    """Pontuação contínua 0-100 do indicador de FII, ou None."""
    if value is None:
        return None
    # Guarda contra dados corrompidos (não pontua lixo)
    if ind == "pvp" and value <= 0:
        return None
    if ind == "dividend_yield" and (value < 0 or value > 50):
        return None
    anchors = _FII_CURVES.get(ind)
    if not anchors:
        return None
    return round(_fii_interp(value, anchors), 1)


# Pesos
FII_QUALITY_WEIGHTS_BRICK = {
    "vacancy_pct":     0.45,
    "delinquency_pct": 0.30,
    "liquidity":       0.25,
}
FII_PRICE_WEIGHTS = {
    "pvp":            0.65,
    "dividend_yield": 0.35,
}

# Graduação (5 níveis). FII é "fundo" → preço masculino.
FII_QUALITY_TIERS = [(85, "Excelente"), (70, "Ótima"), (55, "Boa"), (40, "Razoável"), (0, "Fraca")]
FII_PRICE_TIERS   = [(85, "Pechincha"), (70, "Muito barato"), (55, "Barato"), (40, "Justo"), (0, "Caro")]
FII_GOOD_THRESHOLD = 55

_FII_VERDICT_COLORS = {
    "boa_barato":   "#1b5e20",
    "boa_caro":     "#7b5800",
    "fraca_barato": "#bf360c",  # ⚠ value trap
    "fraca_caro":   "#7f0000",
}
# Cor do diagnóstico de papel (1 eixo: só preço)
_FII_PRICE_ONLY_COLORS = {
    "Pechincha": "#1b5e20", "Muito barato": "#1b5e20", "Barato": "#2e7d32",
    "Justo": "#7b5800", "Caro": "#7f0000",
}


def _fii_tier(score, tiers):
    if score is None:
        return None
    for lim, label in tiers:
        if score >= lim:
            return label
    return tiers[-1][1]


def fii_alerts(fii: dict) -> list[str]:
    """Alertas de robustez (acendem só no negativo). Base do diagnóstico de papel."""
    alerts: list[str] = []
    dy = fii.get("dividend_yield")
    if dy is not None and dy > 14:
        alerts.append("⚠ DY muito alto (> 14%) — pode ser não recorrente ou risco de crédito")
    liq = fii.get("liquidity")
    if liq is not None and liq < 1_000_000:
        alerts.append("⚠ Liquidez baixa (< R$ 1M/dia) — difícil entrar/sair")
    age = _fii_age_years(fii.get("inception_date"))
    if age is not None and age < 2:
        alerts.append("⚠ Fundo recente (< 2 anos) — pouco histórico")
    return alerts


def _fii_age_years(inception_date) -> Optional[float]:
    if not inception_date:
        return None
    import datetime as _dt
    raw = str(inception_date).split("T")[0].strip()  # tira hora de ISO
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            d = _dt.datetime.strptime(raw, fmt).date()
            return (_dt.date.today() - d).days / 365.25
        except ValueError:
            continue
    return None


def _fii_composite(fii: dict, weights: dict):
    ws = tw = 0.0
    bd: dict = {}
    for ind, w in weights.items():
        sc = score_fii_indicator(ind, fii.get(ind))
        bd[ind] = {"score": sc, "weight": w}
        if sc is not None:
            ws += sc * w
            tw += w
    return (ws / tw if tw > 0 else None), bd


def _diagnose_fii(q, p, paper: bool, thr: float = FII_GOOD_THRESHOLD):
    if p is None:
        return None
    pt = _fii_tier(p, FII_PRICE_TIERS)
    if paper or q is None:
        # Papel (ou sem qualidade): diagnóstico de 1 eixo — só preço.
        return {
            "label": pt, "verdict": "papel", "quality_tier": None,
            "price_tier": pt, "color": _FII_PRICE_ONLY_COLORS.get(pt, "#37474f"),
        }
    qt = _fii_tier(q, FII_QUALITY_TIERS)
    verdict = ("boa" if q >= thr else "fraca") + "_" + ("barato" if p >= thr else "caro")
    label = f"{qt} · {pt.lower()}"
    if verdict == "fraca_barato":
        label = "⚠ " + label
    return {
        "label": label, "verdict": verdict,
        "color": _FII_VERDICT_COLORS.get(verdict, "#37474f"),
        "quality_tier": qt, "price_tier": pt,
    }


def calculate_fii_scores(fii: dict) -> dict:
    """Scores duais de FII.

    Retorna {quality, price, diagnosis, alerts, paper, breakdown_quality,
    breakdown_price}. Tijolo tem Qualidade×Preço; papel NÃO tem nota de
    Qualidade (proxies dariam falsa confiança — API não fornece dados de
    crédito), só Preço + alertas de robustez.
    """
    paper = is_paper_fii(fii.get("fund_type"))
    p, bp = _fii_composite(fii, FII_PRICE_WEIGHTS)
    if paper:
        q, bq = None, {}
    else:
        q, bq = _fii_composite(fii, FII_QUALITY_WEIGHTS_BRICK)
    return {
        "quality": round(q, 1) if q is not None else None,
        "price":   round(p, 1) if p is not None else None,
        "diagnosis": _diagnose_fii(q, p, paper),
        "alerts": fii_alerts(fii),
        "paper": paper,
        "breakdown_quality": bq,
        "breakdown_price": bp,
    }
