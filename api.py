"""
Módulo de comunicação com a API Bolsai.
Todas as chamadas HTTP ficam isoladas aqui — fácil de manter.
"""
import os
import requests
from typing import Optional

from config import SECTOR_REMAP

BASE_URL = "https://api.usebolsai.com/api/v1"
_TIMEOUT = 15  # segundos


def _get_api_key() -> str:
    """
    Lê a API Key priorizando st.secrets (Streamlit Cloud) e caindo
    para os.environ como fallback (execução local).
    """
    # Tenta st.secrets primeiro (Streamlit Cloud / secrets.toml local)
    try:
        import streamlit as st  # importação lazy para não criar dependência circular
        key = st.secrets.get("BOLSAI_API_KEY", "").strip()
        if key:
            return key
    except Exception:
        pass
    # Fallback: variável de ambiente (local com export BOLSAI_API_KEY=...)
    return os.environ.get("BOLSAI_API_KEY", "").strip()


def _headers() -> dict:
    key = _get_api_key()
    if not key:
        raise ValueError(
            "BOLSAI_API_KEY não encontrada. "
            "Configure em Streamlit Cloud → Settings → Secrets "
            "ou defina a variável de ambiente localmente."
        )
    return {"X-API-Key": key}


def _get(path: str, params: Optional[dict] = None) -> Optional[dict]:
    """Faz GET em BASE_URL/path e retorna JSON ou None se 404."""
    url = f"{BASE_URL}/{path.lstrip('/')}"
    try:
        resp = requests.get(url, headers=_headers(), params=params, timeout=_TIMEOUT)
    except requests.exceptions.ConnectionError:
        raise ConnectionError("Sem conexão com a internet. Verifique sua rede.")
    except requests.exceptions.Timeout:
        raise TimeoutError(f"Timeout ao chamar {path}. Tente novamente.")

    if resp.status_code == 401:
        raise PermissionError("API Key inválida ou não autorizada (401).")
    if resp.status_code == 404:
        return None
    if resp.status_code == 429:
        raise RuntimeError(
            "Limite diário de 200 requisições atingido. "
            "Tente novamente amanhã após meia-noite UTC."
        )
    if not resp.ok:
        raise RuntimeError(f"Erro {resp.status_code} ao chamar {path}: {resp.text[:200]}")

    return resp.json()


# ────────────────────────────────────────────────────────────────
# Endpoints individuais
# ────────────────────────────────────────────────────────────────

def get_fundamentals(ticker: str) -> Optional[dict]:
    """GET /fundamentals/{ticker}"""
    return _get(f"fundamentals/{ticker.upper()}")


def get_company_info(ticker: str) -> Optional[dict]:
    """GET /companies/{ticker}"""
    return _get(f"companies/{ticker.upper()}")


def get_stock_stats(ticker: str) -> Optional[dict]:
    """GET /stocks/{ticker}/stats"""
    return _get(f"stocks/{ticker.upper()}/stats")


def get_sectors() -> list[str]:
    """GET /companies/sectors — lista de setores disponíveis."""
    data = _get("companies/sectors")
    if data:
        return [s["name"] for s in data.get("sectors", [])]
    return []


def check_api_usage() -> Optional[dict]:
    """GET /keys/usage — quota do dia."""
    key = _get_api_key()
    if not key:
        return None
    try:
        resp = requests.get(
            f"{BASE_URL}/keys/usage",
            params={"api_key": key},
            timeout=_TIMEOUT,
        )
        if resp.ok:
            return resp.json()
    except Exception:
        pass
    return None


# ────────────────────────────────────────────────────────────────
# Endpoints Pro
# ────────────────────────────────────────────────────────────────

def get_dividends(ticker: str) -> Optional[dict]:
    """GET /dividends/{ticker} — Pro plan."""
    return _get(f"dividends/{ticker.upper()}")


def get_financials(ticker: str, statement_type: Optional[str] = None) -> Optional[dict]:
    """GET /financials/{ticker} — Pro plan."""
    params: dict = {}
    if statement_type:
        params["statement_type"] = statement_type
    return _get(f"financials/{ticker.upper()}", params=params or None)


def get_stock_history(ticker: str, limit: int = 1260) -> Optional[dict]:
    """GET /stocks/{ticker}/history — Pro plan. Default 1260 ≈ 5 anos."""
    return _get(f"stocks/{ticker.upper()}/history", params={"limit": limit})


def get_macro_series(series: str) -> Optional[dict]:
    """GET /macro/{series} — Pro plan.
    Series: selic, selic_target, ipca, cdi, usd_brl, eur_brl
    Selic: taxa diária em % (0.0534 ≈ 14.5% a.a. — annualizar com (1+v/100)^252-1).
    IPCA: valor mensal em % (0.58 = 0.58% no mês).
    """
    return _get(f"macro/{series}")


def get_screener(limit: int = 20, **filters) -> Optional[dict]:
    """GET /screener — Pro plan.
    Filtros aceitos: roe_min, pl_max, net_debt_ebitda_max, ebitda_margin_min, ev_ebitda_max.
    """
    params: dict = {"limit": limit}
    params.update({k: v for k, v in filters.items() if v is not None})
    return _get("screener", params=params)


def get_companies_by_sector(sector: str, limit: int = 20) -> Optional[dict]:
    """GET /companies?sector= — lista empresas por setor."""
    return _get("companies", params={"sector": sector, "limit": limit})


# ────────────────────────────────────────────────────────────────
# Função principal — busca todos os dados de um ticker (5 chamadas Pro)
# Plano Pro desbloqueia: /dividends, /financials (DFC_MI para P/FCF)
# ────────────────────────────────────────────────────────────────

def get_all_stock_data(ticker: str) -> dict:
    """
    Busca fundamentos + empresa + estatísticas para um ticker.
    Faz 3 chamadas à API (todas gratuitas). Retorna dict unificado
    ou dict com 'error' em caso de falha.

    Faz 3 chamadas à API (fundamentos + empresa + estatísticas), todas gratuitas.
    O endpoint /dividends é PRO e não é chamado. dividend_yield não existe em
    /fundamentals no plano Free → DY e Payout sempre N/D.
    """
    t = ticker.strip().upper()
    result: dict = {"ticker": t, "error": None}

    # 1 — Fundamentos (obrigatório; 404 → ticker inválido)
    fund = get_fundamentals(t)
    if fund is None:
        result["error"] = f"Ticker '{t}' não encontrado na Bolsai."
        return result

    # 2 — Informações da empresa (setor, nome de pregão)
    company = get_company_info(t)

    # 3 — Estatísticas de preço (variação diária, volume médio 52 semanas)
    stats = get_stock_stats(t)

    # ── Preço e identificação ──────────────────────────────────
    close_price = fund.get("close_price")
    shares      = fund.get("shares_outstanding")

    # ── Liquidez: volume médio 52 semanas × preço (proxy R$) ──
    avg_vol_shares = (stats or {}).get("avg_volume_52w")
    liquidity_brl: Optional[float] = None
    if avg_vol_shares and close_price:
        liquidity_brl = avg_vol_shares * close_price

    # 4 — Dividendos (Pro): DY TTM e dividendo por ação TTM
    div = get_dividends(t)
    dividend_yield_ttm: Optional[float] = None
    ttm_per_share: Optional[float] = None
    if div:
        dividend_yield_ttm = div.get("dividend_yield_ttm")
        ttm_per_share = div.get("ttm_per_share")

    # 5 — DFC (Pro): P/FCF via Caixa Líquido Operacional e Capex
    p_fcf: Optional[float] = None
    fin = get_financials(t, statement_type="DFC_MI")
    if fin:
        stmts = fin.get("statements", [])
        dates = sorted({s["reference_date"] for s in stmts}, reverse=True)
        if dates:
            latest = {s["account_code"]: s["value"] for s in stmts
                      if s["reference_date"] == dates[0] and s["value"] is not None}
            fco = latest.get("6.01")
            capex = (latest.get("6.02.02") or 0) + (latest.get("6.02.03") or 0)
            if fco is not None:
                fcl_k = fco + capex  # valores negativos de capex já deduzem
                mcap = fund.get("market_cap")
                if fcl_k > 0 and mcap:
                    p_fcf = mcap / (fcl_k * 1000)

    # Payout: dividendo por ação TTM / LPA (sem precisar de net_income em unidade)
    lpa_val = fund.get("lpa")
    payout: Optional[float] = None
    if ttm_per_share and lpa_val and lpa_val > 0:
        payout = round(ttm_per_share / lpa_val * 100, 1)

    result.update(
        {
            # JSON bruto de /fundamentals — usado apenas para debug, removido antes de salvar
            "_raw_fund": dict(fund),
            # Identificação
            "ticker":             fund.get("ticker", t),
            "corporate_name":     fund.get("corporate_name", ""),
            "trade_name":         (company or {}).get("trade_name", ""),
            "sector":             SECTOR_REMAP.get(t, (company or {}).get("sector", "")),
            "reference_date":     fund.get("reference_date"),
            # Preço
            "close_price":        close_price,
            "daily_change_pct":   (stats or {}).get("daily_change_pct"),
            "week_52_low":        (stats or {}).get("week_52_low"),
            "week_52_high":       (stats or {}).get("week_52_high"),
            "ytd_return_pct":     (stats or {}).get("ytd_return_pct"),
            "market_cap":         fund.get("market_cap"),
            "shares_outstanding": shares,
            # ── Indicadores com score (todos de /fundamentals) ─
            "net_debt_ebitda":    fund.get("net_debt_ebitda"),
            "roe":                fund.get("roe"),
            "ev_ebitda":          fund.get("ev_ebitda"),
            "pl":                 fund.get("pl"),
            "ebitda_margin":      fund.get("ebitda_margin"),
            "cagr_earnings_5y":   fund.get("cagr_earnings_5y"),
            "cagr_revenue_5y":    fund.get("cagr_revenue_5y"),
            "p_fcf":              p_fcf,
            "dividend_yield":     dividend_yield_ttm,
            "liquidity":          liquidity_brl,
            # ── Indicadores informativos (sem score) ───────────
            "pvp":          fund.get("pvp"),
            "payout":       payout,
            "net_margin":   fund.get("net_margin"),
            "gross_margin": fund.get("gross_margin"),
            "ebit_margin":  fund.get("ebit_margin"),
            "roa":          fund.get("roa"),
            "roic":         fund.get("roic"),
            "lpa":          fund.get("lpa"),
            "vpa":          fund.get("vpa"),
            "current_ratio":fund.get("current_ratio"),
            "net_debt":     fund.get("net_debt"),     # R$ mil
            "ebitda":       fund.get("ebitda"),       # R$ mil
            "net_income":   fund.get("net_income"),   # R$ mil
            "net_revenue":  fund.get("net_revenue"),  # R$ mil
            "avg_volume_52w": avg_vol_shares,
        }
    )
    return result
