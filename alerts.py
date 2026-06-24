"""
Motor de alertas: avalia condições (fator, operador, valor) sobre ações.

Um alerta tem:
  - escopo: tickers específicos OU uma lista inteira (por nome)
  - condições: lista de {fator, operador, valor}
  - combinador: "E" (todas) ou "OU" (qualquer uma)

A avaliação é pura: recebe o alerta + "views" das ações (dicts achatados com
os valores de cada fator já calculados pelo app) e devolve quais dispararam.
"""
from __future__ import annotations
from typing import Optional


# Fatores disponíveis nas condições (v1). 'field' = chave na view da ação.
FACTORS: dict[str, dict] = {
    "cotacao":     {"label": "Cotação",            "field": "close_price",      "unit": "R$", "kind": "money"},
    "var_dia":     {"label": "Variação do dia",    "field": "daily_change_pct", "unit": "%",  "kind": "pct"},
    "dy":          {"label": "Dividend Yield",     "field": "dividend_yield",   "unit": "%",  "kind": "pct"},
    "pl":          {"label": "P/L",                "field": "pl",               "unit": "x",  "kind": "mult"},
    "pvp":         {"label": "P/VP",               "field": "pvp",              "unit": "x",  "kind": "mult"},
    "roe":         {"label": "ROE",                "field": "roe",              "unit": "%",  "kind": "pct"},
    "potencial":   {"label": "Potencial vs alvo",  "field": "potencial",        "unit": "%",  "kind": "pct"},
    "qualidade":   {"label": "Score Qualidade",    "field": "quality",          "unit": "",   "kind": "score"},
    "preco_score": {"label": "Score Preço",        "field": "price_score",      "unit": "",   "kind": "score"},
}

OPERADORES = [">", "≥", "<", "≤"]


def _op_apply(op: str, value: float, thr: float) -> bool:
    if op == ">":  return value > thr
    if op == "≥":  return value >= thr
    if op == "<":  return value < thr
    if op == "≤":  return value <= thr
    return False


def _fmt_value(fator: str, value) -> str:
    if value is None:
        return "N/D"
    f = FACTORS.get(fator, {})
    kind = f.get("kind")
    if kind == "money":
        return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if kind == "pct":
        return f"{value:+.1f}%" if fator == "var_dia" else f"{value:.1f}%"
    if kind == "mult":
        return f"{value:.2f}x"
    if kind == "score":
        return f"{value:.0f}"
    return str(value)


def cond_label(cond: dict) -> str:
    """Descrição legível de uma condição, ex.: 'DY > 8%'."""
    f = FACTORS.get(cond.get("fator"), {})
    unit = f.get("unit", "")
    return f"{f.get('label', cond.get('fator'))} {cond.get('operador')} {cond.get('valor')}{unit}"


def cond_met(cond: dict, view: dict) -> tuple[bool, Optional[float]]:
    """(condição satisfeita?, valor atual do fator). Valor ausente → não satisfaz."""
    f = FACTORS.get(cond.get("fator"))
    if not f:
        return False, None
    value = view.get(f["field"])
    if value is None:
        return False, None
    try:
        ok = _op_apply(cond.get("operador", ">"), float(value), float(cond.get("valor", 0)))
    except (TypeError, ValueError):
        return False, value
    return ok, value


def evaluate_ticker(alert: dict, view: dict) -> Optional[dict]:
    """Avalia o alerta para UMA ação. Retorna detalhes se disparou, senão None."""
    conds = alert.get("condicoes", [])
    if not conds:
        return None
    combin = alert.get("combinador", "E")
    resultados = []  # (cond, ok, value)
    for c in conds:
        ok, val = cond_met(c, view)
        resultados.append((c, ok, val))

    oks = [r[1] for r in resultados]
    disparou = all(oks) if combin == "E" else any(oks)
    if not disparou:
        return None
    return {
        "ticker": view.get("ticker", ""),
        "condicoes": [
            {"label": cond_label(c), "ok": ok, "valor_fmt": _fmt_value(c.get("fator"), val)}
            for c, ok, val in resultados
        ],
    }


def evaluate_alert(alert: dict, views: list[dict]) -> list[dict]:
    """Avalia o alerta contra as views (ações já filtradas pelo escopo).

    Retorna a lista de disparos: [{ticker, condicoes:[{label, ok, valor_fmt}]}].
    """
    if not alert.get("ativo", True):
        return []
    out = []
    for v in views:
        d = evaluate_ticker(alert, v)
        if d:
            out.append(d)
    return out


def scope_tickers(alert: dict, listas: dict) -> list[str]:
    """Resolve o escopo do alerta em uma lista de tickers.

    listas = {nome_lista: {ticker: ...}} (as listas do usuário).
    """
    if alert.get("escopo_tipo") == "lista":
        nome = alert.get("escopo_lista", "")
        return list(listas.get(nome, {}).keys())
    return list(alert.get("escopo_tickers", []))


def scope_label(alert: dict) -> str:
    """Descrição legível do escopo."""
    if alert.get("escopo_tipo") == "lista":
        return f"Lista: {alert.get('escopo_lista', '—')}"
    tk = alert.get("escopo_tickers", [])
    return ", ".join(tk) if tk else "—"


def alert_label(alert: dict) -> str:
    """Nome do alerta (ou auto-descrição se sem nome)."""
    nome = (alert.get("nome") or "").strip()
    if nome:
        return nome
    join = " E " if alert.get("combinador") == "E" else " OU "
    conds = join.join(cond_label(c) for c in alert.get("condicoes", []))
    return f"{scope_label(alert)} · {conds or 'sem condições'}"
