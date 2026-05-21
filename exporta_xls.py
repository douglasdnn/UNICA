import sqlite3
import pandas as pd
import re
import os

def export_sqlite_to_csv(db_path, output_dir):
    # Conecta ao banco
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Garante que o diretório de saída existe
    os.makedirs(output_dir, exist_ok=True)

    # Lista todas as tabelas
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall()]

    # Filtra as que começam com letras (a-z ou A-Z)
    tables = [t for t in tables if re.match(r'^[A-Za-z]', t)]

    for table_name in tables:
        print(f"Exportando tabela: {table_name}")
        df = pd.read_sql_query(f"SELECT * FROM '{table_name}'", conn)
        output_file = os.path.join(output_dir, f"{table_name}.csv")
        df.to_csv(output_file, index=False, encoding='utf-8-sig')

    conn.close()
    print(f"Exportação concluída. Arquivos salvos em: {output_dir}")

# Exemplo de uso:
export_sqlite_to_csv('pet.db', 'planilhas_exportadas_csv')
