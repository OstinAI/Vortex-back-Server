from sqlalchemy import Column, Integer, String, Boolean, BigInteger, Text
from db.models import Base

class MailMessage(Base):
    __tablename__ = "mail_messages"

    company_id = Column(Integer, primary_key=True)
    folder = Column(String(100), primary_key=True)
    uid = Column(BigInteger, primary_key=True)

    sender = Column(Text)
    subject = Column(Text)
    date = Column(Text)
    has_attachments = Column(Boolean, default=False)
