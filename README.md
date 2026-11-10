# BI Vendas, Estoque e Compras (Uai Comprei)

BI de vendas (Mercado Livre e Shopee), estoque (Omie 03 e 04), compras (notas e Qive) e pedidos (Omie), com foco no grupo Beira Rio.

- **Publicar:** veja [`PUBLICAR-NO-RENDER.md`](PUBLICAR-NO-RENDER.md) (Render + banco Neon, de graça).
- **Com o Claude no Chrome:** veja [`CLAUDE-CHROME.md`](CLAUDE-CHROME.md), com a instrução pronta para colar.
- **Senhas e chaves** nunca vão para este repositório: ficam nas variáveis de ambiente do Render (`BI_SENHA`, `DATABASE_URL`, `OMIE…`, `QIVE…`).
- **Este repositório precisa ser privado:** `dados_iniciais/` tem vendas, compras e pedidos da empresa.

## Estrutura
- `backend/` — servidor Python (FastAPI): cálculos, importações e integrações (Omie, Qive).
- `frontend/` — interface (React). `frontend/dist/` já vai compilada, então o servidor não precisa de Node.
- `dados_iniciais/` — planilhas e pedidos carregados automaticamente no primeiro início com banco vazio.
- `render.yaml` — configuração do serviço no Render. `build.sh` / `start.sh` — instalação e início.

---

# BI Vendas & Estoque

BI pessoal de vendas, estoque e compras de calçados (Mercado Livre e Shopee, fornecedor Beira Rio), com pedidos de compra vindos do Omie.

## Navegação

| Grupo | Página | O que responde |
|---|---|---|
| — | Visão geral | Como foi o último mês, o mês corrente, e a situação de estoque, reposição e pedidos |
| Vendas | Resultado | KPIs do período, comparação com o período anterior, canais, leitura do período |
| | Produtos | Ranking por modelo, cabedal ou SKU, com detalhe de cada item |
| | Preços | Faixas e preços que mais venderam; preço médio mês a mês |
| | Mês a mês | Histórico mensal e comparação entre dois meses |
| Estoque | Posição | Saldo por depósito e cobertura |
| | Reposição | Estoque × venda × pedidos em aberto: o que está zerado sem pedido, o que chega tarde, grade quebrada |
| | Parado e excesso | Itens sem venda e com cobertura acima de 120 dias |
| | Vendas perdidas | Perdas nos dias em que o item ficou zerado |
| Compras | Pedidos (Omie) | Pares e valor a receber, entregas por semana, vencimentos, previsões vencidas, grade de cada pedido |
| | Pronta-entrega | Economia do pronta-entrega contra o programado |
| Dados | Importar, Omie, Histórico, Vínculos, Estoque externo, Qualidade | Alimentação e conferência das bases |

Os filtros globais (período em meses, categoria de produtos, nível e fornecedor) ficam no topo e aparecem só nas páginas em que fazem sentido.

## Omie

- Credenciais: no Replit, crie os Secrets `OMIE_APP_KEY` e `OMIE_APP_SECRET`. Alternativa: tela Dados › Omie (fica salvo no banco).
- A sincronização usa `PesquisarPedCompra` (todos os status, 50 por página) e `ConsultarCliente` (nome do fornecedor) e substitui a cópia local.
  Roda ao iniciar o servidor e a cada `OMIE_SYNC_HORAS` horas (padrão 6; 0 desliga). Também há o botão "Sincronizar agora".
- O código do item no pedido (`cProduto`, ex.: `8367.875-9569-35312-34`) passa pelo mesmo parser de produtos, por isso os pedidos
  se ligam ao estoque e às vendas por SKU e por tamanho.
- Status do pedido = filtro do Omie em que ele aparece (pendente, faturado, recebido…). "A receber" = quantidade − quantidade recebida nos pedidos em aberto.
- `dados_iniciais/omie_pedidos.json` é um instantâneo de 22/10/2026 carregado pela carga inicial; a primeira sincronização o substitui.

## Arquitetura

```
frontend/  React + Vite + Recharts (só exibe; nenhum cálculo de negócio)
  src/App.jsx           navegação, filtros globais, rotas (#/vendas/resultado ...)
  src/pages/            uma tela por arquivo/grupo
backend/
  app/produto.py        regra única de identificação de produtos (modelo/cabedal/cor/tamanho)
  app/importadores/     leitura, validação, deduplicação, prévia, confirmação e desfazer
  app/indicadores.py    todas as fórmulas
  app/resumo.py         resumo textual montado a partir dos indicadores
  app/omie.py           cliente e sincronização da API do Omie (pedidos de compra)
  app/pedidos.py        indicadores dos pedidos e cruzamento com estoque/vendas (reposição)
  app/db.py             esquema (PostgreSQL via DATABASE_URL, ou SQLite em storage/bi.db)
  app/main.py           API REST + serve o frontend compilado
  scripts/carga_inicial.py
dados_iniciais/         planilhas usadas na carga inicial
storage/                banco SQLite e cópia de cada arquivo importado
```

## Rodar no Replit

1. Crie um Repl e envie **o conteúdo** do zip, de modo que `.replit`, `start.sh` e as pastas `backend/` e `frontend/` fiquem na raiz do Repl (não dentro de uma subpasta).
2. Em *Secrets*, crie `OMIE_APP_KEY` e `OMIE_APP_SECRET`.
3. Opcional: crie o banco PostgreSQL no painel *Database*; o sistema usa `DATABASE_URL` automaticamente. Sem ele, os dados ficam em `storage/bi.db`.
4. Clique em **Run**. Na primeira vez, o `start.sh` instala as dependências, compila a interface e carrega `dados_iniciais/` (cerca de 1–2 minutos; acompanhe no Console). O app abre quando aparecer “Iniciando o BI na porta 8000”.

Localmente: `bash start.sh` e abra http://localhost:8000.

## Regras de identificação

- **Calçados:** `MODELO-CABEDAL-COR[-TAMANHO]`, com modelo `XXXX.XXX` ou `XXXX.XXXX`.
  - Depois do modelo, `-` e `.` são equivalentes: `7208.100.29516.109603-39` = `7208.100-29516-109603-39`.
  - Com um único segmento depois do modelo, ele é a **cor** e o cabedal fica “não informado”.
  - O SKU canônico usa hífens e não inclui o tamanho. O tamanho vem só do estoque.
  - Um SKU de venda com tamanho embutido (`2376.100-23153-78276- 29`) é somado ao SKU base e aparece em Qualidade.
- **Demais produtos:** o próprio código. O código de estoque é ligado ao SKU vendido em quatro passos:
  1. código idêntico;
  2. código igual mais um sufixo de tamanho (`4515-999G`, `7075360000`, `11573-960-37`);
  3. vínculo manual;
  4. se nada disso funcionar, o código vira um produto próprio.
- **Níveis de análise:** Modelo, Cabedal (modelo + cabedal) e SKU (modelo + cabedal + cor).

## Fórmulas

| Indicador | Fórmula |
|---|---|
| Unidades e faturamento | Soma no período. Faturamento = valor faturado do relatório; não é lucro. |
| Preço médio | Σ faturamento ÷ Σ unidades do nível escolhido (nunca média de médias). |
| Comparação | Período anterior com o mesmo número de meses. Se houver mês parcial, compara média diária. |
| Preço que mais vendeu | Unidades por faixa do preço médio de cada SKU em cada mês (o relatório é mensal). |
| Economia pronta-entrega | (preço líquido do programado do **mesmo modelo** na compra programada mais próxima − preço PE) × pares. PE = “Preço com desconto” igual ao “Valor unitário”. Sem programado do modelo: “sem referência”. Sem quantidade: fora do cálculo. |
| Estoque atual | Soma da foto mais recente de cada depósito. |
| Tempo de estoque | Estoque ÷ demanda diária (em peças; kits convertidos pela “visão compra”). Itens sem venda no período ficam como “sem giro”. |
| Vendas perdidas | Para cada dia com foto de estoque e cada SKU zerado (soma dos depósitos): demanda diária do SKU nos últimos 3 meses, descontados os dias já zerados. Valor = pares × preço médio do SKU. |
| Grade quebrada | SKU com venda nos últimos 3 meses, estoque positivo e algum tamanho zerado. |
| Estoque parado | Estoque positivo sem venda nos últimos 3 meses. |
| Curva ABC | Recalculada pelo faturamento do período: A até 80%, B até 95%, C o restante. |

Limites: crítico abaixo de 15 dias de cobertura e excesso acima de 120 dias (`indicadores.py`).

## Importação

- **Prévia antes de gravar:** a prévia mostra quantos registros seriam adicionados, atualizados, duplicados e rejeitados, com avisos e erros por linha.
- **Mapeamento de colunas:** fica salvo por estrutura de arquivo, então um arquivo com as mesmas colunas é reconhecido sozinho.
- **Vendas:** a chave é SKU + mês. Reimportar atualiza só o que mudou, como o mês parcial. A data de extração define quantos dias o mês parcial tem.
- **Estoque:** uma foto por depósito e por data. Reimportar a mesma data substitui a foto. Importe todos os dias para medir vendas perdidas.
- **Compras:** a chave é nota + EAN + ocorrência.
  - O modo **Substituir período** serve para reexportações, por exemplo para incluir a coluna de quantidade.
  - Sem a coluna de quantidade, ela só é deduzida em notas com um único modelo e um único preço.
- **Desfazer:** cada importação pode ser desfeita, e o estado anterior é restaurado exatamente.
- **Estoque externo:** SKUs com estoque fora dos depósitos importados (Full, fornecedor) saem dos cálculos de ruptura, cobertura e vendas perdidas.

## Novidades

- **Clique nos meses**: na Visão geral e em Vendas › Mês a mês, clicar num mês do gráfico (ou no nome do mês na tabela) filtra o período por esse mês e abre Vendas › Resultado. Em Resultado, com vários meses selecionados, clicar num mês restringe o período a ele.
- **Estoque › Pedidos x estoque**: itens com estoque baixo e sem pedido de compra em aberto, e itens comprados com estoque chegando (chega antes ou depois de acabar, previsão vencida). Limite de "estoque baixo" e fornecedor ajustáveis.
- **Estoque › Relatórios**: tendência do estoque (baixando, subindo, zerou, quando zera) e download do relatório em Excel (`/api/relatorios/estoque.xlsx`) com as abas Resumo, Posição, Tendência, Reposição, Sem pedido e baixo, Comprado chegando, Grade quebrada, Parado e Evolução. Os botões "Baixar relatório" também aparecem em Posição, Reposição e Pedidos x estoque.
- A tendência compara fotos de estoque; com uma só data importada, mostra quando cada item zera no ritmo de venda. Importe o estoque todo dia para acompanhar a evolução.
- **Vendas por período (lista de vendidos do dia)**: em Dados › Importar arquivos, suba a planilha com SKU e quantidade vendida. O tipo é reconhecido sozinho; escolha o canal (Shopee, Mercado Livre ou não informar) e o período (padrão: um dia). Os códigos são ligados ao SKU pelo mesmo vínculo do estoque. As unidades entram nos indicadores somadas às vendas mensais, só nos dias que o relatório mensal ainda não cobre; o faturamento desses dias é estimado pelo preço médio de cada produto. Reenviar o mesmo canal e período substitui o anterior; dá para desfazer em Histórico de importações.
- **Faturado**: nos pedidos de compra, o que antes aparecia como "previsão vencida" agora aparece como "Faturado".
- **Modelos separados por cabedal**: em Dados › Qualidade e regras. O 7208.101 já vem separado (7208.101-29516 e 7208.101-31337 viram modelos diferentes). O SKU não muda.
- **Ticket médio e várias planilhas**: a lista de vendidos aceita a coluna opcional "Ticket médio" (valor médio por unidade). Com ela, o faturamento é Vendas x Ticket médio; células vazias continuam estimadas pelo preço médio. Em Importar arquivos dá para enviar várias planilhas de uma vez: cada uma tem sua prévia (canal, conta/loja opcional e período) e há o botão "Confirmar todas". Planilhas do mesmo canal, conta e período se substituem; o BI avisa antes.
- **Resultado atualiza com as vendas do dia**: o período padrão passou a ser o mês atual, e ao importar uma lista do dia o período vai para o mês atual. Na prévia da lista, a opção "Somar mesmo assim" soma vendas de dias que o relatório mensal já cobre (use quando o relatório mensal ainda não tem essas vendas).
- **Vendas dia a dia (Resultado)**: semana atual x mesmos dias da semana passada, últimos 7 dias, vendas por semana (por canal, com faturamento), por dia, média por dia da semana e mais vendidos da semana. Usa as listas do dia (`/api/vendas/diario`) e não depende do período do topo.
- **Mais gráficos no Resultado**: canais mês a mês e preço médio (12 meses), concentração do faturamento (curva ABC), faturamento por faixa de preço e quem mais ganhou e perdeu faturamento. A "Leitura do período" saiu do Resultado.
- **Compras › Mais comprados**: ranking dos modelos mais comprados nos relatórios de compras (notas de entrada) do período, com valor, preço médio, % pronta-entrega, notas, última compra, quanto vendeu no período, estoque de hoje e pares a receber no Omie. Modelos separados por cabedal comprados sem cabedal somam todos os cabedais.
- **Dados › Sistema**: versão do servidor e da interface, banco em uso (PostgreSQL ou arquivo local), ambiente (Repl ou app publicado) e últimas importações. Um aviso aparece no topo quando a interface está desatualizada ou quando o banco não guarda os dados ao republicar.
- **Atualização no Replit**: o zip já traz a interface compilada (`frontend/dist`). O `start.sh` recompila sozinho quando o código da interface ou o `requirements.txt` mudam, e o `index.html` é servido sem cache.
- **Compras atualizadas (jan–out/26)**: os relatórios de compras de `dados_iniciais/` foram trocados pelas versões novas (notas até 27/10). Para atualizar um BI já em uso, importe `Jan_Jun.xlsx` e `Jul_Out.xlsx` em Dados › Importar arquivos no modo "Substituir o período". O importador agora acerta sozinho colunas com outra grafia (ex.: "Sku" x "SKU").
- **Compras na história**: Mais comprados mostra, para cada modelo, quantas compras (notas) e pares ele teve em todo o histórico importado; a ficha do produto também.
- **Produtos em linha**: marque cada modelo como em linha ou fora de linha na ficha do produto (abre de qualquer tela) ou em lote em Dados › Produtos em linha. O seletor "Linha" no topo filtra todas as telas, gráficos e relatórios (todos, só em linha, só fora de linha, só sem marcação).
- **Pedir análise**: menu "Pedir análise" gera um texto com todos os números do BI (vendas 12 meses, top modelos, altas e quedas, faixas de preço, dia a dia, estoque e tendência, reposição, grade, parado, compras na história, pronta-entrega, pedidos e entregas por semana) e as perguntas para o analista. Copie e cole numa conversa com o Claude. Respeita o período, a categoria e o filtro de linha do topo. Não inclui informação financeira (`/api/analise/prompt`).
- **Estoque pela API do Omie**: o estoque não vem mais de planilha. Unlock = local "Geral" do Omie 03 (UAI COMPREI 03, Extrema) e Juatuba = local "Geral" do Omie 04 (UAI COMPREI 04, Juatuba). Crie no Replit os Secrets `OMIE03_APP_KEY`, `OMIE03_APP_SECRET`, `OMIE04_APP_KEY` e `OMIE04_APP_SECRET` (chave de aplicativo de cada empresa) ou salve-os em Dados › Omie. O BI atualiza ao iniciar e a cada 6 horas (`OMIE_ESTOQUE_HORAS`), e há o botão "Atualizar estoque agora". Cada atualização vira a foto de estoque do dia (a do mesmo dia é substituída), passando pelos mesmos vínculos de código, histórico e tendência. A quantidade pode ser o físico (padrão) ou o disponível (físico − reservado). As planilhas Unlock.xlsx e Juatuba.xlsx saíram de `dados_iniciais/`; importar planilha de estoque continua possível como plano B.
- **Curva ABC (Pareto)**: Vendas › Curva ABC classifica os modelos pelas vendas de um período base (padrão: últimos 3 meses, por faturamento; A até 80%, B até 95%, C o resto; cada categoria tem a sua curva). O seletor "Curva" no topo filtra todas as telas, gráficos, pedidos e relatórios (A, B, C, A+B, sem venda), junto com o filtro de linha. A coluna "Curva" das tabelas usa a mesma classificação.
- **Compras pela API do Qive**: Dados › Qive lê as NF-e recebidas (todos os CNPJs Uai, sem transferências entre as empresas), tira o SKU do texto do item, a quantidade, o preço e PE/PROG pela regra da planilha. Secrets `QIVE_API_ID` e `QIVE_API_KEY` (endereço em `QIVE_API_URL`, padrão https://api.arquivei.com.br); sincroniza ao iniciar e a cada 6 horas (`QIVE_SYNC_HORAS`). Notas que também estão nas planilhas de compras (mesma data e valor total) contam uma vez, pela do Qive.
- **De onde vem cada dado**: Dados › Sistema mostra a origem atual de vendas, estoque, compras e pedidos (API ou planilha).
- **Vendas por semana**: em Dados › Importar arquivos, "Vendas por semana a partir de" define o mês em que as vendas passam a vir só das planilhas semanais (o relatório mensal desses meses é ignorado, não apagado; desligando, volta). Semana do mês: 1 = dias 1–7, 2 = 8–14, 3 = 15–21, 4 = 22–28, 5 = 29 ao fim. Na prévia da planilha, "Semana do mês" preenche o período. O quadro mostra quais semanas já foram enviadas por canal. Em Vendas › Resultado, escolhendo um mês, aparecem as semanas comparadas com as do mês anterior (pela média por dia) e os modelos semana a semana.
- **Curva ABC com variação**: cada curva mostra as vendas no período do topo com seta e % contra o período anterior (um mês contra o mês anterior; com mês parcial, pela média por dia). A lista também mostra a variação de cada modelo.
- **SKUs do BI**: Dados › SKUs do BI lista todos os SKUs lidos (vendas, estoque, compras, planilhas semanais). Os excluídos somem de todo o BI e podem ser incluídos de volta.
- **Ficha do produto**: vendas por mês empilhadas por marketplace (o mouse mostra cada canal), bloco de informações (curva, linha, primeira e última venda, preço médio de venda, custo médio de compra, fornecedor, tamanhos, EANs, códigos de estoque) e botão Voltar ao abrir um SKU de dentro de um modelo (Esc também volta).
- **Outubro em diante só por semana (padrão)**: a opção "Vendas por semana a partir de" já vem ligada em out/26 (inclusive em bancos que já existiam e nunca configuraram). O relatório mensal de outubro continua guardado; se alguém desligar a opção, ela não religa sozinha.
- **Marcas (Compras › Marcas)**: faturamento, pares vendidos, pares e valor comprados, custo médio, % pronta-entrega, vendido ÷ comprado, estoque, cobertura e a receber de cada marca do grupo Beira Rio (Vizzano, Modare, Moleca, Molekinho, Molekinha, Actvitta, Beira Rio), com variação contra o período anterior e gráfico mês a mês de vendas ou compras. "Agrupar Molekinho + Molekinha" soma as duas. A marca vem da descrição nas vendas (ou nos pedidos do Omie); para modelos sem descrição, do 1º dígito do código (1/3/6 Vizzano, 2 Molekinho/Molekinha, 4/8/9 Beira Rio, 5 Moleca, 7 Modare), com correção manual na própria tela.
- **Omie todo dia às 12:00**: pedidos de compra e estoque do Omie sincronizam todo dia às 12:00 (Brasília); horários editáveis em Dados › Omie (ex.: "07:00, 12:00") ou pela variável `OMIE_HORARIOS`. Se o servidor estiver fora do ar no horário, sincroniza quando voltar. Para voltar ao intervalo antigo, defina `OMIE_SYNC_HORAS`.
- **Publicação no Render + Neon**: veja `PUBLICAR-NO-RENDER.md`. O BI agora tem login (`BI_SENHA`; opcional `BI_SENHA_LEITURA` só para consulta) e, publicado na internet sem senha, não mostra dados. `GET /api/cron/sincronizar?token=CRON_TOKEN` acorda o servidor e sincroniza Omie e Qive (para o cron-job.org às 12h). A interface vai compilada no projeto, então o servidor não precisa de Node.
- **Calendário de compras (Compras › Calendário de compras)**: qual modelo da Beira Rio foi comprado em cada mês, sem preço, pelo relatório de notas (Emitente, Data, Número, Valor da nota, EAN). O SKU sai do EAN já visto nas compras e nos pedidos do Omie. Mostra modelos por mês e por marca, modelos novos e "sem recompra" (vendem e não são comprados há mais de 60 dias). Importação em Dados › Importar ("Itens comprados"); `dados_iniciais/Itens_compra_*.xlsx` entram sozinhos num banco vazio. A mesma nota vinda da planilha de compras completa conta uma vez.
- **Primeira publicação mais segura**: com o banco vazio, a carga de `dados_iniciais/` roda em segundo plano depois que o servidor sobe (no Neon leva de 1 a 5 minutos); a interface mostra "Preparando o BI" e a API fica travada até terminar. Conexões com o banco são renovadas a cada 5 minutos (o Neon gratuito suspende o banco parado).
- **Importação rápida das vendas do dia/semana**: em Dados › Importar arquivos, solte todas as planilhas de uma vez (ou solte em qualquer tela do BI). Canal, conta e período já vêm preenchidos e basta clicar em "Importar tudo".
  - Canal: pelo nome do arquivo ("shopee", "ml", "meli", "mercado livre"); senão, o mesmo do último envio de um arquivo com o mesmo nome.
  - Conta: uma conta já usada que apareça no nome do arquivo (ex.: "Uai 03"); senão, a do último envio.
  - Período: datas no nome do arquivo ("03-11", "01 a 07-11", "2026-11-03", "semana 2"); senão, o período seguinte ao último envio do canal e conta (dia seguinte ou próxima semana do mês). Vários arquivos do mesmo canal viram dias ou semanas seguidos, na ordem dos nomes.
  - Cada campo mostra de onde veio; o que precisa de conferência fica destacado em laranja ("N para conferir"). "Mudar as planilhas de uma vez" aplica canal, conta ou período a todas. Colunas e avisos ficam em "Detalhes".
  - Regras em `backend/app/importadores/sugestao.py`; a memória fica na configuração `importar_memoria`.
