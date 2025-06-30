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
    time.sleep(4)

    # Pega o texto
    pyautogui.click(1000, 600)
    time.sleep(0.5)  # Pequena pausa para garantir que o foco esteja correto
    pyautogui.hotkey('ctrl', 'a')
    time.sleep(0.2)  # Pequena pausa para segurança
    pyautogui.hotkey('ctrl', 'c')
    time.sleep(0.2)  # Dá tempo do sistema copiar para a área de transferência
    conteudo = pyperclip.paste()
    pyautogui.click(1000, 600)
    pyautogui.hotkey('f5')
    time.sleep(3)  # Pequena pausa para segurança

    #devolve o conteudo
    return conteudo