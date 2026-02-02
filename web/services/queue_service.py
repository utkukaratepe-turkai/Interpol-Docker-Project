import pika
import json
import time
import requests
from io import BytesIO
from datetime import datetime
from extensions import db, minio_client, BUCKET_NAME
from models.criminal import Criminal
from models.criminal_detail import CriminalDetail, SexEnum
from models.photo import Photo

# Sabitler
RABBIT_HOST = "rabbitmq"
QUEUE_NAME = "interpol_queue"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36..."}


def upload_image_to_minio(image_url, entity_id, folder_type, img_id_suffix):
    """Resmi indirir ve MinIO'ya yükleyerek yolunu döner."""
    if not image_url or not image_url.startswith('http'):
        return None
    try:
        safe_id = entity_id.replace('/', '_')
        filename = f"{safe_id}/{folder_type}/{safe_id}_{img_id_suffix}.jpg"

        resp = requests.get(image_url, timeout=10, headers=HEADERS)
        if resp.status_code == 200:
            content = resp.content
            minio_client.put_object(
                BUCKET_NAME, filename, BytesIO(content), len(content), content_type="image/jpeg"
            )
            return filename
    except Exception as e:
        print(f"❌ Resim yükleme hatası: {e}")
    return None


def process_criminal_detail_and_photos(criminal_obj, links):
    """Interpol detay sayfasını (detail.json) çeker ve modelleri doldurur."""
    detail_href = links.get('self', {}).get('href')
    if not detail_href: return

    try:
        resp = requests.get(detail_href, timeout=10, headers=HEADERS)
        if resp.status_code == 200:
            data = resp.json()

            # Detay kaydı yoksa oluştur
            if not criminal_obj.detail:
                criminal_obj.detail = CriminalDetail(criminal_id=criminal_obj.id)

            # Cinsiyet Enum Eşlemesi
            sex_val = data.get('sex_id')
            criminal_obj.detail.sex_id = SexEnum[sex_val] if sex_val in SexEnum.__members__ else SexEnum.U

            # Fiziksel ve Kimlik Bilgileri
            criminal_obj.detail.height = float(data.get('height', 0)) if data.get('height') else None
            criminal_obj.detail.weight = float(data.get('weight', 0)) if data.get('weight') else None
            criminal_obj.detail.eyes_colors_id = data.get('eyes_colors_id')
            criminal_obj.detail.hairs_id = data.get('hairs_id')
            criminal_obj.detail.place_of_birth = data.get('place_of_birth')
            criminal_obj.detail.country_of_birth_id = data.get('country_of_birth_id')
            criminal_obj.detail.languages_spoken_ids = data.get('languages_spoken_ids')
            criminal_obj.detail.distinguishing_marks = data.get('distinguishing_marks')

            # Hukuki Detaylar ve Ham Yedek
            criminal_obj.detail.arrest_warrants = data.get('arrest_warrants', [])
            criminal_obj.detail.full_raw_json = data

            # Diğer Fotoğrafları İşle
            images_link = data.get('_links', {}).get('images', {}).get('href')
            if images_link:
                img_resp = requests.get(images_link, timeout=10, headers=HEADERS)
                if img_resp.status_code == 200:
                    for img_item in img_resp.json().get('_embedded', {}).get('images', []):
                        pic_id = str(img_item.get('picture_id'))
                        # Fotoğraf daha önce kaydedilmemişse indir
                        if not any(p.picture_id == pic_id for p in criminal_obj.photos):
                            path = upload_image_to_minio(img_item['_links']['self']['href'],
                                                         criminal_obj.entity_id, "others", pic_id)
                            if path:
                                criminal_obj.photos.append(Photo(image_path=path, picture_id=pic_id))
    except Exception as e:
        print(f"❌ Detay işleme hatası: {e}")


def consume_queue(app):
    """RabbitMQ Polling Modu: Bir mesaj al, bağlantıyı kapat, işle."""
    print(' [*] Kuyruk işleme servisi başlatıldı (Polling Modu)...')

    while True:
        connection = None
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters(RABBIT_HOST))
            channel = connection.channel()
            channel.queue_declare(queue=QUEUE_NAME)

            # Kuyruktan tek bir mesaj iste (basic_get)
            method_frame, _, body = channel.basic_get(queue=QUEUE_NAME, auto_ack=True)

            if method_frame:
                print(f"📥 [Web Container] Veri paketi alındı. RabbitMQ bağlantısı kapatılıyor...")
                connection.close()  # İşlem uzun süreceği için bağlantıyı hemen kapatıyoruz
                connection = None

                data = json.loads(body)
                notices = data.get('_embedded', {}).get('notices', [])

                with app.app_context():
                    degisiklik_sayisi = 0
                    for person in notices:
                        try:
                            entity_id = person.get('entity_id')
                            name = f"{person.get('forename', '')} {person.get('name', '')}".strip()
                            nationalities = person.get('nationalities', [])
                            links = person.get('_links', {})

                            existing = Criminal.query.filter_by(entity_id=entity_id).first()

                            if existing:
                                # --- GÜNCELLEME KONTROLÜ ---
                                changed = False
                                if existing.name != name:
                                    existing.name = name
                                    changed = True

                                if existing.nationalities != nationalities:
                                    existing.nationalities = nationalities
                                    changed = True

                                if changed:
                                    existing.status = "UPDATED"
                                    process_criminal_detail_and_photos(existing, links)
                                    degisiklik_sayisi += 1
                            else:
                                # --- YENİ KAYIT ---
                                thumb_href = links.get('thumbnail', {}).get('href')
                                thumb_path = upload_image_to_minio(thumb_href, entity_id, "thumbnail", "profile")

                                new_criminal = Criminal(
                                    entity_id=entity_id,
                                    name=name,
                                    forename=person.get('forename'),
                                    date_of_birth=person.get('date_of_birth'),  # main.json'dan
                                    nationalities=nationalities,
                                    thumbnail_path=thumb_path,
                                    status="NEW",
                                    alarm=True
                                )
                                db.session.add(new_criminal)
                                db.session.flush()  # ID almak için

                                process_criminal_detail_and_photos(new_criminal, links)
                                degisiklik_sayisi += 1

                        except Exception as inner_e:
                            print(f"❌ Veri hatası ({entity_id}): {inner_e}")

                    if degisiklik_sayisi > 0:
                        db.session.commit()
                        print(f"💾 {degisiklik_sayisi} işlem tamamlandı.")
            else:
                if connection: connection.close()
                time.sleep(5)  # Mesaj yoksa bekle

        except Exception as e:
            print(f"⚠️ Döngü hatası: {e}")
            if connection and not connection.is_closed:
                try:
                    connection.close()
                except:
                    pass
            time.sleep(5)