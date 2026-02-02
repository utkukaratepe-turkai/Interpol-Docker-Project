from datetime import datetime, timezone
from flask import Blueprint, render_template
from models.criminal import Criminal
from sqlalchemy.orm import joinedload
from extensions import db
main_bp = Blueprint('main', __name__)

# --- WEB SİTESİ ROTALARI ---
@main_bp.route('/')
def index():
    criminals = Criminal.query.options(joinedload(Criminal.detail)).order_by(Criminal.id.desc()).all()

    now = datetime.now(timezone.utc)

    for criminal in criminals:
        # Eğer timestamp DateTime ise doğrudan fark alabiliriz
        if criminal.timestamp:
            diff = (now - criminal.timestamp).total_seconds()

            # Eğer son 60 sn içinde güncellendiyse VEYA veritabanında alarm zaten set edilmişse
            if criminal.status == 'UPDATED' and diff < 60:
                criminal.alarm = True
            else:
                criminal.alarm = False

    return render_template('index_with_bootstrap.html', criminals=criminals)


@main_bp.route('/detail/<path:entity_id>')
def detail_page(entity_id):
    stmt = db.select(Criminal).options(joinedload(Criminal.detail)).where(Criminal.entity_id == entity_id)
    criminal = db.one_or_404(stmt)
    if criminal.alarm:
        criminal.alarm = False
        db.session.commit()
    return render_template('detail.html', criminal=criminal)