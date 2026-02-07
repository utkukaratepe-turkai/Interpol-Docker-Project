from datetime import datetime, timezone
from flask import Blueprint, render_template, request, flash, redirect, url_for
from models.criminal import Criminal
from models.criminal_detail import CriminalDetail
from models.forms import UnifiedCriminalForm
from sqlalchemy.orm import joinedload
from extensions import db
from flask import request
import time

main_bp = Blueprint('main', __name__)

# --- WEB SİTESİ ROTALARI ---
@main_bp.route('/')
def index():
    criminals = Criminal.query.options(joinedload(Criminal.detail)).order_by(Criminal.id.desc()).all()
    return render_template('index_with_bootstrap.html', criminals=criminals)

@main_bp.route('/detail/<path:entity_id>')
def detail_page(entity_id):
    stmt = db.select(Criminal).options(joinedload(Criminal.detail)).where(Criminal.entity_id == entity_id)
    criminal = db.one_or_404(stmt)
    return render_template('detail.html', criminal=criminal)


@main_bp.route('/delete/<path:entity_id>', methods=['POST'])
def delete_criminal(entity_id):
    stmt = db.select(Criminal).where(Criminal.entity_id == entity_id)
    criminal = db.one_or_404(stmt)
    try:
        db.session.delete(criminal)
        db.session.commit()
        flash('Kayıt başarıyla silindi.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Silme sırasında hata oluştu: {}'.format(e), 'danger')
    return redirect(url_for('main.index'))

@main_bp.route('/edit_detail/<path:entity_id>', methods=['GET', 'POST'])
def edit_criminal(entity_id):
    stmt = db.select(Criminal).options(joinedload(Criminal.detail)).where(Criminal.entity_id == entity_id)
    criminal = db.one_or_404(stmt)

    # Initialize form with model data where possible
    form = UnifiedCriminalForm(obj=criminal)

    # Populate nested/detail fields on GET (if not auto-populated)
    if request.method == 'GET':
        form.name.data = criminal.name
        form.forename.data = criminal.forename
        form.status.data = criminal.status.name if criminal.status else 'NEW'
        if criminal.detail:
            form.height.data = criminal.detail.height
            form.weight.data = criminal.detail.weight
            form.sex_id.data = criminal.detail.sex_id
            form.distinguishing_marks.data = criminal.detail.distinguishing_marks

    # Handle submission
    if form.validate_on_submit():
        try:
            criminal.name = form.name.data
            criminal.forename = form.forename.data
            criminal.status = form.status.data

            if not criminal.detail:
                criminal.detail = CriminalDetail()
            criminal.detail.height = form.height.data
            criminal.detail.weight = form.weight.data
            criminal.detail.sex_id = form.sex_id.data
            criminal.detail.distinguishing_marks = form.distinguishing_marks.data

            db.session.commit()
            flash('Kayıt başarıyla kaydedildi.', 'success')
            return redirect(url_for('main.detail_page', entity_id=criminal.entity_id))
        except Exception as e:
            db.session.rollback()
            flash('Kaydetme sırasında hata oluştu: {}'.format(e), 'danger')

    return render_template('edit_detail.html', criminal=criminal, form=form)