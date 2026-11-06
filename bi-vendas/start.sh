#!/usr/bin/env bash
# Sobe o BI (API + interface) numa única porta.
# 1ª execução: instala dependências, compila a interface e faz a carga inicial dos arquivos de dados_iniciais/.
set -e
cd "$(dirname "$0")"
# Recompila se a interface não existe, se o código dela mudou desde a última compilação
# ou se faltam dependências (ex.: depois de enviar uma versão nova do BI).
if [ ! -f frontend/dist/index.html ] \
   || [ "$(cat frontend/dist/.build-hash 2>/dev/null)" != "$(bash hash-interface.sh)" ] \
   || [ "$(cat .deps-hash 2>/dev/null)" != "$(sha1sum requirements.txt | cut -d' ' -f1)" ] \
   || ! python3 -c "import fastapi, sqlalchemy, pandas, openpyxl" 2>/dev/null; then
  echo ">> Código novo ou interface ausente: compilando..."
  bash build.sh
fi
cd backend
# Com o banco vazio, a carga de dados_iniciais/ roda em segundo plano depois que o servidor sobe
# (no Neon ela leva alguns minutos; o Render exige que o site responda logo).
echo ">> Iniciando o BI na porta ${PORT:-8000}"
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
