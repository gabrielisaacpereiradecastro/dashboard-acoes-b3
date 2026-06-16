"""
Módulo de comunicação com a API Bolsai.
Todas as chamadas HTTP ficam isoladas aqui — fácil de manter.
"""
import os
import requests
from typing import Optional

BASE_URL = "https://api.usebolsai.com/api/v1"
_TIMEOUT = 15  # segundos


def _headers() -> dict:
    key = os.environ.get("BOLSAI_API_KEY", "").strip()
    if not key:
        raise ValueError(
            "Variável de ambiente BOLSAI_API_KEY não configurada. "
            "Defina-a antes de iniciar o app."
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


def get_dividends(ticker: str) -> Optional[dict]:
    """GET /dividends/{ticker} — retorna dividend_yield_ttm e ttm_per_share."""
    return _get(f"dividends/{ticker.upper()}")


def get_sectors() -> list[str]:
    """GET /companies/sectors — lista de setores disponíveis."""
    data = _get("companies/sectors")
    if data:
        return [s["name"] for s in data.get("sectors", [])]
    return []


def check_api_usage() -> Optional[dict]:
    """GET /keys/usage — quota do dia."""
    key = os.environ.get("BOLSAI_API_KEY", "").strip()
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
# Função principal — busca todos os dados de um ticker (4 chamadas)
# ────────────────────────────────────────────────────────────────

def get_all_stock_data(ticker: str) -> dict:
    """
    Busca fundamentos + empresa + estatísticas + dividendos para um ticker.
    Faz 4 chamadas à API. Retorna dict unificado ou dict com 'error'.
    """
    t = ticker.strip().upper()
    result: dict = {"ticker": t, "error": None}

    # 1 — Fundamentos (obrigatório; se 404 → ticker inválido)
    fund = get_fundamentals(t)
    if fund is None:
        result["error"] = f"Ticker '{t}' não encontrado na Bolsai."
        return result

    # 2 — Informações da empresa (setor, nome de pregão)
    company = get_company_info(t)

    # 3 — Estatísticas de preço (variação, volume médio 52 semanas)
    stats = get_stock_stats(t)

    # 4 — Dividendos (DY TTM, DPS TTM para calcular payout)
    div = get_dividends(t)

    # ── Preço e identificação ──────────────────────────────────
    close_price = fund.get("close_price")
    shares = fund.get("shares_outstanding")

    # ── Liquidez: volume médio 52 semanas × preço (R$) ────────
    avg_vol_shares = stats.get("avg_volume_52w") if stats else None
    liquidity_brl: Optional[float] = None
    if avg_vol_shares and close_price:
        liquidity_brl = avg_vol_shares * close_price

    # ── Payout (%) ─────────────────────────────────────────────
    # DPS TTM (R$/ação) × ações / lucro líquido (R$)
    # net_income na API está em R$ mil → multiplicar por 1000
    payout: Optional[float] = None
    net_income_k = fund.get("net_income")  # R$ mil
    ttm_dps = div.get("ttm_per_share") if div else None
    if ttm_dps and shares and net_income_k and net_income_k > 0:
        payout = (ttm_dps * shares) / (net_income_k * 1000) * 100

    result.update(
        {
            # Identificação
            "ticker":          fund.get("ticker", t),
            "corporate_name":  fund.get("corporate_name", ""),
            "trade_name":      (company or {}).get("trade_name", ""),
            "sector":          (company or {}).get("sector", ""),
            "reference_date":  fund.get("reference_date"),
            # Preço
            "close_price":      close_price,
            "daily_change_pct": (stats or {}).get("daily_change_pct"),
            "week_52_low":      (stats or {}).get("week_52_low"),
            "week_52_high":     (stats or {}).get("week_52_high"),
            "ytd_return_pct":   (stats or {}).get("ytd_return_pct"),
            "market_cap":       fund.get("market_cap"),
            "shares_outstanding": shares,
            # ── Indicadores com score ──────────────────────────
            "net_debt_ebitda":  fund.get("net_debt_ebitda"),
            "roe":              fund.get("roe"),
            "ev_ebitda":        fund.get("ev_ebitda"),
            "pl":               fund.get("pl"),
            "ebitda_margin":    fund.get("ebitda_margin"),
            "cagr_earnings_5y": fund.get("cagr_earnings_5y"),
            "cagr_revenue_5y":  fund.get("cagr_revenue_5y"),
            "p_fcf":            None,  # requer plano Pro (endpoint /financials)
            "dividend_yield":   (div or {}).get("dividend_yield_ttm"),
            "liquidity":        liquidity_brl,
            # ── Indicadores informativos (sem score) ───────────
            "pvp":         fund.get("pvp"),
            "payout":      payout,
            "net_margin":  fund.get("net_margin"),
            "gross_margin": fund.get("gross_margin"),
            "ebit_margin": fund.get("ebit_margin"),
            "roa":         fund.get("roa"),
            "roic":        fund.get("roic"),
            "lpa":         fund.get("lpa"),
            "vpa":         fund.get("vpa"),
            "current_ratio": fund.get("current_ratio"),
            "net_debt":    fund.get("net_debt"),    # R$ mil
            "ebitda":      fund.get("ebitda"),      # R$ mil
            "net_income":  fund.get("net_income"),  # R$ mil
            "net_revenue": fund.get("net_revenue"), # R$ mil
            "avg_volume_52w": avg_vol_shares,
        }
    )
    return result
