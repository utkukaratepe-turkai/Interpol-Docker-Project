import json
import pika
import requests
import time
import random
import os

API_URL = os.getenv("API_URL", "https://ws-public.interpol.int/notices/v1/red?resultPerPage=160&page=1")
RABBIT_HOST = os.getenv("RABBIT_HOST", "rabbitmq")
QUEUE_NAME = os.getenv("QUEUE_NAME", "interpol_queue")
SLEEP_TIME = int(os.getenv("SLEEP_TIME", 60))

def get_and_post_interpol_data():
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        response = requests.get(API_URL, headers=headers)
        if response.status_code == 200:
            interpol_data = response.json()
            kisi_sayisi = len(interpol_data["_embedded"]["notices"])
            first_person = interpol_data["_embedded"]["notices"][0]
            num = random.randint(1, 1000)
            original_name = first_person['name']
            first_person['name'] = f"{original_name}(TEST-{num})"
            print(f"{original_name} ismi {first_person['name']} olarak değiştirildi)")
        connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBIT_HOST))
        channel = connection.channel()
        channel.queue_declare(queue=QUEUE_NAME)
        message_body = json.dumps(interpol_data)
        channel.basic_publish(exchange="", routing_key=QUEUE_NAME, body=message_body)
        print(f"{kisi_sayisi} kişi verisi kuyruğa eklendi.")
        connection.close()
    except Exception as e:
        print(f"Hata oluştu {e}")

if __name__ == "__main__":
    print("Container A başlatıldı periyodik veri çekilecek.")
    while True :
        get_and_post_interpol_data()
        time.sleep(SLEEP_TIME)

