"""
Módulo de comunicação com a API Bolsai.
Todas as chamadas HTTP ficam isoladas aqui — fácil de manter.
"""
import os
import time
import requests
from typing import Optional

from config import SECTOR_REMAP, SETORES_CICLICOS, BANK_KEYWORDS

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
    """Faz GET em BASE_URL/path e retorna JSON ou None se 404.

    Tenta novamente (com backoff) em erros transitórios — 5xx, timeout e
    falha de conexão — que são comuns em atualizações em massa.
    """
    url = f"{BASE_URL}/{path.lstrip('/')}"
    _last_err: Exception = RuntimeError(f"Falha ao chamar {path}.")
    for _attempt in range(3):
        try:
            resp = requests.get(url, headers=_headers(), params=params, timeout=_TIMEOUT)
        except requests.exceptions.ConnectionError:
            _last_err = ConnectionError("Sem conexão com a internet. Verifique sua rede.")
            time.sleep(0.6 * (_attempt + 1))
            continue
        except requests.exceptions.Timeout:
            _last_err = TimeoutError(f"Timeout ao chamar {path}.")
            time.sleep(0.6 * (_attempt + 1))
            continue

        if resp.status_code == 401:
            raise PermissionError("API Key inválida ou não autorizada (401).")
        if resp.status_code == 404:
            return None
        if resp.status_code == 429:
            # Limite diário: tentar de novo não ajuda.
            raise RuntimeError(
                "Limite diário de requisições da API atingido. "
                "Tente novamente amanhã após meia-noite UTC."
            )
        if resp.status_code >= 500:
            _last_err = RuntimeError("A API retornou erro temporário (5xx).")
            time.sleep(0.7 * (_attempt + 1))
            continue
        if not resp.ok:
            raise RuntimeError(f"Erro {resp.status_code} ao chamar {path}: {resp.text[:200]}")

        return resp.json()

    raise _last_err


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


def get_fundamentals_history(ticker: str, limit: int = 20) -> Optional[dict]:
    """GET /fundamentals/{ticker}/history — histórico trimestral de indicadores (Pro)."""
    return _get(f"fundamentals/{ticker.upper()}/history", params={"limit": limit})


def get_macro_series(series: str) -> Optional[dict]:
    """GET /macro/{series} — Pro plan.
    Series: selic, selic_target, ipca, cdi, usd_brl, eur_brl
    Selic: taxa diária em % (0.0534 ≈ 14.5% a.a. — annualizar com (1+v/100)^252-1).
    IPCA: valor mensal em % (0.58 = 0.58% no mês).
    """
    return _get(f"macro/{series}")


# ────────────────────────────────────────────────────────────────
# Macro do Banco Central (SGS) — API PÚBLICA, sem chave/autenticação
# ────────────────────────────────────────────────────────────────

_SGS_BASE = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{cod}/dados"

# Códigos das séries usadas no painel de Ciclo
SGS_SELIC_META   = 432    # Meta Selic definida pelo Copom (% a.a.)
SGS_IPCA_12M     = 13522  # IPCA acumulado 12 meses (%)
SGS_IBC_BR       = 24364  # IBC-Br dessazonalizado (proxy mensal do PIB, índice)
SGS_USD_BRL      = 1      # Dólar (venda)
SGS_CREDITO_PIB  = 20622  # Saldo de crédito / PIB (%)


def get_sgs(codigo: int, ultimos: int = 1, dias: Optional[int] = None) -> Optional[list]:
    """Série temporal do SGS do Banco Central (pública, sem autenticação).

    - `ultimos`: pega os N pontos mais recentes (limite ~50 em séries diárias).
    - `dias`: se informado, busca por intervalo (hoje − N dias até hoje) — sem
      o limite do /ultimos, ideal para séries diárias como a Selic.

    Retorna lista [{"data": "dd/mm/aaaa", "valor": "x.y"}] (antigo → recente) ou None.
    """
    from datetime import date, timedelta
    try:
        if dias:
            fim = date.today()
            ini = fim - timedelta(days=dias)
            url = _SGS_BASE.format(cod=codigo)
            params = {"formato": "json",
                      "dataInicial": ini.strftime("%d/%m/%Y"),
                      "dataFinal": fim.strftime("%d/%m/%Y")}
        else:
            url = _SGS_BASE.format(cod=codigo) + f"/ultimos/{ultimos}"
            params = {"formato": "json"}
        r = requests.get(url, params=params, timeout=12)
        if r.ok:
            return r.json()
    except Exception:
        pass
    return None


_FOCUS_URL = ("https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/"
              "odata/ExpectativasMercadoAnuais")


def get_focus(indicador: str, top: int = 6) -> Optional[dict]:
    """Mediana das expectativas do boletim Focus (BC) por ano de referência.

    indicador: 'IPCA', 'PIB Total', 'Selic', 'Câmbio'. API pública (Olinda),
    sem chave. Retorna {ano(int): mediana(float)} ou None.
    """
    import urllib.parse
    try:
        # URL montada à mão (OData é sensível à codificação de aspas/espaços)
        filtro = urllib.parse.quote(f"Indicador eq '{indicador}'", safe="'")
        url = (f"{_FOCUS_URL}?%24filter={filtro}&%24orderby=Data%20desc"
               f"&%24top={top}&%24format=json&%24select=DataReferencia,Mediana")
        r = requests.get(url, timeout=12)
        if not r.ok:
            return None
        out: dict = {}
        for v in r.json().get("value", []):
            try:
                ano = int(v["DataReferencia"])
            except (TypeError, ValueError, KeyError):
                continue
            if ano not in out and v.get("Mediana") is not None:  # mais recente vem 1º
                out[ano] = float(v["Mediana"])
        return out or None
    except Exception:
        pass
    return None


def get_ibovespa_pl() -> Optional[float]:
    """Raspa o P/L atual do Ibovespa do Investidor10 (sem auth).

    Fonte de terceiros — pode quebrar se o site mudar o HTML; retorna None
    nesse caso (o painel exibe fallback gracioso). Média histórica de longo
    prazo (~12×) é constante documentada no app, não vem daqui.
    """
    import re
    try:
        r = requests.get(
            "https://investidor10.com.br/indices/pl-ibovespa/",
            headers={"User-Agent": "Mozilla/5.0"}, timeout=12,
        )
        if not r.ok:
            return None
        m = re.search(r'class="value">\s*([0-9]{1,2},[0-9]{2})\s*<', r.text)
        if m:
            val = float(m.group(1).replace(",", "."))
            if 4 < val < 40:  # sanidade: P/L de índice fica nessa faixa
                return val
    except Exception:
        pass
    return None


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
# FIIs (Pro)
# ────────────────────────────────────────────────────────────────

def get_fii(ticker: str) -> Optional[dict]:
    """GET /fiis/{ticker} — dados completos de um FII."""
    return _get(f"fiis/{ticker.upper()}")


def get_fii_distributions(ticker: str) -> Optional[dict]:
    """GET /fiis/{ticker}/distributions — histórico de rendimentos do FII (Pro).
    Estrutura confirmada ao vivo via debug; parser no app é flexível."""
    return _get(f"fiis/{ticker.upper()}/distributions")


def get_fii_screener(limit: int = 20, **filters) -> Optional[dict]:
    """GET /fiis/screener — screener de FIIs."""
    params: dict = {"limit": limit}
    params.update({k: v for k, v in filters.items() if v is not None})
    return _get("fiis/screener", params=params)


def get_fii_list(limit: int = 100, offset: int = 0) -> Optional[dict]:
    """GET /fiis — lista paginada de FIIs."""
    return _get("fiis", params={"limit": limit, "offset": offset})


def get_all_fii_data(ticker: str) -> dict:
    """Busca dados completos de um FII: /fiis/{ticker} + /stocks/{ticker}/stats."""
    t = ticker.strip().upper()
    result: dict = {"ticker": t, "error": None}

    fii = get_fii(t)
    if fii is None:
        result["error"] = f"FII '{t}' não encontrado na Bolsai."
        return result

    stats = get_stock_stats(t)
    close_price = fii.get("close_price") or (stats or {}).get("close")
    avg_vol = (stats or {}).get("avg_volume_52w")
    liquidity_brl: Optional[float] = None
    if avg_vol and close_price:
        liquidity_brl = avg_vol * close_price

    result.update({
        "ticker":            fii.get("ticker", t),
        "name":              fii.get("name", ""),
        "fund_type":         fii.get("fund_type") or "N/D",
        "segment":           fii.get("segment", ""),
        "close_price":       close_price,
        "daily_change_pct":  (stats or {}).get("daily_change_pct"),
        "week_52_low":       (stats or {}).get("week_52_low"),
        "week_52_high":      (stats or {}).get("week_52_high"),
        "pvp":               fii.get("pvp"),
        "dividend_yield":    fii.get("dividend_yield_ttm"),
        "vacancy_pct":       fii.get("vacancy_pct"),
        "delinquency_pct":   fii.get("delinquency_pct"),
        "leased_pct":        fii.get("leased_pct"),
        "net_asset_value":   fii.get("net_asset_value"),
        "shares_outstanding":fii.get("shares_outstanding"),
        "total_shareholders":fii.get("total_shareholders"),
        "administrator":     fii.get("administrator"),
        "management_type":   fii.get("management_type"),
        "inception_date":    fii.get("inception_date"),
        "property_count":    fii.get("property_count"),
        "total_area_sqm":    fii.get("total_area_sqm"),
        "asset_composition": fii.get("asset_composition"),
        "top_properties":    fii.get("top_properties"),
        "reference_date":    fii.get("reference_date"),
        "liquidity":         liquidity_brl,
        "avg_volume_52w":    avg_vol,
    })

    # Sanitiza valores absurdos da API (ex.: DY -2071%, P/VP 0,00) → None,
    # para não exibir lixo nem poluir scores/médias ponderadas.
    def _san(v, lo, hi):
        return v if (isinstance(v, (int, float)) and lo <= v <= hi) else None
    result["dividend_yield"]  = _san(result.get("dividend_yield"), 0, 50)
    result["pvp"]             = _san(result.get("pvp"), 0.01, 5)
    result["vacancy_pct"]     = _san(result.get("vacancy_pct"), 0, 100)
    result["delinquency_pct"] = _san(result.get("delinquency_pct"), 0, 100)
    result["leased_pct"]      = _san(result.get("leased_pct"), 0, 100)
    return result


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

    # Setor final (remapeado) + flags de setor (decidem buscas extras)
    _sector_final = SECTOR_REMAP.get(t, (company or {}).get("sector", "") or "")
    # Remove prefixo genérico de holding ("Emp. Adm. Part. - X" → "X")
    for _pfx in ("Emp. Adm. Part. - ", "Empresas Administradoras de Participações - "):
        if _sector_final.startswith(_pfx):
            _sector_final = _sector_final[len(_pfx):].strip()
            break
    _sl = _sector_final.lower()
    _is_cyclical_sec = any(kw in _sl for kw in SETORES_CICLICOS)
    _is_bank_sec = any(kw in _sl for kw in BANK_KEYWORDS)

    # 3 — Estatísticas de preço (variação diária, volume médio 52 semanas)
    stats = get_stock_stats(t)

    # ── Preço e identificação ──────────────────────────────────
    # /fundamentals CANONICALIZA classes ON/PN (query BMEB3 → dados de BMEB4, preço
    # 66,18). Já o /stocks/stats traz o `close` da CLASSE consultada (BMEB3 = 50,60).
    # Então preferimos o preço do /stats; P/L e P/VP são recalculados com ele.
    _fund_close = fund.get("close_price")
    _stats_close = (stats or {}).get("close")
    close_price = _stats_close or _fund_close
    shares      = fund.get("shares_outstanding")

    _pl_out, _pvp_out = fund.get("pl"), fund.get("pvp")
    if (_stats_close and _fund_close and abs(_stats_close - _fund_close) > 1e-6):
        _lpa, _vpa = fund.get("lpa"), fund.get("vpa")
        if _lpa and _lpa > 0:
            _pl_out = round(_stats_close / _lpa, 2)
        if _vpa and _vpa > 0:
            _pvp_out = round(_stats_close / _vpa, 2)

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

    # 5 — DFC (Pro): P/FCF e FCL via Caixa Líquido Operacional e Capex
    p_fcf: Optional[float] = None
    _fcl_k: Optional[float] = None        # FCL mais recente em R$ mil
    _fcl_historico: dict = {}             # {ano_str: FCL_em_R$_mil} — todos os anos disponíveis
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
                _fcl_k = fco + capex  # R$ mil; negativo = FCL negativo (válido para DCF)
                mcap = fund.get("market_cap")
                if _fcl_k > 0 and mcap:
                    p_fcf = mcap / (_fcl_k * 1000)

        # Histórico de FCL por ano (para normalização cíclica)
        _fco_by_yr: dict = {}
        _capex_by_yr: dict = {}
        for _s in stmts:
            _yr = (_s.get("reference_date") or "")[:4]
            _v  = _s.get("value")
            _c  = _s.get("account_code", "")
            if not _yr or _v is None:
                continue
            if _c == "6.01" and _yr not in _fco_by_yr:
                _fco_by_yr[_yr] = _v
            elif _c in ("6.02.02", "6.02.03"):
                _capex_by_yr[_yr] = _capex_by_yr.get(_yr, 0) + _v
        for _yr in _fco_by_yr:
            _fcl_historico[_yr] = _fco_by_yr[_yr] + _capex_by_yr.get(_yr, 0)

    # Payout: dividendo por ação TTM / LPA (sem precisar de net_income em unidade)
    lpa_val = fund.get("lpa")
    payout: Optional[float] = None
    if ttm_per_share and lpa_val and lpa_val > 0:
        payout = round(ttm_per_share / lpa_val * 100, 1)

    # 6 — DRE (Pro): CAGR + EBIT + Despesas Financeiras (Cobertura de Juros)
    _cagr_earn: Optional[float] = fund.get("cagr_earnings_5y")
    _cagr_rev: Optional[float] = fund.get("cagr_revenue_5y")
    # EBIT: tenta do campo direto do /fundamentals; fallback via margem EBIT × receita
    _ebit_mil: Optional[float] = fund.get("ebit")
    if _ebit_mil is None and fund.get("ebit_margin") is not None and fund.get("net_revenue"):
        _ebit_mil = fund["ebit_margin"] / 100 * fund["net_revenue"]  # R$ mil
    # Despesas financeiras: tenta do campo direto (Bolsai Pro pode fornecer)
    _fin_exp_mil: Optional[float] = fund.get("financial_expenses")

    _ebit_historico: dict = {}  # {ano: EBIT R$ mil} — usado p/ EBITDA mid-cycle (cíclicas)

    # Busca o DRE se faltar algum campo OU se for cíclica (precisa do EBIT histórico)
    if (_cagr_earn is None or _cagr_rev is None or _ebit_mil is None
            or _fin_exp_mil is None or _is_cyclical_sec):
        dre = get_financials(t, statement_type="DRE")
        if dre:
            _profit: dict = {}
            _revenue: dict = {}
            _ebit_dre: dict = {}
            _fin_exp_dre: dict = {}
            for _s in (dre.get("statements") or []):
                _yr = (_s.get("reference_date") or "")[:4]
                _v = _s.get("value")
                _c = _s.get("account_code", "")
                if not _yr or _v is None:
                    continue
                if _c == "3.11.01" and _yr not in _profit:
                    _profit[_yr] = _v
                elif _c == "3.11" and _yr not in _profit:
                    _profit[_yr] = _v
                if _c == "3.01" and _yr not in _revenue:
                    _revenue[_yr] = abs(_v)
                if _c == "3.05" and _yr not in _ebit_dre:
                    _ebit_dre[_yr] = _v   # EBIT (CVM 3.05)
                if _c == "3.06.02" and _yr not in _fin_exp_dre:
                    _fin_exp_dre[_yr] = _v  # Despesas Financeiras (CVM 3.06.02, negativo)

            def _calc_cagr(data: dict) -> Optional[float]:
                yrs = sorted(data.keys())
                if len(yrs) < 2:
                    return None
                start_v, end_v = data[yrs[0]], data[yrs[-1]]
                n = int(yrs[-1]) - int(yrs[0])
                if n <= 0 or start_v <= 0 or end_v <= 0:
                    return None
                return round(((end_v / start_v) ** (1 / n) - 1) * 100, 1)

            if _cagr_earn is None:
                _cagr_earn = _calc_cagr(_profit)
            if _cagr_rev is None:
                _cagr_rev = _calc_cagr(_revenue)
            if _ebit_mil is None and _ebit_dre:
                _ebit_mil = _ebit_dre[max(_ebit_dre)]
            if _fin_exp_mil is None and _fin_exp_dre:
                _fin_exp_mil = _fin_exp_dre[max(_fin_exp_dre)]
            _ebit_historico = dict(_ebit_dre)

    # Histórico de indicadores (1 chamada): ROE p/ Gordon (bancos) + P/L e EV/EBITDA
    # por trimestre p/ valuation por REVERSÃO À MÉDIA (múltiplo mediano da própria
    # empresa). Fallback gracioso: listas vazias se a API não trouxer o campo.
    _roe_historico: list = []
    _pl_historico: list = []
    _ev_ebitda_historico: list = []
    _fh = get_fundamentals_history(t, limit=20)
    if _fh:
        for _h in (_fh.get("history") or []):
            for _campo, _lst in (("roe", _roe_historico),
                                 ("pl", _pl_historico),
                                 ("ev_ebitda", _ev_ebitda_historico)):
                _v = _h.get(_campo)
                if _v is not None:
                    try:
                        _lst.append(round(float(_v), 2))
                    except (TypeError, ValueError):
                        continue

    # PSR = Market Cap / Receita Líquida Anual
    _psr: Optional[float] = None
    _mc = fund.get("market_cap")
    _nr = fund.get("net_revenue")  # R$ mil
    if _mc and _nr and _nr > 0:
        _psr = _mc / (_nr * 1000)  # ambos em R$

    # Cobertura de Juros = EBIT / |Despesas Financeiras|
    _interest_coverage: Optional[float] = None
    if _ebit_mil is not None and _fin_exp_mil is not None and _fin_exp_mil != 0:
        _interest_coverage = _ebit_mil / abs(_fin_exp_mil)

    result.update(
        {
            # JSON bruto de /fundamentals — usado apenas para debug, removido antes de salvar
            "_raw_fund": dict(fund),
            # Identificação
            "ticker":             fund.get("ticker", t),
            "corporate_name":     fund.get("corporate_name", ""),
            "trade_name":         (company or {}).get("trade_name", ""),
            "sector":             _sector_final,
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
            "pl":                 _pl_out,
            "ebitda_margin":      fund.get("ebitda_margin"),
            "cagr_earnings_5y":   _cagr_earn,
            "cagr_revenue_5y":    _cagr_rev,
            "p_fcf":              p_fcf,
            "dividend_yield":     dividend_yield_ttm,
            "liquidity":          liquidity_brl,
            # ── Indicadores informativos (sem score) ───────────
            "pvp":          _pvp_out,
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
            "net_revenue":      fund.get("net_revenue"),  # R$ mil
            "avg_volume_52w":   avg_vol_shares,
            # ── Indicadores novos ──────────────────────────────
            "psr":              _psr,
            "fcl":              _fcl_k,          # FCL mais recente em R$ mil
            "fcl_historico":    _fcl_historico,  # {ano: FCL R$ mil} para normalização cíclica
            "ebit_historico":   _ebit_historico, # {ano: EBIT R$ mil} p/ EBITDA mid-cycle (cíclicas)
            "roe_historico":    _roe_historico,  # [ROE %] trimestral p/ normalizar Gordon (bancos)
            "pl_historico":     _pl_historico,        # [P/L] trimestral p/ reversão à média
            "ev_ebitda_historico": _ev_ebitda_historico,  # [EV/EBITDA] trimestral p/ reversão à média
            "interest_coverage": _interest_coverage,
        }
    )
    return result
