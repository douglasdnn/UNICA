#!/bin/bash
# entrypoint.sh

set -e

# Garante que o diretorio de trabalho esteja correto
cd /app

# Garante diretorio persistente do SQLite
mkdir -p /app/DB

# Sincroniza dependencias a cada inicializacao para refletir alteracoes em requirements.txt
if [ -f /app/requirements.txt ]; then
	echo "[entrypoint] Instalando dependencias de /app/requirements.txt"
	python -m pip install --no-cache-dir --root-user-action=ignore --upgrade -r /app/requirements.txt
	echo "[entrypoint] Validando dependencias instaladas (pip check)"
	python -m pip check
else
	echo "[entrypoint] ERRO: arquivo /app/requirements.txt nao encontrado"
	exit 1
fi

# Sobe um display virtual para scripts que dependem de GUI (pyautogui/mouseinfo).
export DISPLAY=:99
export XAUTHORITY=/root/.Xauthority
touch "$XAUTHORITY"
if ! pgrep -x Xvfb >/dev/null 2>&1; then
	rm -f /tmp/.X99-lock
	Xvfb :99 -screen 0 1280x1024x24 -nolisten tcp &
	sleep 1
fi

# Executa o scheduler como processo principal do container.
exec python /app/scheduler.py