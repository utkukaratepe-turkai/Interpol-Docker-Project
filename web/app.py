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
from sqlalchemy.dialects.postgresql import JSONB
import time

headers = {"User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Mobile Safari/537.36"} #403 hatası almamak için

app = Flask(__name__)

#Environment Variables
RABBIT_HOST = os.getenv("RABBIT_HOST", "rabbitmq")
QUEUE_NAME = os.getenv("QUEUE_NAME", "interpol_queue")

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

        # --- POLICY AYARI---
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
    image_url = db.Column(db.String(300))  # Thumbnail linkini tutacağız

    # Boy, kilo, göz rengi, suçlamalar, her şeyi bu torbaya atacağız.
    details = db.Column(JSONB)

    # Fotoğrafları yine ayrı tutabiliriz çünkü onlar liste ve zayıf varlık.
    photos = db.relationship('Photo', backref='owner', lazy=True, cascade="all, delete-orphan")

    def __repr__(self):
        return f'<Criminal {self.name} (ID: {self.entity_id})>'

# --- FOTOĞRAF TABLOSU ---
class Photo(db.Model):
    __tablename__ = 'photos'

    id = db.Column(db.Integer, primary_key=True)
    criminal_id = db.Column(db.Integer, db.ForeignKey('criminals.id'), nullable=False)
    url = db.Column(db.String(300))  # MinIO Linki
    picture_id = db.Column(db.String(50))  # Interpol'ün verdiği ID

    def __repr__(self):
        return f'<Photo {self.picture_id}>'


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


def process_criminal_detail_and_photos(criminal_db_obj, person_links):
    """
    1. Detay sayfasını çeker ve JSON olarak kaydeder.
    2. Resimleri indirir.
    """
    detail_href = person_links.get('self', {}).get('href')
    if not detail_href: return

    try:
        # --- A) DETAY VERİSİNİ ÇEK VE KAYDET (JSONB) ---
        resp = requests.get(detail_href, timeout=10, headers=headers)

        if resp.status_code == 200:
            data = resp.json()

            # Tek tek eyes, hair vs eşlemiyoruz. Hepsini 'details' kolonuna atıyoruz.
            criminal_db_obj.details = data

            # --- B) FOTOĞRAFLARI ÇEK ---
            images_link = data.get('_links', {}).get('images', {}).get('href')

            if images_link:
                print(f"📸 Fotoğraf sayfasına gidiliyor: {images_link}")

                # Fotoğraf endpoint'ine AYRI bir istek atıyoruz
                img_resp = requests.get(images_link, timeout=15, headers=headers)

                if img_resp.status_code == 200:
                    img_data = img_resp.json()

                    # Artık resim listesi burada!
                    embedded_images = img_data.get('_embedded', {}).get('images', [])

                    print(f"   -> {len(embedded_images)} adet fotoğraf bulundu.")

                    for img_item in embedded_images:
                        pic_id = img_item.get('picture_id')
                        img_href = img_item.get('_links', {}).get('self', {}).get('href')

                        if img_href and pic_id:
                            # MinIO'ya Yükle
                            minio_url = upload_image_to_minio(
                                image_url=img_href,
                                entity_id=criminal_db_obj.entity_id,
                                folder_type="others",
                                img_id_suffix=pic_id
                            )

                            if minio_url:
                                # DB Kontrol ve Kayıt
                                existing_photo = Photo.query.filter_by(picture_id=pic_id).first()
                                if not existing_photo:
                                    new_photo = Photo(
                                        owner=criminal_db_obj,
                                        url=minio_url,
                                        picture_id=pic_id
                                    )
                                    db.session.add(new_photo)
                                    # print(f"      + Foto Eklendi: {pic_id}")
    except Exception as e:
        print(f"Detay/Foto işleme hatası ({criminal_db_obj.entity_id}): {e}")


def upload_image_to_minio(image_url, entity_id, folder_type, img_id_suffix):
    """
    image_url: İndirilecek link
    entity_id: Suçlu ID (örn: 2026/3921)
    folder_type: 'thumbnail' veya 'others'
    img_id_suffix: picture_id (Dosya isminin sonuna eklenecek)
    """
    if not image_url or not image_url.startswith('http'):
        return None

    try:
        # ID içindeki slashları düzelt (2026/3921 -> 2026_3921)
        safe_entity_id = entity_id.replace('/', '_')

        # Dosya ismi formatı: {ENTITY_ID}_{PICTURE_ID}.jpg
        # Örnek: 2026_3921/others/2026_3921_63782631.jpg
        filename = f"{safe_entity_id}/{folder_type}/{safe_entity_id}_{img_id_suffix}.jpg"

        response = requests.get(image_url, timeout=10, headers=headers)
        if response.status_code == 200:
            img_data = BytesIO(response.content)
            length = len(response.content)

            minio_client.put_object(
                BUCKET_NAME,
                filename,
                img_data,
                length,
                content_type="image/jpeg"
            )
            return f"http://localhost:9000/{BUCKET_NAME}/{filename}"

    except Exception as e:
        print(f"Resim yükleme hatası ({folder_type} - {img_id_suffix}): {e}")

    return None


def consume_queue():
    print(' [*] Kuyruk işleme servisi başlatıldı (Polling Modu)...')

    while True:
        connection = None
        try:
            # 1. RabbitMQ'ya Bağlan
            connection = pika.BlockingConnection(pika.ConnectionParameters(RABBIT_HOST))
            channel = connection.channel()
            channel.queue_declare(queue=QUEUE_NAME)

            # 2. Kuyruktan tek bir mesaj iste (basic_get)
            # basic_consume yerine basic_get kullanıyoruz. Bu "bir tane ver ve sus" demektir.
            method_frame, header_frame, body = channel.basic_get(queue=QUEUE_NAME, auto_ack=True)

            if method_frame:
                # MESAJ VAR!
                print(f"📥 [Web Container] Yeni veri paketi alındı. İşleniyor...")

                # 3. KRİTİK ADIM: Veriyi aldık, RabbitMQ ile işimiz bitti.
                connection.close()
                connection = None  # Bağlantı değişkenini boşa çıkar

                # 4. Veriyi İşle (Offline Mod)
                data = json.loads(body)
                notices = data.get('_embedded', {}).get('notices', [])

                with app.app_context():
                    degisiklik_sayisi = 0

                    for person in notices:
                        try:
                            entity_id = person.get('entity_id')
                            name = f"{person.get('forename', '')} {person.get('name', '')}".strip()
                            raw_nationalities = str(person.get('nationalities', []))
                            nationalities = convert_to_country(raw_nationalities)
                            links = person.get('_links', {})
                            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                            existing = Criminal.query.filter_by(entity_id=entity_id).first()

                            if existing:
                                # --- GÜNCELLEME KONTROLÜ (JSONB Versiyonu) ---
                                degisiklik_raporu = []

                                # İsim ve Uyruk kontrolü aynı
                                if existing.name != name:
                                    degisiklik_raporu.append(f"İSİM DEĞİŞTİ")
                                    existing.name = name

                                if existing.nationalities != nationalities:
                                    degisiklik_raporu.append(f"UYRUK DEĞİŞTİ")
                                    existing.nationalities = nationalities

                                # Detay kontrolü için yine canlı veriye bakıyoruz
                                detail_href = links.get('self', {}).get('href')
                                if detail_href:
                                    try:
                                        resp = requests.get(detail_href, timeout=5, headers=headers)
                                        if resp.status_code == 200:
                                            live_data = resp.json()

                                            # JSON KARŞILAŞTIRMASI (Çok daha güçlü)
                                            # Veritabanındaki JSON ile Canlı JSON aynı mı?
                                            # (Not: Birebir eşitlik bazen timestamp yüzünden tutmayabilir,
                                            # sadece önemli alanları kıyaslamak daha garantidir ama şimdilik böyle de olur)

                                            # Örnek: Sadece suçlamalar değişmiş mi bakalım
                                            old_warrants = existing.details.get(
                                                'arrest_warrants') if existing.details else []
                                            new_warrants = live_data.get('arrest_warrants', [])

                                            if old_warrants != new_warrants:
                                                degisiklik_raporu.append("SUÇLAMALAR GÜNCELLENDİ")

                                            # Fiziksel özellikler değişmiş mi?
                                            if existing.details and existing.details.get(
                                                    'distinguishing_marks') != live_data.get('distinguishing_marks'):
                                                degisiklik_raporu.append("FİZİKSEL DETAY GÜNCELLENDİ")

                                            # Eğer güncelleme varsa, YENİ JSON'ı kaydet
                                            if len(degisiklik_raporu) > 0:
                                                existing.details = live_data  # Güncel veriyi bas

                                    except Exception as e:
                                        print(f"Kontrol hatası: {e}")

                                if len(degisiklik_raporu) > 0:
                                    existing.timestamp = now
                                    existing.status = "UPDATED"
                                    process_criminal_detail_and_photos(existing, links)  # Resimleri de tazele
                                    # ...

                            else:
                                # --- YENİ KAYIT ---
                                thumb_href = links.get('thumbnail', {}).get('href')
                                thumb_url = upload_image_to_minio(
                                    image_url=thumb_href,
                                    entity_id=entity_id,
                                    folder_type="thumbnail",
                                    img_id_suffix="profile"
                                )

                                new_criminal = Criminal(
                                    entity_id=entity_id,
                                    name=name,
                                    nationalities=nationalities,
                                    timestamp=now,
                                    alarm=False,
                                    status="NEW",
                                    image_url=thumb_url,
                                    details={}
                                )
                                db.session.add(new_criminal)
                                db.session.flush()

                                process_criminal_detail_and_photos(new_criminal, links)
                                degisiklik_sayisi += 1

                        except Exception as inner_e:
                            print(f"Veri işleme hatası ({person.get('entity_id')}): {inner_e}")

                    # Toplu Kayıt
                    if degisiklik_sayisi > 0:
                        db.session.commit()
                        print(f"💾 {degisiklik_sayisi} kayıt/güncelleme başarıyla işlendi.")

            else:
                # MESAJ YOKSA
                # Bağlantıyı kapat ve biraz uyu, işlemciyi yorma.
                if connection and not connection.is_closed:
                    connection.close()
                time.sleep(5)

        except Exception as e:
            print(f"⚠️ İşlem Döngüsü Hatası: {e}")
            # Hata durumunda bağlantı açık kaldıysa kapatmayı dene
            if connection and not connection.is_closed:
                try:
                    connection.close()
                except:
                    pass
            time.sleep(5)  # Hata alınca 5 saniye bekle tekrar dene


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
        if is_updated and difference_on_seconds < 60: #60 saniye içinde güncellendiyse alarm çalsın.
            criminal.alarm = True
        else:
            criminal.alarm = False
        criminal_list.append(criminal)
    return render_template('index_with_bootstrap.html', criminals=criminal_list)


# --- DETAY SAYFASI ROTASI ---
@app.route('/detail/<path:entity_id>') # 'path:' takısı her şeyi (slash dahil) tek string olarak alır.
def detail_page(entity_id):
    # ID'ye göre suçluyu bul, yoksa 404 hatası ver
    criminal = Criminal.query.filter_by(entity_id=entity_id).first_or_404()
    return render_template('detail.html', criminal=criminal)


@app.template_filter('dil_cevir')
def dil_cevir_filter(deger):
    """
    Interpol'den gelen kodu (FRE, ENG) pycountry ile adına çevirir.
    """
    if not deger:
        return "Not Known"

    codes = str(deger).replace("[", "").replace("]", "").replace("'", "").replace('"', "")
    codes = codes.split(',')
    languages = []

    for code in codes:
        code = code.strip() #Boşlukları ortadan kaldır.
        try:
            language = pycountry.languages.get(alpha_3=code)
            if language:
                languages.append(language.name)
            else:
                languages.append(code)
        except:
            languages.append(code)

    return ', '.join(languages)

@app.template_filter('ulke_cevir')
def ulke_cevir_filter(code):
    """
    Interpol'den gelen kodu (RU, US) pycountry ile adına çevirir.
    """
    return convert_to_country(code)


if __name__ == '__main__':

    with app.app_context():
        db.create_all()

    # Kuyruk dinleyicisini ayrı bir "Thread" (iş parçacığı) olarak başlat
    # Bu sayede Flask sunucusu çalışırken arka planda veri kaydı devam etsin.
    threading.Thread(target=consume_queue, daemon=True).start()

    # Web sunucusunu başlat
    app.run(host='0.0.0.0', port=5000)