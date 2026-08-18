#!/usr/bin/env python3
# 01-monitora.py — Condensação do notebook Unica-01-Gera-Tabela.ipynb

import argparse

parser = argparse.ArgumentParser(description="Monitora comarcas no eproc")
parser.add_argument("--headless", action="store_true", help="Rodar em modo headless (sem interface gráfica)")
parser.add_argument("--comarca", type=str, help="Nome da comarca a processar")
args = parser.parse_args()

# === Importações ===

from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException
from selenium.common.exceptions import ElementClickInterceptedException
from selenium.common.exceptions import TimeoutException

from datetime import datetime
import platform
import time
import re
import os
import glob
from eproc_driver import eproc as eproc
import sqlite3
import PyPDF2
import traceback
import sys

from dotenv import load_dotenv

import gspread
from oauth2client.service_account import ServiceAccountCredentials

# === Setup ===

if platform.system() == "Windows":
    pasta_downloads = r"D:\Douglas\Downloads"
else:
    pasta_downloads = os.path.expanduser("~/Downloads")

debug = False

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
comarca_solicitada = args.comarca.strip() if args.comarca else None


# === Sincroniza comarcas da planilha Google com o SQLite ===

db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "DB", "unica.db")

with sqlite3.connect(db_path) as conn:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS Comarcas (
            nome TEXT PRIMARY KEY,
            spreadsheet_id TEXT,
            data_inclusao TEXT,
            data_ultimo_processamento TEXT
        )
    """)

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

with sqlite3.connect(db_path) as conn:
    cursor = conn.cursor()
    existentes = {row[0] for row in cursor.execute("SELECT nome FROM Comarcas").fetchall()}
    agora = datetime.now().isoformat()

    inseridos = 0
    atualizados = 0
    removidos = 0

    for nome, sheet_id in comarcas_planilha:
        if nome not in existentes:
            cursor.execute(
                "INSERT INTO Comarcas (nome, spreadsheet_id, data_inclusao, data_ultimo_processamento) VALUES (?, ?, ?, NULL)",
                (nome, sheet_id, agora)
            )
            inseridos += 1
        else:
            cursor.execute("UPDATE Comarcas SET spreadsheet_id = ? WHERE nome = ?", (sheet_id, nome))
            atualizados += 1

    para_remover = existentes - nomes_planilha
    if para_remover:
        cursor.executemany("DELETE FROM Comarcas WHERE nome = ?", [(n,) for n in para_remover])
        removidos = len(para_remover)

    conn.commit()

print(f"Comarcas sincronizadas: {inseridos} inseridas, {atualizados} atualizadas, {removidos} removidas (total na planilha: {len(comarcas_planilha)})")


# === Define funções ===

def pega_tabela_pagina(dados_tabela):
    tabela = navegador.find_element(By.ID, "tabelaLocalizadores")
    linhas = tabela.find_elements(By.TAG_NAME, "tr")[1:]
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

def pega_ultima_peticao(navegador, num_processo):
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

    documentos_eventos_filtrados = [item for item in documentos_eventos if item[1] == "PET"]

    if not documentos_eventos_filtrados:
        print("❌ Nenhuma petição encontrada.")
        return None, None

    documentos_eventos_filtrados.sort(key=lambda x: int(x[2]), reverse=True)
    documento_requerido = documentos_eventos_filtrados[0]
    evento_id = documento_requerido[2]

    caminho_pdf = os.path.join(pasta_downloads, f"{num_processo}.pdf")

    elemento = navegador.find_element(By.ID, documento_requerido[0])
    link = elemento.find_element(By.XPATH, ".//*[contains(@class, 'infraLinkDoc')]")

    if hasattr(navegador, "requests"):
        navegador.requests.clear()
    link.click()

    WebDriverWait(navegador, 10).until(
        EC.presence_of_element_located((By.ID, "divBoxPreview"))
    )
    time.sleep(2)

    if len(navegador.window_handles) > 1:
        navegador.switch_to.window(navegador.window_handles[-1])
    try:
        timestamp_download = datetime.now().isoformat()
        navegador.find_element(By.TAG_NAME, 'body').send_keys('\t\t\n')
        time.sleep(1)
    except Exception as e:
        print("Botão 'open-button' não encontrado ou erro ao clicar:", e)

    if len(navegador.window_handles) > 1:
        while len(navegador.window_handles) > 1:
            navegador.switch_to.window(navegador.window_handles[-1])
            navegador.close()
        navegador.switch_to.window(navegador.window_handles[0])

    arquivos_pdf = glob.glob(os.path.join(pasta_downloads, "*.pdf"))
    if not arquivos_pdf:
        print("❌ Nenhum PDF encontrado na pasta de downloads.")
        return evento_id, None

    pdf_mais_recente = max(arquivos_pdf, key=os.path.getmtime)
    tempo_modificacao = os.path.getmtime(pdf_mais_recente)
    tempo_modificacao_dt = datetime.fromtimestamp(tempo_modificacao)
    tempo_diff = abs((tempo_modificacao_dt - datetime.fromisoformat(timestamp_download)).total_seconds())

    if tempo_diff <= 10:
        os.makedirs(os.path.dirname(caminho_pdf), exist_ok=True)
        os.replace(pdf_mais_recente, caminho_pdf)
        print(f"PDF renomeado e salvo em: {caminho_pdf}")
        return evento_id, caminho_pdf
    else:
        print(f"PDF mais recente tem diferença de {tempo_diff:.2f} segundos da timestamp. Não será renomeado.")
        return evento_id, None

def extrair_texto_pdf(caminho_pdf):
    with open(caminho_pdf, 'rb') as arquivo:
        leitor = PyPDF2.PdfReader(arquivo)
        texto = ""
        for pagina in leitor.pages:
            texto += pagina.extract_text()
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


# === Pega a comarca há mais tempo sem processar e entra no perfil ===

limite_horas = 2

with sqlite3.connect(db_path) as conn:
    cursor = conn.cursor()
    cursor.execute("""
        SELECT nome, spreadsheet_id, data_ultimo_processamento FROM Comarcas
        ORDER BY
            CASE WHEN data_ultimo_processamento IS NULL THEN 0 ELSE 1 END,
            data_ultimo_processamento ASC
    """)
    todas_comarcas = cursor.fetchall()

if not todas_comarcas:
    raise RuntimeError("Nenhuma comarca encontrada no banco de dados.")

agora = datetime.now()
perfil = None
comarca_spreadsheet_id = None

if comarca_solicitada:
    for nome, sid, _ in todas_comarcas:
        if nome.lower() == comarca_solicitada.lower():
            perfil = nome
            comarca_spreadsheet_id = sid
            break

    if perfil is None:
        raise RuntimeError(f"Comarca solicitada não encontrada no banco de dados: {comarca_solicitada}")
else:
    for nome, sid, data_proc in todas_comarcas:
        if data_proc:
            try:
                ultima = datetime.fromisoformat(data_proc)
                diff_horas = (agora - ultima).total_seconds() / 3600
                if diff_horas < limite_horas:
                    print(f"  {nome}: atualizada há {diff_horas:.1f}h (< {limite_horas}h), pulando.")
                    continue
            except ValueError:
                pass
        perfil = nome
        comarca_spreadsheet_id = sid
        break

    if perfil is None:
        print(f"\nTodas as comarcas foram atualizadas há menos de {limite_horas} horas. Encerrando.")
        exit(0)

print(f"Comarca selecionada: {perfil} (spreadsheet_id: {comarca_spreadsheet_id})")

# Inicia o navegador, loga no perfil escolhido

if debug:
    print(f"[DEBUG] pasta_downloads: {pasta_downloads}")

navegador = eproc.novo_browser(pasta_downloads, headless=args.headless)

if debug:
    print("[DEBUG] Navegador iniciado.")

username = os.getenv("EPROC_USERNAME")
password = os.getenv("EPROC_PASSWORD")
pyotop_code = os.getenv("EPROC_PYOTP_CODE")

# Tentar login — se houver falha de conexão com o chromedriver, recria o navegador e tenta novamente uma vez.
try:
    eproc.login_no_eproc(navegador, username, password, pyotop_code)
except Exception as e:
    print(f"Aviso: falha no login inicial: {e}. Tentando recriar o navegador e reconectar.")
    try:
        navegador.quit()
    except Exception:
        pass
    time.sleep(2)
    navegador = eproc.novo_browser(pasta_downloads, headless=args.headless)
    eproc.login_no_eproc(navegador, username, password, pyotop_code)

if debug:
    print("[DEBUG] Login realizado.")

eproc.entrar_no_perfil(navegador, perfil)

if debug:
    print(f"[DEBUG] Entrou no perfil: {perfil}")


# === Navega, extrai dados, espelha no DB, sincroniza planilha Google, atualiza timestamp ===

# --- Parte 1: Navegação até MINUTAR ---

meus_localizadores = WebDriverWait(navegador, 20).until(
    EC.element_to_be_clickable((By.CSS_SELECTOR, 'i[title="Meus Localizadores"]'))
)
meus_localizadores.click()

# Procurar a célula que contenha o texto "MINUTAR" (case-insensitive) — aumenta o
# timeout e captura screenshot/page source em caso de Timeout para ajudar no debug.
try:
    td_civel_minutar = WebDriverWait(navegador, 30).until(
        EC.presence_of_element_located((By.XPATH,
            "//td[contains(translate(text(), 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'), 'MINUTAR')]")
    ))
except TimeoutException:
    try:
        navegador.save_screenshot('/tmp/01-monitora_timeout_minutar.png')
    except Exception:
        pass
    try:
        with open('/tmp/01-monitora_page_source.html', 'w', encoding='utf-8') as fh:
            fh.write(navegador.page_source)
    except Exception:
        pass
    print("Aviso: 'MINUTAR' não encontrado para esta comarca. Marcando como monitorado e encerrando execução para essa comarca.")
    # Marcar como monitorado (atualiza data_ultimo_processamento) mesmo sem processar
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "UPDATE Comarcas SET data_ultimo_processamento = ? WHERE nome = ?",
                (datetime.now().isoformat(), perfil)
            )
            conn.commit()
        print(f"Campo 'data_ultimo_processamento' de '{perfil}' atualizado (marca como monitorado).")
    except Exception as e:
        print(f"Erro ao atualizar data_ultimo_processamento para marcar como monitorado: {type(e).__name__}: {e}")
    try:
        navegador.quit()
    except Exception:
        pass
    sys.exit(0)

td_seguinte = td_civel_minutar.find_element(By.XPATH, 'following-sibling::td[1]')

a_element = WebDriverWait(td_seguinte, 20).until(
    EC.element_to_be_clickable((By.TAG_NAME, 'a'))
)
a_element.click()

label_100 = WebDriverWait(navegador, 20).until(
    EC.element_to_be_clickable((By.XPATH, '//label[contains(text(), "100 processos por página")]'))
)
label_100.click()

label_ndias_situacao = WebDriverWait(navegador, 20).until(
    EC.element_to_be_clickable((By.ID, "lbloptNdiasSituacao"))
)
checkbox_ndias = navegador.find_element(By.ID, "optNdiasSituacao")
if not checkbox_ndias.is_selected():
    label_ndias_situacao.click()

botao_consultar = navegador.find_element(By.ID, "btnConsultar")
navegador.execute_script("arguments[0].scrollIntoView();", botao_consultar)

try:
    botao_consultar.click()
except ElementClickInterceptedException:
    navegador.execute_script("arguments[0].scrollIntoView({block: 'center'});", botao_consultar)
    time.sleep(1)
    botao_consultar.click()

# --- Parte 2: Cria tabelas temp e temp_atp ---

with sqlite3.connect(db_path) as conn:
    conn.execute("DROP TABLE IF EXISTS temp")
    conn.execute("DROP TABLE IF EXISTS temp_atp")
    for tabela_nome in ("temp", "temp_atp"):
        conn.execute(f"""
            CREATE TABLE {tabela_nome} (
                perfil TEXT,
                numero_processo TEXT,
                classe TEXT,
                dias TEXT,
                col_e TEXT,
                col_f TEXT,
                col_g TEXT,
                inclusao TEXT,
                flag TEXT
            )
        """)
    conn.commit()

print("Tabelas 'temp' e 'temp_atp' criadas com sucesso.")

# --- Parte 3: Extrai dados de todas as páginas e identifica ATP ---

processos_planilha_comarca = set()
try:
    planilha_comarca_atual = client.open_by_key(comarca_spreadsheet_id)
    aba_comarca_atual = planilha_comarca_atual.sheet1
    valores_planilha_atual = aba_comarca_atual.col_values(2)
    processos_planilha_comarca = {
        valor.strip()
        for valor in valores_planilha_atual[1:]
        if valor and valor.strip()
    }
    print(f"Processos atuais na planilha da comarca '{perfil}': {len(processos_planilha_comarca)}")
except Exception as e:
    print(f"Erro ao ler processos da planilha da comarca '{perfil}': {type(e).__name__}: {e}")
    print("Seguindo sem atalho de processos da planilha nesta execução.")

pagina = 1
total_inseridos = 0
total_atp = 0
processamento_ok = True

try:
    while True:
        print(f"Processando página {pagina}...")

        WebDriverWait(navegador, 20).until(
            EC.presence_of_element_located((By.ID, "tabelaLocalizadores"))
        )
        time.sleep(2)

        tabela_el = navegador.find_element(By.ID, "tabelaLocalizadores")
        linhas = tabela_el.find_elements(By.TAG_NAME, "tr")[1:]

        registros_temp = []
        registros_atp = []

        for linha in linhas:
            colunas = linha.find_elements(By.TAG_NAME, "td")
            if len(colunas) < 4:
                continue

            col_processo = colunas[1]
            numero_processo = col_processo.text.split('\n')[0].strip()
            classe = colunas[2].text.split('\n')[0]
            tipo = colunas[3].text.split('\n')[0]
            dias = colunas[-1].text.split('\n')[0]

            registro = [perfil, numero_processo, tipo, classe, "", "", "", dias, "0"]

            if numero_processo in processos_planilha_comarca:
                registros_temp.append(registro)
                continue

            eh_atp = False
            icones = col_processo.find_elements(By.XPATH, ".//i | .//img | .//span[contains(@class, 'fa')] | .//span[contains(@class, 'icon')]")

            for icone in icones:
                try:
                    title = icone.get_attribute("title") or ""
                    data_title = icone.get_attribute("data-original-title") or ""
                    data_content = icone.get_attribute("data-content") or ""
                    texto_attrs = f"{title} {data_title} {data_content}"

                    if "REGRA DE AUTOMATIZAÇÃO" in texto_attrs.upper() or "UNICA RESUMOS" in texto_attrs.upper():
                        eh_atp = True
                        break

                    if icone.is_displayed():
                        navegador.execute_script("arguments[0].scrollIntoView({block: 'center'});", icone)
                        ActionChains(navegador).move_to_element(icone).perform()
                        time.sleep(0.5)

                        tooltips = navegador.find_elements(By.CSS_SELECTOR,
                            ".tooltip-inner, .popover-body, .popover-content, .infraTooltip, [role='tooltip']")
                        for tip in tooltips:
                            try:
                                if tip.is_displayed() and ("REGRA DE AUTOMATIZAÇÃO" in tip.text.upper() or "UNICA RESUMOS" in tip.text.upper()):
                                    eh_atp = True
                                    break
                            except Exception:
                                continue

                        ActionChains(navegador).move_to_element(tabela_el).perform()
                        time.sleep(0.2)

                    if eh_atp:
                        break
                except Exception:
                    continue

            if eh_atp:
                registros_atp.append(registro)
            else:
                registros_temp.append(registro)

        with sqlite3.connect(db_path) as conn:
            if registros_temp:
                conn.executemany(
                    "INSERT INTO temp (perfil, numero_processo, classe, dias, col_e, col_f, col_g, inclusao, flag) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    registros_temp
                )
            if registros_atp:
                conn.executemany(
                    "INSERT INTO temp_atp (perfil, numero_processo, classe, dias, col_e, col_f, col_g, inclusao, flag) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    registros_atp
                )
            conn.commit()

        total_inseridos += len(registros_temp)
        total_atp += len(registros_atp)
        print(f"  Página {pagina}: {len(registros_temp)} em temp, {len(registros_atp)} em temp_atp")

        # Se menos de 100 registros na página, é a última
        total_pagina = len(registros_temp) + len(registros_atp)
        if total_pagina < 100:
            print(f"Página {pagina} com {total_pagina} registros (< 100). Última página.")
            break

        proxima_encontrada = False
        seletores = [
            (By.ID, "lnkInfraProximaPaginacao"),
            (By.ID, "lnkInfraProximaPagina"),
            (By.ID, "sbmProximaPagina"),
            (By.ID, "btnProximaPagina"),
            (By.XPATH, "//a[contains(@title, 'Próxima')]"),
            (By.XPATH, "//a[contains(@title, 'próxima')]"),
            (By.XPATH, "//a[contains(text(), '»')]"),
            (By.XPATH, "//a[contains(text(), 'Próxima')]"),
            (By.XPATH, "//input[contains(@title, 'Próxima')]"),
            (By.CSS_SELECTOR, "a.infraBotaoProximaPagina"),
            (By.CSS_SELECTOR, ".infraPaginaSeguinte a"),
            (By.CSS_SELECTOR, "a[onclick*='proxima']"),
            (By.CSS_SELECTOR, "a[onclick*='Proxima']"),
        ]

        max_tentativas = 10
        for by, valor in seletores:
            try:
                botao_proxima = navegador.find_element(by, valor)
                if botao_proxima.is_displayed():
                    navegador.execute_script("arguments[0].scrollIntoView({block: 'center'});", botao_proxima)
                    time.sleep(0.5)
                    clicou = False
                    for tentativa in range(max_tentativas):
                        try:
                            botao_proxima.click()
                            clicou = True
                            break
                        except ElementClickInterceptedException:
                            print(f"  Clique interceptado (tentativa {tentativa + 1}/{max_tentativas}). Aguardando 60s...")
                            time.sleep(60)
                            navegador.execute_script("arguments[0].scrollIntoView({block: 'center'});", botao_proxima)
                            time.sleep(1)
                    if clicou:
                        time.sleep(2)
                        pagina += 1
                        proxima_encontrada = True
                        if pagina == 2:
                            print(f"  (Botão de paginação encontrado via: {by}='{valor}')")
                        break
            except NoSuchElementException:
                continue

        if not proxima_encontrada:
            print(f"Todas as {pagina} páginas processadas com sucesso.")
            break

except Exception as e:
    print(f"Erro na página {pagina}: {type(e).__name__}: {e}")
    print(f"Dados coletados até o momento foram salvos. Planilha NÃO será atualizada.")
    processamento_ok = False

print(f"\nTotal: {total_inseridos} registros em 'temp', {total_atp} registros em 'temp_atp'.")

# --- Parte 4 em diante: só executa se processamento_ok ---

if not processamento_ok:
    print("Processamento interrompido por erro. Planilha e timestamp NÃO serão atualizados.")
else:
        sync_principal_ok = False
        subetapa = "inicio_partes_4_6"

        try:
            # --- Parte 4: Cria tabela da comarca e espelha temp nela ---
            subetapa = "parte_4_cria_tabela_comarca"

            with sqlite3.connect(db_path) as conn:
                conn.execute(f"""
                    CREATE TABLE IF NOT EXISTS [{perfil}] (
                        perfil TEXT,
                        numero_processo TEXT,
                        classe TEXT,
                        dias TEXT,
                        col_e TEXT,
                        col_f TEXT,
                        col_g TEXT,
                        inclusao TEXT,
                        flag TEXT
                    )
                """)

                conn.execute(f"DELETE FROM [{perfil}]")
                conn.execute(f"INSERT INTO [{perfil}] SELECT * FROM temp")
                conn.commit()

                total = conn.execute(f"SELECT COUNT(*) FROM [{perfil}]").fetchone()[0]

            print(f"Tabela '[{perfil}]' criada/atualizada com {total} registros espelhados de 'temp'.")

            # --- Parte 5: Compara DB da comarca com planilha Google → temp_ins e temp_del ---
            subetapa = "parte_5_abre_planilha_comarca"

            planilha_comarca = client.open_by_key(comarca_spreadsheet_id)
            aba = planilha_comarca.sheet1

            subetapa = "parte_5_le_coluna_b_planilha"
            valores_planilha = aba.col_values(2)
            processos_planilha = set()
            for v in valores_planilha[1:]:
                v_strip = v.strip()
                if v_strip:
                    processos_planilha.add(v_strip)

            subetapa = "parte_5_le_db_comarca"
            with sqlite3.connect(db_path) as conn:
                rows_db = conn.execute(f"SELECT * FROM [{perfil}]").fetchall()

            processos_db = {row[1].strip() for row in rows_db}

            with sqlite3.connect(db_path) as conn:
                conn.execute("DROP TABLE IF EXISTS temp_ins")
                conn.execute("DROP TABLE IF EXISTS temp_del")

                conn.execute("""
                    CREATE TABLE temp_ins (
                        perfil TEXT, numero_processo TEXT, classe TEXT, dias TEXT,
                        col_e TEXT, col_f TEXT, col_g TEXT, inclusao TEXT, flag TEXT
                    )
                """)
                conn.execute("CREATE TABLE temp_del (numero_processo TEXT)")

                inserir = [row for row in rows_db if row[1].strip() not in processos_planilha]
                if inserir:
                    conn.executemany("INSERT INTO temp_ins VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", inserir)

                deletar = [p for p in processos_planilha if p not in processos_db]
                if deletar:
                    conn.executemany("INSERT INTO temp_del (numero_processo) VALUES (?)", [(p,) for p in deletar])

                conn.commit()
                total_ins = conn.execute("SELECT COUNT(*) FROM temp_ins").fetchone()[0]
                total_del = conn.execute("SELECT COUNT(*) FROM temp_del").fetchone()[0]

            print(f"Planilha Google: {len(processos_planilha)} processos. DB [{perfil}]: {len(processos_db)} processos.")
            print(f"temp_ins: {total_ins} | temp_del: {total_del}")

            # --- Parte 6: Executa deletes e inserts na planilha Google ---

            while True:
                subetapa = "parte_6_calcula_pendencias"
                with sqlite3.connect(db_path) as conn:
                    pendentes_del = conn.execute("SELECT COUNT(*) FROM temp_del").fetchone()[0]
                    pendentes_ins = conn.execute("SELECT COUNT(*) FROM temp_ins").fetchone()[0]

                if pendentes_del == 0 and pendentes_ins == 0:
                    print("temp_del e temp_ins zeradas. Sincronização concluída.")
                    break

                if pendentes_del > 0:
                    try:
                        subetapa = "parte_6_delete_le_temp_del"
                        with sqlite3.connect(db_path) as conn:
                            processos_del = {row[0] for row in conn.execute("SELECT numero_processo FROM temp_del").fetchall()}

                        subetapa = "parte_6_delete_le_planilha"
                        todas_linhas = aba.get_all_values()

                        indices_deletar = []
                        for i, row in enumerate(todas_linhas):
                            if i == 0:
                                continue
                            if len(row) > 1 and row[1].strip() in processos_del:
                                indices_deletar.append(i)

                        if indices_deletar:
                            indices_deletar.sort(reverse=True)
                            requests_delete = [{
                                'deleteDimension': {
                                    'range': {
                                        'sheetId': aba.id,
                                        'dimension': 'ROWS',
                                        'startIndex': idx,
                                        'endIndex': idx + 1
                                    }
                                }
                            } for idx in indices_deletar]

                            subetapa = "parte_6_delete_batch_update"
                            aba.spreadsheet.batch_update({'requests': requests_delete})

                            deletados = {todas_linhas[idx][1].strip() for idx in indices_deletar}
                            with sqlite3.connect(db_path) as conn:
                                conn.executemany("DELETE FROM temp_del WHERE numero_processo = ?", [(p,) for p in deletados])
                                conn.commit()

                            print(f"Deletadas {len(indices_deletar)} linhas da planilha.")
                        else:
                            with sqlite3.connect(db_path) as conn:
                                conn.execute("DELETE FROM temp_del")
                                conn.commit()
                            print("Processos de temp_del não encontrados na planilha. Tabela limpa.")

                    except Exception as e:
                        print(f"Erro ao deletar ({subetapa}): {type(e).__name__}: {e}. Tentando novamente em 10s...")
                        time.sleep(10)
                    continue

                if pendentes_ins > 0:
                    try:
                        subetapa = "parte_6_insert_le_temp_ins"
                        with sqlite3.connect(db_path) as conn:
                            registros = conn.execute("SELECT * FROM temp_ins").fetchall()

                        dados = [list(r) for r in registros]
                        subetapa = "parte_6_insert_append_rows"
                        aba.append_rows(dados, value_input_option='RAW')

                        with sqlite3.connect(db_path) as conn:
                            conn.execute("DELETE FROM temp_ins")
                            conn.commit()

                        print(f"Inseridas {len(dados)} linhas na planilha.")

                    except Exception as e:
                        print(f"Erro ao inserir ({subetapa}): {type(e).__name__}: {e}. Tentando novamente em 10s...")
                        time.sleep(10)
                    continue

            sync_principal_ok = True

        except Exception as e:
            print(f"Erro nas partes 4-6 ({subetapa}): {type(e).__name__}: {e}")
            print("Traceback resumido:")
            print(traceback.format_exc(limit=2))
            print("Planilha NÃO foi atualizada e comarca NÃO foi marcada como processada.")

        if sync_principal_ok:
            # --- Limpeza de linhas em branco ---
            try:
                subetapa = "parte_6b_limpeza_linhas_brancas_leitura"
                todas_linhas = aba.get_all_values()
                linhas_brancas = []
                for i, row in enumerate(todas_linhas):
                    if i == 0:
                        continue
                    if all(cell.strip() == "" for cell in row):
                        linhas_brancas.append(i)

                if linhas_brancas:
                    linhas_brancas.sort(reverse=True)
                    requests_limpar = [{
                        'deleteDimension': {
                            'range': {
                                'sheetId': aba.id,
                                'dimension': 'ROWS',
                                'startIndex': idx,
                                'endIndex': idx + 1
                            }
                        }
                    } for idx in linhas_brancas]
                    subetapa = "parte_6b_limpeza_linhas_brancas_batch_update"
                    aba.spreadsheet.batch_update({'requests': requests_limpar})
                    print(f"Removidas {len(linhas_brancas)} linhas em branco da planilha.")
                else:
                    print("Nenhuma linha em branco encontrada.")
            except Exception as e:
                print(f"Erro ao limpar linhas em branco ({subetapa}): {type(e).__name__}: {e}")

            # --- Parte 7: Atualiza data_ultimo_processamento ---

            try:
                subetapa = "parte_7_update_data_ultimo_processamento"
                with sqlite3.connect(db_path) as conn:
                    conn.execute(
                        "UPDATE Comarcas SET data_ultimo_processamento = ? WHERE nome = ?",
                        (datetime.now().isoformat(), perfil)
                    )
                    conn.commit()

                print(f"Campo 'data_ultimo_processamento' de '{perfil}' atualizado.")
            except Exception as e:
                print(f"Erro ao atualizar data_ultimo_processamento ({subetapa}): {type(e).__name__}: {e}")

# === Encerramento: fecha o browser e libera memória ===
try:
    navegador.quit()
    print("Navegador encerrado com sucesso.")
except Exception:
    pass

import gc
gc.collect()
print("Memória liberada.")
