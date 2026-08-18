# Bibliotecas de Sistema
from datetime import datetime
import time
import threading
import sys
import re
import os
import traceback
import logging
from collections import deque
from queue import Queue

# Bibliotecas externas
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import ollama
from flask import Flask, Response, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

app = Flask(__name__)
CORS(app)

messages = deque(maxlen=2000)
listeners = []
state_lock = threading.Lock()
current_status = "Inicializando..."
original_stdout = sys.stdout
original_stderr = sys.stderr

ACCESS_LOG_PATTERN = re.compile(
    r'^\d{1,3}(?:\.\d{1,3}){3} - - \[.*\] "(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) .+" \d{3} -$'
)

class TerminalCapture:
    def __init__(self, stream_type="stdout", original_stream=None):
        self.stream_type = stream_type
        self.original_stream = original_stream

    def write(self, message):
        if self.original_stream is not None:
            self.original_stream.write(message)

        lines = [line.strip() for line in str(message).splitlines() if line.strip()]
        if not lines:
            return

        for line in lines:
            # Evita poluir o painel com logs de acesso HTTP do servidor Flask.
            if ACCESS_LOG_PATTERN.match(line):
                continue

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            formatted_message = f"[{timestamp}] [{self.stream_type}] {line}"

            with state_lock:
                messages.append(formatted_message)
                global current_status
                current_status = formatted_message
                for listener in listeners[:]:
                    try:
                        listener.put(formatted_message)
                    except Exception:
                        if listener in listeners:
                            listeners.remove(listener)
    
    def flush(self):
        if self.original_stream is not None:
            self.original_stream.flush()

# Redireciona stdout
sys.stdout = TerminalCapture("stdout", original_stdout)
sys.stderr = TerminalCapture("stderr", original_stderr)

@app.route('/')
def index():
    return """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Resumos UNICA</title>
    <style>
        :root {
            color-scheme: dark;
            --bg: #0b1220;
            --panel: #111a2e;
            --line: #224036;
            --text: #dbe6ff;
            --muted: #8fbfa8;
            --accent: #86efac;
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
            background: radial-gradient(circle at top, #123328 0, var(--bg) 55%);
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
            max-width: 55%;
            overflow: hidden;
            text-overflow: ellipsis;
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
            background: linear-gradient(180deg, rgba(20, 52, 40, 0.95), rgba(17, 26, 46, 0.9));
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
            max-height: 26vh;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            min-width: 560px;
        }
        thead th {
            position: sticky;
            top: 0;
            z-index: 1;
            background: #123024;
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
            background: rgba(134, 239, 172, 0.08);
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
        .toolbar-right {
            display: flex;
            align-items: center;
            gap: 10px;
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
            .shell { padding: 16px; }
            .matrix-scroller { max-height: 22vh; }
        }

        @media (max-width: 768px) {
            .shell { padding: 10px; }
            .header { margin-bottom: 10px; }
            .title { font-size: 22px; }
            .subtitle { font-size: 13px; }
            .matrix-block { padding: 10px; }
            .toolbar { padding: 10px 12px; }
            #terminal { padding: 12px; }
        }
    </style>
</head>
<body>
    <div class="shell">
        <div class="header">
            <div>
                <h1 class="title">Serviço de resumos de petições da UNICA</h1>
                <p class="subtitle">Saida em tempo real da geracao de resumos</p>
            </div>
            <div class="badge" id="status">Carregando...</div>
        </div>
        <div class="panel">
            <div class="matrix-block">
                <div class="matrix-head">
                    <div>
                        <div class="matrix-title">Matriz de execucao</div>
                        <div id="matrixUpdated">Atualizando dados...</div>
                    </div>
                </div>
                <div class="matrix-scroller">
                    <table>
                        <thead>
                            <tr>
                                <th>Servico</th>
                                <th>Modelo</th>
                                <th>Porta</th>
                                <th>Status</th>
                            </tr>
                        </thead>
                        <tbody id="matrixBody"></tbody>
                    </table>
                </div>
            </div>
            <div class="toolbar">
                <span>Porta 5000</span>
                <div class="toolbar-right">
                    <span>Atualizacao ao vivo</span>
                </div>
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

        function renderMatrix(statusText) {
            matrixBody.innerHTML = '';
            const row = document.createElement('tr');
            row.innerHTML = `
                <td>Resumos</td>
                <td>cnmoro/gemma3-gaia-ptbr-4b:q4_k_m</td>
                <td>5000</td>
                <td>${statusText || 'Inicializando...'}</td>
            `;
            matrixBody.appendChild(row);
            matrixUpdated.textContent = 'Atualizado em ' + new Date().toISOString().replace('T', ' ').slice(0, 19);
            resizeTerminal();
        }

        async function refreshLogs() {
            try {
                const response = await fetch('/api/logs');
                const data = await response.json();
                renderLogs(data.logs || []);
            } catch (_) {}
        }

        async function refreshStatus() {
            try {
                const response = await fetch('/api/status');
                const data = await response.json();
                const current = data.status || 'Inicializando...';
                status.textContent = current;
                renderMatrix(current);
            } catch (_) {}
        }

        refreshLogs();
        refreshStatus();
        resizeTerminal();
        setInterval(refreshLogs, 2000);
        setInterval(refreshStatus, 5000);
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
            renderMatrix(event.data);
        };
    </script>
</body>
</html>
"""

@app.route('/stream')
def stream():
    q = Queue()

    with state_lock:
        listeners.append(q)
        history = list(messages)

    def generate():
        try:
            for msg in history:
                yield f"data: {msg}\\n\\n"

            while True:
                try:
                    msg = q.get(timeout=30)
                    yield f"data: {msg}\\n\\n"
                except Exception:
                    yield ": keepalive\\n\\n"
        finally:
            with state_lock:
                if q in listeners:
                    listeners.remove(q)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@app.route('/api/status')
def api_status():
    with state_lock:
        return jsonify({"status": current_status, "port": 5000})


@app.route('/api/logs')
def api_logs():
    with state_lock:
        return jsonify({"logs": list(messages)})


# DEBUG, sim ou não
debug = False
MODEL_NAME = "cnmoro/gemma3-gaia-ptbr-4b:q4_k_m"

# Definição de perfil e tipo de processo

scope = [
    'https://spreadsheets.google.com/feeds',
    'https://www.googleapis.com/auth/drive'
]


try:
    load_dotenv()
except Exception as e:
    print("Erro ao carregar .env:", e)
    raise
service_project_id = os.getenv("GCP_PROJECT_ID")
service_private_key_id = os.getenv("GCP_PRIVATE_KEY_ID")
service_private_key = os.getenv("GCP_PRIVATE_KEY")
service_client_email = os.getenv("GCP_CLIENT_EMAIL")
service_client_id = os.getenv("GCP_CLIENT_ID")

if not all([service_project_id, service_private_key_id, service_private_key, service_client_email, service_client_id]):
    raise RuntimeError("Uma ou mais variáveis de ambiente GCP_* não definidas.")

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
client = gspread.authorize(creds)

resumos_spreadsheet_id = os.getenv("RESUMOS_SPREADSHEET_ID")
if not resumos_spreadsheet_id:
    raise RuntimeError("Variavel de ambiente RESUMOS_SPREADSHEET_ID nao definida.")


# Define funções

def listar_planilhas(client, resumos_spreadsheet_id):
    """Retorna lista ordenada de IDs de planilhas da coluna B da aba Comarcas."""
    try:
        spreadsheet_resumo = with_retry(
            lambda: client.open_by_key(resumos_spreadsheet_id),
            "abrir planilha de resumos",
            retries=3,
            base_delay=2
        )
        planilha_comarcas = spreadsheet_resumo.worksheet("Comarcas")

        valores_coluna_b = planilha_comarcas.col_values(2)
        regex_id = r"/d/([^/]+)"
        ids_extraidos = []

        for v in valores_coluna_b[9:]:
            url = str(v).strip()
            if url and url != "-":
                match = re.search(regex_id, url)
                if match:
                    ids_extraidos.append(match.group(1))

        if not ids_extraidos:
            print(f"Nenhum ID válido encontrado na coluna B de {planilha_comarcas.title}.")

        return ids_extraidos

    except Exception as e:
        log_exception("listar planilhas de resumos", e)
        return []


def log_exception(contexto, erro):
    print(f"[ERRO] {contexto}: {type(erro).__name__}: {erro}")
    print(traceback.format_exc())


# Erros que não adianta tentar novamente
NON_RETRYABLE = (
    PermissionError,
    ValueError,
    KeyError,
    TypeError,
)


def with_retry(operation, operation_name, retries=3, base_delay=2):
    last_error = None

    for tentativa in range(1, retries + 1):
        try:
            return operation()
        except NON_RETRYABLE:
            raise
        except Exception as erro:
            last_error = erro
            if tentativa == retries:
                break

            espera = base_delay * (2 ** (tentativa - 1))
            print(
                f"[WARN] Falha em '{operation_name}' "
                f"({tentativa}/{retries}): {type(erro).__name__}: {erro}. "
                f"Tentando novamente em {espera}s."
            )
            time.sleep(espera)

    raise last_error


def validar_inicio():
    print("[INIT] Validando acesso ao Google Sheets...")
    try:
        planilha_resumos = with_retry(
            lambda: client.open_by_key(resumos_spreadsheet_id),
            "validar planilha RESUMOS_SPREADSHEET_ID",
            retries=3,
            base_delay=2,
        )
        planilha_resumos.worksheet("Comarcas")
        print("[INIT] Google Sheets OK.")
    except Exception as erro:
        log_exception("validacao de Google Sheets", erro)
        return False

    print("[INIT] Validando conectividade com Ollama...")
    try:
        response = with_retry(
            lambda: ollama.list(),
            "verificar servidor Ollama",
            retries=3,
            base_delay=2,
        )

        model_names = []
        models_list = []
        if isinstance(response, dict):
            models_list = response.get("models", [])
        elif hasattr(response, "models"):
            models_list = response.models or []

        for model in models_list:
            name = None
            if isinstance(model, dict):
                name = model.get("name") or model.get("model")
            elif hasattr(model, "model"):
                name = model.model
            elif hasattr(model, "name"):
                name = model.name
            if name:
                model_names.append(name)

        if model_names:
            print(f"[INIT] Ollama OK. Modelos disponiveis: {', '.join(model_names)}")
            if MODEL_NAME not in model_names:
                print(
                    f"[WARN] O modelo '{MODEL_NAME}' nao foi encontrado. "
                    "A geracao de resumo pode falhar se ele nao estiver carregado."
                )
        else:
            print(
                "[WARN] Ollama respondeu, mas nenhum modelo foi listado. "
                "A geracao de resumo pode falhar se o modelo nao estiver carregado."
            )
    except Exception as erro:
        log_exception("validacao de Ollama", erro)
        return False

    return True

def vasculha_planilhas(spreadsheet):
    # Obtém a aba de controle
    control_sheet = spreadsheet.worksheet("Controle")    
    planilha_alvo = (control_sheet.cell(1, 2).value or "").strip()

    if planilha_alvo and planilha_alvo != "-":
        processo_alvo = (control_sheet.cell(2, 2).value or "").strip()
        if not processo_alvo or processo_alvo == "-":
            print(f"Planilha alvo '{planilha_alvo}' encontrada, mas sem processo definido (B2 vazio ou '-').")
            return None, None, 0
        print(f"Processo pendente encontrado: Planilha '{planilha_alvo}', Processo {processo_alvo}")
        return processo_alvo, planilha_alvo, 1            

    print("Nenhum processo pendente encontrado em nenhuma planilha.")
    return None, None, 0

def ollama_resumo(pedido):    
    pergunta_gemma = "Considere o seguinte pedido." \
    f"{pedido}" \
    "Resuma, da maneira mais objetiva possível, o pedido. Não mencione dados pessoais, como nomes, números de documento, números de processo, valores, etc. " \
    "O resumo deve ser genérico e breve (uma frase apenas, com o mínimo de palavras possível). " \
    "Se tiver mais de um pedido, retorne uma frase para cada um." \

    resumo = with_retry(
        lambda: ollama.chat(
            model=MODEL_NAME,
            messages=[{'role': 'user', 'content': f'{pergunta_gemma}'}],
        ),
        "gerar resumo no Ollama",
        retries=3,
        base_delay=2,
    )

    return(resumo['message']['content'])

def atualiza_controle_processo(spreadsheet, numero_processo, nome_planilha, controle):
    sheet = spreadsheet.worksheet(nome_planilha)
    cabecalho = sheet.row_values(1)

    try:
        col_num_processo = cabecalho.index("Número do Processo") + 1
    except ValueError:
        raise ValueError("Cabeçalho 'Número do Processo' não encontrado na planilha.")

    valores_processo = sheet.col_values(col_num_processo)

    linha_alvo = None
    for i, valor in enumerate(valores_processo[1:], start=2):
        if str(valor).strip() == str(numero_processo).strip():
            linha_alvo = i
            break

    if linha_alvo is None:
        raise ValueError(f"Processo {numero_processo} não encontrado na planilha {nome_planilha}.")

    sheet.update_cell(linha_alvo, 9, controle)

def gera_resumo(spreadsheet, numero_processo, nome_planilha):
    sheet = spreadsheet.worksheet(nome_planilha)
    
    valores_coluna_b = sheet.col_values(2)
    linha_processo = None

    atualiza_controle_processo(spreadsheet, numero_processo, nome_planilha, "Resumindo...")

    for i, valor_b in enumerate(valores_coluna_b[1:], start=2):
        if str(valor_b).strip() == str(numero_processo).strip():
            linha_processo = i
            break

    if not linha_processo:
        print(f"Processo {numero_processo} não encontrado na planilha {nome_planilha}")
        return None, None

    texto_peticao = sheet.cell(linha_processo, 7).value or ""

    print(f"Planilha: {nome_planilha}")
    print(f"Processo: {numero_processo}")
    print(f"Texto da petição: {texto_peticao[:200]}...")

    if len(texto_peticao.encode('utf-8')) > 10000:
        resumo_ollama = "Texto maior do que 10.000 bytes, provavelmente pedido complexo"
    elif texto_peticao == "Erro: petição em imagem, sem texto copiável":
        resumo_ollama = "Erro: petição em imagem, sem texto copiável"
    elif texto_peticao == "Alerta: não há documento do tipo PET sem despacho posterior.":
        resumo_ollama = "Alerta: não há documento do tipo PET sem despacho posterior."
    elif texto_peticao.startswith("Erro: Message: no such element"):
        resumo_ollama = "Erro: problema com a captura no Selenium."
    else:
        resumo_ollama = ollama_resumo(texto_peticao)
    
    print(f"Resumo: {resumo_ollama}")

    if resumo_ollama:
        sheet.update_cell(linha_processo, 6, resumo_ollama)
        atualiza_controle_processo(spreadsheet, numero_processo, nome_planilha, "Pronto")
        print(f"Resumo gravado na linha {linha_processo} da planilha {nome_planilha}")
    else:
        print("Nenhum resumo para gravar")  

def roda(spreadsheet):
    try:
        numero_processo, nome_planilha, retorno = vasculha_planilhas(spreadsheet)
        if retorno == 1:
            try:
                gera_resumo(spreadsheet, numero_processo, nome_planilha)
            except Exception as e:
                log_exception(
                    f"gerar resumo para processo {numero_processo} na planilha {nome_planilha}",
                    e,
                )
        return retorno
    except Exception as e:
        log_exception("executar roda()", e)
        return 0

def executa(spreadsheet, pausa_entre_processos=5):
    print(f"[{datetime.now()}] Iniciando execução do processo de resumos.")
    resumos_feitos = 0
    ultimo_processo = None

    while True:
        try:
            retorno = roda(spreadsheet)
            if retorno == 0:
                print(f"[{datetime.now()}] Sem mais processos nesta planilha. Total de resumos: {resumos_feitos}.")
                return resumos_feitos

            # Detecta se o controle ainda aponta o mesmo processo (fórmula não recalculou)
            control_sheet = spreadsheet.worksheet("Controle")
            processo_atual = (control_sheet.cell(2, 2).value or "").strip()
            if processo_atual and processo_atual == ultimo_processo:
                print(
                    f"[WARN] Controle ainda aponta o mesmo processo ({processo_atual}). "
                    "Possível delay no recalculo da planilha. Saindo desta planilha."
                )
                return resumos_feitos

            ultimo_processo = processo_atual
            resumos_feitos += 1
            print(f"[{datetime.now()}] Resumo #{resumos_feitos} gerado. Verificando proximo...")
            time.sleep(pausa_entre_processos)
        except Exception as e:
            log_exception("executar roda() em executa()", e)
            print(f"[{datetime.now()}] Erro durante processamento. Total de resumos nesta planilha: {resumos_feitos}.")
            return resumos_feitos

def running():
    erros_consecutivos = 0
    rodadas_sem_resumo = 0

    while True:
        # Carrega lista de planilhas no inicio de cada rodada completa
        print(f"[{datetime.now()}] Carregando lista de planilhas...")
        lista_ids = listar_planilhas(client, resumos_spreadsheet_id)

        if not lista_ids:
            print("[WARN] Nenhuma planilha encontrada. Tentando novamente em 60s.")
            time.sleep(60)
            continue

        print(f"[INFO] {len(lista_ids)} planilha(s) na fila.")
        total_resumos_rodada = 0

        for idx, spreadsheet_key in enumerate(lista_ids, start=1):
            etapa = "iniciando ciclo"
            try:
                print(f"\n[{datetime.now()}] === Planilha {idx}/{len(lista_ids)}: {spreadsheet_key} ===")

                etapa = "abrir planilha"
                key = spreadsheet_key  # captura para lambda
                spreadsheet = with_retry(
                    lambda: client.open_by_key(key),
                    f"abrir planilha ({key})",
                    retries=3,
                    base_delay=2,
                )

                etapa = "executar processamento"
                resumos = executa(spreadsheet)
                erros_consecutivos = 0
                total_resumos_rodada += resumos

                if resumos == 0:
                    print("[INFO] Planilha sem pendencias.")
                else:
                    print(f"[INFO] {resumos} resumo(s) feito(s).")

                time.sleep(5)

            except PermissionError as e:
                log_exception(f"planilha {idx}/{len(lista_ids)} na etapa '{etapa}'", e)
                print(
                    "[DICA] Planilha nao compartilhada com a service account. "
                    "Pulando para a proxima."
                )
                time.sleep(5)

            except (ValueError, KeyError, TypeError) as e:
                log_exception(f"planilha {idx}/{len(lista_ids)} na etapa '{etapa}' (erro de dados)", e)
                print("[INFO] Erro de dados — pulando esta planilha.")
                time.sleep(5)

            except Exception as e:
                erros_consecutivos += 1
                log_exception(f"planilha {idx}/{len(lista_ids)} na etapa '{etapa}'", e)

                if erros_consecutivos >= 5:
                    pausa = 300
                    print(
                        f"[WARN] {erros_consecutivos} erros consecutivos. "
                        f"Pausa longa de {pausa}s para evitar sobrecarga."
                    )
                else:
                    pausa = min(60 * erros_consecutivos, 300)

                print(f"[INFO] Proximo ciclo em {pausa}s.")
                time.sleep(pausa)

        print(f"\n[{datetime.now()}] === Rodada completa. {total_resumos_rodada} resumo(s) nesta rodada. ===")

        if total_resumos_rodada == 0:
            rodadas_sem_resumo += 1
            print(f"[INFO] {rodadas_sem_resumo}/3 rodada(s) consecutiva(s) sem resumos.")
            if rodadas_sem_resumo >= 3:
                print("[INFO] 3 rodadas sem resumos. Descansando por 1 hora.")
                time.sleep(3600)
                rodadas_sem_resumo = 0
            else:
                time.sleep(10)
        else:
            rodadas_sem_resumo = 0
            time.sleep(10)


if __name__ == '__main__':
    if not validar_inicio():
        print("[FATAL] Falha nas validacoes iniciais. Encerrando aplicacao.")
        sys.exit(1)

    # Desativa access logs do Flask/Werkzeug; o painel mostra apenas logs de negócio.
    werkzeug_logger = logging.getLogger("werkzeug")
    werkzeug_logger.setLevel(logging.ERROR)
    werkzeug_logger.disabled = True

    thread = threading.Thread(target=running, daemon=True)
    thread.start()
    app.run(debug=False, host='0.0.0.0', port=5000)