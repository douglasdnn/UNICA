import os
import requests
import json
from typing import Optional

def perguntar(pergunta: str, model: str = "gemini-1.5-flash") -> Optional[str]:
    """
    Envia uma pergunta para a API do Google Gemini e retorna a resposta em texto.

    Args:
        pergunta (str): O texto da pergunta a ser enviada para o modelo.
        model (str): O nome do modelo a ser usado (padrão: "gemini-1.5-flash").

    Returns:
        Optional[str]: A resposta de texto do modelo, ou None se ocorrer um erro.
    """
    # 1. Obter a chave da API a partir de uma variável de ambiente
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Erro: A variável de ambiente GEMINI_API_KEY não foi definida.")
        return None

    # 2. Montar a URL e o corpo da requisição
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    
    headers = {
        'Content-Type': 'application/json'
    }
    
    payload = {
        "contents": [{
            "parts": [{
                "text": pergunta
            }]
        }]
    }

    # 3. Fazer a requisição e tratar possíveis erros
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()  # Lança uma exceção para status de erro (4xx ou 5xx)
        
        data = response.json()
        
        # 4. Extrair e retornar a resposta de texto do JSON
        # Acessa de forma segura para evitar erros se a estrutura da resposta mudar
        resposta_texto = data.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text')
        
        if resposta_texto is None:
            print("❌ Erro: Não foi possível encontrar o texto da resposta no JSON recebido.")
            print("--- Resposta completa da API ---")
            print(json.dumps(data, indent=2, ensure_ascii=False))
            return None

        return resposta_texto

    except requests.exceptions.RequestException as e:
        print(f"❌ Erro na requisição para a API: {e}")
        if e.response is not None:
            print(f"Status Code: {e.response.status_code}")
            print(f"Resposta: {e.response.text}")
        return None
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        print(f"❌ Erro ao processar a resposta da API: {e}")
        print(f"Resposta recebida: {response.text}")
        return None

