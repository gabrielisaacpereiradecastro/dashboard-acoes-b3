"""
Lógica de classificação de indicadores e cálculo do Score final (0-100).
"""
from __future__ import annotations
from config import (
    INDICATOR_WEIGHTS, CLASS_POINTS, SCORE_LEVELS,
    BANK_KEYWORDS, UTILITY_KEYWORDS, RETAIL_KEYWORDS,
    QUALITY_WEIGHTS, PRICE_WEIGHTS, QUALITY_WEIGHTS_BANK, PRICE_WEIGHTS_BANK,
    QUALITY_TIERS, PRICE_TIERS, VERDICT_COLORS, SCORE_GOOD_THRESHOLD,
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


# ────────────────────────────────────────────────────────────────
# Pontuação CONTÍNUA por indicador + scores Qualidade × Preço
# ────────────────────────────────────────────────────────────────

# Curvas: anchors (valor, score 0-100). Score alto = melhor (qualidade alta
# ou preço atrativo/barato). Interpolação linear entre anchors, clamp nas pontas.
_CURVES = {
    "roe":                  [(0, 0), (5, 25), (10, 50), (15, 75), (25, 100)],
    "roe_bank":             [(0, 0), (6, 25), (10, 50), (14, 75), (18, 100)],
    "net_debt_ebitda":      [(0.5, 100), (1.5, 75), (2.5, 50), (3.5, 25), (5, 0)],
    "net_debt_ebitda_util": [(2, 100), (3, 75), (4, 50), (5, 25), (6.5, 0)],
    "ebitda_margin":        [(6, 25), (12, 50), (20, 75), (30, 100)],
    "ebitda_margin_retail": [(3, 25), (6, 50), (10, 75), (15, 100)],
    "ebitda_margin_util":   [(10, 25), (20, 50), (30, 75), (40, 100)],
    "cagr_earnings_5y":     [(-10, 10), (0, 50), (8, 75), (15, 100)],
    "cagr_revenue_5y":      [(-5, 10), (0, 50), (6, 75), (12, 100)],
    "ev_ebitda":            [(5, 100), (8, 75), (12, 50), (16, 25), (20, 0)],
    "pl":                   [(10, 95), (15, 72), (20, 50), (30, 22), (40, 0)],
    "p_fcf":                [(8, 100), (15, 75), (22, 50), (30, 25), (40, 0)],
    "pvp":                  [(0.5, 100), (1, 90), (2, 60), (3, 40), (5, 15), (7, 0)],
    "pvp_bank":             [(0.7, 100), (1.0, 80), (1.5, 55), (2.0, 35), (2.5, 15), (3, 5)],
}


def _interp(value: float, anchors: list) -> float:
    if value <= anchors[0][0]:
        return float(anchors[0][1])
    if value >= anchors[-1][0]:
        return float(anchors[-1][1])
    for (v0, s0), (v1, s1) in zip(anchors, anchors[1:]):
        if v0 <= value <= v1:
            t = (value - v0) / (v1 - v0) if v1 != v0 else 0.0
            return s0 + t * (s1 - s0)
    return float(anchors[-1][1])


def score_indicator(ind: str, value, sector: str):
    """Pontuação contínua 0-100 do indicador, ou None se inaplicável/inconclusivo."""
    if value is None:
        return None
    bank = is_bank(sector)
    # Casos especiais
    if ind in ("ev_ebitda", "p_fcf") and value < 0:
        return 0.0
    if ind == "pl":
        if value < 0:
            return 0.0
        if value < 5:
            return None  # value trap — inconclusivo
    if ind == "net_debt_ebitda" and value < 0:
        return 100.0  # caixa líquido > dívida = melhor situação

    key = ind
    if ind == "roe" and bank:
        key = "roe_bank"
    elif ind == "net_debt_ebitda" and is_utility(sector):
        key = "net_debt_ebitda_util"
    elif ind == "ebitda_margin" and is_retail(sector):
        key = "ebitda_margin_retail"
    elif ind == "ebitda_margin" and is_utility(sector):
        key = "ebitda_margin_util"
    elif ind == "pvp" and bank:
        key = "pvp_bank"

    anchors = _CURVES.get(key)
    if not anchors:
        return None
    return round(_interp(value, anchors), 1)


def _composite(stock: dict, weights: dict, sector: str):
    """Média ponderada das pontuações; redistribui peso dos ausentes."""
    ws = tw = 0.0
    bd: dict = {}
    for ind, w in weights.items():
        sc = score_indicator(ind, stock.get(ind), sector)
        bd[ind] = {"score": sc, "weight": w}
        if sc is not None:
            ws += sc * w
            tw += w
    return (ws / tw if tw > 0 else None), bd


def _tier(score, tiers):
    """Rótulo graduado (5 níveis) do score, ou None."""
    if score is None:
        return None
    for lim, label in tiers:
        if score >= lim:
            return label
    return tiers[-1][1]


def _diagnose(q, p, thr: float = SCORE_GOOD_THRESHOLD):
    """Diagnóstico graduado: combina os tiers de Qualidade e Preço.

    Retorna {label, verdict, color, quality_tier, price_tier} ou None.
    A cor vem do veredito 2×2 (preserva o alerta de value trap); o rótulo é
    graduado (ex.: 'Ótima · barata', 'Razoável · justa').
    """
    if q is None or p is None:
        return None
    qt = _tier(q, QUALITY_TIERS)
    pt = _tier(p, PRICE_TIERS)
    verdict = ("boa" if q >= thr else "fraca") + "_" + ("barata" if p >= thr else "cara")
    label = f"{qt} · {pt.lower()}"
    if verdict == "fraca_barata":
        label = "⚠ " + label  # possível value trap
    return {
        "label": label,
        "verdict": verdict,
        "color": VERDICT_COLORS.get(verdict, "#37474f"),
        "quality_tier": qt,
        "price_tier": pt,
    }


def earnings_quality(stock: dict) -> dict | None:
    """Qualidade do lucro: quanto do lucro vira caixa livre (FCL/Lucro).

    Derivado dos múltiplos já disponíveis: FCL/Lucro = P/L ÷ P/FCF
    (ambos = valor de mercado / X). Sinaliza lucro "de papel" (não vira caixa).
    Não se aplica a bancos. Retorna {ratio, level, label, penalty} ou None.

    - penalty: fator multiplicativo aplicado ao score de Qualidade (≤ 1.0).
    """
    sector = stock.get("sector", "")
    if is_bank(sector):
        return None
    pl = stock.get("pl")
    p_fcf = stock.get("p_fcf")
    if pl is None or p_fcf is None or pl <= 0:
        return None  # prejuízo/sem dado: tratado em outros pontos

    if p_fcf <= 0:  # FCL negativo: lucro não vira caixa
        return {"ratio": None, "level": "ruim", "penalty": 0.70,
                "label": "⚠ FCL negativo — lucro não vira caixa"}

    ratio = pl / p_fcf  # = FCL / Lucro
    if ratio < 0.4:
        return {"ratio": ratio, "level": "ruim", "penalty": 0.78,
                "label": f"⚠ Baixa conversão em caixa ({ratio*100:.0f}% do lucro)"}
    if ratio < 0.7:
        return {"ratio": ratio, "level": "fraca", "penalty": 0.90,
                "label": f"Conversão em caixa moderada ({ratio*100:.0f}% do lucro)"}
    if ratio <= 1.5:
        return {"ratio": ratio, "level": "ok", "penalty": 1.0,
                "label": f"Lucro vira caixa ({ratio*100:.0f}% do lucro)"}
    return {"ratio": ratio, "level": "forte", "penalty": 1.0,
            "label": f"Caixa supera o lucro ({ratio*100:.0f}%)"}


def calculate_scores(stock: dict) -> dict:
    """Retorna {quality, price, diagnosis, earnings_quality, breakdown_quality, breakdown_price}.

    Funciona para TODOS os setores (bancos têm pesos próprios). Pontuação contínua.
    A Qualidade sofre haircut quando o lucro não se converte em caixa (lucro de papel).
    """
    sector = stock.get("sector", "")
    bank = is_bank(sector)
    qw = QUALITY_WEIGHTS_BANK if bank else QUALITY_WEIGHTS
    pw = PRICE_WEIGHTS_BANK if bank else PRICE_WEIGHTS

    q, bq = _composite(stock, qw, sector)
    p, bp = _composite(stock, pw, sector)

    eq = earnings_quality(stock)
    if q is not None and eq is not None and eq["penalty"] < 1.0:
        q = q * eq["penalty"]

    return {
        "quality": round(q, 1) if q is not None else None,
        "price":   round(p, 1) if p is not None else None,
        "diagnosis": _diagnose(q, p),
        "earnings_quality": eq,
        "breakdown_quality": bq,
        "breakdown_price": bp,
    }
