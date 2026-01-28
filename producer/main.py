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
SLEEP_TIME = int(os.getenv("SLEEP_TIME", 300))

BASE_URL = "https://ws-public.interpol.int/notices/v1/red"

# Tüm ülkeleri al
COUNTRIES = [country.alpha_2 for country in pycountry.countries]

def get_and_post_interpol_data():
    headers={"User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Mobile Safari/537.36"}

    try:
        connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBIT_HOST))
        channel = connection.channel()
        channel.queue_declare(queue=QUEUE_NAME)

        toplam_gonderilen = 0
        print(f"🌍 HIZLI TARAMA BAŞLATILIYOR (Sadece Uyruk Filtresi)...")

        # Ülkeleri karıştır (Sürekli A harfinden başlamasın)
        random.shuffle(COUNTRIES)

        for country_code in COUNTRIES:
            try:
                # Yaş filtresi kaldırıldı, sadece uyruk gönderiyoruz
                params = {
                    'nationality': country_code,
                    'resultPerPage': 160  # API'nin izin verdiği maksimum sayı
                }

                response = requests.get(BASE_URL, params=params, headers=headers)

                if response.status_code == 200:
                    interpol_data = response.json()
                    notices = interpol_data.get("_embedded", {}).get("notices", [])
                    count = len(notices)

                    if count > 0:
                        message_body = json.dumps(interpol_data)
                        channel.basic_publish(exchange="", routing_key=QUEUE_NAME, body=message_body)

                        toplam_gonderilen += count
                        print(f"✅ {country_code}: {count} kayıt alındı.")

                elif response.status_code == 429:
                    print(f"⚠️ Hız Limiti (Rate Limit)! 5 saniye bekleniyor...")
                    time.sleep(5)

                # Interpol sunucularını yormamak ve banlanmamak için kısa mola
                time.sleep(0.2)

            except Exception as e_inner:
                print(f"Hata ({country_code}): {e_inner}")

        connection.close()
        print(f"🏁 Tarama tamamlandı. Toplam {toplam_gonderilen} veri işlendi.")

    except Exception as e:
        print(f"Genel Bağlantı Hatası: {e}")


if __name__ == "__main__":
    print(f"🚀 Producer Başlatıldı. Hedef: Tüm Dünya (Sadece Uyruk).")
    while True:
        get_and_post_interpol_data()
        print(f"💤 Döngü bitti. {SLEEP_TIME} saniye bekleniyor...")
        time.sleep(SLEEP_TIME)