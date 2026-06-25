"""
Configurações centralizadas: pesos, limites por indicador, cores e classificações por setor.
"""

# Base URL da API Bolsai
BASE_URL = "https://api.usebolsai.com/api/v1"

# ────────────────────────────────────────────────────────────────
# Scores SEPARADOS: Qualidade (negócio) × Preço (valuation)
# ────────────────────────────────────────────────────────────────

# Não-bancos
QUALITY_WEIGHTS = {
    "roe":              0.30,
    "net_debt_ebitda":  0.25,
    "ebitda_margin":    0.20,
    "cagr_earnings_5y": 0.15,
    "cagr_revenue_5y":  0.10,
}
PRICE_WEIGHTS = {          # score alto = barata/atrativa
    "ev_ebitda": 0.40,
    "pl":        0.35,
    "p_fcf":     0.25,
}
# Bancos (métricas próprias)
QUALITY_WEIGHTS_BANK = {
    "roe":              0.50,
    "cagr_earnings_5y": 0.30,
    "cagr_revenue_5y":  0.20,
}
PRICE_WEIGHTS_BANK = {
    "pvp": 0.60,
    "pl":  0.40,
}
# Seguradoras: como bancos, ROE é o eixo de qualidade; mas o Preço se ancora
# no P/L (EV/EBITDA não se aplica; P/VP é naturalmente alto por serem
# asset-light com ROE altíssimo → entra com peso menor e curva própria).
QUALITY_WEIGHTS_INSURER = {
    "roe":              0.60,
    "cagr_earnings_5y": 0.25,
    "cagr_revenue_5y":  0.15,
}
PRICE_WEIGHTS_INSURER = {
    "pl":  0.70,
    "pvp": 0.30,
}

# Limiar "bom/barato" para a cor do diagnóstico (≥)
SCORE_GOOD_THRESHOLD = 55

# Graduação dos scores (5 níveis): (limite_min, rótulo)
QUALITY_TIERS = [
    (85, "Excelente"),
    (70, "Ótima"),
    (55, "Boa"),
    (40, "Razoável"),
    (0,  "Fraca"),
]
PRICE_TIERS = [
    (85, "Pechincha"),
    (70, "Muito barata"),
    (55, "Barata"),
    (40, "Justa"),
    (0,  "Cara"),
]

# Cor do diagnóstico pelo "veredito" 2×2 (Qualidade × Preço)
VERDICT_COLORS = {
    "boa_barata":   "#1b5e20",  # boa+barata = oportunidade
    "boa_cara":     "#7b5800",  # boa+cara
    "fraca_barata": "#bf360c",  # barata mas fraca = ⚠ value trap
    "fraca_cara":   "#7f0000",  # fraca+cara
}

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
    "DMVF3": "Farmácias e Drogarias",  # d1000 Varejo Farma (era "Comércio Varejista")
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
