from extensions import db
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import String, Integer, Boolean, DateTime, func, ARRAY, Date
from typing import List, Optional
from datetime import datetime, timezone
import enum
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM

class CriminalStatus(enum.Enum):
    NEW = "NEW"
    UPDATED = "UPDATED"

class Criminal(db.Model):
    __tablename__ = 'criminals'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    forename: Mapped[Optional[str]] = mapped_column(String(200))
    date_of_birth: Mapped[Optional[datetime.date]] = mapped_column(Date)  #Eğer date tam ise burada tutacak yoksa birth_year'da tutacak.
    birth_year: Mapped[Optional[int]] = mapped_column(Integer, index=True) # Yeni kolon: Sadece yılı tutacak (Örn: 1966)
    nationalities: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String)) # ["IN", "TR"] gibi
    thumbnail_path: Mapped[Optional[str]] = mapped_column(String(300))
    status: Mapped[CriminalStatus] = mapped_column(
        PG_ENUM(CriminalStatus, name="criminal_status_types", create_type=True),
        default=CriminalStatus.NEW,
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    # İlişkiler
    detail: Mapped["CriminalDetail"] = relationship(back_populates="master", uselist=False, cascade="all, delete-orphan")
    photos: Mapped[List["Photo"]] = relationship(back_populates="owner", cascade="all, delete-orphan")

    @property
    def image_url(self):
        from extensions import MINIO_PUBLIC_URL, BUCKET_NAME
        if self.thumbnail_path:
            return f"{MINIO_PUBLIC_URL}/{BUCKET_NAME}/{self.thumbnail_path}"
        return None

    @property
    def is_alarm_active(self):
        #Eğer criminal "UPDATED" ise ve güncelleme üzerinden 60 saniye geçmemişse alarm aktif olsun
        if self.status == CriminalStatus.UPDATED and self.updated_at:
            return (datetime.now(timezone.utc) - self.updated_at).total_seconds() <= 60
        return False

    __table_args__ = (
        db.Index('idx_name_forename', 'name', 'forename'),  # İki kolonu birleştiren tek indeks
    )

