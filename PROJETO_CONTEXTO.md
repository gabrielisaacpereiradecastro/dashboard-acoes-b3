# Análise Fundamentalista B3 — Documento de Contexto do Projeto

> **Como usar este documento:** cole o conteúdo inteiro no início de um novo chat com Claude
> ou como primeira mensagem para o Claude Code antes de pedir qualquer alteração. Isso garante
> que o assistente entenda a arquitetura, decisões já tomadas e o estado atual sem precisar
> reler todo o histórico de conversas — economiza tempo e tokens.

> **Última atualização:** 23/06/2026 — reformulação do motor de valuation (híbrido por setor),
> correções de setor (BALM4, DEXP3), Small Caps via SMAL11, nova **aba de Ciclo de Mercado**
> (dados do Banco Central). Documento agora versionado no git.

---

## 1. Visão geral

App de análise fundamentalista de ações da B3 (bolsa brasileira), em **Python + Streamlit**,
hospedado no **Streamlit Community Cloud**. Uso pessoal entre amigos (Gabriel, Bolivar, Danilo),
sem fins comerciais.

- **Repositório GitHub:** `dashboard-acoes-b3` do usuário `gabrielisaacpereiradecastro`
- **Pasta local:** `~/Desktop/"App ações TRIC"`
- **Deploy:** Streamlit Community Cloud, branch `main`, arquivo principal `app.py`
- **Fonte de dados:** API **Bolsai Pro** (usebolsai.com) — assinatura paga ativa
- **Token da API:** secret `BOLSAI_API_KEY` configurado no Streamlit Cloud (nunca no código)

---

## 2. Arquitetura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `app.py` | Interface Streamlit completa — abas, tabelas, gráficos, sidebar |
| `api.py` | Comunicação com a API Bolsai + **API pública do Banco Central** (SGS e Focus, sem chave) + scraping do P/L do Ibovespa (Investidor10) |
| `score.py` | Lógica de classificação e cálculo do score de cada indicador |
| `config.py` | Constantes, limites de classificação, pesos, `SECTOR_REMAP`, keywords de setor (`SETORES_CICLICOS`, `UTILITY_KEYWORDS`, `INSURER_KEYWORDS`, `SHOPPING_KEYWORDS`) e múltiplos de referência |
| `requirements.txt` | Dependências (inclui `yfinance`, `plotly`, `beautifulsoup4`) |
| `.streamlit/config.toml` | Tema dark mode + `toolbarMode = "minimal"` |
| `acoes_salvas.json` | Apenas **cache local de sessão** — a fonte de verdade é o Supabase (ver seção 3) |

---

## 3. Persistência de dados — ATENÇÃO CRÍTICA

**Histórico do problema:** inicialmente os dados eram salvos em `acoes_salvas.json` local,
listado no `.gitignore`. Um redeploy do Streamlit Cloud apagou esse arquivo porque ele nunca
foi versionado no git — **todos os dados de carteiras/watchlist foram perdidos uma vez** por
esse motivo (20/06/2026). Houve uma tentativa intermediária com GitHub Gist, depois substituída.

**Solução atual (definitiva):** persistência via **Supabase** (PostgreSQL gerenciado).
- Tabela `app_state`, linha única `id = 1`, coluna `dados` (JSONB) com o JSON de todos os usuários.
- Secrets necessários no Streamlit Cloud: `SUPABASE_URL` e `SUPABASE_KEY`.
- `_save_all()` grava no Supabase **a cada alteração**; `_load_file()` lê do Supabase primeiro
  (o arquivo local `acoes_salvas.json` é só cache da sessão). Sobrevive a reboot/redeploy/crash.
- Funções em `app.py`: `_load_file_supabase`, `_save_file_supabase` (REST API do Supabase,
  upsert com header `Prefer: resolution=merge-duplicates`).
- **Nunca remover ou alterar essa lógica sem entender completamente** — é o que garante que
  os dados sobrevivam a redeploys. O `SECTOR_REMAP` é re-aplicado no carregamento
  (`_apply_sector_remap`), então correções de setor pegam só recarregando, sem re-buscar.

---

## 4. Sistema de usuários

Sem login/senha real — é um seletor simples por nome, suficiente para uso entre amigos.

- Tela inicial: `st.selectbox` "👤 Quem é você?" com opções **Gabriel, Bolivar, Danilo**
- Estrutura de dados no Supabase (coluna `dados`):
  ```json
  {
    "usuarios": {
      "Gabriel": { "listas": { "Carteira": {...}, "Watchlist": {...}, "Pesquisa": {...} } },
      "Bolivar": { "listas": {...} },
      "Danilo": { "listas": {...} }
    }
  }
  ```
- Botão "🔄 Trocar usuário" na sidebar volta à tela de seleção
- Cada usuário tem listas completamente isoladas

---

## 5. Sistema de listas (dentro de cada usuário)

Três listas padrão por usuário, mais possibilidade de criar novas:

- **⭐ Carteira** — únicas com campos de **quantidade**, **preço médio de compra** (opcional)
  e **data de compra** (opcional). Tem seção "📊 Análise da Carteira" com gráficos de pizza
  (por setor e por ação), valor total, variação do dia, DY/P-L/Score/Dívida médios ponderados,
  e lucro/prejuízo não realizado quando preço médio está preenchido.
- **👁 Watchlist** — acompanhamento sem quantidade
- **🔍 Pesquisa** — lista "de trabalho", com botão de limpar tudo de uma vez

Gerenciamento de listas (criar/excluir) fica dentro de um `st.expander("⚙️ Gerenciar listas")`.

---

## 6. Sistema de Score (ações, não-bancos)

Score de **0 a 100**, calculado a partir de 10 indicadores ponderados:

| Indicador | Peso | Excelente | Bom | Razoável | Atenção | Proibitivo |
|---|---|---|---|---|---|---|
| Dívida Líq./EBITDA | 25% | ≤0,5x (ou negativo) | 0,5–1,5x | 1,5–2,5x | 2,5–3,5x | >3,5x |
| ROE | 20% | ≥25% | 15–25% | 10–15% | 5–10% | <5% |
| EV/EBITDA | 15% | ≤5x | 5–8x | 8–12x | 12–16x | >16x |
| P/L | 10% | 5–10x | 10–15x | 15–20x | 20–30x | >30x ou negativo |
| Margem EBITDA | 10% | ≥30% | 20–30% | 12–20% | 6–12% | <6% |
| CAGR Lucro 5a | 5% | ≥15% | 8–15% | 0–8% | -10–0% | <-10% |
| P/FCF | 5% | ≤8x | 8–15x | 15–22x | 22–30x | >30x |
| Dividend Yield | 5% | ≥8% | 5–8% | 3–5% | 1–3% | <1% |
| Liquidez diária | 5% | >R$5M | R$3–5M | R$1–3M | R$500k–1M | <R$500k |
| CAGR Receita 5a | 5% | ≥12% | 6–12% | 0–6% | -5–0% | <-5% |

**Regras especiais:**
- Indicador N/D → peso redistribuído proporcionalmente entre os demais (nunca penaliza)
- **Bancos não recebem score geral** — aparecem com aviso "⚠️ Bancário"; indicadores
  aplicáveis (ROE, P/L, Mg.EBITDA, Liquidez) continuam visíveis e coloridos
- **P/L abaixo de 5x** → classificado como "Inconclusivo" (não "Atenção"), com aviso de
  possível value trap; peso redistribuído como se fosse N/D
- Resultado final: 80–100 Excelente🟢 / 60–79 Bom🟩 / 40–59 Razoável🟡 / 20–39 Atenção🟠 / 0–19 Evitar🔴

**Indicadores informativos (cor, mas SEM peso no score):** P/VP, PSR, ROA, ROIC, Margem
Líquida, Margem Bruta, LPA, VPA, Liquidez Corrente, Cobertura de Juros, Payout, Governança.

Escala P/VP: <1,0x Bom(verde claro) / 1,0–2,0x Excelente / 2,0–3,0x Razoável / 3,0–5,0x
Atenção / >5,0x Proibitivo. Bancos: até 1,5x verde / 1,5–2,5x amarelo / acima vermelho.

Escala PSR: ≤1x Excelente / 1–2x Bom / 2–4x Razoável / 4–6x Atenção / >6x Proibitivo.

Escala Cobertura de Juros (EBIT/Despesa Financeira): ≥5x Excelente / 3–5x Bom / 1,5–3x
Razoável / 1–1,5x Atenção / <1x Proibitivo.

---

## 7. Insights setoriais (popovers ℹ️)

Cada indicador com score tem um popover clicável (ícone `ℹ️` inline, sem container visual,
CSS customizado para ficar discreto) explicando: O que mede / Por que importa / Interpretação
(maior ou menor melhor) / Faixa ideal / Atenção (armadilhas). Abaixo disso, um bloco
**"📊 Contexto setorial"** com nota específica detectada automaticamente pelo setor da ação
(via `_sector_insight(indicador, setor)`).

**Setores mapeados com insight próprio:** Educação, Energia/Transmissão/Saneamento/Utilities,
Bancos/Financeiro/Seguradoras, Construção Civil, Varejo/Comércio, Saúde, Metalurgia/Siderurgia,
Têxtil/Vestuário, Agronegócio. Setores não mapeados usam texto padrão genérico.

`SECTOR_REMAP` em `config.py` corrige classificações ruins da B3 (ex: SmartFit aparecia como
"Brinquedos e Lazer", ALLOS como "Comércio", BALM4/Baumer como "Metalurgia" sendo equipamento
médico, DEXP3/Dexxos estava errado como "Farmácia" sendo química — remapeados para os setores
corretos). **Importante para o valuation:** o setor define a rota de valuation (ver seção 10),
então um remap errado também escolhe o método errado. Aplicado tanto em dados novos da API
quanto em dados já salvos no Supabase (`_apply_sector_remap` no carregamento).

---

## 8. Painel de Contexto de Mercado (topo do app)

Linha compacta sempre visível, cache de 1h (`@st.cache_data(ttl=3600)`), botão 🔄 manual:
- **Ibovespa e Small Caps:** via **yfinance** (`BOVA11.SA` e `SMAL11.SA` — o ticker SMLL11.SA
  estava deslistado no Yahoo, trocado por SMAL11.SA, o ETF iShares Small Cap, que é estável;
  fallback gracioso para "Indisponível" com tooltip se a fonte falhar)
- **Ibov vs Small (YTD):** comparação simples de retorno acumulado no ano
- **USD/BRL, Selic, IPCA 12m, Juro Real:** via endpoint `/api/v1/macro` da Bolsai Pro
  (dados do Banco Central — podem ter delay de 24-48h após mudanças do COPOM, é normal
  e não é bug)

---

## 8.1 Aba de Ciclo de Mercado (🌐 Ciclo) — termômetro educacional

Aba que estima a fase do ciclo econômico (framework **Investment Clock**: Crescimento ×
Inflação) de forma **educacional** — mostra o cenário macro e o que cada fase historicamente
favoreceu; **não dá sinal de compra/venda nem conselho de risco personalizado** — decisão
consciente de design (timing de ciclo é incerto e o Brasil é puxado por fatores globais).

**Fontes de dados (todas públicas e GRATUITAS, sem chave/secret):**
- **API SGS do Banco Central** (`api.get_sgs`): Selic meta (432), IPCA 12m (13522), IBC-Br
  (24364), USD/BRL (1), Crédito/PIB (20622). O param `dias` busca por intervalo de datas —
  necessário para séries diárias como a Selic, pois o `/ultimos/N` tem limite (~50) e estoura.
- **API Olinda / Expectativas do Focus** (`api.get_focus`): mediana das projeções de IPCA, PIB
  e Selic por ano de referência. URL montada à mão (OData é sensível à codificação de aspas).
- **P/L do Ibovespa** (`api.get_ibovespa_pl`): scraping do Investidor10. **A Bolsai NÃO tem
  endpoint de índice/Ibovespa — confirmado** (todos os 22 endpoints dela são por ticker/setor/
  macro). Média histórica ~12× é constante documentada. Fallback gracioso se o HTML mudar.

**Relógio do ciclo:** quadrante Crescimento (IBC-Br a/a) × Inflação (momentum do IPCA 12m em
6 meses), com marcador na fase provável + **rastro dos últimos ~6 meses** (direção do
deslocamento). 4 fases: Recuperação 🌱 / Aquecimento 🔥 / Estagflação 🥶 / Desaceleração ❄️,
cada uma com o que historicamente favoreceu.

Também exibe os indicadores do BC, as **expectativas do Focus** (com leitura do caminho da
Selic = afrouxamento/aperto, que substitui a curva de juros) e o **P/L do Ibovespa vs média**.

Funções em `app.py`: `_get_ciclo_data` (cache 6h), `_ciclo_fase`, `_show_ciclo_relogio`,
`_show_ciclo_tab`, dict `_CICLO_FASES`. Disclaimers fortes: simplificação que ignora fatores
globais (Fed/China/commodities); timing de ciclo é incerto; não é recomendação.

---

## 9. Gráficos e visualizações (aba Detalhe)

- **Histórico de preços:** Plotly interativo, seletores 1M/3M/6M/1A/3A/5A, MM50 opcional,
  fallback automático para dados de 52 semanas se endpoint de histórico falhar. Checkbox
  para sobrepor retorno normalizado do Ibovespa no mesmo período.
- **Radar individual:** 6 indicadores principais (Dív/EBITDA, ROE, EV/EBITDA, P/L, Mg.EBITDA,
  Liquidez), score 0-100 por eixo
- **Radar comparativo:** via `st.multiselect` (2-4 ações) acima da tabela na aba Comparativo,
  sobrepõe radares em cores diferentes, auto-renderiza com ≥2 selecionadas, tabela de valores
  lado a lado abaixo
- **Lucro vs Cotação:** dois eixos Y, até 5 anos, mostra convergência/divergência valuation

---

## 10. Valuation — MOTOR HÍBRIDO POR SETOR (seção "📐 Valuation")

**Decisão estratégica (jun/2026):** o DCF-sobre-FCL único dava erro médio de **107pp** vs
preços-alvo do BTG e gerava absurdos (PETR4 +600%, CXSE3 +850%). Foi substituído por um motor
**híbrido**, onde cada setor usa o método que o mercado de fato usa. Roteamento em
`_build_table` (coluna Potencial) e `_show_dcf` (aba Detalhe), nesta ordem:

1. **Bancos** → **Gordon Growth**: `P/VP justo = (ROE−g)/(Ke−g)`, Ke=12%, g=4%.
   Conservador Ke×1.08, g×0.7. `_gordon_base_price` / `_show_gordon_growth`.
2. **Seguradoras** → **P/L × LPA** (P/L justo 10×). DCF de FCL não funciona (float de prêmios
   distorce o caixa). `_is_insurer`, `INSURER_KEYWORDS`, `INSURER_FAIR_PE`.
3. **Shoppings** → **EV/EBITDA 10,5×** (FCL distorcido por compra/venda de imóveis).
   `_is_shopping`, `SHOPPING_KEYWORDS`, `SHOPPING_FAIR_EV_EBITDA`.
4. **Cíclicas** (petróleo, mineração, siderurgia, celulose, agro) → **EV/EBITDA through-cycle**
   sobre `base = max(EBITDA atual, EBITDA mid-cycle)`. O múltiplo baixo já é o desconto de
   ciclicidade — por isso NÃO se normaliza o EBITDA para baixo (seria dupla-contagem; usar a
   mediana só quando ela for MAIOR, para proteger em vales). Múltiplos: petróleo 5×, mineração
   6×, siderurgia 6,5×, celulose 7×, agro 5× (`CICLICA_EV_EBITDA_BUCKETS` no `app.py`).
   EBITDA mid-cycle = mediana do EBIT histórico × razão EBITDA/EBIT atual. `api.py` busca o
   DRE **só para cíclicas** e guarda `ebit_historico`. `_cyclical_base_price`.
5. **Utilities** (energia, saneamento) → **DCF com WACC 10%, perp_g 4%** (fluxo regulado,
   menor risco). `_dcf_base_price` / `_dcf_params`.
6. **Geral** (todo o resto) → **EV/EBITDA por sub-bucket**: saúde/farma 11×, consumo 11×,
   indústria 12×, locação 7×, varejo/vestuário/educação 6×, construção 5×, default 8×
   (`GERAL_EV_EBITDA_BUCKETS` no `app.py`).

**Exibição:** sempre FAIXA (3 cenários Conservador/Base/Otimista) + gráfico de barras Plotly
com linha do preço atual. Aviso fixo de "ferramenta educacional, não é recomendação".
Helper genérico `_ev_ebitda_price(s, mult)` reusado por shoppings/geral/cíclicas.

**Coluna "Potencial"** (tabela comparativa, após "Preço"): usa o cenário **Base** (não mais
Conservador). Setas ↑/↓ com % e cor verde/vermelha. "N/D" se faltarem dados.

**Constantes:** `INSURER_*`, `SHOPPING_*` ficam em `config.py` mas são lidas em `app.py` com
`getattr(config, nome, default)` — fallback embutido porque o Streamlit Cloud já serviu
`config.py` stale várias vezes (cache de `.pyc`), causando ImportError. Buckets de Geral e
Cíclica são definidos direto no `app.py` pelo mesmo motivo.

**Calibração vs BTG (jun/2026), erro médio:** cíclicas maduras ~13pp (PETR4 9pp, VALE3 3pp),
shoppings ~16pp, seguradoras ~23pp, bancos ~35pp, utilities ~45pp, geral ~64pp.

**Limitação honesta:** nomes *forward-dependent* (SUZB3, PRIO3, WEGE3, RADL3) leem
conservadores — o múltiplo sobre resultado ATUAL não captura o lucro futuro / recuperação de
preço de commodity que o analista projeta com um "deck". Selo de baixa confiança avisa.

**REFINOS PENDENTES (a fazer):**
1. **Normalizar o ROE dos bancos** — BBAS3 veio com ROE 6,6% de um trimestre ruim, distorcendo
   o Gordon (deu -44% vs BTG +27%). Usar ROE médio/normalizado.
2. **Nomes forward-dependent** acima — exigiriam estimativa de EBITDA futuro / deck de commodity.

---

## 11. Screener

Filtros customizáveis com sliders (ROE mín, P/L máx, Dív/EBITDA máx, Mg.EBITDA mín,
EV/EBITDA máx, Liquidez mín, Score mín) + checkboxes (excluir bancos, apenas Novo Mercado).

**Filtros salvos** (persistidos no Supabase): usuário pode salvar com nome customizado. Três
filtros padrão pré-configurados (não editáveis): "🏆 Fundamentalista", "💰 Dividendos",
"🚀 Crescimento", "🏆 Elite — Score ≥ 80".

Botão "🔍 Buscar na B3" consulta endpoint de screener da Bolsai Pro, limite 20 resultados,
botão "Adicionar à lista atual".

---

## 12. Aba FIIs (independente da aba de ações)

Sistema de listas próprio (não compartilha com ações). Score FII 0-100 com pesos: DY 30%,
P/VP 25%, Vacância 20%, Liquidez 15%, Inadimplência 10%.

Escalas: DY (≥12% Exc / 8-12% Bom / 6-8% Raz / 4-6% Atenção / <4% Proib) · P/VP (<0,90x Exc
/ 0,90-1,05x Bom / 1,05-1,15x Raz / 1,15-1,30x Atenção / >1,30x Proib) · Vacância (<3% Exc /
3-8% Bom / 8-15% Raz / 15-25% Atenção / >25% Proib) · Inadimplência (<1% Exc / 1-3% Bom /
3-6% Raz / 6-10% Atenção / >10% Proib).

Screener próprio com filtros específicos de FII. Filtro por tipo (Papel/Tijolo/Híbrido/FOF)
populado dinamicamente a partir do campo retornado pela API.

---

## 13. Outras funcionalidades

- **Minhas Anotações:** campo de texto livre por ação (`st.text_area`), com data de última
  revisão automática, campo "o que mudou desde a última revisão" (aparece só se já existir
  nota anterior), histórico de até 5 versões anteriores em expander
- **Alertas de mudança de classificação:** ao atualizar dados, compara classificação anterior
  vs nova de cada indicador, badge "🔔 X indicadores mudaram" com detalhamento
- **Exportar CSV:** botão na aba Comparativo, baixa a tabela atual com todos os indicadores
- **Fuso horário:** todos os timestamps usam `datetime.now(timezone(timedelta(hours=-3)))`
  (Brasília), nunca UTC puro
- **Tela de boas-vindas** (lista vazia): apresentação resumida do app, sem menção a "200
  req/dia" (texto antigo removido)

---

## 14. Decisões de design importantes (não reverter sem motivo)

- Toolbar do Streamlit oculta via `[client] toolbarMode = "minimal"` + CSS adicional
  (`#MainMenu`, `header`, `.stDeployButton`, `[data-testid="stToolbar"]` todos `display:none`)
  — para amigos não verem/editarem o código pelo navegador
- Painel de Diagnóstico/Debug nunca aparece por padrão na sidebar — só dentro de
  `st.expander` colapsado, ou condicionado a variável de ambiente que nunca está ativa em
  produção
- Símbolos 🟢 redondo = Excelente/Proibitivo (extremos), 🟩🟡🟠 quadrados = intermediários —
  intencional, manter
- Nunca usar cor azul nos indicadores — paleta é estritamente verde/amarelo/laranja/vermelho/
  cinza(N/D)
- Função de estilização da tabela (`_apply_styles` / `styler_fn`) deve sempre ter guards
  contra `KeyError`: checar `col in class_df.columns` E `idx in class_df.index` antes de
  `.at[]`, com try/except de fallback retornando string vazia — já causou bugs 2x antes

---

## 15. Limitações conhecidas / pendências

- Small Caps via yfinance (SMAL11.SA) pode eventualmente retornar "Indisponível" (fonte externa)
- Alguns CAGRs (Lucro/Receita 5a) ficam N/D para empresas com histórico curto na Bolsai ou
  lucro-base negativo — é limitação real de dados, não bug
- Não há composição/sobreposição de carteiras de fundos de investimento (FIAs) — avaliado e
  descartado por complexidade (exigiria parsing de CDA da CVM, dados defasados 30-60 dias)
- App não tem autenticação de segurança real — é seletor de nome sem senha, adequado apenas
  para uso entre pessoas de confiança

---

## 16. Fluxo de trabalho padrão para novas alterações

1. Abrir Claude Code na pasta `~/Desktop/"App ações TRIC"`
2. Colar prompt de melhoria (sempre pedir para **não fazer push**, só commit)
3. Revisar o que foi feito, testar localmente se necessário
4. Fazer push manual no Terminal:
   ```bash
   cd ~/Desktop/"App ações TRIC"
   git push https://SEU_TOKEN_GITHUB@github.com/gabrielisaacpereiradecastro/dashboard-acoes-b3.git main
   ```
   (usar `--force` apenas se houver conflito identificado e compreendido)
5. Aguardar 1-2 min o Streamlit Cloud redeployar automaticamente
6. Testar no app (idealmente em aba anônima primeiro, para evitar falso positivo de cache)
7. Se algo quebrar: pedir ao Claude Code para adicionar `st.exception(e)` temporário para
   capturar o erro completo antes de tentar corrigir "no escuro"

**Nunca esquecer:** sempre confirmar que os secrets `BOLSAI_API_KEY`, `SUPABASE_URL` e
`SUPABASE_KEY` estão configurados no Streamlit Cloud após qualquer recriação de app.

**Cache stale do Streamlit Cloud:** ao adicionar uma constante nova em `config.py` e importá-la
em `app.py`, o deploy às vezes serve um `config.py` antigo (cache de `.pyc`) e quebra com
ImportError. Padrão seguro: ler com `getattr(config, nome, default)` ou definir a constante
direto no `app.py`. Já aconteceu 3+ vezes (classify_psr, SETORES_CICLICOS, INSURER_KEYWORDS).
