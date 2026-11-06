#!/usr/bin/env bash
# Instala as dependências e compila a interface (frontend/dist).
set -e
cd "$(dirname "$0")"
REQ_HASH=$(sha1sum requirements.txt | cut -d' ' -f1)
deps_ok() { python3 -c "import fastapi, sqlalchemy, pandas, openpyxl, uvicorn, multipart" 2>/dev/null; }
if deps_ok && [ "$(cat .deps-hash 2>/dev/null)" = "$REQ_HASH" ]; then
  echo ">> Dependências Python já instaladas."
else
  echo ">> Instalando dependências Python..."
  python3 -m pip install -q -r requirements.txt 2>/dev/null || pip install -q -r requirements.txt 2>/dev/null \
    || uv pip install -q -r requirements.txt 2>/dev/null || python3 -m pip install -q --break-system-packages -r requirements.txt \
    || echo "!! A instalação das dependências Python falhou."
  if deps_ok; then echo "$REQ_HASH" > .deps-hash; else echo "!! Faltam dependências Python."; exit 1; fi
fi
# A interface já vai compilada no projeto (frontend/dist). Só recompila se o código dela mudou;
# assim servidores sem Node (ex.: Render com Python) publicam sem precisar compilar nada.
if [ -f frontend/dist/index.html ] && [ "$(cat frontend/dist/.build-hash 2>/dev/null)" = "$(bash hash-interface.sh)" ] && [ "${FORCAR_BUILD:-}" != "1" ]; then
  echo ">> Interface já compilada e atualizada."
  exit 0
fi
if ! command -v npm >/dev/null 2>&1; then
  echo "!! A interface precisa ser recompilada, mas este servidor não tem Node/npm."
  exit 1
fi
echo ">> Instalando dependências da interface..."
cd frontend
npm install --no-audit --no-fund --loglevel=error
echo ">> Compilando a interface..."
npm run build
# marca qual versão do código foi compilada (o start.sh recompila se o código mudar)
bash ../hash-interface.sh > dist/.build-hash
