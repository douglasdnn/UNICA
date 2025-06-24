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

#Driver do eproc
print("Driver do Eproc importado")

def configura_webdriver(downloadpath):
    options = webdriver.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-gpu")
    options.add_argument("start-maximized")
    options.add_argument("--remote-debugging-port=9222")
    options.add_argument("--safebrowsing-disable-download-protection")
    options.add_experimental_option("prefs", {
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing_for_trusted_sources_enabled": False,
        "safebrowsing.enabled": False,
        "plugins.always_open_pdf_externally": True, #It will not show PDF directly in chrome
        "download.default_directory": downloadpath
        })
    return options

def novo_browser(options):  
    driver = webdriver.Chrome(options=options)
    driver.implicitly_wait(0.5)
    return driver

def novo_webdriver():  
    options = webdriver.ChromeOptions()
    options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
    driver = webdriver.Chrome(options=options)
    driver.implicitly_wait(0.5)
    driver.get("https://eproc1g.tjrs.jus.br/eproc/externo_controlador.php?acao=principal")
    time.sleep(5) 
    return driver

def preenche_login(driver, usuario, senha, tempo):
#vai até a tela de login
    driver.get("https://eproc1g.tjrs.jus.br/eproc/externo_controlador.php?acao=principal")
    time.sleep(tempo)    

#preenche a tela de login
    driver.find_element(By.ID, "txtUsuario").click()
    time.sleep(tempo)
    driver.find_element(By.ID, "txtUsuario").send_keys(usuario)
    time.sleep(tempo)
    driver.find_element(By.ID, "txtUsuario").click()
    time.sleep(tempo)
    driver.find_element(By.ID, "pwdSenha").send_keys(senha)
    time.sleep(tempo)
    driver.find_element(By.ID, "pwdSenha").send_keys(Keys.ENTER)
    time.sleep(tempo+5)

#entra no perfil selecionado
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

#passa o aviso de sessão encerrada, se necessário
def pula_mensagens(driver):
    try: 
        driver.switch_to.alert.text == "Sua sessão foi encerrada. Por favor, inicie uma nova sessão."
        element = driver.find_element(By.ID, "imgCertificado")
        print("Usuário deslogado") 
    except:
        print("Usuário já logado") 

#entra em um determinado processo
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

def pesquisa_lista_processos_certificar(driver):
    driver.find_element(By.CSS_SELECTOR, "a:nth-child(2) > .material-icons").click()
    time.sleep(2)
    driver.find_element(By.XPATH, "//a[contains(@href, '11667251739982685964026375651')]").click()
    time.sleep(2)
    driver.find_element(By.ID, "optPaginacao100").click()
    time.sleep(2)
    driver.find_element(By.ID, "divInfraAreaDados").click()
    time.sleep(2)
    driver.execute_script("window.scrollTo(0, 0)")
    time.sleep(2)
    driver.find_element(By.CSS_SELECTOR, "#divInfraBarraComandosSuperior > #btnConsultar").click()
    time.sleep(2)


#cria uma lista com os processos na tela do localizador
def cria_lista(driver, arquivo):
    links = driver.find_elements(By.PARTIAL_LINK_TEXT, ".8.21.")
    with open(arquivo, 'w') as file:
        for link in links:
            file.write(str(link.get_attribute('text').replace('.', '').replace('-', '')) + '\n')
    print("Lista criada em " + arquivo)

def troca_buchabqui(driver, processo):
    entrar_no_processo(driver, processo)

    driver.find_element(By.LINK_TEXT, "Associar Procurador Parte").click()
    time.sleep(1)

    # Verifica se tem a Carolina. Se tem, passa adiante.
    tabela = driver.find_element(By.ID, ("divInfraAreaTabela"))
    texto = "CAROLINA PINHEIRO MACHADO BUCHABQUI"
    achado = "não"
    for i, linha in enumerate(tabela.find_elements(By.TAG_NAME, ("tr"))):
        for celula in linha.find_elements(By.TAG_NAME, ("td")):
            if texto in celula.text:
                linha_achada = i + 1  
                achado = "sim"
    if achado == "não":
        # Associar procurador Carolina
        driver.find_element(By.XPATH, "//img[@alt='Adicionar Procurador']").click()
        driver.find_element(By.ID, "txtProcurador").click()
        time.sleep(1)
        driver.find_element(By.ID, "txtProcurador").send_keys("RS080737")
        time.sleep(10)
        driver.find_element(By.XPATH, "//a[contains(.,'RS080737 - Carolina Pinheiro Machado Buchabqui - ADVOGADO')]").click()
        time.sleep(1)
        driver.find_element(By.CSS_SELECTOR, "#divInfraBarraComandosInferior > #btnAssociar").click()
        time.sleep(1)
        driver.find_element(By.CSS_SELECTOR, "#divInfraBarraComandosInferior > #btnConfirmarAssoc").click()
        time.sleep(1)

    # retira a Marília
    tabela = driver.find_element(By.ID, ("divInfraAreaTabela"))
    texto = "MARILIA PINHEIRO MACHADO BUCHABQUI"
    achado = "não"
    for i, linha in enumerate(tabela.find_elements(By.TAG_NAME, ("tr"))):
        for celula in linha.find_elements(By.TAG_NAME, ("td")):
            if texto in celula.text:
                linha_achada = i + 1  
                achado = "sim"
    if achado == "sim":
        driver.find_element(By.XPATH, "//tr["+str(linha_achada)+"]/td[5]/a[3]/img").click()
        time.sleep(2)
        driver.switch_to.alert.accept()
        time.sleep(1)

    # Volta
    driver.find_element(By.CSS_SELECTOR, "#divInfraBarraComandosInferior > #btnVoltar").click()

    
def certifica_buchabqui(driver, processo, senha):
    entrar_no_processo(driver, processo)
    driver.switch_to.window(driver.window_handles[0])
    time.sleep(1)
    driver.execute_script("window.scrollTo(0, 600);")
    time.sleep(1)
    driver.find_element(By.LINK_TEXT, "starPreferências").click()
    time.sleep(2)
    driver.find_element(By.LINK_TEXT, "certifica troca Buchabqui").click()
    time.sleep(2)
    print(f"Processo {processo}: Criando certidão...")
    driver.switch_to.window(driver.window_handles[1])
    time.sleep(3)
    driver.find_element(By.XPATH, "//button[2]/span").click()
    time.sleep(4)
    driver.switch_to.window(driver.window_handles[0])
    time.sleep(4)
    driver.find_element(By.CSS_SELECTOR, ".infraTrClara a:nth-child(4) .infraImg").click()
    time.sleep(4)
    driver.switch_to.frame(1)
    time.sleep(1)
    print(f"Processo {processo}: Assinando certidão...")
    driver.find_element(By.ID, "txtSenha").send_keys(senha)
    time.sleep(2)
    driver.find_element(By.ID, "txtSenha").send_keys(Keys.ENTER)
    time.sleep(1)
    # driver.find_element(By.NAME, "imgRecursoMinutaAjax").click()
    # time.sleep(3)
    # assert driver.switch_to.alert.text == "Deseja Enviar minuta para movimentação?"
    # driver.switch_to.alert.accept()
    # time.sleep(3)
    # driver.find_element(By.ID, "txtEvento").click()
    # time.sleep(2)
    # driver.find_element(By.ID, "txtEvento").send_keys("Juntada de certidão")
    # time.sleep(5)
    # element = driver.find_element(By.LINK_TEXT, "Juntada de certidão")
    # time.sleep(2)
    # print(f"Processo {processo}: Anexando certidão...")
    # driver.find_element(By.ID, "txtEvento").send_keys(Keys.ENTER)
    # time.sleep(2)
    # driver.find_element(By.ID, "sbmMovimentar").click()
    # time.sleep(5)
    print(f"Processo {processo}: Concluído.")
    driver.execute_script("window.scrollTo(0, 600);")    


