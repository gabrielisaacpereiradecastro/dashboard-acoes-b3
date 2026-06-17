"""
App principal — Análise Fundamentalista B3
Fonte de dados: API Bolsai (usebolsai.com)
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import api
import score as sc
from config import (
    BG_COLORS, COLOR_EMOJI, INDICATOR_LABELS, INDICATOR_WEIGHTS,
    SCORE_COLORS,
)

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

# Ordem exata das colunas na tabela (indicadores com score)
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


# ────────────────────────────────────────────────────────────────
# Persistência
# ────────────────────────────────────────────────────────────────

def load_data() -> dict:
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_data(data: dict) -> None:
    DATA_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


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


def _staleness_color(updated_at_iso: Optional[str]) -> str:
    """Retorna cor CSS baseada na idade dos dados."""
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
        if dt.tzinfo:
            dt = dt.astimezone().replace(tzinfo=None)
        return dt.strftime("%d/%m/%Y às %H:%M")
    except Exception:
        return updated_at_iso


# ────────────────────────────────────────────────────────────────
# Inicialização do session_state
# ────────────────────────────────────────────────────────────────

def _init_state():
    if "acoes" not in st.session_state:
        st.session_state.acoes = load_data()
    if "selected_ticker" not in st.session_state:
        st.session_state.selected_ticker = None
    # Mensagens persistidas entre reruns para sobreviver ao st.rerun()
    if "flash_errors" not in st.session_state:
        st.session_state.flash_errors: list[str] = []
    if "flash_success" not in st.session_state:
        st.session_state.flash_success: str = ""
    # Log de debug da última operação de fetch
    if "debug_log" not in st.session_state:
        st.session_state.debug_log: list[str] = []
    # JSON bruto de /fundamentals do último ticker buscado
    if "debug_raw_fund" not in st.session_state:
        st.session_state.debug_raw_fund: Optional[dict] = None


# ────────────────────────────────────────────────────────────────
# Fetch e persistência de uma ação
# ────────────────────────────────────────────────────────────────

def _fetch_ticker(ticker: str) -> Optional[str]:
    """
    Busca dados de um ticker e salva no session_state/JSON.
    Retorna string de erro ou None em caso de sucesso.
    Registra log de debug em st.session_state.debug_log.
    """
    t = ticker.strip().upper()
    log = st.session_state.debug_log

    # Verificar se a chave está disponível
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

    # Extrair e armazenar o JSON bruto de /fundamentals ANTES de salvar
    raw_fund = data.pop("_raw_fund", {})
    st.session_state.debug_raw_fund = raw_fund

    # Log rápido dos campos de interesse
    log.append(
        f"📌 dividend_yield={raw_fund.get('dividend_yield')!r}"
        f"  |  cagr_earnings_5y={raw_fund.get('cagr_earnings_5y')!r}"
        f"  |  cagr_revenue_5y={raw_fund.get('cagr_revenue_5y')!r}"
    )
    log.append(f"📋 Total de campos retornados por /fundamentals: {len(raw_fund)}")
    log.append("👇 JSON completo disponível no painel abaixo")

    st.session_state.acoes[t] = {
        "data": data,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    save_data(st.session_state.acoes)
    return None


def _update_all() -> list[str]:
    """Reatualiza todos os tickers salvos. Retorna lista de erros."""
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

def _enrich(entry: dict) -> dict:
    """Adiciona score, label e breakdown ao dict de dados da ação."""
    stock = entry["data"]
    s, label, breakdown = sc.calculate_score(stock)
    return {**stock, "score": s, "score_label": label, "breakdown": breakdown}


# ────────────────────────────────────────────────────────────────
# Construção da tabela comparativa
# ────────────────────────────────────────────────────────────────

def _build_table(stocks: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Retorna (display_df, class_df).
    display_df: valores formatados para exibição.
    class_df: classificações para aplicar cores.
    """
    rows_display = []
    rows_class = []

    for s in stocks:
        sector = s.get("sector", "")
        classifications = sc.classify_all(s)

        display_row = {
            "Ticker":    s.get("ticker", ""),
            "Empresa":   s.get("trade_name") or s.get("corporate_name", ""),
            "Setor":     sector,
            "Preço":     _fmt_price(s.get("close_price")),
            "Var.Dia":   _fmt_pct(s.get("daily_change_pct")),
        }

        class_row = {"Ticker": s.get("ticker", ""), "Empresa": "", "Setor": "", "Preço": "", "Var.Dia": ""}

        # Score
        score = s.get("score")
        label = s.get("score_label", "")
        if score is None:
            display_row["Score"] = "⚠ Bancário"
            class_row["Score"] = "NA"
        else:
            display_row["Score"] = f"{score:.0f} — {label}"
            class_row["Score"] = label  # reused para cor

        # Indicadores com score
        for ind in SCORED_COLS_ORDER:
            col_name = INDICATOR_LABELS.get(ind, ind)
            cls, disp = classifications.get(ind, ("ND", "N/D"))
            display_row[col_name] = disp
            class_row[col_name] = cls

        # P/VP informativo
        pvp = s.get("pvp")
        display_row["P/VP"] = f"{pvp:.2f}x" if pvp is not None else "—"
        class_row["P/VP"] = ""

        rows_display.append(display_row)
        rows_class.append(class_row)

    display_df = pd.DataFrame(rows_display)
    class_df = pd.DataFrame(rows_class)
    return display_df, class_df


def _apply_styles(display_df: pd.DataFrame, class_df: pd.DataFrame):
    """Aplica cores de fundo às células dos indicadores."""

    # Mapeamento de faixa de score para cor de fundo
    score_bg = {
        "Excelente":     "#1b5e20",
        "Bom":           "#2e7d32",
        "Razoável":      "#7b5800",
        "Atenção":       "#bf360c",
        "Evitar":        "#7f0000",
        "Setor Bancário": "#37474f",
        "NA":            "#37474f",
    }

    # Colunas coloridas = Score + indicadores scored
    colored_cols = {"Score"} | {INDICATOR_LABELS.get(i, i) for i in SCORED_COLS_ORDER}

    def styler_fn(df: pd.DataFrame) -> pd.DataFrame:
        styles = pd.DataFrame("", index=df.index, columns=df.columns)
        for col in df.columns:
            if col not in colored_cols:
                continue
            col_in_class = col in class_df.columns
            for idx in df.index:
                cls = ""
                if col_in_class and idx in class_df.index:
                    try:
                        cls = class_df.at[idx, col] or ""
                    except (KeyError, ValueError):
                        cls = ""
                bg = score_bg.get(cls, "") if col == "Score" else BG_COLORS.get(cls, "")
                if bg:
                    styles.at[idx, col] = (
                        f"background-color: {bg}; color: #ffffff; "
                        "font-weight: 600; text-align: center"
                    )
        return styles

    return display_df.style.apply(styler_fn, axis=None)


# ────────────────────────────────────────────────────────────────
# Visão de detalhe de uma ação
# ────────────────────────────────────────────────────────────────

def _show_detail(s: dict):
    sector = s.get("sector", "")
    bank = sc.is_bank(sector)
    classifications = sc.classify_all(s)
    score = s.get("score")
    label = s.get("score_label", "")
    breakdown = s.get("breakdown", {})

    # ── Cabeçalho ──────────────────────────────────────────────
    c1, c2, c3 = st.columns([3, 2, 2])
    with c1:
        nome = s.get("corporate_name") or s.get("ticker", "")
        pregao = s.get("trade_name", "")
        st.markdown(f"## {pregao or nome}")
        st.caption(nome if pregao else "")
        st.markdown(f"**Setor:** {sector or '—'}")
        ref = s.get("reference_date", "")
        if ref:
            st.caption(f"Balanço de referência: {ref}")

    with c2:
        preco = s.get("close_price")
        var = s.get("daily_change_pct")
        if preco is not None:
            var_color = "#4caf50" if (var or 0) >= 0 else "#f44336"
            st.metric(
                "Preço Atual",
                _fmt_price(preco),
                delta=f"{var:+.2f}%" if var is not None else None,
            )
        st.metric("Market Cap", _fmt_mcap(s.get("market_cap")))

    with c3:
        low52 = s.get("week_52_low")
        high52 = s.get("week_52_high")
        ytd = s.get("ytd_return_pct")
        if low52 and high52:
            st.markdown(f"**52 sem:** {_fmt_price(low52)} — {_fmt_price(high52)}")
        if ytd is not None:
            st.markdown(f"**Retorno YTD:** {_fmt_pct(ytd)}")

    st.divider()

    # ── Score ───────────────────────────────────────────────────
    if bank:
        st.warning(
            "⚠️ **Setor bancário requer análise específica — score global não aplicável.**\n\n"
            "Para bancos, priorize P/VP (ideal 1,0×–2,5×), ROE, Índice de Basileia e inadimplência."
        )
    else:
        score_cor = SCORE_COLORS.get(label, "#9e9e9e")
        st.markdown(
            f"<h3 style='color:{score_cor}'>Score: {score:.0f}/100 — {label}</h3>",
            unsafe_allow_html=True,
        )

        # Barra de progresso geral
        st.progress(int(score) if score else 0)

    st.divider()

    # ── Gráfico de preço ────────────────────────────────────────
    with st.expander("📈 Gráfico de Preço Histórico", expanded=False):
        st.info(
            "Histórico de preços requer o **plano Pro** da Bolsai "
            "(endpoint `/stocks/{ticker}/history`). "
            "Faça upgrade em usebolsai.com para visualizar o gráfico."
        )

    # ── Indicadores com score ───────────────────────────────────
    st.subheader("Indicadores com Score")

    DESCS = {
        "net_debt_ebitda":  "Alavancagem: quanto tempo levaria para pagar a dívida líquida com o EBITDA.",
        "roe":              "Retorno sobre o Patrimônio Líquido — eficiência na geração de lucro.",
        "ev_ebitda":        "Múltiplo de valuation: valor da empresa vs. geração de caixa operacional.",
        "pl":               "Preço / Lucro — quanto o mercado paga por cada R$ 1 de lucro.",
        "ebitda_margin":    "Margem EBITDA — eficiência operacional (% da receita).",
        "cagr_earnings_5y": "Taxa composta de crescimento anual do lucro líquido nos últimos 5 anos.",
        "p_fcf":            "Preço / Fluxo de Caixa Livre (FCO − Capex). Requer plano Pro.",
        "dividend_yield":   "Dividend Yield TTM — rendimento em dividendos nos últimos 12 meses.",
        "liquidity":        "Volume médio diário estimado (vol. méd. 52 sem. × preço).",
        "cagr_revenue_5y":  "Taxa composta de crescimento anual da receita líquida nos últimos 5 anos.",
    }

    for ind in SCORED_COLS_ORDER:
        cls, disp = classifications.get(ind, ("ND", "N/D"))
        label_ind = INDICATOR_LABELS.get(ind, ind)
        emoji = COLOR_EMOJI.get(cls, "⬜")
        peso = INDICATOR_WEIGHTS[ind]
        bd = breakdown.get(ind, {})
        pts = bd.get("points")
        contrib = bd.get("contribution")

        bg = BG_COLORS.get(cls, "#37474f")

        with st.container():
            ca, cb, cc = st.columns([3, 2, 3])
            with ca:
                st.markdown(f"**{label_ind}** *(peso {peso*100:.0f}%)*")
                st.caption(DESCS.get(ind, ""))
            with cb:
                st.markdown(
                    f"<div style='background:{bg};color:#fff;padding:6px 12px;"
                    f"border-radius:6px;text-align:center;font-weight:700;font-size:1.05rem'>"
                    f"{emoji} {disp}</div>",
                    unsafe_allow_html=True,
                )
            with cc:
                if pts is not None and contrib is not None:
                    st.caption(f"Pontuação: {pts}/100 → contribuição: {contrib:.1f} pts")
                    st.progress(int(pts))
                elif cls in ("ND", "NA"):
                    st.caption("Não disponível — peso redistribuído entre demais indicadores")
        st.markdown("")

    # ── Indicadores informativos ────────────────────────────────
    st.divider()
    st.subheader("Indicadores Informativos")

    pvp = s.get("pvp")
    payout = s.get("payout")
    net_margin = s.get("net_margin")
    roa = s.get("roa")
    roic = s.get("roic")

    with st.container():
        st.markdown("#### P/VP — Preço / Valor Patrimonial")
        if bank:
            st.markdown(
                "**Indicador principal para bancos.** "
                "P/VP ideal entre **1,0× e 2,5×**."
            )
        if pvp is not None:
            st.markdown(f"**Valor:** {pvp:.2f}×")
            if pvp < 1.0:
                st.caption("< 1,0 — possível desconto patrimonial (verifique qualidade dos ativos).")
            elif pvp > 3.0:
                st.caption("> 3,0 — exige ROE muito alto para justificar o prêmio.")
        else:
            st.caption("N/D")

    with st.container():
        st.markdown("#### Payout (%)")
        if payout is not None:
            st.markdown(f"**Valor:** {payout:.1f}%")
            fcf = s.get("p_fcf")
            if payout > 80:
                st.caption(
                    "⚠️ Payout alto (> 80%). "
                    + ("Atenção: FCO/Capex indisponíveis (requer plano Pro) — verifique FCL manualmente." if fcf is None else "")
                )
        else:
            st.caption("N/D (calculado como DPS TTM × Ações / Lucro Líquido)")

    with st.container():
        st.markdown("#### Governança")
        st.caption(
            "Segmento de listagem e Tag Along não estão disponíveis no "
            "plano gratuito da API Bolsai. Consulte o site da B3 ou o "
            "Formulário de Referência (CVM) para essas informações."
        )

    if bank:
        with st.container():
            st.markdown("#### Índice de Basileia")
            st.caption(
                "Indicador regulatório de capital (mínimo: 11%; confortável: ≥ 14%). "
                "Não disponível na API Bolsai — consulte o Relatório de Administração "
                "ou o site do Banco Central do Brasil."
            )

    # ── Outros indicadores financeiros ─────────────────────────
    st.divider()
    with st.expander("📋 Outros indicadores", expanded=False):
        cols = st.columns(3)
        items = [
            ("Margem Líquida",  f"{net_margin:.1f}%" if net_margin is not None else "N/D"),
            ("ROA",             f"{roa:.1f}%" if roa is not None else "N/D"),
            ("ROIC",            f"{roic:.1f}%" if roic is not None else "N/D"),
            ("LPA",             f"R$ {s['lpa']:.2f}" if s.get("lpa") else "N/D"),
            ("VPA",             f"R$ {s['vpa']:.2f}" if s.get("vpa") else "N/D"),
            ("Liq. Corrente",   f"{s['current_ratio']:.2f}x" if s.get("current_ratio") else "N/D"),
            ("EBITDA (R$ mi)",  f"{s['ebitda']/1000:.0f}" if s.get("ebitda") else "N/D"),
            ("Rec. Líq. (R$ mi)", f"{s['net_revenue']/1000:.0f}" if s.get("net_revenue") else "N/D"),
            ("Lucro Líq. (R$ mi)", f"{s['net_income']/1000:.0f}" if s.get("net_income") else "N/D"),
        ]
        for i, (lbl, val) in enumerate(items):
            cols[i % 3].metric(lbl, val)


# ────────────────────────────────────────────────────────────────
# Aba Screener
# ────────────────────────────────────────────────────────────────

def _show_screener():
    st.markdown("## 🔎 Screener")
    st.info(
        "O Screener filtra todas as ~264 ações da B3 em tempo real usando o "
        "endpoint `/screener` da Bolsai. Este endpoint requer o **plano Pro** "
        "(R$ 29/mês). Os filtros abaixo estão preparados — ative-os após o upgrade."
    )

    disabled = True

    with st.form("screener_form"):
        c1, c2, c3 = st.columns(3)
        with c1:
            roe_min = st.slider("ROE mínimo (%)", 0, 50, 10, disabled=disabled)
            pl_max  = st.slider("P/L máximo (x)",  0, 50, 20, disabled=disabled)
            dy_min  = st.slider("DY mínimo (%)",    0, 20,  3, disabled=disabled)
        with c2:
            ev_max   = st.slider("EV/EBITDA máximo (x)", 0, 30, 12, disabled=disabled)
            mg_min   = st.slider("Margem EBITDA mín. (%)", 0, 50, 10, disabled=disabled)
            score_min = st.slider("Score mínimo", 0, 100, 50, disabled=disabled)
        with c3:
            sector_filter = st.selectbox("Setor", ["Todos"], disabled=disabled)

        submitted = st.form_submit_button(
            "🔍 Buscar na B3",
            disabled=True,
            help="Disponível no plano Pro da Bolsai",
        )

    if submitted:
        st.warning("Endpoint disponível apenas no plano Pro.")


# ────────────────────────────────────────────────────────────────
# Sidebar
# ────────────────────────────────────────────────────────────────

def _sidebar():
    with st.sidebar:
        st.markdown("# 📈 Análise B3")
        st.caption("Análise fundamentalista de ações brasileiras")
        st.divider()

        # ── Status da API Key (corrigido: lê st.secrets) ───────
        api_key = api._get_api_key()
        if api_key:
            st.success(f"API Key configurada ({api_key[:8]}…)", icon="🔑")
        else:
            st.error(
                "**BOLSAI_API_KEY não encontrada.**\n\n"
                "No Streamlit Cloud: vá em **Settings → Secrets** e adicione:\n"
                "```\nBOLSAI_API_KEY = \"sk_sua_chave\"\n```",
                icon="🚨",
            )

        # ── Exibir mensagens flash (persistidas entre reruns) ───
        # Estas são gravadas ANTES do st.rerun() e lidas no próximo ciclo
        if st.session_state.flash_success:
            st.success(st.session_state.flash_success)
            st.session_state.flash_success = ""
        for err in st.session_state.flash_errors:
            st.error(err)
        st.session_state.flash_errors = []

        # ── Painel de debug (mostra log + JSON bruto da última busca) ──
        if st.session_state.debug_log:
            with st.expander("🔧 Debug — última operação", expanded=True):
                for line in st.session_state.debug_log:
                    st.markdown(f"`{line}`")

                if st.session_state.debug_raw_fund:
                    st.markdown("**JSON completo de /fundamentals/{ticker}:**")
                    st.json(st.session_state.debug_raw_fund, expanded=True)

                if st.button("Limpar log", key="clear_debug"):
                    st.session_state.debug_log = []
                    st.session_state.debug_raw_fund = None
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
                # Não chama st.rerun() aqui — o warning aparece normalmente
                st.warning("Digite ao menos um ticker.")
            else:
                # Limpa log e mensagens anteriores
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

                # ── Salvar mensagens no session_state ANTES do rerun ──
                if adicionados:
                    st.session_state.flash_success = (
                        f"Adicionado(s) com sucesso: {', '.join(adicionados)}"
                    )
                st.session_state.flash_errors = erros
                # rerun → sidebar re-renderiza e exibe as mensagens flash
                st.rerun()

        st.divider()

        # ── Atualização ────────────────────────────────────────
        st.markdown("### Atualização")

        oldest_update = None
        for entry in st.session_state.acoes.values():
            ua = entry.get("updated_at")
            if ua:
                try:
                    dt = datetime.fromisoformat(ua)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if oldest_update is None or dt < oldest_update:
                        oldest_update = dt
                except Exception:
                    pass

        if oldest_update:
            ua_str = _fmt_updated(oldest_update.isoformat())
            cor = _staleness_color(oldest_update.isoformat())
            st.markdown(
                f"<span style='color:{cor};font-size:0.85rem'>"
                f"Última atualização: {ua_str}</span>",
                unsafe_allow_html=True,
            )
            age_h = (datetime.now(timezone.utc) - oldest_update).total_seconds() / 3600
            if age_h >= 48:
                st.caption("🔴 Dados com mais de 48h — recomenda-se atualizar.")
            elif age_h >= 24:
                st.caption("🟠 Dados com mais de 24h.")
        else:
            st.caption("Nenhum dado carregado ainda.")

        if st.button("🔄 Atualizar Todos", use_container_width=True,
                     disabled=not st.session_state.acoes):
            with st.spinner("Atualizando todos os tickers…"):
                erros = _update_all()
            # Persistir resultado antes do rerun
            st.session_state.flash_errors = erros
            if not erros:
                st.session_state.flash_success = "Todos os dados atualizados com sucesso!"
            st.rerun()

        # ── Uso da API ─────────────────────────────────────────
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

        st.divider()

        # ── Lista de ações salvas ──────────────────────────────
        st.markdown("### Ações Salvas")
        if not st.session_state.acoes:
            st.caption("Nenhuma ação salva. Adicione acima.")
        else:
            for ticker, entry in list(st.session_state.acoes.items()):
                data = entry.get("data", {})
                s, lbl, _ = sc.calculate_score({**data})
                score_str = f"{s:.0f}" if s is not None else "Ban."
                cor_score = SCORE_COLORS.get(lbl, "#9e9e9e")

                col_a, col_b, col_c = st.columns([3, 2, 1])
                with col_a:
                    if st.button(ticker, key=f"sel_{ticker}", use_container_width=True):
                        st.session_state.selected_ticker = ticker
                with col_b:
                    st.markdown(
                        f"<span style='color:{cor_score};font-size:0.9rem'>"
                        f"{score_str} {lbl[:4] if lbl else ''}</span>",
                        unsafe_allow_html=True,
                    )
                with col_c:
                    if st.button("✕", key=f"rm_{ticker}", help=f"Remover {ticker}"):
                        del st.session_state.acoes[ticker]
                        save_data(st.session_state.acoes)
                        if st.session_state.selected_ticker == ticker:
                            st.session_state.selected_ticker = None
                        st.rerun()


# ────────────────────────────────────────────────────────────────
# App principal
# ────────────────────────────────────────────────────────────────

def main():
    _init_state()
    _sidebar()

    # ── Sem dados ──────────────────────────────────────────────
    if not st.session_state.acoes:
        st.markdown("## Bem-vindo ao Analisador Fundamentalista B3")
        st.markdown(
            "Adicione tickers no painel à esquerda para começar. "
            "Cada ação é analisada com **10 indicadores fundamentalistas** "
            "ponderados em um score de **0 a 100**."
        )
        st.markdown(
            "**Fonte de dados:** [Bolsai](https://usebolsai.com) · "
            "**Plano gratuito:** 200 req/dia"
        )
        return

    # ── Enriquecer com scores ──────────────────────────────────
    enriched: list[dict] = []
    for ticker, entry in st.session_state.acoes.items():
        try:
            e = _enrich(entry)
            enriched.append(e)
        except Exception as ex:
            st.warning(f"Erro ao processar {ticker}: {ex}")

    # Ordenar por score (maior primeiro; bancos no final)
    enriched.sort(
        key=lambda x: (x.get("score") is not None, x.get("score") or -1),
        reverse=True,
    )

    # ── Tabs ───────────────────────────────────────────────────
    tab_comp, tab_det, tab_scr = st.tabs(["📊 Comparativo", "🔍 Detalhe", "🔎 Screener"])

    # ────────────────────────────────────────────────────────────
    # Tab 1 — Comparativo
    # ────────────────────────────────────────────────────────────
    with tab_comp:
        st.markdown("### Tabela Comparativa")
        st.caption(
            "Clique em uma linha para ver o detalhamento completo na aba **Detalhe**. "
            "Colunas coloridas por classificação fundamentalista."
        )

        display_df, class_df = _build_table(enriched)

        # Usar Ticker como índice para recuperar seleção
        tickers_ordered = display_df["Ticker"].tolist()

        # Remover coluna Ticker do display (já está no índice implícito)
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
                "Score":         st.column_config.TextColumn("Score", width="medium"),
                "Empresa":       st.column_config.TextColumn("Empresa", width="medium"),
                "Setor":         st.column_config.TextColumn("Setor", width="medium"),
                "Dív.Líq/EBITDA": st.column_config.TextColumn("Dív/EBITDA", width="small"),
                "ROE":           st.column_config.TextColumn("ROE", width="small"),
                "EV/EBITDA":     st.column_config.TextColumn("EV/EBITDA", width="small"),
                "P/L":           st.column_config.TextColumn("P/L", width="small"),
                "Mg. EBITDA":    st.column_config.TextColumn("Mg.EBITDA", width="small"),
                "CAGR Lucro 5a": st.column_config.TextColumn("CAGR Lucro", width="small"),
                "P/FCF":         st.column_config.TextColumn("P/FCF", width="small"),
                "Div. Yield":    st.column_config.TextColumn("DY", width="small"),
                "Liquidez":      st.column_config.TextColumn("Liquidez", width="small"),
                "CAGR Rec. 5a":  st.column_config.TextColumn("CAGR Rec.", width="small"),
                "P/VP":          st.column_config.TextColumn("P/VP", width="small"),
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

        # Legenda de cores
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

    # ────────────────────────────────────────────────────────────
    # Tab 2 — Detalhe
    # ────────────────────────────────────────────────────────────
    with tab_det:
        tickers_avail = [e["ticker"] for e in enriched]
        selected = st.session_state.selected_ticker

        # Selectbox para escolher ação
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
    # Tab 3 — Screener
    # ────────────────────────────────────────────────────────────
    with tab_scr:
        _show_screener()


if __name__ == "__main__":
    main()
