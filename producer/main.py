import json
import pika
import requests
import time
import random
import os
import pycountry

# RabbitMQ Ayarları
RABBIT_HOST = os.getenv("RABBIT_HOST", "rabbitmq")
QUEUE_NAME = os.getenv("QUEUE_NAME", "interpol_queue")
SLEEP_TIME = int(os.getenv("SLEEP_TIME", 300))  # Tarama uzun süreceği için bekleme süresini artırabilirsin

BASE_URL = "https://ws-public.interpol.int/notices/v1/red"

# Tüm ülkeleri al
COUNTRIES = [country.alpha_2 for country in pycountry.countries]

# YAŞ FİLTRESİ LİSTESİ
# Her ülkeyi bu yaş aralıklarına bölerek tarayacağız.
# Bu sayede "Rusya" gibi kalabalık ülkelerde 160 sınırına takılmadan herkesi alabileceğiz.
AGE_RANGES = [
    (18, 24), (25, 29), (30, 34), (35, 39),
    (40, 44), (45, 49), (50, 54), (55, 59),
    (60, 64), (65, 69), (70, 79), (80, 99)
]


def get_and_post_interpol_data():
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    try:
        connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBIT_HOST))
        channel = connection.channel()
        channel.queue_declare(queue=QUEUE_NAME)

        toplam_gonderilen = 0
        print(f"🌍 DERİN TARAMA BAŞLATILIYOR (Ülke + Yaş Filtresi)...")

        # Ülkeleri karıştır (Sürekli A harfinden başlamasın)
        random.shuffle(COUNTRIES)

        for country_code in COUNTRIES:
            # Her ülke için yaş aralıklarını dön
            for (age_min, age_max) in AGE_RANGES:
                try:
                    params = {
                        'nationality': country_code,
                        'ageMin': age_min,
                        'ageMax': age_max,
                        'resultPerPage': 160  # O yaş aralığının max 160'ını iste
                    }

                    response = requests.get(BASE_URL, params=params, headers=headers)

                    if response.status_code == 200:
                        interpol_data = response.json()
                        notices = interpol_data.get("_embedded", {}).get("notices", [])
                        count = len(notices)

                        if count > 0:
                            # --- TEST KODU: İsim Değişikliği Simülasyonu ---
                            # (Alarm sistemini test etmek için ilk veriyi değiştiriyoruz)
                            first_person = notices[0]
                            original_name = first_person['name']
                            num = random.randint(1, 1000)
                            # Sadece %10 ihtimalle isim değiştir ki veritabanı sürekli "UPDATED" dolmasın
                            if random.random() < 0.1:
                                first_person['name'] = f"{original_name} (TEST-{num})"
                            # -----------------------------------------------

                            message_body = json.dumps(interpol_data)
                            channel.basic_publish(exchange="", routing_key=QUEUE_NAME, body=message_body)

                            toplam_gonderilen += count
                            # Hangi aralıktan veri geldiğini görelim
                            print(f"✅ {country_code} [{age_min}-{age_max} Yaş]: {count} kayıt alındı.")

                    elif response.status_code == 429:
                        print(f"⚠️ Hız Limiti (Rate Limit)! 5 saniye bekleniyor...")
                        time.sleep(5)

                    # Interpol sunucularını yormamak ve banlanmamak için kısa mola
                    # 12 yaş aralığı x 250 ülke = 3000 istek demektir. Hızlı gitmemeliyiz.
                    time.sleep(0.2)

                except Exception as e_inner:
                    print(f"Hata ({country_code}): {e_inner}")

        connection.close()
        print(f"🏁 Tarama tamamlandı. Toplam {toplam_gonderilen} veri işlendi.")

    except Exception as e:
        print(f"Genel Bağlantı Hatası: {e}")


if __name__ == "__main__":
    print(f"🚀 Producer Başlatıldı. Hedef: Tüm Dünya (Yaş Filtreli).")
    while True:
        get_and_post_interpol_data()
        print(f"💤 Döngü bitti. {SLEEP_TIME} saniye bekleniyor...")
        time.sleep(SLEEP_TIME)