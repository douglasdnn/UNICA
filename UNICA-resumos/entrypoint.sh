#!/bin/bash
set -e

# Aguarda o serviço Ollama iniciar
echo "Aguardando servico Ollama iniciar..."
for i in $(seq 1 60); do
    if curl -s http://ollama:11434/api/tags > /dev/null 2>&1; then
        echo "Ollama respondendo."
        break
    fi
    echo "Tentativa $i/60... aguardando Ollama..."
    sleep 2
done

if ! curl -s http://ollama:11434/api/tags > /dev/null 2>&1; then
    echo "[FATAL] Ollama nao respondeu apos 120s. Abortando."
    exit 1
fi

# Faz o pull do modelo via API do Ollama
MODEL="cnmoro/gemma3-gaia-ptbr-4b:q4_k_m"
echo "Verificando/Baixando modelo ${MODEL}..."
curl -s http://ollama:11434/api/pull -d "{\"name\": \"${MODEL}\"}"

# Valida que o modelo esta carregado
echo "Validando disponibilidade do modelo..."
for i in $(seq 1 30); do
    if curl -s http://ollama:11434/api/tags | grep -q "${MODEL}"; then
        echo "Modelo ${MODEL} pronto."
        break
    fi
    echo "Tentativa $i/30... aguardando modelo..."
    sleep 2
done

if ! curl -s http://ollama:11434/api/tags | grep -q "${MODEL}"; then
    echo "[WARN] Modelo ${MODEL} nao apareceu em /api/tags. A aplicacao pode falhar ao gerar resumos."
fi

# Executa o script principal
echo "Iniciando aplicacao..."
exec python /app/ollama-resumos.py