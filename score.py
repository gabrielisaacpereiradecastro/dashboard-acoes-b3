"""
Lógica de classificação de indicadores e cálculo do Score final (0-100).
"""
from __future__ import annotations
from config import (
    INDICATOR_WEIGHTS, CLASS_POINTS, SCORE_LEVELS,
    BANK_KEYWORDS, UTILITY_KEYWORDS, RETAIL_KEYWORDS,
)


# ────────────────────────────────────────────────────────────────
# Identificadores de setor
# ────────────────────────────────────────────────────────────────

def _lower(sector: str) -> str:
    return (sector or "").lower()


def is_bank(sector: str) -> bool:
    s = _lower(sector)
    return any(k in s for k in BANK_KEYWORDS)


def is_utility(sector: str) -> bool:
    s = _lower(sector)
    return any(k in s for k in UTILITY_KEYWORDS)


def is_retail(sector: str) -> bool:
    s = _lower(sector)
    return any(k in s for k in RETAIL_KEYWORDS)


# ────────────────────────────────────────────────────────────────
# Funções de classificação — retornam (classificação, display_str)
# ────────────────────────────────────────────────────────────────

def classify_net_debt_ebitda(value, sector: str) -> tuple[str, str]:
    if is_bank(sector):
        return "NA", "N/A — Bancário"
    if value is None:
        return "ND", "N/D"

    util = is_utility(sector)
    # Limites por faixa: [Excelente, Bom, Razoável, Atenção]
    lim = [2.0, 3.0, 4.0, 5.0] if util else [0.5, 1.5, 2.5, 3.5]
    display = f"{value:.2f}x"

    if value < 0:
        # Dívida líquida negativa = caixa líquido > dívida → melhor situação possível
        return "Excelente", display
    elif value <= lim[0]:
        return "Excelente", display
    elif value <= lim[1]:
        return "Bom", display
    elif value <= lim[2]:
        return "Razoável", display
    elif value <= lim[3]:
        return "Atenção", display
    else:
        return "Proibitivo", display


def classify_roe(value, sector: str) -> tuple[str, str]:
    if value is None:
        return "ND", "N/D"
    display = f"{value:.1f}%"

    if is_bank(sector):
        if value >= 18:   return "Excelente", display
        elif value >= 14: return "Bom", display
        elif value >= 10: return "Razoável", display
        elif value >= 6:  return "Atenção", display
        else:             return "Proibitivo", display
    else:
        if value >= 25:   return "Excelente", display
        elif value >= 15: return "Bom", display
        elif value >= 10: return "Razoável", display
        elif value >= 5:  return "Atenção", display
        else:             return "Proibitivo", display


def classify_ev_ebitda(value, sector: str) -> tuple[str, str]:
    if is_bank(sector):
        return "NA", "N/A — Bancário"
    if value is None:
        return "ND", "N/D"
    display = f"{value:.2f}x"

    if value < 0:         return "Proibitivo", display
    elif value <= 5:      return "Excelente", display
    elif value <= 8:      return "Bom", display
    elif value <= 12:     return "Razoável", display
    elif value <= 16:     return "Atenção", display
    else:                 return "Proibitivo", display


def classify_pl(value, sector: str) -> tuple[str, str]:
    if value is None:
        return "ND", "N/D"
    if value < 0:
        return "Proibitivo", "Prejuízo"
    display = f"{value:.2f}x"

    if value < 5:         return "Inconclusivo", f"⚠️ {display}"  # possível armadilha de valor
    elif value <= 10:     return "Excelente", display
    elif value <= 15:     return "Bom", display
    elif value <= 20:     return "Razoável", display
    elif value <= 30:     return "Atenção", display
    else:                 return "Proibitivo", display


def classify_ebitda_margin(value, sector: str) -> tuple[str, str]:
    if value is None:
        return "ND", "N/D"
    display = f"{value:.1f}%"

    if is_retail(sector):
        lim = [15, 10, 6, 3]
    elif is_utility(sector):
        lim = [40, 30, 20, 10]
    else:
        lim = [30, 20, 12, 6]

    if value >= lim[0]:   return "Excelente", display
    elif value >= lim[1]: return "Bom", display
    elif value >= lim[2]: return "Razoável", display
    elif value >= lim[3]: return "Atenção", display
    else:                 return "Proibitivo", display


def classify_cagr_earnings(value, sector: str) -> tuple[str, str]:
    if value is None:
        return "ND", "N/D"
    display = f"{value:.1f}%"

    if value >= 15:       return "Excelente", display
    elif value >= 8:      return "Bom", display
    elif value >= 0:      return "Razoável", display
    elif value >= -10:    return "Atenção", display
    else:                 return "Proibitivo", display


def classify_p_fcf(value, sector: str) -> tuple[str, str]:
    if value is None:
        return "ND", "N/D"
    display = f"{value:.2f}x"

    if value < 0:         return "Proibitivo", display
    elif value <= 8:      return "Excelente", display
    elif value <= 15:     return "Bom", display
    elif value <= 22:     return "Razoável", display
    elif value <= 30:     return "Atenção", display
    else:                 return "Proibitivo", display


def classify_dividend_yield(value, sector: str) -> tuple[str, str]:
    if value is None:
        return "ND", "N/D"
    display = f"{value:.1f}%"

    if value >= 8:        return "Excelente", display
    elif value >= 5:      return "Bom", display
    elif value >= 3:      return "Razoável", display
    elif value >= 1:      return "Atenção", display
    else:                 return "Proibitivo", display


def _fmt_brl(v: float) -> str:
    if v >= 1_000_000:
        return f"R$ {v / 1_000_000:.1f}M"
    elif v >= 1_000:
        return f"R$ {v / 1_000:.0f}k"
    return f"R$ {v:.0f}"


def classify_liquidity(value, sector: str) -> tuple[str, str]:
    """value em R$ (vol. médio 52 semanas × preço)."""
    if value is None:
        return "ND", "N/D"
    display = _fmt_brl(value)

    if value > 5_000_000:    return "Excelente", display
    elif value > 3_000_000:  return "Bom", display
    elif value > 1_000_000:  return "Razoável", display
    elif value > 500_000:    return "Atenção", display
    else:                    return "Proibitivo", display


def classify_cagr_revenue(value, sector: str) -> tuple[str, str]:
    if value is None:
        return "ND", "N/D"
    display = f"{value:.1f}%"

    if value >= 12:       return "Excelente", display
    elif value >= 6:      return "Bom", display
    elif value >= 0:      return "Razoável", display
    elif value >= -5:     return "Atenção", display
    else:                 return "Proibitivo", display


def classify_pvp(value, sector: str) -> tuple[str, str]:
    """P/VP — informativo (sem peso no score). Escala diferente para bancos."""
    if value is None:
        return "ND", "N/D"
    display = f"{value:.2f}×"

    if is_bank(sector):
        if value <= 1.5:    return "Bom", display
        elif value <= 2.5:  return "Razoável", display
        else:               return "Proibitivo", display
    else:
        if value < 1.0:     return "Bom", display
        elif value <= 2.0:  return "Excelente", display
        elif value <= 3.0:  return "Razoável", display
        elif value <= 5.0:  return "Atenção", display
        else:               return "Proibitivo", display


def classify_psr(value, sector: str) -> tuple[str, str]:
    """PSR — Price/Sales Ratio. Informativo (não entra no score)."""
    if value is None:
        return "ND", "N/D"
    display = f"{value:.2f}×"
    if value <= 1:      return "Excelente", display
    elif value <= 2:    return "Bom", display
    elif value <= 4:    return "Razoável", display
    elif value <= 6:    return "Atenção", display
    else:               return "Proibitivo", display


def classify_interest_coverage(value, sector: str) -> tuple[str, str]:
    """Cobertura de Juros = EBIT / Despesa Financeira. Informativo."""
    if is_bank(sector):
        return "NA", "N/A — Bancário"
    if value is None:
        return "ND", "N/D"
    display = f"{value:.2f}×"
    if value >= 5:      return "Excelente", display
    elif value >= 3:    return "Bom", display
    elif value >= 1.5:  return "Razoável", display
    elif value >= 1:    return "Atenção", display
    else:               return "Proibitivo", display


# Mapeamento ordenado: indicador → função de classificação
CLASSIFIERS: dict = {
    "net_debt_ebitda":  classify_net_debt_ebitda,
    "roe":              classify_roe,
    "ev_ebitda":        classify_ev_ebitda,
    "pl":               classify_pl,
    "ebitda_margin":    classify_ebitda_margin,
    "cagr_earnings_5y": classify_cagr_earnings,
    "p_fcf":            classify_p_fcf,
    "dividend_yield":   classify_dividend_yield,
    "liquidity":        classify_liquidity,
    "cagr_revenue_5y":  classify_cagr_revenue,
}


# ────────────────────────────────────────────────────────────────
# Classificação de todos os indicadores de uma vez
# ────────────────────────────────────────────────────────────────

def classify_all(stock: dict) -> dict[str, tuple[str, str]]:
    """
    Retorna {indicador: (classificação, display_str)} para todos os
    indicadores com score.
    """
    sector = stock.get("sector", "")
    return {
        ind: fn(stock.get(ind), sector)
        for ind, fn in CLASSIFIERS.items()
    }


# ────────────────────────────────────────────────────────────────
# Score final
# ────────────────────────────────────────────────────────────────

def calculate_score(stock: dict) -> tuple[float | None, str, dict]:
    """
    Retorna (score, label, breakdown).

    - score: 0-100 ou None para bancos
    - label: 'Excelente', 'Bom', 'Razoável', 'Atenção', 'Evitar'
             ou 'Setor Bancário'
    - breakdown: {indicador: {classification, display, points, weight, contribution}}
    """
    sector = stock.get("sector", "")

    if is_bank(sector):
        # Spec: bancos não recebem score final
        classifications = classify_all(stock)
        breakdown = {
            ind: {
                "classification": cls,
                "display": disp,
                "points": None,
                "weight": INDICATOR_WEIGHTS[ind],
                "contribution": None,
            }
            for ind, (cls, disp) in classifications.items()
        }
        return None, "Setor Bancário", breakdown

    classifications = classify_all(stock)
    breakdown: dict = {}
    weighted_sum = 0.0
    total_weight = 0.0

    for ind, (cls, disp) in classifications.items():
        w = INDICATOR_WEIGHTS[ind]
        if cls in ("ND", "NA", "Inconclusivo"):
            breakdown[ind] = {
                "classification": cls,
                "display": disp,
                "points": None,
                "weight": w,
                "contribution": None,
            }
            continue

        pts = CLASS_POINTS.get(cls, 0)
        contribution = pts * w
        weighted_sum += contribution
        total_weight += w
        breakdown[ind] = {
            "classification": cls,
            "display": disp,
            "points": pts,
            "weight": w,
            "contribution": contribution,
        }

    if total_weight == 0:
        return 0.0, "Sem dados", breakdown

    # Normaliza redistribuindo pesos dos indicadores ausentes
    score = weighted_sum / total_weight

    label = "Evitar"
    for low, high, lbl in SCORE_LEVELS:
        if low <= score < high:
            label = lbl
            break

    return round(score, 1), label, breakdown


def score_color(label: str) -> str:
    """Retorna hex color para o label de score."""
    from config import SCORE_COLORS
    return SCORE_COLORS.get(label, "#9e9e9e")
