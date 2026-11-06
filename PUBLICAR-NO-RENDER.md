# Publicar o BI no Render + Neon (de graça)

- **Neon** (neon.com): o banco de dados. Guarda importações, marcações e configurações. Grátis e permanente (1 GB).
- **Render** (render.com): o servidor que roda o BI. No plano grátis ele "dorme" depois de 15 min sem uso e leva ~1 min para acordar.
- **cron-job.org**: acorda o BI todo dia às 12h para sincronizar Omie e Qive (no plano grátis do Render ele estaria dormindo).
- **GitHub**: onde fica o código; o Render publica a partir dele.

Tempo: ~30 minutos. Você vai precisar estar logado no GitHub e criar conta no Neon e no Render (dá para entrar com a conta do GitHub nos dois).

## 1. Código no GitHub
1. Em github.com, clique em **New repository**. Nome: `bi-vendas`. Marque **Private**. Crie.
2. Na página do repositório vazio, clique em **uploading an existing file**.
3. Descompacte o zip do BI no computador e arraste **o conteúdo da pasta** (backend, frontend, dados_iniciais, render.yaml, build.sh, start.sh etc.), não o zip.
   - O upload pelo navegador aceita até 100 arquivos por vez: se reclamar, envie em duas levas (primeiro `backend` e os arquivos soltos; depois `frontend` e `dados_iniciais`).
4. Clique em **Commit changes**.

## 2. Banco no Neon
1. Em https://neon.com, **Sign up** (pode usar o GitHub). O painel fica em https://console.neon.tech.
2. Crie um projeto: nome `bi-vendas`, região **AWS US East 1 (N. Virginia)**.
3. Na pergunta "what else does your app need?", escolha **Just Postgres for now** (o BI já tem login e não usa os outros recursos).
4. Na tela do projeto, clique em **Connect** e copie a **Connection string** (começa com `postgresql://`). Guarde como senha: é o `DATABASE_URL`.

## 3. Servidor no Render
1. Em render.com, **Get Started** e entre com o GitHub. Autorize o Render a ver o repositório `bi-vendas`.
2. Clique em **New +** → **Blueprint** e escolha o repositório `bi-vendas`. O Render lê o arquivo `render.yaml`.
3. Ele pede as variáveis. Preencha:
   - `DATABASE_URL`: a Connection string do Neon.
   - `BI_SENHA`: a senha para entrar no BI (forte; não use a do e-mail).
   - `BI_SENHA_LEITURA`: opcional, senha só de consulta para outras pessoas.
   - Omie e Qive: pode deixar em branco agora e configurar depois em Dados › Omie / Dados › Qive.
4. Clique em **Apply**. A publicação leva alguns minutos (instala as dependências).
5. Quando aparecer **Live**, abra o endereço `https://bi-vendas-xxxx.onrender.com`. Na primeira vez aparece **"Preparando o BI"** por 1 a 5 minutos, enquanto as vendas, compras e pedidos de `dados_iniciais/` são gravados no Neon; a página abre sozinha quando termina. Depois entre com a `BI_SENHA`.

## 4. Sincronização das 12h (cron-job.org)
1. No Render, abra o serviço → **Environment** e copie o valor de `CRON_TOKEN`.
2. Em cron-job.org, crie conta e clique em **Create cronjob**:
   - URL: `https://SEU-ENDERECO.onrender.com/api/cron/sincronizar?token=COLE_O_CRON_TOKEN`
   - Agendamento: todo dia às **12:00**, fuso **America/Sao_Paulo**.
   - Em "Advanced", aumente o tempo limite para 30 s (o servidor pode estar acordando).
3. Salve e clique em **Test run**: deve responder `202` e "Sincronização iniciada".

## 5. Conferir
- No BI, abra **Dados › Sistema**: ambiente "Render", banco "PostgreSQL", sem avisos vermelhos.
- Em **Dados › Omie**, teste as conexões e clique em "Atualizar estoque agora".

## Para atualizar o BI depois
Envie os arquivos novos para o mesmo repositório do GitHub (substituindo os antigos). O Render publica sozinho em alguns minutos. Os dados ficam no Neon e não se perdem.

## Se quiser que o servidor não durma
No Render, serviço → **Settings** → **Instance type** → **Starter** (~US$ 7/mês). O banco continua no Neon grátis.
