import pandas as pd
import sqlite3

nome=input("Qual é o nome do arquivo?")
comarca=input("Qual é o nome da comarca?")
# Caminho do arquivo XLS/XLSX
caminho_arquivo = f'{nome}.xltx'  # ou .xlsx
# Nome do banco SQLite
caminho_banco = f'{nome}.db'
# Nome da tabela no SQLite
nome_tabela = f'{comarca}'
# Ler o arquivo Excel em um DataFrame
df = pd.read_excel(caminho_arquivo)
# Adicionar uma coluna 'id' baseada no número da linha (começando em 1)
df.insert(0, 'id', range(1, len(df) + 1))
# Conectar ao banco SQLite
conn = sqlite3.connect(caminho_banco)
# Escrever a tabela no banco, sobrescrevendo caso já exista (ou use if_exists='append' para adicionar)
df.to_sql(nome_tabela, conn, if_exists='replace', index=False)
conn.close()
print("Importação concluída com sucesso.")

conn = sqlite3.connect(f'{nome}.db')
cursor = conn.cursor()
query=f'ALTER TABLE {comarca} ADD conteudo TEXT;'
cursor.execute(query)
conn.commit()
conn.close()
print("Coluna conteúdo adicionada.")
