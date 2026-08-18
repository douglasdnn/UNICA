# -*- coding: utf-8 -*-
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import NoSuchElementException
from selenium.common.exceptions import TimeoutException
from webdriver_manager.chrome import ChromeDriverManager

#Bibliotecas de Sistema
import platform
import time
import re
import os
import requests
import psutil
import sqlite3
from contextlib import closing
import tempfile

#bibliotecas de configuração
import pyotp

#bibliotecas de automação
import pyperclip
try:
    import pyautogui
except BaseException:
    pyautogui = None

#Funções
def novo_browser(download_directory, headless=False):  
    # Em ambientes com HTTP(S)_PROXY global, o Chrome pode falhar com
    # ERR_PROXY_CONNECTION_FAILED. Por padrao, desativamos proxy para o eproc.
    disable_proxy = os.getenv("EPROC_DISABLE_PROXY", "1") != "0"

    if disable_proxy:
        for proxy_var in [
            "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
            "http_proxy", "https_proxy", "no_proxy",
        ]:
            os.environ.pop(proxy_var, None)

    PROCNAME = "chromedriver" # or chromedriver or IEDriverServer
    for proc in psutil.process_iter():
        # check whether the process name matches
        if proc.name() == PROCNAME:
            proc.kill()
    options = webdriver.ChromeOptions()

    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--window-size=1920,1080")

    options.add_argument("--no-sandbox")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    temp_profile_dir = tempfile.mkdtemp(prefix="eproc-chrome-")
    options.add_argument(f"--user-data-dir={temp_profile_dir}")
    if not headless:
        options.add_argument("start-maximized")
    options.add_argument("--remote-debugging-port=0")
    options.add_argument("--safebrowsing-disable-download-protection")
    if disable_proxy:
        options.add_argument("--no-proxy-server")
        options.add_argument("--proxy-server=direct://")
        options.add_argument("--proxy-auto-detect=false")
        options.add_argument("--proxy-bypass-list=*")
        options.set_capability("proxy", {"proxyType": "direct"})
    #options.add_argument("--incognito")
    options.add_experimental_option('prefs', {
        "download.default_directory": download_directory,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": False,
        "plugins.always_open_pdf_externally": True  # PDF será baixado automaticamente, não aberto no Chrome
    })
    if platform.system() == "Windows":
        chromedriver_path = r"D:\Douglas\Drivers\chromedriver.exe" 
        service = Service(chromedriver_path)
        chromePath = r"D:\Douglas\chrome-win64\chrome.exe"
        options.binary_location = chromePath
    else:
        import shutil
        system_chromedriver = shutil.which("chromedriver")
        if system_chromedriver:
            service = Service(system_chromedriver)
        else:
            service = Service(ChromeDriverManager().install())

    browser = webdriver.Chrome(service=service, options=options)
    params = {'behavior' : 'allow', 'downloadPath': download_directory}
    browser.execute_cdp_cmd('Page.setDownloadBehavior', params)

    # Tentar carregar a página com algumas tentativas para lidar com desconexões temporárias
    url_eproc = 'https://eproc1g.tjrs.jus.br/eproc/'
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            browser.get(url_eproc)
            break
        except Exception as e:
            print(f"Aviso: falha ao acessar {url_eproc} (tentativa {attempt}/{max_retries}): {e}")
            if attempt == max_retries:
                raise
            time.sleep(2)
    if not headless:
        browser.maximize_window()

    #Cria o diretório de download, se ele não existir
    if not os.path.exists(download_directory):
        os.makedirs(download_directory)

    print("Driver do Eproc importado")
    return browser

def login_no_eproc(browser, username, password, pyotop_code):  
    
    #define os campos
    cp1 = ["txtUsuario", "pwdSenha", "sbmEntrar", "txtAcessoCodigo", "btnValidar"]
    cp2 = ["username", "password", "kc-login", "otp", "kc-login"]
       
    # Esperar campo de usuário
    # Espera por cp1[0] ou cp2[0]
    try:
        WebDriverWait(browser, 5).until(
            EC.visibility_of_element_located((By.ID, cp1[0]))
        )
        cp = 1
    except TimeoutException:
        WebDriverWait(browser, 5).until(
            EC.visibility_of_element_located((By.ID, cp2[0]))
        )
        cp = 2

    if cp == 1:
        # Fluxo padrão (campos cp1)
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
        pass
    else:
        # Fluxo alternativo (campos cp2)
        browser.find_element(By.ID, 'username').send_keys(username)
        WebDriverWait(browser, 10).until(
            EC.visibility_of_element_located((By.ID, 'password'))
        )
        browser.find_element(By.ID, 'password').send_keys(password)
        WebDriverWait(browser, 10).until(
            EC.element_to_be_clickable((By.ID, 'kc-login'))
        ).click()
        totp = pyotp.TOTP(pyotop_code)
        WebDriverWait(browser, 30).until(
            EC.visibility_of_element_located((By.ID, 'otp'))
        ).send_keys(totp.now())
        WebDriverWait(browser, 10).until(
            EC.element_to_be_clickable((By.ID, 'kc-login'))
        ).click()
        return
    
def login_no_eproc_casa(browser, username, password, pyotop_code):  
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

def entrar_no_processo(driver, processo):
    driver.find_element(By.NAME, "txtNumProcessoPesquisaRapida").send_keys(processo)
    time.sleep(1)
    driver.find_element(By.CSS_SELECTOR, ".d-none .btn-pesquisar > .material-icons").click()
    time.sleep(1)
    # Aguarda até que o body esteja presente, indicando que a página carregou
    try:
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        print(f"Página do processo {processo} carregada com sucesso.")
    except TimeoutException:
        print(f"Falha ao carregar a página do processo {processo}.")

def entrar_nas_minutas(driver):
    try:
        target = driver.find_element(By.CSS_SELECTOR, '[data-target="#menu-ul-106"]')
        target.click()
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        # Procura o elemento <a> com title "Modelos Padrão" e clica nele
        target = driver.find_element(By.CSS_SELECTOR, 'a[title="Modelos padrão"]')
        target.click()
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        print(f"Página de modelos de minutas carregada.")
    except NoSuchElementException:
        print(f"Link não encontrado.")
        return 

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
    link_doc = elemento.find_element(By.XPATH, ".//*[contains(@class, 'infraLinkDoc')]")
    actions.move_to_element(link_doc).perform()
    # 3. Aguardar para o hover ter efeito
    time.sleep(3)
    
    # Verifica se há uma div com a classe 'divBoxPreview' visível na página
    overlays = navegador.find_elements(By.ID, "divBoxPreview")    
    visiveis = [div for div in overlays if div.is_displayed()]

    conteudo = ""
    if visiveis:
        div = overlays[0]
        # Move o foco para a div
        #ActionChains(navegador).move_to_element(div).click().perform()
        # Aguarda carregar o conteúdo (ajuste o tempo se necessário)
        time.sleep(3)
        # Clica no centro da divBoxPreview
        div_size = div.size
        div_location = div.location
        center_x = div_location['x'] + div_size['width'] // 2
        center_y = div_location['y'] + div_size['height'] // 2
        #pyautogui.click(center_x, center_y)
        #time.sleep(0.5)
        # Limpa a área de transferência
        tentativas = 0
        while pyperclip.paste() != "" and tentativas < 100:
            pyperclip.copy("")
            time.sleep(0.1)
            tentativas += 1

        # Seleciona todo o texto e copia (Ctrl+A, Ctrl+C)
        # Repete o Ctrl+C até que o conteúdo da área de transferência não seja ""
        actions.move_to_element(div).perform()
        time.sleep(0.1)
        actions.move_to_element(div).click().perform()
        #pyautogui.click(center_x, center_y)

        conteudo = ""

        for _ in range(20):
            actions.key_down(Keys.CONTROL).send_keys('a').key_up(Keys.CONTROL).perform()
            time.sleep(0.05)
    
        tentativas = 0
        while conteudo == "" and tentativas < 100:
            actions.key_down(Keys.CONTROL).send_keys('c').key_up(Keys.CONTROL).perform()
            time.sleep(0.2)
            conteudo = pyperclip.paste()
            tentativas += 1
        
        # Clica no botão de fechar o preview, se existir
        btn_close = navegador.find_element(By.ID, "divClosePreview")
        btn_close.click()    
        time.sleep(2)

    else:
        print("Erro ao recuperar o documento")
    return conteudo

def esperar_pdf(navegador, inicio_click, timeout=10):
    """Espera até encontrar uma requisição de PDF feita depois do clique."""
    inicio_espera = time.time()
    while time.time() - inicio_espera < timeout:
        for request in navegador.requests:
            if (
                request.response
                and "application/pdf" in request.response.headers.get("Content-Type", "").lower()
                and request.date >= inicio_click
            ):
                return request
        time.sleep(0.2)
    return None

def pega_PDF(navegador, num_processo, documento):
    # Criar ActionChains para executar o mouse over
    actions = ActionChains(navegador)
    # Aguarda o elemento estar presente
    WebDriverWait(navegador, 20).until(
        EC.presence_of_element_located((By.ID, documento))
    )
    # 1. Localizar o elemento pelo ID
    elemento = navegador.find_element(By.ID, documento)

    # Rolar a página para o elemento antes de mover o mouse
    navegador.execute_script("arguments[0].scrollIntoView(true); window.scrollBy(0, -150);", elemento)

    try:
        link_doc = elemento.find_element(By.XPATH, ".//*[contains(@class, 'infraLinkDoc')]")
        actions.move_to_element(link_doc).click().perform()
        time.sleep(3)

        momento_click = time.time()
        pdf_request = esperar_pdf(navegador, momento_click, timeout=10)

        if pdf_request and pdf_request.response and pdf_request.response.body:
            # Se uma nova aba foi aberta, feche-a após o download
            if len(navegador.window_handles) > 1:
                navegador.switch_to.window(navegador.window_handles[-1])
            # Faz o download direto
            pdfs_dir = "PDFS"
            if not os.path.exists(pdfs_dir):
                os.makedirs(pdfs_dir)
            pdf_path = os.path.join(pdfs_dir, f"{num_processo}.pdf")
            # Salva o PDF, sobrescrevendo se já existir
            with open(pdf_path, "wb") as f:
                f.write(pdf_request.response.body)
            # Fecha a aba do PDF após o download, se necessário
            if len(navegador.window_handles) > 1:
                navegador.close()
                navegador.switch_to.window(navegador.window_handles[0])
            print(f"✅ PDF salvo como {num_processo}.pdf")
            time.sleep(1)
        else:
            print("❌ Erro ao recuperar o documento: PDF não encontrado ou resposta inválida.")

    except Exception as e:
        print(f"❌ Erro ao recuperar o documento: {e}")

def baixa_pdf_por_link(navegador, documento, caminho_destino):
    """
    Faz o download de um PDF a partir de um link que abre o PDF em uma nova aba/janela.
    O download é feito via requests, utilizando os cookies e headers do navegador SeleniumWire.
    """
    print("Iniciando baixa_pdf_por_link")
    # Pega os cookies do navegador SeleniumWire
    session = requests.Session()
    print("Obtendo cookies do navegador")
    for cookie in navegador.get_cookies():
        session.cookies.set(cookie['name'], cookie['value'])
    print("Cookies obtidos e setados na sessão requests")
    
    print(f"Procurando elemento com ID: {documento}")
    elemento = navegador.find_element(By.ID, documento)
    print("Elemento encontrado, procurando link do documento")
    link = elemento.find_element(By.XPATH, ".//*[contains(@class, 'infraLinkDoc')]")
    pdf_url = link.get_attribute("href")
    print(f"URL do PDF obtida: {pdf_url}")

    # Tenta copiar o user-agent do navegador
    try:
        user_agent = navegador.execute_script("return navigator.userAgent;")
        session.headers.update({'User-Agent': user_agent})
        print(f"User-Agent setado: {user_agent}")
    except Exception as e:
        print(f"Erro ao obter User-Agent: {e}")

    print("Fazendo requisição GET para baixar o PDF")
    resp = session.get(pdf_url, stream=True)
    print(f"Status da resposta: {resp.status_code}")
    if resp.status_code == 200 and 'application/pdf' in resp.headers.get('Content-Type', ''):
        print(f"Salvando PDF em {caminho_destino}")
        with open(caminho_destino, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        print(f"PDF salvo em {caminho_destino}")
    else:
        print("Erro ao baixar o PDF. Status:", resp.status_code)

def grava_texto_documento(processo, evento, documentos):
    
    conn = sqlite3.connect("movimentos.db")
    cursor = conn.cursor() 
    
    cursor.execute("""
        UPDATE movimentos
        SET documentos = ? WHERE processo = ? AND evento = ?
    """, (str(documentos), str(processo), int(evento)))

    conn.commit()   
    print(f"Documentos do evento {evento} do processo {processo} atualizados.")
    cursor.close()
    conn.close()

def pega_eventos(navegador, perfil, processo):

    movimentos = []
    eventos = navegador.find_elements(By.CLASS_NAME, "infraEventoDescricao")
    insercoes=0

    for evento in eventos:
        tr_element = evento.find_element(By.XPATH, "./ancestor::tr")
        # Número do evento
        numero_evento_text = tr_element.find_element(By.XPATH, './td[2]').text.strip()
        # Extrai apenas os dígitos do texto para garantir que seja um número
        numero_evento = ''.join(filter(str.isdigit, numero_evento_text))
        if not numero_evento:
            continue  # pula se não encontrar número
        numero_evento = int(numero_evento)
        # Descrição do evento
        descricao = evento.text.strip()
        # Parte
        data_parte = tr_element.get_attribute("data-parte")
        # IDs dos documentos associados ao evento (busca por elementos com id começando com 'tdEvento{numero_evento}Doc')

        # Evita duplicatas: só adiciona se não houver um igual já inserido
        if not any(mov for mov in movimentos if mov["numero_evento"] == numero_evento and mov["descricao"] == descricao and mov["usuario"] == data_parte):
            movimentos.append({
                "numero_evento": numero_evento,
                "descricao": descricao,
                "usuario": data_parte
            })
            
            for mov in movimentos:
                conn = sqlite3.connect("movimentos.db", timeout=1)
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT 1 FROM movimentos WHERE processo = ? AND evento = ? LIMIT 1",
                    (str(processo), int(mov["numero_evento"]))
                )                
                existe = cursor.fetchone() is not None
                cursor.close()
                conn.close()
                if not existe:
                    conn = sqlite3.connect("movimentos.db", timeout=1)
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        INSERT INTO movimentos (processo, vara, evento, usuario, descricao)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            str(processo),
                            perfil,
                            int(mov["numero_evento"]),
                            str(data_parte),
                            mov["descricao"]                        
                        )

                    )    
                    conn.commit()
                    cursor.close()
                    conn.close()
                    insercoes=insercoes+1
    print(f"{insercoes} movimentos do processo {processo} inseridos no banco de dados.")

def atualiza_textos_documentos(navegador, processo, tipos_indesejaveis):
    conn = sqlite3.connect("movimentos.db")
    cursor = conn.cursor()   

    documentos_eventos = []
    eventos = navegador.find_elements(By.CLASS_NAME, "td-evento")

    for evento in eventos:
        doc_id = evento.get_dom_attribute("id")
        tr_element = evento.find_element(By.XPATH, "./ancestor::tr")
        evento_id = tr_element.find_element(By.XPATH, './td[2]').text
        # Garante que evento_id seja apenas um int (remove qualquer caractere não numérico)
        evento_id = ''.join(filter(str.isdigit, evento_id))
        
        # Pega o atributo data-nome do elemento com classe infraLinkDocumento dentro do link
        try:
            infra_link = evento.find_element(By.XPATH, ".//*[contains(@class, 'infraLinkDoc')]")
            data_nome = infra_link.get_attribute("data-nome")
        except Exception:
            data_nome = None

        documentos_eventos.append((doc_id, data_nome, evento_id))

    # Remove documentos cujo data-nome está na lista de indesejáveis
    documentos_eventos = [
        (doc_id, data_nome, evento_id)
        for doc_id, data_nome, evento_id in documentos_eventos
        if data_nome not in tipos_indesejaveis
    ]

    # Filtra apenas os documentos cujo evento ainda não possui texto na coluna "documentos"
    documentos_eventos_filtrados = []
    for doc_id, data_nome, evento_id in documentos_eventos:
        # Garante que evento_id seja um inteiro
        try:
            evento_id_int = int(''.join(filter(str.isdigit, evento_id)))
        except Exception:
            continue  # pula se não conseguir converter

        cursor.execute(
            "SELECT documentos FROM movimentos WHERE processo = ? AND evento = ?",
            (str(processo), evento_id_int)
        )
        row = cursor.fetchone()
        if row is None or not row[0]:
            documentos_eventos_filtrados.append((doc_id, data_nome, evento_id))

    documentos_eventos = documentos_eventos_filtrados

    textos_documentos = []
    for doc_id, data_nome, evento_id in documentos_eventos:
        texto = pega_texto_documento(navegador, doc_id)
        texto = f"**********{data_nome}**********\n{texto}"        
        textos_documentos.append((doc_id, texto))
        grava_texto_documento(processo, evento_id, texto)

    
    conn.close()

def insere_lembrete(navegador, texto):
    # Localiza o campo de lembrete e insere o texto
    
    navegador.switch_to.default_content()
    novo_btn = navegador.find_element(By.LINK_TEXT, "Novo")
    navegador.execute_script("arguments[0].scrollIntoView(true);", novo_btn)
    time.sleep(0.5)
    novo_btn.click()
    navegador.switch_to.frame(1)
    navegador.find_element(By.ID, "txaDescricao").click()
    navegador.find_element(By.ID, "txaDescricao").send_keys(texto)
    navegador.find_element(By.CSS_SELECTOR, "td:nth-child(2) > .infraRadio").click()
    navegador.find_element(By.CSS_SELECTOR, "#divInfraBarraComandosInferior > #sbmSalvar").click()
    navegador.switch_to.default_content()
    time.sleep(2)

def apaga_ultimo_lembrete(navegador):
    # Localiza o campo de lembrete e insere o texto
    
    navegador.find_element(By.CSS_SELECTOR, ".divLembretePara > a:nth-child(2) > .material-icons").click()
    assert navegador.switch_to.alert.text == "Deseja excluir o lembrete?"
    navegador.switch_to.alert.accept()
    time.sleep(2)



def trataMinuta(texto, tipo_ato):
    # Regex para capturar o texto a partir do tipo_ato até @NUMEROPROCESSOFORMATADO@
    # O re.escape é usado para escapar caracteres especiais no tipo_ato
    padrao = re.compile(
        rf"{re.escape(tipo_ato)}.*?(@NUMEROPROCESSOFORMATADO@)", 
        re.IGNORECASE | re.DOTALL | re.UNICODE
    )    
    match = padrao.search(texto)    
    if not match:
        return None  # Retorna None se não encontrou o padrão    
    texto_limpo = match.group(0)    
    # Remove tudo depois de @NUMEROPROCESSOFORMATADO@ (inclusive o que vier depois dele)
    texto_limpo = re.sub(r"(@NUMEROPROCESSOFORMATADO@).*", r"\1", texto_limpo, flags=re.DOTALL)    
    # Remove quebras de linha em excesso (mais de 2 quebras viram 2)
    texto_limpo = re.sub(r'\n\s*\n+', '\n\n', texto_limpo)    
    # Remove espaços em excesso nas linhas
    texto_limpo = '\n'.join(linha.strip() for linha in texto_limpo.splitlines())    
    return texto_limpo

def pegaMinuta(driver, cod_minuta):
    pyautogui.click(1000, 600)
    time.sleep(0.2)  # Pequena pausa para segurança
    driver.find_element(By.ID, "txtCodigoModelo").clear()
    time.sleep(0.2)  # Pequena pausa para segurança
    #insere o código 
    driver.find_element(By.ID, "txtCodigoModelo").click()
    time.sleep(0.2)  # Pequena pausa para segurança
    driver.find_element(By.ID, "txtCodigoModelo").send_keys(cod_minuta)
    time.sleep(2)
    pyautogui.hotkey('enter')
    time.sleep(4)
    # Localiza o elemento com código
    elemento = driver.find_element(By.PARTIAL_LINK_TEXT, str(cod_minuta))
    # Cria uma cadeia de ações e move o mouse até o elemento
    actions = ActionChains(driver)
    actions.move_to_element(elemento).perform()
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

def gravaTextoMinuta(cod_minuta, texto_minuta):
    with closing(sqlite3.connect('minutas.db')) as conn:
        cursor = conn.cursor()
        query_insert = 'UPDATE minutas SET conteudo = ? WHERE Código = ?;'
        cursor.execute(query_insert, (texto_minuta, cod_minuta))
        conn.commit()

def pegaProximaMinutaVazia():
    with closing(sqlite3.connect('minutas.db')) as conn:
        cursor = conn.cursor()
        query_select = 'SELECT "Código", "Tipo de Documento" FROM minutas WHERE conteudo IS NULL LIMIT 1'
        cursor.execute(query_select)
        resultados = cursor.fetchall()
        return resultados








