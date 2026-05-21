# Bibliotecas de Sistema
from datetime import datetime
import time
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import sys
from io import StringIO

# Bibliotecas de IA
import ollama
from flask import Flask, render_template
from flask_socketio import SocketIO

from dotenv import load_dotenv

from flask import Flask
from flask_cors import CORS
import threading
import time
import sys
from io import StringIO

app = Flask(__name__)
CORS(app)

messages = []
listeners = []

class TerminalCapture:
    def write(self, message):
        if message.strip():
            messages.append(message.strip())
            # Notifica listeners
            for listener in listeners[:]:
                try:
                    listener.put(message.strip())
                except:
                    listeners.remove(listener)
    
    def flush(self):
        pass

# Redireciona stdout
sys.stdout = TerminalCapture()

@app.route('/')
def index():
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Terminal</title>
        <style>
            body {{
                margin: 0;
                padding: 10px;
                font-family: 'Courier New', monospace;
                font-size: 12px;
                background: #1e1e1e;
                color: #00ff00;
            }}
            #terminal {{
                height: 90vh;
                overflow-y: auto;
                border: 1px solid #444;
                padding: 10px;
                white-space: pre-wrap;
                word-wrap: break-word;
            }}
        </style>
    </head>
    <body>
        <div id="terminal"></div>
        <script>
            const terminal = document.getElementById('terminal');
            const eventSource = new EventSource('/stream');
            eventSource.onmessage = function(event) {{
                terminal.textContent += event.data + '\\n';
                terminal.scrollTop = terminal.scrollHeight;
            }};
        </script>
    </body>
    </html>
    """

@app.route('/stream')
def stream():
    from queue import Queue
    q = Queue()
    listeners.append(q)
    
    def generate():
        # Envia mensagens anteriores
        for msg in messages:
            yield f"data: {msg}\n\n"
        
        # Envia novas mensagens
        while True:
            try:
                msg = q.get(timeout=30)
                yield f"data: {msg}\n\n"
            except:
                break
        
        if q in listeners:
            listeners.remove(q)
    
    return generate(), {'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache'}


# DEBUG, sim ou não
debug = False

# Definição de perfil e tipo de processo

scope = [
    'https://spreadsheets.google.com/feeds',
    'https://www.googleapis.com/auth/drive'
]


import os
import json
try:
    load_dotenv()
except Exception as e:
    print("Erro ao carregar .env:", e)

service_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
if not service_json:
    raise RuntimeError("Variavel de ambiente GOOGLE_SERVICE_ACCOUNT_JSON nao definida.")

creds_dict = json.loads(service_json)
if "private_key" in creds_dict and isinstance(creds_dict["private_key"], str):
    creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")

creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)

spreadsheet_id = os.getenv("GOOGLE_SPREADSHEET_ID")
if not spreadsheet_id:
    raise RuntimeError("Variavel de ambiente GOOGLE_SPREADSHEET_ID nao definida.")
spreadsheet = client.open_by_key(spreadsheet_id)


control_sheet = spreadsheet.worksheet("Controle")
cell_b1 = control_sheet.cell(1, 2).value

perfil = control_sheet.cell(1, 2).value
tipo_processo = control_sheet.cell(2, 2).value

sheet = spreadsheet.worksheet(perfil)

# Define funções

def vasculha_planilhas(spreadsheet):
    # Obtém a aba de controle
    control_sheet = spreadsheet.worksheet("Controle")
    status = control_sheet.cell(3, 2).value
    print(f"Comunicação com a planilha: {status}")
    
    # Itera sobre todas as abas
    for ws in spreadsheet.worksheets():
        valores = ws.get_all_values()
        if not valores or len(valores) < 2:
            continue

        cabecalho = valores[0]

        # Tenta localizar colunas, define padrão caso não existam
        try:
            col_num_processo = cabecalho.index("Número do Processo")
        except ValueError:
            continue

        col_controle = cabecalho.index("Controle") if "Controle" in cabecalho else 8
        col_resumo = cabecalho.index("Resumo") if "Resumo" in cabecalho else 5
        col_peticao = cabecalho.index("Texto da Petição") if "Texto da Petição" in cabecalho else 6

        for row in valores[1:]:
            # Extrai valores com segurança
            valor_controle = row[col_controle].strip() if col_controle < len(row) else ""
            resumo = row[col_resumo].strip() if col_resumo < len(row) else ""
            peticao = row[col_peticao].strip() if col_peticao < len(row) else ""

            # Critério: não está pronto E possui conteúdo relevante (Resumo ou Petição)
            if valor_controle != "Pronto":
                texto_a_processar = resumo if len(resumo) > 10 else peticao
                
                if len(texto_a_processar) > 10:
                    numero_processo = row[col_num_processo].strip() if col_num_processo < len(row) else None
                    print(f"Processo encontrado: {numero_processo} na planilha {ws.title}")
                    return numero_processo, ws.title, 1

    print("Nenhum processo pendente encontrado em nenhuma planilha.")
    return None, None, 0

def ollama_resumo(pedido):    
    pergunta_gemma = "Considere o seguinte pedido." \
    f"{pedido}" \
    "Resuma, da maneira mais objetiva possível, o pedido. Não mencione dados pessoais, como nomes, números de documento, números de processo, valores, etc. " \
    "O resumo deve ser genérico e breve (uma frase apenas, com o mínimo de palavras possível). " \
    "Se tiver mais de um pedido, retorne uma frase para cada um." \

    resumo = ollama.chat(
        model="cnmoro/gemma3-gaia-ptbr-4b:q4_k_m",
        messages=[{'role': 'user', 'content': f'{pergunta_gemma}'}],    
    )

    return(resumo['message']['content'])

def atualiza_controle_processo(numero_processo, nome_planilha, controle):
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

    sheet.update_cell(linha_alvo, 9, controle)

def gera_resumo(numero_processo, nome_planilha):
    sheet = spreadsheet.worksheet(nome_planilha)
    
    valores_coluna_b = sheet.col_values(2)
    linha_processo = None

    atualiza_controle_processo(numero_processo, nome_planilha, "Resumindo...")

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
        atualiza_controle_processo(numero_processo, nome_planilha, "Pronto")
        print(f"Resumo gravado na linha {linha_processo} da planilha {nome_planilha}")
    else:
        print("Nenhum resumo para gravar")  

def roda(spreadsheet):
    try:
        numero_processo, nome_planilha, retorno = vasculha_planilhas(spreadsheet)
        if retorno == 1:
            try:
                gera_resumo(numero_processo, nome_planilha)
            except Exception as e:
                print(f"Erro ao gerar resumo para o processo {numero_processo} na planilha {nome_planilha}: {e}")
        return retorno
    except Exception as e:
        print(f"Erro ao executar roda(): {e}")
        return 0

def executa(spreadsheet, intervalo_minutos=10):
    while True:
        try:
            retorno = roda(spreadsheet)
            if retorno == 0:
                print(f"[{datetime.now()}] Sem mais processos. Aguardando.")
            if retorno == 1:
                print(f"[{datetime.now()}] Resumo gerado.")                
        except Exception as e:
            print(f"[{datetime.now()}] erro ao executar roda(): {e}")
            retorno = 0

        if retorno == 1:
            continue

        time.sleep(intervalo_minutos * 60)

def running():
    while True:
        try:
            executa(spreadsheet, 10)
        except Exception as e:
            print(f"Erro no loop principal: {e}")
            time.sleep(60)


if __name__ == '__main__':
    thread = threading.Thread(target=running, daemon=True)
    thread.start()
    app.run(debug=False, host='0.0.0.0', port=5000)