import requests
from flask import Flask, render_template
from flask_sqlalchemy import SQLAlchemy
import pika
import json
import threading
from datetime import datetime
import os
import pycountry
from io import BytesIO
from minio import Minio

app = Flask(__name__)

#Environment Variables
RABBIT_HOST = os.getenv("RABBIT_HOST", "rabbitmq")
QUEUE_NAME = os.getenv("QUEUE_NAME", "interpol_queue")
DB_NAME=os.getenv("DB_NAME", "interpol.db")

#Minio Configuration
MINIO_ENDPOINT = "minio:9000" #Dockerdan bağlanabilmek için
MINIO_ACCESS = "minioadmin"
MINIO_SECRET = "minioadmin"
BUCKET_NAME = "interpol-criminal-images"

# postgresql://KULLANICI:SIFRE@SERVIS_ADI:PORT/VERITABANI_ADI
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://interpol_user:gizlisifre123@db:5432/interpol_db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

#Veritabanı objesini oluştur.
db = SQLAlchemy(app)

#Minio Initialization
minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS,
    secret_key=MINIO_SECRET,
    secure=False
)

# Kova (Bucket) oluşturma işlemi
try:
    if not minio_client.bucket_exists(BUCKET_NAME):
        minio_client.make_bucket(BUCKET_NAME)
        print(f"📂 '{BUCKET_NAME}' kovası oluşturuldu.")

        # --- POLICY AYARI (HATA KORUMALI) ---
        # MinIO sürümlerine göre policy formatı değişebiliyor.
        # En basit ve garanti yöntem: Principal = "*"
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "PublicRead",
                    "Effect": "Allow",
                    "Principal": "*",
                    "Action": ["s3:GetObject"],
                    "Resource": [f"arn:aws:s3:::{BUCKET_NAME}/*"]
                }
            ]
        }
        minio_client.set_bucket_policy(BUCKET_NAME, json.dumps(policy))
        print("🔓 Kova 'Public' yapıldı.")

except Exception as e:
    # Eğer Policy hatası verirse programı çökertme, sadece uyarı ver ve devam et.
    # Resimler yine de indirilir, sadece tarayıcıda hemen görünmeyebilir.
    print(f"⚠️ MinIO Policy Uyarısı: {e}")
    print("Devam ediliyor... (Resim indirme işlemi etkilenmez)")

#Veritabanı Modeli
class Criminal(db.Model):
    __tablename__ = 'criminals'

    id = db.Column(db.Integer, primary_key=True)
    entity_id = db.Column(db.String(50), unique=True)  # ID tekrar etmesin
    name = db.Column(db.String(200))
    nationalities = db.Column(db.String(200))
    timestamp = db.Column(db.String(50))
    alarm = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(50), default="NEW")
    image_url = db.Column(db.String(300)) #Thumbnail linkini tutacağız

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

#Image Process Engine
def process_thumbnail(criminal_data, entity_id):
    """
    Sadece _links -> thumbnail içindeki resmi indirir ve MinIO'ya atar.
    """
    filename = f"{entity_id.replace('/','_')}.jpg" #Dosya Adı: ID.jpg
    try:
        links = criminal_data.get("_links", {})
        thumbnail_data = links.get("thumbnail", {})
        href = thumbnail_data.get("href")

        if not href or not isinstance(href, str) or not href.startswith('http'):
            return None

        # 1.Resmi indir (RAM'e)
        response = requests.get(href, timeout=10, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        if response.status_code == 200:
            img_data = BytesIO(response.content)
            length = len(response.content)

            # 2.MinIO'ya yükle
            minio_client.put_object(
                BUCKET_NAME,
                filename,
                img_data,
                length,
                content_type="image/jpeg"
            )
        #3.Web server için URL üret (localhost)
        return f"http://localhost:9000/{BUCKET_NAME}/{filename}"

    except Exception as e:
        print(f"Resim Hatası ({entity_id}): {e}")
        return None

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

                        existing = Criminal.query.filter_by(entity_id=entity_id).first()

                        if existing:
                            # Değişiklikleri not alacağımız boş bir liste oluşturuyoruz
                            degisiklik_raporu = []

                            # 1. İsim Kontrolü
                            if existing.name != name:
                                degisiklik_raporu.append(f"İSİM: '{existing.name}' -> '{name}'")
                                existing.name = name  # Veritabanını güncelle

                            # 2. Uyruk Kontrolü
                            if existing.nationalities != nationalities:
                                degisiklik_raporu.append(f"UYRUK: '{existing.nationalities}' -> '{nationalities}'")
                                existing.nationalities = nationalities  # Veritabanını güncelle

                            # Eğer rapor listesi boş değilse, demek ki bir şeyler değişmiş
                            if len(degisiklik_raporu) > 0:
                                existing.timestamp = now
                                existing.status = "UPDATED"
                                existing.alarm = False  # Alarmın tekrar çalması için (Index'te hesaplanacak)

                                degisiklik_sayisi += 1

                                # Listeyi okunabilir bir cümleye çevir
                                rapor_metni = " | ".join(degisiklik_raporu)
                                print(f"♻️ GÜNCELLEME [{entity_id}]: {rapor_metni}")
                        else:
                            #Thumbnail'i minIO'ya çek.
                            thumb_url = process_thumbnail(person, entity_id)

                            #Veritabanına kaydet.
                            yeni_suclu = Criminal(
                                entity_id=entity_id,
                                name=name,
                                nationalities=nationalities,
                                timestamp=now,
                                alarm=False,
                                status="NEW",
                                image_url=thumb_url
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