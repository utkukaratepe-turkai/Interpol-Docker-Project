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
import time

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

    # İLİŞKİ: Bir suçlunun BİR detay kaydı olur (uselist=False -> Bire-Bir İlişki)
    # Bu sayede 'criminal.detail' diyerek diğer tablodaki veriye ulaşacağız.
    detail = db.relationship('CriminalDetail', backref='owner', uselist=False, cascade="all, delete-orphan")
    photos = db.relationship('Photo', backref='owner', lazy=True, cascade="all, delete-orphan")

    def __repr__(self):
        return f'<Criminal {self.name} (ID: {self.entity_id})>'


class CriminalDetail(db.Model):
    __tablename__ = 'criminal_details'

    id = db.Column(db.Integer, primary_key=True)
    criminal_id = db.Column(db.Integer, db.ForeignKey('criminals.id'), unique=True, nullable=False)

    # -- JSON'dan Gelen Ekstra Veriler --
    birth_date = db.Column(db.String(50))  # date_of_birth
    birth_place = db.Column(db.String(100))  # place_of_birth
    birth_country = db.Column(db.String(10))  # country_of_birth_id (TN, FR vb.)

    gender = db.Column(db.String(10))  # sex_id (M/F)
    height = db.Column(db.Float)  # height
    weight = db.Column(db.Float)  # weight
    eyes = db.Column(db.String(50))  # eyes_colors_id
    hair = db.Column(db.String(50))  # hairs_id

    languages = db.Column(db.String(200))  # languages_spoken_ids (Liste stringe çevrilecek)
    marks = db.Column(db.Text)  # distinguishing_marks (Uzun metin olabilir)

    # Suçlama Bilgileri (Arrest Warrants içinden)
    warrant_country = db.Column(db.String(50))  # issuing_country_id
    charges = db.Column(db.Text)  # charge
    charge_translation = db.Column(db.Text) # charge_translation

    def __repr__(self):
        return f'<Detail {self.criminal_id}>'


# --- FOTOĞRAF TABLOSU (GÜNCELLENDİ) ---
class Photo(db.Model):
    __tablename__ = 'photos'

    id = db.Column(db.Integer, primary_key=True)
    criminal_id = db.Column(db.Integer, db.ForeignKey('criminals.id'), nullable=False)
    url = db.Column(db.String(300))  # MinIO Linki
    picture_id = db.Column(db.String(50))  # Interpol'ün verdiği ID (Örn: 63782631)

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
    1. Detay sayfasını çeker (Kişisel Bilgiler)
    2. O sayfanın içindeki 'images' linkini bulur
    3. O linke gidip fotoğraf galerisini çeker (MinIO + DB)
    """
    # 1. ADIM: DETAY SAYFASINA GİT (Kişisel Bilgiler İçin)
    detail_href = person_links.get('self', {}).get('href')
    if not detail_href: return

    try:
        # --- Profil Detaylarını Çek ---
        resp = requests.get(detail_href, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200: return

        data = resp.json()

        # --- A) DETAY TABLOSUNA KAYIT ---
        # (Bu kısım aynı kalıyor, kişisel bilgileri kaydediyoruz)
        langs = data.get('languages_spoken_ids', [])
        langs_str = ", ".join(langs) if langs else None

        warrants = data.get('arrest_warrants', [])

        charge_list=[]
        charge_trans_list=[]
        issuing_countries=set()

        for w in warrants:
            if w.get('charge'):
                charge_list.append(w.get('charge'))

            if w.get('charge_translation'):
                charge_trans_list.append(w.get('charge_translation'))

            if w.get('issuing_country_id'):
                issuing_countries.add(w.get('issuing_country_id'))

        # Listeleri string'e çevirip veritabanına hazır hale getiriyoruz
        charge = "\n".join(charge_list)
        charge_translation = "\n".join(charge_trans_list)
        issuing_country_id = ", ".join(issuing_countries)

        # Eğer detay daha önce yoksa ekle
        if not criminal_db_obj.detail:
            detail = CriminalDetail(
                owner=criminal_db_obj,
                birth_date=data.get('date_of_birth'),
                birth_place=data.get('place_of_birth'),
                birth_country=data.get('country_of_birth_id'),
                gender=data.get('sex_id'),
                height=data.get('height'),
                weight=data.get('weight'),
                eyes=data.get('eyes_colors_id'),
                hair=data.get('hairs_id'),
                languages=langs_str,
                marks=data.get('distinguishing_marks'),
                warrant_country=issuing_country_id,
                charges=charge,
                charge_translation=charge_translation
            )
            db.session.add(detail)

        # --- B) FOTOĞRAF GALERİSİNE GİT (DÜZELTME BURADA) ---
        # Ana detay JSON'ının içinde '_links' -> 'images' linkini alıyoruz.
        images_link = data.get('_links', {}).get('images', {}).get('href')

        if images_link:
            print(f"📸 Fotoğraf sayfasına gidiliyor: {images_link}")

            # Fotoğraf endpoint'ine AYRI bir istek atıyoruz
            img_resp = requests.get(images_link, timeout=15, headers={"User-Agent": "Mozilla/5.0"})

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

        response = requests.get(image_url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
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
                                # --- GÜNCELLEME KONTROLÜ ---
                                degisiklik_raporu = []

                                # 1. İsim ve Uyruk Kontrolü (Klasik Kontrol)
                                if existing.name != name:
                                    degisiklik_raporu.append(f"İSİM: '{existing.name}' -> '{name}'")
                                    existing.name = name

                                if existing.nationalities != nationalities:
                                    degisiklik_raporu.append(f"UYRUK: '{existing.nationalities}' -> '{nationalities}'")
                                    existing.nationalities = nationalities

                                # 2. DETAY KONTROLÜ (YENİ: Suçlama ve Fiziksel Özellikler)
                                # Detay değişmiş mi diye anlamak için güncel veriyi çekip bakıyoruz.
                                detail_href = links.get('self', {}).get('href')

                                # Sadece detay sayfası linki varsa ve veritabanında eski detay varsa kıyasla
                                if detail_href and existing.detail:
                                    try:
                                        # Hızlıca güncel veriyi çek (Timeout kısa tutuldu)
                                        resp = requests.get(detail_href, timeout=5,
                                                            headers={"User-Agent": "Mozilla/5.0"})
                                        if resp.status_code == 200:
                                            live_data = resp.json()

                                            # A) Suçlama (Charge) Değişmiş mi?
                                            live_warrants = live_data.get('arrest_warrants', [])
                                            live_charges_list = [w.get('charge') for w in live_warrants if
                                                                 w.get('charge')]
                                            live_charges_str = "\n".join(live_charges_list)

                                            # Veritabanındaki eski suçlama (None ise boş string yap)
                                            db_charges = existing.detail.charges or ""

                                            if live_charges_str != db_charges:
                                                degisiklik_raporu.append("SUÇLAMA GÜNCELLENDİ")

                                            # B) Ayırt Edici İşaretler (Marks) Değişmiş mi?
                                            live_marks = live_data.get('distinguishing_marks') or ""
                                            db_marks = existing.detail.marks or ""

                                            if live_marks != db_marks:
                                                degisiklik_raporu.append("FİZİKSEL DETAY GÜNCELLENDİ")

                                    except Exception as check_e:
                                        # Detay kontrolü hata verirse akışı bozma, sadece logla
                                        print(f"⚠️ Detay kontrol hatası ({entity_id}): {check_e}")

                                # --- EĞER HERHANGİ BİR DEĞİŞİKLİK VARSA ---
                                if len(degisiklik_raporu) > 0:
                                    existing.timestamp = now
                                    existing.status = "UPDATED"
                                    existing.alarm = False

                                    # Eski detayı sil (Çünkü process fonksiyonu yenisini oluşturacak)
                                    if existing.detail:
                                        db.session.delete(existing.detail)
                                        db.session.flush()

                                    # Tüm yeni verileri (Detay + Fotoğraflar) indir ve kaydet
                                    process_criminal_detail_and_photos(existing, links)

                                    degisiklik_sayisi += 1
                                    print(f"♻️ GÜNCELLEME [{entity_id}]: {' | '.join(degisiklik_raporu)}")

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
                                    image_url=thumb_url
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
        if is_updated and difference_on_seconds < 30: #60 saniye içinde güncellendiyse alarm çalsın.
            criminal.alarm = True
        else:
            criminal.alarm = False
        criminal_list.append(criminal)
    return render_template('index_with_bootstrap.html', criminals=criminal_list)


# --- JINJA2 ÖZEL FİLTRE (Veri yoksa 'BİLİNMİYOR' yazar) ---
@app.template_filter('bilinmiyor')
def bilinmiyor_filter(value):
    if value is None or value == "" or value == "None" or value == []:
        return "BİLİNMİYOR"
    return value

# --- DETAY SAYFASI ROTASI ---
@app.route('/detail/<path:entity_id>') # 'path:' takısı her şeyi (slash dahil) tek string olarak alır.
def detail_page(entity_id):
    # ID'ye göre suçluyu bul, yoksa 404 hatası ver
    criminal = Criminal.query.filter_by(entity_id=entity_id).first_or_404()
    return render_template('detail.html', criminal=criminal)

if __name__ == '__main__':

    with app.app_context():
        db.create_all()

    # Kuyruk dinleyicisini ayrı bir "Thread" (iş parçacığı) olarak başlat
    # Bu sayede Flask sunucusu çalışırken arka planda veri kaydı devam etsin.
    threading.Thread(target=consume_queue, daemon=True).start()

    # Web sunucusunu başlat
    app.run(host='0.0.0.0', port=5000)