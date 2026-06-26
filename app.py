"""
App principal — Análise Fundamentalista B3
Fonte de dados: API Bolsai (usebolsai.com)
"""
from __future__ import annotations

import functools
import json
import math
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

import api
import score as sc
import score_fii as sf
import alerts as al
from score import classify_psr as _classify_psr, classify_interest_coverage as _classify_interest_coverage
import config as _cfg
from config import (
    BG_COLORS, COLOR_EMOJI, INDICATOR_LABELS,
    SCORE_COLORS, SECTOR_REMAP, SETORES_CICLICOS, UTILITY_KEYWORDS,
)

# Constantes de valuation por setor com FALLBACK embutido. O Streamlit Cloud
# já serviu config.py stale várias vezes (cache de .pyc), causando ImportError
# em nomes recém-adicionados. getattr garante que o app sobe mesmo se o
# config.py do servidor estiver desatualizado — o config continua sendo a
# fonte canônica quando o deploy está fresco.
INSURER_KEYWORDS = getattr(
    _cfg, "INSURER_KEYWORDS",
    ["seguradora", "seguradoras", "seguros", "seguridade", "resseguro"],
)
INSURER_FAIR_PE = getattr(_cfg, "INSURER_FAIR_PE", 10.0)
SHOPPING_KEYWORDS = getattr(
    _cfg, "SHOPPING_KEYWORDS", ["shopping", "centros comerciais"],
)
SHOPPING_FAIR_EV_EBITDA = getattr(_cfg, "SHOPPING_FAIR_EV_EBITDA", 10.5)

# ────────────────────────────────────────────────────────────────
# Configuração da página
# ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Análise Fundamentalista B3",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

DATA_FILE = Path("acoes_salvas.json")
TZ_BSB    = timezone(timedelta(hours=-3))
LISTAS_PADRAO = ["⭐ Carteira", "👁 Watchlist", "🔍 Pesquisa"]
USUARIOS = ["Gabriel", "Bolivar", "Danilo"]

def _now_bsb() -> datetime:
    return datetime.now(TZ_BSB)

SCORED_COLS_ORDER = [
    "net_debt_ebitda",
    "roe",
    "ev_ebitda",
    "pl",
    "ebitda_margin",
    "cagr_earnings_5y",
    "p_fcf",
    "dividend_yield",
    "liquidity",
    "cagr_revenue_5y",
]

# Indicadores usados no gráfico radar (6 de maior peso)
RADAR_INDICATORS = [
    "net_debt_ebitda",
    "roe",
    "ev_ebitda",
    "pl",
    "ebitda_margin",
    "liquidity",
]

# Pares (cor da linha, cor de preenchimento rgba) para até 4 ações no radar
RADAR_COLORS = [
    ("#4caf50", "rgba(76,175,80,0.20)"),
    ("#2196f3", "rgba(33,150,243,0.20)"),
    ("#ff9800", "rgba(255,152,0,0.20)"),
    ("#e91e63", "rgba(233,30,99,0.20)"),
]

# ────────────────────────────────────────────────────────────────
# Conteúdo dos popovers explicativos
# ────────────────────────────────────────────────────────────────
INDICATOR_INFO: dict[str, dict[str, str]] = {
    "net_debt_ebitda": {
        "o_que_mede": "Quantos anos de geração de caixa operacional seriam necessários para pagar toda a dívida líquida.",
        "por_que_importa": "Empresa muito endividada fica vulnerável em crises e paga juros altos, sobrando menos para o acionista.",
        "interpretacao": "Quanto menor, melhor. Valor negativo = caixa líquido (ótimo).",
        "faixa_ideal": "≤ 0,5× Excelente · até 1,5× Bom · até 2,5× Razoável · até 3,5× Atenção · acima: Proibitivo",
        "atencao": "Utilities e concessões suportam mais dívida por terem receita previsível — limite sobe para 3,5× Bom.",
    },
    "roe": {
        "o_que_mede": "Quanto a empresa lucra para cada R$ 1 de patrimônio dos acionistas.",
        "por_que_importa": "Mede a qualidade e eficiência do negócio — ROE alto e consistente geralmente cria valor no longo prazo.",
        "interpretacao": "Quanto maior, melhor.",
        "faixa_ideal": "≥ 25% Excelente · 15–25% Bom · 10–15% Razoável · 5–10% Atenção · abaixo: Proibitivo",
        "atencao": "ROE pode ser inflado artificialmente por dívida alta — sempre cruzar com Dív/EBITDA.",
    },
    "ev_ebitda": {
        "o_que_mede": "Quantas vezes o valor total da empresa (incluindo dívida) representa sua geração de caixa operacional anual.",
        "por_que_importa": "Múltiplo de valuation robusto — ignora estrutura de capital e depreciação, permitindo comparar empresas alavancadas e não.",
        "interpretacao": "Quanto menor, melhor.",
        "faixa_ideal": "≤ 5× Excelente · 5–8× Bom · 8–12× Razoável · 12–16× Atenção · acima: Proibitivo",
        "atencao": "Não usar para bancos — estrutura de capital é o negócio deles.",
    },
    "pl": {
        "o_que_mede": "Quantos anos de lucro atual seriam necessários para recuperar o investimento.",
        "por_que_importa": "Referência rápida de caro ou barato.",
        "interpretacao": "Existe faixa ideal — muito baixo pode ser armadilha de valor, muito alto significa pagar caro pelo crescimento.",
        "faixa_ideal": "5–10× Excelente · 10–15× Bom · 15–20× Razoável · 20–30× Atenção · acima ou negativo: Proibitivo",
        "atencao": "⚠️ P/L < 5× é marcado como **Inconclusivo** — pode ser armadilha de valor ou lucro não-recorrente. Confirme se o resultado é sustentável antes de concluir que a ação está barata. P/L negativo = prejuízo.",
    },
    "ebitda_margin": {
        "o_que_mede": "Percentual da receita que se converte em caixa operacional antes de juros, impostos e depreciação.",
        "por_que_importa": "Mede a eficiência operacional pura do negócio, independente de estrutura de capital.",
        "interpretacao": "Quanto maior, melhor.",
        "faixa_ideal": "≥ 30% Excelente · 20–30% Bom · 12–20% Razoável · 6–12% Atenção · abaixo: Proibitivo",
        "atencao": "Varejo tem margens estruturalmente menores — use comparação setorial.",
    },
    "cagr_earnings_5y": {
        "o_que_mede": "Taxa de crescimento anual composta do lucro líquido nos últimos 5 anos.",
        "por_que_importa": "Distingue empresa saudável de empresa em deterioração disfarçada — crescimento consistente é sinal de vitalidade.",
        "interpretacao": "Quanto maior, melhor. Positivo é o mínimo aceitável.",
        "faixa_ideal": "≥ 15% Excelente · 8–15% Bom · 0–8% Razoável · -10–0% Atenção · abaixo: Proibitivo",
        "atencao": "Um ano com resultado extraordinário distorce o CAGR — verificar se o crescimento é consistente.",
    },
    "p_fcf": {
        "o_que_mede": "Quanto o mercado paga pelo fluxo de caixa livre (lucro caixa real após investimentos).",
        "por_que_importa": "FCL é muito mais difícil de manipular contabilmente que o lucro — empresa com lucro alto e FCL negativo é sinal de alerta.",
        "interpretacao": "Quanto menor, melhor.",
        "faixa_ideal": "≤ 8× Excelente · 8–15× Bom · 15–22× Razoável · 22–30× Atenção · acima: Proibitivo",
        "atencao": "Disponível apenas no plano Pro da API Bolsai.",
    },
    "dividend_yield": {
        "o_que_mede": "Percentual do preço atual que a empresa pagou em dividendos nos últimos 12 meses.",
        "por_que_importa": "Dividendo consistente indica geração real de caixa e gestão alinhada com o acionista.",
        "interpretacao": "Quanto maior, melhor — mas dividendo insustentável é pior que nenhum.",
        "faixa_ideal": "≥ 8% Excelente · 5–8% Bom · 3–5% Razoável · 1–3% Atenção · abaixo: Proibitivo",
        "atencao": "DY alto com payout acima de 80% e FCL negativo é sinal de dividendo insustentável.",
    },
    "liquidity": {
        "o_que_mede": "Volume médio diário negociado em reais.",
        "por_que_importa": "Liquidez baixa significa que você pode não conseguir vender quando quiser, ou vender a preço ruim.",
        "interpretacao": "Quanto maior, melhor.",
        "faixa_ideal": "> R$ 5M Excelente · R$ 3–5M Bom · R$ 1–3M Razoável · R$ 500k–1M Atenção · abaixo: Proibitivo",
        "atencao": "Estimado via volume médio 52 semanas × preço atual — pode diferir do volume médio 21 dias.",
    },
    "cagr_revenue_5y": {
        "o_que_mede": "Taxa de crescimento anual composta da receita líquida nos últimos 5 anos.",
        "por_que_importa": "Receita crescendo é condição para lucro crescer no longo prazo — receita estagnada eventualmente comprime margens.",
        "interpretacao": "Quanto maior, melhor.",
        "faixa_ideal": "≥ 12% Excelente · 6–12% Bom · 0–6% Razoável · -5–0% Atenção · abaixo: Proibitivo",
        "atencao": "Crescimento por aquisições pode mascarar deterioração orgânica.",
    },
    "pvp": {
        "o_que_mede": "Quanto o mercado paga em relação ao valor contábil do patrimônio.",
        "por_que_importa": "P/VP abaixo de 1 pode indicar desconto patrimonial — empresa vale menos na bolsa do que seus ativos contábeis.",
        "interpretacao": "Existe faixa ideal — muito baixo pode sinalizar problema de qualidade dos ativos, muito alto exige ROE alto para justificar.",
        "faixa_ideal": "1–2× costuma ser razoável para a maioria. Bancos bons negociam entre 1–2,5×.",
        "atencao": "Indicador informativo — não entra no score.",
    },
    "psr": {
        "o_que_mede": "Quanto o mercado paga por cada R$ 1 de receita (Market Cap / Receita Líquida TTM).",
        "por_que_importa": "Útil para avaliar empresas sem lucro ainda ou com lucro distorcido, quando P/L não é confiável.",
        "interpretacao": "Quanto menor, melhor.",
        "faixa_ideal": "≤ 1× Excelente · 1–2× Bom · 2–4× Razoável · 4–6× Atenção · > 6× Proibitivo",
        "atencao": "Não considera margem nem rentabilidade — empresa com PSR baixo mas margens ruins pode não ser barata de verdade. Indicador informativo, não entra no score.",
    },
}


# ────────────────────────────────────────────────────────────────
# Persistência — Supabase (PostgreSQL)
# Fallback automático para arquivo local em desenvolvimento.
# ────────────────────────────────────────────────────────────────

def _sb_url() -> str:
    return st.secrets.get("SUPABASE_URL", "").rstrip("/")

def _sb_key() -> str:
    return st.secrets.get("SUPABASE_KEY", "")

def _sb_headers() -> dict:
    k = _sb_key()
    return {
        "apikey": k,
        "Authorization": f"Bearer {k}",
        "Content-Type": "application/json",
    }

def _sb_configured() -> bool:
    return bool(_sb_url() and _sb_key())


def _load_file_supabase() -> dict:
    """Carrega dados do Supabase (persiste entre redeploys do Streamlit Cloud)."""
    if not _sb_configured():
        return {}
    try:
        import requests as _req
        r = _req.get(
            f"{_sb_url()}/rest/v1/app_state?id=eq.1&select=dados",
            headers=_sb_headers(),
            timeout=10,
        )
        if r.status_code == 200 and r.json():
            return r.json()[0].get("dados") or {}
    except Exception:
        pass
    return {}


def _save_file_supabase(data: dict) -> None:
    """Salva dados no Supabase (upsert)."""
    if not _sb_configured():
        return
    try:
        import requests as _req
        headers = {**_sb_headers(), "Prefer": "resolution=merge-duplicates"}
        _req.post(
            f"{_sb_url()}/rest/v1/app_state",
            headers=headers,
            json={"id": 1, "dados": data},
            timeout=10,
        )
    except Exception:
        pass


def _load_file() -> dict:
    """Lê os dados — Supabase primeiro, arquivo local como fallback."""
    sb_data = _load_file_supabase()
    if sb_data:
        # cache local para leituras rápidas na mesma sessão
        try:
            DATA_FILE.write_text(json.dumps(sb_data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
        return sb_data
    # Fallback: arquivo local (desenvolvimento sem Supabase configurado)
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _load_usuario_data(usuario: str) -> dict:
    """Retorna dados de um usuário: {"listas": {…}, "screener_filtros": {…}, "fiis_listas": {…}}"""
    raw = _load_file()
    if "usuarios" in raw:
        return raw["usuarios"].get(usuario, {})
    # Legado (sem chave 'usuarios'): migra dados existentes para Gabriel
    if usuario == "Gabriel":
        if "listas" in raw:
            return {
                "listas": raw["listas"],
                "screener_filtros": raw.get("screener_filtros", {}),
                "fiis_listas": raw.get("fiis_listas", {}),
            }
        # formato muito antigo: dict plano de tickers
        listas: dict = {lp: {} for lp in LISTAS_PADRAO}
        for ticker, entry in raw.items():
            if isinstance(entry, dict) and "data" in entry:
                listas[LISTAS_PADRAO[0]][ticker] = entry
        return {"listas": listas, "screener_filtros": {}, "fiis_listas": {}}
    return {}


_HOLDING_PREFIXES = (
    "Emp. Adm. Part. - ",
    "Empresas Administradoras de Participações - ",
)


def _clean_sector(sector: str) -> str:
    """Remove o prefixo genérico de holding (ex.: 'Emp. Adm. Part. - Energia
    Elétrica' → 'Energia Elétrica')."""
    s = (sector or "").strip()
    for pfx in _HOLDING_PREFIXES:
        if s.startswith(pfx):
            return s[len(pfx):].strip()
    return s


def _apply_sector_remap(lista: dict) -> None:
    for ticker, entry in lista.items():
        if not isinstance(entry.get("data"), dict):
            continue
        if ticker in SECTOR_REMAP:
            entry["data"]["sector"] = SECTOR_REMAP[ticker]
        else:
            entry["data"]["sector"] = _clean_sector(entry["data"].get("sector", ""))


def load_data() -> dict:
    """Retorna a lista atual (compat com código legado que lê notas do disco)."""
    return st.session_state.get("acoes", {})


def _save_all() -> None:
    """Persiste dados do usuário atual no JSON (estrutura multi-usuário)."""
    usuario = st.session_state.get("usuario_atual")
    if not usuario:
        return
    raw = _load_file()
    # Migração: se ainda não tem estrutura multi-usuário, cria
    if "usuarios" not in raw:
        raw = {"usuarios": {u: {} for u in USUARIOS}}
    raw["usuarios"][usuario] = {
        "listas":           dict(st.session_state.get("todas_listas", {})),
        "screener_filtros": dict(st.session_state.get("screener_filtros", {})),
        "fiis_listas":      dict(st.session_state.get("fiis_listas", {})),
        "alertas":          list(st.session_state.get("alertas", [])),
    }
    DATA_FILE.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    # Persiste no Supabase para sobreviver a redeploys do Streamlit Cloud
    _save_file_supabase(raw)


def save_data(_data: dict = None) -> None:
    """Compat: salva tudo via _save_all."""
    _save_all()


# ────────────────────────────────────────────────────────────────
# Utilitários de formatação
# ────────────────────────────────────────────────────────────────

def _fmt_price(v) -> str:
    if v is None:
        return "—"
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_pct(v, decimals=1) -> str:
    if v is None:
        return "—"
    return f"{v:+.{decimals}f}%"


def _fmt_mcap(v) -> str:
    if v is None:
        return "—"
    if v >= 1e12:
        return f"R$ {v/1e12:.2f}T"
    if v >= 1e9:
        return f"R$ {v/1e9:.1f}B"
    if v >= 1e6:
        return f"R$ {v/1e6:.0f}M"
    return f"R$ {v:,.0f}"


def _fmt_quarter(date_str: str) -> str:
    """Converte 'YYYY-MM-DD' para formato trimestral '1T26'."""
    if not date_str:
        return "—"
    try:
        d = datetime.fromisoformat(date_str[:10]).date()
        q = (d.month - 1) // 3 + 1
        return f"{q}T{str(d.year)[2:]}"
    except Exception:
        return date_str[:7]


def _quarter_staleness(date_str: str) -> str:
    """Retorna classificação de cor para idade do balanço: '' / 'Atenção' / 'Proibitivo'."""
    if not date_str:
        return ""
    try:
        d = datetime.fromisoformat(date_str[:10]).replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - d).days
        if age_days > 365:
            return "Proibitivo"
        if age_days > 180:
            return "Atenção"
        return ""
    except Exception:
        return ""


def _staleness_color(updated_at_iso: Optional[str]) -> str:
    if not updated_at_iso:
        return "#f44336"
    try:
        dt = datetime.fromisoformat(updated_at_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - dt
        if age < timedelta(hours=24):
            return "#4caf50"
        elif age < timedelta(hours=48):
            return "#ff9800"
        else:
            return "#f44336"
    except Exception:
        return "#f44336"


def _fmt_updated(updated_at_iso: Optional[str]) -> str:
    if not updated_at_iso:
        return "Nunca atualizado"
    try:
        dt = datetime.fromisoformat(updated_at_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(TZ_BSB).replace(tzinfo=None)
        return dt.strftime("%d/%m/%Y às %H:%M")
    except Exception:
        return updated_at_iso


# ────────────────────────────────────────────────────────────────
# Inicialização do session_state
# ────────────────────────────────────────────────────────────────

def _switch_list(nova_lista: str) -> None:
    """Muda a lista ativa, sincronizando session_state."""
    st.session_state.lista_atual = nova_lista
    if nova_lista not in st.session_state.todas_listas:
        st.session_state.todas_listas[nova_lista] = {}
    st.session_state.acoes = st.session_state.todas_listas[nova_lista]
    st.session_state.selected_ticker = None


def _init_state():
    """Inicializa session_state a partir dos dados do usuário atual."""
    usuario = st.session_state.get("usuario_atual")
    if not usuario:
        return  # Aguarda seleção de usuário

    if "todas_listas" not in st.session_state:
        u_data = _load_usuario_data(usuario)
        todas = u_data.get("listas", {})
        for lp in LISTAS_PADRAO:
            if lp not in todas:
                todas[lp] = {}
        for lista in todas.values():
            _apply_sector_remap(lista)
        st.session_state.todas_listas = todas

    if "lista_atual" not in st.session_state:
        listas_keys = list(st.session_state.todas_listas.keys())
        st.session_state.lista_atual = listas_keys[0] if listas_keys else LISTAS_PADRAO[0]

    if "acoes" not in st.session_state:
        st.session_state.acoes = st.session_state.todas_listas.get(
            st.session_state.lista_atual, {}
        )

    if "screener_filtros" not in st.session_state:
        u_data = _load_usuario_data(usuario)
        st.session_state.screener_filtros = u_data.get("screener_filtros", {})

    if "fiis_listas" not in st.session_state:
        u_data = _load_usuario_data(usuario)
        fiis = u_data.get("fiis_listas", {})
        if not fiis:
            fiis = {"🏢 FIIs": {}}
        st.session_state.fiis_listas = fiis

    if "lista_fii_atual" not in st.session_state:
        fii_keys = list(st.session_state.fiis_listas.keys())
        st.session_state.lista_fii_atual = fii_keys[0] if fii_keys else "🏢 FIIs"

    if "alertas" not in st.session_state:
        st.session_state.alertas = _load_usuario_data(usuario).get("alertas", [])

    if "selected_ticker" not in st.session_state:
        st.session_state.selected_ticker = None
    if "flash_errors" not in st.session_state:
        st.session_state.flash_errors: list[str] = []
    if "flash_success" not in st.session_state:
        st.session_state.flash_success: str = ""
    if "debug_log" not in st.session_state:
        st.session_state.debug_log: list[str] = []
    if "debug_raw_fund" not in st.session_state:
        st.session_state.debug_raw_fund: Optional[dict] = None
    if "confirm_del_lista" not in st.session_state:
        st.session_state.confirm_del_lista = False
    if "selected_fii" not in st.session_state:
        st.session_state.selected_fii = None
    if "confirm_del_fii_lista" not in st.session_state:
        st.session_state.confirm_del_fii_lista = False


# ────────────────────────────────────────────────────────────────
# Fetch e persistência de uma ação
# ────────────────────────────────────────────────────────────────

def _fetch_ticker(ticker: str) -> Optional[str]:
    t = ticker.strip().upper()
    log = st.session_state.debug_log

    api_key = api._get_api_key()
    if api_key:
        log.append(f"✅ API Key encontrada ({api_key[:8]}…)")
    else:
        msg = "❌ API Key NÃO encontrada. Configure BOLSAI_API_KEY em Secrets."
        log.append(msg)
        return msg

    log.append(f"📡 Chamando: GET {api.BASE_URL}/fundamentals/{t}")

    try:
        data = api.get_all_stock_data(t)
    except Exception as e:
        err = f"Exceção ao buscar {t}: {type(e).__name__}: {e}"
        log.append(f"❌ {err}")
        return err

    if data.get("error"):
        log.append(f"⚠️ API retornou erro: {data['error']}")
        return data["error"]

    log.append(f"✅ {t} carregado: preço={data.get('close_price')}, setor={data.get('sector')!r}")

    raw_fund = data.pop("_raw_fund", {})
    st.session_state.debug_raw_fund = raw_fund

    log.append(
        f"📌 dividend_yield={raw_fund.get('dividend_yield')!r}"
        f"  |  cagr_earnings_5y={raw_fund.get('cagr_earnings_5y')!r}"
        f"  |  cagr_revenue_5y={raw_fund.get('cagr_revenue_5y')!r}"
    )
    log.append(f"📋 Total de campos retornados por /fundamentals: {len(raw_fund)}")

    # Força o ticker armazenado a ser o que o usuário digitou.
    # A Bolsai pode retornar fund["ticker"] = "ITUB4" mesmo para a query "ITUB3" —
    # usar esse valor causaria exibição errada na lista.
    data["ticker"] = t

    _prev = st.session_state.acoes.get(t, {})

    # Detecta mudanças de classificação em relação à versão anterior
    _cls_changes: list[dict] = []
    _prev_data = _prev.get("data", {})
    if _prev_data:
        _old_cls = sc.classify_all(_prev_data)
        _new_cls = sc.classify_all(data)
        for _ind, (_new_c, _new_d) in _new_cls.items():
            _old_c = _old_cls.get(_ind, ("", ""))[0]
            if _old_c and _old_c not in ("ND", "NA") and _new_c not in ("ND", "NA") and _old_c != _new_c:
                _cls_changes.append({
                    "ind":  INDICATOR_LABELS.get(_ind, _ind),
                    "de":   _old_c,
                    "para": _new_c,
                })

    st.session_state.acoes[t] = {
        "data":                   data,
        "updated_at":             _now_bsb().isoformat(),
        "qtd":                    _prev.get("qtd", 0),
        "preco_medio":            _prev.get("preco_medio", 0.0),
        "data_compra":            _prev.get("data_compra", ""),
        "notas":                  _prev.get("notas", ""),
        "notas_updated_at":       _prev.get("notas_updated_at", ""),
        "notas_mudancas":         _prev.get("notas_mudancas", ""),
        "notas_historico":        _prev.get("notas_historico", []),
        "classification_changes": _cls_changes,
    }
    st.session_state.todas_listas[st.session_state.lista_atual] = st.session_state.acoes
    _save_all()
    return None


def _update_all() -> list[str]:
    st.session_state.debug_log = []
    erros = []
    tickers = list(st.session_state.acoes.keys())
    progress = st.progress(0, text="Atualizando dados…")
    for i, t in enumerate(tickers):
        err = _fetch_ticker(t)
        if err:
            erros.append(f"{t}: {err}")
        progress.progress((i + 1) / len(tickers), text=f"Atualizando {t}…")
    progress.empty()
    return erros


# ────────────────────────────────────────────────────────────────
# Enriquecimento com score
# ────────────────────────────────────────────────────────────────

_EMPTY_SCORES = {
    "quality": None, "price": None, "diagnosis": None, "earnings_quality": None,
    "breakdown_quality": {}, "breakdown_price": {},
}


def _enrich(entry: dict) -> dict:
    stock = entry["data"]
    # getattr p/ resiliência ao hot-reload do Streamlit Cloud (módulo em cache
    # sem a função nova → degrada sem derrubar o app inteiro; reboot resolve).
    _calc = getattr(sc, "calculate_scores", None)
    scores = _calc(stock) if _calc else dict(_EMPTY_SCORES)
    return {**stock, "scores": scores}


def _score_band(v) -> str:
    """Mapeia um score 0-100 para o rótulo de faixa (para colorir)."""
    if v is None:
        return ""
    if v >= 80:   return "Excelente"
    elif v >= 60: return "Bom"
    elif v >= 40: return "Razoável"
    elif v >= 20: return "Atenção"
    return "Evitar"


def _score_color_hex(v) -> str:
    """Cor (hex) para um score 0-100 — usada em badges compactas."""
    return SCORE_COLORS.get(_score_band(v), "#9e9e9e")


# ────────────────────────────────────────────────────────────────
# Construção da tabela comparativa
# ────────────────────────────────────────────────────────────────

def _na(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


# Formatadores de exibição (o dtype continua numérico → ordenação correta).
# N/D = dado ausente (fallback); as overrides em _apply_styles distinguem N/A vs N/D.
def _ff_score(v): return "N/D" if _na(v) else f"{v:.0f}"
def _ff_price(v): return "N/D" if _na(v) else _fmt_price(v)
def _ff_var(v):   return "N/D" if _na(v) else f"{v:+.2f}%"
def _ff_pot(v):   return "N/D" if _na(v) else (f"↑ {v:.1f}%" if v >= 0 else f"↓ {abs(v):.1f}%")
def _ff_pct(v):   return "N/D" if _na(v) else f"{v:.1f}%"
def _ff_mult(v):  return "N/D" if _na(v) else f"{v:.2f}x"
def _ff_pvp(v):   return "N/D" if _na(v) else f"{v:.2f}×"
def _ff_liqM(v):  return "N/D" if _na(v) else f"R$ {v:.1f}M"
def _ff_pl(v):
    if _na(v):  return "N/D"
    if v < 0:   return "Prejuízo"
    if v < 5:   return f"⚠️ {v:.2f}x"
    return f"{v:.2f}x"

_TABLE_NUM_FMT = {
    "Cotação": _ff_price, "Potencial": _ff_pot, "Var.Dia": _ff_var,
    "Qualidade": _ff_score, "Atratividade": _ff_score,
    "Dív.Líq/EBITDA": _ff_mult, "ROE": _ff_pct, "EV/EBITDA": _ff_mult,
    "P/L": _ff_pl, "Mg. EBITDA": _ff_pct, "CAGR Lucro 5a": _ff_pct,
    "P/FCF": _ff_mult, "Div. Yield": _ff_pct, "Liquidez": _ff_liqM,
    "CAGR Rec. 5a": _ff_pct, "P/VP": _ff_pvp, "PSR": _ff_pvp,
}


def _build_table(stocks: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows_display = []
    rows_class = []

    for s in stocks:
        sector = s.get("sector", "")
        classifications = sc.classify_all(s)

        ref_date = s.get("reference_date", "")
        # Potencial de valorização — cenário Base/Esperado (motor por setor)
        _price_now = s.get("close_price")
        if sc.is_bank(sector):
            _target = _gordon_base_price(s)
        elif _is_insurer(sector):
            _target = _insurer_base_price(s)
        elif _is_shopping(sector):
            _target = _shopping_base_price(s)
        elif _is_cyclical(sector):
            _target = _cyclical_base_price(s)
        elif _is_utility(sector):
            _target = _dcf_base_price(s)
        else:
            _target = _geral_base_price(s)
        if _target is not None and _price_now and _price_now > 0:
            _pot_pct = (_target / _price_now - 1) * 100
            _pot_cls = "Positivo" if _pot_pct >= 0 else "Negativo"
        else:
            _pot_pct, _pot_cls = None, "ND"

        # Valores numéricos crus → o st.dataframe ordena numericamente (NumberColumn).
        display_row = {
            "Ticker":    s.get("ticker", ""),
            "Empresa":   s.get("trade_name") or s.get("corporate_name", ""),
            "Setor":     sector,
            "Balanço":   _fmt_quarter(ref_date),
            "Cotação":   _price_now,
            "Potencial": _pot_pct,
            "Var.Dia":   s.get("daily_change_pct"),
        }
        class_row = {
            "Ticker": s.get("ticker", ""), "Empresa": "", "Setor": "",
            "Balanço": _quarter_staleness(ref_date), "Cotação": "",
            "Potencial": _pot_cls, "Var.Dia": "",
        }

        # Scores separados: Qualidade × Preço (atratividade) + Diagnóstico
        _scores = s.get("scores") or sc.calculate_scores(s)
        _q = _scores.get("quality")
        _p = _scores.get("price")
        _diag = _scores.get("diagnosis")  # dict {label, verdict, color, ...} ou None
        display_row["Qualidade"]    = _q
        class_row["Qualidade"]      = _score_band(_q)
        display_row["Atratividade"] = _p
        class_row["Atratividade"]   = _score_band(_p)
        display_row["Diagnóstico"]  = _diag["label"] if _diag else "—"
        class_row["Diagnóstico"]    = ("verdict_" + _diag["verdict"]) if _diag else ""

        for ind in SCORED_COLS_ORDER:
            col_name = INDICATOR_LABELS.get(ind, ind)
            cls, _disp = classifications.get(ind, ("ND", "N/D"))
            raw = s.get(ind)
            if ind == "liquidity" and raw is not None:
                raw = raw / 1e6   # exibe/ordena em R$ milhões
            display_row[col_name] = None if cls in ("NA", "ND") else raw
            class_row[col_name] = cls

        pvp = s.get("pvp")
        cls_pvp, _ = sc.classify_pvp(pvp, sector)
        display_row["P/VP"] = pvp
        class_row["P/VP"] = cls_pvp

        cls_psr, _ = _classify_psr(s.get("psr"), sector)
        display_row["PSR"] = s.get("psr")
        class_row["PSR"] = cls_psr

        rows_display.append(display_row)
        rows_class.append(class_row)

    return pd.DataFrame(rows_display), pd.DataFrame(rows_class)


def _dedup_enriched(stocks: list[dict]) -> list[dict]:
    """Remove entradas com ticker vazio ou duplicado (mantém primeira ocorrência)."""
    seen: set = set()
    result = []
    for s in stocks:
        t = s.get("ticker") or ""
        if t and t not in seen:  # ignora ticker vazio — causaria índice não-único
            seen.add(t)
            result.append(s)
    return result


def _apply_styles(display_df: pd.DataFrame, class_df: pd.DataFrame):
    """Aplica cores às colunas classificadas. Robusto a índice/colunas não-únicos."""
    score_bg = {
        "Excelente":      "#1b5e20",
        "Bom":            "#2e7d32",
        "Razoável":       "#7b5800",
        "Atenção":        "#bf360c",
        "Evitar":         "#7f0000",
        "Setor Bancário": "#37474f",
        "NA":             "#37474f",
        # Veredito do diagnóstico Qualidade × Preço
        "verdict_boa_barata":   "#1b5e20",
        "verdict_boa_cara":     "#7b5800",
        "verdict_fraca_barata": "#bf360c",
        "verdict_fraca_cara":   "#7f0000",
    }
    colored_cols = {"Qualidade", "Atratividade", "Diagnóstico", "P/VP", "PSR", "Balanço", "Potencial"} | {INDICATOR_LABELS.get(i, i) for i in SCORED_COLS_ORDER}

    # Formata as colunas numéricas (display); o dtype continua numérico → ordena certo.
    _fmt_map = {c: f for c, f in _TABLE_NUM_FMT.items() if c in display_df.columns}

    # Pandas >= 2.x: _update_ctx lança KeyError se index ou columns não forem únicos.
    # Retorna sem cores em vez de travar o app.
    if not display_df.index.is_unique or not display_df.columns.is_unique:
        return display_df.style.format(_fmt_map)

    # Alinha class_df ao display_df (colunas extras recebem "" → sem cor)
    class_aligned = class_df.reindex(
        index=display_df.index,
        columns=display_df.columns,
        fill_value="",
    ).fillna("")

    styler = display_df.style.format(_fmt_map)

    # Override por célula: N/A (não aplicável ao setor) vs N/D (dado ausente).
    # Necessário pois column_config format= sobrescreveria o texto do Styler.
    for _col in display_df.columns:
        if _col not in class_aligned.columns:
            continue
        _na_rows = [i for i in display_df.index if class_aligned.loc[i, _col] == "NA"]
        _nd_rows = [i for i in display_df.index if class_aligned.loc[i, _col] == "ND"]
        try:
            if _na_rows:
                styler = styler.format("N/A", subset=pd.IndexSlice[_na_rows, [_col]])
            if _nd_rows:
                styler = styler.format("N/D", subset=pd.IndexSlice[_nd_rows, [_col]])
        except Exception:
            pass  # subset inválido em edge case — ignora silenciosamente

    for col in display_df.columns:
        if col not in colored_cols:
            continue
        is_score = col in ("Qualidade", "Atratividade", "Diagnóstico")

        # Default-args capturam os valores por cópia (evita bug de closure em loop)
        def _col_style(
            series: pd.Series,
            _col: str = col,
            _is_score: bool = is_score,
        ) -> pd.Series:
            out = pd.Series("", index=series.index, dtype=object)
            for idx in series.index:
                cls = ""
                try:
                    raw_cls = class_aligned.at[idx, _col]
                    cls = str(raw_cls) if raw_cls else ""
                except Exception:
                    cls = ""
                bg = score_bg.get(cls, "") if _is_score else BG_COLORS.get(cls, "")
                if bg:
                    out.at[idx] = (
                        f"background-color:{bg};color:#ffffff;"
                        "font-weight:600;text-align:center"
                    )
            return out

        try:
            styler = styler.apply(_col_style, axis=0, subset=[col])
        except Exception:
            pass  # coluna ausente ou edge-case residual — ignora

    return styler


# ────────────────────────────────────────────────────────────────
# Gráfico de posicionamento no intervalo de 52 semanas
# ────────────────────────────────────────────────────────────────

def _price_range_chart(s: dict) -> Optional[go.Figure]:
    low = s.get("week_52_low")
    high = s.get("week_52_high")
    current = s.get("close_price")
    if not (low and high and current and high > low):
        return None

    ytd = s.get("ytd_return_pct") or 0
    price_color = "#4caf50" if ytd >= 0 else "#f44336"

    fig = go.Figure()

    # Faixa cinza de fundo (low → high)
    fig.add_trace(go.Bar(
        x=[high - low],
        y=[""],
        base=[low],
        orientation="h",
        marker=dict(color="#2e3250", line=dict(width=0)),
        showlegend=False,
        hoverinfo="skip",
        width=0.4,
    ))

    # Marcador do preço atual
    fig.add_trace(go.Scatter(
        x=[current],
        y=[""],
        mode="markers",
        marker=dict(color=price_color, size=20, symbol="diamond",
                    line=dict(color="#ffffff", width=2)),
        name="Preço atual",
        hovertemplate=f"<b>Preço atual</b><br>R$ {current:.2f}<extra></extra>",
    ))

    # Anotações de mínimo e máximo
    fig.add_annotation(
        x=low, y=0.05, yref="paper",
        text=f"<b>Mín 52s</b><br>R$ {low:.2f}",
        showarrow=False, font=dict(color="#9e9e9e", size=11),
        xanchor="left",
    )
    fig.add_annotation(
        x=high, y=0.05, yref="paper",
        text=f"<b>Máx 52s</b><br>R$ {high:.2f}",
        showarrow=False, font=dict(color="#9e9e9e", size=11),
        xanchor="right",
    )
    fig.add_annotation(
        x=current, y=1.0, yref="paper",
        text=f"<b>R$ {current:.2f}</b>",
        showarrow=True, arrowhead=2, arrowcolor=price_color,
        font=dict(color=price_color, size=13),
        ay=-30,
    )

    ytd_sign = "+" if ytd >= 0 else ""
    fig.update_layout(
        title=dict(
            text=f"Intervalo de 52 Semanas  ·  YTD: {ytd_sign}{ytd:.1f}%",
            font=dict(color="#e8eaf6", size=13),
            x=0,
        ),
        xaxis=dict(
            tickformat=",.2f",
            tickprefix="R$ ",
            color="#9e9e9e",
            gridcolor="#2e3250",
            showgrid=True,
        ),
        yaxis=dict(showticklabels=False, showgrid=False, range=[-0.5, 0.5]),
        paper_bgcolor="#0e1117",
        plot_bgcolor="#1e2130",
        margin=dict(l=20, r=20, t=50, b=50),
        height=180,
        showlegend=False,
    )
    return fig


# ────────────────────────────────────────────────────────────────
# Gráfico radar
# ────────────────────────────────────────────────────────────────

def _radar_chart(stocks_data: list[dict], names: list[str]) -> go.Figure:
    labels = [INDICATOR_LABELS.get(i, i) for i in RADAR_INDICATORS]
    labels_closed = labels + [labels[0]]

    fig = go.Figure()

    for stock, name, (line_color, fill_color) in zip(stocks_data, names, RADAR_COLORS):
        _sec_r = stock.get("sector", "")
        values = []
        for ind in RADAR_INDICATORS:
            pts = sc.score_indicator(ind, stock.get(ind), _sec_r)
            values.append(pts if pts is not None else 0)
        values_closed = values + [values[0]]

        fig.add_trace(go.Scatterpolar(
            r=values_closed,
            theta=labels_closed,
            fill="toself",
            name=name,
            line=dict(color=line_color, width=2),
            fillcolor=fill_color,
            hovertemplate="<b>%{theta}</b><br>Pontuação: %{r}/100<extra>" + name + "</extra>",
        ))

    fig.update_layout(
        polar=dict(
            radialaxis=dict(
                visible=True,
                range=[0, 100],
                tickfont=dict(color="#9e9e9e", size=10),
                gridcolor="#333344",
                linecolor="#333344",
            ),
            angularaxis=dict(
                tickfont=dict(color="#e8eaf6", size=11),
                gridcolor="#333344",
                linecolor="#333344",
            ),
            bgcolor="#1e2130",
        ),
        showlegend=len(names) > 1,
        legend=dict(font=dict(color="#e8eaf6"), bgcolor="rgba(0,0,0,0)"),
        paper_bgcolor="#0e1117",
        margin=dict(l=40, r=40, t=40, b=40),
        height=380,
    )
    return fig


# ────────────────────────────────────────────────────────────────
# Insights contextuais por setor
# ────────────────────────────────────────────────────────────────

_SECTOR_INSIGHTS: dict[str, dict[str, str]] = {
    "net_debt_ebitda": {
        "bank":    "Não aplicável a bancos e financeiras — a dívida é o produto deles. Avalie pelo Índice de Basileia (mínimo regulatório 11%, confortável acima de 14%).",
        "util":    "Empresas de energia e transmissão têm receita regulada e contratos de longo prazo, o que suporta mais alavancagem. Dív/EBITDA até 3,5x é confortável no setor.",
        "retail":  "Varejistas usam capital de giro intensivamente. Dívida líquida negativa é comum e indica boa gestão de caixa operacional.",
        "civil":   "Construtoras costumam ter dívida baixa pois financiam obras com recebíveis de clientes. Dív/EBITDA acima de 2x merece atenção extra no setor.",
        "health":  "Empresas de saúde frequentemente se alavancam para aquisições de clínicas e hospitais. Até 2,5x é aceitável se o crescimento e margens justificarem.",
        "edu":     "Empresas de educação com modelo de mensalidades têm fluxo de caixa previsível. Dív/EBITDA até 2x é confortável; acima de 3x merece atenção dado o risco regulatório do setor.",
        "steel":   "Setor intensivo em capital com ciclos de commodity. Dívida deve ser analisada no contexto do ciclo — no pico parece baixa, no fundo parece alta.",
        "agro":    "Agronegócio tem sazonalidade intensa e dependência de commodity. Dívida deve ser analisada no contexto do ciclo agrícola e câmbio.",
        "textile": "Empresas de moda e vestuário têm sazonalidade intensa. Dívida até 2x é confortável; acima disso verificar gestão de estoques e ciclo de caixa.",
        "default": "Dívida líquida negativa significa mais caixa que dívida — situação excelente em qualquer setor.",
    },
    "roe": {
        "bank":    "Bancos bem geridos no Brasil têm ROE entre 18–25%. Abaixo de 15% indica ineficiência. Itaú e Bradesco historicamente mantêm acima de 20%.",
        "util":    "Setor regulado naturalmente tem ROE entre 12–20% pela previsibilidade da receita. ROE acima de 20% é excelente para o setor.",
        "retail":  "Varejistas eficientes costumam ter ROE alto (20–40%) por usar muito capital de terceiros. Cruzar sempre com endividamento para verificar sustentabilidade.",
        "civil":   "Construtoras bem geridas têm ROE entre 15–25%. Acima de 30% pode indicar alavancagem excessiva ou resultado não-recorrente.",
        "health":  "Hospitais e operadoras bem geridos têm ROE entre 15–25%. Operadoras de planos de saúde podem ter ROE menor mas mais previsível.",
        "edu":     "Educação bem gerida tem ROE entre 15–30%. Empresas com grande base de alunos e baixo churn costumam manter ROE alto de forma consistente.",
        "steel":   "ROE de siderúrgicas é muito cíclico — pode variar de negativo a 30%+ ao longo do ciclo. Preferir média de 5–7 anos ao valor pontual.",
        "agro":    "ROE de empresas agrícolas varia muito com preço de commodities e câmbio. Média de 5 anos é mais representativa que o valor pontual.",
        "textile": "Marcas fortes de vestuário com ROE acima de 20% indicam poder de precificação e fidelização. Abaixo de 12% sugere commoditização ou gestão ineficiente.",
        "default": "ROE consistentemente acima de 15% por vários anos é o principal sinal de qualidade de um negócio.",
    },
    "ev_ebitda": {
        "bank":    "Não aplicável a bancos — use P/VP como múltiplo principal. Bancos de qualidade negociam P/VP entre 1,5–2,5x.",
        "util":    "Utilities brasileiras tipicamente negociam entre 7–12x pela previsibilidade do fluxo de caixa. Abaixo de 7x pode ser oportunidade rara.",
        "retail":  "Varejistas eficientes negociam entre 5–10x. Acima de 12x o mercado precifica crescimento que pode não se materializar.",
        "civil":   "Construtoras com bom landbank e execução costumam negociar entre 4–8x. O ciclo do setor impacta muito os múltiplos.",
        "health":  "Saúde no Brasil historicamente negocia premium (10–16x) pela resiliência da demanda e consolidação do setor.",
        "edu":     "Setor educacional no Brasil negocia entre 4–10x. Empresas com crescimento de matrículas acima de 10% ao ano podem justificar múltiplos maiores.",
        "steel":   "Múltiplos de commodities são altamente cíclicos. EV/EBITDA abaixo de 4x no fundo do ciclo frequentemente é oportunidade; acima de 8x no pico é sinal de cautela.",
        "agro":    "Empresas de agronegócio negociam entre 4–8x em ciclos normais. Muito sensíveis ao câmbio e preço internacional das commodities.",
        "default": "EV/EBITDA abaixo de 6x com ROE alto é combinação rara e valiosa no mercado brasileiro.",
    },
    "ebitda_margin": {
        "util":    "Transmissoras e distribuidoras bem operadas devem ter Margem EBITDA acima de 35%. Abaixo disso indica ineficiência operacional ou pressão regulatória.",
        "retail":  "Varejo tem margens estruturalmente menores (6–15%). Comparar sempre com pares do setor, não com empresas de outros segmentos.",
        "civil":   "Margens entre 15–25% são típicas. Acima de 25% indica eficiência operacional acima da média ou mix de produtos premium (alto padrão).",
        "health":  "Hospitais e clínicas costumam ter 15–25%. Operadoras de planos têm margens menores mas mais previsíveis. Farmácias têm margens mais baixas ainda (8–15%).",
        "edu":     "Faculdades presenciais têm margem entre 20–35%. EAD pode ter margens acima de 40% pela escalabilidade do modelo.",
        "steel":   "Siderúrgicas eficientes têm Margem EBITDA entre 15–30% no ciclo normal. Margens acima de 30% geralmente ocorrem no pico e não são sustentáveis.",
        "agro":    "Processadoras de alimentos têm margens entre 10–20%. Produtores agrícolas puros podem ter margens maiores mas com alta volatilidade.",
        "textile": "Empresas de moda com marca forte têm margens entre 15–25%. Empresas mais commoditizadas ficam entre 8–15%.",
        "tech":    "Empresas de software bem posicionadas têm margens acima de 30%. Abaixo de 20% indica concorrência intensa ou fase de investimento.",
        "default": "Margem EBITDA estável ou crescente ao longo dos anos é mais importante que o valor absoluto isolado.",
    },
    "pl": {
        "bank":    "Bancos brasileiros de qualidade negociam entre 8–12x P/L. Acima de 15x indica crescimento premium precificado. Abaixo de 7x pode indicar problema de qualidade de ativos.",
        "util":    "Utilities costumam negociar entre 10–16x P/L pela estabilidade dos dividendos. São comparáveis a títulos de renda fixa de longo prazo.",
        "retail":  "Varejistas crescendo rapidamente podem justificar P/L entre 15–25x. Acima disso o risco de execução e competição aumenta muito.",
        "civil":   "Construtoras ciclicamente negociam entre 5–12x. P/L abaixo de 8x com ROE alto frequentemente representa oportunidade no setor.",
        "health":  "Setor defensivo que justifica P/L entre 15–25x pela resiliência. Abaixo de 12x pode ser oportunidade se os fundamentos operacionais estiverem sólidos.",
        "edu":     "P/L muito baixo em educação pode refletir resultado não-recorrente ou reconhecimento antecipado de receita. Verificar se o EBITDA confirma a rentabilidade.",
        "steel":   "P/L de empresas cíclicas é enganoso — no pico do ciclo parece alto e no fundo parece baixo. Preferir EV/EBITDA normalizado.",
        "agro":    "Assim como siderurgia, P/L de agronegócio é enganoso no ciclo. Preferir análise por EV/EBITDA normalizado e geração de caixa.",
        "textile": "Setor cíclico com sazonalidade — analisar resultados anualizados, não trimestrais isolados.",
        "default": "P/L deve ser analisado junto com a taxa de crescimento. Uma empresa crescendo 20% ao ano com P/L de 20x pode ser mais barata que uma estagnada com P/L de 10x.",
    },
    "cagr_earnings_5y": {
        "bank":    "Crescimento de carteira de crédito de 10–20% ao ano é saudável. Crescimento muito acima disso pode indicar deterioração da qualidade do crédito.",
        "util":    "Setor regulado cresce mais lentamente (5–10% ao ano) mas com altíssima previsibilidade. Crescimento acima de 12% é excepcional.",
        "retail":  "Varejistas em expansão de lojas frequentemente crescem lucro 15–25% ao ano. Verificar se crescimento é orgânico ou por aquisições.",
        "civil":   "Crescimento de construtoras é muito cíclico — um CAGR positivo de 5 anos é mais significativo que em setores mais estáveis. Verificar lançamentos e VSO.",
        "health":  "Crescimento de 10–20% ao ano é viável dado o envelhecimento da população e subpenetração de planos de saúde no Brasil.",
        "edu":     "Crescimento em educação é influenciado por expansão de matrículas e aquisições. Verificar crescimento orgânico separado de M&A.",
        "steel":   "CAGR de receita em commodities é fortemente influenciado pelo preço da matéria-prima. Focar em crescimento de volume e eficiência de custo.",
        "agro":    "Crescimento de receita fortemente influenciado por preço de commodity e câmbio. Focar em crescimento de volume e expansão de área plantada.",
        "textile": "Crescimento sustentável vem de expansão de canais (digital + físico) e fortalecimento de marca. Verificar crescimento de mesmas lojas (SSS).",
        "default": "CAGR de lucro consistentemente acima da inflação (~5%) é o mínimo para preservação real de valor.",
    },
    "cagr_revenue_5y": {
        "bank":    "Crescimento de carteira de crédito de 10–20% ao ano é saudável. Crescimento muito acima disso pode indicar deterioração da qualidade do crédito.",
        "util":    "Setor regulado cresce mais lentamente (5–10% ao ano) mas com altíssima previsibilidade. Crescimento acima de 12% é excepcional.",
        "retail":  "Varejistas em expansão de lojas frequentemente crescem receita 15–25% ao ano. Crescimento de SSS (mesmas lojas) acima de 5% real é excelente.",
        "civil":   "Crescimento de construtoras é muito cíclico — um CAGR positivo de 5 anos é mais significativo que em setores mais estáveis. Verificar VSO.",
        "health":  "Crescimento de 10–20% ao ano é viável dado o envelhecimento da população e subpenetração de planos de saúde no Brasil.",
        "edu":     "Crescimento em educação é influenciado por expansão de matrículas e aquisições. Verificar crescimento orgânico separado de M&A.",
        "steel":   "Crescimento de receita em commodities é fortemente influenciado pelo preço da matéria-prima. Focar em crescimento de volume e eficiência de custo.",
        "agro":    "Crescimento de receita fortemente influenciado por preço de commodity e câmbio. Focar em crescimento de volume e expansão de área plantada.",
        "textile": "Crescimento sustentável vem de expansão de canais (digital + físico) e fortalecimento de marca. Verificar crescimento de mesmas lojas (SSS).",
        "default": "CAGR de receita consistentemente acima da inflação (~5%) é o mínimo para preservação real de valor.",
    },
    "liquidity": {
        "default": "Volume abaixo de R$ 1M/dia limita o tamanho da posição que você pode montar ou desmontar sem impactar o preço. Para posições acima de R$ 50k, prefira ações com volume acima de R$ 5M/dia.",
    },
}


def _sector_insight(ind: str, sector: str) -> str:
    """Retorna insight setorial para o popover do indicador, ou '' se não mapeado."""
    ind_map = _SECTOR_INSIGHTS.get(ind)
    if not ind_map:
        return ""
    s = sector.lower()
    # Detecção de setor por substrings (case-insensitive, já normalizado acima)
    is_bank    = any(k in s for k in ["banco", "financ", "crédit", "credit", "segur", "bancári"])
    is_util    = any(k in s for k in ["energ", "saneamento", "concess", "transmiss", "utilit", "gás", "agua", "água"])
    is_retail  = any(k in s for k in ["varejo", "comércio", "comercio", "atacado", "supermercado"])
    is_civil   = any(k in s for k in ["constru", "incorpor", "imobili"])
    is_health  = any(k in s for k in ["saúde", "saude", "hospit", "médic", "medic", "farmac", "clínica", "clinica"])
    is_edu     = any(k in s for k in ["educa"])
    is_steel   = any(k in s for k in ["metal", "sider", "aço", "aco", "miner"])
    is_agro    = any(k in s for k in ["agro", "açúcar", "acucar", "agricultur", "aliment"])
    is_textile = any(k in s for k in ["têxtil", "textil", "vestuário", "vestuario"])
    is_tech    = any(k in s for k in ["tecnologia", "software", "internet", "telecomunicaç"])

    if is_bank    and "bank"    in ind_map: return ind_map["bank"]
    if is_util    and "util"    in ind_map: return ind_map["util"]
    if is_retail  and "retail"  in ind_map: return ind_map["retail"]
    if is_civil   and "civil"   in ind_map: return ind_map["civil"]
    if is_health  and "health"  in ind_map: return ind_map["health"]
    if is_edu     and "edu"     in ind_map: return ind_map["edu"]
    if is_steel   and "steel"   in ind_map: return ind_map["steel"]
    if is_agro    and "agro"    in ind_map: return ind_map["agro"]
    if is_textile and "textile" in ind_map: return ind_map["textile"]
    if is_tech    and "tech"    in ind_map: return ind_map["tech"]
    return ind_map.get("default", "")


# ────────────────────────────────────────────────────────────────
# Painel macro — dados macroeconômicos em tempo real (Pro)
# ────────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_macro() -> dict:
    result: dict = {}
    try:
        s = api.get_macro_series("selic")
        if s and s.get("data"):
            daily = s["data"][0]["value"]
            result["selic"] = round(((1 + daily / 100) ** 252 - 1) * 100, 2)
    except Exception:
        pass
    try:
        ip = api.get_macro_series("ipca")
        if ip and ip.get("data"):
            vals = [d["value"] for d in ip["data"][:12]]
            result["ipca_12m"] = round((math.prod(1 + v / 100 for v in vals) - 1) * 100, 2)
    except Exception:
        pass
    try:
        usd = api.get_macro_series("usd_brl")
        if usd and usd.get("data"):
            pts = usd["data"]
            result["usd_brl"] = pts[0]["value"]
            if len(pts) >= 2:
                result["usd_1d_chg"] = (pts[0]["value"] - pts[1]["value"]) / pts[1]["value"] * 100
    except Exception:
        pass
    try:
        _bvsp = yf.Ticker("BOVA11.SA")
        _fi = _bvsp.fast_info
        _ibov_price = _fi.last_price
        _ibov_prev = _fi.previous_close
        if _ibov_price and _ibov_prev and _ibov_prev > 0:
            result["ibov_price"] = round(float(_ibov_price), 2)
            result["ibov_chg"] = round(float(_ibov_price / _ibov_prev - 1) * 100, 2)
        _now = datetime.now()
        _ytd = _bvsp.history(start=f"{_now.year}-01-02", interval="1d")
        if not _ytd.empty and _ibov_price:
            _ytd_first = float(_ytd["Close"].iloc[0])
            if _ytd_first > 0:
                result["ibov_ytd"] = round((float(_ibov_price) / _ytd_first - 1) * 100, 1)
    except Exception:
        pass
    try:
        # SMAL11 é o ETF iShares Small Cap (SMLL11 está deslistado no Yahoo Finance)
        _smll = yf.Ticker("SMAL11.SA")
        _fi = _smll.fast_info
        _smll_price = _fi.last_price
        _smll_prev = _fi.previous_close
        if _smll_price and _smll_prev and _smll_prev > 0:
            result["smll_price"] = round(float(_smll_price), 2)
            result["smll_chg"] = round(float(_smll_price / _smll_prev - 1) * 100, 2)
        _now = datetime.now()
        _ytd = _smll.history(start=f"{_now.year}-01-02", interval="1d")
        if not _ytd.empty and _smll_price:
            _ytd_first = float(_ytd["Close"].iloc[0])
            if _ytd_first > 0:
                result["smll_ytd"] = round((float(_smll_price) / _ytd_first - 1) * 100, 1)
    except Exception:
        pass
    return result


def _show_macro_panel() -> None:
    macro = _fetch_macro()
    col_hdr, col_btn = st.columns([11, 1])
    with col_hdr:
        st.markdown("**📈 Contexto de Mercado**")
    with col_btn:
        if st.button("🔄", help="Atualizar painel macro", key="macro_refresh"):
            _fetch_macro.clear()
            st.rerun()

    c1, c2, c3, c4, c5, c6, c7 = st.columns(7)

    with c1:
        st.markdown("**Ibovespa (BOVA11)**")
        price = macro.get("ibov_price")
        chg = macro.get("ibov_chg") or 0
        chg_col = "#4caf50" if chg >= 0 else "#f44336"
        if price:
            st.markdown(
                f"R$ {price:,.2f} "
                f"<span style='color:{chg_col};font-size:0.85rem'>{chg:+.2f}%</span>",
                unsafe_allow_html=True,
            )
        else:
            st.caption("Indisponível")
        pl = macro.get("ibov_pl")
        if pl:
            if pl < 10:
                bg, lbl = "#2e7d32", "Barato"
            elif pl <= 14:
                bg, lbl = "#7b5800", "Neutro"
            else:
                bg, lbl = "#7f0000", "Caro"
            st.markdown(
                f"P/L {pl:.1f}× "
                f"<span style='background:{bg};color:#fff;padding:1px 5px;"
                f"border-radius:3px;font-size:0.72rem'>{lbl}</span> "
                f"<span style='font-size:0.72rem;color:#9e9e9e'>(média histórica ~12×)</span>",
                unsafe_allow_html=True,
            )

    with c2:
        st.markdown("**Small Caps (SMAL11)**")
        sp = macro.get("smll_price")
        sc_chg = macro.get("smll_chg") or 0
        sc_col = "#4caf50" if sc_chg >= 0 else "#f44336"
        if sp:
            st.markdown(
                f"R$ {sp:,.2f} "
                f"<span style='color:{sc_col};font-size:0.85rem'>{sc_chg:+.2f}%</span>",
                unsafe_allow_html=True,
            )
        else:
            st.caption("Indisponível", help="Fonte de dados para Small Caps instável — em verificação.")

    with c3:
        ibov_ytd = macro.get("ibov_ytd")
        smll_ytd = macro.get("smll_ytd")
        st.markdown("**Ibov vs Small (YTD)**")
        if ibov_ytd is not None and smll_ytd is not None:
            diff = smll_ytd - ibov_ytd
            if diff > 2:
                bg_badge, txt_badge = "#1b5e20", "Small Caps ↑"
            elif diff < -2:
                bg_badge, txt_badge = "#bf360c", "Ibov ↑"
            else:
                bg_badge, txt_badge = "#37474f", "Pareados"
            st.markdown(
                f"<span style='white-space:nowrap'>Ibov: <b>{ibov_ytd:+.1f}%</b></span><br>"
                f"<span style='white-space:nowrap'>SMLL: <b>{smll_ytd:+.1f}%</b></span><br>"
                f"<span style='background:{bg_badge};color:#fff;padding:1px 6px;"
                f"border-radius:3px;font-size:0.72rem'>{txt_badge}</span>",
                unsafe_allow_html=True,
            )
        else:
            st.caption("Indisponível")

    with c4:
        st.markdown("**USD / BRL**")
        usd = macro.get("usd_brl")
        usd_chg = macro.get("usd_1d_chg") or 0
        usd_col = "#f44336" if usd_chg > 0 else "#4caf50"
        if usd:
            st.markdown(
                f"R$ {usd:.4f} "
                f"<span style='color:{usd_col};font-size:0.85rem'>{usd_chg:+.2f}%</span>",
                unsafe_allow_html=True,
            )
        else:
            st.caption("Indisponível")

    with c5:
        st.markdown("**Selic (a.a.)**")
        selic = macro.get("selic")
        if selic:
            st.markdown(f"**{selic:.2f}%**")
        else:
            st.caption("Indisponível")

    with c6:
        st.markdown("**IPCA 12m**")
        ipca = macro.get("ipca_12m")
        selic = macro.get("selic") or 0
        if ipca:
            juro_real = ((1 + selic / 100) / (1 + ipca / 100) - 1) * 100
            st.markdown(f"**{ipca:.2f}%**")
            st.caption(f"Juro real: {juro_real:.1f}% a.a.")
        else:
            st.caption("Indisponível")

    with c7:
        _cart = st.session_state.get("_macro_cart") or {}
        st.markdown("**Minha Carteira**")
        _cv  = _cart.get("valor")
        _cp  = _cart.get("pnl_pct")
        _cvd = _cart.get("var_dia")
        if _cv is not None:
            _pnl_col = "#34d399" if (_cp or 0) >= 0 else "#f87171"
            _vd_col  = "#34d399" if (_cvd or 0) >= 0 else "#f87171"
            st.markdown(
                f"R$ {_cv:,.0f}<br>"
                f"<span style='color:{_pnl_col};font-size:0.85rem'>"
                f"{'↑' if (_cp or 0) >= 0 else '↓'} {abs(_cp):.1f}% total</span>",
                unsafe_allow_html=True,
            )
            if _cvd is not None:
                st.caption(
                    f"Hoje: "
                    f"<span style='color:{_vd_col}'>{_cvd:+.2f}%</span>",
                    unsafe_allow_html=True,
                )
        else:
            st.caption("Sem posições")

    st.divider()


# ────────────────────────────────────────────────────────────────
# Histórico de preços (Pro) + BOVA11 para comparação
# ────────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_bova11_history(n_days: int) -> Optional[pd.DataFrame]:
    """Busca histórico do BOVA11 via yfinance para os últimos n_days pregões."""
    try:
        bova = yf.Ticker("BOVA11.SA")
        start = (datetime.now() - timedelta(days=int(n_days * 1.6) + 30)).strftime("%Y-%m-%d")
        hist = bova.history(start=start)
        if hist.empty:
            return None
        df = hist.reset_index()[["Date", "Close"]].rename(columns={"Date": "date", "Close": "close"})
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
        return df.tail(n_days).reset_index(drop=True)
    except Exception:
        return None


@st.cache_data(ttl=3600 * 6, show_spinner=False)
def _fetch_ibov_vs_small(years: int = 5) -> Optional[pd.DataFrame]:
    """Histórico diário de BOVA11 (Ibov) e SMAL11 (Small Caps) alinhado, via yfinance."""
    try:
        start = (datetime.now() - timedelta(days=365 * years + 30)).strftime("%Y-%m-%d")
        ibov = yf.Ticker("BOVA11.SA").history(start=start)["Close"]
        small = yf.Ticker("SMAL11.SA").history(start=start)["Close"]
        if ibov.empty or small.empty:
            return None
        df = pd.DataFrame({"Ibov": ibov, "Small": small}).dropna()
        if len(df) < 30:
            return None
        df.index = pd.to_datetime(df.index).tz_localize(None)
        return df
    except Exception:
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_price_history(ticker: str) -> Optional[pd.DataFrame]:
    try:
        data = api.get_stock_history(ticker, limit=1260)
        if not data or not data.get("prices"):
            return None
        df = pd.DataFrame(data["prices"])
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df = df.sort_values("trade_date").reset_index(drop=True)
        df["ma50"] = df["adjusted_close"].rolling(50, min_periods=1).mean()
        return df
    except Exception:
        return None


def _chart_pct_pill(label_left: str, pct: float, extra: str = "") -> str:
    """Pill destacado com a variação do período (verde/vermelho) + rótulo à esquerda."""
    up = pct >= 0
    txt = "#34d399" if up else "#f87171"
    bg  = "#0c2a23" if up else "#2a0f14"
    bd  = "#1f4a3d" if up else "#4a1f28"
    return (
        "<div style='display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:2px 0 10px'>"
        f"<span style='font-weight:600;color:#e8ecf4;font-size:0.95rem'>{label_left}</span>"
        f"<span style='font-size:1.2rem;font-weight:800;color:{txt};background:{bg};"
        f"border:1px solid {bd};padding:4px 15px;border-radius:999px'>{pct:+.2f}%</span>"
        f"{extra}</div>"
    )


def _show_price_history_chart(s: dict) -> None:
    ticker = s.get("ticker", "")
    df = _fetch_price_history(ticker)

    if df is None or df.empty:
        # Fallback para gráfico de 52 semanas
        fig = _price_range_chart(s)
        if fig:
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        else:
            st.info("Dados de preço indisponíveis.")
        return

    periods = {"1D": 1, "5D": 5, "1M": 21, "3M": 63, "6M": 126, "1A": 252, "3A": 756, "5A": 1260}
    ctrl_cols = st.columns([5, 2, 3])
    with ctrl_cols[0]:
        sel = st.radio(
            "Período:", list(periods.keys()), index=5, horizontal=True,
            key=f"hist_period_{ticker}",
        )
    with ctrl_cols[1]:
        show_ma   = st.checkbox(
            "MM50", value=False, key=f"hist_ma_{ticker}",
            help=(
                "**Média Móvel de 50 dias** — média do preço dos últimos 50 pregões, "
                "suaviza o ruído e mostra a **tendência de médio prazo** (~2,5 meses).\n\n"
                "- Preço **acima** e linha subindo → tendência de alta; **abaixo** e caindo → baixa.\n"
                "- Preço muito **distante** da linha → esticado (sobrecomprado/sobrevendido).\n"
                "- Em tendências, costuma servir de **suporte/resistência** dinâmica.\n\n"
                "É **análise técnica** (timing de preço), complementar ao resto do app, que é "
                "**fundamentalista** (qualidade e valuation). Indicador *atrasado*: confirma "
                "tendências, não prevê reversões, e dá sinais falsos em mercado lateral."
            ),
        )
    with ctrl_cols[2]:
        show_ibov = st.checkbox("📊 Comparar com Ibovespa", value=False, key=f"hist_ibov_{ticker}")

    n_days  = periods[sel]
    # 1D: usa os 2 últimos pregões (fechamento anterior → atual) para formar uma linha
    # em vez de um único ponto. API só tem dados diários — intraday não disponível.
    df_plot = df.tail(max(n_days, 2) if n_days == 1 else n_days)
    _line_mode = "lines+markers" if n_days <= 7 else "lines"

    # Pill destacado com a variação do período
    _pct_period = (df_plot["adjusted_close"].iloc[-1] / df_plot["adjusted_close"].iloc[0] - 1) * 100
    _daily_chg  = s.get("daily_change_pct")  # variação do dia atual (API)
    _pct_show   = _daily_chg if (n_days == 1 and _daily_chg is not None) else _pct_period
    st.markdown(_chart_pct_pill(f"{ticker} — {sel}", _pct_show), unsafe_allow_html=True)

    # Modo comparativo (normalizado em base 100) vs. modo preço absoluto
    if show_ibov:
        df_ibov = _fetch_bova11_history(n_days)
        if df_ibov is not None and not df_ibov.empty:
            base_s = df_plot["adjusted_close"].iloc[0]
            base_i = df_ibov["close"].iloc[0]
            y_stock = (df_plot["adjusted_close"] / base_s * 100).values
            y_ibov  = (df_ibov["close"] / base_i * 100).values
            pct     = (y_stock[-1] - 100)
            pct_ibov= (y_ibov[-1] - 100)
            line_col = "#34d399" if pct >= 0 else "#f87171"
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=df_plot["trade_date"].values, y=y_stock,
                mode=_line_mode, name=ticker,
                line=dict(color=line_col, width=2),
                hovertemplate=f"<b>%{{x|%d/%m/%Y}}</b><br>{ticker}: %{{y:.1f}} ({pct:+.1f}%)<extra></extra>",
            ))
            fig.add_trace(go.Scatter(
                x=df_ibov["date"].values, y=y_ibov,
                mode="lines", name="Ibovespa",
                line=dict(color="#9e9e9e", width=1.5, dash="dot"),
                hovertemplate=f"<b>%{{x|%d/%m/%Y}}</b><br>Ibovespa: %{{y:.1f}} ({pct_ibov:+.1f}%)<extra></extra>",
            ))
            if show_ma:  # MM50 normalizada na mesma base 100 da ação
                y_ma = (df_plot["ma50"] / base_s * 100).values
                fig.add_trace(go.Scatter(
                    x=df_plot["trade_date"].values, y=y_ma,
                    mode="lines", name="MM50",
                    line=dict(color="#ff9800", width=1.5, dash="dot"),
                    hovertemplate="MM50: %{y:.1f}<extra></extra>",
                ))
            fig.update_layout(
                height=280, margin=dict(l=0, r=0, t=8, b=0),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                xaxis=dict(showgrid=False, color="#9e9e9e"),
                yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.06)", color="#9e9e9e",
                           ticksuffix=""),
                showlegend=True, legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color="#c8cce0")),
                title=dict(
                    text=f"{ticker} vs Ibovespa — {sel}  |  {ticker}: {pct:+.1f}%  Ibov: {pct_ibov:+.1f}%",
                    font=dict(size=12, color="#e8eaf6"),
                ),
            )
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
            return
        else:
            st.caption("⚠️ Dados do Ibovespa indisponíveis — exibindo preço absoluto.")

    # Modo padrão: preço absoluto
    pct = _pct_period
    line_col = "#34d399" if pct >= 0 else "#f87171"
    fill_col = "rgba(52,211,153,0.07)" if pct >= 0 else "rgba(248,113,113,0.07)"

    _xfmt = "%d/%m" if n_days > 5 else "%d/%m %Hh"
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_plot["trade_date"], y=df_plot["adjusted_close"],
        mode=_line_mode, name="Preço ajustado",
        line=dict(color=line_col, width=2),
        fill="tozeroy", fillcolor=fill_col,
        hovertemplate=f"<b>%{{x|{_xfmt}}}</b><br>R$ %{{y:.2f}}<extra></extra>",
    ))
    if show_ma:
        fig.add_trace(go.Scatter(
            x=df_plot["trade_date"], y=df_plot["ma50"],
            mode="lines", name="MM50",
            line=dict(color="#ff9800", width=1.5, dash="dot"),
            hovertemplate="MM50: R$ %{y:.2f}<extra></extra>",
        ))
    # Eixo X: 1D/5D → formato de data curto sem horário degenerado
    _xaxis_cfg = dict(
        showgrid=False, color="#9e9e9e",
        tickformat="%d/%m/%y" if n_days >= 21 else "%d/%m",
        nticks=6,
    )
    fig.update_layout(
        height=280, margin=dict(l=0, r=0, t=8, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis=_xaxis_cfg,
        yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.06)", color="#9e9e9e"),
        showlegend=show_ma, legend=dict(bgcolor="rgba(0,0,0,0)"),
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# ────────────────────────────────────────────────────────────────
# Gráfico Lucro vs Cotação (Pro)
# ────────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_lucro_cotacao(ticker: str) -> Optional[tuple]:
    fin = api.get_financials(ticker, statement_type="DRE")
    hist = api.get_stock_history(ticker, limit=1500)
    if not fin or not hist:
        return None

    stmts = fin.get("statements", [])
    lucro_by_year: dict = {}
    for acc in ("3.11.01", "3.11", "3.09"):
        for s in stmts:
            if s["account_code"] == acc and s["value"] is not None:
                yr = s["reference_date"][:4]
                if yr not in lucro_by_year:
                    lucro_by_year[yr] = s["value"] / 1e6  # R$ mi
        if lucro_by_year:
            break

    prices = hist.get("prices", [])
    if not prices:
        return None
    df_h = pd.DataFrame(prices)
    df_h["trade_date"] = pd.to_datetime(df_h["trade_date"])
    df_h = df_h.sort_values("trade_date")

    price_by_year: dict = {}
    now_year = datetime.now().year
    for yr in range(now_year - 6, now_year + 1):
        yr_data = df_h[df_h["trade_date"].dt.year == yr]
        if not yr_data.empty:
            price_by_year[str(yr)] = yr_data.iloc[-1]["adjusted_close"]

    common = sorted(set(lucro_by_year) & set(price_by_year))
    if len(common) < 2:
        return None
    years = common[-5:]
    return years, [lucro_by_year[y] for y in years], [price_by_year[y] for y in years]


def _show_lucro_cotacao_chart(ticker: str) -> None:
    data = _fetch_lucro_cotacao(ticker)
    if not data:
        return
    years, lucros, cotacoes = data

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=years, y=lucros, mode="lines+markers", name="Lucro Líquido (R$ mi)",
        line=dict(color="#42a5f5", width=2),
        marker=dict(size=7),
        hovertemplate="<b>%{x}</b><br>Lucro: R$ %{y:.0f}M<extra></extra>",
        yaxis="y1",
    ))
    fig.add_trace(go.Scatter(
        x=years, y=cotacoes, mode="lines+markers", name="Cotação (R$)",
        line=dict(color="#66bb6a", width=2),
        marker=dict(size=7),
        hovertemplate="<b>%{x}</b><br>Cotação: R$ %{y:.2f}<extra></extra>",
        yaxis="y2",
    ))
    fig.update_layout(
        title=dict(
            text="Lucro vs Cotação — convergência de longo prazo",
            font=dict(size=13, color="#e8eaf6"),
        ),
        height=280, margin=dict(l=0, r=60, t=40, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(showgrid=False, color="#9e9e9e", type="category"),
        yaxis=dict(title="Lucro (R$ mi)", color="#42a5f5",
                   showgrid=True, gridcolor="rgba(255,255,255,0.05)"),
        yaxis2=dict(title="Cotação (R$)", color="#66bb6a",
                    overlaying="y", side="right", showgrid=False),
        legend=dict(bgcolor="rgba(0,0,0,0)", orientation="h", y=-0.15),
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    st.caption(
        "Quando cotação cresce mais que lucro por anos seguidos, o valuation se torna mais exigente. "
        "Convergência indica fundamentos sólidos sustentando a valorização."
    )


# ────────────────────────────────────────────────────────────────
# Helpers de valuation (usados na tabela e no detalhe)
# ────────────────────────────────────────────────────────────────

def _is_cyclical(sector: str) -> bool:
    """True se o setor for cíclico/commodity (usar FCL normalizado no DCF)."""
    sl = (sector or "").lower()
    return any(kw in sl for kw in SETORES_CICLICOS)


def _is_utility(sector: str) -> bool:
    """True se for utility/setor regulado (energia, saneamento, transmissão, gás)."""
    sl = (sector or "").lower()
    return any(kw in sl for kw in UTILITY_KEYWORDS)


def _is_insurer(sector: str) -> bool:
    """True se for seguradora/corretora (valuation por P/L, não DCF de FCL)."""
    sl = (sector or "").lower()
    return any(kw in sl for kw in INSURER_KEYWORDS)


def _insurer_base_price(s: dict, fair_pe: float = INSURER_FAIR_PE) -> Optional[float]:
    """Preço justo para seguradoras — P/L de referência × LPA. Retorna R$/ação ou None.

    DCF de FCL não funciona para seguradoras (FCL distorcido pelo float de
    prêmios). O mercado as avalia por múltiplo de lucro / dividendos.
    """
    lpa = s.get("lpa")
    if lpa is None or lpa <= 0:
        return None
    return fair_pe * lpa


def _is_shopping(sector: str) -> bool:
    """True se for shopping/centro comercial (valuation por EV/EBITDA)."""
    sl = (sector or "").lower()
    return any(kw in sl for kw in SHOPPING_KEYWORDS)


def _ev_ebitda_price(s: dict, mult: float) -> Optional[float]:
    """Preço justo via EV/EBITDA: (múltiplo × EBITDA − dívida líq.) / ações.

    Genérico — usado por shoppings (e futuramente cíclicas/geral). Retorna
    R$/ação ou None se EBITDA ausente/negativo.
    """
    ebitda = s.get("ebitda")          # R$ mil
    shares = s.get("shares_outstanding")
    if ebitda is None or ebitda <= 0 or not shares or shares <= 0:
        return None
    net_debt = s.get("net_debt") or 0.0
    equity_k = mult * ebitda - net_debt
    return max(0.0, equity_k * 1000 / shares)


def _shopping_base_price(s: dict, mult: float = SHOPPING_FAIR_EV_EBITDA) -> Optional[float]:
    """Preço justo para shoppings — EV/EBITDA de referência."""
    return _ev_ebitda_price(s, mult)


# EV/EBITDA justo por sub-bucket do "Geral" (normas BR through-cycle, não
# ajustados a um analista). Ordem importa: o primeiro match vence.
GERAL_EV_EBITDA_BUCKETS = [
    (["farmácia", "farmacia", "drogaria", "saúde", "saude", "médic", "medic",
      "diagnóstic", "diagnostic", "hospital", "odonto"], 11.0, "Saúde / Farma"),
    (["bebida", "alimento", "fumo", "frigorífic", "frigorific", "proteína",
      "proteina"], 11.0, "Consumo (alimentos/bebidas)"),
    (["máquina", "maquina", "equipamento", "bens de capital", "industrial",
      "indústria - ", "industria - "], 12.0, "Indústria / Bens de capital"),
    (["locação", "locacao", "aluguel"], 7.0, "Locação / Serviços"),
    (["educação", "educacao", "ensino"], 6.0, "Educação"),
    (["construção", "construcao", "mat. constr", "incorporação",
      "incorporacao"], 5.0, "Construção civil"),
    (["têxtil", "textil", "vestuário", "vestuario", "calçad", "calcad",
      "esportiv"], 6.0, "Vestuário / Têxtil"),
    (["comércio", "comercio", "varejo", "atacado", "supermercado",
      "distribui"], 6.0, "Varejo / Distribuição"),
]
GERAL_EV_EBITDA_DEFAULT = 8.0


def _geral_bucket(sector: str) -> tuple[float, str]:
    """Retorna (múltiplo EV/EBITDA, rótulo do sub-bucket) para um setor 'Geral'."""
    sl = (sector or "").lower()
    for kws, mult, label in GERAL_EV_EBITDA_BUCKETS:
        if any(kw in sl for kw in kws):
            return mult, label
    return GERAL_EV_EBITDA_DEFAULT, "Geral (default)"


def _geral_base_price(s: dict) -> Optional[float]:
    """Preço justo para empresas 'gerais' — EV/EBITDA por sub-bucket setorial."""
    mult, _ = _geral_bucket(s.get("sector", ""))
    return _ev_ebitda_price(s, mult)


def _growth_context(s: dict, fair_mult: Optional[float]) -> Optional[str]:
    """Nota de contexto para nomes de crescimento (markdown) ou None.

    Dispara quando a ação negocia a múltiplo premium vs o setor OU tem CAGR alto
    — sinais de que o mercado precifica lucro futuro. O alvo (sobre o resultado
    atual) tende a subestimar esses nomes; a nota deixa isso explícito.
    """
    cagr = s.get("cagr_earnings_5y")
    cagr_label = "lucro"
    if cagr is None:
        cagr = s.get("cagr_revenue_5y")
        cagr_label = "receita"
    ev = s.get("ev_ebitda")
    premium = ev is not None and fair_mult and ev > 1.3 * fair_mult
    growth = cagr is not None and cagr >= 15
    if not (premium or growth):
        return None
    bits = []
    if premium and ev:
        bits.append(f"negocia a **{ev:.1f}×** EV/EBITDA vs ~{fair_mult:.0f}× de referência do setor")
    if growth:
        bits.append(f"cresceu **{cagr:.0f}%/ano** ({cagr_label}, 5 anos)")
    return (
        "📈 **Nome de crescimento** — " + "; ".join(bits) + ". O preço-alvo acima usa o "
        "**resultado atual** e tende a ser um **piso conservador**: o mercado e os analistas "
        "precificam o lucro **futuro**, que este modelo não projeta. Use o histórico de "
        "crescimento e a sustentabilidade para julgar — não conclua 'caro/barato' só pelo alvo."
    )


# EV/EBITDA through-cycle por sub-setor cíclico (aplicado sobre EBITDA mid-cycle).
# Múltiplos da pesquisa de mercado (Itaú BBA Vale ~4×, etc.).
CICLICA_EV_EBITDA_BUCKETS = [
    (["petróleo", "petroleo", "petro", "combustível", "combustivel"], 5.0, "Petróleo e Gás"),
    (["mineração", "mineracao", "minério", "minerio", "extração mineral",
      "extracao mineral"], 6.0, "Mineração"),
    (["metalurgia", "siderurgia"], 6.5, "Siderurgia / Metalurgia"),
    (["papel e celulose", "celulose", "papel"], 7.0, "Papel e Celulose"),
    (["açúcar", "acucar", "álcool", "alcool", "agricultura", "agropecuária",
      "agropecuaria", "sucroalcooleiro"], 5.0, "Agro / Açúcar e Álcool"),
]
CICLICA_EV_EBITDA_DEFAULT = 5.0


def _ciclica_bucket(sector: str) -> tuple[float, str]:
    """Retorna (EV/EBITDA through-cycle, rótulo) para um setor cíclico."""
    sl = (sector or "").lower()
    for kws, mult, label in CICLICA_EV_EBITDA_BUCKETS:
        if any(kw in sl for kw in kws):
            return mult, label
    return CICLICA_EV_EBITDA_DEFAULT, "Cíclica (default)"


def _ebitda_midcycle(s: dict) -> tuple[Optional[float], int, Optional[float], float]:
    """Retorna (EBITDA_midcycle, n_anos, EBIT_mid, ratio_EBITDA/EBIT).

    Cíclicas: usa a mediana do EBIT histórico (mid-cycle) e faz a ponte para
    EBITDA via a razão EBITDA/EBIT atual (D&A é relativamente estável).
    EBITDA_mid = None se houver menos de 5 anos de EBIT positivo.
    """
    hist: dict = s.get("ebit_historico") or {}
    anos = sorted(hist.keys(), reverse=True)[:10]
    pos = [hist[a] for a in anos if hist.get(a) is not None and hist[a] > 0]
    if len(pos) < 5:
        return None, len(pos), None, 1.0

    vs = sorted(pos)
    n = len(vs)
    mid = n // 2
    ebit_mid = (vs[mid - 1] + vs[mid]) / 2 if n % 2 == 0 else vs[mid]

    # Razão EBITDA/EBIT atual para reconstruir o EBITDA normalizado
    ebitda_cur = s.get("ebitda")
    ebit_cur = None
    if s.get("ebit_margin") is not None and s.get("net_revenue"):
        ebit_cur = s["ebit_margin"] / 100 * s["net_revenue"]
    if ebitda_cur and ebit_cur and ebit_cur > 0:
        ratio = min(max(ebitda_cur / ebit_cur, 1.05), 2.5)
    else:
        ratio = 1.4  # add-back de D&A padrão quando não dá para calcular
    return ebit_mid * ratio, n, ebit_mid, ratio


def _cyclical_ebitda_base(s: dict) -> Optional[float]:
    """EBITDA base para cíclicas = max(EBITDA atual, EBITDA mid-cycle).

    Nunca normaliza para baixo (o múltiplo through-cycle já é o desconto de
    ciclicidade — normalizar o EBITDA também seria dupla-contagem), mas usa a
    mediana histórica quando ela for MAIOR (protege em vales do ciclo).
    """
    ebitda_cur = s.get("ebitda")
    ebitda_mid, _n, _e, _r = _ebitda_midcycle(s)
    candidatos = [v for v in (ebitda_cur, ebitda_mid) if v is not None and v > 0]
    return max(candidatos) if candidatos else None


def _cyclical_base_price(s: dict) -> Optional[float]:
    """Preço justo para cíclicas — EV/EBITDA through-cycle sobre o EBITDA base."""
    ebitda_base = _cyclical_ebitda_base(s)
    if ebitda_base is None or ebitda_base <= 0:
        return None
    shares = s.get("shares_outstanding")
    if not shares or shares <= 0:
        return None
    mult, _ = _ciclica_bucket(s.get("sector", ""))
    net_debt = s.get("net_debt") or 0.0
    return max(0.0, (mult * ebitda_base - net_debt) * 1000 / shares)


def _dcf_params(sector: str) -> tuple[float, float]:
    """Retorna (wacc, perp_g) ajustados ao setor.
    Utilities reguladas: WACC 10% (Selic+2%, menor beta) e g perpétuo 4%
    (indexação tarifária de longo prazo). Demais: 12% e 3% (padrão)."""
    if _is_utility(sector):
        return 0.10, 0.04
    return 0.12, 0.03


def _fcl_normalizado(s: dict) -> tuple[Optional[float], Optional[float], int]:
    """
    Retorna (fcl_base_norm, fcl_ultimo, n_anos):
    - fcl_base_norm: média dos últimos 3-5 anos (None se < 3 anos positivos)
    - fcl_ultimo:    FCL do período mais recente
    - n_anos:        quantos anos foram usados na média (0 se não normalizou)
    Se o setor não for cíclico, fcl_base_norm == fcl_ultimo.
    """
    fcl_ultimo = s.get("fcl")
    sector = s.get("sector", "")
    if not _is_cyclical(sector):
        return fcl_ultimo, fcl_ultimo, 0

    hist: dict = s.get("fcl_historico") or {}
    if not hist:
        return fcl_ultimo, fcl_ultimo, 0

    # Filtra positivos de TODOS os anos e pega os 10 mais recentes positivos.
    # ([:10] nos anos desperdiçaria slots em anos negativos, ignorando positivos mais antigos)
    todos_pos = [(a, hist[a]) for a in sorted(hist.keys(), reverse=True)
                 if hist[a] is not None and hist[a] > 0]
    valores_pos = [v for _, v in todos_pos[:10]]

    if len(valores_pos) < 5:
        return None, fcl_ultimo, len(valores_pos)  # insuficiente

    valores_sorted = sorted(valores_pos)
    n = len(valores_sorted)
    mid = n // 2
    fcl_mediana = (valores_sorted[mid - 1] + valores_sorted[mid]) / 2 if n % 2 == 0 else valores_sorted[mid]
    return fcl_mediana, fcl_ultimo, n


def _dcf_conservative_price(s: dict, wacc: float = 0.12, g5: float = 0.10, perp_g: float = 0.03) -> Optional[float]:
    """Preço justo DCF — cenário Conservador (g5 × 0.7). Usa FCL normalizado para setores cíclicos."""
    fcl_base, _, _ = _fcl_normalizado(s)
    shares = s.get("shares_outstanding")
    if not fcl_base or fcl_base <= 0 or not shares or shares <= 0:
        return None
    net_debt = s.get("net_debt") or 0.0
    g_cons = g5 * 0.7
    if wacc <= perp_g:
        return None
    pv, fcl_y = 0.0, fcl_base
    for yr in range(1, 6):
        fcl_y *= (1 + g_cons)
        pv += fcl_y / (1 + wacc) ** yr
    tv = fcl_base * (1 + g_cons) ** 5 * (1 + perp_g) / (wacc - perp_g)
    pv += tv / (1 + wacc) ** 5
    equity_k = pv - net_debt
    return max(0.0, equity_k * 1000 / shares)


# Bancos com participação relevante do governo → prêmio de governança no Ke
_BANCOS_ESTATAIS = {"BBAS3", "BBAS11", "BAZA3", "BRSR3", "BRSR6", "BNBR3"}

# Prêmios de risco de equity sobre a Rf estrutural (CAPM simplificado, β≈1).
# Privado: ERP sobre a NTN-B longa (~4pp). Estatal: + governança/risco político.
_KE_PREMIO_PRIVADO = 0.040
_KE_PREMIO_ESTATAL = 0.065
_KE_MIN, _KE_MAX   = 0.12, 0.20   # faixa sã para clamp do Ke nominal


@st.cache_data(ttl=86400, show_spinner=False)
def _rf_estrutural() -> float:
    """Risk-free de perpetuidade = Selic estrutural (mediana Focus do horizonte
    mais distante, ~10%), NÃO a Selic spot (cíclica). Fração; fallback 0.10.

    Para um modelo de perpetuidade (Gordon), a taxa livre de risco deve refletir
    o juro normalizado de longo prazo — é assim que as casas ancoram o Ke."""
    try:
        focus = api.get_focus("Selic", top=80)
        if focus:
            v = focus[max(focus.keys())]   # ano de referência mais distante
            if v is not None and 6.0 <= v <= 20.0:
                return v / 100
    except Exception:
        pass
    return 0.10


def _bank_ke(ticker: str) -> float:
    """Ke dinâmico (CAPM) = Rf estrutural (Selic de longo prazo do Focus, ~10%)
    + prêmio de risco de equity. Privado +4pp; estatal +6,5pp (governança).
    Clamp 12–20%. Ancorado na Selic NORMALIZADA, não na spot (perpetuidade)."""
    rf = _rf_estrutural()
    premio = _KE_PREMIO_ESTATAL if (ticker or "").upper() in _BANCOS_ESTATAIS else _KE_PREMIO_PRIVADO
    return min(max(rf + premio, _KE_MIN), _KE_MAX)


@st.cache_data(ttl=86400, show_spinner=False)
def _g_perpetuidade() -> float:
    """Crescimento de perpetuidade NOMINAL = PIB real + IPCA de longo prazo
    (medianas Focus do horizonte mais distante). Convenção das casas brasileiras
    (g = PIB nominal de longo prazo) e consistente com o Ke nominal — descontar
    fluxo nominal com g real subavalia. Clamp 3–7%; fallback 0.055."""
    try:
        ipca = api.get_focus("IPCA", top=80)
        pib  = api.get_focus("PIB Total", top=80)
        if ipca and pib:
            gi = ipca[max(ipca.keys())]
            gp = pib[max(pib.keys())]
            if gi is not None and gp is not None:
                return min(max((gi + gp) / 100, 0.03), 0.07)
    except Exception:
        pass
    return 0.055


def _bank_roe_norm(s: dict) -> Optional[float]:
    """ROE normalizado = max(ROE atual, mediana dos últimos 8 trimestres).

    Suaviza um trimestre atípico (ex.: BBAS3 caiu a 6,6% na crise do agro, com
    mediana ~12%) sem rebaixar bancos saudáveis cujo ROE atual já é alto (o max
    preserva o ROE corrente quando ele está acima da mediana — ex.: ITUB4).
    """
    roe = s.get("roe")
    hist = [r for r in (s.get("roe_historico") or []) if r is not None]
    if len(hist) >= 4:
        import statistics
        med = statistics.median(hist[:8])
        return max(roe, med) if roe is not None else med
    return roe


def _gordon_conservative_price(s: dict, g: float = 0.04) -> Optional[float]:
    """Preço alvo para bancos — Gordon Growth cenário Conservador (g×0.7, Ke×1.08).
    Usa ROE normalizado e Ke por tipo de banco (estatal vs privado)."""
    roe = _bank_roe_norm(s)
    vpa = s.get("vpa")
    if roe is None or vpa is None or vpa <= 0:
        return None
    ke = _bank_ke(s.get("ticker", ""))
    roe_f = roe / 100
    g_cons  = g  * 0.7
    ke_cons = ke * 1.08  # conservador: +8% sobre Ke base
    if ke_cons <= g_cons:
        return None
    pvp_j = (roe_f - g_cons) / (ke_cons - g_cons)
    if pvp_j <= 0:
        return None
    return pvp_j * vpa


def _dcf_base_price(s: dict, wacc: Optional[float] = None, g5: float = 0.10,
                    perp_g: Optional[float] = None) -> Optional[float]:
    """Preço justo DCF — cenário Base/Esperado (g5 sem ajuste). Usa FCL normalizado p/ cíclicos.
    WACC e perp_g são ajustados por setor (utilities reguladas: 10%/4%)."""
    _w_sec, _pg_sec = _dcf_params(s.get("sector", ""))
    if wacc is None:
        wacc = _w_sec
    if perp_g is None:
        perp_g = _pg_sec
    fcl_base, _fcl_ult, _ = _fcl_normalizado(s)
    shares = s.get("shares_outstanding")
    if not fcl_base or fcl_base <= 0 or not shares or shares <= 0:
        return None
    net_debt = s.get("net_debt") or 0.0
    if wacc <= perp_g:
        return None
    pv, fcl_y = 0.0, fcl_base
    for yr in range(1, 6):
        fcl_y *= (1 + g5)
        pv += fcl_y / (1 + wacc) ** yr
    tv = fcl_base * (1 + g5) ** 5 * (1 + perp_g) / (wacc - perp_g)
    pv += tv / (1 + wacc) ** 5
    equity_k = pv - net_debt
    return max(0.0, equity_k * 1000 / shares)


def _gordon_base_price(s: dict, g: Optional[float] = None) -> Optional[float]:
    """Preço alvo bancos — Gordon Growth Base/Esperado. ROE normalizado + Ke
    dinâmico + g de perpetuidade nominal (PIB+IPCA de longo prazo do Focus)."""
    if g is None:
        g = _g_perpetuidade()
    roe = _bank_roe_norm(s)
    vpa = s.get("vpa")
    if roe is None or vpa is None or vpa <= 0:
        return None
    ke = _bank_ke(s.get("ticker", ""))
    roe_f = roe / 100
    if ke <= g:
        return None
    pvp_j = (roe_f - g) / (ke - g)
    if pvp_j <= 0:
        return None
    return pvp_j * vpa


# ────────────────────────────────────────────────────────────────
# Valuation — Gordon Growth (bancos)
# ────────────────────────────────────────────────────────────────

def _show_gordon_growth(s: dict) -> None:
    """Valuation para bancos via Gordon Growth (P/VP justificado pelo ROE)."""
    roe_spot = s.get("roe")
    roe   = _bank_roe_norm(s)   # normalizado (max do atual com a mediana de 8 trimestres)
    vpa   = s.get("vpa")
    price = s.get("close_price")
    ticker = s.get("ticker", "")

    st.divider()
    st.subheader("📐 Valuation — Gordon Growth (P/VP Justificado)")
    st.info(
        "ℹ️ Para bancos, o valuation usa o **modelo de Gordon Growth sobre o Patrimônio** "
        "(P/VP justificado pelo ROE), método padrão para o setor — diferente do DCF "
        "tradicional usado para as demais ações, pois o fluxo de caixa de um banco "
        "não é diretamente comparável ao de empresas não-financeiras."
    )
    if ticker in _BANCOS_ESTATAIS:
        st.warning(
            "⚠️ **Empresa com participação relevante do governo** — risco de governança e "
            "interferência política pode justificar desconto persistente que o modelo de "
            "Gordon Growth não captura. Resultado deve ser interpretado com cautela adicional."
        )

    if roe is None or vpa is None or vpa <= 0:
        st.warning("⚠️ ROE ou VPA não disponível — Gordon Growth não pode ser calculado.")
        return

    # ROE normalizado (suaviza trimestre atípico). Mostra o spot quando difere.
    if roe_spot is not None and abs(roe - roe_spot) > 0.2:
        st.caption(
            f"ROE usado: **{roe:.1f}%** (normalizado — mediana de até 8 trimestres; "
            f"ROE do último período: {roe_spot:.1f}%) · VPA: **R\\$ {vpa:.2f}**")
    else:
        st.caption(f"ROE base: **{roe:.1f}%** · VPA: **R\\$ {vpa:.2f}**")

    _rf = _rf_estrutural() * 100
    _ke_default = _bank_ke(ticker) * 100
    _premio_pp = (_KE_PREMIO_ESTATAL if ticker.upper() in _BANCOS_ESTATAIS
                  else _KE_PREMIO_PRIVADO) * 100
    _g_default = _g_perpetuidade() * 100
    st.caption(
        f"Ke ancorado na **Selic estrutural** (Focus longo prazo ≈ {_rf:.1f}%) "
        f"+ prêmio de equity de {_premio_pp:.1f}pp "
        f"({'estatal' if ticker.upper() in _BANCOS_ESTATAIS else 'privado'}) "
        f"= **{_ke_default:.1f}%**. · g de perpetuidade = **PIB + IPCA** de longo "
        f"prazo (Focus) ≈ **{_g_default:.1f}%** (nominal, coerente com o Ke). "
        f"Nenhum dos dois usa o juro spot — o modelo é de perpetuidade."
    )
    col_ke, col_g = st.columns(2)
    with col_ke:
        ke = st.slider(
            "Ke — Custo do Capital Próprio (%)",
            min_value=8.0, max_value=25.0, value=_ke_default, step=0.5,
            key=f"gg_ke_{ticker}",
            help="Padrão = Selic estrutural (Focus, ~10%) + prêmio de equity "
                 "(+4pp privado, +6,5pp estatal). Ajuste livre para testar cenários.",
        ) / 100
    with col_g:
        g = st.slider(
            "Crescimento na perpetuidade (%)",
            min_value=0.0, max_value=8.0, value=_g_default, step=0.25,
            key=f"gg_g_{ticker}",
            help="Padrão = PIB real + IPCA de longo prazo (Focus) = PIB nominal. "
                 "Teto teórico do crescimento perpétuo de um banco maduro.",
        ) / 100

    if ke <= g:
        st.error("Ke deve ser maior que o crescimento (g).")
        return

    roe_f = roe / 100

    # P/VP justificado de Gordon com guarda-corpos: piso no spread (Ke−g) e teto
    # de P/VP evitam a explosão do modelo quando Ke≈g (denominador → 0).
    _GG_FLOOR_SPREAD = 0.03   # spread mínimo Ke−g
    _GG_PVP_CAP      = 4.0     # nenhum banco BR justifica P/VP > 4x via Gordon

    def _gg_price(roe_s: float, g_s: float, ke_s: float) -> Optional[float]:
        den   = max(ke_s - g_s, _GG_FLOOR_SPREAD)
        pvp_j = min(max((roe_s - g_s) / den, 0.0), _GG_PVP_CAP)
        return pvp_j * vpa

    # Ke FIXO entre cenários: a taxa de desconto não oscila ±30% de um cenário p/
    # outro — mover Ke e g juntos colapsava o denominador e inflava o Otimista
    # (gerava P/VP de 6x+). Varia o que de fato é incerto num banco: o ROE
    # sustentável (assimétrico, pois ROE alto reverte à média p/ baixo) e o
    # crescimento de longo prazo (±1pp absoluto).
    scenarios = [
        ("Conservador", roe_f * 0.80, max(g - 0.01, 0.0), ke, "#f44336"),
        ("Base",        roe_f,        g,                   ke, "#4caf50"),
        ("Otimista",    roe_f * 1.05, g + 0.01,            ke, "#2196f3"),
    ]
    prices_gg = {name: _gg_price(rs, gs, ks) for name, rs, gs, ks, _ in scenarios}

    def _upside(p: Optional[float]) -> Optional[str]:
        # Sem parênteses para o st.metric detectar o sinal e colorir
        # automaticamente (verde = alta, vermelho = queda)
        if p is not None and price and price > 0:
            return f"{(p / price - 1) * 100:+.1f}%"
        return None

    c_r, c_b, c_o = st.columns(3)
    p_c, p_b, p_o = prices_gg["Conservador"], prices_gg["Base"], prices_gg["Otimista"]
    c_r.metric("Conservador (ROE−20%, g−1pp)", f"R$ {p_c:.2f}" if p_c is not None else "N/D", _upside(p_c))
    c_b.metric("Base",                          f"R$ {p_b:.2f}" if p_b is not None else "N/D", _upside(p_b))
    c_o.metric("Otimista (ROE+5%, g+1pp)",     f"R$ {p_o:.2f}" if p_o is not None else "N/D", _upside(p_o))

    fig = go.Figure()
    names  = [n for n, *_ in scenarios]
    vals   = [prices_gg[n] or 0 for n in names]
    colors = [c for *_, c in scenarios]
    fig.add_trace(go.Bar(
        x=names, y=vals,
        marker_color=colors,
        text=[f"R$ {v:.2f}" for v in vals],
        textposition="outside",
        hovertemplate="%{x}: R$ %{y:.2f}<extra></extra>",
    ))
    if price:
        fig.add_hline(
            y=price, line_dash="dash", line_color="#ffeb3b", line_width=2,
            annotation_text=f"Preço atual: R$ {price:.2f}",
            annotation_font_color="#ffeb3b",
        )
    fig.update_layout(
        height=300, margin=dict(l=0, r=0, t=30, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(showgrid=False, color="#9e9e9e"),
        yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.06)", color="#9e9e9e", tickprefix="R$ "),
        showlegend=False,
        title=dict(text="Faixa de Preço Justo — Gordon Growth (3 cenários)", font=dict(size=12, color="#e8eaf6")),
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    st.warning(
        "⚠️ **Aviso:** modelo educacional de aproximação — não constitui recomendação de investimento. "
        "Resultados são muito sensíveis às premissas de ROE, Ke e crescimento."
    )


# ────────────────────────────────────────────────────────────────
# Valuation DCF
# ────────────────────────────────────────────────────────────────

def _show_insurer_valuation(s: dict) -> None:
    """Valuation para seguradoras via múltiplo P/L × LPA (3 cenários de P/L)."""
    lpa   = s.get("lpa")
    price = s.get("close_price")
    pl_atual = s.get("pl")
    ticker = s.get("ticker", "")

    st.divider()
    st.subheader("📐 Valuation — Múltiplo de Lucro (P/L)")
    st.info(
        "ℹ️ Para seguradoras, o valuation usa **múltiplo de lucro (P/L × LPA)** — "
        "método padrão do setor. O DCF de fluxo de caixa não se aplica porque o "
        "caixa de uma seguradora é distorcido pelo *float* de prêmios."
    )

    if lpa is None or lpa <= 0:
        st.warning("⚠️ LPA não disponível ou negativo — múltiplo P/L não aplicável.")
        return

    st.caption(
        f"LPA: **R\\$ {lpa:.2f}**"
        + (f" · P/L atual: **{pl_atual:.1f}×**" if pl_atual else "")
    )

    pe_base = st.slider(
        "P/L justo de referência (×)",
        min_value=5.0, max_value=18.0, value=float(INSURER_FAIR_PE), step=0.5,
        key=f"ins_pe_{ticker}",
        help="P/L através do ciclo. Padrão 10× para seguradoras brasileiras estáveis.",
    )

    cenarios = [
        ("Conservador", pe_base * 0.85, "#f44336"),
        ("Base",        pe_base,        "#4caf50"),
        ("Otimista",    pe_base * 1.15, "#2196f3"),
    ]

    def _upside(p: Optional[float]) -> Optional[str]:
        if p is not None and price and price > 0:
            return f"{(p / price - 1) * 100:+.1f}%"
        return None

    c_r, c_b, c_o = st.columns(3)
    p_c = cenarios[0][1] * lpa
    p_b = cenarios[1][1] * lpa
    p_o = cenarios[2][1] * lpa
    c_r.metric(f"Conservador ({cenarios[0][1]:.1f}×)", f"R$ {p_c:.2f}", _upside(p_c))
    c_b.metric(f"Base ({cenarios[1][1]:.1f}×)",        f"R$ {p_b:.2f}", _upside(p_b))
    c_o.metric(f"Otimista ({cenarios[2][1]:.1f}×)",    f"R$ {p_o:.2f}", _upside(p_o))

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=["Conservador", "Base", "Otimista"], y=[p_c, p_b, p_o],
        marker_color=["#f44336", "#4caf50", "#2196f3"],
        text=[f"R$ {v:.2f}" for v in (p_c, p_b, p_o)],
        textposition="outside",
        hovertemplate="%{x}: R$ %{y:.2f}<extra></extra>",
    ))
    if price:
        fig.add_hline(
            y=price, line_dash="dash", line_color="#ffeb3b", line_width=2,
            annotation_text=f"Preço atual: R$ {price:.2f}",
            annotation_font_color="#ffeb3b",
        )
    fig.update_layout(
        height=300, margin=dict(l=0, r=0, t=30, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(showgrid=False, color="#9e9e9e"),
        yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.06)", color="#9e9e9e",
                   tickprefix="R$ "),
        showlegend=False,
        title=dict(text="Faixa de Preço Justo — P/L (3 cenários)", font=dict(size=12, color="#e8eaf6")),
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    st.warning(
        "⚠️ **Aviso:** Múltiplo de referência simplificado. Seguradoras com perfil "
        "de crescimento diferenciado (ex.: forte expansão ou franquia em maturação) "
        "podem justificar P/L acima ou abaixo do padrão. Não é recomendação de investimento."
    )


def _show_shopping_valuation(s: dict) -> None:
    """Valuation para shoppings via EV/EBITDA (3 cenários de múltiplo)."""
    ebitda   = s.get("ebitda")          # R$ mil
    net_debt = s.get("net_debt") or 0.0
    shares   = s.get("shares_outstanding")
    price    = s.get("close_price")
    ev_atual = s.get("ev_ebitda")
    ticker   = s.get("ticker", "")

    st.divider()
    st.subheader("📐 Valuation — Múltiplo EV/EBITDA")
    st.info(
        "ℹ️ Para shoppings, o valuation usa **EV/EBITDA** — método padrão do setor. "
        "O DCF de fluxo de caixa não se aplica bem porque o caixa é distorcido por "
        "compra e venda de empreendimentos."
    )

    if ebitda is None or ebitda <= 0 or not shares or shares <= 0:
        st.warning("⚠️ EBITDA ou nº de ações indisponível — EV/EBITDA não aplicável.")
        return

    st.caption(
        f"EBITDA: **R\\$ {ebitda/1000:.0f} mi** · Dívida líq.: **R\\$ {net_debt/1000:.0f} mi**"
        + (f" · EV/EBITDA atual: **{ev_atual:.1f}×**" if ev_atual else "")
    )
    _gc = _growth_context(s, SHOPPING_FAIR_EV_EBITDA)
    if _gc:
        st.info(_gc)

    mult_base = st.slider(
        "EV/EBITDA justo de referência (×)",
        min_value=4.0, max_value=18.0, value=float(SHOPPING_FAIR_EV_EBITDA), step=0.5,
        key=f"shop_mult_{ticker}",
        help="EV/EBITDA através do ciclo. Padrão 10,5× para shoppings brasileiros.",
    )

    def _upside(p: Optional[float]) -> Optional[str]:
        if p is not None and price and price > 0:
            return f"{(p / price - 1) * 100:+.1f}%"
        return None

    p_c = _ev_ebitda_price(s, mult_base * 0.85)
    p_b = _ev_ebitda_price(s, mult_base)
    p_o = _ev_ebitda_price(s, mult_base * 1.15)

    c_r, c_b, c_o = st.columns(3)
    c_r.metric(f"Conservador ({mult_base*0.85:.1f}×)", f"R$ {p_c:.2f}", _upside(p_c))
    c_b.metric(f"Base ({mult_base:.1f}×)",             f"R$ {p_b:.2f}", _upside(p_b))
    c_o.metric(f"Otimista ({mult_base*1.15:.1f}×)",    f"R$ {p_o:.2f}", _upside(p_o))

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=["Conservador", "Base", "Otimista"], y=[p_c, p_b, p_o],
        marker_color=["#f44336", "#4caf50", "#2196f3"],
        text=[f"R$ {v:.2f}" for v in (p_c, p_b, p_o)],
        textposition="outside",
        hovertemplate="%{x}: R$ %{y:.2f}<extra></extra>",
    ))
    if price:
        fig.add_hline(
            y=price, line_dash="dash", line_color="#ffeb3b", line_width=2,
            annotation_text=f"Preço atual: R$ {price:.2f}",
            annotation_font_color="#ffeb3b",
        )
    fig.update_layout(
        height=300, margin=dict(l=0, r=0, t=30, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(showgrid=False, color="#9e9e9e"),
        yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.06)", color="#9e9e9e",
                   tickprefix="R$ "),
        showlegend=False,
        title=dict(text="Faixa de Preço Justo — EV/EBITDA (3 cenários)", font=dict(size=12, color="#e8eaf6")),
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    st.warning(
        "⚠️ **Aviso:** Múltiplo de referência simplificado. Shoppings premium "
        "(maior margem/localização) podem negociar acima do padrão. "
        "Não é recomendação de investimento."
    )


def _show_geral_valuation(s: dict) -> None:
    """Valuation 'geral' via EV/EBITDA por sub-bucket setorial (referência conservadora)."""
    sector   = s.get("sector", "")
    ebitda   = s.get("ebitda")          # R$ mil
    net_debt = s.get("net_debt") or 0.0
    shares   = s.get("shares_outstanding")
    price    = s.get("close_price")
    ev_atual = s.get("ev_ebitda")
    ticker   = s.get("ticker", "")
    mult_setor, bucket_label = _geral_bucket(sector)

    st.divider()
    st.subheader("📐 Valuation — Múltiplo EV/EBITDA (referência setorial)")
    st.info(
        f"ℹ️ Sub-setor identificado: **{bucket_label}** → EV/EBITDA de referência "
        f"**{mult_setor:.0f}×**. Valuation por múltiplo sobre o EBITDA atual."
    )
    st.warning(
        "🟠 **Referência de baixa precisão.** O múltiplo médio do setor é aplicado sobre o "
        "EBITDA *atual*, então: pode **subestimar** empresas em forte crescimento (cujo lucro "
        "futuro o mercado já antecipa) e **superestimar** empresas que negociam abaixo da média "
        "do setor por algum motivo estrutural. Trate como ponto de partida, não como preço-alvo."
    )

    if ebitda is None or ebitda <= 0 or not shares or shares <= 0:
        st.info("⚠️ EBITDA ou nº de ações indisponível — múltiplo não aplicável para este ticker.")
        return

    st.caption(
        f"EBITDA: **R\\$ {ebitda/1000:.0f} mi** · Dívida líq.: **R\\$ {net_debt/1000:.0f} mi**"
        + (f" · EV/EBITDA atual: **{ev_atual:.1f}×**" if ev_atual else "")
    )
    _gc = _growth_context(s, mult_setor)
    if _gc:
        st.info(_gc)

    mult_base = st.slider(
        "EV/EBITDA justo de referência (×)",
        min_value=3.0, max_value=22.0, value=float(mult_setor), step=0.5,
        key=f"geral_mult_{ticker}",
        help=f"Padrão do sub-setor '{bucket_label}': {mult_setor:.0f}×. Ajuste se conhecer o caso.",
    )

    def _upside(p: Optional[float]) -> Optional[str]:
        if p is not None and price and price > 0:
            return f"{(p / price - 1) * 100:+.1f}%"
        return None

    p_c = _ev_ebitda_price(s, mult_base * 0.85)
    p_b = _ev_ebitda_price(s, mult_base)
    p_o = _ev_ebitda_price(s, mult_base * 1.15)

    c_r, c_b, c_o = st.columns(3)
    c_r.metric(f"Conservador ({mult_base*0.85:.1f}×)", f"R$ {p_c:.2f}", _upside(p_c))
    c_b.metric(f"Base ({mult_base:.1f}×)",             f"R$ {p_b:.2f}", _upside(p_b))
    c_o.metric(f"Otimista ({mult_base*1.15:.1f}×)",    f"R$ {p_o:.2f}", _upside(p_o))

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=["Conservador", "Base", "Otimista"], y=[p_c, p_b, p_o],
        marker_color=["#f44336", "#4caf50", "#2196f3"],
        text=[f"R$ {v:.2f}" for v in (p_c, p_b, p_o)],
        textposition="outside",
        hovertemplate="%{x}: R$ %{y:.2f}<extra></extra>",
    ))
    if price:
        fig.add_hline(
            y=price, line_dash="dash", line_color="#ffeb3b", line_width=2,
            annotation_text=f"Preço atual: R$ {price:.2f}",
            annotation_font_color="#ffeb3b",
        )
    fig.update_layout(
        height=300, margin=dict(l=0, r=0, t=30, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(showgrid=False, color="#9e9e9e"),
        yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.06)", color="#9e9e9e",
                   tickprefix="R$ "),
        showlegend=False,
        title=dict(text="Faixa de Preço Justo — EV/EBITDA (3 cenários)", font=dict(size=12, color="#e8eaf6")),
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    st.warning(
        "⚠️ Ferramenta educacional de aproximação — **não é recomendação de investimento**."
    )


def _show_cyclical_valuation(s: dict) -> None:
    """Valuation para cíclicas — EV/EBITDA through-cycle sobre EBITDA mid-cycle."""
    sector   = s.get("sector", "")
    net_debt = s.get("net_debt") or 0.0
    shares   = s.get("shares_outstanding")
    price    = s.get("close_price")
    ebitda_cur = s.get("ebitda")
    ticker   = s.get("ticker", "")
    mult_setor, bucket_label = _ciclica_bucket(sector)
    ebitda_mid, n_anos, ebit_mid, ratio = _ebitda_midcycle(s)

    # Base = max(EBITDA atual, mid-cycle): o múltiplo baixo já desconta o ciclo,
    # então não se normaliza para baixo; a mediana só entra se for MAIOR (vale).
    ebitda_base = _cyclical_ebitda_base(s)

    st.divider()
    st.subheader("📐 Valuation — EV/EBITDA through-cycle (cíclica)")
    st.info(
        f"ℹ️ Sub-setor cíclico: **{bucket_label}** → EV/EBITDA through-cycle "
        f"**{mult_setor:.1f}×**. O múltiplo baixo já é o desconto de ciclicidade; "
        "a base é o **maior** entre EBITDA atual e o médio do ciclo (protege em vales "
        "sem punir picos moderados)."
    )

    if not shares or shares <= 0:
        st.warning("⚠️ Nº de ações indisponível — valuation não aplicável.")
        return
    if ebitda_base is None or ebitda_base <= 0:
        st.warning("⚠️ EBITDA indisponível ou negativo — valuation não aplicável.")
        return

    st.warning(
        "🟠 **Referência through-cycle.** Pode divergir de analistas que apostam numa "
        "alta/queda **específica** do preço da commodity (deck de preços que não "
        "modelamos). Empresas muito alavancadas ou em forte crescimento (EBITDA forward "
        "≫ atual) tendem a ler conservador aqui. Valor justo de longo prazo, não alvo de 12m."
    )

    # Comparativo EBITDA atual vs mid-cycle vs base usada
    if ebitda_mid is not None and ebitda_cur:
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("EBITDA atual", f"R$ {ebitda_cur/1000:.0f} mi")
        col_b.metric(f"EBITDA mid-cycle ({n_anos}a)", f"R$ {ebitda_mid/1000:.0f} mi")
        col_c.metric("Base usada (maior)", f"R$ {ebitda_base/1000:.0f} mi")
    else:
        st.caption(
            f"EBITDA base: **R\\$ {ebitda_base/1000:.0f} mi** · "
            f"Dívida líq.: **R\\$ {net_debt/1000:.0f} mi**"
            + ("" if ebitda_mid is not None else "  ·  ⚠️ sem histórico de EBIT (usando atual)")
        )

    def _price_at(mult: float) -> float:
        return max(0.0, (mult * ebitda_base - net_debt) * 1000 / shares)

    def _upside(p: Optional[float]) -> Optional[str]:
        if p is not None and price and price > 0:
            return f"{(p / price - 1) * 100:+.1f}%"
        return None

    _gc = _growth_context(s, mult_setor)
    if _gc:
        st.info(_gc)

    mult_base = st.slider(
        "EV/EBITDA through-cycle (×)",
        min_value=2.0, max_value=12.0, value=float(mult_setor), step=0.5,
        key=f"ciclo_mult_{ticker}",
        help=f"Padrão do sub-setor '{bucket_label}': {mult_setor:.1f}×.",
    )

    p_c = _price_at(mult_base * 0.85)
    p_b = _price_at(mult_base)
    p_o = _price_at(mult_base * 1.15)

    c_r, c_b, c_o = st.columns(3)
    c_r.metric(f"Conservador ({mult_base*0.85:.1f}×)", f"R$ {p_c:.2f}", _upside(p_c))
    c_b.metric(f"Base ({mult_base:.1f}×)",             f"R$ {p_b:.2f}", _upside(p_b))
    c_o.metric(f"Otimista ({mult_base*1.15:.1f}×)",    f"R$ {p_o:.2f}", _upside(p_o))

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=["Conservador", "Base", "Otimista"], y=[p_c, p_b, p_o],
        marker_color=["#f44336", "#4caf50", "#2196f3"],
        text=[f"R$ {v:.2f}" for v in (p_c, p_b, p_o)],
        textposition="outside",
        hovertemplate="%{x}: R$ %{y:.2f}<extra></extra>",
    ))
    if price:
        fig.add_hline(
            y=price, line_dash="dash", line_color="#ffeb3b", line_width=2,
            annotation_text=f"Preço atual: R$ {price:.2f}",
            annotation_font_color="#ffeb3b",
        )
    fig.update_layout(
        height=300, margin=dict(l=0, r=0, t=30, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(showgrid=False, color="#9e9e9e"),
        yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.06)", color="#9e9e9e",
                   tickprefix="R$ "),
        showlegend=False,
        title=dict(text="Faixa de Preço Justo — EV/EBITDA mid-cycle", font=dict(size=12, color="#e8eaf6")),
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    st.warning(
        "⚠️ Ferramenta educacional de aproximação — **não é recomendação de investimento**."
    )


def _show_dcf(s: dict) -> None:
    """Seção de Valuation por Fluxo de Caixa Descontado (DCF)."""
    sector = s.get("sector", "")
    if sc.is_bank(sector):
        _show_gordon_growth(s)
        return
    if _is_insurer(sector):
        _show_insurer_valuation(s)
        return
    if _is_shopping(sector):
        _show_shopping_valuation(s)
        return
    if _is_cyclical(sector):
        _show_cyclical_valuation(s)
        return
    # DCF segue apenas para utilities; demais usam EV/EBITDA setorial
    if not _is_utility(sector):
        _show_geral_valuation(s)
        return

    fcl_k = s.get("fcl")  # FCL mais recente em R$ mil
    net_debt = s.get("net_debt")
    shares = s.get("shares_outstanding")
    price = s.get("close_price")
    ciclico = _is_cyclical(sector)
    utility = _is_utility(sector)
    # Parâmetros padrão de WACC/perp_g ajustados ao setor (utilities: 10%/4%)
    _wacc_default, _perp_default = _dcf_params(sector)

    st.divider()
    st.subheader("📐 Valuation por DCF (Fluxo de Caixa Descontado)")

    if utility:
        st.info(
            "🏛️ **Setor regulado — WACC reduzido (10%)** refletindo menor risco de "
            "fluxo de caixa tarifário. Concessões de energia/saneamento têm receita "
            "regulada e indexada à inflação, justificando prêmio de risco menor que "
            "o de empresas não-reguladas."
        )

    if fcl_k is None or shares is None or shares <= 0:
        st.info(
            "⚠️ FCL (Fluxo de Caixa Livre) ou número de ações não disponível para este ticker. "
            "O modelo DCF requer dados de DFC disponíveis na API Bolsai."
        )
        return

    # Determina a base de FCL a usar (normalizada para setores cíclicos)
    fcl_norm, fcl_ultimo, n_anos_hist = _fcl_normalizado(s)

    if ciclico:
        if fcl_norm is None:
            # Histórico insuficiente para normalizar
            st.warning(
                "⚠️ **Setor cíclico — histórico insuficiente para normalização.** "
                f"Foram encontrados apenas {n_anos_hist} ano(s) de FCL positivo "
                "(mínimo: 3). O cálculo usa o FCL do último período, que pode estar "
                "distorcido pelo momento atual do ciclo de commodity."
            )
            fcl_base = fcl_k
        else:
            st.warning(
                "⚠️ **Empresa de setor cíclico — valuation usa FCL médio normalizado.** "
                f"Em vez do resultado mais recente (R$ {fcl_ultimo/1000:.0f} mi), o modelo "
                f"usa a média dos últimos {n_anos_hist} anos (R$ {fcl_norm/1000:.0f} mi) "
                "para evitar distorção causada por picos ou vales do ciclo de commodities."
            )
            fcl_base = fcl_norm
    else:
        fcl_base = fcl_k

    if fcl_base is None or fcl_base <= 0:
        if ciclico:
            st.warning(
                f"⚠️ FCL base negativo ou zero (R$ {(fcl_base or 0)/1000:.0f} mi) — "
                "DCF não aplicável. Verifique se a empresa está em fase de investimento "
                "intenso ou se o ciclo atual é desfavorável."
            )
        else:
            st.warning(
                "⚠️ **FCL historicamente negativo (empresa em fase de expansão intensiva) "
                "— DCF não aplicável.** Avalie por múltiplos (EV/EBITDA, P/VP) ou fluxo "
                "normalizado quando a maturação dos investimentos elevar o caixa livre."
            )
        return

    # Informações da base usada
    if ciclico and fcl_norm is not None:
        col_i1, col_i2, col_i3 = st.columns(3)
        col_i1.metric("FCL último período", f"R$ {fcl_ultimo/1000:.0f} mi")
        col_i2.metric(f"FCL médio {n_anos_hist}a (usado)", f"R$ {fcl_norm/1000:.0f} mi")
        col_i3.metric("Ações", f"{shares/1e6:.1f} mi")
    else:
        st.caption(
            f"FCL base (último exercício): **R\\$ {fcl_base/1000:.0f} mi** · "
            f"Ações: **{shares/1e6:.1f} milhões**"
        )

    col_s1, col_s2, col_s3 = st.columns(3)
    with col_s1:
        wacc = st.slider(
            "WACC (%)", min_value=6.0, max_value=20.0, value=_wacc_default * 100, step=0.5,
            key=f"dcf_wacc_{s.get('ticker','')}",
            help="Padrão 12%. Utilities reguladas usam 10% (menor risco de fluxo tarifário).",
        ) / 100
    with col_s2:
        g5 = st.slider(
            "Crescimento FCL (5 anos, %)", min_value=-10.0, max_value=40.0, value=10.0, step=0.5,
            key=f"dcf_g5_{s.get('ticker','')}",
        ) / 100
    with col_s3:
        perp_g = st.slider(
            "Crescimento na perpetuidade (%)", min_value=0.0, max_value=8.0, value=_perp_default * 100, step=0.25,
            key=f"dcf_perp_{s.get('ticker','')}",
            help="Padrão 3%. Utilities reguladas usam 4% (indexação tarifária de longo prazo).",
        ) / 100

    if wacc <= perp_g:
        st.error("WACC deve ser maior que o crescimento na perpetuidade.")
        return

    def _dcf_price(fcl_b: float, g: float, w: float, pg: float, nd_k: float, n_shares: float) -> float:
        pv = 0.0
        fcl_y = fcl_b
        for yr in range(1, 6):
            fcl_y *= (1 + g)
            pv += fcl_y / (1 + w) ** yr
        tv = fcl_b * (1 + g) ** 5 * (1 + pg) / (w - pg)
        pv += tv / (1 + w) ** 5
        equity_k = pv - (nd_k or 0)
        return max(0.0, equity_k * 1000 / n_shares)

    nd_k = net_debt or 0.0
    scenarios = [
        ("Conservador", g5 * 0.7, "#f44336"),
        ("Base",        g5,       "#4caf50"),
        ("Otimista",    g5 * 1.3, "#2196f3"),
    ]

    prices_dcf = {}
    for name, g, _ in scenarios:
        prices_dcf[name] = _dcf_price(fcl_base, g, wacc, perp_g, nd_k, shares)

    p_cons = prices_dcf["Conservador"]
    p_base = prices_dcf["Base"]
    p_otim = prices_dcf["Otimista"]

    c_r, c_b, c_o = st.columns(3)
    def _upside(p):
        # Sem parênteses para o st.metric detectar o sinal e colorir
        # automaticamente (verde = alta, vermelho = queda)
        if price and price > 0:
            return f"{(p/price-1)*100:+.1f}%"
        return None

    c_r.metric("Conservador (−30% crescimento)", f"R$ {p_cons:.2f}", _upside(p_cons))
    c_b.metric("Base",                            f"R$ {p_base:.2f}", _upside(p_base))
    c_o.metric("Otimista (+30% crescimento)",     f"R$ {p_otim:.2f}", _upside(p_otim))

    # Gráfico Plotly
    fig = go.Figure()
    colors = ["#f44336", "#4caf50", "#2196f3"]
    names  = ["Conservador", "Base", "Otimista"]
    vals   = [p_cons, p_base, p_otim]
    fig.add_trace(go.Bar(
        x=names, y=vals,
        marker_color=colors,
        text=[f"R$ {v:.2f}" for v in vals],
        textposition="outside",
        hovertemplate="%{x}: R$ %{y:.2f}<extra></extra>",
    ))
    if price:
        fig.add_hline(
            y=price,
            line_dash="dash", line_color="#ffeb3b", line_width=2,
            annotation_text=f"Preço atual: R$ {price:.2f}",
            annotation_font_color="#ffeb3b",
        )
    fig.update_layout(
        height=320, margin=dict(l=0, r=0, t=30, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(showgrid=False, color="#9e9e9e"),
        yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.06)", color="#9e9e9e",
                   tickprefix="R$ "),
        showlegend=False,
        title=dict(text="Faixa de Preço Justo — DCF (3 cenários)", font=dict(size=12, color="#e8eaf6")),
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    st.warning(
        "⚠️ **Aviso importante:** Este modelo é uma ferramenta educacional de aproximação e "
        "**não constitui recomendação de investimento**. Os valores são altamente sensíveis às "
        "premissas de WACC, crescimento e perpetuidade. Resultados passados não garantem "
        "retornos futuros. Consulte um profissional habilitado antes de investir."
    )


# ────────────────────────────────────────────────────────────────
# Visão de detalhe de uma ação
# ────────────────────────────────────────────────────────────────

def _show_quality_price_map(q: Optional[float], p: Optional[float]) -> None:
    """Mapa 2×2 Qualidade × Preço com a ação posicionada."""
    thr = 55
    quads = [
        (thr, thr, 100, 100, "#1b5e20", "🟢 Boa<br>e barata"),
        (0, thr, thr, 100, "#bf360c", "🟠 Barata,<br>mas fraca"),
        (thr, 0, 100, thr, "#7b5800", "🟡 Boa,<br>mas cara"),
        (0, 0, thr, thr, "#7f0000", "🔴 Fraca<br>e cara"),
    ]
    active = None
    if q is not None and p is not None:
        active = ("🟢" if q >= thr and p >= thr else "🟠" if q < thr and p >= thr
                  else "🟡" if q >= thr and p < thr else "🔴")
    fig = go.Figure()
    for x0, y0, x1, y1, cor, nome in quads:
        on = active is not None and nome.startswith(active)
        fig.add_shape(type="rect", x0=x0, y0=y0, x1=x1, y1=y1, fillcolor=cor,
                      opacity=0.55 if on else 0.15, layer="below",
                      line=dict(color="rgba(255,255,255,0.15)", width=1))
        fig.add_annotation(x=(x0 + x1) / 2, y=(y0 + y1) / 2, text=nome, showarrow=False,
                           font=dict(size=14, color="#e8eaf6"))
    fig.add_shape(type="line", x0=thr, y0=0, x1=thr, y1=100,
                  line=dict(color="rgba(255,255,255,0.3)", width=1))
    fig.add_shape(type="line", x0=0, y0=thr, x1=100, y1=thr,
                  line=dict(color="rgba(255,255,255,0.3)", width=1))
    if q is not None and p is not None:
        fig.add_trace(go.Scatter(
            x=[q], y=[p], mode="markers+text",
            marker=dict(size=24, color="#ffeb3b", line=dict(color="#fff", width=3)),
            text=["AQUI"], textposition="top center", cliponaxis=False,
            textfont=dict(size=11, color="#fff", family="Arial Black"),
            hovertemplate=f"Qualidade {q:.0f} · Preço {p:.0f}<extra></extra>"))
    # Folga nos eixos p/ a bolha/rótulo "AQUI" caberem mesmo no canto (q/p ~100).
    fig.update_layout(
        height=340, margin=dict(l=8, r=8, t=8, b=28),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", showlegend=False,
        xaxis=dict(range=[-6, 109], showgrid=False, zeroline=False, showticklabels=False,
                   title=dict(text="←  menor qualidade      maior qualidade  →",
                              font=dict(size=10, color="#9e9e9e"))),
        yaxis=dict(range=[-8, 112], showgrid=False, zeroline=False, showticklabels=False,
                   title=dict(text="←  mais cara      mais barata  →",
                              font=dict(size=10, color="#9e9e9e"))))
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def _show_portfolio_quality_price_map(positions: list[dict]) -> None:
    """Mapa 2×2 com TODAS as posições (bolha ∝ peso) + centroide ponderado."""
    thr = 55
    pts = [p for p in positions
           if p.get("quality") is not None and p.get("price_score") is not None]
    if not pts:
        return
    # Quadrantes simétricos: tingidos de LO..HI partidos no limiar (thr).
    LO, HI = 10, 100
    rects = [
        (thr, thr, HI, HI, "rgba(52,211,153,0.13)", "rgba(52,211,153,0.55)"),   # boa e barata
        (LO, thr, thr, HI, "rgba(251,146,60,0.13)", "rgba(251,146,60,0.55)"),   # barata, mas fraca
        (thr, LO, HI, thr, "rgba(251,191,36,0.12)", "rgba(251,191,36,0.50)"),   # boa, mas cara
        (LO, LO, thr, thr, "rgba(248,113,113,0.12)", "rgba(248,113,113,0.50)"), # fraca e cara
    ]
    fig = go.Figure()
    for x0, y0, x1, y1, cor, bcor in rects:
        fig.add_shape(type="rect", x0=x0, y0=y0, x1=x1, y1=y1, fillcolor=cor,
                      layer="below", line=dict(color=bcor, width=1.4))
    fig.add_shape(type="line", x0=thr, y0=LO, x1=thr, y1=HI,
                  line=dict(color="rgba(255,255,255,0.3)", width=1))
    fig.add_shape(type="line", x0=LO, y0=thr, x1=HI, y1=thr,
                  line=dict(color="rgba(255,255,255,0.3)", width=1))
    # Pills de rótulo nos cantos de cada quadrante
    pills = [
        (HI - 1, HI - 1, "right", "top",    "#34d399", "#04342c", "boa e barata"),
        (LO + 1, HI - 1, "left",  "top",    "#fb923c", "#4a1b0c", "barata, mas fraca"),
        (HI - 1, LO + 1, "right", "bottom", "#fbbf24", "#412402", "boa, mas cara"),
        (LO + 1, LO + 1, "left",  "bottom", "#f87171", "#501313", "fraca e cara"),
    ]
    for px, py, xa, ya, bg, tx, lbl in pills:
        fig.add_annotation(x=px, y=py, text=lbl, showarrow=False,
                           xanchor=xa, yanchor=ya, bgcolor=bg, borderpad=4,
                           font=dict(size=12, color=tx, family="Inter, sans-serif"))

    max_w = max(p["weight"] for p in pts) or 1
    sizes = [14 + 26 * (p["weight"] / max_w) for p in pts]
    fig.add_trace(go.Scatter(
        x=[p["quality"] for p in pts], y=[p["price_score"] for p in pts],
        mode="markers+text",
        marker=dict(size=sizes, color="#42a5f5", opacity=0.75,
                    line=dict(color="#fff", width=1.5)),
        text=[p["ticker"] for p in pts], textposition="top center",
        textfont=dict(size=11, color="#cfe3ff"), cliponaxis=False,
        customdata=[[p["weight"] * 100] for p in pts],
        hovertemplate="%{text}<br>Qualidade %{x:.0f} · Preço %{y:.0f}"
                      "<br>%{customdata[0]:.1f}% da carteira<extra></extra>"))

    # Centroide ponderado (★)
    qc = _weighted_avg_portfolio(positions, "quality")
    pc = _weighted_avg_portfolio(positions, "price_score")
    if qc is not None and pc is not None:
        fig.add_trace(go.Scatter(
            x=[qc], y=[pc], mode="markers+text",
            marker=dict(size=20, color="#ffeb3b", symbol="star",
                        line=dict(color="#000", width=1.5)),
            text=["carteira"], textposition="bottom center",
            textfont=dict(size=10, color="#ffeb3b", family="Arial Black"),
            cliponaxis=False,
            hovertemplate=f"Carteira (pond.)<br>Qualidade {qc:.0f} · Preço {pc:.0f}<extra></extra>"))

    # Folga nos eixos para a bolha inteira (e o rótulo) caberem dentro da
    # área visível. Mais folga na vertical, que é o eixo curto.
    fig.update_layout(
        height=540, margin=dict(l=8, r=8, t=8, b=30),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", showlegend=False,
        xaxis=dict(range=[3, 107], showgrid=False, zeroline=False, showticklabels=False,
                   title=dict(text="←  menor qualidade      maior qualidade  →",
                              font=dict(size=15, color="#c7cedb", family="Inter, sans-serif"))),
        yaxis=dict(range=[3, 107], showgrid=False, zeroline=False, showticklabels=False,
                   title=dict(text="←  mais cara      mais barata  →",
                              font=dict(size=15, color="#c7cedb", family="Inter, sans-serif"))))
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    st.caption("Cada bolha é uma posição (tamanho ∝ % da carteira); a ⭐ é a média ponderada.")


def _show_score_panel(s: dict) -> None:
    """Painel de scores Qualidade × Preço + diagnóstico + mapa 2×2."""
    scores = s.get("scores") or sc.calculate_scores(s)
    q, p, diag = scores.get("quality"), scores.get("price"), scores.get("diagnosis")

    st.subheader("📊 Qualidade × Preço")
    if diag:
        st.markdown(
            f"<div style='display:inline-block;background:{diag['color']};padding:6px 16px;"
            f"border-radius:999px;color:#fff;font-size:1.05rem;font-weight:600;margin-bottom:10px'>"
            f"{diag['label']}</div>",
            unsafe_allow_html=True)
    elif q is None and p is None:
        st.info("Dados insuficientes para calcular os scores deste ticker.")
        return

    _qtier = diag["quality_tier"] if diag else None
    _ptier = diag["price_tier"] if diag else None
    col_a, col_b = st.columns([1, 1.15])
    with col_a:
        cq, cp = st.columns(2)
        cq.metric("Qualidade", f"{q:.0f}/100" if q is not None else "—")
        if _qtier:
            cq.caption(f"**{_qtier}**")
        if q is not None:
            cq.progress(int(q))
        cp.metric("Preço (atratividade)", f"{p:.0f}/100" if p is not None else "—")
        if _ptier:
            cp.caption(f"**{_ptier}**")
        if p is not None:
            cp.progress(int(p))
        _eq = scores.get("earnings_quality")
        if _eq:
            _eq_colors = {"ruim": "#bf360c", "fraca": "#7b5800",
                          "ok": "#2e7d32", "forte": "#1b5e20"}
            _ec = _eq_colors.get(_eq["level"], "#37474f")
            _haircut = ("" if _eq["penalty"] >= 1.0
                        else f" · −{(1 - _eq['penalty']) * 100:.0f}% na Qualidade")
            st.markdown(
                f"<div style='background:{_ec};padding:6px 12px;border-radius:6px;color:#fff;"
                f"font-size:0.85rem;margin:6px 0'>🧮 Qualidade do lucro: "
                f"{_eq['label']}{_haircut}</div>",
                unsafe_allow_html=True)
        st.caption(
            "**Qualidade** = ROE, solidez, margem e crescimento. **Preço** = EV/EBITDA, P/L, "
            "P/FCF (bancos: P/VP e P/L). Quanto **maior o Preço, mais barata** a ação.")
        with st.expander("Ver o que puxou cada score"):
            _bq = scores.get("breakdown_quality", {})
            _bp = scores.get("breakdown_price", {})
            for titulo, bd in [("🏅 Qualidade", _bq), ("💰 Preço", _bp)]:
                st.markdown(f"**{titulo}**")
                for ind, info in bd.items():
                    nm = INDICATOR_LABELS.get(ind, ind)
                    _sci = info.get("score")
                    _sv = "—" if _sci is None else f"{_sci:.0f}"
                    st.caption(f"{nm}: {_sv}/100 · peso {info['weight'] * 100:.0f}%")
    with col_b:
        _show_quality_price_map(q, p)


def _show_detail(s: dict):
    sector = s.get("sector", "")
    bank = sc.is_bank(sector)
    classifications = sc.classify_all(s)
    scores = s.get("scores") or sc.calculate_scores(s)

    # ── Cabeçalho ──────────────────────────────────────────────
    c1, c2, c3 = st.columns([3, 2, 2])
    with c1:
        nome = s.get("corporate_name") or s.get("ticker", "")
        pregao = s.get("trade_name", "")
        st.markdown(f"## {pregao or nome}")
        st.caption(nome if pregao else "")
        _tkr = s.get("ticker", "")
        st.markdown(
            f"<span style='display:inline-block;font-size:0.8rem;font-weight:500;color:#a7f3d0;"
            f"background:#0c2a23;border:1px solid #1f4a3d;padding:3px 11px;border-radius:999px'>"
            f"{sector or '—'}{(' · ' + _tkr) if _tkr else ''}</span>",
            unsafe_allow_html=True)
        ref = s.get("reference_date", "")
        if ref:
            st.caption(f"Balanço de referência: {ref}")

    with c2:
        preco = s.get("close_price")
        var = s.get("daily_change_pct")
        if preco is not None:
            st.metric(
                "Preço Atual",
                _fmt_price(preco),
                delta=f"{var:+.2f}%" if var is not None else None,
            )
        _pl_h = s.get("pl")
        _dy_h = s.get("dividend_yield")
        _mpl, _mdy = st.columns(2)
        _mpl.metric("P/L", f"{_pl_h:.1f}x" if _pl_h is not None else "—")
        _mdy.metric("DY", f"{_dy_h:.1f}%" if _dy_h is not None else "—")

    with c3:
        low52 = s.get("week_52_low")
        high52 = s.get("week_52_high")
        ytd = s.get("ytd_return_pct")
        if low52 and high52:
            _lo = _fmt_price(low52).replace("$", "&#36;")
            _hi = _fmt_price(high52).replace("$", "&#36;")
            st.markdown(
                f"<div style='font-size:1.05rem;margin-bottom:6px'><b>52 sem:</b> "
                f"{_lo} — {_hi}</div>", unsafe_allow_html=True)
        if ytd is not None:
            st.markdown(
                f"<div style='font-size:1.05rem'><b>Retorno YTD:</b> "
                f"{_fmt_pct(ytd)}</div>", unsafe_allow_html=True)

    st.divider()

    # ── Scores Qualidade × Preço + diagnóstico ──────────────────
    _show_score_panel(s)

    # ── Alertas de mudança de classificação ────────────────────
    _t_alert = s.get("ticker", "")
    _cls_changes = st.session_state.acoes.get(_t_alert, {}).get("classification_changes", [])
    if _cls_changes:
        _n = len(_cls_changes)
        with st.expander(f"🔔 {_n} indicador{'es' if _n > 1 else ''} mudou{'am' if _n > 1 else ''} de classificação desde a última atualização", expanded=False):
            for _chg in _cls_changes:
                _old_em = COLOR_EMOJI.get(_chg['de'], "⬜")
                _new_em = COLOR_EMOJI.get(_chg['para'], "⬜")
                st.markdown(f"**{_chg['ind']}:** {_old_em} {_chg['de']} → {_new_em} {_chg['para']}")

    st.divider()

    # ── Gráfico de preço histórico ──────────────────────────────
    _show_price_history_chart(s)

    # ── Indicadores por score (Qualidade × Preço) ──────────────
    st.divider()
    st.subheader("Indicadores por Score")
    st.caption("Cada indicador alimenta a **Qualidade** (negócio) ou o **Preço** "
               "(atratividade). A pontuação 0–100 é contínua; o peso é dentro do "
               "respectivo eixo.")

    _bd_q = scores.get("breakdown_quality", {})
    _bd_p = scores.get("breakdown_price", {})
    for _titulo, _bd in [("🏅 Qualidade", _bd_q), ("💰 Preço (atratividade)", _bd_p)]:
        if not _bd:
            continue
        st.markdown(f"#### {_titulo}")
        for ind, binfo in _bd.items():
            if ind == "pvp":  # P/VP não está no classify_all
                cls, disp = sc.classify_pvp(s.get("pvp"), sector)
            else:
                cls, disp = classifications.get(ind, ("ND", "N/D"))
            label_ind = INDICATOR_LABELS.get(ind, ind)
            emoji = COLOR_EMOJI.get(cls, "⬜")
            peso = binfo.get("weight", 0.0)
            pts = binfo.get("score")
            bg = BG_COLORS.get(cls, "#37474f")
            info = INDICATOR_INFO.get(ind, {})

            with st.container():
                # Layout: [nome] [ℹ️] [(peso X%)] [valor colorido] [pontuação]
                ca, cb, cc, cd, ce = st.columns([2.0, 0.28, 1.1, 2, 3])
                with ca:
                    st.markdown(f"**{label_ind}**")
                with cb:
                    if info:
                        with st.popover("ℹ️"):
                            st.markdown(f"**{label_ind}**")
                            st.markdown(f"**O que mede:** {info.get('o_que_mede', '')}")
                            st.markdown(f"**Por que importa:** {info.get('por_que_importa', '')}")
                            st.markdown(f"**Interpretação:** {info.get('interpretacao', '')}")
                            st.markdown(f"**Faixa ideal:** {info.get('faixa_ideal', '')}")
                            st.caption(f"⚠ {info.get('atencao', '')}")
                            insight = _sector_insight(ind, sector)
                            if insight:
                                st.divider()
                                st.markdown(f"📊 **Contexto setorial:** {insight}")
                with cc:
                    st.markdown(f"*(peso {peso*100:.0f}%)*")
                with cd:
                    st.markdown(
                        f"<div style='background:{bg};color:#fff;padding:6px 12px;"
                        f"border-radius:6px;text-align:center;font-weight:700;font-size:1.05rem'>"
                        f"{emoji} {disp}</div>",
                        unsafe_allow_html=True,
                    )
                with ce:
                    if pts is not None:
                        st.caption(f"Pontuação: {pts:.0f}/100 · peso {peso*100:.0f}%")
                        st.progress(int(pts))
                    else:
                        st.caption("Não disponível/inconclusivo — peso redistribuído")
            st.markdown("")

    # ── Radar dos 6 indicadores principais ─────────────────────
    # Pulado p/ financeiras (banco/seguradora): metade dos 6 indicadores do
    # radar (EV/EBITDA, Dív.Líq/EBITDA, Mg.EBITDA) não se aplica e o gráfico
    # vira uma forma degenerada/enganosa.
    if not bank and not sc.is_insurer(sector):
        st.divider()
        st.subheader("Perfil Radar")
        st.caption("Pontuação (0–100) nos 6 indicadores de maior peso.")
        fig_radar = _radar_chart([s], [s.get("ticker", "")])
        st.plotly_chart(fig_radar, use_container_width=True, config={"displayModeBar": False})

    # ── Lucro vs Cotação ────────────────────────────────────────
    _lucro_data = _fetch_lucro_cotacao(s.get("ticker", ""))
    if _lucro_data:
        st.divider()
        st.subheader("Lucro vs Cotação")
        _show_lucro_cotacao_chart(s.get("ticker", ""))

    # ── DCF Valuation ───────────────────────────────────────────
    _show_dcf(s)

    # ── Indicadores informativos ────────────────────────────────
    st.divider()
    st.subheader("Indicadores Informativos")

    pvp = s.get("pvp")
    payout = s.get("payout")
    net_margin = s.get("net_margin")
    roa = s.get("roa")
    roic = s.get("roic")

    # P/VP com popover
    with st.container():
        col_pvp, col_pvp_help = st.columns([8, 1])
        with col_pvp:
            st.markdown("#### P/VP — Preço / Valor Patrimonial")
        with col_pvp_help:
            info_pvp = INDICATOR_INFO.get("pvp", {})
            if info_pvp:
                with st.popover("❓"):
                    st.markdown("**P/VP — Preço / Valor Patrimonial**")
                    st.markdown(f"**O que mede:** {info_pvp.get('o_que_mede', '')}")
                    st.markdown(f"**Por que importa:** {info_pvp.get('por_que_importa', '')}")
                    st.markdown(f"**Interpretação:** {info_pvp.get('interpretacao', '')}")
                    st.markdown(f"**Faixa ideal:** {info_pvp.get('faixa_ideal', '')}")
                    st.caption(f"⚠ {info_pvp.get('atencao', '')}")
        if bank:
            st.markdown("**Indicador principal para bancos.** P/VP ideal entre **1,0× e 2,5×**.")
        cls_pvp, disp_pvp = sc.classify_pvp(pvp, sector)
        bg_pvp = BG_COLORS.get(cls_pvp, "#37474f")
        emoji_pvp = COLOR_EMOJI.get(cls_pvp, "⬜")
        if pvp is not None:
            st.markdown(
                f"<div style='display:inline-block;background:{bg_pvp};color:#fff;"
                f"padding:8px 18px;border-radius:8px;font-weight:700;font-size:1.5rem'>"
                f"{emoji_pvp} {disp_pvp}</div>",
                unsafe_allow_html=True,
            )
            if _is_insurer(sector):
                st.caption("P/VP alto é normal em seguradoras (asset-light, ROE estruturalmente alto). Avalie pelo P/L.")
            elif pvp < 1.0:
                st.caption("Abaixo do valor patrimonial — pode ser desconto real ou sinalizar problema de qualidade dos ativos.")
            elif pvp > 3.0:
                st.caption("⚠ Exige ROE muito alto para justificar o prêmio.")
        else:
            st.caption("N/D")

    # PSR com popover — oculto p/ seguradoras (depende de receita convencional)
    if not _is_insurer(sector):
        with st.container():
            col_psr, col_psr_help = st.columns([8, 1])
            with col_psr:
                st.markdown("#### PSR — Preço / Receita")
            with col_psr_help:
                info_psr = INDICATOR_INFO.get("psr", {})
                if info_psr:
                    with st.popover("❓"):
                        st.markdown("**PSR — Preço / Receita (Price-to-Sales)**")
                        st.markdown(f"**O que mede:** {info_psr.get('o_que_mede', '')}")
                        st.markdown(f"**Por que importa:** {info_psr.get('por_que_importa', '')}")
                        st.markdown(f"**Interpretação:** {info_psr.get('interpretacao', '')}")
                        st.markdown(f"**Faixa ideal:** {info_psr.get('faixa_ideal', '')}")
                        st.caption(f"⚠ {info_psr.get('atencao', '')}")
            cls_psr, disp_psr = _classify_psr(s.get("psr"), sector)
            bg_psr   = BG_COLORS.get(cls_psr, "#37474f")
            emoji_psr = COLOR_EMOJI.get(cls_psr, "⬜")
            if s.get("psr") is not None:
                st.markdown(
                    f"<div style='display:inline-block;background:{bg_psr};color:#fff;"
                    f"padding:6px 14px;border-radius:6px;font-weight:700;font-size:1.05rem'>"
                    f"{emoji_psr} {disp_psr}</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.caption("N/D")

    with st.container():
        st.markdown("#### Payout (%)")
        if payout is not None:
            st.markdown(
                f"<div style='font-size:1.5rem;font-weight:700'>{payout:.1f}%</div>",
                unsafe_allow_html=True)
            if payout > 80:
                st.caption("⚠️ Payout alto (> 80%). Verifique sustentabilidade com FCL.")
        else:
            st.caption("N/D — sem dados de dividendos ou LPA disponíveis para este ticker.")

    with st.container():
        st.markdown("#### Governança")
        st.caption(
            "Segmento de listagem e Tag Along não são fornecidos pela API Bolsai. "
            "Consulte o site da B3 ou o Formulário de Referência (CVM)."
        )

    if bank:
        with st.container():
            st.markdown("#### Índice de Basileia")
            st.caption(
                "Indicador regulatório de capital (mínimo: 11%; confortável: ≥ 14%). "
                "Não disponível na API Bolsai — consulte o Relatório de Administração "
                "ou o site do Banco Central do Brasil."
            )

    # ── Anotações do usuário ────────────────────────────────────
    st.divider()
    st.subheader("📝 Minhas Anotações")
    _ticker = s.get("ticker", "")
    _notas_key    = f"notas_{_ticker}"
    _mudanca_key  = f"notas_mudanca_{_ticker}"

    _notas_entry  = st.session_state.acoes.get(_ticker, {})
    _notas_text   = _notas_entry.get("notas", "")
    _notas_updated= _notas_entry.get("notas_updated_at", "")
    _historico    = _notas_entry.get("notas_historico", [])

    # Inicializa session_state com valores salvos
    if _notas_key not in st.session_state:
        st.session_state[_notas_key] = _notas_text
    if _mudanca_key not in st.session_state:
        st.session_state[_mudanca_key] = ""

    st.text_area(
        "Anotações / tese de investimento:",
        key=_notas_key,
        height=160,
        placeholder=(
            "Escreva sua tese, lembretes ou observações sobre esta ação…\n\n"
            "Use o campo abaixo para registrar atualizações — elas serão inseridas "
            "automaticamente aqui no topo, formando um histórico cronológico."
        ),
    )
    st.text_input(
        "📅 O que mudou desde a última revisão? (opcional)",
        key=_mudanca_key,
        placeholder="ex.: resultado do 1T25 acima do esperado, reduzi preço-alvo…",
        help="Ao salvar, este texto será inserido no topo das anotações com a data atual.",
    )

    def _save_notas_btn(_t=_ticker, _key=_notas_key, _mkey=_mudanca_key):
        new_text    = st.session_state.get(_key, "")
        new_mudanca = st.session_state.get(_mkey, "").strip()
        entry = st.session_state.acoes.get(_t)
        if entry is None:
            return
        old_text = entry.get("notas", "")
        if new_text == old_text and not new_mudanca:
            return

        # Se "O que mudou" foi preenchido, prepend uma entrada de log no topo do texto
        if new_mudanca:
            now_fmt   = _now_bsb().strftime("%d/%m/%Y %H:%M")
            sep       = "──────────────────────"
            log_entry = f"📅 {now_fmt} — Atualização\n{new_mudanca}"
            final_text = f"{log_entry}\n\n{sep}\n\n{new_text}" if new_text.strip() else log_entry
        else:
            final_text = new_text

        # Empurra versão anterior para o histórico (max 5)
        hist = list(entry.get("notas_historico", []))
        if old_text:
            hist.insert(0, {"texto": old_text, "data": entry.get("notas_updated_at", "")})
            hist = hist[:5]

        entry["notas"]            = final_text
        entry["notas_updated_at"] = _now_bsb().isoformat()
        entry["notas_historico"]  = hist
        # Remove campo obsoleto notas_mudancas (agora baked into o texto)
        entry.pop("notas_mudancas", None)
        st.session_state.acoes[_t] = entry
        # Atualiza text_area para refletir o novo conteúdo imediatamente
        st.session_state[_key]  = final_text
        st.session_state[_mkey] = ""
        _save_all()

    st.button("💾 Salvar anotação", key=f"btn_notas_{_ticker}", on_click=_save_notas_btn)

    if _notas_updated:
        try:
            _dt = datetime.fromisoformat(_notas_updated)
            if _dt.tzinfo is None:
                _dt = _dt.replace(tzinfo=timezone.utc)
            _dt = _dt.astimezone(TZ_BSB).replace(tzinfo=None)
            st.caption(f"Última edição: {_dt.strftime('%d/%m/%Y %H:%M')} (Brasília)")
        except Exception:
            st.caption(f"Última edição: {_notas_updated[:16]}")

    if _historico:
        with st.expander(f"🕓 Histórico ({len(_historico)} versões anteriores)", expanded=False):
            for _v in _historico:
                _vdata = _v.get("data", "")
                try:
                    _vdt = datetime.fromisoformat(_vdata)
                    if _vdt.tzinfo is None:
                        _vdt = _vdt.replace(tzinfo=timezone.utc)
                    _vdt = _vdt.astimezone(TZ_BSB).replace(tzinfo=None)
                    _vdata = _vdt.strftime("%d/%m/%Y %H:%M")
                except Exception:
                    _vdata = _vdata[:16]
                st.markdown(f"**Versão de {_vdata}**")
                st.markdown(
                    f"<div style='background:#1a1d2e;border-left:3px solid #3f51b5;"
                    f"padding:8px 12px;border-radius:4px;color:#c8cce0;font-size:0.9rem;"
                    f"white-space:pre-wrap'>"
                    f"{_v.get('texto','').replace('<','&lt;').replace('>','&gt;')}"
                    f"</div>",
                    unsafe_allow_html=True,
                )
                st.markdown("")

    # ── Outros indicadores ─────────────────────────────────────
    _OUTROS_INFO: dict[str, str] = {
        "ROA":                 "**Return on Assets** — Lucro líquido / Ativo total. Mede a eficiência com que a empresa usa seus ativos para gerar lucro. Acima de 5% é satisfatório para a maioria dos setores.",
        "ROIC":                "**Return on Invested Capital** — Lucro operacional após impostos / Capital investido. Indica se a empresa cria valor acima do custo de capital. ROIC > WACC = geração de valor.",
        "Margem Líquida":      "**Net Margin** — Lucro líquido / Receita líquida. Percentual de cada real de receita que se converte em lucro após todas as despesas e impostos.",
        "Margem Bruta":        "**Gross Margin** — (Receita − Custo dos produtos) / Receita. Indica o poder de precificação e a eficiência produtiva antes das despesas operacionais.",
        "LPA":                 "**Lucro por Ação** — Lucro líquido / número de ações. Base para calcular o P/L. Crescimento consistente do LPA sinaliza geração de valor para o acionista.",
        "VPA":                 "**Valor Patrimonial por Ação** — Patrimônio líquido / número de ações. Comparado ao preço de mercado (P/VP), indica se a ação negocia com prêmio ou desconto em relação ao balanço.",
        "Liq. Corrente":       "**Current Ratio** — Ativo circulante / Passivo circulante. Acima de 1,5× indica boa folga de caixa para honrar obrigações de curto prazo. Abaixo de 1× é sinal de atenção.",
        "EBITDA (R$ mi)":      "**EBITDA** — Lucro antes de juros, impostos, depreciação e amortização, em R$ milhões. Proxy do caixa operacional; base para indicadores como EV/EBITDA e Dív/EBITDA.",
        "Rec. Líq. (R$ mi)":   "**Receita Líquida** — Faturamento após deduções fiscais e devoluções, em R$ milhões. Principal linha de crescimento; base para cálculo das margens.",
        "Lucro Líq. (R$ mi)":  "**Lucro Líquido** — Resultado final após todas as despesas, juros e impostos, em R$ milhões. Lucro negativo (prejuízo) classifica o P/L como Proibitivo.",
        "Cob. de Juros":       "**Cobertura de Juros** = EBIT / Despesa Financeira. Indica quantas vezes o lucro operacional cobre os juros da dívida. Abaixo de 1× significa que a empresa não gera lucro suficiente para pagar os juros — sinal grave de risco financeiro.",
        "Div. Yield":          "**Dividend Yield** — Dividendos pagos nos últimos 12 meses / preço da ação. Quanto a ação rende em proventos por ano. Especialmente relevante em seguradoras e empresas maduras pagadoras.",
    }
    st.divider()
    with st.expander("📋 Outros indicadores", expanded=False):
        _gross_margin = s.get("gross_margin")
        _int_cov = s.get("interest_coverage")
        cls_cov, disp_cov = _classify_interest_coverage(_int_cov, sector)
        _dy = s.get("dividend_yield")
        if _is_insurer(sector):
            # Seguradora não tem DRE convencional: margens/receita/EBITDA/cobertura
            # de juros não se aplicam (ficavam todos N/D). Mostra só o que faz
            # sentido + dividendos (relevante no setor).
            st.caption("ℹ️ Margens, Receita, EBITDA e Cobertura de Juros foram omitidos — "
                       "seguradora não reporta DRE convencional. Foco em rentabilidade "
                       "e dividendos.")
            items = [
                ("ROA",                 f"{roa:.1f}%" if roa is not None else "N/D"),
                ("ROIC",                f"{roic:.1f}%" if roic is not None else "N/D"),
                ("Div. Yield",          f"{_dy:.1f}%" if _dy is not None else "N/D"),
                ("LPA",                 f"R$ {s['lpa']:.2f}" if s.get("lpa") else "N/D"),
                ("VPA",                 f"R$ {s['vpa']:.2f}" if s.get("vpa") else "N/D"),
                ("Lucro Líq. (R$ mi)",  f"{s['net_income']/1000:.0f}" if s.get("net_income") else "N/D"),
            ]
        else:
            items = [
                ("Margem Líquida",      f"{net_margin:.1f}%" if net_margin is not None else "N/D"),
                ("Margem Bruta",        f"{_gross_margin:.1f}%" if _gross_margin is not None else "N/D"),
                ("ROA",                 f"{roa:.1f}%" if roa is not None else "N/D"),
                ("ROIC",                f"{roic:.1f}%" if roic is not None else "N/D"),
                ("Div. Yield",          f"{_dy:.1f}%" if _dy is not None else "N/D"),
                ("LPA",                 f"R$ {s['lpa']:.2f}" if s.get("lpa") else "N/D"),
                ("VPA",                 f"R$ {s['vpa']:.2f}" if s.get("vpa") else "N/D"),
                ("Liq. Corrente",       f"{s['current_ratio']:.2f}x" if s.get("current_ratio") else "N/D"),
                ("EBITDA (R$ mi)",      f"{s['ebitda']/1000:.0f}" if s.get("ebitda") else "N/D"),
                ("Rec. Líq. (R$ mi)",   f"{s['net_revenue']/1000:.0f}" if s.get("net_revenue") else "N/D"),
                ("Lucro Líq. (R$ mi)",  f"{s['net_income']/1000:.0f}" if s.get("net_income") else "N/D"),
                ("Cob. de Juros",       disp_cov),
            ]
        cols = st.columns(3)
        for i, (lbl, val) in enumerate(items):
            with cols[i % 3]:
                c_met, c_info = st.columns([4, 1])
                # Cobertura de juros: mostra badge colorida em vez de metric
                if lbl == "Cob. de Juros" and cls_cov not in ("ND", "NA"):
                    bg_cov   = BG_COLORS.get(cls_cov, "#37474f")
                    emoji_cov = COLOR_EMOJI.get(cls_cov, "⬜")
                    c_met.markdown(f"**{lbl}**")
                    c_met.markdown(
                        f"<div style='display:inline-block;background:{bg_cov};color:#fff;"
                        f"padding:4px 10px;border-radius:5px;font-weight:700;font-size:0.95rem'>"
                        f"{emoji_cov} {disp_cov}</div>",
                        unsafe_allow_html=True,
                    )
                else:
                    c_met.metric(lbl, val)
                if lbl in _OUTROS_INFO:
                    with c_info.popover("ℹ️", use_container_width=True):
                        st.markdown(_OUTROS_INFO[lbl])


# ────────────────────────────────────────────────────────────────
# Tabela comparativa lado a lado (HTML com cores)
# ────────────────────────────────────────────────────────────────

def _comparison_table(selected_tickers: list[str], stocks: list[dict]) -> None:
    """Renderiza tabela indicador × ação com células coloridas por classificação."""
    all_inds = list(SCORED_COLS_ORDER) + ["pvp", "psr"]

    th = "padding:9px 10px;color:#8b94a7;border-bottom:1px solid #232b3a;background:#151b26;font-weight:600;font-size:0.72rem;text-transform:uppercase;letter-spacing:0.04em"
    html = "<div style='overflow-x:auto'>"
    html += "<table style='width:100%;border-collapse:collapse;font-size:0.87rem'>"
    html += "<thead><tr>"
    html += f"<th style='{th};text-align:left'>Indicador</th>"
    for t in selected_tickers:
        html += f"<th style='{th};text-align:center'>{t}</th>"
    html += "</tr></thead><tbody>"

    for i, ind in enumerate(all_inds):
        label_ind = INDICATOR_LABELS.get(ind, ind)
        row_bg = "#0e1117" if i % 2 == 0 else "#131629"
        html += f"<tr style='background:{row_bg}'>"
        html += (
            f"<td style='padding:6px 10px;color:#c8cce0;border-bottom:1px solid #1e2130;"
            f"font-weight:500'>{label_ind}</td>"
        )
        for stock in stocks:
            sector = stock.get("sector", "")
            if ind == "pvp":
                cls, disp = sc.classify_pvp(stock.get("pvp"), sector)
            elif ind == "psr":
                cls, disp = _classify_psr(stock.get("psr"), sector)
            else:
                cls, disp = sc.classify_all(stock).get(ind, ("ND", "N/D"))
            bg = BG_COLORS.get(cls, "")
            if bg:
                cell_style = (
                    f"background:{bg};color:#fff;font-weight:600;"
                    f"text-align:center;padding:6px 10px;border-bottom:1px solid #1e2130"
                )
            else:
                cell_style = (
                    f"background:{row_bg};color:#666;"
                    f"text-align:center;padding:6px 10px;border-bottom:1px solid #1e2130"
                )
            html += f"<td style='{cell_style}'>{disp}</td>"
        html += "</tr>"

    html += "</tbody></table></div>"
    st.markdown(html, unsafe_allow_html=True)


# ────────────────────────────────────────────────────────────────
# Aba Screener
# ────────────────────────────────────────────────────────────────

_SCREENER_PRESETS: dict = {
    "🏆 Fundamentalista": {"roe_min": 15, "pl_max": 15, "nd_max": 2, "mg_min": 12, "ev_max": 15, "qual_min": 65, "price_min": 0,  "excl_bancos": True},
    "💰 Dividendos":      {"roe_min": 12, "pl_max": 20, "nd_max": 3, "mg_min": 10, "ev_max": 20, "qual_min": 55, "price_min": 0,  "excl_bancos": False},
    "🚀 Crescimento":     {"roe_min": 18, "pl_max": 25, "nd_max": 2, "mg_min": 15, "ev_max": 20, "qual_min": 60, "price_min": 0,  "excl_bancos": True},
    "🎯 Qualidade ≥ 80":  {"roe_min": 0,  "pl_max": 50, "nd_max": 5, "mg_min":  0, "ev_max": 20, "qual_min": 80, "price_min": 0,  "excl_bancos": False},
    "🔥 Barganhas":       {"roe_min": 0,  "pl_max": 50, "nd_max": 5, "mg_min":  0, "ev_max": 20, "qual_min": 55, "price_min": 70, "excl_bancos": False},
}


def _apply_scr_preset(params: dict) -> None:
    st.session_state.scr_roe_min   = int(params.get("roe_min", 15))
    st.session_state.scr_pl_max    = int(params.get("pl_max", 15))
    st.session_state.scr_nd_max    = int(params.get("nd_max", 2))
    st.session_state.scr_mg_min    = int(params.get("mg_min", 12))
    st.session_state.scr_ev_max    = int(params.get("ev_max", 8))
    # compat: filtros salvos antigos tinham só "score_min" (mapeia p/ Qualidade)
    st.session_state.scr_qual_min  = int(params.get("qual_min", params.get("score_min", 0)))
    st.session_state.scr_price_min = int(params.get("price_min", 0))
    st.session_state.scr_excl_bancos = bool(params.get("excl_bancos", True))


def _show_screener():
    st.markdown("## 🔎 Screener — B3 Completo")
    st.caption("Filtra todas as empresas listadas na B3 em tempo real via API Bolsai Pro.")

    # ── Presets e filtros salvos ───────────────────────────────
    col_presets, col_saved = st.columns([1, 1])

    with col_presets:
        st.markdown("**Presets:**")
        for nome_preset, params_preset in _SCREENER_PRESETS.items():
            if st.button(nome_preset, key=f"preset_{nome_preset}", use_container_width=True):
                _apply_scr_preset(params_preset)
                st.rerun()

    with col_saved:
        st.markdown("**Meus filtros salvos:**")
        filtros_user = st.session_state.get("screener_filtros", {})
        if filtros_user:
            for nome_f, params_f in list(filtros_user.items()):
                _col_ap, _col_rm = st.columns([4, 1])
                with _col_ap:
                    if st.button(nome_f, key=f"filtro_ap_{nome_f}", use_container_width=True):
                        _apply_scr_preset(params_f)
                        st.rerun()
                with _col_rm:
                    if st.button("🗑", key=f"filtro_rm_{nome_f}", help=f"Excluir '{nome_f}'"):
                        del st.session_state.screener_filtros[nome_f]
                        _save_all()
                        st.rerun()
        else:
            st.caption("Nenhum filtro salvo ainda.")

    st.divider()

    # ── Painel de filtros ──────────────────────────────────────
    with st.expander("⚙️ Ajustar filtros", expanded=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            roe_min   = st.slider("ROE mínimo (%)",        0, 50,  15, key="scr_roe_min")
            pl_max    = st.slider("P/L máximo (x)",         1, 50,  15, key="scr_pl_max")
            nd_max    = st.slider("Dív/EBITDA máximo (x)", -2,  5,   2, key="scr_nd_max")
        with c2:
            mg_min    = st.slider("Mg. EBITDA mínima (%)", 0, 50,  12, key="scr_mg_min")
            ev_max    = st.slider("EV/EBITDA máximo (x)",  0, 20,   8, key="scr_ev_max")
        with c3:
            qual_min  = st.slider("Score qualidade (mín.)", 0, 100,  0, key="scr_qual_min",
                                  help="Mantém ações com Score de Qualidade (negócio) ≥ este valor")
            price_min = st.slider("Score preço (mín.)",     0, 100,  0, key="scr_price_min",
                                  help="Mantém ações com Score de Preço (atratividade; maior = mais barata) ≥ este valor")
            excl_bancos = st.checkbox("Excluir bancos", value=True, key="scr_excl_bancos")
            st.caption(
                "Filtros de múltiplos vão para a API; os **scores de qualidade e "
                "preço** e a exclusão de bancos são aplicados localmente."
            )

        # Salvar filtro atual
        st.markdown("---")
        _col_nome, _col_salvar = st.columns([3, 1])
        with _col_nome:
            _nome_filtro = st.text_input("Nome para salvar:", placeholder="ex: Minha estratégia",
                                         key="scr_nome_filtro", label_visibility="collapsed")
        with _col_salvar:
            if st.button("💾 Salvar filtro", key="btn_salvar_filtro", use_container_width=True):
                _nome = _nome_filtro.strip()
                if _nome:
                    st.session_state.screener_filtros[_nome] = {
                        "roe_min": roe_min, "pl_max": pl_max, "nd_max": nd_max,
                        "mg_min": mg_min, "ev_max": ev_max,
                        "qual_min": qual_min, "price_min": price_min,
                        "excl_bancos": excl_bancos,
                    }
                    _save_all()
                    st.success(f"Filtro '{_nome}' salvo!")

    # ── Botão busca ────────────────────────────────────────────
    if not st.button("🔍 Buscar na B3", use_container_width=True, key="btn_scr_buscar"):
        return

    with st.spinner("Buscando ações na B3…"):
        result = api.get_screener(
            limit=20,
            roe_min=roe_min if roe_min > 0 else None,
            pl_max=pl_max if pl_max < 50 else None,
            net_debt_ebitda_max=nd_max if nd_max < 5 else None,
            ebitda_margin_min=mg_min if mg_min > 0 else None,
            ev_ebitda_max=ev_max if ev_max < 20 else None,
        )

    if not result or not result.get("data"):
        st.warning("Nenhuma ação encontrada com esses filtros.")
        return

    total = result.get("total", 0)

    # Converte resultado do screener para formato do app e calcula score
    enriched_scr: list[dict] = []
    for raw in result["data"]:
        t_remap = SECTOR_REMAP.get(raw.get("ticker", ""), raw.get("sector", ""))
        _sec = t_remap
        if excl_bancos and sc.is_bank(_sec):
            continue
        stock = {
            "ticker":           raw.get("ticker", ""),
            "trade_name":       raw.get("corporate_name", ""),
            "corporate_name":   raw.get("corporate_name", ""),
            "sector":           _sec,
            "close_price":      raw.get("close_price"),
            "daily_change_pct": None,
            "reference_date":   raw.get("reference_date"),
            "net_debt_ebitda":  raw.get("net_debt_ebitda"),
            "roe":              raw.get("roe"),
            "ev_ebitda":        raw.get("ev_ebitda"),
            "pl":               raw.get("pl"),
            "ebitda_margin":    raw.get("ebitda_margin"),
            "cagr_earnings_5y": raw.get("cagr_earnings_5y"),
            "cagr_revenue_5y":  raw.get("cagr_revenue_5y"),
            "p_fcf":            None,
            "dividend_yield":   raw.get("dividend_yield"),
            "liquidity":        None,
            "pvp":              raw.get("pvp"),
            "net_margin":       raw.get("net_margin"),
        }
        scr_scores = sc.calculate_scores(stock)
        _q, _p = scr_scores.get("quality"), scr_scores.get("price")
        if qual_min > 0 and (_q is None or _q < qual_min):
            continue
        if price_min > 0 and (_p is None or _p < price_min):
            continue
        enriched_scr.append({**stock, "scores": scr_scores})

    _crit = []
    if qual_min > 0:
        _crit.append(f"Score qualidade ≥ {qual_min}")
    if price_min > 0:
        _crit.append(f"Score preço ≥ {price_min}")
    _crit_str = (" com " + " e ".join(_crit)) if _crit else ""
    st.info(
        f"**{total}** ações analisadas pela Bolsai. "
        f"Exibindo **{len(enriched_scr)}**{_crit_str}"
        + (" (bancos excluídos)." if excl_bancos else ".")
    )

    if not enriched_scr:
        return

    enriched_scr = _dedup_enriched(enriched_scr)
    display_df, class_df = _build_table(enriched_scr)
    styled = _apply_styles(display_df.set_index("Ticker"), class_df.set_index("Ticker"))
    st.dataframe(styled, use_container_width=True, height=min(42 + 35 * len(enriched_scr), 420))

    col_add, _ = st.columns([1, 3])
    with col_add:
        if st.button("➕ Adicionar todas à lista atual", use_container_width=True, key="scr_add_all"):
            added, erros = [], []
            with st.spinner("Buscando dados completos…"):
                for e in enriched_scr:
                    t = e["ticker"]
                    if t not in st.session_state.acoes:
                        err = _fetch_ticker(t)
                        if err:
                            erros.append(f"{t}: {err}")
                        else:
                            added.append(t)
            st.session_state.flash_success = f"Adicionadas à {st.session_state.lista_atual}: {', '.join(added)}" if added else ""
            st.session_state.flash_errors = erros
            st.rerun()


# ────────────────────────────────────────────────────────────────
# Tela de seleção de usuário
# ────────────────────────────────────────────────────────────────

@functools.lru_cache(maxsize=1)
def _login_dotfield_uri() -> str:
    """Gera um campo de pontos em ONDA concentrado à direita (estilo Empiricus):
    cortina vertical ondulada que esmaece para a esquerda. Retorna data-URI SVG."""
    import urllib.parse
    W, H, STEP = 1440, 900, 26
    dots = []
    for iy in range(0, H // STEP + 2):
        for ix in range(0, W // STEP + 2):
            x, y = ix * STEP, iy * STEP
            # borda esquerda ondulada da cortina (concava no meio)
            left_edge = W * 0.50 + 150 * math.sin(y / H * math.pi * 1.15)
            d = x - left_edge
            if d <= 0:
                continue
            # opacidade cresce para a direita (satura) + leve fade no topo/base
            op = min(0.44, d / 320) * (1 - abs(y - H / 2) / (H * 0.62))
            if op <= 0.03:
                continue
            col = "#34d399" if (ix + iy) % 5 else "#7dd3fc"   # esmeralda + toque azul-céu
            dots.append(f'<circle cx="{x}" cy="{y}" r="1.15" fill="{col}" opacity="{op:.3f}"/>')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
           f'preserveAspectRatio="xMidYMid slice">{"".join(dots)}</svg>')
    return "data:image/svg+xml," + urllib.parse.quote(svg)


def _tela_selecao_usuario() -> None:
    """Exibida antes do app quando nenhum usuário está selecionado."""
    st.markdown(
        "<style>[data-testid='stAppViewContainer']{background:"
        # glow esmeralda no topo
        "radial-gradient(900px 480px at 50% -10%, rgba(52,211,153,0.10), transparent 62%),"
        "#0b0e14;}"
        # campo de pontos em onda (estilo Empiricus) atrás de tudo, à direita
        "[data-testid='stAppViewContainer']::before{content:'';position:fixed;inset:0;"
        "pointer-events:none;z-index:0;"
        f"background-image:url(\"{_login_dotfield_uri()}\");"
        "background-size:cover;background-position:center right;}"
        "</style>", unsafe_allow_html=True)
    _, col, _ = st.columns([1, 2.2, 1])
    with col:
        st.markdown(
            "<div style='text-align:center;padding:56px 0 4px'>"
            "<div style='display:inline-flex;width:70px;height:70px;border-radius:18px;"
            "background:#0c2a23;border:1px solid #1f4a3d;align-items:center;justify-content:center;"
            "font-size:2.1rem;margin-bottom:18px'>📈</div>"
            "<h1 style='margin:0;font-size:2.1rem;letter-spacing:-0.02em'>Análise Fundamentalista B3</h1>"
            "<p style='color:#8b94a7;margin:12px 0 0;font-size:1.02rem'>"
            "Ações e FIIs · scores de qualidade e preço · valuation por setor · alertas</p>"
            "</div>", unsafe_allow_html=True)
        st.markdown(
            "<div style='display:flex;gap:8px;justify-content:center;flex-wrap:wrap;margin:20px 0 28px'>"
            + "".join(
                f"<span style='font-size:0.8rem;color:#a7f3d0;background:#0c2a23;"
                f"border:1px solid #1f4a3d;padding:5px 13px;border-radius:999px'>{t}</span>"
                for t in ["Qualidade × Preço", "Valuation por setor", "Carteira & FIIs", "Alertas in-app"])
            + "</div>", unsafe_allow_html=True)
        with st.container(border=True):
            st.markdown("#### 👤 Quem é você?")
            st.caption("Selecione seu perfil para acessar sua carteira personalizada.")
            usuario = st.selectbox(
                "Usuário", USUARIOS, key="sel_usuario_login",
                label_visibility="collapsed",
            )
            if st.button("Entrar  →", key="btn_entrar", type="primary", use_container_width=True):
                st.session_state.usuario_atual = usuario
                st.rerun()
        st.markdown(
            "<p style='text-align:center;color:#5b6473;font-size:0.78rem;margin-top:22px'>"
            "Dados via Bolsai Pro · uso pessoal/educacional · não é recomendação de investimento</p>",
            unsafe_allow_html=True)


# ────────────────────────────────────────────────────────────────
# Sidebar
# ────────────────────────────────────────────────────────────────

def _sidebar_atualizacao() -> None:
    """Seção de Atualização (refresh Ações/FIIs/Tudo + quota). Renderiza na sidebar."""
    with st.sidebar:
        st.markdown("### Atualização")

        _now = datetime.now(timezone.utc)
        newest_update = None   # mais recente (= "última atualização")
        _n_stale = 0           # quantas posições estão com >24h
        for entry in st.session_state.acoes.values():
            ua = entry.get("updated_at")
            if not ua:
                _n_stale += 1
                continue
            try:
                dt = datetime.fromisoformat(ua)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if newest_update is None or dt > newest_update:
                    newest_update = dt
                if (_now - dt).total_seconds() / 3600 >= 24:
                    _n_stale += 1
            except Exception:
                _n_stale += 1

        if newest_update:
            ua_str = _fmt_updated(newest_update.isoformat())
            cor = _staleness_color(newest_update.isoformat())
            st.markdown(
                f"<span style='color:{cor};font-size:0.85rem'>"
                f"Última atualização: {ua_str}</span>",
                unsafe_allow_html=True,
            )
            if _n_stale:
                st.caption(f"🟠 {_n_stale} ação(ões) com dados >24h — não atualizaram "
                           "(erro da API ou limite). Tente **Atualizar** de novo.")
        else:
            st.caption("Nenhum dado carregado ainda.")

        _fiis_atual_sb = st.session_state.fiis_listas.get(st.session_state.lista_fii_atual, {})

        def _refresh_fiis(save: bool = True) -> None:
            """Re-busca os FIIs da lista ativa, preservando posições."""
            _fetch_fii.clear()
            for _tt in list(_fiis_atual_sb.keys()):
                with st.spinner(f"Atualizando {_tt}…"):
                    _nd = _fetch_fii(_tt)
                if not _nd.get("error"):
                    _old = _fiis_atual_sb.get(_tt, {})
                    _fiis_atual_sb[_tt] = {**_nd,
                                           "qtd": _old.get("qtd", 0),
                                           "preco_medio": _old.get("preco_medio", 0.0),
                                           "data_compra": _old.get("data_compra", "")}
            if save:
                _save_all()

        if st.button("🔄 Atualizar Ações", use_container_width=True,
                     disabled=not st.session_state.acoes):
            with st.spinner("Atualizando ações…"):
                erros = _update_all()
            st.session_state.flash_errors = erros
            if not erros:
                st.session_state.flash_success = "Ações atualizadas com sucesso!"
            st.rerun()

        if st.button("🔄 Atualizar FIIs", use_container_width=True,
                     disabled=not _fiis_atual_sb,
                     help=f"Atualiza os FIIs da lista '{st.session_state.lista_fii_atual}'"):
            _refresh_fiis()
            st.rerun()

        if st.button("🔄 Atualizar Tudo", use_container_width=True, type="primary",
                     disabled=not (st.session_state.acoes or _fiis_atual_sb),
                     help="Atualiza ações e FIIs de uma vez"):
            with st.spinner("Atualizando ações…"):
                erros = _update_all() if st.session_state.acoes else []
            if _fiis_atual_sb:
                _refresh_fiis(save=False)
            _save_all()
            st.session_state.flash_errors = erros
            if not erros:
                st.session_state.flash_success = "Ações e FIIs atualizados!"
            st.rerun()

        with st.expander("📊 Uso da API (quota)"):
            usage = api.check_api_usage()
            if usage:
                used = usage.get("used_today", 0)
                limit = usage.get("daily_limit", 200)
                remaining = usage.get("remaining", limit - used)
                st.progress(used / limit if limit else 0,
                            text=f"{used}/{limit} requisições hoje")
                st.caption(f"Restantes: {remaining}")
            else:
                st.caption("Indisponível (verifique a API Key).")


def _sidebar():
    with st.sidebar:
        _u = st.session_state.get("usuario_atual", "")
        col_u, col_troca = st.columns([3, 2])
        col_u.markdown(f"**Olá, {_u} 👋**")
        if col_troca.button("🔄 Trocar", key="btn_trocar_usuario", use_container_width=True, help="Trocar usuário"):
            for _k in [
                "usuario_atual", "todas_listas", "lista_atual", "acoes",
                "screener_filtros", "selected_ticker", "fiis_listas",
                "lista_fii_atual", "selected_fii", "confirm_del_lista",
                "confirm_del_fii_lista", "alertas",
            ]:
                st.session_state.pop(_k, None)
            st.rerun()

        st.markdown("# 📈 Análise B3")
        st.caption("Análise fundamentalista de ações brasileiras")

        # ── Navegação por área ─────────────────────────────────
        _AREAS = ["📊 Ações", "🏢 FIIs", "🔎 Screener", "🌐 Ciclo", "🔔 Alertas"]
        _cur_area = st.session_state.get("area", _AREAS[0])
        st.session_state.area = st.radio(
            "Navegação", _AREAS,
            index=_AREAS.index(_cur_area) if _cur_area in _AREAS else 0,
            label_visibility="collapsed",
        )
        _badge_n = st.session_state.get("_alert_badge_n", 0)
        if _badge_n:
            st.markdown(
                f"<div style='background:#1b5e20;color:#fff;padding:5px 10px;border-radius:6px;"
                f"font-size:0.85rem;margin:2px 0 6px'>🔔 {_badge_n} alerta(s) disparado(s) "
                f"— veja em <b>Alertas</b></div>", unsafe_allow_html=True)
        st.divider()

        # ── Status da API (discreto) ───────────────────────────
        api_key = api._get_api_key()
        if api_key:
            st.markdown(
                "<span style='color:#9e9e9e;font-size:0.8rem'>🔑 API conectada</span>",
                unsafe_allow_html=True,
            )
        else:
            st.error(
                "**BOLSAI_API_KEY não encontrada.**\n\n"
                "No Streamlit Cloud: **Settings → Secrets** → `BOLSAI_API_KEY = \"sk_…\"`",
                icon="🚨",
            )

        # ── Diagnóstico (apenas em DEBUG_MODE=true) ────────────
        import os as _os
        if _os.environ.get("DEBUG_MODE", "").lower() == "true":
            with st.expander("🔧 Diagnóstico", expanded=False):
                if st.session_state.debug_log:
                    for line in st.session_state.debug_log:
                        st.markdown(f"`{line}`")
                    if st.session_state.debug_raw_fund:
                        st.markdown("**JSON /fundamentals:**")
                        st.json(st.session_state.debug_raw_fund, expanded=False)
                    if st.button("Limpar log", key="clear_debug"):
                        st.session_state.debug_log = []
                        st.session_state.debug_raw_fund = None
                        st.rerun()
                else:
                    st.caption("Nenhuma operação registrada.")

        # ── Mensagens flash ────────────────────────────────────
        if st.session_state.flash_success:
            _ph = st.empty()
            _ph.success(st.session_state.flash_success)
            st.session_state.flash_success = ""
            time.sleep(3)
            _ph.empty()
        _errs = st.session_state.flash_errors
        if _errs:
            if len(_errs) > 3:
                st.warning(f"⚠ {len(_errs)} ticker(s) falharam (erro temporário da API). "
                           "Os valores anteriores foram mantidos — tente **Atualizar** de novo.")
                with st.expander("Ver detalhes"):
                    for err in _errs:
                        st.caption(err)
            else:
                for err in _errs:
                    st.error(err)
        st.session_state.flash_errors = []

        # ── Fora da área Ações: mostra só a Atualização e encerra ──
        if st.session_state.get("area", "📊 Ações") != "📊 Ações":
            _sidebar_atualizacao()
            return

        st.divider()

        # ── Seletor de lista ──────────────────────────────────
        listas_keys = list(st.session_state.todas_listas.keys())
        cur_idx = listas_keys.index(st.session_state.lista_atual) if st.session_state.lista_atual in listas_keys else 0

        chosen_lista = st.selectbox(
            "Lista", listas_keys, index=cur_idx,
            key="sidebar_lista_sel", label_visibility="collapsed",
        )

        # Detecta mudança de lista pelo selectbox
        if chosen_lista != st.session_state.lista_atual:
            _switch_list(chosen_lista)
            st.rerun()

        with st.expander("⚙️ Gerenciar listas"):
            _nome_input = st.text_input(
                "Nome da nova lista", key="nova_lista_nome_input",
                placeholder="ex: Dividendos, Longo Prazo…",
                label_visibility="collapsed",
            )
            if st.button("➕ Criar lista", key="btn_criar_lista", use_container_width=True):
                _nome = _nome_input.strip()
                if not _nome:
                    st.warning("Digite um nome.")
                elif _nome in st.session_state.todas_listas:
                    st.warning("Já existe uma lista com esse nome.")
                else:
                    st.session_state.todas_listas[_nome] = {}
                    _save_all()
                    _switch_list(_nome)
                    st.rerun()

            st.divider()
            _can_del = len(st.session_state.todas_listas) > 1
            if not _can_del:
                st.caption("Crie outra lista antes de excluir esta.")
            else:
                if not st.session_state.get("confirm_del_lista"):
                    if st.button(
                        f"🗑 Excluir lista atual  ({st.session_state.lista_atual})",
                        key="btn_del_lista_ask", use_container_width=True,
                    ):
                        st.session_state.confirm_del_lista = True
                        st.rerun()
                else:
                    st.warning(f"Excluir **{st.session_state.lista_atual}** e todas as ações nela?")
                    _cd1, _cd2 = st.columns(2)
                    with _cd1:
                        if st.button("✅ Confirmar", key="btn_del_lista_ok", use_container_width=True):
                            _lista_del = st.session_state.lista_atual
                            del st.session_state.todas_listas[_lista_del]
                            _nova = list(st.session_state.todas_listas.keys())[0]
                            _switch_list(_nova)
                            _save_all()
                            st.session_state.confirm_del_lista = False
                            st.rerun()
                    with _cd2:
                        if st.button("✗ Cancelar", key="btn_del_lista_cancel", use_container_width=True):
                            st.session_state.confirm_del_lista = False
                            st.rerun()

        # Botão especial da lista "🔍 Pesquisa"
        if st.session_state.lista_atual == "🔍 Pesquisa" and st.session_state.acoes:
            if st.button("🧹 Limpar tudo da Pesquisa", use_container_width=True, key="btn_clear_pesq"):
                st.session_state.acoes.clear()
                _save_all()
                st.rerun()

        st.divider()

        # ── Adicionar tickers ──────────────────────────────────
        st.markdown("### Adicionar Ações")
        tickers_input = st.text_input(
            "Ticker(s)",
            placeholder="Ex: PETR4, VALE3, ITUB4",
            help="Separe múltiplos tickers por vírgula ou espaço.",
        )

        if st.button("➕ Adicionar e Buscar", use_container_width=True):
            tickers_raw = tickers_input.replace(",", " ").split()
            if not tickers_raw:
                st.warning("Digite ao menos um ticker.")
            else:
                st.session_state.debug_log = []
                st.session_state.flash_errors = []
                st.session_state.flash_success = ""

                erros: list[str] = []
                adicionados: list[str] = []

                with st.spinner("Buscando dados na API Bolsai…"):
                    for t in tickers_raw:
                        t = t.strip().upper()
                        if not t:
                            continue
                        try:
                            err = _fetch_ticker(t)
                        except Exception as exc:
                            err = f"Exceção inesperada em {t}: {exc}"
                            st.session_state.debug_log.append(f"❌ {err}")

                        if err:
                            erros.append(f"{t}: {err}")
                        else:
                            adicionados.append(t)

                if adicionados:
                    st.session_state.flash_success = (
                        f"Adicionado(s): {', '.join(adicionados)}"
                    )
                st.session_state.flash_errors = erros
                st.rerun()

        # ── Busca por setor ────────────────────────────────────
        with st.expander("🏭 Buscar por Setor", expanded=False):
            try:
                sectors_list = api.get_sectors() or []
            except Exception:
                sectors_list = []
            sector_opts = ["— Selecione —"] + sorted(sectors_list)
            chosen_sector = st.selectbox(
                "Setor", sector_opts, key="sidebar_sector_sel",
                label_visibility="collapsed",
            )
            if not sectors_list:
                st.caption("Setores indisponíveis no momento (limite de API ou "
                           "instabilidade). Tente mais tarde.")
            if chosen_sector != "— Selecione —":
                with st.spinner("Buscando empresas…"):
                    sec_result = api.get_companies_by_sector(chosen_sector, limit=20)
                if sec_result and sec_result.get("data"):
                    cos = sec_result["data"]
                    st.caption(f"{sec_result.get('total', len(cos))} empresas — mostrando {len(cos)}")
                    to_add: list[str] = []
                    for co in cos:
                        tk = co.get("ticker_primary", "")
                        nm = co.get("trade_name") or co.get("corporate_name", "")
                        already = tk in st.session_state.acoes
                        checked = st.checkbox(
                            f"{tk} — {nm[:28]}",
                            value=already,
                            disabled=already,
                            key=f"sec_cb_{tk}",
                        )
                        if checked and not already:
                            to_add.append(tk)
                    if to_add:
                        if st.button("➕ Adicionar selecionadas", use_container_width=True, key="sec_add_btn"):
                            added2, erros2 = [], []
                            with st.spinner("Buscando dados…"):
                                for tk in to_add:
                                    err2 = _fetch_ticker(tk)
                                    if err2:
                                        erros2.append(f"{tk}: {err2}")
                                    else:
                                        added2.append(tk)
                            st.session_state.flash_success = f"Adicionadas: {', '.join(added2)}" if added2 else ""
                            st.session_state.flash_errors = erros2
                            st.rerun()
                else:
                    st.caption("Nenhuma empresa encontrada para este setor.")

    # ── Atualização (depois de lista/adicionar/setor) ──────────
    _sidebar_atualizacao()

    with st.sidebar:
        st.divider()

        # ── Lista de ações salvas ──────────────────────────────
        _n = len(st.session_state.acoes)
        st.markdown(f"### {st.session_state.lista_atual} ({_n})")
        if not st.session_state.acoes:
            st.caption("Nenhuma ação nesta lista. Adicione acima.")
        else:
            for ticker, entry in list(st.session_state.acoes.items()):
                data = entry.get("data", {})
                _sc_side = sc.calculate_scores({**data})
                _q_side, _p_side = _sc_side.get("quality"), _sc_side.get("price")
                _q_str = f"{_q_side:.0f}" if _q_side is not None else "—"
                _p_str = f"{_p_side:.0f}" if _p_side is not None else "—"

                col_a, col_b, col_c = st.columns([3, 2, 1])
                with col_a:
                    if st.button(ticker, key=f"sel_{ticker}", use_container_width=True):
                        st.session_state.selected_ticker = ticker
                with col_b:
                    st.markdown(
                        f"<span style='font-size:0.8rem'>"
                        f"<span style='color:{_score_color_hex(_q_side)}'>Q {_q_str}</span> · "
                        f"<span style='color:{_score_color_hex(_p_side)}'>P {_p_str}</span></span>",
                        unsafe_allow_html=True,
                    )
                with col_c:
                    if st.button("✕", key=f"rm_{ticker}", help=f"Remover {ticker}"):
                        del st.session_state.acoes[ticker]
                        _save_all()
                        if st.session_state.selected_ticker == ticker:
                            st.session_state.selected_ticker = None
                        st.rerun()


# ────────────────────────────────────────────────────────────────
# Aba FIIs
# ────────────────────────────────────────────────────────────────

_FII_TYPE_LABELS = {
    "papel":        "📄 Papel",
    "tijolo":       "🧱 Tijolo",
    "hibrido":      "🔀 Híbrido",
    "fof":          "🏗 FOF",
    "desenvolvimento": "🏗 Desenvolvimento",
}

_FII_COL_HEADERS = [
    "Ticker", "Nome", "Tipo", "Preço", "DY TTM", "P/VP",
    "Vacância", "Inadimp.", "Liquidez", "Qualidade", "Preço*", "Diagnóstico",
]

@st.cache_data(ttl=3600)
def _fetch_fii(ticker: str) -> dict:
    try:
        return api.get_all_fii_data(ticker.strip().upper())
    except Exception as e:
        return {"ticker": ticker.upper(), "error": str(e)}


def _fmt_fii_val(key: str, fii: dict):
    """Formata o valor de exibição para a tabela de FIIs."""
    v = fii.get(key)
    if key == "close_price":
        return f"R$ {v:.2f}" if v is not None else "N/D"
    if key == "dividend_yield":
        return f"{v:.1f}%" if v is not None else "N/D"
    if key == "pvp":
        return f"{v:.2f}x" if v is not None else "N/D"
    if key in ("vacancy_pct", "delinquency_pct"):
        return f"{v:.1f}%" if v is not None else "N/D"
    if key == "liquidity":
        if v is None:
            return "N/D"
        if v >= 1_000_000:
            return f"R$ {v/1_000_000:.1f}M"
        if v >= 1_000:
            return f"R$ {v/1_000:.0f}k"
        return f"R$ {v:.0f}"
    return "N/D"


def _fii_table_html(fiis_data: list[dict]) -> str:
    """Renderiza tabela de FIIs com células coloridas por classificação."""
    th = "padding:9px 10px;color:#8b94a7;border-bottom:1px solid #232b3a;background:#151b26;font-weight:600;font-size:0.72rem;text-transform:uppercase;letter-spacing:0.04em"
    html = "<div style='overflow-x:auto'>"
    html += "<table style='width:100%;border-collapse:collapse;font-size:0.87rem'>"
    html += "<thead><tr>"
    for h in _FII_COL_HEADERS:
        html += f"<th style='{th};text-align:center'>{h}</th>"
    html += "</tr></thead><tbody>"

    _calc_scores = getattr(sf, "calculate_fii_scores", None)
    for i, fii in enumerate(fiis_data):
        row_bg = "#0e1117" if i % 2 == 0 else "#131629"
        scf = _calc_scores(fii) if _calc_scores else {}
        html += f"<tr style='background:{row_bg}'>"

        # Ticker
        html += f"<td style='padding:6px 10px;text-align:center;font-weight:700;color:#90caf9'>{fii.get('ticker','')}</td>"
        # Nome (truncado)
        nome = (fii.get("name") or "")[:30]
        html += f"<td style='padding:6px 10px;color:#c8cce0'>{nome}</td>"
        # Tipo
        ft = (fii.get("fund_type") or "").lower()
        tipo_lbl = _FII_TYPE_LABELS.get(ft, fii.get("fund_type") or "N/D")
        html += f"<td style='padding:6px 10px;text-align:center;color:#c8cce0'>{tipo_lbl}</td>"

        # Preço
        price_disp = _fmt_fii_val("close_price", fii)
        html += f"<td style='padding:6px 10px;text-align:center;color:#e8eaf6'>{price_disp}</td>"

        # DY TTM
        dy_cls, dy_disp = sf.classify_fii_dy(fii.get("dividend_yield"))
        dy_bg = BG_COLORS.get(dy_cls, "#37474f")
        html += f"<td style='padding:6px 10px;text-align:center;background:{dy_bg};border-radius:4px'>{dy_disp}</td>"

        # P/VP
        pvp_cls, pvp_disp = sf.classify_fii_pvp(fii.get("pvp"))
        pvp_bg = BG_COLORS.get(pvp_cls, "#37474f")
        html += f"<td style='padding:6px 10px;text-align:center;background:{pvp_bg};border-radius:4px'>{pvp_disp}</td>"

        # Vacância e Inadimplência — N/A para papel (não tem imóvel físico)
        _is_paper_row = scf.get("paper", False)
        if _is_paper_row:
            for _ in range(2):
                html += ("<td style='padding:6px 10px;text-align:center;background:#37474f;"
                         "border-radius:4px;color:#b0bec5;font-size:0.8rem'>N/A</td>")
        else:
            vac_cls, vac_disp = sf.classify_fii_vacancy(fii.get("vacancy_pct"))
            vac_bg = BG_COLORS.get(vac_cls, "#37474f")
            html += f"<td style='padding:6px 10px;text-align:center;background:{vac_bg};border-radius:4px'>{vac_disp}</td>"
            ina_cls, ina_disp = sf.classify_fii_delinquency(fii.get("delinquency_pct"))
            ina_bg = BG_COLORS.get(ina_cls, "#37474f")
            html += f"<td style='padding:6px 10px;text-align:center;background:{ina_bg};border-radius:4px'>{ina_disp}</td>"

        # Liquidez
        liq_cls, liq_disp = sf.classify_fii_liquidity(fii.get("liquidity"))
        liq_bg = BG_COLORS.get(liq_cls, "#37474f")
        html += f"<td style='padding:6px 10px;text-align:center;background:{liq_bg};border-radius:4px'>{liq_disp}</td>"

        # Qualidade (tijolo) — papel não tem nota
        _q, _p = scf.get("quality"), scf.get("price")
        _diag = scf.get("diagnosis")
        if scf.get("paper"):
            html += ("<td style='padding:6px 10px;text-align:center;background:#37474f;"
                     "border-radius:4px;color:#cfd8dc;font-size:0.8rem'>papel</td>")
        else:
            _qbg = _score_color_hex(_q) if _q is not None else "#37474f"
            _qs = f"{_q:.0f}" if _q is not None else "—"
            html += (f"<td style='padding:6px 10px;text-align:center;background:{_qbg};"
                     f"border-radius:4px;font-weight:700'>{_qs}</td>")
        # Preço (atratividade)
        _pbg = _score_color_hex(_p) if _p is not None else "#37474f"
        _ps = f"{_p:.0f}" if _p is not None else "—"
        html += (f"<td style='padding:6px 10px;text-align:center;background:{_pbg};"
                 f"border-radius:4px;font-weight:700'>{_ps}</td>")
        # Diagnóstico
        _dbg = _diag["color"] if _diag else "#37474f"
        _dlbl = _diag["label"] if _diag else "—"
        html += (f"<td style='padding:6px 10px;text-align:center;background:{_dbg};"
                 f"border-radius:4px;font-weight:600;font-size:0.82rem'>{_dlbl}</td>")

        html += "</tr>"

    html += "</tbody></table></div>"
    return html


_FII_IND_LABELS = {
    "dividend_yield": "DY TTM",
    "pvp":            "P/VP",
    "vacancy_pct":    "Vacância",
    "liquidity":      "Liquidez",
    "delinquency_pct": "Inadimplência",
}


def _show_fii_detail(fii: dict) -> None:
    # getattr p/ resiliência ao hot-reload do Streamlit (score_fii em cache
    # sem a função nova → mostra aviso de reboot em vez de quebrar).
    _calc = getattr(sf, "calculate_fii_scores", None)
    if _calc is None:
        st.warning("Atualize o app: faça **Reboot** (Manage app → ⋮ → Reboot) "
                   "para carregar os scores novos de FII.")
        return
    scores = _calc(fii)
    q, p, diag = scores.get("quality"), scores.get("price"), scores.get("diagnosis")
    paper = scores.get("paper", False)

    st.markdown(f"### {fii.get('ticker')} — {fii.get('name','')}")
    ft = fii.get("fund_type") or ""
    seg = fii.get("segment") or ""
    st.caption(f"{_FII_TYPE_LABELS.get(ft.lower(), ft)}  •  {seg}")

    # ── Diagnóstico Qualidade × Preço ──────────────────────────
    if diag:
        st.markdown(
            f"<div style='display:inline-block;background:{diag['color']};padding:6px 16px;"
            f"border-radius:999px;color:#fff;font-size:1.05rem;font-weight:600;margin:6px 0'>"
            f"{('💰 ' if paper else '')}{diag['label']}</div>",
            unsafe_allow_html=True)
    cqp = st.columns(2)
    if paper:
        cqp[0].metric("Qualidade", "N/A — papel")
    else:
        cqp[0].metric("Qualidade", f"{q:.0f}/100" if q is not None else "—")
        if diag and diag.get("quality_tier"):
            cqp[0].caption(f"**{diag['quality_tier']}**")
    cqp[1].metric("Preço (atratividade)", f"{p:.0f}/100" if p is not None else "—")
    if diag and diag.get("price_tier"):
        cqp[1].caption(f"**{diag['price_tier']}**")

    # ── Alertas de robustez + disclaimer de papel ──────────────
    for _alert in scores.get("alerts", []):
        st.warning(_alert)
    if paper:
        st.info(
            "📋 **FII de papel — qualidade não pontuada.** Os dados da Bolsai não cobrem "
            "risco de crédito (inadimplência/rating/LTV dos CRIs), que é o que realmente "
            "importa aqui. Os alertas acima sinalizam problemas estruturais, mas **não "
            "substituem a leitura do relatório gerencial** do fundo."
        )

    st.divider()

    # ── Métricas principais (oculta vacância/inadimplência p/ papel) ──
    price = fii.get("close_price")
    chg = fii.get("daily_change_pct")
    dy = fii.get("dividend_yield")
    pvp = fii.get("pvp")
    if paper:
        cols_m = st.columns(4)
        cols_m[0].metric("Preço", f"R$ {price:.2f}" if price else "N/D",
                         delta=f"{chg:+.2f}%" if chg is not None else None)
        cols_m[1].metric("DY TTM", f"{dy:.1f}%" if dy is not None else "N/D")
        cols_m[2].metric("P/VP", f"{pvp:.2f}x" if pvp is not None else "N/D")
        _liq = fii.get("liquidity")
        cols_m[3].metric("Liquidez/dia", _fmt_mcap(_liq) if _liq else "N/D")
    else:
        cols_m = st.columns(5)
        cols_m[0].metric("Preço", f"R$ {price:.2f}" if price else "N/D",
                         delta=f"{chg:+.2f}%" if chg is not None else None)
        cols_m[1].metric("DY TTM", f"{dy:.1f}%" if dy is not None else "N/D")
        cols_m[2].metric("P/VP", f"{pvp:.2f}x" if pvp is not None else "N/D")
        vac = fii.get("vacancy_pct")
        cols_m[3].metric("Vacância", f"{vac:.1f}%" if vac is not None else "N/D")
        ina = fii.get("delinquency_pct")
        cols_m[4].metric("Inadimplência", f"{ina:.1f}%" if ina is not None else "N/D")

    st.divider()

    # ── Composição dos scores (Qualidade × Preço) ──────────────
    with st.expander("📊 Composição dos scores", expanded=True):
        _grupos = [("💰 Preço (atratividade)", scores.get("breakdown_price", {}))]
        if not paper:
            _grupos.insert(0, ("🏅 Qualidade", scores.get("breakdown_quality", {})))
        for _titulo, _bd in _grupos:
            if not _bd:
                continue
            st.markdown(f"**{_titulo}**")
            for ind, binfo in _bd.items():
                _sci = binfo.get("score")
                _sv = "—" if _sci is None else f"{_sci:.0f}/100"
                _raw = fii.get(ind)
                if ind in ("dividend_yield", "vacancy_pct", "delinquency_pct"):
                    _disp = f"{_raw:.1f}%" if _raw is not None else "N/D"
                elif ind == "pvp":
                    _disp = f"{_raw:.2f}x" if _raw is not None else "N/D"
                elif ind == "liquidity":
                    _disp = _fmt_mcap(_raw) if _raw else "N/D"
                else:
                    _disp = str(_raw) if _raw is not None else "N/D"
                st.caption(
                    f"{_FII_IND_LABELS.get(ind, ind)}: **{_disp}** · "
                    f"pontuação {_sv} · peso {binfo['weight']*100:.0f}%")

    # Dados complementares
    with st.expander("🏢 Dados do fundo", expanded=False):
        _nav = fii.get("net_asset_value")
        _shares = fii.get("shares_outstanding")
        _prop = fii.get("property_count")
        _area = fii.get("total_area_sqm")
        _adm = fii.get("administrator")
        _mgmt = fii.get("management_type")
        _inception = fii.get("inception_date")
        _liq = fii.get("liquidity")

        rows = [
            ("Patrimônio Líquido",   f"R$ {_nav/1e6:.0f} mi" if _nav else "N/D"),
            ("Cotas emitidas",       f"{_shares:,.0f}".replace(",", ".") if _shares else "N/D"),
            ("Liquidez média (52s)", _fmt_fii_val("liquidity", fii)),
            ("Nº de imóveis",        str(_prop) if _prop is not None else "N/D"),
            ("Área total (m²)",      f"{_area:,.0f}".replace(",", ".") if _area else "N/D"),
            ("Administrador",        _adm or "N/D"),
            ("Gestão",               _mgmt or "N/D"),
            ("Início",               _inception[:10] if _inception else "N/D"),
        ]
        for lbl, val in rows:
            col_l, col_v = st.columns([2, 3])
            col_l.markdown(f"**{lbl}**")
            col_v.markdown(val)

    # Composição de ativos
    comp = fii.get("asset_composition")
    if comp:
        with st.expander("📂 Composição de ativos", expanded=False):
            if isinstance(comp, list):
                for item in comp:
                    if isinstance(item, dict):
                        nm = item.get("name") or item.get("asset") or str(item)
                        pct = item.get("percentage") or item.get("pct") or item.get("weight")
                        pct_str = f"{pct:.1f}%" if pct is not None else ""
                        st.markdown(f"- **{nm}** {pct_str}")
            elif isinstance(comp, dict):
                for k, v in comp.items():
                    st.markdown(f"- **{k}**: {v}")

    # Top imóveis
    top_props = fii.get("top_properties")
    if top_props:
        with st.expander("🏗 Principais imóveis", expanded=False):
            if isinstance(top_props, list):
                for item in top_props:
                    if isinstance(item, dict):
                        nm = item.get("name") or item.get("property") or str(item)
                        loc = item.get("location") or item.get("city") or ""
                        loc_str = f" — {loc}" if loc else ""
                        pct = item.get("percentage") or item.get("pct")
                        pct_str = f" ({pct:.1f}%)" if pct is not None else ""
                        st.markdown(f"- **{nm}**{loc_str}{pct_str}")


@st.cache_data(ttl=1800)
def _fetch_fii_screener_batch(limit: int = 150) -> list[dict]:
    """Busca lote de FIIs do screener Bolsai e normaliza para nosso formato."""
    try:
        resp = api.get_fii_screener(limit=limit)
        items: list = []
        if resp and isinstance(resp.get("data"), list):
            items = resp["data"]
        else:
            resp2 = api.get_fii_list(limit=limit)
            if resp2 and isinstance(resp2.get("fiis"), list):
                items = resp2["fiis"]
        result = []
        for item in items:
            if not isinstance(item, dict):
                continue
            result.append({
                "ticker":          item.get("ticker") or "",
                "name":            item.get("name") or "",
                "fund_type":       item.get("fund_type") or "",
                "segment":         item.get("segment") or "",
                "close_price":     item.get("close_price"),
                "pvp":             item.get("pvp"),
                "dividend_yield":  item.get("dividend_yield_ttm") or item.get("dividend_yield"),
                "vacancy_pct":     item.get("vacancy_pct"),
                "delinquency_pct": item.get("delinquency_pct"),
                "liquidity":       None,  # não disponível no batch
            })
        return result
    except Exception:
        return []


def _show_fii_screener(fiis_lista_atual: dict) -> None:
    """Screener de FIIs com filtros e tabela colorida."""
    st.markdown("### 🔎 Screener de FIIs")
    st.caption("Filtre FIIs da Bolsai e adicione os melhores à sua lista.")

    with st.expander("⚙️ Filtros", expanded=True):
        c1, c2, c3 = st.columns(3)
        dy_min    = c1.number_input("DY mínimo (%)",      min_value=0.0, max_value=30.0, value=0.0, step=0.5, key="fscr_dy_min")
        pvp_max   = c2.number_input("P/VP máximo",        min_value=0.0, max_value=5.0,  value=2.0, step=0.05, key="fscr_pvp_max")
        pvp_min   = c3.number_input("P/VP mínimo",        min_value=0.0, max_value=5.0,  value=0.0, step=0.05, key="fscr_pvp_min")
        c4, c5, c6 = st.columns(3)
        vac_max   = c4.number_input("Vacância máx. (%)",  min_value=0.0, max_value=100.0, value=30.0, step=1.0, key="fscr_vac_max")
        ina_max   = c5.number_input("Inadimp. máx. (%)",  min_value=0.0, max_value=100.0, value=10.0, step=0.5, key="fscr_ina_max")
        tipo_opcoes_scr = ["Todos"] + list(_FII_TYPE_LABELS.values())
        tipo_scr  = c6.selectbox("Tipo", tipo_opcoes_scr, key="fscr_tipo")
        c7, c8, c9 = st.columns(3)
        qual_min  = c7.number_input(
            "Score qualidade mín.", min_value=0, max_value=100, value=0, step=5,
            key="fscr_qual_min", help="≥ este valor (exclui papel, que não tem nota de qualidade)")
        price_min = c8.number_input(
            "Score preço mín.", min_value=0, max_value=100, value=0, step=5,
            key="fscr_price_min", help="≥ este valor (maior = mais barato/atrativo)")
        with c9:
            st.caption("")
            col_busca, col_limpa = st.columns(2)
            buscar = col_busca.button("🔍 Buscar", key="btn_fscr_buscar", use_container_width=True, type="primary")
            limpar = col_limpa.button("♻ Limpar", key="btn_fscr_limpar", use_container_width=True)

    if limpar:
        _fetch_fii_screener_batch.clear()
        st.rerun()

    if not buscar and "fii_screener_results" not in st.session_state:
        st.info("Configure os filtros e clique **Buscar** para consultar a Bolsai.")
        return

    if buscar:
        with st.spinner("Consultando Bolsai…"):
            all_fiis = _fetch_fii_screener_batch(150)
        st.session_state["fii_screener_results"] = all_fiis

    all_fiis = st.session_state.get("fii_screener_results", [])
    if not all_fiis:
        st.warning("Nenhum FII retornado pela API. Verifique a conexão ou tente novamente.")
        return

    # ── Filtragem local ───────────────────────────────────────────
    filtered = []
    for fii in all_fiis:
        dy  = fii.get("dividend_yield")
        pvp = fii.get("pvp")
        vac = fii.get("vacancy_pct")
        ina = fii.get("delinquency_pct")
        _scf = sf.calculate_fii_scores(fii)
        _q, _p = _scf.get("quality"), _scf.get("price")

        if dy_min > 0 and (dy is None or dy < dy_min):
            continue
        if pvp is not None:
            if pvp > pvp_max:
                continue
            if pvp_min > 0 and pvp < pvp_min:
                continue
        if vac_max < 100 and vac is not None and vac > vac_max:
            continue
        if ina_max < 100 and ina is not None and ina > ina_max:
            continue
        if qual_min > 0 and (_q is None or _q < qual_min):
            continue
        if price_min > 0 and (_p is None or _p < price_min):
            continue
        if tipo_scr != "Todos":
            ft = (fii.get("fund_type") or "").strip()
            lbl = _FII_TYPE_LABELS.get(ft.lower(), ft.capitalize())
            if lbl != tipo_scr:
                continue
        filtered.append(fii)

    st.info(f"**{len(filtered)}** FIIs encontrados de **{len(all_fiis)}** consultados.")

    if not filtered:
        return

    # ── Tabela de resultados ──────────────────────────────────────
    st.markdown(
        _fii_table_html(filtered),
        unsafe_allow_html=True,
    )

    # ── Adicionar à lista atual ───────────────────────────────────
    st.markdown("")
    scr_tickers = [f["ticker"] for f in filtered if f.get("ticker")]
    scr_sel = st.multiselect(
        "Selecione FIIs para adicionar",
        scr_tickers,
        key="fscr_sel_add",
        placeholder="Selecione um ou mais tickers…",
    )
    if st.button("➕ Adicionar selecionados à lista", key="btn_fscr_add", use_container_width=True, disabled=not scr_sel):
        added, erros = [], []
        with st.spinner("Buscando dados completos…"):
            for _t in scr_sel:
                if _t in fiis_lista_atual:
                    continue
                _d = _fetch_fii(_t)
                if _d.get("error"):
                    erros.append(f"{_t}: {_d['error']}")
                else:
                    fiis_lista_atual[_t] = _d
                    added.append(_t)
        _save_all()
        if added:
            st.success(f"Adicionados: {', '.join(added)}")
        if erros:
            for e in erros:
                st.error(e)
        if added:
            st.rerun()


def _show_fii_portfolio_analysis(fiis_dict: dict) -> None:
    """Análise consolidada da carteira de FIIs (posições com qtd > 0)."""
    _calc = getattr(sf, "calculate_fii_scores", None)
    positions = []
    for t, f in fiis_dict.items():
        qtd = int(f.get("qtd", 0) or 0)
        price = f.get("close_price")
        if qtd <= 0 or not price:
            continue
        pm = float(f.get("preco_medio", 0) or 0)
        scf = _calc(f) if _calc else {}
        positions.append({
            "ticker": t, "qtd": qtd, "price": price, "value": qtd * price,
            "preco_medio": pm if pm > 0 else None,
            "pnl_reais": (price - pm) * qtd if pm > 0 else None,
            "pnl_pct":   (price / pm - 1) * 100 if pm > 0 else None,
            "dy": f.get("dividend_yield"), "pvp": f.get("pvp"),
            "vacancy": f.get("vacancy_pct"), "delinquency": f.get("delinquency_pct"),
            "quality": scf.get("quality"), "price_score": scf.get("price"),
            "paper": scf.get("paper", False),
            "daily_change_pct": f.get("daily_change_pct"), "weight": 0.0,
        })
    if not positions:
        return

    st.divider()
    st.markdown("## 📊 Análise da Carteira de FIIs")
    total = sum(p["value"] for p in positions)
    for p in positions:
        p["weight"] = p["value"] / total

    # Valor total + P&L
    col_v, col_pnl = st.columns(2)
    col_v.metric("💰 Valor Total", f"R$ {total:,.0f}".replace(",", "."))
    pnl_pos = [p for p in positions if p.get("pnl_reais") is not None]
    if pnl_pos:
        tot_pnl = sum(p["pnl_reais"] for p in pnl_pos)
        tot_custo = sum((p["preco_medio"] or 0) * p["qtd"] for p in pnl_pos)
        pnl_pct = (tot_pnl / tot_custo * 100) if tot_custo > 0 else None
        _c = "#34d399" if tot_pnl >= 0 else "#f87171"
        _sig = "+" if tot_pnl >= 0 else "-"
        col_pnl.markdown(
            f"<div style='padding:8px 0'><div style='font-size:0.8rem;color:#9ea3b0'>"
            f"💼 Lucro/Prejuízo não realizado</div>"
            f"<div style='font-size:1.5rem;font-weight:700;color:{_c}'>"
            f"{_sig}R$ {abs(tot_pnl):,.0f}".replace(",", ".") +
            (f" <span style='font-size:1rem'>({_sig}{abs(pnl_pct):.1f}%)</span>" if pnl_pct is not None else "")
            + "</div></div>", unsafe_allow_html=True)

    # Indicadores ponderados
    dy_p  = _weighted_avg_portfolio(positions, "dy")
    pvp_p = _weighted_avg_portfolio(positions, "pvp")
    vac_p = _weighted_avg_portfolio(positions, "vacancy")
    ina_p = _weighted_avg_portfolio(positions, "delinquency")
    cA, cB, cC, cD = st.columns(4)
    cA.metric("DY Pond.", f"{dy_p:.1f}%" if dy_p is not None else "N/D",
              help="Dividend Yield médio ponderado pelo valor de cada posição")
    cB.metric("P/VP Pond.", f"{pvp_p:.2f}x" if pvp_p is not None else "N/D")
    cC.metric("Vacância Pond.", f"{vac_p:.1f}%" if vac_p is not None else "N/D",
              help="Só FIIs de tijolo; papel não tem vacância")
    cD.metric("Inadimpl. Pond.", f"{ina_p:.1f}%" if ina_p is not None else "N/D")

    # Qualidade × Preço ponderado + mapa 2×2
    q_p = _weighted_avg_portfolio(positions, "quality")
    p_p = _weighted_avg_portfolio(positions, "price_score")
    if q_p is not None or p_p is not None:
        st.markdown("#### 🎯 Qualidade × Preço da carteira")
        _diag = sf._diagnose_fii(q_p, p_p, paper=(q_p is None)) if hasattr(sf, "_diagnose_fii") else None
        if _diag:
            st.markdown(
                f"<div style='display:flex;align-items:center;gap:10px;margin-bottom:10px'>"
                f"<span style='color:#8b94a7;font-size:0.9rem'>Veredito da carteira:</span>"
                f"<span style='display:inline-block;background:{_diag['color']};padding:5px 16px;"
                f"border-radius:999px;color:#fff;font-size:1.0rem;font-weight:600'>"
                f"{_diag['label']}</span></div>", unsafe_allow_html=True)
        cq, cp = st.columns(2)
        cq.metric("Qualidade Pond.", f"{q_p:.0f}/100" if q_p is not None else "N/D",
                  help="Média ponderada — só FIIs de tijolo (papel não tem nota de qualidade)")
        cp.metric("Preço Pond.", f"{p_p:.0f}/100" if p_p is not None else "N/D")
        _n_paper = sum(1 for p in positions if p["paper"])
        _show_portfolio_quality_price_map(positions)
        if _n_paper:
            st.caption(f"⚠ {_n_paper} FII(s) de papel não aparecem no mapa "
                       "(sem eixo de qualidade) — veja-os na tabela e nos alertas do Detalhe.")


def _fii_list_selector() -> dict:
    """Seletor de lista FII + gerenciar listas (acima das sub-abas). Retorna a lista ativa."""

    # ── Seletor de lista FII ─────────────────────────────────────
    fii_listas_keys = list(st.session_state.fiis_listas.keys())
    cur_fii_idx = (
        fii_listas_keys.index(st.session_state.lista_fii_atual)
        if st.session_state.lista_fii_atual in fii_listas_keys else 0
    )
    chosen_fii_lista = st.selectbox(
        "Lista FII", fii_listas_keys, index=cur_fii_idx, key="fii_lista_sel",
    )
    if chosen_fii_lista != st.session_state.lista_fii_atual:
        st.session_state.lista_fii_atual = chosen_fii_lista
        st.rerun()

    with st.expander("⚙️ Gerenciar listas FII"):
        _fii_nome_in = st.text_input(
            "Nome da nova lista FII", key="nova_fii_lista_input",
            placeholder="ex: FIIs Tijolo, Papel, Diversificado…",
            label_visibility="collapsed",
        )
        if st.button("➕ Criar lista FII", key="btn_criar_fii_lista", use_container_width=True):
            _fn = _fii_nome_in.strip()
            if not _fn:
                st.warning("Digite um nome.")
            elif _fn in st.session_state.fiis_listas:
                st.warning("Já existe uma lista com esse nome.")
            else:
                st.session_state.fiis_listas[_fn] = {}
                st.session_state.lista_fii_atual = _fn
                st.rerun()
        st.divider()
        _can_del_fii = len(st.session_state.fiis_listas) > 1
        if not _can_del_fii:
            st.caption("Crie outra lista antes de excluir esta.")
        else:
            if not st.session_state.get("confirm_del_fii_lista"):
                if st.button(
                    f"🗑 Excluir lista ({st.session_state.lista_fii_atual})",
                    key="btn_del_fii_lista_ask", use_container_width=True,
                ):
                    st.session_state.confirm_del_fii_lista = True
                    st.rerun()
            else:
                st.warning(f"Excluir **{st.session_state.lista_fii_atual}**?")
                _dc1, _dc2 = st.columns(2)
                with _dc1:
                    if st.button("✅ Confirmar", key="btn_del_fii_ok", use_container_width=True):
                        del st.session_state.fiis_listas[st.session_state.lista_fii_atual]
                        st.session_state.lista_fii_atual = list(st.session_state.fiis_listas.keys())[0]
                        st.session_state.confirm_del_fii_lista = False
                        st.rerun()
                with _dc2:
                    if st.button("✗ Cancelar", key="btn_del_fii_cancel", use_container_width=True):
                        st.session_state.confirm_del_fii_lista = False
                        st.rerun()

    return st.session_state.fiis_listas.get(st.session_state.lista_fii_atual, {})


def _show_fii_tabela(fiis_atuais: dict) -> None:
    """Tabela de FIIs: adicionar, filtrar, remover/atualizar, listar."""
    # ── Adicionar FII ─────────────────────────────────────────────
    col_in, col_btn, _ = st.columns([2, 1, 1.5])
    with col_in:
        fii_input = st.text_input(
            "Ticker do FII", placeholder="Ex: HGLG11, KNRI11, MXRF11",
            key="fii_ticker_input", label_visibility="collapsed",
        )
    with col_btn:
        if st.button("➕ Adicionar FII", key="btn_add_fii", use_container_width=True):
            # Aceita vários tickers separados por vírgula e/ou espaço.
            _tickers = [t for t in fii_input.upper().replace(",", " ").split() if t]
            if not _tickers:
                st.warning("Digite um ou mais tickers.")
            else:
                _add_ok, _add_ja, _add_err = [], [], []
                for _t in _tickers:
                    if _t in fiis_atuais:
                        _add_ja.append(_t)
                        continue
                    with st.spinner(f"Buscando {_t}…"):
                        _fii_data = _fetch_fii(_t)
                    if _fii_data.get("error"):
                        _add_err.append(f"{_t}: {_fii_data['error']}")
                    else:
                        fiis_atuais[_t] = {**_fii_data, "qtd": 0,
                                           "preco_medio": 0.0, "data_compra": ""}
                        _add_ok.append(_t)
                if _add_ok:
                    st.success(f"Adicionado(s): {', '.join(_add_ok)}")
                if _add_ja:
                    st.info(f"Já estava(m) na lista: {', '.join(_add_ja)}")
                for _e in _add_err:
                    st.error(_e)
                if _add_ok:
                    _save_all()
                    st.rerun()

    # ── Filtro por tipo ───────────────────────────────────────────
    def _tipo_label(fii: dict) -> str:
        ft = (fii.get("fund_type") or "").strip()
        return _FII_TYPE_LABELS.get(ft.lower(), ft.capitalize()) if ft else ""

    _tipos_disponiveis = sorted({_tipo_label(f) for f in fiis_atuais.values() if _tipo_label(f)})
    _tipo_opcoes = ["Todos"] + _tipos_disponiveis
    _col_f, _ = st.columns([2, 2.5])
    with _col_f:
        _tipo_filtro = st.selectbox("Filtrar por tipo", _tipo_opcoes, key="fii_tipo_filtro")

    # Aplica filtro
    fiis_filtrados = list(fiis_atuais.values())
    if _tipo_filtro != "Todos":
        fiis_filtrados = [f for f in fiis_filtrados if _tipo_label(f) == _tipo_filtro]

    if not fiis_atuais:
        st.info("Nenhum FII na lista. Adicione um ticker acima.")
        return

    # ── Remover ───────────────────────────────────────────────────
    st.markdown("**🗑 Remover FII da lista**")
    col_rem, col_att, _ = st.columns([2, 1, 1.5])
    with col_rem:
        _fii_tickers = list(fiis_atuais.keys())
        _rem_sel = st.selectbox(
            "Remover FII", ["—"] + _fii_tickers, key="fii_remover_sel",
            label_visibility="collapsed")
    with col_att:
        if st.button("🗑 Remover", key="btn_rem_fii", use_container_width=True):
            if _rem_sel != "—":
                fiis_atuais.pop(_rem_sel, None)
                if st.session_state.selected_fii == _rem_sel:
                    st.session_state.selected_fii = None
                _save_all()
                st.rerun()
    st.caption("🔄 Para atualizar os dados dos FIIs, use **Atualizar FIIs** no menu lateral.")

    st.divider()

    # ── Tabela ────────────────────────────────────────────────────
    if fiis_filtrados:
        st.markdown(
            _fii_table_html(fiis_filtrados),
            unsafe_allow_html=True,
        )
        st.caption("**Qualidade** e **Preço\\*** = scores 0–100 (Preço\\* alto = mais "
                   "atrativo/barato). FIIs de **papel** não têm nota de qualidade "
                   "(sem dados de crédito) — veja os alertas no Detalhe.")
    else:
        st.info(f"Nenhum FII do tipo '{_tipo_filtro}' na lista.")


def _show_fii_detail_tab(fiis_atuais: dict) -> None:
    """Detalhe do FII — seletor no topo (igual ações)."""
    st.markdown("### 🔍 Detalhe do FII")
    _det_tickers = list(fiis_atuais.keys())  # as chaves SÃO os tickers
    if not _det_tickers:
        st.info("Adicione um FII na aba 📋 Tabela para ver o detalhe.")
    else:
        try:
            _det_default = (_det_tickers.index(st.session_state.selected_fii)
                            if st.session_state.selected_fii in _det_tickers else 0)
            _det_chosen = st.selectbox(
                "Selecione o FII", _det_tickers, index=_det_default,
                key="fii_detalhe_sel",
                format_func=lambda t: f"{t} — {fiis_atuais.get(t, {}).get('name', '')}",
            )
            st.session_state.selected_fii = _det_chosen
            _show_fii_detail(fiis_atuais[_det_chosen])
        except Exception as _e:
            st.error(f"Erro ao montar o detalhe do FII: {_e}")


def _show_fii_carteira(fiis_atuais: dict) -> None:
    """Carteira de FIIs: editor de posições + análise consolidada."""
    from datetime import date as _date  # usado no parse de data_compra
    with st.expander("✏️ Editar posições (quantidade e preço médio)", expanded=False):
        _fii_pos_rows = []
        for _t, _f in fiis_atuais.items():
            _dc_raw = _f.get("data_compra", "")
            try:
                _dc_val = _date.fromisoformat(_dc_raw) if _dc_raw else None
            except ValueError:
                _dc_val = None
            _fii_pos_rows.append({
                "Ticker": _t,
                "Quantidade": int(_f.get("qtd", 0) or 0),
                "Preço Médio (R$)": float(_f.get("preco_medio", 0) or 0),
                "Data de Compra": _dc_val,
            })
        _fii_pos_df = pd.DataFrame(_fii_pos_rows)
        _fii_edited = st.data_editor(
            _fii_pos_df,
            column_config={
                "Ticker": st.column_config.TextColumn("Ticker", disabled=True, width="small"),
                "Quantidade": st.column_config.NumberColumn(
                    "Qtd", min_value=0, max_value=10_000_000, step=1, width="small"),
                "Preço Médio (R$)": st.column_config.NumberColumn(
                    "Preço Médio (R$)", min_value=0.0, format="%.2f", width="medium",
                    help="Opcional — para calcular lucro/prejuízo"),
                "Data de Compra": st.column_config.DateColumn("Data de Compra", width="medium"),
            },
            hide_index=True, use_container_width=True, key="fii_qty_data_editor",
        )
        if st.button("💾 Salvar posições", key="btn_salvar_fii_qtd"):
            _changed = False
            for _, _row in _fii_edited.iterrows():
                _t = str(_row["Ticker"])
                _nq = int(_row["Quantidade"] or 0)
                _npm = float(_row["Preço Médio (R$)"] or 0)
                _dco = _row["Data de Compra"]
                _ndc = _dco.isoformat() if _dco is not None else ""
                if _t in fiis_atuais:
                    _o = fiis_atuais[_t]
                    if (_o.get("qtd", 0) != _nq or _o.get("preco_medio", 0) != _npm
                            or _o.get("data_compra", "") != _ndc):
                        _o["qtd"], _o["preco_medio"], _o["data_compra"] = _nq, _npm, _ndc
                        _changed = True
            if _changed:
                _save_all()
                st.success("Posições salvas.")
                st.rerun()
            else:
                st.info("Nenhuma alteração detectada.")

    # ── Análise consolidada da carteira de FIIs ───────────────────
    try:
        _show_fii_portfolio_analysis(fiis_atuais)
    except Exception as _e:
        st.warning(f"Não foi possível montar a análise consolidada: {_e}")


def _show_fii_tab() -> None:
    st.markdown("## 🏢 Análise de FIIs")
    fiis_atuais = _fii_list_selector()
    tab_cart, tab_tab, tab_det, tab_scr = st.tabs(
        ["📊 Carteira", "📋 Tabela", "🔍 Detalhe", "🔎 Screener"])
    with tab_cart:
        _show_fii_carteira(fiis_atuais)
    with tab_tab:
        _show_fii_tabela(fiis_atuais)
    with tab_det:
        _show_fii_detail_tab(fiis_atuais)
    with tab_scr:
        _show_fii_screener(fiis_atuais)


# ────────────────────────────────────────────────────────────────
# Análise de Portfólio (apenas lista ⭐ Carteira)
# ────────────────────────────────────────────────────────────────

_PORTFOLIO_COLORS = [
    "#4fc3f7", "#81c784", "#ffb74d", "#f06292", "#ce93d8",
    "#80cbc4", "#ffd54f", "#ff8a65", "#90caf9", "#a5d6a7",
    "#ffe082", "#ef9a9a", "#b39ddb", "#80deea", "#bcaaa4",
    "#ffab40", "#69f0ae", "#ea80fc", "#40c4ff", "#ccff90",
]


def _qty_editor(enriched: list[dict], acoes: dict) -> None:
    """Exibe editor de quantidades, preço médio e data de compra para a Carteira."""
    from datetime import date as _date
    with st.expander("📝 Carteira — Quantidades e Posições", expanded=False):
        qty_rows = []
        for e in enriched:
            t  = e["ticker"]
            en = acoes.get(t, {})
            dc_raw = en.get("data_compra", "")
            try:
                dc_val = _date.fromisoformat(dc_raw) if dc_raw else None
            except ValueError:
                dc_val = None
            qty_rows.append({
                "Ticker":         t,
                "Quantidade":     int(en.get("qtd", 0) or 0),
                "Preço Médio (R$)": float(en.get("preco_medio", 0) or 0),
                "Data de Compra": dc_val,
            })
        qty_df = pd.DataFrame(qty_rows)
        edited = st.data_editor(
            qty_df,
            column_config={
                "Ticker": st.column_config.TextColumn("Ticker", disabled=True, width="small"),
                "Quantidade": st.column_config.NumberColumn(
                    "Qtd", min_value=0, max_value=10_000_000, step=1, width="small",
                ),
                "Preço Médio (R$)": st.column_config.NumberColumn(
                    "Preço Médio (R$)", min_value=0.0, format="%.2f", width="medium",
                    help="Opcional — preço médio de compra para calcular lucro/prejuízo",
                ),
                "Data de Compra": st.column_config.DateColumn(
                    "Data de Compra", width="medium",
                    help="Opcional — data de compra ou início da posição",
                ),
            },
            hide_index=True,
            use_container_width=True,
            key="qty_data_editor",
        )
        if st.button("💾 Salvar posições", key="btn_salvar_qtd", use_container_width=False):
            changed = False
            for _, row in edited.iterrows():
                t       = str(row["Ticker"])
                new_qty = int(row["Quantidade"] or 0)
                new_pm  = float(row["Preço Médio (R$)"] or 0)
                dc_obj  = row["Data de Compra"]
                new_dc  = dc_obj.isoformat() if dc_obj is not None else ""
                if t in acoes:
                    old = acoes[t]
                    if (old.get("qtd", 0) != new_qty or
                            old.get("preco_medio", 0) != new_pm or
                            old.get("data_compra", "") != new_dc):
                        acoes[t]["qtd"]         = new_qty
                        acoes[t]["preco_medio"]  = new_pm
                        acoes[t]["data_compra"]  = new_dc
                        changed = True
            if changed:
                _save_all()
                st.success("Posições salvas.")
                st.rerun()
            else:
                st.info("Nenhuma alteração detectada.")


def _weighted_avg_portfolio(positions: list[dict], field: str) -> Optional[float]:
    """Média ponderada de um campo, redistribuindo pesos de posições sem dado."""
    valid = [(p["weight"], p[field]) for p in positions
             if p.get(field) is not None and not (isinstance(p.get(field), float) and math.isnan(p[field]))]
    if not valid:
        return None
    total_w = sum(w for w, _ in valid)
    if total_w == 0:
        return None
    return sum(w * v for w, v in valid) / total_w


def _show_portfolio_analysis(enriched: list[dict], acoes: dict) -> None:
    """Seção 📊 Análise da Carteira — visível apenas quando ⭐ Carteira com posições > 0."""
    positions = []
    for e in enriched:
        t     = e["ticker"]
        en    = acoes.get(t, {})
        qtd   = int(en.get("qtd", 0) or 0)
        price = e.get("close_price")
        pm    = float(en.get("preco_medio", 0) or 0)
        if qtd > 0 and price:
            pnl_r   = (price - pm) * qtd if pm > 0 else None
            pnl_pct = (price / pm - 1) * 100   if pm > 0 else None
            _sc = e.get("scores") or {}
            positions.append({
                "ticker":           t,
                "qtd":              qtd,
                "price":            price,
                "value":            qtd * price,
                "preco_medio":      pm if pm > 0 else None,
                "pnl_reais":        pnl_r,
                "pnl_pct":         pnl_pct,
                "sector":           e.get("sector") or "Outros",
                "dy":               e.get("dividend_yield"),
                "pl":               e.get("pl") if (e.get("pl") or 0) > 0 else None,
                "quality":          _sc.get("quality"),
                "price_score":      _sc.get("price"),
                "nd_ebitda":        e.get("net_debt_ebitda"),
                "daily_change_pct": e.get("daily_change_pct"),
                "weight":           0.0,
            })

    if not positions:
        return

    st.divider()
    st.markdown("## 📊 Análise da Carteira")

    total_valor = sum(p["value"] for p in positions)
    for p in positions:
        p["weight"] = p["value"] / total_valor

    # ── Variação ponderada do dia ──────────────────────────────────
    valid_var = [
        (p["daily_change_pct"], p["weight"])
        for p in positions
        if p.get("daily_change_pct") is not None
    ]
    if valid_var:
        total_w_var = sum(w for _, w in valid_var)
        var_pond_pct: Optional[float] = (
            sum(v * w for v, w in valid_var) / total_w_var if total_w_var > 0 else None
        )
    else:
        var_pond_pct = None

    # ── Valor total + variação (linha de destaque) ─────────────────
    col_total, col_var = st.columns(2)
    col_total.metric(
        "💰 Valor Total",
        f"R$ {total_valor:,.0f}".replace(",", "."),
    )
    with col_var:
        if var_pond_pct is not None:
            valor_ontem   = total_valor / (1 + var_pond_pct / 100)
            var_reais     = total_valor - valor_ontem
            var_color     = "#34d399" if var_pond_pct >= 0 else "#f87171"
            icon          = "📈" if var_pond_pct >= 0 else "📉"
            sign_pct      = "+" if var_pond_pct >= 0 else ""
            sign_r        = "+" if var_reais >= 0 else "-"
            reais_abs_fmt = (
                f"R$ {abs(var_reais):,.2f}"
                .replace(",", "X").replace(".", ",").replace("X", ".")
            )
            # Quando esses preços foram atualizados (a variação reflege aquele momento)
            _ups = [acoes.get(p["ticker"], {}).get("updated_at") for p in positions]
            _ups = [u for u in _ups if u]
            _upd_line = (
                f"<div style='font-size:0.72rem;color:#6b7280;margin-top:4px'>"
                f"atualizado em {_fmt_updated(max(_ups))}</div>" if _ups else "")
            st.markdown(
                f"""
<div style="padding:10px 0 4px 0">
  <div style="font-size:0.8rem;color:#9ea3b0;margin-bottom:6px">
    {icon} Variação Hoje
  </div>
  <div style="font-size:1.75rem;font-weight:700;color:{var_color};line-height:1.1">
    {sign_pct}{var_pond_pct:.2f}%
  </div>
  <div style="font-size:0.95rem;color:{var_color};margin-top:4px">
    {sign_r}{reais_abs_fmt}
  </div>
  {_upd_line}
</div>""",
                unsafe_allow_html=True,
            )
        else:
            st.metric("📅 Variação Hoje", "N/D",
                      help="Variação diária indisponível para todas as posições")

    st.markdown("<div style='margin-top:8px'></div>", unsafe_allow_html=True)

    # ── Indicadores ponderados ────────────────────────────────────
    dy_pond   = _weighted_avg_portfolio(positions, "dy")
    pl_pond   = _weighted_avg_portfolio(positions, "pl")
    nd_pond   = _weighted_avg_portfolio(positions, "nd_ebitda")

    col_dy, col_pl, col_nd = st.columns(3)
    col_dy.metric(
        "DY Pond.",
        f"{dy_pond:.1f}%" if dy_pond is not None else "N/D",
        help="Dividend Yield médio ponderado pelo valor de cada posição",
    )
    col_pl.metric(
        "P/L Pond.",
        f"{pl_pond:.1f}x" if pl_pond is not None else "N/D",
        help="P/L médio ponderado (exclui P/L negativo e inconclusivo)",
    )
    col_nd.metric(
        "Dív/EBITDA Pond.",
        f"{nd_pond:.2f}x" if nd_pond is not None else "N/D",
        help="Dívida Líquida/EBITDA médio ponderado (excluindo N/A bancário e N/D)",
    )

    # ── Qualidade × Preço da carteira (ponderado) + mapa 2×2 ──────
    q_pond = _weighted_avg_portfolio(positions, "quality")
    p_pond = _weighted_avg_portfolio(positions, "price_score")
    if q_pond is not None or p_pond is not None:
        st.markdown("<div style='margin-top:10px'></div>", unsafe_allow_html=True)
        st.markdown("#### 🎯 Qualidade × Preço da carteira")
        _diag_pond = sc._diagnose(q_pond, p_pond)
        if _diag_pond:
            st.markdown(
                f"<div style='display:flex;align-items:center;gap:10px;margin-bottom:10px'>"
                f"<span style='color:#8b94a7;font-size:0.9rem'>Veredito da carteira:</span>"
                f"<span style='display:inline-block;background:{_diag_pond['color']};padding:5px 16px;"
                f"border-radius:999px;color:#fff;font-size:1.0rem;font-weight:600'>"
                f"{_diag_pond['label']}</span></div>",
                unsafe_allow_html=True)
        cqp, cpp = st.columns(2)
        cqp.metric(
            "Qualidade Pond.",
            f"{q_pond:.0f}/100" if q_pond is not None else "N/D",
            help="Qualidade média ponderada pelo valor de cada posição",
        )
        cpp.metric(
            "Preço Pond.",
            f"{p_pond:.0f}/100" if p_pond is not None else "N/D",
            help="Atratividade de preço média ponderada (maior = mais barata)",
        )
        _show_portfolio_quality_price_map(positions)

    # ── P&L total das posições com preço médio ────────────────────
    pnl_positions = [p for p in positions if p.get("pnl_reais") is not None]
    if pnl_positions:
        total_pnl = sum(p["pnl_reais"] for p in pnl_positions)
        total_custo = sum((p["preco_medio"] or 0) * p["qtd"] for p in pnl_positions)
        total_pnl_pct = (total_pnl / total_custo * 100) if total_custo > 0 else None
        pnl_color = "#34d399" if total_pnl >= 0 else "#f87171"
        sign = "+" if total_pnl >= 0 else ""
        pnl_fmt = f"R$ {abs(total_pnl):,.0f}".replace(",", ".")
        pct_fmt = f"{sign}{total_pnl_pct:.1f}%" if total_pnl_pct is not None else ""
        st.markdown(
            f"""<div style='margin-top:12px;padding:14px 16px;border-radius:12px;
            background:#151b26;border:1px solid #232b3a;border-left:4px solid {pnl_color}'>
            <span style='color:#8b94a7;font-size:0.85rem'>💼 Lucro/Prejuízo não realizado
            ({len(pnl_positions)} posição{'ões' if len(pnl_positions)>1 else ''})</span><br>
            <span style='color:{pnl_color};font-size:1.5rem;font-weight:600'>
            {sign}{pnl_fmt}</span>
            <span style='color:{pnl_color};font-size:1rem;margin-left:10px'>{pct_fmt}</span>
            </div>""",
            unsafe_allow_html=True,
        )
        st.markdown("")

    # ── Tabela de posições ────────────────────────────────────────
    st.markdown("#### Posições")
    pos_rows = sorted(positions, key=lambda p: p["weight"], reverse=True)

    def _fmt_pnl_r(v: Optional[float]) -> str:
        if v is None:
            return "—"
        sign = "+" if v >= 0 else "-"
        return f"{sign}R$ {abs(v):,.0f}".replace(",", ".")

    def _fmt_pnl_pct(v: Optional[float]) -> str:
        if v is None:
            return "—"
        return f"{'+' if v >= 0 else ''}{v:.1f}%"

    pos_data = [
        {
            "Ticker":              p["ticker"],
            "Qtd":                 f"{p['qtd']:,}".replace(",", "."),
            "Preço Atual":         f"R$ {p['price']:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            "Preço Médio":         f"R$ {p['preco_medio']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if p.get("preco_medio") else "—",
            "Lucro/Prej. (R$)":    _fmt_pnl_r(p.get("pnl_reais")),
            "Lucro/Prej. (%)":     _fmt_pnl_pct(p.get("pnl_pct")),
            "Valor Total":         f"R$ {p['value']:,.0f}".replace(",", "."),
            "% Carteira":          f"{p['weight'] * 100:.1f}%",
        }
        for p in pos_rows
    ]
    pos_df = pd.DataFrame(pos_data)

    # Colore P&L baseando-se no sinal (verde/vermelho via Styler)
    def _color_pnl(val: str) -> str:
        if val.startswith("+"):
            return "color:#4caf50;font-weight:600"
        if val.startswith("-"):
            return "color:#ef5350;font-weight:600"
        return ""

    try:
        styled_pos = pos_df.style.map(_color_pnl, subset=["Lucro/Prej. (R$)", "Lucro/Prej. (%)"])
    except Exception:
        styled_pos = pos_df

    st.dataframe(styled_pos, hide_index=True, use_container_width=True,
                 height=min(42 + 35 * len(pos_data), 400))

    # ── Gráficos de rosca ─────────────────────────────────────────
    def _group_small(
        items: list[tuple[str, float]],
        threshold_pct: float = 3.0,
        outros_word: str = "itens",
    ) -> tuple[list[str], list[float], list[str]]:
        """
        Agrupa entradas < threshold_pct% em um único slice "Outros (N itens)".
        Retorna (labels, values, customdata) onde customdata é a quebra
        individual dos agrupados para exibição no tooltip.
        """
        total = sum(v for _, v in items)
        if total == 0:
            return [], [], []
        main = [(lbl, val) for lbl, val in items if val / total * 100 >= threshold_pct]
        small = [(lbl, val) for lbl, val in items if val / total * 100 < threshold_pct]

        labels: list[str] = [lbl for lbl, _ in main]
        values: list[float] = [val for _, val in main]
        hovers: list[str] = [""] * len(main)

        if small:
            outros_lbl = f"Outros ({len(small)} {outros_word})"
            outros_val = sum(v for _, v in small)
            breakdown = "<br>".join(
                f"  · {lbl}: {val / total * 100:.1f}%"
                for lbl, val in sorted(small, key=lambda x: -x[1])
            )
            labels.append(outros_lbl)
            values.append(outros_val)
            hovers.append(breakdown)

        return labels, values, hovers

    _HOVER_TPL = (
        "<b>%{label}</b><br>"
        "R$ %{value:,.0f}<br>"
        "%{percent}"
        "%{customdata}<extra></extra>"
    )

    col_p1, col_p2 = st.columns(2)

    # Rosca por ação
    with col_p1:
        st.markdown("#### Por ação")
        tick_items = [(p["ticker"], p["value"]) for p in pos_rows]
        labels_tick, values_tick, hovers_tick = _group_small(
            tick_items, threshold_pct=3.0, outros_word="ações"
        )
        # Formata customdata: linha extra no hover só quando há breakdown
        cd_tick = [f"<br>{h}" if h else "" for h in hovers_tick]
        colors_tick = [_PORTFOLIO_COLORS[i % len(_PORTFOLIO_COLORS)] for i in range(len(labels_tick))]
        fig_tick = go.Figure(go.Pie(
            labels=labels_tick,
            values=values_tick,
            customdata=cd_tick,
            marker=dict(colors=colors_tick, line=dict(color="#0e1117", width=1.5)),
            textinfo="none",        # legenda lateral já mostra tudo — sem texto nas fatias
            hovertemplate=_HOVER_TPL,
            hole=0.35,
        ))
        fig_tick.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=10, b=10, l=10, r=10),
            showlegend=True,
            legend=dict(font=dict(color="#c8cce0", size=11), bgcolor="rgba(0,0,0,0)"),
            height=350,
        )
        st.plotly_chart(fig_tick, use_container_width=True, config={"displayModeBar": False})

    # Rosca por setor
    with col_p2:
        st.markdown("#### Por setor")
        setor_vals: dict[str, float] = {}
        for p in positions:
            setor = p["sector"] or "Outros"
            setor_vals[setor] = setor_vals.get(setor, 0) + p["value"]
        setor_items = sorted(setor_vals.items(), key=lambda x: x[1], reverse=True)
        labels_set, values_set, hovers_set = _group_small(
            setor_items, threshold_pct=3.0, outros_word="setores"
        )
        cd_set = [f"<br>{h}" if h else "" for h in hovers_set]
        colors_set = [_PORTFOLIO_COLORS[(i * 3) % len(_PORTFOLIO_COLORS)] for i in range(len(labels_set))]
        fig_set = go.Figure(go.Pie(
            labels=labels_set,
            values=values_set,
            customdata=cd_set,
            marker=dict(colors=colors_set, line=dict(color="#0e1117", width=1.5)),
            textinfo="none",        # legenda lateral já mostra tudo — sem texto nas fatias
            hovertemplate=_HOVER_TPL,
            hole=0.35,
        ))
        fig_set.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=10, b=10, l=10, r=10),
            showlegend=True,
            legend=dict(font=dict(color="#c8cce0", size=11), bgcolor="rgba(0,0,0,0)"),
            height=350,
        )
        st.plotly_chart(fig_set, use_container_width=True, config={"displayModeBar": False})


# ────────────────────────────────────────────────────────────────
# Aba de Ciclo de Mercado (termômetro educacional — Investment Clock)
# ────────────────────────────────────────────────────────────────

# Fase do ciclo: (rótulo, cor, descrição, o que historicamente favoreceu)
# Descrições focam na dinâmica crescimento × inflação (o que o relógio mede).
# A política monetária NÃO é afirmada aqui — vem dinâmica do Focus na caixa da fase,
# para não contradizer a expectativa real do mercado.
_CICLO_FASES = {
    "recuperacao": ("🌱 Recuperação", "#1b5e20",
        "Atividade acelerando com inflação baixa ou em queda — classicamente a fase mais "
        "favorável a tomar risco.",
        "Ações — especialmente nomes de crescimento e cíclicas de consumo."),
    "aquecimento": ("🔥 Aquecimento", "#bf360c",
        "Atividade ainda crescendo e inflação voltando a subir — a economia 'esquenta'. "
        "Classicamente, fim de ciclo de alta.",
        "Commodities e cíclicas de materiais/energia (mineração, petróleo, siderurgia)."),
    "estagflacao": ("🥶 Estagflação", "#37474f",
        "Atividade enfraquecendo com inflação ainda alta — o cenário mais difícil para risco.",
        "Caixa e pós-fixado (CDI/Selic); perfil de menor risco e mais reservas."),
    "desaceleracao": ("❄️ Desaceleração", "#1f3a5f",
        "Atividade e inflação caindo juntas — o ciclo arrefece e prepara a próxima recuperação.",
        "Renda fixa pré-fixada e títulos longos (duration); começar a montar posição em ações."),
}


def _ciclo_fase(ibc_yoy: Optional[float], ipca_mom: Optional[float]) -> Optional[str]:
    """Determina a fase pelo crescimento (IBC-Br YoY) e momentum da inflação (IPCA 6m)."""
    if ibc_yoy is None or ipca_mom is None:
        return None
    cresc = ibc_yoy >= 0
    infla = ipca_mom >= 0
    if cresc and not infla:
        return "recuperacao"
    if cresc and infla:
        return "aquecimento"
    if not cresc and infla:
        return "estagflacao"
    return "desaceleracao"


@st.cache_data(ttl=3600 * 6, show_spinner=False)
def _get_ciclo_data() -> dict:
    """Coleta indicadores macro do BC (SGS) + P/L do Ibovespa. Cache de 6h."""
    out: dict = {}

    def _serie(cod, n=1, dias=None):
        d = api.get_sgs(cod, ultimos=n, dias=dias) or []
        vals = []
        for p in d:
            try:
                vals.append(float(p["valor"]))
            except (TypeError, ValueError, KeyError):
                continue
        return vals

    # Selic é diária → busca por intervalo (~13 meses) para ver a direção
    selic = _serie(api.SGS_SELIC_META, dias=400)
    out["selic"] = selic[-1] if selic else None
    out["selic_dir"] = (selic[-1] - selic[0]) if len(selic) >= 2 else 0.0

    ipca = _serie(api.SGS_IPCA_12M, 13)
    out["ipca"] = ipca[-1] if ipca else None
    out["ipca_mom"] = (ipca[-1] - ipca[-7]) if len(ipca) >= 7 else None

    ibc = _serie(api.SGS_IBC_BR, 13)
    out["ibc_yoy"] = ((ibc[-1] / ibc[0] - 1) * 100) if len(ibc) >= 13 and ibc[0] > 0 else None

    usd = _serie(api.SGS_USD_BRL, 1)
    out["usd"] = usd[-1] if usd else None

    cred = _serie(api.SGS_CREDITO_PIB, 13)
    out["credito_pib"] = cred[-1] if cred else None
    out["credito_dir"] = (cred[-1] - cred[0]) if len(cred) >= 2 else 0.0

    if out.get("selic") is not None and out.get("ipca") is not None:
        out["juro_real"] = ((1 + out["selic"] / 100) / (1 + out["ipca"] / 100) - 1) * 100
    else:
        out["juro_real"] = None

    _ibov = getattr(api, "get_ibovespa_pl", None)
    out["ibov_pl"] = _ibov() if _ibov else None
    out["ibov_pl_media"] = 12.0  # média histórica de longo prazo (referência, desde 2001)

    # Expectativas do Focus (forward-looking). getattr com fallback: o Streamlit
    # Cloud às vezes serve api.py stale (cache de .pyc) e get_focus seria recém-
    # adicionada — sem o guard, o app inteiro quebraria com AttributeError.
    _focus = getattr(api, "get_focus", None)
    out["focus_ipca"] = _focus("IPCA") if _focus else None
    out["focus_pib"] = _focus("PIB Total") if _focus else None
    out["focus_selic"] = _focus("Selic") if _focus else None

    # Rastro do marcador — posição no relógio nos últimos ~6 meses
    ibc_full = _serie(api.SGS_IBC_BR, 18)
    ipca_full = _serie(api.SGS_IPCA_12M, 13)
    trail = []
    for off in range(5, -1, -1):  # mais antigo → mais recente
        ie = -1 - off
        if len(ibc_full) >= 13 + off and len(ipca_full) >= 7 + off and ibc_full[ie - 12] > 0:
            yoy = (ibc_full[ie] / ibc_full[ie - 12] - 1) * 100
            mom = ipca_full[ie] - ipca_full[ie - 6]
            trail.append((max(-1.0, min(1.0, yoy / 4.0)), max(-1.0, min(1.0, mom / 2.0))))
    out["trail"] = trail
    return out


def _show_ciclo_relogio(mx: float, my: float, fase: str, trail: Optional[list] = None) -> None:
    """Desenha o 'relógio do ciclo' (quadrante Crescimento × Inflação) com o marcador."""
    quad = {  # (x0,y0,x1,y1, cor, chave)
        "aquecimento":   (0, 0, 1, 1, "#bf360c"),
        "estagflacao":   (-1, 0, 0, 1, "#37474f"),
        "recuperacao":   (0, -1, 1, 0, "#1b5e20"),
        "desaceleracao": (-1, -1, 0, 0, "#1f3a5f"),
    }
    fig = go.Figure()
    for k, (x0, y0, x1, y1, cor) in quad.items():
        ativo = (k == fase)
        fig.add_shape(type="rect", x0=x0, y0=y0, x1=x1, y1=y1,
                      line=dict(color="rgba(255,255,255,0.15)", width=1),
                      fillcolor=cor, opacity=0.6 if ativo else 0.16, layer="below")
    # Rótulos nas bordas (longe do centro, onde fica o marcador): fase em negrito
    # + o que historicamente favorece, com prefixo explícito.
    labels = [
        (0.5, 0.86, "<b>🔥 Aquecimento</b>", "favorece commodities"),
        (-0.5, 0.86, "<b>🥶 Estagflação</b>", "favorece caixa / pós-fixado"),
        (0.5, -0.78, "<b>🌱 Recuperação</b>", "favorece ações"),
        (-0.5, -0.78, "<b>❄️ Desaceleração</b>", "favorece renda fixa"),
    ]
    for x, y, nome, favor in labels:
        fig.add_annotation(x=x, y=y, text=nome, showarrow=False,
                           font=dict(size=12, color="#ffffff"))
        fig.add_annotation(x=x, y=y, yshift=-15, text=favor, showarrow=False,
                           font=dict(size=9.5, color="#b9c0cf"))
    # eixos
    fig.add_shape(type="line", x0=-1, y0=0, x1=1, y1=0,
                  line=dict(color="rgba(255,255,255,0.35)", width=1))
    fig.add_shape(type="line", x0=0, y0=-1, x1=0, y1=1,
                  line=dict(color="rgba(255,255,255,0.35)", width=1))
    # rastro dos últimos meses — gradiente do passado (apagado/pequeno) ao presente
    if trail and len(trail) >= 2:
        tx = [t[0] for t in trail]
        ty = [t[1] for t in trail]
        n = len(tx)
        sizes = [6 + 8 * (i / (n - 1)) for i in range(n)]               # 6 → 14 px
        cores = [f"rgba(255,255,255,{0.2 + 0.6 * (i / (n - 1)):.2f})"   # translúcido → opaco
                 for i in range(n)]
        # linha conectando os pontos (branca, fina)
        fig.add_trace(go.Scatter(
            x=tx, y=ty, mode="lines",
            line=dict(color="rgba(255,255,255,0.45)", width=2),
            hoverinfo="skip"))
        # pontos do rastro com gradiente (mostra a direção do tempo)
        fig.add_trace(go.Scatter(
            x=tx, y=ty, mode="markers",
            marker=dict(size=sizes, color=cores,
                        line=dict(color="rgba(0,0,0,0.35)", width=1)),
            hoverinfo="skip"))
        # rótulo do ponto mais antigo, para deixar a direção do tempo explícita
        fig.add_annotation(x=tx[0], y=ty[0], text="há ~6m", showarrow=False,
                           font=dict(size=9, color="#cfd3dc"), yshift=-13)
    # marcador atual — grande, anel branco e rótulo "AGORA"
    _txt_pos = "bottom center" if my > 0.45 else "top center"
    fig.add_trace(go.Scatter(
        x=[mx], y=[my], mode="markers+text",
        marker=dict(size=28, color="#ffeb3b", line=dict(color="#ffffff", width=3), symbol="circle"),
        text=["AGORA"], textposition=_txt_pos,
        textfont=dict(size=13, color="#ffffff", family="Arial Black"),
        hovertemplate="Posição atual<extra></extra>"))
    fig.update_layout(
        height=420, margin=dict(l=10, r=10, t=10, b=30),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        xaxis=dict(range=[-1.08, 1.08], showgrid=False, zeroline=False, showticklabels=False,
                   title=dict(text="←  Atividade contraindo      Atividade crescendo  →",
                              font=dict(size=10, color="#9e9e9e"))),
        yaxis=dict(range=[-1.08, 1.08], showgrid=False, zeroline=False, showticklabels=False,
                   title=dict(text="←  Inflação caindo      Inflação subindo  →",
                              font=dict(size=10, color="#9e9e9e"))),
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def _show_ibov_small_section() -> None:
    """Gráfico Ibovespa × Small Caps ao longo do tempo + força relativa vs média."""
    st.markdown("##### Ibovespa × Small Caps — desempenho relativo")
    df = _fetch_ibov_vs_small(5)
    if df is None or df.empty:
        st.caption("Histórico indisponível no momento (fonte externa).")
        return

    per = st.radio("Período", ["1A", "3A", "5A"], horizontal=True, index=1,
                   key="ibovsmall_per", label_visibility="collapsed")
    dias = {"1A": 365, "3A": 365 * 3, "5A": 365 * 5}[per]
    corte = df.index.max() - pd.Timedelta(days=dias)
    d = df[df.index >= corte].copy()
    if len(d) < 5:
        d = df.copy()

    # Normaliza base 100 no início do recorte (comparação de retorno acumulado)
    d["Ibov_n"] = d["Ibov"] / d["Ibov"].iloc[0] * 100
    d["Small_n"] = d["Small"] / d["Small"].iloc[0] * 100
    gap = d["Small_n"].iloc[-1] - d["Ibov_n"].iloc[-1]  # quanto Small (sub/sobre)performou

    # Força relativa Small/Ibov vs a média de 5 anos (responde "gap > média histórica?")
    ratio5 = df["Small"] / df["Ibov"]
    rel_vs_media = (ratio5.iloc[-1] / ratio5.mean() - 1) * 100

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=d.index, y=d["Ibov_n"], name="Ibovespa",
                             line=dict(color="#42a5f5", width=2)))
    fig.add_trace(go.Scatter(x=d.index, y=d["Small_n"], name="Small Caps",
                             line=dict(color="#ffb74d", width=2)))
    fig.update_layout(
        height=320, margin=dict(l=0, r=0, t=34, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(showgrid=False, color="#9e9e9e"),
        yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.06)", color="#9e9e9e",
                   title=dict(text="base 100", font=dict(size=10, color="#9e9e9e"))),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, font=dict(color="#e8eaf6")),
    )
    st.caption(f"Retorno acumulado, base 100 no início do período ({per}).")
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    st.caption(
        "Duas leituras: o **acumulado** mostra quanto as Small renderam a menos no período; "
        "o **hoje vs média** mostra o quão descontadas elas estão agora frente à relação "
        "típica com o Ibov nos últimos 5 anos."
    )
    c1, c2 = st.columns(2)
    c1.metric(f"Acumulado no período ({per})", f"{gap:+.0f} pp")
    c1.caption(
        f"retorno das Small {'acima' if gap >= 0 else 'abaixo'} do Ibov, em pontos "
        "percentuais (diferença das duas linhas)")
    c2.metric("Hoje vs relação média (5 anos)", f"{rel_vs_media:+.0f}%")
    c2.caption("🟢 Small historicamente barata vs Ibov" if rel_vs_media < -3 else
               ("🔴 Small historicamente cara vs Ibov" if rel_vs_media > 3 else "perto da média"))
    if rel_vs_media < -8:
        st.caption(
            f"📉 As Small Caps estão **{abs(rel_vs_media):.0f}% abaixo** da relação média de 5 anos "
            "com o Ibovespa — historicamente um nível de desconto relativo elevado (o que costuma "
            "acontecer com juros altos, que penalizam mais as empresas menores e alavancadas)."
        )


def _show_ciclo_tab() -> None:
    st.markdown("### 🌐 Termômetro de Ciclo de Mercado")
    st.caption(
        "Onde estamos no ciclo econômico, segundo o framework do **Investment Clock** "
        "(Crescimento × Inflação). Ferramenta **educacional** — mostra o cenário macro e o que "
        "cada fase historicamente favoreceu; **não é recomendação** de compra/venda."
    )

    d = _get_ciclo_data()
    fase = _ciclo_fase(d.get("ibc_yoy"), d.get("ipca_mom"))

    # ── Relógio + diagnóstico da fase ──────────────────────────────
    col_g, col_t = st.columns([1.1, 1])
    with col_g:
        if fase:
            mx = max(-1.0, min(1.0, (d["ibc_yoy"] or 0) / 4.0))
            my = max(-1.0, min(1.0, (d["ipca_mom"] or 0) / 2.0))
            _show_ciclo_relogio(mx, my, fase, trail=d.get("trail"))
        else:
            st.info("⚠️ Dados macro do Banco Central indisponíveis no momento. Tente mais tarde.")
    with col_t:
        if fase:
            rotulo, cor, desc, favorece = _CICLO_FASES[fase]
            st.markdown(
                f"<div style='background:{cor};padding:12px 16px;border-radius:8px;margin-bottom:8px'>"
                f"<div style='color:#fff;font-size:1.15rem;font-weight:700'>{rotulo}</div></div>",
                unsafe_allow_html=True)
            st.markdown(f"**Leitura atual:** {desc}")
            st.markdown(f"**Historicamente favoreceu:** {favorece}")
            # Política monetária REAL (Focus) — reconcilia com a fase clássica
            _fs = d.get("focus_selic") or {}
            _prox = _now_bsb().year + 1
            _sn, _sp = d.get("selic"), _fs.get(_prox)
            if _sn is not None and _sp is not None:
                if _sp < _sn - 0.25:
                    st.markdown(f"📉 **Juros (Focus):** o mercado espera **queda** da Selic "
                                f"(~{_sp:.1f}% até {_prox}) — viés de afrouxamento à frente.")
                elif _sp > _sn + 0.25:
                    st.markdown(f"📈 **Juros (Focus):** o mercado espera **alta** da Selic "
                                f"(~{_sp:.1f}% até {_prox}) — viés de aperto à frente.")
                else:
                    st.markdown(f"➡️ **Juros (Focus):** o mercado espera Selic **estável** "
                                f"(~{_sp:.1f}%).")
            st.caption(
                "Eixos: crescimento = IBC-Br (proxy do PIB) na comparação anual; inflação = "
                "tendência do IPCA 12m nos últimos 6 meses.")

    st.divider()

    # ── Indicadores macro (BC) ─────────────────────────────────────
    st.markdown("##### Indicadores (Banco Central)")

    # Tendência (seta coerente + palavra) e nível vs referência econômica
    def _trend(v, up, down, flat, thr=0.1):
        if v is None:
            return flat
        if v > thr:
            return f"↑ {up}"
        if v < -thr:
            return f"↓ {down}"
        return f"→ {flat}"

    def _faixa(v, faixas):
        """faixas = [(limite_min, rótulo), ...] decrescente; retorna o 1º cujo v >= limite."""
        if v is None:
            return ""
        for lim, rot in faixas:
            if v >= lim:
                return rot
        return faixas[-1][1]

    c1, c2, c3, c4, c5, c6 = st.columns(6)

    _selic = d.get("selic")
    c1.metric("Selic (meta)", f"{_selic:.2f}%" if _selic is not None else "—")
    if _selic is not None:
        _niv = _faixa(_selic, [(9, "🔴 muito restritiva"), (7.5, "🟠 acima do neutro"),
                               (6, "🟡 perto do neutro"), (-99, "🟢 estimulativa")])
        c1.caption(f"{_niv} · {_trend(d.get('selic_dir'), 'subindo', 'caindo', 'estável')}")

    _ipca = d.get("ipca")
    c2.metric("IPCA (12m)", f"{_ipca:.2f}%" if _ipca is not None else "—")
    if _ipca is not None:
        _niv = _faixa(_ipca, [(4.5, "🔴 acima do teto da meta"), (3, "🟠 acima do centro (3%)"),
                              (-99, "🟢 na meta ou abaixo")])
        c2.caption(f"{_niv} · {_trend(d.get('ipca_mom'), 'acelerando', 'desacelerando', 'estável')}")

    _jr = d.get("juro_real")
    c3.metric("Juro real", f"{_jr:.2f}%" if _jr is not None else "—")
    if _jr is not None:
        c3.caption(_faixa(_jr, [(6, "🔴 muito restritivo"), (4.5, "🟠 restritivo"),
                                (3, "🟡 perto do neutro"), (-99, "🟢 estimulativo")]))

    _ibc = d.get("ibc_yoy")
    c4.metric("Atividade (IBC-Br a/a)", f"{_ibc:+.1f}%" if _ibc is not None else "—")
    if _ibc is not None:
        c4.caption(_faixa(_ibc, [(2.5, "🟢 acima do potencial"), (1.2, "🟡 perto do potencial"),
                                 (0, "🟠 abaixo do potencial"), (-99, "🔴 contraindo")]))

    _usd = d.get("usd")
    c5.metric("USD/BRL", f"R$ {_usd:.2f}" if _usd is not None else "—")

    _cred = d.get("credito_pib")
    c6.metric("Crédito/PIB", f"{_cred:.1f}%" if _cred is not None else "—")
    c6.caption(_trend(d.get("credito_dir"), "subindo", "caindo", "estável"))

    st.caption(
        "Referências (não médias históricas): Selic neutra ~7,5% · meta de inflação 3% "
        "(teto 4,5%) · juro real neutro ~4,5% · crescimento potencial ~1,8%."
    )

    st.divider()

    # ── Expectativas do Focus (forward-looking) ────────────────────
    st.markdown("##### Expectativas do mercado — Boletim Focus (BC)")
    ano = _now_bsb().year
    prox = ano + 1
    fi = d.get("focus_ipca") or {}
    fp = d.get("focus_pib") or {}
    fs = d.get("focus_selic") or {}
    def _exp(dic, casas=2):
        a = dic.get(ano)
        p = dic.get(prox)
        val = f"{a:.{casas}f}%" if a is not None else "—"
        cap = f"{prox}: {p:.{casas}f}%" if p is not None else ""
        return val, cap
    fc1, fc2, fc3 = st.columns(3)
    _v, _cap = _exp(fi); fc1.metric(f"IPCA esperado {ano}", _v); fc1.caption(_cap)
    _v, _cap = _exp(fp); fc2.metric(f"PIB esperado {ano}", _v); fc2.caption(_cap)
    _v, _cap = _exp(fs); fc3.metric(f"Selic esperada (fim {ano})", _v); fc3.caption(_cap)
    # Interpretação do caminho da Selic (substitui a curva de juros)
    _selic_now = d.get("selic")
    _selic_prox = fs.get(prox)
    if _selic_now is not None and _selic_prox is not None:
        if _selic_prox < _selic_now - 0.25:
            st.caption(f"📉 O mercado projeta **queda da Selic** (de {_selic_now:.2f}% para "
                       f"~{_selic_prox:.2f}% até o fim de {prox}) — viés de **afrouxamento "
                       "monetário** à frente, historicamente favorável a ações e duration.")
        elif _selic_prox > _selic_now + 0.25:
            st.caption(f"📈 O mercado projeta **alta da Selic** (para ~{_selic_prox:.2f}% até "
                       f"o fim de {prox}) — viés de **aperto monetário**.")
        else:
            st.caption("➡️ O mercado projeta **Selic estável** à frente.")

    st.divider()

    # ── P/L do Ibovespa vs média histórica ─────────────────────────
    st.markdown("##### Valuation da bolsa — P/L do Ibovespa")
    pl = d.get("ibov_pl")
    media = d.get("ibov_pl_media", 12.0)
    if pl:
        gap = (pl / media - 1) * 100
        if gap > 5:
            tag, cor = "acima da média (mais caro)", "#bf360c"
        elif gap < -5:
            tag, cor = "abaixo da média (mais barato)", "#1b5e20"
        else:
            tag, cor = "próximo da média", "#7b5800"
        cc1, cc2, cc3 = st.columns(3)
        cc1.metric("P/L atual", f"{pl:.1f}×")
        cc2.metric("Média histórica (~desde 2001)", f"{media:.1f}×")
        cc3.metric("Posição", f"{gap:+.0f}%")
        cc3.caption(tag)
        st.markdown(
            f"<div style='background:{cor};color:#fff;padding:6px 12px;border-radius:6px;"
            f"font-size:0.9rem'>A bolsa negocia a <b>{pl:.1f}×</b> lucros, <b>{tag}</b> "
            f"(referência ~{media:.0f}×).</div>", unsafe_allow_html=True)
    else:
        st.caption("P/L do Ibovespa indisponível no momento (fonte externa). "
                   "Referência de média histórica: ~12×.")

    st.divider()
    _show_ibov_small_section()

    st.divider()
    st.warning(
        "⚠️ **Leia com cautela.** Este é um termômetro educacional simplificado. O ciclo "
        "brasileiro é fortemente influenciado por fatores **globais** (Fed, China, commodities) "
        "que este painel doméstico não captura, e timing de ciclo é notoriamente incerto. "
        "Não constitui recomendação de investimento — use como contexto, não como gatilho."
    )


# ────────────────────────────────────────────────────────────────
# Alertas
# ────────────────────────────────────────────────────────────────

def _target_price(s: dict) -> Optional[float]:
    """Preço-alvo (cenário Base) pelo motor por setor — mesmo de _build_table."""
    sector = s.get("sector", "")
    if sc.is_bank(sector):
        return _gordon_base_price(s)
    if _is_insurer(sector):
        return _insurer_base_price(s)
    if _is_shopping(sector):
        return _shopping_base_price(s)
    if _is_cyclical(sector):
        return _cyclical_base_price(s)
    if _is_utility(sector):
        return _dcf_base_price(s)
    return _geral_base_price(s)


def _alert_view(s: dict) -> dict:
    """View achatada de uma ação com todos os fatores de alerta."""
    scores = s.get("scores") or sc.calculate_scores(s)
    price = s.get("close_price")
    target = _target_price(s)
    potencial = ((target / price - 1) * 100) if (target and price and price > 0) else None
    return {
        "ticker":           s.get("ticker", ""),
        "close_price":      price,
        "daily_change_pct": s.get("daily_change_pct"),
        "dividend_yield":   s.get("dividend_yield"),
        "pl":               s.get("pl"),
        "pvp":              s.get("pvp"),
        "roe":              s.get("roe"),
        "potencial":        potencial,
        "quality":          scores.get("quality"),
        "price_score":      scores.get("price"),
    }


def _build_alert_views() -> dict:
    """{ticker: view} para todos os tickers das listas de ações do usuário."""
    views: dict = {}
    for ldata in st.session_state.todas_listas.values():
        for ticker, entry in ldata.items():
            if ticker in views:
                continue
            data = entry.get("data", {})
            if not data or data.get("error"):
                continue
            try:
                views[ticker] = _alert_view(data)
            except Exception:
                pass
    return views


def _show_alertas_tab() -> None:
    st.markdown("## 🔔 Alertas")
    st.caption(
        "Crie alertas com uma ou mais condições combinadas (E/OU). São avaliados "
        "**ao abrir o app ou atualizar os dados** — o app não roda em segundo plano.")

    views = _build_alert_views()
    all_tickers = sorted(views.keys())
    list_names = list(st.session_state.todas_listas.keys())
    st.session_state.setdefault("_alert_conds", [])

    # ── Criar novo alerta ─────────────────────────────────────────
    with st.expander("➕ Criar novo alerta", expanded=not st.session_state.alertas):
        nome = st.text_input("Nome (opcional)", key="_alert_nome",
                              placeholder="ex: BBAS3 barata")

        esc_tipo = st.radio("Escopo", ["Ações específicas", "Uma lista inteira"],
                            horizontal=True, key="_alert_esc_tipo")
        esc_tickers, esc_lista = [], ""
        if esc_tipo == "Ações específicas":
            esc_tickers = st.multiselect("Ações", all_tickers, key="_alert_tickers")
        else:
            esc_lista = st.selectbox("Lista", list_names, key="_alert_lista")

        st.markdown("**Condições**")
        cc1, cc2, cc3, cc4 = st.columns([3, 1.1, 1.6, 1.3])
        _fopts = list(al.FACTORS.keys())
        f_sel = cc1.selectbox("Fator", _fopts, key="_alert_fator",
                              format_func=lambda k: al.FACTORS[k]["label"],
                              label_visibility="collapsed")
        op_sel = cc2.selectbox("Op", al.OPERADORES, key="_alert_op", label_visibility="collapsed")
        val_sel = cc3.number_input("Valor", value=0.0, step=0.5, key="_alert_val",
                                   label_visibility="collapsed")
        if cc4.button("➕ Condição", key="_alert_add_cond", use_container_width=True):
            st.session_state._alert_conds.append(
                {"fator": f_sel, "operador": op_sel, "valor": float(val_sel)})
            st.rerun()

        if st.session_state._alert_conds:
            for i, c in enumerate(st.session_state._alert_conds):
                ck, cd = st.columns([6, 1])
                ck.markdown(f"- **{al.cond_label(c)}**")
                if cd.button("🗑", key=f"_alert_delc_{i}"):
                    st.session_state._alert_conds.pop(i)
                    st.rerun()
        else:
            st.caption("Adicione ao menos uma condição acima.")

        combin = st.radio("Combinar condições", ["E", "OU"], horizontal=True, key="_alert_combin",
                          help="E = todas precisam bater · OU = qualquer uma já dispara")

        if st.button("✅ Criar alerta", type="primary", key="_alert_criar"):
            if not st.session_state._alert_conds:
                st.warning("Adicione ao menos uma condição.")
            elif esc_tipo == "Ações específicas" and not esc_tickers:
                st.warning("Selecione ao menos uma ação.")
            else:
                st.session_state.alertas.append({
                    "id": str(int(time.time() * 1000)),
                    "nome": nome.strip(),
                    "ativo": True,
                    "escopo_tipo": "tickers" if esc_tipo == "Ações específicas" else "lista",
                    "escopo_tickers": list(esc_tickers),
                    "escopo_lista": esc_lista,
                    "combinador": combin,
                    "condicoes": list(st.session_state._alert_conds),
                    "criado_em": _now_bsb().isoformat(),
                    "acks": [],
                })
                st.session_state._alert_conds = []
                _save_all()
                st.success("Alerta criado!")
                st.rerun()

    # ── Alertas vigentes ──────────────────────────────────────────
    st.markdown("### Alertas vigentes")
    if not st.session_state.alertas:
        st.info("Nenhum alerta criado ainda. Use **➕ Criar novo alerta** acima.")
        return

    for idx, alert in enumerate(st.session_state.alertas):
        ativo = alert.get("ativo", True)
        scope_tk = al.scope_tickers(alert, st.session_state.todas_listas)
        scope_views = [views[t] for t in scope_tk if t in views]
        triggers = al.evaluate_alert(alert, scope_views) if ativo else []

        if not ativo:
            barra = ("#37474f", "⏸ Pausado")
        elif triggers:
            barra = ("#1b5e20", f"✓ Condição já atingida — {', '.join(d['ticker'] for d in triggers)}")
        else:
            barra = ("#1a1d2e", "🔍 Monitorando")

        with st.container():
            cinfo, cbtn = st.columns([5, 1.4])
            with cinfo:
                st.markdown(
                    f"<div style='background:{barra[0]};padding:8px 14px;border-radius:8px;"
                    f"color:#fff;font-weight:600;margin-bottom:6px'>{barra[1]}</div>",
                    unsafe_allow_html=True)
                st.markdown(f"**{al.alert_label(alert)}**")
                _join = " **E** " if alert.get("combinador") == "E" else " **OU** "
                st.caption("Escopo: " + al.scope_label(alert) + "  ·  Condições: "
                           + _join.join(al.cond_label(c) for c in alert.get("condicoes", [])))
                if triggers:
                    for d in triggers:
                        _vals = " · ".join(f"{c['valor_fmt']}" for c in d["condicoes"])
                        st.markdown(f"<span style='color:#81c784'>● {d['ticker']}: {_vals}</span>",
                                    unsafe_allow_html=True)
            with cbtn:
                _lbl_toggle = "▶ Ativar" if not ativo else "⏸ Pausar"
                if st.button(_lbl_toggle, key=f"_alert_toggle_{idx}", use_container_width=True):
                    alert["ativo"] = not ativo
                    _save_all()
                    st.rerun()
                if st.button("🗑 Excluir", key=f"_alert_excl_{idx}", use_container_width=True):
                    st.session_state.alertas.pop(idx)
                    _save_all()
                    st.rerun()
        st.divider()


def _eval_alerts_global() -> tuple[list[dict], bool]:
    """Avalia todos os alertas ativos. Retorna (resultados_nao_vistos, acks_mudou).

    resultados = [{alert, triggered, novos}] só dos alertas com disparo NÃO visto.
    Sincroniza acks: remove tickers que pararam de disparar (condição resetou).
    """
    if not st.session_state.get("alertas"):
        return [], False
    views = _build_alert_views()
    resultados, mudou = [], False
    for alert in st.session_state.alertas:
        if not alert.get("ativo", True):
            continue
        scope_tk = al.scope_tickers(alert, st.session_state.todas_listas)
        scope_views = [views[t] for t in scope_tk if t in views]
        trigs = al.evaluate_alert(alert, scope_views)
        trig_tickers = [d["ticker"] for d in trigs]
        acks = alert.get("acks", [])
        new_acks = [a for a in acks if a in trig_tickers]  # reseta acks de quem parou
        if new_acks != acks:
            alert["acks"] = new_acks
            mudou = True
        novos = [t for t in trig_tickers if t not in alert.get("acks", [])]
        if novos:
            resultados.append({"alert": alert, "triggered": trigs, "novos": novos})
    return resultados, mudou


def _show_alert_banner(resultados: list[dict]) -> None:
    """Banner no topo com os alertas recém-disparados (não vistos)."""
    linhas = [f"<b>{al.alert_label(r['alert'])}</b> → {', '.join(r['novos'])}"
              for r in resultados]
    st.markdown(
        f"<div style='background:#1b5e20;padding:10px 16px;border-radius:8px;color:#fff;"
        f"margin-bottom:8px'>🔔 <b>{len(resultados)} alerta(s) disparado(s)</b><br>"
        + "<br>".join(linhas) + "</div>",
        unsafe_allow_html=True)
    if st.button("✓ Marcar como visto", key="_alert_ack_all"):
        for r in resultados:
            r["alert"]["acks"] = [d["ticker"] for d in r["triggered"]]
        _save_all()
        st.rerun()


# ────────────────────────────────────────────────────────────────
# App principal
# ────────────────────────────────────────────────────────────────

def main():
    st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

/* ── Tipografia: Inter ──────────────────────────────── */
html, body, [data-testid="stAppViewContainer"], [data-testid="stSidebar"],
button, input, select, textarea, .stMarkdown {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
}
h1 { font-weight: 700 !important; letter-spacing: -0.02em; }
h2, h3, h4 { font-weight: 600 !important; letter-spacing: -0.01em; }

/* ── Métricas em card ───────────────────────────────── */
[data-testid="stMetric"] {
    background: #151b26;
    border: 1px solid #232b3a;
    border-radius: 12px;
    padding: 12px 16px;
}
[data-testid="stMetricValue"] { font-weight: 600; }
[data-testid="stMetricLabel"] p { color: #8b94a7; }

/* ── Botões ─────────────────────────────────────────── */
.stButton > button {
    border-radius: 10px;
    border: 1px solid #2a3343;
    font-weight: 500;
    transition: border-color .12s ease, background .12s ease;
}
.stButton > button:hover { border-color: #34d399; }

/* ── Inputs / selects / expanders ───────────────────── */
[data-baseweb="select"] > div,
.stTextInput input, .stNumberInput input {
    border-radius: 10px !important;
}
[data-testid="stExpander"] details {
    border: 1px solid #232b3a;
    border-radius: 12px;
}

/* ── Sidebar ────────────────────────────────────────── */
[data-testid="stSidebar"] {
    background: #0c1119;
    border-right: 1px solid #1c2230;
}
[data-baseweb="tab-list"] { gap: 4px; }

#MainMenu {visibility: hidden;}
.stDeployButton {display: none;}
[data-testid="stDecoration"] {display: none;}
footer {visibility: hidden;}
/* Desktop: esconde header e toolbar por inteiro (sidebar já abre expandida).
   Mobile: mantém ambos visíveis — stExpandSidebarButton vive dentro de stToolbar
   e é o único meio de abrir a sidebar quando ela começa colapsada. */
@media (min-width: 768px) {
    header {visibility: hidden;}
    [data-testid="stToolbar"] {display: none;}
}
</style>
""", unsafe_allow_html=True)
    if "usuario_atual" not in st.session_state:
        _tela_selecao_usuario()
        return

    _init_state()

    # Avalia alertas antes do sidebar (alimenta o badge); salva se acks mudaram
    _alert_res, _alert_changed = _eval_alerts_global()
    if _alert_changed:
        _save_all()
    st.session_state._alert_badge_n = len(_alert_res)

    _sidebar()

    if _alert_res:
        _show_alert_banner(_alert_res)

    # ── Navegação por área (FIIs/Screener/Ciclo independem de ações) ──
    _area = st.session_state.get("area", "📊 Ações")
    if _area == "🏢 FIIs":
        _show_fii_tab()
        return
    if _area == "🔎 Screener":
        _show_screener()
        return
    if _area == "🌐 Ciclo":
        _show_ciclo_tab()
        return
    if _area == "🔔 Alertas":
        _show_alertas_tab()
        return

    # ── Área Ações ────────────────────────────────────────────
    if not st.session_state.acoes:
        st.markdown("## 📈 Bem-vindo ao Analisador Fundamentalista B3")
        st.markdown(
            "Este app ajuda você a analisar ações da bolsa brasileira combinando 10+ indicadores "
            "fundamentalistas em um score único de 0 a 100, com contexto setorial, comparação "
            "visual entre ações, valuation por fluxo de caixa descontado e acompanhamento de carteira."
        )
        st.markdown(
            "**Para começar:** adicione um ou mais tickers no campo à esquerda "
            "(ex: PETR4, VALE3, ITUB4)."
        )
        return

    enriched: list[dict] = []
    for ticker, entry in st.session_state.acoes.items():
        try:
            e = _enrich(entry)
            enriched.append(e)
        except Exception as ex:
            st.warning(f"Erro ao processar {ticker}: {ex}")

    enriched.sort(
        key=lambda x: (
            (x.get("scores") or {}).get("quality") is not None,
            (x.get("scores") or {}).get("quality") or -1,
        ),
        reverse=True,
    )

    # ── Rendimento da carteira atual → passa para painel macro ──
    _cart_valor, _cart_custo, _cart_var_dia = 0.0, 0.0, []
    for e in enriched:
        t   = e.get("ticker", "")
        en  = st.session_state.acoes.get(t, {})
        qtd = int(en.get("qtd", 0) or 0)
        if qtd <= 0:
            continue
        price = e.get("close_price") or 0
        pm    = float(en.get("preco_medio", 0) or 0)
        val   = qtd * price
        _cart_valor += val
        if pm > 0:
            _cart_custo += qtd * pm
        chg = e.get("daily_change_pct")
        if chg is not None:
            _cart_var_dia.append((chg, val))
    _cart_pnl_pct   = (_cart_valor / _cart_custo - 1) * 100 if _cart_custo > 0 else None
    _cart_var_d_pct = (sum(c * v for c, v in _cart_var_dia) / sum(v for _, v in _cart_var_dia)
                       if _cart_var_dia else None)
    st.session_state["_macro_cart"] = {
        "valor": _cart_valor if _cart_custo > 0 else None,
        "pnl_pct": _cart_pnl_pct,
        "var_dia": _cart_var_d_pct,
    }

    # ── Painel macro ──────────────────────────────────────────
    _show_macro_panel()

    # CSS global: popover ℹ️ sem container visual, tamanho legível
    st.markdown("""
<style>
div[data-testid="stPopover"] button {
    border: none !important;
    border-radius: 0 !important;
    font-size: 16px !important;
    min-width: unset !important;
    width: auto !important;
    height: auto !important;
    min-height: unset !important;
    padding: 0 2px !important;
    background: transparent !important;
    box-shadow: none !important;
    font-weight: 400 !important;
    cursor: pointer !important;
    vertical-align: middle !important;
    line-height: 1.4 !important;
    opacity: 0.85;
}
div[data-testid="stPopover"] button:hover {
    background: transparent !important;
    border: none !important;
    opacity: 1.0 !important;
}
</style>
""", unsafe_allow_html=True)

    enriched = _dedup_enriched(enriched)

    tab_cart, tab_comp, tab_det, tab_cmp = st.tabs(
        ["📊 Carteira", "📋 Tabela", "🔍 Detalhe", "⚖️ Comparar"]
    )

    # ────────────────────────────────────────────────────────────
    # Tab — Carteira (consolidada da ⭐ Carteira)
    # ────────────────────────────────────────────────────────────
    with tab_cart:
        if st.session_state.lista_atual == LISTAS_PADRAO[0]:
            _qty_editor(enriched, st.session_state.acoes)
            _show_portfolio_analysis(enriched, st.session_state.acoes)
        else:
            st.info(
                f"A análise consolidada é da lista **{LISTAS_PADRAO[0]}**. "
                f"Selecione-a no menu lateral (você está em "
                f"**{st.session_state.lista_atual}**)."
            )

    # ────────────────────────────────────────────────────────────
    # Tab 1 — Comparativo (tabela limpa, sem radar)
    # ────────────────────────────────────────────────────────────
    with tab_comp:
        st.markdown("### Tabela Comparativa")
        st.caption(
            "Veja cada ação da lista lado a lado, colorida por classificação. "
            "Selecione uma na aba **🔍 Detalhe** para o aprofundamento, ou use "
            "**⚖️ Comparar** para o radar. A consolidação das suas posições está em **📊 Carteira**."
        )

        # Ordenação confiável (server-side) — útil p/ agrupar por setor.
        _sort_opts = {
            "Qualidade ↓": (lambda e: (e.get("scores") or {}).get("quality") or -1, True),
            "Preço ↓":     (lambda e: (e.get("scores") or {}).get("price") or -1, True),
            "Setor (A-Z)": (lambda e: (e.get("sector") or "").lower(), False),
            "Ticker (A-Z)": (lambda e: e.get("ticker", ""), False),
            "DY ↓":        (lambda e: e.get("dividend_yield") if e.get("dividend_yield") is not None else -1, True),
            "Variação dia ↓": (lambda e: e.get("daily_change_pct") if e.get("daily_change_pct") is not None else -999, True),
        }
        _sc1, _ = st.columns([2, 4])
        _sort_sel = _sc1.selectbox("Ordenar por", list(_sort_opts.keys()),
                                   key="tabela_sort", label_visibility="collapsed")
        _key, _rev = _sort_opts[_sort_sel]
        enriched = sorted(enriched, key=_key, reverse=_rev)

        display_df, class_df = _build_table(enriched)
        if display_df.empty or "Ticker" not in display_df.columns:
            st.warning(
                "Nenhuma ação pôde ser processada. Se você acabou de atualizar o app, "
                "faça **Reboot** (Manage app → ⋮ → Reboot) para recarregar os módulos."
            )
            return
        tickers_ordered = display_df["Ticker"].tolist()

        display_df_show = display_df.set_index("Ticker")
        class_df_show = class_df.set_index("Ticker")

        styled = _apply_styles(display_df_show, class_df_show)

        event = st.dataframe(
            styled,
            use_container_width=True,
            on_select="rerun",
            selection_mode="single-row",
            height=min(42 + 35 * len(enriched), 600),
            column_config={
                "Qualidade":       st.column_config.NumberColumn(
                    "Qualidade", width="small", format="%.0f",
                    help="Qualidade do negócio (0-100): ROE, solidez, margem e crescimento. "
                         "Maior = melhor empresa."),
                "Atratividade":    st.column_config.NumberColumn(
                    "Preço", width="small", format="%.0f",
                    help="Atratividade do preço (0-100): EV/EBITDA, P/L, P/FCF (bancos: P/VP, P/L). "
                         "Maior = mais barata."),
                "Diagnóstico":     st.column_config.TextColumn(
                    "Diagnóstico", width="medium",
                    help="Combina Qualidade × Preço: 'Boa e barata' (oportunidade) · 'Boa, mas "
                         "cara' · 'Barata, mas fraca' (⚠ possível value trap) · 'Fraca e cara'."),
                "Empresa":         st.column_config.TextColumn("Empresa", width="medium"),
                "Setor":           st.column_config.TextColumn("Setor", width="medium"),
                "Balanço":         st.column_config.TextColumn("Balanço", width="small"),
                "Cotação":         st.column_config.NumberColumn("Cotação", width="small", format="R$ %.2f"),
                "Potencial":       st.column_config.NumberColumn(
                    "Potencial", width="small", format="%+.1f%%",
                    help="Potencial de valorização vs preço atual no cenário Esperado (Base): "
                         "DCF para ações em geral, Gordon Growth para bancos. "
                         "Os 3 cenários (Conservador/Base/Otimista) ficam na aba Detalhe.",
                ),
                "Var.Dia":         st.column_config.NumberColumn("Var.Dia", width="small", format="%+.2f%%"),
                # Indicadores: sem format= para que o Styler mostre N/A ou N/D
                # corretamente (format= sobrescreveria NaN → "None")
                "Dív.Líq/EBITDA":  st.column_config.NumberColumn("Dív/EBITDA", width="small"),
                "ROE":             st.column_config.NumberColumn("ROE", width="small"),
                "EV/EBITDA":       st.column_config.NumberColumn("EV/EBITDA", width="small"),
                "P/L":             st.column_config.NumberColumn("P/L", width="small"),
                "Mg. EBITDA":      st.column_config.NumberColumn("Mg.EBITDA", width="small"),
                "CAGR Lucro 5a":   st.column_config.NumberColumn("CAGR Lucro", width="small"),
                "P/FCF":           st.column_config.NumberColumn("P/FCF", width="small"),
                "Div. Yield":      st.column_config.NumberColumn("DY", width="small"),
                "Liquidez":        st.column_config.NumberColumn("Liq. (R$M)", width="small"),
                "CAGR Rec. 5a":    st.column_config.NumberColumn("CAGR Rec.", width="small"),
                "P/VP":            st.column_config.NumberColumn("P/VP", width="small"),
                "PSR":             st.column_config.NumberColumn("PSR", width="small"),
            },
        )

        if event.selection and event.selection.rows:
            row_idx = event.selection.rows[0]
            if row_idx < len(tickers_ordered):
                st.session_state.selected_ticker = tickers_ordered[row_idx]
                st.info(
                    f"**{tickers_ordered[row_idx]}** selecionado. "
                    "Veja o detalhamento na aba **🔍 Detalhe**."
                )

        # ── Legenda + CSV ──────────────────────────────────────
        col_leg, col_csv = st.columns([4, 1])
        with col_leg:
            with st.expander("🎨 Legenda de cores"):
                cols = st.columns(5)
                for i, (cls, em) in enumerate(
                    [("Excelente", "🟢"), ("Bom", "🟩"), ("Razoável", "🟡"),
                     ("Atenção", "🟠"), ("Proibitivo", "🔴")]
                ):
                    bg = BG_COLORS[cls]
                    cols[i].markdown(
                        f"<div style='background:{bg};color:#fff;padding:4px 8px;"
                        f"border-radius:4px;text-align:center'>{em} {cls}</div>",
                        unsafe_allow_html=True,
                    )
        with col_csv:
            csv_bytes = display_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="⬇ Exportar CSV",
                data=csv_bytes,
                file_name="analise_b3.csv",
                mime="text/csv",
                use_container_width=True,
            )

    # ────────────────────────────────────────────────────────────
    # Tab 2 — Detalhe
    # ────────────────────────────────────────────────────────────
    with tab_det:
        tickers_avail = [e["ticker"] for e in enriched]
        selected = st.session_state.selected_ticker

        default_idx = 0
        if selected and selected in tickers_avail:
            default_idx = tickers_avail.index(selected)

        chosen = st.selectbox(
            "Selecione a ação",
            tickers_avail,
            index=default_idx,
            format_func=lambda t: f"{t} — {next((e.get('trade_name') or e.get('corporate_name','') for e in enriched if e['ticker']==t), '')}",
        )
        st.session_state.selected_ticker = chosen

        if chosen:
            stock_detail = next((e for e in enriched if e["ticker"] == chosen), None)
            if stock_detail:
                _show_detail(stock_detail)

    # ────────────────────────────────────────────────────────────
    # Tab 3 — Comparar (radar cross-listas)
    # ────────────────────────────────────────────────────────────
    with tab_cmp:
        st.markdown("### ⚖️ Comparar Ações")
        st.caption(
            "Compare ações de **qualquer lista** — independente de qual está selecionada na sidebar. "
            "Selecione de 2 a 4 ações para ver o radar e a tabela de indicadores lado a lado."
        )

        # Agrega todas as ações de todas as listas (sem duplicatas)
        # Prioridade de fonte: Carteira > outras listas (ordem de LISTAS_PADRAO)
        _all_stocks_map: dict[str, tuple[str, dict]] = {}  # ticker -> (lista, data)
        _listas_ordenadas = list(LISTAS_PADRAO) + [
            k for k in st.session_state.todas_listas if k not in LISTAS_PADRAO
        ]
        for _lname in _listas_ordenadas:
            _ldata = st.session_state.todas_listas.get(_lname, {})
            for _tk, _entry in _ldata.items():
                if _tk not in _all_stocks_map:
                    _raw = _entry.get("data", {})
                    if _raw and not _raw.get("error"):
                        # _enrich adiciona os scores; o radar usa score_indicator
                        _all_stocks_map[_tk] = (_lname, _enrich(_entry))

        if not _all_stocks_map:
            st.info("Nenhuma ação com dados disponível. Adicione ações nas suas listas primeiro.")
        else:
            # Opções do multiselect: "TICKER (Lista)"
            _cmp_options = [
                f"{tk} ({ln})"
                for tk, (ln, _) in sorted(_all_stocks_map.items())
            ]
            _cmp_ticker_of = {
                f"{tk} ({ln})": tk
                for tk, (ln, _) in _all_stocks_map.items()
            }

            _cmp_selected_opts = st.multiselect(
                "Selecione 2 a 4 ações para comparar:",
                _cmp_options,
                max_selections=4,
                placeholder="Escolha as ações…",
                key="cmp_multiselect",
            )
            _cmp_tickers = [_cmp_ticker_of[o] for o in _cmp_selected_opts]

            if len(_cmp_tickers) < 2:
                if len(_cmp_tickers) == 1:
                    st.caption("Selecione ao menos **2 ações** para ver o radar comparativo.")
                else:
                    st.caption("Selecione entre 2 e 4 ações acima para iniciar a comparação.")
            else:
                _cmp_stocks = [_all_stocks_map[t][1] for t in _cmp_tickers]

                banks_in = [
                    t for t, s in zip(_cmp_tickers, _cmp_stocks)
                    if sc.is_bank(s.get("sector", ""))
                ]
                if banks_in:
                    st.caption(
                        f"⚠ {', '.join(banks_in)}: setor bancário — "
                        "pontuação zero no radar (score não calculado para bancos)."
                    )

                fig_cmp = _radar_chart(_cmp_stocks, _cmp_tickers)
                st.plotly_chart(fig_cmp, use_container_width=True,
                                config={"displayModeBar": False})

                st.markdown("##### Valores por indicador")
                _comparison_table(_cmp_tickers, _cmp_stocks)


if __name__ == "__main__":
    main()
