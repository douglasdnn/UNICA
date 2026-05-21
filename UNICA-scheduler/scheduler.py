#!/usr/bin/env python3
"""
Orquestrador que executa scripts em loop e expoe a saida em um browser.
"""

import subprocess
import threading
import time
import sys
import sqlite3
import os
import re
from collections import deque
from datetime import datetime
from pathlib import Path
from queue import Queue

from flask import Flask, Response, jsonify
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).parent
VENV_PYTHON = SCRIPT_DIR.parent / "ollama-venv" / "bin" / "python"

# Permite rodar o scheduler fora do Docker carregando .env local.
load_dotenv(SCRIPT_DIR / ".env", override=True)

SCRIPTS = [
    SCRIPT_DIR / "01-monitora.py",
    SCRIPT_DIR / "02-peticoes.py",
]
LEMBRETES_SCRIPT = SCRIPT_DIR / "03-lembretes.py"

SCRIPT_COMARCA_COLUMNS = {
    "01-monitora.py": "data_ultimo_processamento",
    "02-peticoes.py": "data_peticoes",
}

WEB_PORT = 3001
DAY_START_HOUR = 12
DAY_END_HOUR = 19
DAY_WAIT_SECONDS = 20 * 60
NIGHT_WAIT_SECONDS = 40 * 60
NIGHTLY_LEMBRETES_HOUR = 22
DB_PATH = SCRIPT_DIR / "DB" / "unica.db"

app = Flask(__name__)
log_buffer = deque(maxlen=1000)
stream_listeners = []
state_lock = threading.Lock()
execution_lock = threading.Lock()
current_status = "Inicializando..."


def get_google_client():
  scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
  ]

  service_project_id = os.getenv("GCP_PROJECT_ID")
  service_private_key_id = os.getenv("GCP_PRIVATE_KEY_ID")
  service_private_key = os.getenv("GCP_PRIVATE_KEY")
  service_client_email = os.getenv("GCP_CLIENT_EMAIL")
  service_client_id = os.getenv("GCP_CLIENT_ID")

  if not all(
    [
      service_project_id,
      service_private_key_id,
      service_private_key,
      service_client_email,
      service_client_id,
    ]
  ):
    raise RuntimeError("Uma ou mais variaveis de ambiente GCP_* nao definidas.")

  if isinstance(service_private_key, str):
    service_private_key = service_private_key.replace("\\n", "\n")

  creds_dict = {
    "type": "service_account",
    "project_id": service_project_id,
    "private_key_id": service_private_key_id,
    "private_key": service_private_key,
    "client_email": service_client_email,
    "client_id": service_client_id,
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{service_client_email.replace('@', '%40')}",
    "universe_domain": "googleapis.com",
  }

  creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
  return gspread.authorize(creds)


def sync_comarcas_from_sheet():
  spreadsheet_id = os.getenv("GOOGLE_SHEET_ID")
  if not spreadsheet_id:
    raise RuntimeError("Variavel de ambiente GOOGLE_SHEET_ID nao definida.")

  client = get_google_client()
  spreadsheet = client.open_by_key(spreadsheet_id)
  planilha_comarcas = spreadsheet.worksheet("Comarcas")
  valores = planilha_comarcas.get("A10:B")

  comarcas_planilha = []
  for row in valores:
    nome = row[0].strip() if len(row) > 0 and row[0].strip() else None
    url = row[1].strip() if len(row) > 1 and row[1].strip() else ""
    if nome:
      match = re.search(r"/d/([^/]+)", url)
      sheet_id = match.group(1) if match else ""
      comarcas_planilha.append((nome, sheet_id))

  nomes_planilha = {nome for nome, _ in comarcas_planilha}
  agora = datetime.now().isoformat()

  with sqlite3.connect(DB_PATH) as conn:
    conn.execute(
      """
      CREATE TABLE IF NOT EXISTS Comarcas (
        nome TEXT PRIMARY KEY,
        spreadsheet_id TEXT,
        data_inclusao TEXT,
        data_ultimo_processamento TEXT
      )
      """
    )

    existentes = {
      row[0]
      for row in conn.execute("SELECT nome FROM Comarcas").fetchall()
    }

    inseridos = 0
    atualizados = 0
    removidos = 0

    for nome, sheet_id in comarcas_planilha:
      if nome not in existentes:
        conn.execute(
          "INSERT INTO Comarcas (nome, spreadsheet_id, data_inclusao, data_ultimo_processamento) VALUES (?, ?, ?, NULL)",
          (nome, sheet_id, agora),
        )
        inseridos += 1
      else:
        conn.execute(
          "UPDATE Comarcas SET spreadsheet_id = ? WHERE nome = ?",
          (sheet_id, nome),
        )
        atualizados += 1

    para_remover = existentes - nomes_planilha
    if para_remover:
      conn.executemany(
        "DELETE FROM Comarcas WHERE nome = ?",
        [(nome,) for nome in para_remover],
      )
      removidos = len(para_remover)

    conn.commit()

  return inseridos, atualizados, removidos, len(comarcas_planilha)


def emit(message):
    """Registra mensagem e envia para listeners do browser."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line, flush=True)

    with state_lock:
        log_buffer.append(line)
        for q in stream_listeners[:]:
            try:
                q.put(line)
            except Exception:
                if q in stream_listeners:
                    stream_listeners.remove(q)


def set_status(message):
    global current_status
    with state_lock:
        current_status = message
    emit(message)


def log(msg):
    emit(msg)


def get_wait_seconds(now=None):
    """Define downtime dinamico por faixa horaria.

    - 12:00 ate 18:59 -> 20 minutos
    - fora desse periodo -> 40 minutos
    """
    if now is None:
        now = datetime.now()

    if DAY_START_HOUR <= now.hour < DAY_END_HOUR:
        return DAY_WAIT_SECONDS

    return NIGHT_WAIT_SECONDS


def _format_elapsed(value):
    if not value:
        return "nunca"

    try:
        if isinstance(value, str):
            value = value.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(value)
        else:
            parsed = value

        delta = datetime.now() - parsed
        total_seconds = max(int(delta.total_seconds()), 0)

        if total_seconds < 60:
            return "agora"

        minutes = total_seconds // 60
        hours, minutes = divmod(minutes, 60)
        days, hours = divmod(hours, 24)

        parts = []
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        if minutes and len(parts) < 2:
            parts.append(f"{minutes}m")

        return " ".join(parts) or "agora"
    except Exception:
        return str(value)


def load_matrix_rows():
    with sqlite3.connect(DB_PATH) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(Comarcas)")}

        select_parts = ["nome"]
        for column in ("data_ultimo_processamento", "data_peticoes", "data_lembretes"):
            if column in columns:
                select_parts.append(column)
            else:
                select_parts.append(f"NULL AS {column}")

        query = f"""
            SELECT {', '.join(select_parts)}
            FROM Comarcas
            ORDER BY nome COLLATE NOCASE
        """
        rows = conn.execute(query).fetchall()

    result = []
    for row in rows:
        result.append({
            "nome": row[0],
            "monitoramento": _format_elapsed(row[1]),
            "peticoes": _format_elapsed(row[2]),
            "lembretes": _format_elapsed(row[3]),
        })

    return result


def _parse_db_timestamp(value):
    if not value:
        return None

    if isinstance(value, datetime):
        return value

    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    return None


def _delay_sort_key(value):
    parsed = _parse_db_timestamp(value)
    if parsed is None:
        # Datas ausentes/invalidas sao tratadas como mais atrasadas.
        return (0, float("-inf"))

    try:
        return (1, parsed.timestamp())
    except Exception:
        return (0, float("-inf"))


def get_oldest_comarca_info(column_name):
    with sqlite3.connect(DB_PATH) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(Comarcas)")}
        if column_name not in columns:
            return None, None

        row = conn.execute(
            f"""
            SELECT nome, {column_name}
            FROM Comarcas
          WHERE spreadsheet_id IS NOT NULL AND spreadsheet_id != ''
            ORDER BY
                CASE WHEN {column_name} IS NULL THEN 0 ELSE 1 END,
                {column_name} ASC,
                nome COLLATE NOCASE ASC
            LIMIT 1
            """
        ).fetchone()

    if not row:
        return None, None

    return row[0], row[1]


def get_all_active_comarcas():
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT nome
            FROM Comarcas
            WHERE spreadsheet_id IS NOT NULL AND spreadsheet_id != ''
            ORDER BY nome COLLATE NOCASE ASC
            """
        ).fetchall()

    return [row[0] for row in rows]


def run_nightly_lembretes_batch(now, last_run_date):
    run_date = now.date()
    if now.hour < NIGHTLY_LEMBRETES_HOUR:
        return last_run_date

    if last_run_date == run_date:
        return last_run_date

    comarcas = get_all_active_comarcas()
    if not comarcas:
        log("Lote noturno de lembretes: nenhuma comarca ativa para processar.")
        return run_date

    log(
        "Lote noturno de lembretes iniciado "
        f"({len(comarcas)} comarcas, apos {NIGHTLY_LEMBRETES_HOUR}:00)."
    )

    success = 0
    failed = 0
    for comarca in comarcas:
        set_status(f"Lote noturno: executando 03-lembretes.py para {comarca}")
        ok = execute_script(LEMBRETES_SCRIPT, comarca=comarca)
        if ok:
            success += 1
        else:
            failed += 1

    log(
        "Lote noturno de lembretes concluido: "
        f"{success} sucesso(s), {failed} falha(s)."
    )
    return run_date


def get_most_delayed_script():
    selected_script = None
    selected_comarca = None
    selected_value = None
    selected_key = None

    for script in SCRIPTS:
        comarca = None
        value = None

        column_name = SCRIPT_COMARCA_COLUMNS.get(script.name)
        if column_name:
            comarca, value = get_oldest_comarca_info(column_name)

        key = _delay_sort_key(value)
        if selected_key is None or key < selected_key:
            selected_key = key
            selected_script = script
            selected_comarca = comarca
            selected_value = value

    return selected_script, selected_comarca, selected_value


def execute_script(script_path, comarca=None):
    """Executa um script Python com streaming de saida em tempo real."""
    if not script_path.exists():
        log(f"Erro: Script nao encontrado: {script_path}")
        return False

    python = VENV_PYTHON if VENV_PYTHON.exists() else "python3"

    log(f"Iniciando: {script_path.name}")
    try:
        command = [str(python), "-u", str(script_path), "--headless"]
        if comarca:
            command.extend(["--comarca", comarca])

        process = subprocess.Popen(
            command,
            cwd=str(SCRIPT_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        if process.stdout is not None:
            for raw_line in process.stdout:
                line = raw_line.strip()
                if line:
                    log(f"{script_path.name} | {line}")

        result_code = process.wait()

        if result_code == 0:
            log(f"Concluido: {script_path.name}")
        else:
            log(f"{script_path.name} finalizou com codigo: {result_code}")

        return result_code == 0
    except Exception as e:
        log(f"Erro ao executar {script_path.name}: {e}")
        return False


def main():
    """Loop principal."""
    set_status("Orquestrador iniciado")
    log(
        "Downtime dinamico: 20 minutos entre 12:00-19:00 e "
        "40 minutos fora desse periodo"
    )
    log(f"Scripts: {', '.join(s.name for s in SCRIPTS)}")
    log(
        "Lote noturno: 03-lembretes.py para todas as comarcas "
        f"apos {NIGHTLY_LEMBRETES_HOUR}:00"
    )
    log("-" * 60)
    nightly_lembretes_last_run_date = None

    try:
        while True:
            now = datetime.now()

            try:
                inseridos, atualizados, removidos, total = sync_comarcas_from_sheet()
                log(
                    "Comarcas sincronizadas da planilha: "
                    f"{inseridos} inseridas, {atualizados} atualizadas, "
                    f"{removidos} removidas (total: {total})"
                )
            except Exception as e:
                log(f"Falha ao sincronizar comarcas da planilha: {e}")

            with execution_lock:
                nightly_lembretes_last_run_date = run_nightly_lembretes_batch(
                    now,
                    nightly_lembretes_last_run_date,
                )

            script, comarca, delay_value = get_most_delayed_script()
            atraso = _format_elapsed(delay_value)

            if comarca is None:
                wait_seconds = get_wait_seconds()
                wait_minutes = wait_seconds // 60
                set_status(
                    "Nenhuma comarca valida na planilha. "
                    f"Nova verificacao em {wait_minutes} minutos"
                )
                time.sleep(wait_seconds)
                continue

            # Garante que nunca haja sobreposicao: a proxima chamada
            # so inicia apos a execucao atual terminar.
            with execution_lock:
                if comarca:
                    set_status(
                  f"Executando {script.name} para {comarca} "
                  f"(mais atrasado: {atraso})"
                )
                    execute_script(script, comarca=comarca)
                else:
                    set_status(f"Executando {script.name} (mais atrasado: {atraso})")
                    execute_script(script)

            wait_seconds = get_wait_seconds()
            wait_minutes = wait_seconds // 60
            set_status(f"Aguardando {wait_minutes} minutos ate a proxima execucao")
            time.sleep(wait_seconds)

    except KeyboardInterrupt:
        log("Orquestrador interrompido pelo usuario")
        sys.exit(0)
    except Exception as e:
        log(f"Erro fatal: {e}")
        sys.exit(1)


@app.route("/")
def index():
    return """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Orquestrador UNICA</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #0b1220;
      --panel: #111a2e;
      --line: #24324f;
      --text: #dbe6ff;
      --muted: #91a4cc;
      --accent: #7dd3fc;
    }
    * { box-sizing: border-box; }
    html, body {
      width: 100%;
      height: 100%;
      height: 100dvh;
      overflow: hidden;
      overscroll-behavior: none;
    }
    body {
      margin: 0;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      background: radial-gradient(circle at top, #17233e 0, var(--bg) 55%);
      color: var(--text);
      display: flex;
      justify-content: center;
    }
    .shell {
      width: min(1200px, 100%);
      max-width: 1200px;
      margin: 0;
      padding: 24px;
      height: 100%;
      max-height: 100%;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }
    .header {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: end;
      margin-bottom: 16px;
    }
    .title { margin: 0; font-size: 28px; }
    .subtitle { margin: 6px 0 0; color: var(--muted); }
    .badge {
      border: 1px solid var(--line);
      background: rgba(17, 26, 46, 0.9);
      padding: 10px 14px;
      border-radius: 999px;
      color: var(--accent);
      white-space: nowrap;
    }
    .panel {
      border: 1px solid var(--line);
      background: rgba(17, 26, 46, 0.92);
      border-radius: 18px;
      overflow: hidden;
      box-shadow: 0 20px 80px rgba(0, 0, 0, 0.35);
      flex: 1;
      min-height: 0;
      display: flex;
      flex-direction: column;
    }
    .matrix-block {
      padding: 16px;
      border-bottom: 1px solid var(--line);
      background: linear-gradient(180deg, rgba(24, 38, 68, 0.95), rgba(17, 26, 46, 0.9));
    }
    .matrix-head {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      margin-bottom: 12px;
      color: var(--muted);
    }
    .matrix-title {
      font-size: 14px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--accent);
    }
    .matrix-scroller {
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: rgba(6, 11, 20, 0.45);
      max-height: 30vh;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      min-width: 760px;
    }
    thead th {
      position: sticky;
      top: 0;
      z-index: 1;
      background: #132038;
      color: var(--accent);
      text-align: left;
      font-weight: 600;
      font-size: 13px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }
    th, td {
      padding: 10px 12px;
      border-bottom: 1px solid rgba(36, 50, 79, 0.7);
      white-space: nowrap;
    }
    tbody tr:hover {
      background: rgba(125, 211, 252, 0.06);
    }
    td:first-child, th:first-child {
      position: sticky;
      left: 0;
      background: inherit;
    }
    tbody td:first-child {
      color: #eef4ff;
      font-weight: 600;
    }
    .toolbar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 12px 16px;
      border-bottom: 1px solid var(--line);
      color: var(--muted);
    }
    #terminal {
      flex: 0 0 auto;
      min-height: 0;
      overflow-y: auto;
      overflow-x: hidden;
      padding: 16px;
      white-space: pre-wrap;
      word-break: break-word;
      line-height: 1.45;
    }
    .line { margin: 0 0 4px; }

    @media (max-width: 1024px) {
      .shell {
        padding: 16px;
      }
      .matrix-scroller {
        max-height: 26vh;
      }
    }

    @media (max-width: 768px) {
      .shell {
        padding: 10px;
      }
      .header {
        margin-bottom: 10px;
      }
      .title {
        font-size: 22px;
      }
      .subtitle {
        font-size: 13px;
      }
      .matrix-block {
        padding: 10px;
      }
      .matrix-scroller {
        max-height: 22vh;
      }
      .toolbar {
        padding: 10px 12px;
      }
      #terminal {
        padding: 12px;
      }
    }
  </style>
</head>
<body>
  <div class="shell">
    <div class="header">
      <div>
        <h1 class="title">Orquestrador UNICA</h1>
        <p class="subtitle">Saída em tempo real do orquestrador</p>
      </div>
      <div class="badge" id="status">Carregando...</div>
    </div>
    <div class="panel">
      <div class="matrix-block">
        <div class="matrix-head">
          <div>
            <div class="matrix-title">Matriz de execução</div>
            <div id="matrixUpdated">Atualizando dados...</div>
          </div>          
        </div>
        <div class="matrix-scroller">
          <table>
            <thead>
              <tr>
                <th>Comarca</th>
                <th>Monitoramento</th>
                <th>Petições</th>
                <th>Lembretes</th>
              </tr>
            </thead>
            <tbody id="matrixBody"></tbody>
          </table>
        </div>
      </div>
      <div class="toolbar">
        <span>Porta 3001</span>
        <span>Atualizacao ao vivo</span>
      </div>
      <div id="terminal"></div>
    </div>
  </div>
  <script>
    const terminal = document.getElementById('terminal');
    const status = document.getElementById('status');
    const matrixBody = document.getElementById('matrixBody');
    const matrixUpdated = document.getElementById('matrixUpdated');
    const MIN_TERMINAL_HEIGHT = 160;
    let renderedLogs = 0;

    function resizeTerminal() {
      const rect = terminal.getBoundingClientRect();
      const viewportHeight = window.innerHeight || document.documentElement.clientHeight;
      const available = Math.floor(viewportHeight - rect.top - 8);
      const height = Math.max(MIN_TERMINAL_HEIGHT, available);
      terminal.style.height = `${height}px`;
    }

    function renderLogs(lines) {
      if (!Array.isArray(lines)) return;

      if (lines.length < renderedLogs) {
        terminal.innerHTML = '';
        renderedLogs = 0;
      }

      for (let i = renderedLogs; i < lines.length; i += 1) {
        const line = document.createElement('div');
        line.className = 'line';
        line.textContent = lines[i];
        terminal.appendChild(line);
      }

      renderedLogs = lines.length;
      terminal.scrollTop = terminal.scrollHeight;
    }

    function renderMatrix(rows) {
      if (!Array.isArray(rows)) return;

      matrixBody.innerHTML = '';

      if (!rows.length) {
        const emptyRow = document.createElement('tr');
        emptyRow.innerHTML = '<td colspan="4">Nenhuma comarca encontrada.</td>';
        matrixBody.appendChild(emptyRow);
        resizeTerminal();
        return;
      }

      for (const row of rows) {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td>${row.nome || ''}</td>
          <td>${row.monitoramento || 'nunca'}</td>
          <td>${row.peticoes || 'nunca'}</td>
          <td>${row.lembretes || 'nunca'}</td>
        `;
        matrixBody.appendChild(tr);
      }

      resizeTerminal();
    }

    function shouldRefreshMatrix(message) {
      return /Concluido:|finalizou com codigo:|Erro ao executar/.test(message);
    }

    async function refreshLogs() {
      try {
        const response = await fetch('/api/logs');
        const data = await response.json();
        renderLogs(data.logs || []);
      } catch (_) {}
    }

    async function refreshMatrix() {
      try {
        const response = await fetch('/api/matrix');
        const data = await response.json();
        renderMatrix(data.rows || []);
        matrixUpdated.textContent = 'Atualizado em ' + (data.updated_at || 'agora');
      } catch (_) {}
    }

    fetch('/api/status')
      .then((response) => response.json())
      .then((data) => { status.textContent = data.status; })
      .catch(() => {});

    refreshLogs();
    refreshMatrix();
    resizeTerminal();
    setInterval(refreshLogs, 2000);
    setInterval(refreshMatrix, 30000);
    window.addEventListener('resize', resizeTerminal);

    const eventSource = new EventSource('/stream');
    eventSource.onmessage = function(event) {
      const line = document.createElement('div');
      line.className = 'line';
      line.textContent = event.data;
      terminal.appendChild(line);
      renderedLogs += 1;
      terminal.scrollTop = terminal.scrollHeight;
      status.textContent = event.data;

      if (shouldRefreshMatrix(event.data)) {
        refreshMatrix();
      }
    };
  </script>
</body>
</html>
"""


@app.route("/api/matrix")
def api_matrix():
  return jsonify({
    "updated_at": datetime.now().isoformat(timespec="seconds"),
    "rows": load_matrix_rows(),
  })


@app.route("/api/status")
def api_status():
    with state_lock:
        return jsonify({"status": current_status, "port": WEB_PORT})


@app.route("/api/logs")
def api_logs():
    with state_lock:
        return jsonify({"logs": list(log_buffer)})


@app.route("/stream")
def stream():
    q = Queue()
    with state_lock:
        stream_listeners.append(q)
        history = list(log_buffer)

    def generate():
        try:
            for line in history:
                yield f"data: {line}\\n\\n"

            while True:
                try:
                    line = q.get(timeout=30)
                    yield f"data: {line}\\n\\n"
                except Exception:
                    yield ": keepalive\\n\\n"
        finally:
            with state_lock:
                if q in stream_listeners:
                    stream_listeners.remove(q)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


if __name__ == "__main__":
    worker = threading.Thread(target=main, daemon=True)
    worker.start()
    app.run(host="0.0.0.0", port=WEB_PORT, debug=False, threaded=True)
