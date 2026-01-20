from flask import Flask, render_template
import pika
import json
import sqlite3
import threading
from datetime import datetime
import os
import pycountry

app = Flask(__name__)

RABBIT_HOST = os.getenv("RABBIT_HOST", "rabbitmq")
QUEUE_NAME = os.getenv("QUEUE_NAME", "interpol_queue")
DB_NAME=os.getenv("DB_NAME", "interpol.db")

# --- VERİTABANI AYARLARI ---
def get_db_connection():
    conn = sqlite3.connect('DB_NAME', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


#Veritabanına bağlan ve criminals tablosunu oluştur
def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    # Tabloyu oluştur (Eğer yoksa)
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS criminals
                   (
                       entity_id TEXT PRIMARY KEY,
                       name TEXT,
                       nationalities TEXT,
                       timestamp TEXT,
                       status TEXT DEFAULT 'NEW'
                   )
    ''')
    conn.commit()
    conn.close()

def convert_to_country(code_string):
    if not code_string:
        return "Not Known"

    codes = str(code_string).replace("[", "").replace("]", "").replace("'", "").replace('"', "")
    codes = codes.split(',')
    nationalities = []

    for code in codes:
        code = code.strip()
        try:
            nationality = pycountry.countries.get(alpha_2=code)
            if nationality:
                nationalities.append(nationality.name)
            else:
                nationalities.append(code)
        except:
            nationalities.append(code)

    return ', '.join(nationalities)

# --- ARKA PLAN GÖREVİ: KUYRUK DİNLEYİCİSİ ---
def consume_queue():
    # Docker içinde olduğumuz için host='rabbitmq' olmalı!
    try:
        connection = pika.BlockingConnection(pika.ConnectionParameters(RABBIT_HOST))
        channel = connection.channel()
        channel.queue_declare(queue=QUEUE_NAME)

        def callback(ch, method, properties, body):
            data = json.loads(body)
            notices = data.get('_embedded', {}).get('notices', [])

            conn = get_db_connection()
            cursor = conn.cursor()
            print(f"📥 [Web Container] Kuyruktan {len(notices)} veri geldi, kaydediliyor...")

            degisiklik_sayisi = 0
            for person in notices:
                try:
                    entity_id = person.get('entity_id')
                    name = f"{person.get('forename', '')} {person.get('name', '')}"
                    nationalities = str(person.get('nationalities', []))
                    nationalities = convert_to_country(nationalities)
                    # Burada basitlik olsun diye timestamp'i şu anki zaman alıyoruz
                    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    #Kullanıcı zaten mevcut mu ? kontrol et
                    existing_user = conn.execute('SELECT * FROM criminals WHERE entity_id = ?', (entity_id,)).fetchone()
                    if existing_user:
                       if existing_user['nationalities'] != nationalities or existing_user['name'] != name:
                          #Önceden kayıt edilmiş bilgi değişti
                          cursor.execute(''' UPDATE criminals
                                          SET nationalities = ?, name = ?, timestamp = ?, status = 'UPDATED' 
                                          WHERE entity_id = ? ''', (nationalities, name, now, entity_id))
                          degisiklik_sayisi += 1
                          print(f"GÜNCELLEME! {name} bilgilerinde değişiklik tespit edildi.")
                       else:
                          pass
                    else:
                        cursor.execute('''
                            INSERT OR REPLACE INTO criminals (entity_id, name, nationalities, timestamp, status)
                            VALUES (?, ?, ?, ?, 'NEW')
                        ''', (entity_id, name, nationalities, now))
                        degisiklik_sayisi += 1
                except Exception as e:
                    print(f"Hata: {e}")

            print(f"{degisiklik_sayisi} kayıtta işlem yapıldı.")
            conn.commit()
            conn.close()

        channel.basic_consume(queue=QUEUE_NAME, on_message_callback=callback, auto_ack=True)
        print(' [*] Kuyruk dinleme servisi başladı...')
        channel.start_consuming()
    except Exception as e:
        print(f"RabbitMQ Bağlantı Hatası: {e}")


# --- WEB SİTESİ ROTALARI ---
@app.route('/')
def index():
    conn = get_db_connection()
    # Veritabanındaki herkesi çek
    criminals = conn.execute('SELECT * FROM criminals ORDER BY timestamp DESC').fetchall()
    conn.close()

    #Jinja'ya göndermeden önce veriyi işle
    criminal_list = []
    now = datetime.now()

    for row in criminals:
        criminal = dict(row)
        timestamp = datetime.strptime(criminal['timestamp'], '%Y-%m-%d %H:%M:%S')
        difference_on_seconds = (now - timestamp).total_seconds()
        is_updated = criminal['status'] == 'UPDATED'
        if is_updated and difference_on_seconds < 30: #60 saniye içinde güncellendiyse alarm çalsın.
            criminal['alarm'] = True
        else:
            criminal['alarm'] = False
        criminal_list.append(criminal)
    return render_template('index_with_bootstrap.html', criminals=criminal_list)


if __name__ == '__main__':
    init_db()

    # Kuyruk dinleyicisini ayrı bir "Thread" (iş parçacığı) olarak başlat
    # Bu sayede Flask sunucusu çalışırken arka planda veri kaydı devam etsin.
    threading.Thread(target=consume_queue, daemon=True).start()

    # Web sunucusunu başlat
    app.run(host='0.0.0.0', port=5000)