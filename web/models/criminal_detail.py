import enum
from extensions import db
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Integer, Float, String, ForeignKey, ARRAY, Text
from sqlalchemy.dialects.postgresql import JSONB, ENUM as PG_ENUM
from typing import Optional, List


# Cinsiyet için Enum tanımı
class SexEnum(enum.Enum):
    M = "Male"
    F = "Female"
    U = "Unknown"


class CriminalDetail(db.Model):
    __tablename__ = 'criminal_details'

    criminal_id: Mapped[int] = mapped_column(Integer, ForeignKey('criminals.id', ondelete="CASCADE"), primary_key=True)

    # Enum kullanımı (PostgreSQL tarafında sex_types adında bir tip oluşturur)
    sex_id: Mapped[Optional[SexEnum]] = mapped_column(
        PG_ENUM(SexEnum, name="sex_types", create_type=True),
        nullable=True
    )

    # detail.json'daki diğer fiziksel özellikler
    height: Mapped[Optional[float]] = mapped_column(Float)  # Boy (Örn: 1.85)
    weight: Mapped[Optional[float]] = mapped_column(Float)  # Kilo (Örn: 187)
    eyes_colors_id: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String))  # ["BLU"]
    hairs_id: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String))

    # Kimlik ve Doğum Bilgileri
    place_of_birth: Mapped[Optional[str]] = mapped_column(String(200))
    country_of_birth_id: Mapped[Optional[str]] = mapped_column(String(10))
    languages_spoken_ids: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String))  # ["TUR", "DAN"]
    distinguishing_marks: Mapped[Optional[str]] = mapped_column(Text)

    # JSON Verileri (Hukuki detaylar ve yedekleme)
    arrest_warrants: Mapped[list] = mapped_column(JSONB, default=list)  # Suç maddeleri
    full_raw_json: Mapped[dict] = mapped_column(JSONB)  # Tüm JSON içeriği

    master: Mapped["Criminal"] = relationship(back_populates="detail")