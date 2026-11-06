#!/usr/bin/env bash
# Impressão digital do código da interface: muda sempre que algum arquivo dela muda.
# LC_ALL=C deixa a ordenação igual em qualquer servidor (o idioma do sistema mudaria a ordem).
cd "$(dirname "$0")/frontend"
find src index.html package.json vite.config.* -type f 2>/dev/null | LC_ALL=C sort | xargs cat | sha1sum | cut -d' ' -f1
