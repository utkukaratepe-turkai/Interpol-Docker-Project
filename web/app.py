import os
from flask import Flask
from extensions import db, migrate, init_minio
from models.criminal import Criminal
from models.criminal_detail import CriminalDetail
from models.photo import Photo
from routes.main import main_bp
from utils.filters import init_filters
import threading
from services.queue_service import consume_queue, start_sweeper

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://interpol_user:gizlisifre123@db:5432/interpol_db'
SECRET_KEY = os.getenv('SECRET_KEY', 'default_secret_key')

# Tüm modelleri bir listede toplamak, hem "kullanılmıyor" uyarısını siler 
# hem de Flask'ın hepsini tek seferde görmesini sağlar.
__all__ = ["Criminal", "CriminalDetail", "Photo"]

# Nesneleri uygulamaya bağla
db.init_app(app)
migrate.init_app(app, db)
init_filters(app)

# Blueprint'leri kaydet
app.register_blueprint(main_bp)
app.config['SECRET_KEY'] = SECRET_KEY

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        init_minio()

    threading.Thread(target=consume_queue, args=(app,), daemon=True).start()
    start_sweeper(app)
    app.run(host='0.0.0.0', port=5000, debug=True)