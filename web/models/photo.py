from extensions import db # 'web.' ön ekini kaldır, direkt extensions
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Integer, String, ForeignKey

class Photo(db.Model):
    __tablename__ = 'photos'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    criminal_id: Mapped[int] = mapped_column(Integer, ForeignKey('criminals.id', ondelete="CASCADE"), nullable=False)
    image_path: Mapped[str] = mapped_column(String(300), nullable=False)
    picture_id: Mapped[str] = mapped_column(String(50), unique=True)

    # DİKKAT: Burada 'Criminal' modelini import etmiyoruz, tırnak içinde ismini veriyoruz.
    # Bu hamle döngüsel bağımlılığı (circular import) anında kırar.
    owner: Mapped["Criminal"] = relationship(back_populates="photos")

    @property
    def image_url(self):
        # Sabitleri fonksiyon içinden import ederek global döngüyü engelliyoruz.
        from extensions import MINIO_PUBLIC_URL, BUCKET_NAME
        if self.image_path:
            return f"{MINIO_PUBLIC_URL}/{BUCKET_NAME}/{self.image_path}"
        return None