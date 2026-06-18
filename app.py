"""
App principal — Análise Fundamentalista B3
Fonte de dados: API Bolsai (usebolsai.com)
"""
from __future__ import annotations

import json
import time
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
    SCORE_COLORS, SECTOR_REMAP,
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
        "atencao": "P/L negativo significa prejuízo. P/L abaixo de 5 pode indicar empresa em declínio ou resultado não-recorrente.",
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
}


# ────────────────────────────────────────────────────────────────
# Persistência
# ────────────────────────────────────────────────────────────────

def load_data() -> dict:
    if DATA_FILE.exists():
        try:
            data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
        # Aplica SECTOR_REMAP nas ações já salvas para corrigir setores sem rebuscar
        for ticker, entry in data.items():
            if ticker in SECTOR_REMAP and isinstance(entry.get("data"), dict):
                entry["data"]["sector"] = SECTOR_REMAP[ticker]
        return data
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
    if "flash_errors" not in st.session_state:
        st.session_state.flash_errors: list[str] = []
    if "flash_success" not in st.session_state:
        st.session_state.flash_success: str = ""
    if "debug_log" not in st.session_state:
        st.session_state.debug_log: list[str] = []
    if "debug_raw_fund" not in st.session_state:
        st.session_state.debug_raw_fund: Optional[dict] = None


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

    st.session_state.acoes[t] = {
        "data": data,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    save_data(st.session_state.acoes)
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

def _enrich(entry: dict) -> dict:
    stock = entry["data"]
    s, label, breakdown = sc.calculate_score(stock)
    return {**stock, "score": s, "score_label": label, "breakdown": breakdown}


# ────────────────────────────────────────────────────────────────
# Construção da tabela comparativa
# ────────────────────────────────────────────────────────────────

def _build_table(stocks: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows_display = []
    rows_class = []

    for s in stocks:
        sector = s.get("sector", "")
        classifications = sc.classify_all(s)

        ref_date = s.get("reference_date", "")
        display_row = {
            "Ticker":   s.get("ticker", ""),
            "Empresa":  s.get("trade_name") or s.get("corporate_name", ""),
            "Setor":    sector,
            "Balanço":  _fmt_quarter(ref_date),
            "Preço":    _fmt_price(s.get("close_price")),
            "Var.Dia":  _fmt_pct(s.get("daily_change_pct")),
        }
        class_row = {
            "Ticker": s.get("ticker", ""), "Empresa": "", "Setor": "",
            "Balanço": _quarter_staleness(ref_date), "Preço": "", "Var.Dia": "",
        }

        score = s.get("score")
        label = s.get("score_label", "")
        if score is None:
            display_row["Score"] = "⚠ Bancário"
            class_row["Score"] = "NA"
        else:
            display_row["Score"] = f"{score:.0f} — {label}"
            class_row["Score"] = label

        for ind in SCORED_COLS_ORDER:
            col_name = INDICATOR_LABELS.get(ind, ind)
            cls, disp = classifications.get(ind, ("ND", "N/D"))
            display_row[col_name] = disp
            class_row[col_name] = cls

        pvp = s.get("pvp")
        cls_pvp, disp_pvp = sc.classify_pvp(pvp, sector)
        display_row["P/VP"] = disp_pvp
        class_row["P/VP"] = cls_pvp

        rows_display.append(display_row)
        rows_class.append(class_row)

    return pd.DataFrame(rows_display), pd.DataFrame(rows_class)


def _apply_styles(display_df: pd.DataFrame, class_df: pd.DataFrame):
    score_bg = {
        "Excelente":      "#1b5e20",
        "Bom":            "#2e7d32",
        "Razoável":       "#7b5800",
        "Atenção":        "#bf360c",
        "Evitar":         "#7f0000",
        "Setor Bancário": "#37474f",
        "NA":             "#37474f",
    }
    colored_cols = {"Score", "P/VP", "Balanço"} | {INDICATOR_LABELS.get(i, i) for i in SCORED_COLS_ORDER}

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
        breakdown = stock.get("breakdown", {})
        values = []
        for ind in RADAR_INDICATORS:
            bd = breakdown.get(ind, {})
            pts = bd.get("points")
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
    is_util    = any(k in s for k in ["energ", "saneamento", "concess", "transmiss", "distribui", "utilit", "gás", "agua", "água"])
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
        st.progress(int(score) if score else 0)

    st.divider()

    # ── Gráfico de preço (52 semanas) ──────────────────────────
    fig_price = _price_range_chart(s)
    if fig_price:
        st.plotly_chart(fig_price, use_container_width=True, config={"displayModeBar": False})
        st.caption(
            "📌 Histórico de preços detalhado (1M/3M/6M/1A) requer plano Pro da Bolsai "
            "(`/stocks/{ticker}/history`). O gráfico acima usa dados de 52 semanas do plano Free."
        )
    else:
        st.info("Dados de intervalo 52 semanas indisponíveis para esta ação.")

    # ── Indicadores com score ───────────────────────────────────
    st.divider()
    st.subheader("Indicadores com Score")

    for ind in SCORED_COLS_ORDER:
        cls, disp = classifications.get(ind, ("ND", "N/D"))
        label_ind = INDICATOR_LABELS.get(ind, ind)
        emoji = COLOR_EMOJI.get(cls, "⬜")
        peso = INDICATOR_WEIGHTS[ind]
        bd = breakdown.get(ind, {})
        pts = bd.get("points")
        contrib = bd.get("contribution")
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
                if pts is not None and contrib is not None:
                    st.caption(f"Pontuação: {pts}/100 → contribuição: {contrib:.1f} pts")
                    st.progress(int(pts))
                elif cls in ("ND", "NA"):
                    st.caption("Não disponível — peso redistribuído entre demais indicadores")
        st.markdown("")

    # ── Radar dos 6 indicadores principais ─────────────────────
    if not bank:
        st.divider()
        st.subheader("Perfil Radar")
        st.caption("Pontuação (0–100) nos 6 indicadores de maior peso.")
        fig_radar = _radar_chart([s], [s.get("ticker", "")])
        st.plotly_chart(fig_radar, use_container_width=True, config={"displayModeBar": False})

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
                f"padding:6px 14px;border-radius:6px;font-weight:700;font-size:1.05rem'>"
                f"{emoji_pvp} {disp_pvp}</div>",
                unsafe_allow_html=True,
            )
            if pvp < 1.0:
                st.caption("Abaixo do valor patrimonial — pode ser desconto real ou sinalizar problema de qualidade dos ativos.")
            elif pvp > 3.0:
                st.caption("⚠ Exige ROE muito alto para justificar o prêmio.")
        else:
            st.caption("N/D")

    with st.container():
        st.markdown("#### Payout (%)")
        if payout is not None:
            st.markdown(f"**Valor:** {payout:.1f}%")
            if payout > 80:
                st.caption("⚠️ Payout alto (> 80%). Verifique sustentabilidade com FCL.")
        else:
            st.caption("N/D (requer dados de dividendos — plano Pro)")

    with st.container():
        st.markdown("#### Governança")
        st.caption(
            "Segmento de listagem e Tag Along não estão disponíveis no plano gratuito. "
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
    _notas_key = f"notas_{_ticker}"

    _saved_data = load_data()
    _notas_entry = _saved_data.get(_ticker, {})
    _notas_text = _notas_entry.get("notas", "")
    _notas_updated = _notas_entry.get("notas_updated_at", "")

    # Inicializa session_state com o valor salvo (apenas na primeira renderização do ticker)
    if _notas_key not in st.session_state:
        st.session_state[_notas_key] = _notas_text

    def _save_notas(_key=_notas_key, _t=_ticker):
        new_text = st.session_state[_key]
        d = load_data()
        if _t in d:
            d[_t]["notas"] = new_text
            d[_t]["notas_updated_at"] = datetime.now(timezone.utc).isoformat()
            save_data(d)

    st.text_area(
        "Observações sobre esta ação:",
        key=_notas_key,
        on_change=_save_notas,
        height=120,
        placeholder="Escreva sua tese, lembretes ou observações sobre esta ação…",
    )
    if _notas_updated:
        try:
            _dt = datetime.fromisoformat(_notas_updated).astimezone()
            st.caption(f"Última edição: {_dt.strftime('%d/%m/%Y %H:%M')}")
        except Exception:
            st.caption(f"Última edição: {_notas_updated[:16]}")

    # ── Outros indicadores ─────────────────────────────────────
    st.divider()
    with st.expander("📋 Outros indicadores", expanded=False):
        cols = st.columns(3)
        items = [
            ("Margem Líquida",      f"{net_margin:.1f}%" if net_margin is not None else "N/D"),
            ("ROA",                 f"{roa:.1f}%" if roa is not None else "N/D"),
            ("ROIC",                f"{roic:.1f}%" if roic is not None else "N/D"),
            ("LPA",                 f"R$ {s['lpa']:.2f}" if s.get("lpa") else "N/D"),
            ("VPA",                 f"R$ {s['vpa']:.2f}" if s.get("vpa") else "N/D"),
            ("Liq. Corrente",       f"{s['current_ratio']:.2f}x" if s.get("current_ratio") else "N/D"),
            ("EBITDA (R$ mi)",      f"{s['ebitda']/1000:.0f}" if s.get("ebitda") else "N/D"),
            ("Rec. Líq. (R$ mi)",   f"{s['net_revenue']/1000:.0f}" if s.get("net_revenue") else "N/D"),
            ("Lucro Líq. (R$ mi)",  f"{s['net_income']/1000:.0f}" if s.get("net_income") else "N/D"),
        ]
        for i, (lbl, val) in enumerate(items):
            cols[i % 3].metric(lbl, val)


# ────────────────────────────────────────────────────────────────
# Tabela comparativa lado a lado (HTML com cores)
# ────────────────────────────────────────────────────────────────

def _comparison_table(selected_tickers: list[str], stocks: list[dict]) -> None:
    """Renderiza tabela indicador × ação com células coloridas por classificação."""
    all_inds = list(SCORED_COLS_ORDER) + ["pvp"]

    th = "padding:8px 10px;color:#e8eaf6;border-bottom:2px solid #333;background:#1a1d2e;font-weight:600"
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
            ev_max    = st.slider("EV/EBITDA máximo (x)", 0, 30, 12, disabled=disabled)
            mg_min    = st.slider("Margem EBITDA mín. (%)", 0, 50, 10, disabled=disabled)
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

        # ── Mensagens flash ────────────────────────────────────
        if st.session_state.flash_success:
            _ph = st.empty()
            _ph.success(st.session_state.flash_success)
            st.session_state.flash_success = ""
            time.sleep(3)
            _ph.empty()
        for err in st.session_state.flash_errors:
            st.error(err)
        st.session_state.flash_errors = []

        # ── Diagnóstico (colapsado por padrão) ────────────────
        with st.expander("🔧 Diagnóstico", expanded=False):
            if st.session_state.debug_log:
                for line in st.session_state.debug_log:
                    st.markdown(f"`{line}`")
                if st.session_state.debug_raw_fund:
                    st.markdown("**JSON completo de /fundamentals/{ticker}:**")
                    st.json(st.session_state.debug_raw_fund, expanded=False)
                if st.button("Limpar log", key="clear_debug"):
                    st.session_state.debug_log = []
                    st.session_state.debug_raw_fund = None
                    st.rerun()
            else:
                st.caption("Nenhuma operação registrada.")

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
                        f"Adicionado(s) com sucesso: {', '.join(adicionados)}"
                    )
                st.session_state.flash_errors = erros
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
    st.markdown("""
<style>
#MainMenu {visibility: hidden;}
header {visibility: hidden;}
.stDeployButton {display: none;}
[data-testid="stToolbar"] {display: none;}
[data-testid="stDecoration"] {display: none;}
footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)
    _init_state()
    _sidebar()

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

    enriched: list[dict] = []
    for ticker, entry in st.session_state.acoes.items():
        try:
            e = _enrich(entry)
            enriched.append(e)
        except Exception as ex:
            st.warning(f"Erro ao processar {ticker}: {ex}")

    enriched.sort(
        key=lambda x: (x.get("score") is not None, x.get("score") or -1),
        reverse=True,
    )

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

    tab_comp, tab_det, tab_scr = st.tabs(["📊 Comparativo", "🔍 Detalhe", "🔎 Screener"])

    # ────────────────────────────────────────────────────────────
    # Tab 1 — Comparativo
    # ────────────────────────────────────────────────────────────
    with tab_comp:
        st.markdown("### Tabela Comparativa")

        # ── Multiselect para radar (acima da tabela) ───────────
        tickers_list = [e["ticker"] for e in enriched]
        selected_compare = st.multiselect(
            "Selecione 2 a 4 ações para comparar no radar:",
            tickers_list,
            max_selections=4,
            placeholder="Escolha as ações…",
        )

        st.caption(
            "Clique em uma linha para ver o detalhamento completo na aba **Detalhe**. "
            "Colunas coloridas por classificação fundamentalista."
        )

        display_df, class_df = _build_table(enriched)
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
                "Score":           st.column_config.TextColumn("Score", width="medium"),
                "Empresa":         st.column_config.TextColumn("Empresa", width="medium"),
                "Setor":           st.column_config.TextColumn("Setor", width="medium"),
                "Balanço":         st.column_config.TextColumn("Balanço", width="small"),
                "Dív.Líq/EBITDA":  st.column_config.TextColumn("Dív/EBITDA", width="small"),
                "ROE":             st.column_config.TextColumn("ROE", width="small"),
                "EV/EBITDA":       st.column_config.TextColumn("EV/EBITDA", width="small"),
                "P/L":             st.column_config.TextColumn("P/L", width="small"),
                "Mg. EBITDA":      st.column_config.TextColumn("Mg.EBITDA", width="small"),
                "CAGR Lucro 5a":   st.column_config.TextColumn("CAGR Lucro", width="small"),
                "P/FCF":           st.column_config.TextColumn("P/FCF", width="small"),
                "Div. Yield":      st.column_config.TextColumn("DY", width="small"),
                "Liquidez":        st.column_config.TextColumn("Liquidez", width="small"),
                "CAGR Rec. 5a":    st.column_config.TextColumn("CAGR Rec.", width="small"),
                "P/VP":            st.column_config.TextColumn("P/VP", width="small"),
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

        # ── Radar comparativo (auto-render quando ≥ 2 selecionadas) ──
        if len(selected_compare) >= 2:
            st.divider()
            st.markdown("#### Radar Comparativo")
            stocks_compare = [
                next(e for e in enriched if e["ticker"] == t)
                for t in selected_compare
            ]
            banks_in = [
                t for t in selected_compare
                if sc.is_bank(
                    next(e for e in enriched if e["ticker"] == t).get("sector", "")
                )
            ]
            if banks_in:
                st.caption(
                    f"⚠ {', '.join(banks_in)}: setor bancário — "
                    "pontuação zero no radar (score não calculado para bancos)."
                )
            fig_compare = _radar_chart(stocks_compare, selected_compare)
            st.plotly_chart(fig_compare, use_container_width=True,
                            config={"displayModeBar": False})
            st.markdown("##### Valores por indicador")
            _comparison_table(selected_compare, stocks_compare)
        elif len(selected_compare) == 1:
            st.caption("Selecione ao menos 2 ações para ver o radar comparativo.")

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
    # Tab 3 — Screener
    # ────────────────────────────────────────────────────────────
    with tab_scr:
        _show_screener()


if __name__ == "__main__":
    main()
