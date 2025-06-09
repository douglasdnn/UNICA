import pandas as pd
import sqlite3

# Caminho do arquivo XLS/XLSX
caminho_arquivo = 'rel.xltx'  # ou .xlsx
# Nome do banco SQLite
caminho_banco = 'minutas.db'
# Nome da tabela no SQLite
nome_tabela = 'minutas'
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

conn = sqlite3.connect('minutas.db')
cursor = conn.cursor()
query='ALTER TABLE minutas ADD conteudo TEXT;'
cursor.execute(query)
conn.commit()
conn.close()
print("Coluna conteúdo adicionada.")
