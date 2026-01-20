from flask import Flask, render_template
from flask_sqlalchemy import SQLAlchemy
import pika
import json
import threading
from datetime import datetime
import os
import pycountry

app = Flask(__name__)

RABBIT_HOST = os.getenv("RABBIT_HOST", "rabbitmq")
QUEUE_NAME = os.getenv("QUEUE_NAME", "interpol_queue")
DB_NAME=os.getenv("DB_NAME", "interpol.db")

# postgresql://KULLANICI:SIFRE@SERVIS_ADI:PORT/VERITABANI_ADI
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://interpol_user:gizlisifre123@db:5432/interpol_db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

#Veritabanı objesini oluştur.
db = SQLAlchemy(app)

#Artık sorgu yazmıyoruz Class tanımlıyoruz.
class Criminal(db.Model):
    __tablename__ = 'criminals'

    id = db.Column(db.Integer, primary_key=True)
    entity_id = db.Column(db.String(50), unique=True)  # ID tekrar etmesin
    name = db.Column(db.String(200))
    nationalities = db.Column(db.String(200))
    timestamp = db.Column(db.String(50))
    alarm = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(50), default="NEW")

    def __repr__(self):
        return f'<Criminal {self.name}>'

def convert_to_country(code_string):
    if not code_string:
        return "Not Known"

    codes = str(code_string).replace("[", "").replace("]", "").replace("'", "").replace('"', "")
    codes = codes.split(',')
    nationalities = []

    for code in codes:
        code = code.strip() #Boşlukları ortadan kaldır.
        try:
            nationality = pycountry.countries.get(alpha_2=code)
            if nationality:
                nationalities.append(nationality.name)
            else:
                nationalities.append(code)
        except:
            nationalities.append(code)

    return ', '.join(nationalities)


# --- DÜZELTİLMİŞ HALİ ---
def consume_queue():
    try:
        connection = pika.BlockingConnection(pika.ConnectionParameters(RABBIT_HOST))
        channel = connection.channel()
        channel.queue_declare(queue=QUEUE_NAME)

        def callback(ch, method, properties, body):
            data = json.loads(body)
            notices = data.get('_embedded', {}).get('notices', [])
            print(f"📥 [Web Container] Kuyruktan {len(notices)} veri geldi...")

            # 1. DÜZELTME: Context döngünün DIŞINA alındı.
            with app.app_context():
                degisiklik_sayisi = 0

                for person in notices:
                    try:
                        entity_id = person.get('entity_id')
                        name = f"{person.get('forename', '')} {person.get('name', '')}".strip()
                        raw_nationalities = str(person.get('nationalities', []))
                        nationalities = convert_to_country(raw_nationalities)
                        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                        existing_user = Criminal.query.filter_by(entity_id=entity_id).first()

                        if existing_user:
                            # Değişiklik kontrolü
                            if existing_user.nationalities != nationalities or existing_user.name != name:
                                existing_user.nationalities = nationalities
                                existing_user.name = name
                                existing_user.timestamp = now
                                existing_user.status = "UPDATED"
                                degisiklik_sayisi += 1
                                print(f"GÜNCELLEME: {name}")
                        else:
                            yeni_suclu = Criminal(
                                entity_id=entity_id,
                                name=name,
                                nationalities=nationalities,
                                timestamp=now,
                                alarm=False,
                                status="NEW"
                            )
                            db.session.add(yeni_suclu)
                            degisiklik_sayisi += 1

                    except Exception as e:
                        print(f"Veri işleme hatası: {e}")

                # 2. DÜZELTME: Döngü bittikten sonra TEK SEFERDE kaydet (Toplu işlem)
                if degisiklik_sayisi > 0:
                    db.session.commit()
                    print(f"💾 {degisiklik_sayisi} değişiklik kaydedildi.")

        channel.basic_consume(queue=QUEUE_NAME, on_message_callback=callback, auto_ack=True)
        print(' [*] Kuyruk dinleme servisi başladı...')
        channel.start_consuming()

    except Exception as e:
        print(f"RabbitMQ Bağlantı Hatası: {e}")


# --- WEB SİTESİ ROTALARI ---
@app.route('/')
def index():
    # Veritabanındaki herkesi çek
    criminals = Criminal.query.order_by(Criminal.id.asc()).all()

    #Jinja'ya göndermeden önce veriyi işle
    criminal_list = []
    now = datetime.now()

    for criminal in criminals:
        timestamp = datetime.strptime(criminal.timestamp, '%Y-%m-%d %H:%M:%S')
        difference_on_seconds = (now - timestamp).total_seconds()
        is_updated = criminal.status == 'UPDATED'
        if is_updated and difference_on_seconds < 30: #60 saniye içinde güncellendiyse alarm çalsın.
            criminal.alarm = True
        else:
            criminal.alarm = False
        criminal_list.append(criminal)
    return render_template('index_with_bootstrap.html', criminals=criminal_list)


if __name__ == '__main__':

    with app.app_context():
        db.create_all()

    # Kuyruk dinleyicisini ayrı bir "Thread" (iş parçacığı) olarak başlat
    # Bu sayede Flask sunucusu çalışırken arka planda veri kaydı devam etsin.
    threading.Thread(target=consume_queue, daemon=True).start()

    # Web sunucusunu başlat
    app.run(host='0.0.0.0', port=5000)