from flask_wtf import FlaskForm
from wtforms import StringField, FloatField, IntegerField, SelectField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional, NumberRange

class UnifiedCriminalForm(FlaskForm):
    # Criminal Tablosu Alanları
    name = StringField('İsim', validators=[DataRequired(), Length(max=200)])
    forename = StringField('Ön İsim', validators=[Optional(), Length(max=200)])
    status = SelectField('Kayıt Durumu', choices=[('NEW', 'Yeni'), ('UPDATED', 'Güncellendi')])
    
    # CriminalDetail Tablosu Alanları
    height = FloatField('Boy (Metre)', validators=[Optional(), NumberRange(min=0.5, max=2.5)])
    weight = FloatField('Kilo (kg)', validators=[Optional(), NumberRange(min=10, max=300)])
    sex_id = SelectField('Cinsiyet', choices=[('M', 'Erkek'), ('F', 'Kadın'), ('U', 'Bilinmiyor')])
    distinguishing_marks = TextAreaField('Ayırt Edici İşaretler', validators=[Optional(), Length(max=1000)])
    
    submit = SubmitField('Tüm Bilgileri Güncelle')