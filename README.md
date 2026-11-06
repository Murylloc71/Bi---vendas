# Qive MCP — Uai Comprei

Servidor MCP remoto, **somente leitura**, que permite ao Claude consultar NF-e no Qive (Arquivei).

## Ferramentas

| Ferramenta | O que faz |
|---|---|
| `ultimas_notas` | Últimas notas que entraram no Qive para um CNPJ (recebidas ou emitidas) |
| `listar_notas` | Todas as notas de um CNPJ em um período |
| `consultar_nota` | Detalhes de uma nota pela chave de acesso (44 dígitos) |

## Configuração na hospedagem (Render)

- **Build command:** `pip install -r requirements.txt`
- **Start command:** `uvicorn server:app --host 0.0.0.0 --port $PORT --no-access-log`

**Variáveis de ambiente** (nunca colocar no GitHub):

| Nome | Valor |
|---|---|
| `QIVE_API_ID` | API ID do Qive |
| `QIVE_API_KEY` | API Key do Qive |
| `MCP_SECRET` | código secreto com 32+ letras/números |
| `QIVE_BASE_URL` | opcional (padrão `https://api.arquivei.com.br`) |

## URLs

- Teste: `https://SEU-SERVIDOR/health` → deve mostrar `ok`
- Conector no Claude: `https://SEU-SERVIDOR/mcp/SEU_MCP_SECRET`

Trate a URL do conector como uma senha: quem a tiver consegue consultar as notas.
