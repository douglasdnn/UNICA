
import sqlite3

conn = sqlite3.connect('minutas.db')
cursor = conn.cursor()
query='ALTER TABLE minutas ADD conteudo TEXT;'
cursor.execute(query)
conn.commit()
conn.close()