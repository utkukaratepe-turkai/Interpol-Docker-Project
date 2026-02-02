import json
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from minio import Minio
import os

# SQLAlchemy ve Migrate nesnelerini burada başlatıyoruz
db = SQLAlchemy()
migrate = Migrate()

# Minio Yapılandırması
MINIO_ENDPOINT = "minio:9000"
MINIO_ACCESS = "minioadmin"
MINIO_SECRET = "minioadmin"
BUCKET_NAME = "interpol-criminal-images"
MINIO_PUBLIC_URL = "http://localhost:9000"

minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS,
    secret_key=MINIO_SECRET,
    secure=False
)

def init_minio():
    """Uygulama başladığında kovanın varlığını kontrol eder ve oluşturur."""
    try:
        if not minio_client.bucket_exists(BUCKET_NAME):
            minio_client.make_bucket(BUCKET_NAME)

            # Public erişim izni (Resimlerin tarayıcıda görünebilmesi için)
            policy = {
                "Version": "2012-10-17",
                "Statement": [{
                    "Effect": "Allow",
                    "Principal": {"AWS": ["*"]},
                    "Action": ["s3:GetObject"],
                    "Resource": [f"arn:aws:s3:::{BUCKET_NAME}/*"]
                }]
            }
            minio_client.set_bucket_policy(BUCKET_NAME, json.dumps(policy))
            print(f"✅ MinIO kovanı '{BUCKET_NAME}' oluşturuldu ve yetkilendirildi.")
    except Exception as e:
        print(f"⚠️ MinIO Başlatma Hatası: {e}")