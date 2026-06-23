# -*- coding: utf-8 -*-
"""Gera o PDF de metodologia de cálculo de preço-alvo do app."""
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_JUSTIFY, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, HRFlowable,
)

AZUL = colors.HexColor("#1f3a5f")
AZUL2 = colors.HexColor("#2e5c8a")
CINZA = colors.HexColor("#444444")
CINZACLARO = colors.HexColor("#eef2f7")
VERDE = colors.HexColor("#1b5e20")

styles = getSampleStyleSheet()
styles.add(ParagraphStyle("Titulo", parent=styles["Title"], fontSize=22,
                          textColor=AZUL, spaceAfter=6, leading=26))
styles.add(ParagraphStyle("Sub", parent=styles["Normal"], fontSize=11,
                          textColor=CINZA, alignment=TA_CENTER, spaceAfter=2))
styles.add(ParagraphStyle("H1", parent=styles["Heading1"], fontSize=15,
                          textColor=AZUL, spaceBefore=16, spaceAfter=6, leading=18))
styles.add(ParagraphStyle("H2", parent=styles["Heading2"], fontSize=12.5,
                          textColor=AZUL2, spaceBefore=10, spaceAfter=4, leading=15))
styles.add(ParagraphStyle("Body", parent=styles["Normal"], fontSize=10.3,
                          alignment=TA_JUSTIFY, leading=15, spaceAfter=6, textColor=CINZA))
styles.add(ParagraphStyle("Formula", parent=styles["Normal"], fontName="Courier-Bold",
                          fontSize=10.5, textColor=AZUL, backColor=CINZACLARO,
                          borderPadding=7, spaceBefore=4, spaceAfter=8, leading=14))
styles.add(ParagraphStyle("Nota", parent=styles["Normal"], fontSize=9.2,
                          textColor=colors.HexColor("#7a4a00"), leading=13,
                          spaceAfter=6, leftIndent=6))
styles.add(ParagraphStyle("Cell", parent=styles["Normal"], fontSize=9.2, leading=12))
styles.add(ParagraphStyle("CellB", parent=styles["Normal"], fontSize=9.2, leading=12,
                          fontName="Helvetica-Bold", textColor=colors.white))

def P(t, s="Body"): return Paragraph(t, styles[s])
def hr(): return HRFlowable(width="100%", thickness=0.7, color=colors.HexColor("#c8d2e0"),
                            spaceBefore=4, spaceAfter=8)

def tabela(dados, larguras, header=True):
    body = [[Paragraph(c, styles["CellB"] if (header and i == 0) else styles["Cell"])
             for c in row] for i, row in enumerate(dados)]
    t = Table(body, colWidths=larguras, hAlign="LEFT")
    est = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#c8d2e0")),
        ("ROWBACKGROUNDS", (0, 1 if header else 0), (-1, -1),
         [colors.white, CINZACLARO]),
    ]
    if header:
        est.append(("BACKGROUND", (0, 0), (-1, 0), AZUL))
    t.setStyle(TableStyle(est))
    return t

story = []

# ── Capa / cabeçalho ────────────────────────────────────────────────
story.append(Spacer(1, 8))
story.append(P("Como o app calcula o Preço-Alvo", "Titulo"))
story.append(P("Análise Fundamentalista B3 — Metodologia de Valuation por setor", "Sub"))
story.append(P("Documento técnico · junho/2026 (rev. 2 — ROE normalizado dos bancos)", "Sub"))
story.append(Spacer(1, 8))
story.append(hr())

# ── 1. Filosofia ────────────────────────────────────────────────────
story.append(P("1. Por que um motor híbrido", "H1"))
story.append(P(
    "Não existe um único método de valuation que funcione bem para todos os tipos de empresa. "
    "Um banco, uma seguradora, uma mineradora e um shopping geram e usam caixa de formas "
    "radicalmente diferentes. Por isso o app <b>não usa um modelo único</b>: ele identifica o "
    "setor de cada ação e aplica o método que o mercado profissional de fato usa para aquele setor."))
story.append(P(
    "Historicamente o app usava Fluxo de Caixa Descontado (DCF) sobre o Fluxo de Caixa Livre "
    "para tudo. Isso produzia distorções graves — em testes, gerava potencial de +600% para a "
    "Petrobras e +850% para a Caixa Seguridade, porque o FCL de um único ano é um péssimo "
    "ponto de partida para esses casos. A solução foi o <b>motor híbrido por setor</b> descrito "
    "abaixo, calibrado contra preços-alvo de uma casa de research profissional (BTG Pactual)."))

story.append(P("Resumo: qual método cada setor usa", "H2"))
story.append(tabela([
    ["Setor", "Método", "Métrica-base"],
    ["Bancos", "Gordon Growth (P/VP justificado)", "ROE, VPA"],
    ["Seguradoras", "Múltiplo de Lucro (P/L)", "LPA"],
    ["Shoppings", "Múltiplo EV/EBITDA", "EBITDA"],
    ["Cíclicas (commodities)", "EV/EBITDA through-cycle", "EBITDA normalizado"],
    ["Utilities (reguladas)", "Fluxo de Caixa Descontado (DCF)", "FCL"],
    ["Demais (consumo, indústria...)", "EV/EBITDA por sub-setor", "EBITDA"],
], [5.2*cm, 7.4*cm, 4.2*cm]))

# ── 2. Como ler ─────────────────────────────────────────────────────
story.append(P("2. Como ler o resultado", "H1"))
story.append(P(
    "Todo preço-alvo é exibido como uma <b>faixa de três cenários</b>, nunca um número único — "
    "porque valuation depende de premissas, e premissas têm incerteza:"))
story.append(P(
    "• <b>Conservador</b> — premissa mais cautelosa (múltiplo ou crescimento reduzido).<br/>"
    "• <b>Base / Esperado</b> — o cenário central. É este que alimenta a coluna "
    "<b>“Potencial”</b> na tabela comparativa.<br/>"
    "• <b>Otimista</b> — premissa mais favorável."))
story.append(P(
    "Cada cenário mostra o preço justo e o potencial (%) frente à cotação atual, em verde se for "
    "alta e vermelho se for queda. Quando o método tem confiabilidade reduzida para aquele caso, "
    "aparece um <b>selo laranja de baixa confiança</b> (ver seção 9). Todos os parâmetros "
    "(múltiplo, WACC, crescimento) são <b>editáveis por sliders</b> na aba Detalhe — o usuário "
    "pode testar as próprias premissas."))

story.append(PageBreak())

# ── 3. Bancos ───────────────────────────────────────────────────────
story.append(P("3. Bancos — Gordon Growth (P/VP justificado)", "H1"))
story.append(P(
    "Para bancos não se usa DCF de fluxo de caixa: o “caixa” de um banco é o próprio negócio "
    "(intermediação financeira), e o que importa é a rentabilidade sobre o patrimônio. O método "
    "padrão é o <b>P/VP justificado pelo ROE</b>, derivado do modelo de Gordon:"))
story.append(Paragraph(
    "P/VP justo = (ROE &minus; g) / (Ke &minus; g)<br/>"
    "Preço-Alvo = P/VP justo &times; VPA", styles["Formula"]))
story.append(P(
    "Onde <b>ROE</b> é o retorno sobre o patrimônio, <b>VPA</b> o valor patrimonial por ação, "
    "<b>g</b> o crescimento perpétuo dos lucros e <b>Ke</b> o custo do capital próprio. A lógica: "
    "um banco que rende ROE acima do seu custo de capital (Ke) vale mais que 1× o patrimônio; "
    "quanto maior o spread (ROE &minus; Ke), maior o P/VP justo."))
story.append(P("Dois refinamentos importantes", "H2"))
story.append(P(
    "• <b>ROE normalizado</b> — em vez do ROE do último trimestre (que pode estar atípico, como "
    "o Banco do Brasil caindo a 6,6% na crise do agro de 2025-26), usa-se o <b>maior valor entre "
    "o ROE atual e a mediana dos últimos 8 trimestres</b>. Isso suaviza um trimestre ruim sem "
    "rebaixar bancos cujo ROE atual já é saudável."))
story.append(P(
    "• <b>Ke por tipo de banco</b> — <b>12%</b> para bancos privados grandes; <b>15%</b> para "
    "bancos <b>estatais</b> (Banco do Brasil etc.), refletindo o prêmio de risco de governança e "
    "interferência política que justifica o desconto persistente desses papéis."))
story.append(P("Parâmetros", "H2"))
story.append(tabela([
    ["Parâmetro", "Valor", "Racional"],
    ["ROE", "máx(atual, mediana de 8 trim.)", "suaviza trimestre atípico"],
    ["Ke — bancos privados", "12%", "Selic + prêmio de risco bancário"],
    ["Ke — bancos estatais", "15%", "+ prêmio de governança"],
    ["g (crescimento perpétuo)", "4%", "≈ infl. + cresc. real de longo prazo"],
    ["Conservador", "Ke ×1,08 · g ×0,7", "desconto sobre o spread"],
], [5.0*cm, 5.6*cm, 6.2*cm]))
story.append(P(
    "<b>Exemplo (ilustrativo):</b> um banco privado com ROE 21%, VPA R$ 20, Ke 12% e g 4% tem "
    "P/VP justo = (0,21 &minus; 0,04) / (0,12 &minus; 0,04) = 2,1×, logo Preço-Alvo = "
    "2,1 &times; R$ 20 = R$ 42.", "Nota"))

# ── 4. Seguradoras ──────────────────────────────────────────────────
story.append(P("4. Seguradoras — Múltiplo de Lucro (P/L)", "H1"))
story.append(P(
    "O fluxo de caixa de uma seguradora é distorcido pelo <i>float</i> (o dinheiro dos prêmios "
    "que ela detém antes de pagar sinistros), então DCF de FCL não funciona. O mercado avalia "
    "seguradoras por <b>múltiplo de lucro</b>:"))
story.append(Paragraph(
    "Preço-Alvo = P/L justo &times; LPA", styles["Formula"]))
story.append(P(
    "Onde <b>LPA</b> é o lucro por ação. O app usa um <b>P/L justo de referência de 10×</b>, um "
    "patamar through-cycle defensável para seguradoras brasileiras estáveis. Os cenários "
    "Conservador/Otimista aplicam 0,85× e 1,15× sobre esse múltiplo.", "Body"))

# ── 5. Shoppings ────────────────────────────────────────────────────
story.append(P("5. Shoppings — Múltiplo EV/EBITDA", "H1"))
story.append(P(
    "O caixa de um shopping é distorcido por compra e venda de empreendimentos, então usa-se "
    "EV/EBITDA, padrão do setor imobiliário de tijolo:"))
story.append(Paragraph(
    "EV justo = múltiplo &times; EBITDA<br/>"
    "Preço-Alvo = (EV justo &minus; Dívida Líquida) / Nº de ações", styles["Formula"]))
story.append(P(
    "<b>EV</b> (Enterprise Value) é o valor da empresa toda; subtraindo a dívida líquida chega-se "
    "ao valor do patrimônio (equity), que dividido pelo número de ações dá o preço justo. O app "
    "usa <b>10,5×</b> de EV/EBITDA through-cycle para shoppings brasileiros."))

story.append(PageBreak())

# ── 6. Cíclicas ─────────────────────────────────────────────────────
story.append(P("6. Cíclicas (commodities) — EV/EBITDA through-cycle", "H1"))
story.append(P(
    "Petróleo, mineração, siderurgia, celulose e agro têm resultados que oscilam violentamente "
    "com o preço da commodity. O método de mercado é EV/EBITDA com um <b>múltiplo baixo "
    "(through-cycle)</b> — e o ponto-chave é que <b>esse múltiplo baixo JÁ É o desconto de "
    "ciclicidade</b>. É por isso que cíclicas negociam a 4–7× EBITDA, e não a 12×."))
story.append(Paragraph(
    "EBITDA base = máx(EBITDA atual, EBITDA mid-cycle)<br/>"
    "Preço-Alvo = (múltiplo &times; EBITDA base &minus; Dívida Líquida) / Nº de ações",
    styles["Formula"]))
story.append(P(
    "O <b>EBITDA mid-cycle</b> (médio do ciclo) é estimado pela mediana do EBIT histórico "
    "(últimos até 10 anos) convertida para EBITDA pela razão EBITDA/EBIT atual. Usa-se o "
    "<b>maior</b> entre o EBITDA atual e o mid-cycle: nunca se normaliza para baixo (isso "
    "descontaria o ciclo duas vezes), mas a mediana protege quando a empresa está num vale "
    "temporário do ciclo."))
story.append(P("Múltiplos through-cycle por sub-setor", "H2"))
story.append(tabela([
    ["Sub-setor", "EV/EBITDA"],
    ["Petróleo e Gás", "5,0×"],
    ["Mineração", "6,0×"],
    ["Siderurgia / Metalurgia", "6,5×"],
    ["Papel e Celulose", "7,0×"],
    ["Agro / Açúcar e Álcool", "5,0×"],
], [9.0*cm, 3.5*cm]))

# ── 7. Utilities ────────────────────────────────────────────────────
story.append(P("7. Utilities (reguladas) — Fluxo de Caixa Descontado", "H1"))
story.append(P(
    "Empresas de energia elétrica e saneamento têm fluxo de caixa <b>previsível e regulado</b> "
    "(tarifas definidas pela ANEEL/ANA, indexadas à inflação). Para elas o DCF funciona bem e é "
    "o método aplicado: projeta-se o FCL por 5 anos, soma-se o valor terminal por perpetuidade e "
    "traz-se tudo a valor presente."))
story.append(P(
    "O diferencial é o <b>WACC (taxa de desconto) reduzido a 10%</b> (vs 12% do padrão) e "
    "crescimento perpétuo de 4%, refletindo o menor risco do fluxo regulado. Os 3 cenários variam "
    "a taxa de crescimento do FCL em ±30%."))

# ── 8. Geral ────────────────────────────────────────────────────────
story.append(P("8. Demais setores — EV/EBITDA por sub-bucket", "H1"))
story.append(P(
    "Consumo, indústria, varejo, locação, educação, construção e saúde usam EV/EBITDA "
    "(mesma fórmula da seção 5), com um múltiplo de referência específico por sub-setor:"))
story.append(tabela([
    ["Sub-setor", "EV/EBITDA"],
    ["Indústria / Bens de capital", "12,0×"],
    ["Saúde / Farmácia", "11,0×"],
    ["Consumo (alimentos / bebidas)", "11,0×"],
    ["Locação / Serviços", "7,0×"],
    ["Varejo · Vestuário · Educação", "6,0×"],
    ["Construção civil", "5,0×"],
    ["Outros (default)", "8,0×"],
], [9.0*cm, 3.5*cm]))

story.append(PageBreak())

# ── 9. Calibração e limitações ──────────────────────────────────────
story.append(P("9. Calibração, validação e limitações", "H1"))
story.append(P(
    "Os múltiplos e parâmetros não foram inventados — foram <b>calibrados contra preços-alvo "
    "reais do BTG Pactual</b> (junho/2026) para ~25 ações. O erro médio do modelo frente ao "
    "BTG, por setor:"))
story.append(tabela([
    ["Setor", "Erro médio vs BTG"],
    ["Cíclicas maduras (PETR4, VALE3)", "~13 pontos percentuais"],
    ["Shoppings", "~16 pp"],
    ["Bancos (após ROE normalizado)", "~17 pp"],
    ["Seguradoras", "~23 pp"],
    ["Utilities", "~45 pp"],
    ["Geral", "~64 pp"],
], [9.5*cm, 5.0*cm]))
story.append(P(
    "<b>Limitação honesta — nomes “forward-dependent”:</b> empresas em forte crescimento ou "
    "recuperação (ex.: Suzano e PRIO apostando em alta da celulose/petróleo, ou compounders "
    "como WEGE e Raia Drogasil) tendem a ler <b>conservador</b> no nosso modelo. Isso é "
    "estrutural: aplicamos o múltiplo sobre o resultado <i>atual</i>, enquanto o analista "
    "profissional projeta o lucro <i>futuro</i> usando um “deck” de preços de commodity ou "
    "estimativas de crescimento que não temos."))
story.append(P(
    "Decidimos <b>não</b> tentar projetar esse lucro futuro — extrapolar crescimento passado "
    "tornaria o modelo otimista feito o sell-side e contra a disciplina conservadora. Em vez "
    "disso, esses nomes recebem um <b>selo de contexto</b>: mostram o múltiplo atual vs o do "
    "setor e o histórico de crescimento (CAGR), deixando explícito que o alvo é um <b>piso "
    "conservador</b> e que cabe ao investidor julgar a sustentabilidade do crescimento."))
story.append(P(
    "<b>Refino ainda em aberto:</b> a premissa de <i>g</i> (crescimento perpétuo) dos bancos — "
    "usamos 4% (real) enquanto analistas usam ~7% (nominal), o que deixa mesmo bancos saudáveis "
    "lendo um pouco conservadores. Mexer nisso afeta todo o motor e exige cautela.", "Nota"))

# ── Aviso ───────────────────────────────────────────────────────────
story.append(Spacer(1, 6))
story.append(hr())
story.append(P("Aviso", "H2"))
story.append(P(
    "<b>Este é um modelo educacional de aproximação, para estudo pessoal — não constitui "
    "recomendação de compra ou venda.</b> Os valores são altamente sensíveis às premissas "
    "(múltiplo, WACC, crescimento) e a dados que podem conter erros de fonte. Resultados "
    "passados não garantem retornos futuros. Consulte um profissional habilitado antes de investir.",
    "Body"))

doc = SimpleDocTemplate(
    "Metodologia_Preco_Alvo.pdf", pagesize=A4,
    leftMargin=2*cm, rightMargin=2*cm, topMargin=1.6*cm, bottomMargin=1.6*cm,
    title="Metodologia de Preço-Alvo — Análise Fundamentalista B3",
    author="App Análise Fundamentalista B3",
)
doc.build(story)
print("PDF gerado: Metodologia_Preco_Alvo.pdf")
