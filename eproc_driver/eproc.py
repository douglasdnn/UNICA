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

#Bibliotecas de Sistema
import time
import re
import csv
import os
import psutil
from bs4 import BeautifulSoup
from eproc_driver import eproc as eproc
import sqlite3
from pathlib import Path
import io
import pandas as pd

#bibliotecas de configuração
import pyotp
import configparser
import keyring

#bibliotecas de automação
import pyperclip
import pyautogui

#Bibliotecas de IA
from gemini import gemini as gemini
import ollama

#Funções
def novo_browser(download_directory):  
    PROCNAME = "chromedriver" # or chromedriver or IEDriverServer
    for proc in psutil.process_iter():
        # check whether the process name matches
        if proc.name() == PROCNAME:
            proc.kill()
    options = webdriver.ChromeOptions()
    
    #options.add_argument("--headless=new")

    options.add_argument("--no-sandbox")
    options.add_argument("--disable-gpu")
    options.add_argument("start-maximized")
    options.add_argument("--remote-debugging-port=9222")
    options.add_argument("--safebrowsing-disable-download-protection")

    options.add_experimental_option('prefs', {
        "download.default_directory": download_directory,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": False,
        #"plugins.always_open_pdf_externally": True, #It will not show PDF directly in chrome        
    })
    browser = webdriver.Chrome(options=options)

    browser.get('https://eproc1g.tjrs.jus.br/eproc/')
    browser.maximize_window()

        #Cria o diretório de download, se ele não existir
    if not os.path.exists(download_directory):
        os.makedirs(download_directory)

    print("Driver do Eproc importado")
    return browser

def login_no_eproc(browser, username, password, pyotop_code):  
    # Esperar campo de usuário
    WebDriverWait(browser, 20).until(
        EC.visibility_of_element_located((By.ID, 'txtUsuario'))
    )
    # Preencher usuário
    browser.find_element(By.ID, 'txtUsuario').send_keys(username)
    # Esperar campo de senha
    WebDriverWait(browser, 10).until(
        EC.visibility_of_element_located((By.ID, 'pwdSenha'))
    )
    # Pegar senha do keyring e preencher    
    browser.find_element(By.ID, 'pwdSenha').send_keys(password)
    # Esperar botão "Entrar" e clicar
    WebDriverWait(browser, 10).until(
        EC.element_to_be_clickable((By.ID, 'sbmEntrar'))
    ).click()
    #passa o 2FA com o Pyotop
    totp = pyotp.TOTP(pyotop_code)
    WebDriverWait(browser, 30).until(
        EC.visibility_of_element_located((By.ID, 'txtAcessoCodigo'))
    ).send_keys(totp.now())
    # Clica no botão "Entrar" para validar o 2FA
    WebDriverWait(browser, 10).until(
        EC.element_to_be_clickable((By.ID, 'btnValidar'))
    ).click()

def login_no_eproc_tj(browser, username, password, pyotop_code):  
    # Esperar campo de usuário
    WebDriverWait(browser, 20).until(
        EC.visibility_of_element_located((By.ID, 'username'))
    )
    # Preencher usuário
    browser.find_element(By.ID, 'username').send_keys(username)
    # Esperar campo de senha
    WebDriverWait(browser, 10).until(
        EC.visibility_of_element_located((By.ID, 'password'))
    )
    # Pegar senha do keyring e preencher    
    browser.find_element(By.ID, 'password').send_keys(password)
    # Esperar botão "Entrar" e clicar
    WebDriverWait(browser, 10).until(
        EC.element_to_be_clickable((By.ID, 'kc-login'))
    ).click()
    #passa o 2FA com o Pyotop
    totp = pyotp.TOTP(pyotop_code)
    WebDriverWait(browser, 30).until(
        EC.visibility_of_element_located((By.ID, 'otp'))
    ).send_keys(totp.now())
    # Clica no botão "Entrar" para validar o 2FA
    WebDriverWait(browser, 10).until(
        EC.element_to_be_clickable((By.ID, 'kc-login'))
    ).click()

def entrar_no_perfil(driver, perfil):
    try:
        perfil_div = driver.find_element(By.XPATH, f"//div[contains(text(), '{perfil}')]")
        perfil_div.click()
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        print(f"Perfil carregado: {perfil}")
    except NoSuchElementException:
        print(f"Perfil '{perfil}' não encontrado.")
        return    

def entrar_no_processo(driver, eproc):
    driver.find_element(By.NAME, "txtNumProcessoPesquisaRapida").send_keys(eproc)
    time.sleep(1)
    driver.find_element(By.CSS_SELECTOR, ".d-none .btn-pesquisar > .material-icons").click()
    time.sleep(1)
    # Aguarda até que o body esteja presente, indicando que a página carregou
    try:
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        print("Página do processo carregada com sucesso.")
    except TimeoutException:
        print("Falha ao carregar a página do processo.")

def pega_texto_documento(navegador, documento):
    WebDriverWait(navegador, 20).until(
        EC.presence_of_element_located((By.ID, documento))
    )
    # 1. Localizar o elemento pelo ID
    elemento = navegador.find_element(By.ID, documento)
    # 2. Criar ActionChains para executar o mouse over
    actions = ActionChains(navegador)
    # Rolar a página para o elemento antes de mover o mouse
    navegador.execute_script("arguments[0].scrollIntoView(true); window.scrollBy(0, -150);", elemento)
    # Faz o mouseover em cima do texto link infraLinkDocumento do elemento
    link_doc = elemento.find_element(By.CLASS_NAME, "infraLinkDocumento")
    actions.move_to_element(link_doc).perform()
    # 3. Aguardar para o hover ter efeito
    time.sleep(5)
    
    # Verifica se há uma div com a classe 'divBoxPreview' visível na página
    overlays = navegador.find_elements(By.ID, "divBoxPreview")
    visiveis = [div for div in overlays if div.is_displayed()]

    conteudo = ""
    if visiveis:
        div = overlays[0]
        # Move o foco para a div
        ActionChains(navegador).move_to_element(div).click().perform()
        # Aguarda carregar o conteúdo (ajuste o tempo se necessário)
        time.sleep(1)
        # Seleciona todo o texto e copia (Ctrl+A, Ctrl+C)
        ActionChains(navegador).key_down(Keys.CONTROL).send_keys('a').key_up(Keys.CONTROL).perform()
        time.sleep(1)
        ActionChains(navegador).key_down(Keys.CONTROL).send_keys('c').key_up(Keys.CONTROL).perform()
        time.sleep(1)
        conteudo = pyperclip.paste()
        # Clica no botão de fechar o preview, se existir
        btn_close = navegador.find_element(By.ID, "divClosePreview")
        btn_close.click()    
        time.sleep(3)

    else:
        print("Erro ao recuperar o documento")
    return conteudo

def pega_eventos(navegador, perfil, processo):

    movimentos = []
    eventos = navegador.find_elements(By.CLASS_NAME, "infraEventoDescricao")

    conn = sqlite3.connect("movimentos.db")
    cursor = conn.cursor()

    for evento in eventos:
        tr_element = evento.find_element(By.XPATH, "./ancestor::tr")
        # Número do evento
        numero_evento = tr_element.find_element(By.XPATH, './td[2]').text.strip()
        # Descrição do evento
        descricao = evento.text.strip()
        # Usuário responsável (normalmente na coluna 4)
        usuario = tr_element.find_element(By.XPATH, './td[5]').text.strip().split('\n')[0]
        # IDs dos documentos associados ao evento (busca por elementos com id começando com 'tdEvento{numero_evento}Doc')

        # Evita duplicatas: só adiciona se não houver um igual já inserido
        if not any(mov for mov in movimentos if mov["numero_evento"] == numero_evento and mov["descricao"] == descricao and mov["usuario"] == usuario):
            movimentos.append({
                "numero_evento": numero_evento,
                "descricao": descricao,
                "usuario": usuario
            })

            for mov in movimentos:
                cursor.execute(
                    "SELECT 1 FROM movimentos WHERE processo = ? AND evento = ? LIMIT 1",
                    (str(processo), int(mov["numero_evento"]))
                )
                existe = cursor.fetchone() is not None
                if not existe:
                    cursor.execute(
                        """
                        INSERT INTO movimentos (processo, vara, evento, descricao)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            str(processo),
                            perfil,
                            int(mov["numero_evento"]),
                            mov["descricao"]                        
                        )
                    )

    conn.commit()
    conn.close()

def atualiza_textos_documentos(navegador, processo):
    conn = sqlite3.connect("movimentos.db")
    cursor = conn.cursor()   

    documentos_eventos = []
    links = navegador.find_elements(By.CLASS_NAME, "td-evento")

    for link in links:
        doc_id = link.get_dom_attribute("id")
        tr_element = link.find_element(By.XPATH, "./ancestor::tr")
        evento_id = tr_element.find_element(By.XPATH, './td[2]').text
        
        # Pega o atributo data-nome do elemento com classe infraLinkDocumento dentro do link
        try:
            infra_link = link.find_element(By.CLASS_NAME, "infraLinkDocumento")
            data_nome = infra_link.get_attribute("data-nome")
        except Exception:
            data_nome = None

        documentos_eventos.append((doc_id, data_nome, evento_id))

    # Filtra apenas os documentos cujo evento ainda não possui texto na coluna "documentos"
    documentos_eventos_filtrados = []
    for doc_id, data_nome, evento_id in documentos_eventos:
        cursor.execute(
            "SELECT documentos FROM movimentos WHERE processo = ? AND evento = ?",
            (str(processo), int(evento_id.strip()))
        )
        row = cursor.fetchone()
        if row is None or not row[0]:
            documentos_eventos_filtrados.append((doc_id, data_nome, evento_id))

    documentos_eventos = documentos_eventos_filtrados

    textos_documentos = []
    for doc_id, data_nome, evento_id in documentos_eventos:
        texto = eproc.pega_texto_documento(navegador, doc_id)
        textos_documentos.append((doc_id, texto))

    # Atualiza cada tupla em documentos_eventos para incluir o texto correspondente
    documentos_eventos = [
        (doc_id, data_nome, evento_id, texto)
        for (doc_id, data_nome, evento_id), (id_movimento, texto) in zip(documentos_eventos, textos_documentos)
    ]

    for doc_id, data_nome, evento_num, texto in documentos_eventos:
        documentos = f"======= {data_nome} =======\n{texto}\n"
        cursor.execute("""
            UPDATE movimentos
            SET documentos = COALESCE(documentos, '') || ?
            WHERE processo = ? AND evento = ?
        """, (documentos, str(processo), int(evento_num)))
        conn.commit()
    conn.close()