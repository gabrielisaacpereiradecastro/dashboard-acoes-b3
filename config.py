"""
Configurações centralizadas: pesos, limites por indicador, cores e classificações por setor.
"""

# Base URL da API Bolsai
BASE_URL = "https://api.usebolsai.com/api/v1"

# Pesos de cada indicador no score final (devem somar 1.0)
INDICATOR_WEIGHTS = {
    "net_debt_ebitda":  0.25,
    "roe":              0.20,
    "ev_ebitda":        0.15,
    "pl":               0.10,
    "ebitda_margin":    0.10,
    "cagr_earnings_5y": 0.05,
    "p_fcf":            0.05,
    "dividend_yield":   0.05,
    "liquidity":        0.05,
    "cagr_revenue_5y":  0.05,
}

# Pontos internos por classificação (0-100)
CLASS_POINTS = {
    "Excelente": 100,
    "Bom":       75,
    "Razoável":  50,
    "Atenção":   25,
    "Proibitivo": 0,
}

# Faixas de Score final e rótulos
SCORE_LEVELS = [
    (80, 101, "Excelente"),
    (60,  80, "Bom"),
    (40,  60, "Razoável"),
    (20,  40, "Atenção"),
    (0,   20, "Evitar"),
]

# Cores de fundo (CSS) para cada classificação — otimizadas para dark mode
BG_COLORS = {
    "Excelente":  "#1b5e20",
    "Bom":        "#2e7d32",
    "Razoável":   "#7b5800",
    "Atenção":    "#bf360c",
    "Proibitivo": "#7f0000",
    "NA":         "#37474f",
    "ND":         "#37474f",
}

# Emoji de cor para exibição rápida
COLOR_EMOJI = {
    "Excelente":  "🟢",
    "Bom":        "🟩",
    "Razoável":   "🟡",
    "Atenção":    "🟠",
    "Proibitivo": "🔴",
    "NA":         "⬜",
    "ND":         "⬜",
}

# Cor do texto do Score por faixa (hex, para st.markdown)
SCORE_COLORS = {
    "Excelente": "#4caf50",
    "Bom":       "#8bc34a",
    "Razoável":  "#ffc107",
    "Atenção":   "#ff9800",
    "Evitar":    "#f44336",
}

# ────────────────────────────────────────────────────────────────
# Identificação de setor
# ────────────────────────────────────────────────────────────────

BANK_KEYWORDS = [
    "banco", "bancos", "financeiro", "financeira",
    "bancário", "bancaria", "crédito", "credito",
]
UTILITY_KEYWORDS = [
    "energia elétrica", "energia eletrica", "saneamento",
    "concessão", "concessao", "transmissão", "transmissao",
    "distribuição", "distribuicao", "água", "agua",
    "gás", "gas canalizado", "utilities",
]
RETAIL_KEYWORDS = [
    "comércio varejista", "comercio varejista",
    "varejo", "comércio atacadista", "comercio atacadista",
    "supermercado", "hipermercado",
]

# Remapeamento manual de setor por ticker (corrige classificações incorretas da B3)
SECTOR_REMAP: dict[str, str] = {
    # Saúde
    "SMFT3": "Saúde e Bem-Estar",
    "PGMN3": "Farmácias e Drogarias",
    "DEXP3": "Farmácias e Drogarias",
    "RADL3": "Farmácias e Drogarias",
    "PNVL3": "Farmácias e Drogarias",
    "SBFG3": "Varejo Esportivo",
    "FLRY3": "Saúde - Diagnósticos",
    "DASA3": "Saúde - Diagnósticos",
    "HAPV3": "Saúde - Planos e Hospitais",
    # Metalurgia
    "GGBR4": "Metalurgia e Siderurgia",
    "CSNA3": "Metalurgia e Siderurgia",
    "USIM5": "Metalurgia e Siderurgia",
    # Shoppings
    "ALLOS3": "Shoppings e Centros Comerciais",
    "MULT3":  "Shoppings e Centros Comerciais",
    "IGTI11": "Shoppings e Centros Comerciais",
    "BRML3":  "Shoppings e Centros Comerciais",
    # Indústria
    "WEGE3": "Indústria - Máquinas e Equipamentos",
    # Locação de veículos
    "RENT3": "Locação de Veículos",
    "MOVI3": "Locação de Veículos",
    "LCAM3": "Locação de Veículos",
}

# ────────────────────────────────────────────────────────────────
# Nomes legíveis dos indicadores
# ────────────────────────────────────────────────────────────────

INDICATOR_LABELS = {
    "net_debt_ebitda":  "Dív.Líq/EBITDA",
    "roe":              "ROE",
    "ev_ebitda":        "EV/EBITDA",
    "pl":               "P/L",
    "ebitda_margin":    "Mg. EBITDA",
    "cagr_earnings_5y": "CAGR Lucro 5a",
    "p_fcf":            "P/FCF",
    "dividend_yield":   "Div. Yield",
    "liquidity":        "Liquidez",
    "cagr_revenue_5y":  "CAGR Rec. 5a",
    "pvp":              "P/VP",
    "net_margin":       "Mg. Líquida",
    "payout":           "Payout",
    "roa":              "ROA",
    "roic":             "ROIC",
}
