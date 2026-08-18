#!/usr/bin/env python3
# 02-peticoes.py - Consolidado do notebook Unica-02-Baixa-PDFs.ipynb

import argparse

parser = argparse.ArgumentParser(description="Baixa petições do eproc")
parser.add_argument("--headless", action="store_true", help="Rodar em modo headless (sem interface gráfica)")
parser.add_argument("--debug", action="store_true", help="Imprimir mensagens de debug")
parser.add_argument("--comarca", type=str, help="Nome da comarca a processar")
args = parser.parse_args()

# ============================================================
# CELL 1: Importações, setup, login no eproc
# ============================================================

from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException

from datetime import datetime
import platform
import time
import re
import os
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from eproc_driver import eproc as eproc
import sqlite3
import PyPDF2
import gc

from dotenv import load_dotenv

import gspread
from oauth2client.service_account import ServiceAccountCredentials

# `ollama` removido das importações — funções que o referenciam
#+permancem definidas caso sejam usadas no futuro.
if platform.system() == "Windows":
    pasta_downloads = r"D:\Douglas\Downloads"
else:
    pasta_downloads = "/tmp/unica_pdfs"

debug = args.debug
comarca_solicitada = args.comarca.strip() if args.comarca else None

scope = [
    'https://spreadsheets.google.com/feeds',
    'https://www.googleapis.com/auth/drive'
]

load_dotenv(override=True)

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

spreadsheet_id = os.getenv("GOOGLE_SHEET_ID")

if not spreadsheet_id:
    raise RuntimeError("Variável de ambiente GOOGLE_SHEET_ID não definida.")

spreadsheet = client.open_by_key(spreadsheet_id)

control_sheet = spreadsheet.worksheet("Controle")
cell_b1 = control_sheet.cell(1, 2).value

perfil = control_sheet.cell(1, 2).value
tipo_processo = control_sheet.cell(2, 2).value

print("Perfil escolhido:", perfil)
print("Tipo de Processo:", tipo_processo)

if debug:
    print(f"[DEBUG] pasta_downloads: {pasta_downloads}")

# Limpa a pasta de downloads antes de iniciar
if os.path.exists(pasta_downloads):
    for f in os.listdir(pasta_downloads):
        caminho = os.path.join(pasta_downloads, f)
        if os.path.isfile(caminho):
            os.remove(caminho)
    print(f"Pasta de downloads limpa: {pasta_downloads}")

navegador = eproc.novo_browser(pasta_downloads, headless=args.headless)

if debug:
    print("[DEBUG] Navegador iniciado.")

username = os.getenv("EPROC_USERNAME")
password = os.getenv("EPROC_PASSWORD")
pyotop_code = os.getenv("EPROC_PYOTP_CODE")

eproc.login_no_eproc(navegador, username, password, pyotop_code)

if debug:
    print("[DEBUG] Login realizado.")


# ============================================================
# CELL 2: Percorre comarcas e seleciona a primeira incompleta
# ============================================================

db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "DB", "unica.db")

with sqlite3.connect(db_path) as conn:
    colunas = [row[1] for row in conn.execute("PRAGMA table_info(Comarcas)").fetchall()]
    if "data_peticoes" not in colunas:
        conn.execute("ALTER TABLE Comarcas ADD COLUMN data_peticoes TEXT")
        conn.commit()
        print("Coluna 'data_peticoes' adicionada à tabela Comarcas.")

with sqlite3.connect(db_path) as conn:
    comarcas = conn.execute("SELECT nome, spreadsheet_id FROM Comarcas").fetchall()

comarcas_ativas = []

for nome, sid in comarcas:
    if not sid:
        print(f"  {nome}: sem spreadsheet_id, pulando.")
        continue
    try:
        planilha = client.open_by_key(sid)
        aba_controle = planilha.worksheet("Controle")
        valor_b3 = (aba_controle.cell(3, 2).value or "").strip()
        if valor_b3 and valor_b3 != "-":
            comarcas_ativas.append(nome)
            print(f"  {nome}: B3 = '{valor_b3}' → INCOMPLETA")
        else:
            print(f"  {nome}: B3 = '{valor_b3}' → completa ou vazia")
    except Exception as e:
        print(f"  {nome}: erro ao acessar planilha ({type(e).__name__}: {e})")

print(f"\nComarcas ativas: {len(comarcas_ativas)} de {len(comarcas)}")
print(comarcas_ativas)

if comarcas_ativas:
    perfil = comarcas_ativas[0]
    print(f"\nPerfil selecionado: {perfil}")
else:
    print("\nNenhuma comarca incompleta encontrada.")
    perfil = None

if comarca_solicitada:
    perfil_solicitado = None
    for nome, _sid in comarcas:
        if nome.lower() == comarca_solicitada.lower():
            perfil_solicitado = nome
            break

    if perfil_solicitado is None:
        raise RuntimeError(f"Comarca solicitada não encontrada no banco de dados: {comarca_solicitada}")

    perfil = perfil_solicitado
    print(f"\nComarca solicitada por parâmetro: {perfil}")

if perfil:
    eproc.entrar_no_perfil(navegador, perfil)
    print(f"Entrou no perfil: {perfil}")

    with sqlite3.connect(db_path) as conn:
        sid = conn.execute("SELECT spreadsheet_id FROM Comarcas WHERE nome = ?", (perfil,)).fetchone()[0]
    spreadsheet = client.open_by_key(sid)
    sheet = spreadsheet.worksheet(perfil)
    print(f"Planilha aberta: {perfil} (id: {sid})")
else:
    # Sem comarca ativa, encerra
    try:
        navegador.quit()
    except Exception:
        pass
    gc.collect()
    print("Nenhuma comarca para processar. Encerrando.")
    exit(0)


# ============================================================
# CELL 3: Definição de funções
# ============================================================

def pega_tabela_pagina(dados_tabela):
    tabela = navegador.find_element(By.ID, "tabelaLocalizadores")
    linhas = tabela.find_elements(By.TAG_NAME, "tr")[1:]
    lastpage = False
    while lastpage is False:
        for linha in linhas:
            WebDriverWait(navegador, 10).until(
                EC.presence_of_element_located((By.XPATH, "//table[@id='tabelaLocalizadores']/tbody"))
            )
            colunas = linha.find_elements(By.TAG_NAME, "td")
            if len(colunas) >= 4:
                dados_tabela.append([
                    colunas[1].text.split('\n')[0],
                    colunas[2].text.split('\n')[0],
                    colunas[3].text.split('\n')[0],
                    colunas[-1].text.split('\n')[0]
                ])
            
            lastpage = True

def _baixar_pdf(navegador, link_element, caminho_pdf):
    """
    Extrai a URL de download do PDF, navega até o viewer para
    obter a URL real do PDF e baixa via fetch() no navegador.
    Retorna (None, caminho_pdf) em caso de sucesso ou (erro, None).
    """
    import base64

    # Salva URL atual para voltar depois
    url_processo = navegador.current_url

    # Extrai a URL do href do link
    href = link_element.get_attribute("href") or ""
    
    # Tenta extrair strLinkDownload do data-dadosiconlink
    dados_icon = link_element.get_attribute("data-dadosiconlink") or ""
    download_url = None
    if dados_icon:
        try:
            decoded = base64.b64decode(dados_icon).decode('utf-8', errors='replace')
            match = re.search(r'strLinkDownload";s:\d+:"([^"]+)"', decoded)
            if match:
                download_url = match.group(1)
        except Exception:
            pass

    if not download_url:
        download_url = href

    if not download_url:
        return "Não foi possível obter a URL do documento.", None

    # Monta URL completa
    if not download_url.startswith('http'):
        from urllib.parse import urljoin
        download_url = urljoin(url_processo, download_url)

    if debug:
        print(f"[DEBUG] URL do documento: {download_url[:150]}")

    # Navega para a URL do documento (abre o viewer)
    navegador.get(download_url)
    time.sleep(3)

    # Tenta extrair a URL real do PDF de dentro do viewer
    pdf_url = None

    # Verifica se o conteúdo da página é diretamente o PDF (object/embed/iframe)
    for selector in ["iframe[src*='controlador']", "iframe", "embed[src]", "object[data]"]:
        try:
            el = navegador.find_element(By.CSS_SELECTOR, selector)
            pdf_url = el.get_attribute("src") or el.get_attribute("data")
            if pdf_url:
                if debug:
                    print(f"[DEBUG] URL do PDF encontrada via {selector}: {pdf_url[:150]}")
                break
        except Exception:
            continue

    # Se não encontrou iframe, tenta procurar links de download na página
    if not pdf_url:
        try:
            page_source = navegador.page_source
            # Procura URLs de download no source
            matches = re.findall(r'(controlador\.php\?acao=acessar_documento_implementacao[^"\'>\s]+)', page_source)
            if matches:
                pdf_url = matches[0]
                if debug:
                    print(f"[DEBUG] URL do PDF via source: {pdf_url[:150]}")
        except Exception:
            pass

    # Se não encontrou, tenta usar a URL que o viewer usa para renderizar
    if not pdf_url:
        try:
            # Procura a variável JS que contém a URL do PDF
            pdf_url = navegador.execute_script("""
                // Tenta encontrar a URL do PDF no DOM
                var iframe = document.querySelector('iframe');
                if (iframe && iframe.src) return iframe.src;
                var embed = document.querySelector('embed');
                if (embed && embed.src) return embed.src;
                var obj = document.querySelector('object');
                if (obj && obj.data) return obj.data;
                return null;
            """)
        except Exception:
            pass

    if not pdf_url:
        if debug:
            print(f"[DEBUG] Page title: {navegador.title}")
            print(f"[DEBUG] Page URL: {navegador.current_url}")
            print(f"[DEBUG] Page source (500 chars): {navegador.page_source[:500]}")
        # Volta para a página do processo
        navegador.get(url_processo)
        time.sleep(2)
        return "Não foi possível encontrar a URL real do PDF no viewer.", None

    # Monta URL completa do PDF
    if not pdf_url.startswith('http'):
        from urllib.parse import urljoin
        pdf_url = urljoin(navegador.current_url, pdf_url)

    # Baixa o PDF usando fetch() no contexto do navegador
    base64_pdf = navegador.execute_async_script("""
        const url = arguments[0];
        const callback = arguments[arguments.length - 1];
        fetch(url)
            .then(r => r.arrayBuffer())
            .then(buf => {
                const bytes = new Uint8Array(buf);
                let binary = '';
                const chunkSize = 8192;
                for (let i = 0; i < bytes.byteLength; i += chunkSize) {
                    const chunk = bytes.subarray(i, i + chunkSize);
                    binary += String.fromCharCode.apply(null, chunk);
                }
                callback(btoa(binary));
            })
            .catch(err => callback('ERROR:' + err.message));
    """, pdf_url)

    # Volta para a página do processo
    navegador.get(url_processo)
    time.sleep(2)

    if not base64_pdf or (isinstance(base64_pdf, str) and base64_pdf.startswith('ERROR:')):
        return f"Falha ao baixar PDF via fetch: {base64_pdf}", None

    pdf_content = base64.b64decode(base64_pdf)

    if pdf_content[:4] != b'%PDF':
        if debug:
            print(f"[DEBUG] Conteúdo recebido não é PDF. Primeiros 200 bytes: {pdf_content[:200]}")
        return "Conteúdo recebido não é um PDF válido.", None

    os.makedirs(os.path.dirname(caminho_pdf), exist_ok=True)
    with open(caminho_pdf, 'wb') as f:
        f.write(pdf_content)
    print(f"PDF baixado e salvo em: {caminho_pdf}")
    return None, caminho_pdf

def pega_ultima_peticao(navegador, num_processo):
    """
    Localiza a última petição ("PET") disponível no processo informado,
    captura a requisição real feita pelo navegador (Selenium Wire) para baixar o PDF
    e salva o arquivo localmente.

    Parâmetros:
        navegador     -> instância do Selenium Wire WebDriver já autenticada no eproc.
        num_processo  -> número do processo (será usado no nome do PDF).

    Retorna:
        (evento_id, caminho_pdf) se o download foi bem-sucedido.
        (None, None) caso não haja petição ou falha no download.
    """
    documentos_eventos = []
    eventos = navegador.find_elements(By.CLASS_NAME, "td-evento")

    for evento in eventos:
        doc_id = evento.get_dom_attribute("id")
        tr_element = evento.find_element(By.XPATH, "./ancestor::tr")
        evento_id = tr_element.find_element(By.XPATH, './td[2]').text
        evento_id = ''.join(filter(str.isdigit, evento_id))

        try:
            infra_link = evento.find_element(By.XPATH, ".//*[contains(@class, 'infraLinkDoc')]")
            data_nome = infra_link.get_attribute("data-nome")
        except Exception:
            data_nome = None

        documentos_eventos.append((doc_id, data_nome, evento_id))

    documentos_eventos_filtrados = [item for item in documentos_eventos if item[1] and "PET" in item[1]]    
    despachos_eventos_filtrados = [item for item in documentos_eventos if item[1] and "DESPADEC" in item[1]]

    if despachos_eventos_filtrados:
        maior_evento_despacho = max(int(item[2]) for item in despachos_eventos_filtrados)
        documentos_eventos_filtrados = [
            item for item in documentos_eventos_filtrados if int(item[2]) > maior_evento_despacho
        ]

    if not documentos_eventos_filtrados:
        erro = "Nenhuma petição encontrada."
        return erro, None
    
    documentos_eventos_filtrados.sort(key=lambda x: int(x[2]), reverse=True)
    documento_requerido = documentos_eventos_filtrados[0]
    evento_id = documento_requerido[2]

    caminho_pdf = os.path.join(pasta_downloads, f"{num_processo}.pdf")

    elemento = navegador.find_element(By.ID, documento_requerido[0])
    link = elemento.find_element(By.XPATH, ".//*[contains(@class, 'infraLinkDoc')]")

    return _baixar_pdf(navegador, link, caminho_pdf)


def pega_ultimo_documento(navegador, num_processo):
    """
    Localiza o último documento disponível no processo informado,
    captura a requisição real feita pelo navegador (Selenium Wire) para baixar o PDF
    e salva o arquivo localmente.

    Parâmetros:
        navegador     -> instância do Selenium Wire WebDriver já autenticada no eproc.
        num_processo  -> número do processo (será usado no nome do PDF).

    Retorna:
        (evento_id, caminho_pdf) se o download foi bem-sucedido.
        (None, None) caso não haja petição ou falha no download.
    """
    documentos_eventos = []
    eventos = navegador.find_elements(By.CLASS_NAME, "td-evento")

    for evento in eventos:
        doc_id = evento.get_dom_attribute("id")
        tr_element = evento.find_element(By.XPATH, "./ancestor::tr")
        evento_id = tr_element.find_element(By.XPATH, './td[2]').text
        evento_id = ''.join(filter(str.isdigit, evento_id))

        try:
            infra_link = evento.find_element(By.XPATH, ".//*[contains(@class, 'infraLinkDoc')]")
            data_nome = infra_link.get_attribute("data-nome")
        except Exception:
            data_nome = None

        documentos_eventos.append((doc_id, data_nome, evento_id))

    documentos_eventos_filtrados = [item for item in documentos_eventos if item[1]]    
   
    if not documentos_eventos_filtrados:
        erro = "Nenhum documento encontrado."
        return erro, None
    
    documentos_eventos_filtrados.sort(key=lambda x: int(x[2]), reverse=True)
    documento_requerido = documentos_eventos_filtrados[0]
    evento_id = documento_requerido[2]

    caminho_pdf = os.path.join(pasta_downloads, f"{num_processo}.pdf")

    elemento = navegador.find_element(By.ID, documento_requerido[0])
    link = elemento.find_element(By.XPATH, ".//*[contains(@class, 'infraLinkDoc')]")

    return _baixar_pdf(navegador, link, caminho_pdf)


def extrair_texto_pdf(caminho_pdf):
    with open(caminho_pdf, 'rb') as arquivo:
        leitor = PyPDF2.PdfReader(arquivo)
        texto = ""
        for pagina in leitor.pages:
            texto += pagina.extract_text()

        texto = re.sub(r'\n+', ' ', texto)
        texto = re.sub(r'\s+', ' ', texto).strip()

        if len(texto) < 5:
            texto = "Erro: petição em imagem, sem texto copiável"

    return texto

def pega_texto_documento(navegador, documento):
    WebDriverWait(navegador, 20).until(
        EC.presence_of_element_located((By.ID, documento))
    )
    elemento = navegador.find_element(By.ID, documento)
    actions = ActionChains(navegador)
    navegador.execute_script("arguments[0].scrollIntoView(true); window.scrollBy(0, -150);", elemento)
    link_doc = elemento.find_element(By.XPATH, ".//*[contains(@class, 'infraLinkDoc')]")
    actions.move_to_element(link_doc).perform()
    time.sleep(5)
    
    overlays = navegador.find_elements(By.ID, "divBoxPreview")
    visiveis = [div for div in overlays if div.is_displayed()]

    conteudo = ""
    if visiveis:
        div = overlays[0]
        ActionChains(navegador).move_to_element(div).click().perform()
        time.sleep(1)
        conteudo = navegador.find_element(By.ID, "divBoxPreview").text
        btn_close = navegador.find_element(By.ID, "divClosePreview")
        btn_close.click()    
        time.sleep(3)
    else:
        print("Erro ao recuperar o documento")
    return conteudo

def ollama_resumo(pedido):    
    pergunta_gemma = "Considere o seguinte pedido." \
    f"{pedido}" \
    "Resuma, da maneira mais objetiva possível, o pedido. Não mencione dados pessoais, como nomes, números de documento, números de processo, valores, etc. " \
    "O resumo deve ser genérico e breve (uma frase apenas, com o mínimo de palavras possível). " \
    "Se tiver mais de um pedido, retorne uma frase para cada um." \

    resumo = ollama.chat(
        model="cnmoro/gemma3-gaia-ptbr-4b:q8_0",
        messages=[{'role': 'user', 'content': f'{pergunta_gemma}'}],    
    )

    return(resumo['message']['content'])

def verifica_tipos_de_pedidos(pedido, lista_de_pedidos):
    print("========== Verificando se é um caso de uso conhecido... ==========")
    pergunta_gemma = "Considere a seguinte lista de pedidos:" \
    f"{lista_de_pedidos}" \
    f"É possível dizer que o pedido '{pedido}' pode ser adequadamente descrito por um item dessa lista?." \
    "Se sim, retorne APENAS o texto EXATO do resumo do pedido correspondente na lista. Se não, retorne APENAS o texto 'Não'."

    resumo = ollama.chat(
        model="cnmoro/gemma3-gaia-ptbr-4b:q8_0",
        messages=[{'role': 'user', 'content': f'{pergunta_gemma}'}],    
    )

    return(resumo['message']['content'])

def baixa_peticao_processo(navegador, processo):
    navegador.switch_to.default_content()
    eproc.entrar_no_processo(navegador, processo)

    with sqlite3.connect("urcaciv.db") as conn:
        erro, texto_peticao = pega_ultima_peticao(navegador, processo) 
    
    return erro, texto_peticao

def baixa_documento_processo(navegador, processo):
    navegador.switch_to.default_content()
    eproc.entrar_no_processo(navegador, processo)

    with sqlite3.connect("urcaciv.db") as conn:
        erro, texto_peticao = pega_ultimo_documento(navegador, processo) 
    
    return erro, texto_peticao


# ============================================================
# CELL 5: pega_proximo
# ============================================================

def erro_fatal_de_estrutura(erro):
    texto = str(erro)
    return isinstance(erro, NoSuchElementException) or "Unable to locate element" in texto or "no such element" in texto

def pega_proximo():
    try:
        records = sheet.get_all_records()
        num_processo = None

        for record in records:
            if not record.get('Texto da Petição'):
                num_processo = record.get('Número do Processo')                
                break

        if num_processo:
            print("processo: ", num_processo)            
        
        if not num_processo:
            print("Nenhum processo pendente encontrado.")
            return

        erro, texto_peticao = baixa_peticao_processo(navegador, num_processo)

        # Retry até 5 vezes se o conteúdo não for PDF válido
        tentativas_pdf = 1
        while erro and "não é um PDF válido" in str(erro) and tentativas_pdf < 5:
            tentativas_pdf += 1
            print(f"  Tentativa {tentativas_pdf}/5...")
            time.sleep(2)
            erro, texto_peticao = baixa_peticao_processo(navegador, num_processo)

        if erro and "não é um PDF válido" in str(erro) and tentativas_pdf >= 5:
            texto_peticao = "Erro: petição em imagem, sem texto copiável"
            cell = sheet.find(num_processo)
            if cell:
                sheet.update_cell(cell.row, 7, texto_peticao)
                print(f"5 tentativas falharam para o processo {num_processo}, marcado como imagem.")
        elif erro:
            print("Erro ao baixar petição:", erro)
            if erro == "Nenhuma petição encontrada.":
                texto_peticao = "Alerta: não há documento do tipo PET sem despacho posterior."
            
            cell = sheet.find(num_processo)
            if cell:
                sheet.update_cell(cell.row, 7, texto_peticao)
                print(f"Erro gravado na planilha para o processo {num_processo}")
        else:
            texto_extraido = extrair_texto_pdf(texto_peticao)

            texto_extraido = ' '.join(texto_extraido.split())

            # Limita a 50000 caracteres
            texto_extraido = texto_extraido[:50000]

            # Remove caracteres iniciais que o Google Sheets interpreta como fórmula
            texto_extraido = texto_extraido.lstrip('=-+@')

            cell = sheet.find(num_processo)
            if cell:
                sheet.update_cell(cell.row, 7, texto_extraido)
                print(f"Texto da petição gravado na planilha para o processo {num_processo}")
        return True
    
    except Exception as e:
        print(f"Erro na função pega_proximo: {e}")
        if 'num_processo' in locals() and num_processo:
            try:
                cell = sheet.find(num_processo)
                if cell:
                    sheet.update_cell(cell.row, 7, f"Erro: {str(e)}")
            except Exception as inner_e:
                print(f"Erro ao gravar erro na planilha: {inner_e}")
        if erro_fatal_de_estrutura(e):
            print("Erro estrutural detectado; interrompendo para não persistir na falha.")
            return False
        return True


# ============================================================
# CELL 6: Apaga os ERROS da planilha
# ============================================================

all_values = sheet.get_all_values()

linhas_para_limpar = []
for i, row in enumerate(all_values):
    if row[6].startswith("Erro"):  # Coluna G (índice 6)
        linhas_para_limpar.append(i + 1)  # +1 porque as linhas começam em 1

if linhas_para_limpar:
    for linha in linhas_para_limpar:
        sheet.update(f'F{linha}:G{linha}', [['', '']])
    print(f"Limpas {len(linhas_para_limpar)} linhas onde a coluna G continha 'Erro'")
else:
    print("Nenhuma linha encontrada com 'Erro' na coluna G")


# ============================================================
# CELL 7: Loop principal com cleanup
# ============================================================

records = sheet.get_all_records()
total_pendentes = sum(1 for record in records if not record.get('Texto da Petição'))

print(f"Total de registros a processar: {total_pendentes}")

contador = 0

try:
    while True:
        records = sheet.get_all_records()
        pendentes = sum(1 for record in records if not record.get('Texto da Petição'))
        if pendentes == 0:
            print("Nenhum registro pendente. Encerrando.")
            break

        try:
            continuar = pega_proximo()
            if continuar is False:
                break
            contador += 1
        except Exception as e:
            print(f"Erro no processamento do registro: {e}")
            break

except Exception as e:
    print(f"Erro fatal que impede o prosseguimento: {e}")

finally:
    print(f"\nTotal de registros processados: {contador}")
    if perfil:
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "UPDATE Comarcas SET data_peticoes = ? WHERE nome = ?",
                (datetime.now().isoformat(), perfil)
            )
            conn.commit()
        print(f"Campo 'data_peticoes' de '{perfil}' atualizado.")
    try:
        navegador.quit()
        print("Navegador fechado.")
    except Exception:
        pass
    gc.collect()
    print("Memória liberada.")
