from extensions import db
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import String, Integer, Boolean, DateTime, func, ARRAY
from typing import List, Optional
from datetime import datetime

class Criminal(db.Model):
    __tablename__ = 'criminals'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    forename: Mapped[Optional[str]] = mapped_column(String(200))
    date_of_birth: Mapped[Optional[str]] = mapped_column(String(50)) # main.json'dan geliyor
    nationalities: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String)) # ["IN", "TR"] gibi
    thumbnail_path: Mapped[Optional[str]] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(50), default="NEW")
    alarm: Mapped[bool] = mapped_column(Boolean, default=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # İlişkiler
    detail: Mapped["CriminalDetail"] = relationship(back_populates="master", uselist=False, cascade="all, delete-orphan")
    photos: Mapped[List["Photo"]] = relationship(back_populates="owner", cascade="all, delete-orphan")

    @property
    def image_url(self):
        from extensions import MINIO_PUBLIC_URL, BUCKET_NAME
        if self.thumbnail_path:
            return f"{MINIO_PUBLIC_URL}/{BUCKET_NAME}/{self.thumbnail_path}"
        return None