# Relatório Diário de Abertura

Pipeline que roda todo dia às 6h da manhã (horário de Brasília) na GitHub Actions:

1. Lê o dashboard 111 do Metabase via API (com API Key)
2. Descobre os 4 cards relevantes pelo nome
3. Calcula métricas (Espera / CNPJ / IM / CRM, sem atualização, atrasados, necessitam ação)
4. Adiciona snapshot ao `historico.json`
5. Atualiza `dashboard_cumulativo.html`
6. Posta resumo no canal `#certificados-prontos` via Slack Workflow webhook
7. Commita os arquivos atualizados de volta no repo

## Setup (uma vez)

### 1. Configurar GitHub Secrets

No repo, vai em **Settings → Secrets and variables → Actions → New repository secret** e cria os 4 secrets abaixo:

| Nome do Secret | Valor |
|---|---|
| `METABASE_API_KEY` | A API Key gerada no Metabase (formato `mb_...`) |
| `METABASE_BASE_URL` | `https://metabase.selvia.app` |
| `METABASE_DASHBOARD_ID` | `111` |
| `SLACK_WEBHOOK_URL` | A URL do Workflow trigger (formato `https://hooks.slack.com/triggers/...`) |

### 2. Permitir que GitHub Actions commite no repo

Vai em **Settings → Actions → General → Workflow permissions** e marca **"Read and write permissions"**. Salva.

### 3. Pronto

O workflow está configurado para rodar diariamente às **9h UTC (6h BRT)**. Você pode também disparar manualmente em **Actions → Relatório Diário de Abertura → Run workflow**.

## Estrutura do projeto

- `run_diario.py` — script principal
- `dashboard_template.html` — template HTML do dashboard cumulativo
- `historico.json` — histórico de snapshots (commitado a cada execução)
- `dashboard_cumulativo.html` — dashboard gerado a cada execução (commitado também)
- `requirements.txt` — dependências Python
- `config.example.json` — template de configuração local (renomear para `config.json` para rodar local)
- `.github/workflows/relatorio-diario.yml` — definição do cron

## Rodar localmente (para debug)

```bash
# Instalar deps
pip install -r requirements.txt

# Copiar template e preencher com seus dados
cp config.example.json config.json
# Edita config.json com API key real e webhook real

# Rodar
python run_diario.py
```

O `config.json` está no `.gitignore` — nunca será versionado.

## Manutenção

- **Cards renomeados no Metabase:** se a operação renomear cards no dashboard, o script continua identificando enquanto a palavra-chave principal estiver no nome (ex: "tabela completa", "sem atualização"). Se renomearem para algo muito diferente, ajustar os regex de `CARD_PATTERNS` no `run_diario.py`.

- **Mudar horário:** edita o cron no `.github/workflows/relatorio-diario.yml`. Lembra que o GitHub usa UTC, então para 6h BRT use `0 9 * * *`.

- **API Key vazada/comprometida:** gera nova no Metabase, atualiza o secret `METABASE_API_KEY` no GitHub. O workflow já passa a usar a nova na próxima execução.

## Troubleshooting

- **Workflow falha com erro 401/403 no Metabase:** API key inválida ou expirada. Gerar nova no Metabase e atualizar secret.
- **Workflow não commita:** verificar se "Read and write permissions" está habilitado nas configurações de Actions do repo.
- **Cards não identificados:** rodar com debug — o script imprime os cards encontrados e os não mapeados. Pode ser que os nomes mudaram.
- **Slack retorna erro:** webhook do Workflow Builder pode ter sido excluído. Recriar e atualizar o secret.
