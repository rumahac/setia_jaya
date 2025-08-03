import sqlite3
from flask import Flask

app = Flask(__name__)

def init_db():
    conn = sqlite3.connect('stok.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS barang
               (id INTEGER PRIMARY KEY, nama TEXT, stok INTEGER)''')
    conn.commit()
    conn.close()

@app.route('/')
def home():
    conn = sqlite3.connect('stok.db')
    c = conn.cursor()
    c.execute("SELECT * FROM barang")
    items = c.fetchall()
    conn.close()
    return {'barang': items}

@app.route('/tambah/<nama>/<int:stok>')
def tambah(nama, stok):
    conn = sqlite3.connect('stok.db')
    c = conn.cursor()
    c.execute("INSERT INTO barang (nama, stok) VALUES (?, ?)", (nama, stok))
    conn.commit()
    conn.close()
    return {'status': 'ok'}

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=8080)
