#!/usr/bin/env python3
# 03-lembretes.py - Consolidado do notebook Unica-04-Insere-Lembretes.ipynb

import argparse

parser = argparse.ArgumentParser(description="Insere lembretes no eproc")
parser.add_argument("--headless", action="store_true", help="Rodar em modo headless (sem interface gráfica)")
parser.add_argument("--debug", action="store_true", help="Imprimir mensagens de debug")
parser.add_argument("--validade", type=int, default=20, help="Validade dos lembretes em dias (padrão: 20)")
parser.add_argument("--comarca", type=str, help="Nome da comarca a processar")
args = parser.parse_args()

# ============================================================
# CELL 1: Importações, setup, login no eproc
# ============================================================

from selenium import webdriver
from selenium.webdriver.support.select import Select
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.alert import Alert
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import NoSuchElementException
from selenium.common.exceptions import TimeoutException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import ElementClickInterceptedException

from datetime import datetime
from datetime import timedelta
from datetime import date
from datetime import timezone
import platform
import time
import re
import csv
import os
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import psutil
from bs4 import BeautifulSoup
from eproc_driver import eproc as eproc
import sqlite3
from pathlib import Path
import io
import pandas as pd
from contextlib import closing
import gc

import pyotp
import configparser
import keyring
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

# Lê TODAS as comarcas e sincroniza lembretes da planilha com o DB
with sqlite3.connect(db_path) as conn:
    comarcas = conn.execute(
        "SELECT nome, spreadsheet_id FROM Comarcas WHERE spreadsheet_id IS NOT NULL AND spreadsheet_id != ''"
    ).fetchall()

total_inseridos_sync = 0
total_existentes_sync = 0

for nome_comarca, sid_comarca in comarcas:
    try:
        planilha_comarca = client.open_by_key(sid_comarca)
        sheet_comarca = planilha_comarca.worksheet(nome_comarca)
        all_rows = sheet_comarca.get_all_values()

        lembretes_planilha = [
            (row[0], row[1], row[4], row[5] if len(row) > 5 else "")
            for row in all_rows[1:]
            if len(row) > 4 and row[4] and len(row[4]) > 1
        ]

        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            inseridos = 0
            existentes = 0

            for unidade, processo, tipo, resumo in lembretes_planilha:
                # Verifica se já existe no DB (mesmo unidade + processo + tipo)
                cursor.execute(
                    "SELECT 1 FROM lembretes WHERE unidade = ? AND processo = ? AND tipo = ?",
                    (unidade, processo, tipo)
                )
                if cursor.fetchone():
                    existentes += 1
                else:
                    cursor.execute(
                        "INSERT INTO lembretes (unidade, processo, tipo, resumo) VALUES (?, ?, ?, ?)",
                        (unidade, processo, tipo, resumo)
                    )
                    inseridos += 1

            conn.commit()
            total_inseridos_sync += inseridos
            total_existentes_sync += existentes
            print(f"  {nome_comarca}: {inseridos} novos, {existentes} já existentes")

    except Exception as e:
        print(f"  {nome_comarca}: erro ao acessar planilha ({type(e).__name__}: {e})")

print(f"\nSincronização concluída: {total_inseridos_sync} novos lembretes, {total_existentes_sync} já existiam.")

# ============================================================
# CELL 3: Seleciona comarca com data_lembretes mais antiga para inserir
# ============================================================

with sqlite3.connect(db_path) as conn:
    cursor = conn.cursor()
    if comarca_solicitada:
        cursor.execute(
            """
            SELECT nome, spreadsheet_id FROM Comarcas
                        WHERE nome = ? COLLATE NOCASE
              AND spreadsheet_id IS NOT NULL AND spreadsheet_id != ''
            LIMIT 1
            """,
            (comarca_solicitada,)
        )
    else:
        cursor.execute("""
            SELECT nome, spreadsheet_id FROM Comarcas
            WHERE spreadsheet_id IS NOT NULL AND spreadsheet_id != ''
            ORDER BY
                CASE WHEN data_lembretes IS NULL THEN 0 ELSE 1 END,
                data_lembretes ASC
            LIMIT 1
        """)
    resultado = cursor.fetchone()

if resultado is None:
    if comarca_solicitada:
        print(f"Comarca solicitada não encontrada no banco de dados: {comarca_solicitada}")
    else:
        print("Nenhuma comarca encontrada no banco de dados.")
    exit(0)

perfil, comarca_spreadsheet_id = resultado
if comarca_solicitada:
    print(f"\nComarca solicitada por parâmetro: {perfil}")
else:
    print(f"\nComarca selecionada para inserção: {perfil}")

# Verifica se há lembretes pendentes para essa comarca
with sqlite3.connect(db_path) as conn:
    pendentes = conn.execute(
        "SELECT COUNT(*) FROM lembretes WHERE unidade = ? AND data_lembrete IS NULL",
        (perfil,)
    ).fetchone()[0]

if pendentes == 0:
    # Atualiza data_lembretes mesmo sem pendentes
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE Comarcas SET data_lembretes = ? WHERE nome = ?",
            (datetime.now().isoformat(), perfil)
        )
        conn.commit()
    print(f"Nenhum lembrete pendente para '{perfil}'. data_lembretes atualizada. Encerrando.")
    exit(0)

print(f"Lembretes pendentes para '{perfil}': {pendentes}")

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

try:
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM lembretes WHERE unidade = ? AND data_lembrete IS NULL", (perfil,))
        lembretes_pendentes = cursor.fetchall()

        total_pendentes = len(lembretes_pendentes)
        print(f"Total de lembretes pendentes: {total_pendentes}")

        for i, lembrete in enumerate(lembretes_pendentes, 1):
            num_processo = lembrete[1].replace(" ", "")
            texto_lembrete = "UNICA RESUMOS - " + lembrete[2]
            print(f"Processo {i} de {total_pendentes}: {num_processo}. Lembrete: {texto_lembrete}")

            try:
                navegador.switch_to.default_content()
                eproc.entrar_no_processo(navegador, num_processo)
                time.sleep(1)
                insere_lembrete(navegador, texto_lembrete, validade)

                timestamp = datetime.now().strftime("%d/%m/%Y")
                cursor.execute(
                    "UPDATE lembretes SET data_lembrete = ? WHERE processo = ? AND unidade = ?",
                    (timestamp, num_processo, lembrete[0])
                )
                conn.commit()
                contador += 1
            except Exception as e:
                print(f"Erro ao inserir lembrete no processo {num_processo}: {e}")
                continue

except Exception as e:
    print(f"Erro fatal durante inserção de lembretes: {e}")


# ============================================================
# CELL 5: Resumo dos lembretes inseridos + log em arquivo
# ============================================================

data_hoje = datetime.now().strftime("%d/%m/%Y")
print(f"\nData de hoje: {data_hoje}")

log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lembretes_log.txt")

with sqlite3.connect(db_path) as conn:
    cursor = conn.cursor()

    # Resumo de TODAS as comarcas (lembretes inseridos hoje)
    cursor.execute("""
        SELECT unidade, tipo, COUNT(*) FROM lembretes
        WHERE data_lembrete LIKE ?
        GROUP BY unidade, tipo
        ORDER BY unidade, tipo
    """, (f"{data_hoje}%",))
    resultados_todas = cursor.fetchall()

with open(log_path, "a", encoding="utf-8") as log:
    log.write(f"\n{'='*60}\n")
    log.write(f"Execução: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n")
    log.write(f"Validade dos lembretes: {validade} dias\n")
    log.write(f"{'='*60}\n")

    if not resultados_todas:
        log.write("Nenhum lembrete inserido hoje.\n")
        print("Nenhum lembrete inserido hoje.")
    else:
        comarca_atual = None
        for unidade, tipo_pedido, quantidade in resultados_todas:
            if unidade != comarca_atual:
                comarca_atual = unidade
                header = f"\nComarca: {unidade}"
                log.write(header + "\n")
                log.write("-" * len(header.strip()) + "\n")
                print(header)
            linha = f'  "UNICA RESUMOS - {tipo_pedido}" - {quantidade} processos'
            log.write(linha + "\n")
            print(linha)

    log.write(f"\nTotal de lembretes inseridos nesta execução: {contador}\n")

print(f"\nLog salvo em: {log_path}")


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
# Zera a tabela de lembretes se todos foram concluídos
# ============================================================

with sqlite3.connect(db_path) as conn:
    pendentes_restantes = conn.execute(
        "SELECT COUNT(*) FROM lembretes WHERE data_lembrete IS NULL"
    ).fetchone()[0]

    if pendentes_restantes == 0:
        # Salva todos os lembretes em Historico antes de apagar
        conn.execute("""
            CREATE TABLE IF NOT EXISTS Historico (
                tipo TEXT,
                resumo TEXT
            )
        """)
        salvos = conn.execute(
            "INSERT INTO Historico (tipo, resumo) SELECT tipo, resumo FROM lembretes WHERE tipo IS NOT NULL AND tipo != ''"
        ).rowcount
        conn.execute("DELETE FROM lembretes")
        conn.commit()
        print(f"Todos os lembretes foram concluídos. {salvos} registros salvos em Historico. Tabela 'lembretes' zerada.")
    else:
        print(f"Ainda restam {pendentes_restantes} lembretes pendentes. Tabela mantida.")


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
