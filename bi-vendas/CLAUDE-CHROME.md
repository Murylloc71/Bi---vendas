# Instrução para o Claude no Chrome

Antes: o código já deve estar no repositório https://github.com/Murylloc71/Bi-vendas (enviado por você, pelo navegador) e você deve estar logado no GitHub neste Chrome.

Copie e cole para o Claude no Chrome:

```
Quero publicar meu BI. O código está no meu GitHub: https://github.com/Murylloc71/Bi-vendas

0. Abra o repositório e confira:
   a) Se ele é privado. Se aparecer "Public", vá em Settings > General > Danger Zone > Change repository visibility > Make private e me peça para confirmar antes de concluir.
   b) Se os arquivos render.yaml, build.sh, start.sh, requirements.txt e as pastas backend, frontend e dados_iniciais estão na raiz (não dentro de outra pasta). Se estiverem dentro de outra pasta, PARE e me avise.

1. Neon (neon.com): crie conta entrando com o GitHub, crie o projeto "bi-vendas" na região AWS US East (N. Virginia), clique em "Connect" e copie a Connection string (começa com postgresql://).

2. Render (render.com): entre com o GitHub e autorize o acesso ao repositório "Bi-vendas". Clique em New + > Blueprint e escolha esse repositório. Em DATABASE_URL, cole a Connection string do Neon. Deixe em branco as variáveis do Omie e do Qive.

3. PARE antes de preencher BI_SENHA e BI_SENHA_LEITURA: eu mesmo digito as senhas. Depois que eu avisar, clique em Apply e acompanhe os logs até o serviço ficar "Live". Se o build falhar, me mostre as últimas linhas do log.

4. No Render, abra o serviço > Environment e copie o valor de CRON_TOKEN. Anote o endereço do serviço (https://...onrender.com).

5. cron-job.org: crie a conta e um cronjob para https://ENDERECO-DO-SERVICO/api/cron/sincronizar?token=CRON_TOKEN, todo dia às 12:00, fuso America/Sao_Paulo, tempo limite de 30 segundos. Rode o "Test run" e me diga a resposta (o esperado é 202).

6. Abra o endereço do BI, espere carregar (até 1 minuto) e me avise para eu entrar com a senha.

Sempre que pedir login, código de verificação, confirmação de e-mail ou cartão de crédito, pare e me chame. Não escolha nenhum plano pago.
```

Para atualizar o BI depois: envie os arquivos novos para o mesmo repositório (substituindo); o Render publica sozinho.
