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
    "Excelente":    "#1b5e20",
    "Bom":          "#2e7d32",
    "Razoável":     "#7b5800",
    "Atenção":      "#bf360c",
    "Proibitivo":   "#7f0000",
    "Inconclusivo": "#4a3800",
    "NA":           "#37474f",
    "ND":           "#37474f",
    "Positivo":     "#1b5e20",
    "Negativo":     "#7f0000",
}

# Emoji de cor para exibição rápida
COLOR_EMOJI = {
    "Excelente":    "🟢",
    "Bom":          "🟩",
    "Razoável":     "🟡",
    "Atenção":      "🟠",
    "Proibitivo":   "🔴",
    "Inconclusivo": "⚠️",
    "NA":           "⬜",
    "ND":           "⬜",
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

# Setores cíclicos/commodities: FCL normalizado (média histórica) no DCF
SETORES_CICLICOS = [
    "petróleo", "petroleo", "petro",
    # NÃO incluir "gás"/"gas" soltos: geram falso-positivo em saneamento
    # ("Serv. Água e Gás"). Petróleo e Gás já é coberto por "petróleo"/"petro".
    "combustível", "combustivel",
    "mineração", "mineracao", "minério", "minerio",
    "extração mineral", "extracao mineral",  # VALE3 vem como "Extração Mineral"
    "metalurgia", "siderurgia",
    "papel e celulose", "celulose",
    "agricultura", "agropecuária", "agropecuaria",
    "açúcar", "acucar", "álcool", "alcool", "sucroalcooleiro",
    "carvão", "carvao",
]
UTILITY_KEYWORDS = [
    "energia elétrica", "energia eletrica", "saneamento",
    "concessão", "concessao", "transmissão", "transmissao",
    "distribuição", "distribuicao", "água", "agua",
    "gás", "gas canalizado", "utilities",
]

# Seguradoras: valuation por P/L × LPA (DCF de FCL não funciona p/ seguradora)
INSURER_KEYWORDS = [
    "seguradora", "seguradoras", "seguros", "seguridade", "resseguro",
]
# P/L justo de referência para seguradoras brasileiras estáveis (through-cycle).
# Validado vs BTG (jun/2026): PSSA3 ~0pp, BBSE3/CXSE3 residuais a refinar.
INSURER_FAIR_PE = 10.0

# Shoppings: valuation por EV/EBITDA (FCL distorcido por compra/venda de imóveis)
SHOPPING_KEYWORDS = [
    "shopping", "centros comerciais",
]
# EV/EBITDA justo through-cycle para shoppings brasileiros.
# Validado vs BTG (jun/2026): ALOS3 ~6pp, IGTI11 ~15pp, MULT3 residual (premium).
SHOPPING_FAIR_EV_EBITDA = 10.5
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
    "RADL3": "Farmácias e Drogarias",
    "PNVL3": "Farmácias e Drogarias",
    "SBFG3": "Varejo Esportivo",
    "FLRY3": "Saúde - Diagnósticos",
    "DASA3": "Saúde - Diagnósticos",
    "HAPV3": "Saúde - Planos e Hospitais",
    "BALM4": "Saúde - Equipamentos Médicos",  # Baumer (era "Metalurgia" na B3)
    # Química
    "DEXP3": "Produtos Químicos",  # Dexxos/Elekeiroz (estava errado como Farmácia)
    # Metalurgia
    "GGBR4": "Metalurgia e Siderurgia",
    "CSNA3": "Metalurgia e Siderurgia",
    "USIM5": "Metalurgia e Siderurgia",
    # Shoppings
    "ALOS3":  "Shoppings e Centros Comerciais",  # Allos (ticker atual)
    "ALLOS3": "Shoppings e Centros Comerciais",  # legado
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
    "psr":              "PSR",
    "net_margin":       "Mg. Líquida",
    "payout":           "Payout",
    "roa":              "ROA",
    "roic":             "ROIC",
}
