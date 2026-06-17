# Análise Fundamentalista B3

App em **Python + Streamlit** para análise fundamentalista de ações da bolsa brasileira (B3), com dados da [Bolsai API](https://usebolsai.com).

## Funcionalidades

- **Score 0–100** ponderado por 10 indicadores (Dív/EBITDA, ROE, EV/EBITDA, P/L, Mg. EBITDA, CAGR Lucro, P/FCF, Dividend Yield, Liquidez, CAGR Receita)
- **Tabela comparativa** com células coloridas por classificação fundamentalista
- **Detalhe completo** por ação: preço, variação, indicadores com barras de progresso
- **Tratamento especial** para bancos (indicadores adaptados, sem score global)
- **Exceções por setor**: Utilities (energia, saneamento) e Varejo têm limites ajustados
- **Persistência entre sessões** via `acoes_salvas.json`
- **Alerta visual** de dados desatualizados (> 24h laranja, > 48h vermelho)
- **Screener** (estrutura pronta, requer plano Pro da Bolsai)

## Pré-requisitos

- Python 3.11+
- Conta gratuita na [Bolsai](https://usebolsai.com) com API Key

## Instalação local

```bash
# 1. Clone ou copie os arquivos para uma pasta
cd "App ações TRIC"

# 2. Crie um ambiente virtual
python -m venv .venv
source .venv/bin/activate        # Mac/Linux
.venv\Scripts\activate.bat       # Windows

# 3. Instale as dependências
pip install -r requirements.txt

# 4. Configure a API Key
export BOLSAI_API_KEY="sk_sua_chave_aqui"   # Mac/Linux
set BOLSAI_API_KEY=sk_sua_chave_aqui        # Windows (cmd)

# 5. Execute o app
streamlit run app.py
```

O app abrirá em `http://localhost:8501`.

## Deploy no Streamlit Community Cloud

1. Suba os arquivos para um repositório **público** no GitHub  
   (o `acoes_salvas.json` está no `.gitignore` — não será enviado)

2. Acesse [share.streamlit.io](https://share.streamlit.io) e conecte o repositório

3. **Configure o Secret:**  
   No painel do app → **Settings → Secrets**, adicione:
   ```toml
   BOLSAI_API_KEY = "sk_sua_chave_aqui"
   ```
   O Streamlit Cloud injeta o secret como variável de ambiente — nunca hardcode a chave no código.

4. Faça o deploy. O app ficará disponível em uma URL `*.streamlit.app`.

> **Nota sobre persistência no Cloud:** O arquivo `acoes_salvas.json` é criado no sistema de arquivos efêmero do Streamlit Cloud. Os dados são perdidos a cada deploy ou reinicialização. Para persistência permanente no Cloud, considere usar o Streamlit Community Cloud com um banco de dados (ex: Supabase) ou migrar para um VPS.

## Estrutura dos arquivos

```
├── app.py               # App principal Streamlit
├── api.py               # Comunicação com a API Bolsai
├── score.py             # Lógica de classificação e score
├── config.py            # Configurações centralizadas (pesos, cores, setores)
├── requirements.txt     # Dependências Python
├── .gitignore           # Ignora .env e acoes_salvas.json
├── README.md            # Este arquivo
└── .streamlit/
    └── config.toml      # Tema dark mode do Streamlit
```

## Limites do plano gratuito da Bolsai

| Recurso | Free | Pro (R$ 29/mês) |
|---------|------|-----------------|
| Requisições/dia | 200 | 10.000 |
| Fundamentos atuais | ✅ | ✅ |
| Histórico de preços | ❌ | ✅ |
| Fluxo de caixa (DFC) | ❌ | ✅ |
| Screener completo | ❌ | ✅ |
| Dados históricos (DFP) | ❌ | ✅ |

**Eficiência de requisições:** cada ticker consome **3 chamadas** (fundamentos + empresa + estatísticas). O endpoint `/dividends` é PRO e não é utilizado. Com 200 req/dia é possível analisar até ~66 tickers por dia com uma atualização completa.

## Indicadores e pesos

| # | Indicador | Peso | Nota |
|---|-----------|------|------|
| 1 | Dív. Líquida / EBITDA | 25% | N/A para bancos |
| 2 | ROE | 20% | Limites ajustados para bancos |
| 3 | EV/EBITDA | 15% | N/A para bancos |
| 4 | P/L | 10% | |
| 5 | Margem EBITDA | 10% | Limites ajustados por setor |
| 6 | CAGR Lucro 5 anos | 5% | N/D se lucro base negativo |
| 7 | P/FCF | 5% | N/D no plano Free (requer DFC) |
| 8 | Dividend Yield | 5% | N/D no plano Free (campo ausente em /fundamentals) |
| 9 | Liquidez | 5% | Vol. médio 52 sem. × preço |
| 10 | CAGR Receita 5 anos | 5% | |

Indicadores N/D ou N/A têm seu peso redistribuído proporcionalmente entre os demais.
