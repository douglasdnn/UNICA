#!/usr/bin/env python3
# 03-lembretes.py - Consolidado do notebook Unica-04-Insere-Lembretes.ipynb

import argparse

parser = argparse.ArgumentParser(description="Insere lembretes no eproc")
parser.add_argument("--headless", action="store_true", help="Rodar em modo headless (sem interface gráfica)")
parser.add_argument("--debug", action="store_true", help="Imprimir mensagens de debug")
parser.add_argument("--validade", type=int, default=20, help="Validade dos lembretes em dias (padrão: 20)")
parser.add_argument("--comarca", type=str, help="Nome da comarca a processar (obrigatorio)")
args = parser.parse_args()

# ============================================================
# CELL 1: Importações, setup, login no eproc
# ============================================================

from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from datetime import datetime, timedelta
import platform
import time
import os
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from eproc_driver import eproc as eproc
import sqlite3
import gc

from dotenv import load_dotenv

import gspread
from oauth2client.service_account import ServiceAccountCredentials

debug = args.debug
validade = args.validade
comarca_solicitada = args.comarca.strip() if args.comarca else None

if platform.system() == "Windows":
    pasta_downloads = r"D:\Douglas\Downloads"
else:
    pasta_downloads = os.path.expanduser("~/Downloads/Processos")

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

db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "DB", "unica.db")

# ============================================================
# CELL 2: Garante schema e sincroniza lembretes de TODAS as comarcas
# ============================================================

# Garante que a coluna data_lembretes existe na tabela Comarcas
with sqlite3.connect(db_path) as conn:
    colunas = [row[1] for row in conn.execute("PRAGMA table_info(Comarcas)").fetchall()]
    if "data_lembretes" not in colunas:
        conn.execute("ALTER TABLE Comarcas ADD COLUMN data_lembretes TEXT")
        conn.commit()
        print("Coluna 'data_lembretes' adicionada à tabela Comarcas.")

# Garante que a tabela lembretes existe
with sqlite3.connect(db_path) as conn:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS lembretes (
            unidade TEXT,
            processo TEXT,
            tipo TEXT,
            resumo TEXT,
            data_lembrete TEXT DEFAULT NULL
        )
    """)
    conn.commit()

# Garante que a coluna resumo existe na tabela lembretes
with sqlite3.connect(db_path) as conn:
    colunas_lembretes = [row[1] for row in conn.execute("PRAGMA table_info(lembretes)").fetchall()]
    if "resumo" not in colunas_lembretes:
        conn.execute("ALTER TABLE lembretes ADD COLUMN resumo TEXT")
        conn.commit()
        print("Coluna 'resumo' adicionada à tabela lembretes.")

# ============================================================
# CELL 3: Seleciona a comarca chamada por parâmetro
# ============================================================

with sqlite3.connect(db_path) as conn:
    cursor = conn.cursor()
    if not comarca_solicitada:
        print("Parametro obrigatorio ausente: --comarca")
        exit(1)

    cursor.execute(
        """
        SELECT nome, spreadsheet_id FROM Comarcas
        WHERE nome = ? COLLATE NOCASE
          AND spreadsheet_id IS NOT NULL AND spreadsheet_id != ''
        LIMIT 1
        """,
        (comarca_solicitada,)
    )
    resultado = cursor.fetchone()

if resultado is None:
    print(f"Comarca solicitada não encontrada no banco de dados: {comarca_solicitada}")
    exit(0)

perfil, comarca_spreadsheet_id = resultado
print(f"\nComarca solicitada por parâmetro: {perfil}")

# ============================================================
# CELL 3.1: Lê lembretes da comarca chamada (em memória)
# ============================================================

try:
    planilha_comarca = client.open_by_key(comarca_spreadsheet_id)
    sheet_comarca = planilha_comarca.worksheet(perfil)
    all_rows = sheet_comarca.get_all_values()

    lembretes_planilha = []
    for row in all_rows[1:]:
        if len(row) <= 4:
            continue

        tipo = (row[4] or "").strip()
        if len(tipo) <= 1:
            continue

        unidade = (row[0] or "").strip() if len(row) > 0 else ""
        processo = (row[1] or "").strip() if len(row) > 1 else ""
        resumo = (row[5] or "").strip() if len(row) > 5 else ""

        if not unidade:
            unidade = perfil
        if not processo:
            continue

        lembretes_planilha.append((unidade, processo, tipo, resumo))

    print(f"Registros candidatos da comarca '{perfil}' na planilha: {len(lembretes_planilha)}")
except Exception as e:
    print(f"Erro ao ler lembretes da comarca '{perfil}': {type(e).__name__}: {e}")
    exit(1)

# Verifica se há lembretes na planilha para essa comarca
if not lembretes_planilha:
    # Atualiza data_lembretes mesmo sem pendentes
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE Comarcas SET data_lembretes = ? WHERE nome = ?",
            (datetime.now().isoformat(), perfil)
        )
        conn.commit()
    print(f"Nenhum lembrete a processar para '{perfil}'. data_lembretes atualizada. Encerrando.")
    exit(0)

print(f"Lembretes a processar para '{perfil}': {len(lembretes_planilha)}")

# Inicia o navegador e loga no eproc
navegador = eproc.novo_browser(pasta_downloads, headless=args.headless)

if debug:
    print("[DEBUG] Navegador iniciado.")

username = os.getenv("EPROC_USERNAME")
password = os.getenv("EPROC_PASSWORD")
pyotop_code = os.getenv("EPROC_PYOTP_CODE")

eproc.login_no_eproc(navegador, username, password, pyotop_code)

if debug:
    print("[DEBUG] Login realizado.")

eproc.entrar_no_perfil(navegador, perfil)
print(f"Entrou no perfil: {perfil}")


# ============================================================
# CELL 4: Insere os lembretes no eproc
# ============================================================

def insere_lembrete(navegador, texto, validade_dias):
    data_atual = datetime.now().strftime("%d/%m/%Y")
    data_atual = data_atual + " 00:00"
    data_fim = (datetime.now() + timedelta(days=validade_dias)).strftime("%d/%m/%Y")
    data_fim = data_fim + " 00:00"

    navegador.switch_to.default_content()
    novo_btn = navegador.find_element(By.LINK_TEXT, "Novo")

    time.sleep(0.5)
    novo_btn.click()

    WebDriverWait(navegador, 10).until(
        EC.frame_to_be_available_and_switch_to_it(1)
    )

    WebDriverWait(navegador, 20).until(
        EC.presence_of_element_located((By.ID, "txaDescricao"))
    )
    navegador.find_element(By.ID, "txaDescricao").click()
    navegador.find_element(By.ID, "txaDescricao").send_keys(texto)
    navegador.find_element(By.CSS_SELECTOR, "td:nth-child(2) > .infraRadio").click()

    campo_validade = navegador.find_element(By.ID, "chkInformaValidade")
    navegador.execute_script("arguments[0].scrollIntoView(true); window.scrollBy(0, -150);", campo_validade)
    campo_validade.click()

    navegador.find_element(By.ID, "txtDataInicio").clear()
    navegador.find_element(By.ID, "txtDataInicio").send_keys(data_atual)

    navegador.find_element(By.ID, "txtDataTermino").clear()
    navegador.find_element(By.ID, "txtDataTermino").send_keys(data_fim)

    btn_salvar = navegador.find_element(By.CSS_SELECTOR, "#divInfraBarraComandosInferior > #sbmSalvar")
    navegador.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn_salvar)
    time.sleep(0.5)
    btn_salvar.click()
    navegador.switch_to.default_content()
    time.sleep(2)


contador = 0
ja_processados = 0

try:
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        total_planejados = len(lembretes_planilha)
        print(f"Total de lembretes planejados: {total_planejados}")

        for i, lembrete in enumerate(lembretes_planilha, 1):
            unidade, processo, tipo_pedido, resumo = lembrete
            num_processo = processo.replace(" ", "")
            texto_lembrete = "UNICA RESUMOS - " + tipo_pedido
            print(f"Processo {i} de {total_planejados}: {num_processo}. Lembrete: {texto_lembrete}")

            cursor.execute(
                """
                SELECT rowid, data_lembrete FROM lembretes
                WHERE unidade = ? AND processo = ? AND tipo = ?
                LIMIT 1
                """,
                (unidade, processo, tipo_pedido)
            )
            existente = cursor.fetchone()
            if existente and existente[1]:
                ja_processados += 1
                print(f"  Já processado anteriormente ({existente[1]}). Pulando.")
                continue

            try:
                navegador.switch_to.default_content()
                eproc.entrar_no_processo(navegador, num_processo)
                time.sleep(1)
                insere_lembrete(navegador, texto_lembrete, validade)

                timestamp = datetime.now().strftime("%d/%m/%Y")
                if existente:
                    cursor.execute(
                        "UPDATE lembretes SET resumo = ?, data_lembrete = ? WHERE rowid = ?",
                        (resumo, timestamp, existente[0])
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO lembretes (unidade, processo, tipo, resumo, data_lembrete)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (unidade, processo, tipo_pedido, resumo, timestamp)
                    )
                conn.commit()
                contador += 1
            except Exception as e:
                print(f"Erro ao inserir lembrete no processo {num_processo}: {e}")
                continue

except Exception as e:
    print(f"Erro fatal durante inserção de lembretes: {e}")


print(f"Registros já processados (pulados): {ja_processados}")


# ============================================================
# Atualiza data_lembretes na tabela Comarcas
# ============================================================

with sqlite3.connect(db_path) as conn:
    conn.execute(
        "UPDATE Comarcas SET data_lembretes = ? WHERE nome = ?",
        (datetime.now().isoformat(), perfil)
    )
    conn.commit()
    print(f"\ndata_lembretes atualizada para comarca '{perfil}'.")


# ============================================================
# Cleanup
# ============================================================

print(f"\nTotal de lembretes inseridos: {contador}")
try:
    navegador.quit()
    print("Navegador fechado.")
except Exception:
    pass
gc.collect()
print("Memória liberada.")
