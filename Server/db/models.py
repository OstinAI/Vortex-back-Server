# -*- coding: utf-8 -*-
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, UniqueConstraint, BigInteger, Text, LargeBinary, Table, Float
from sqlalchemy import Index

Base = declarative_base()

# ============================
#  USER <-> REGION (M2M)
# ============================
user_regions = Table(
    "user_regions",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("region_id", Integer, ForeignKey("regions.id"), primary_key=True),
)

# ============================
#  COMPANY
# ============================
class Company(Base):
    __tablename__ = 'companies'

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    storage_limit_mb = Column(Integer, default=100, nullable=False)      # лимит (МБ), можно менять
    storage_used_bytes = Column(BigInteger, default=0, nullable=False)   # занято (байт)

    users = relationship('User', back_populates='company')
    departments = relationship('Department', back_populates='company')
    regions = relationship("Region", back_populates="company")
    clients = relationship("Client", back_populates="company")
    crm_settings = relationship("CompanyCRMSettings", back_populates="company", uselist=False)
    pipelines = relationship("Pipeline", back_populates="company", cascade="all, delete-orphan")
    channel_routes = relationship("CRMChannelRoute", back_populates="company", cascade="all, delete-orphan")


    def __repr__(self):
        return f'<Company id={self.id} name={self.name!r}>'
    
# ============================
#  COMPANY PROFILE FIELDS (custom fields at registration)
# ============================
class CompanyProfileField(Base):
    __tablename__ = "company_profile_fields"
    __table_args__ = (
        UniqueConstraint("company_id", "key", name="uq_company_profile_field_key"),
        Index("ix_company_profile_fields_company", "company_id"),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)

    key = Column(String(120), nullable=False)      # название поля
    value = Column(Text, default="", nullable=False)
    required = Column(Boolean, default=False, nullable=False)

# ============================
#  USER
# ============================
class User(Base):
    __tablename__ = 'users'
    __table_args__ = (
        UniqueConstraint('username', 'company_id', name='uq_user_company'),
    )

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(255), nullable=False)
    company_id = Column(Integer, ForeignKey('companies.id'), nullable=False)
    department_id = Column(Integer, ForeignKey('departments.id'), nullable=True)
    is_department_head = Column(Boolean, default=False, nullable=False)
    is_inventory_head = Column(Boolean, default=False, nullable=False)
    role = Column(String(50), default='User', nullable=False)

    password_hash = Column(String(512), nullable=False)
    salt = Column(String(128), nullable=False)
    iterations = Column(Integer, nullable=False)

    first_login = Column(Boolean, default=True)
    temp_password_expire = Column(String(50), default=None)

    full_name = Column(String(255))
    phone = Column(String(50))
    email = Column(String(255))
    birth_date = Column(String(20))
    hire_date = Column(String(20))
    position = Column(String(255))
    address = Column(String(500))
    notes = Column(String(1000))
    status = Column(String(50), default="active")
    resume_path = Column(String(500))

    avatar_path = Column(String(500))

    company = relationship('Company', back_populates='users')
    department = relationship('Department', back_populates='users')
    regions = relationship("Region", secondary=user_regions, back_populates="users")

    def __repr__(self):
        return f'<User id={self.id} username={self.username!r} company_id={self.company_id}>'

# ============================
#  MAIL ACCOUNT
# ============================
class MailAccount(Base):
    __tablename__ = 'mail_accounts'

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey('companies.id'), nullable=False)

    email = Column(String(255), nullable=False)
    encrypted_password = Column(String(512), nullable=False)
    provider = Column(String(50), default="mailru")

    company = relationship('Company')

# ============================
#  MAIL MESSAGE (HEADERS CACHE)
# ============================
class MailMessage(Base):
    __tablename__ = "mail_messages"

    company_id = Column(Integer, primary_key=True)
    folder = Column(String(100), primary_key=True)
    uid = Column(BigInteger, primary_key=True)

    sender = Column(Text)
    subject = Column(Text)
    date = Column(Text)
    has_attachments = Column(Boolean, default=False)

# ============================
#  WHATSAPP NUMBER
# ============================
class WhatsAppNumber(Base):
    __tablename__ = "wa_numbers"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)

    phone = Column(String(32), nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)

    # политика
    block_new_chats = Column(Boolean, default=True, nullable=False)

    # приветствие (автоответ)
    greeting_enabled = Column(Boolean, default=False, nullable=False)
    greeting_text = Column(Text, default="", nullable=False)

    company = relationship("Company")

    __table_args__ = (
        UniqueConstraint("company_id", "phone", name="uq_wa_number_company_phone"),
    )

# ============================
#  WHATSAPP CHAT
# ============================
class WhatsAppChat(Base):
    __tablename__ = "wa_chats"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)

    # номер компании (с какого WA аккаунта)
    wa_phone = Column(String(32), nullable=False, index=True)

    # собеседник
    peer_phone = Column(String(32), nullable=False, index=True)

    peer_name = Column(String(255), default="")
    peer_avatar_url = Column(Text, default="")

    last_message_ts_ms = Column(BigInteger, default=0)

    __table_args__ = (
        UniqueConstraint("company_id", "wa_phone", "peer_phone", name="uq_wa_chat_key"),
    )

# ============================
#  WHATSAPP MESSAGE
# ============================
class WhatsAppMessage(Base):
    __tablename__ = "wa_messages"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)

    wa_phone = Column(String(32), nullable=False, index=True)
    peer_phone = Column(String(32), nullable=False, index=True)

    direction = Column(String(10), nullable=False)  # "in" / "out"
    text = Column(Text, default="")

    file_id = Column(Integer, ForeignKey("stored_files.id"), nullable=True, index=True)
    file_name = Column(String(255), default="")
    file_mime = Column(String(100), default="")
    file_size_bytes = Column(BigInteger, default=0)

    ts_ms = Column(BigInteger, default=0, index=True)

    # status: "pending" / "sent" / "delivered" / "read"
    status = Column(String(20), default="pending")

    # идентификатор WA (если поймаем)
    wa_msg_id = Column(String(200), default="", index=True)

    msg_key = Column(String(300), default="", index=True)

    __table_args__ = (
        UniqueConstraint("company_id", "wa_phone", "peer_phone", "ts_ms", "direction", "text", "file_id",
                         name="uq_wa_msg_dedup"),

    )

from sqlalchemy import Column, Integer, String, BigInteger, UniqueConstraint

class WhatsAppClientState(Base):
    __tablename__ = "whatsapp_client_state"

    id = Column(Integer, primary_key=True, autoincrement=True)

    company_id = Column(Integer, nullable=False)
    wa_phone = Column(String(32), nullable=False)

    client_id = Column(String(128), nullable=False)  # уникальный ID клиента (устройство/инстанс)
    last_delivered_id = Column(BigInteger, nullable=False, default=0)  # последний доставленный message.id

    __table_args__ = (
        UniqueConstraint("company_id", "wa_phone", "client_id", name="uq_wa_client_state"),
    )

class StoredFile(Base):
    __tablename__ = "stored_files"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    uploader_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    filename = Column(String(255), nullable=False, default="file.bin")
    mime_type = Column(String(100), nullable=False, default="application/octet-stream")
    size_bytes = Column(BigInteger, nullable=False, default=0)

    sha256 = Column(String(64), nullable=False, default="")

    data = Column(LargeBinary, nullable=False)  # ВАЖНО: храним файл в БД (BLOB)

    created_ts_ms = Column(BigInteger, default=0, index=True)

    company = relationship("Company")

class Department(Base):
    __tablename__ = "departments"
    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_department_company_name"),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)

    company = relationship("Company", back_populates="departments")
    users = relationship("User", back_populates="department")

# ============================
#  REGION
# ============================
class Region(Base):
    __tablename__ = "regions"
    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_region_company_name"),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)

    company = relationship("Company", back_populates="regions")
    users = relationship("User", secondary=user_regions, back_populates="regions")

    def __repr__(self):
        return f"<Region id={self.id} company_id={self.company_id} name={self.name!r}>"

# ============================
#  CRM: CLIENT
# ============================
class Client(Base):
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    region_id = Column(Integer, ForeignKey("regions.id"), nullable=True, index=True)
    pipeline_id = Column(Integer, ForeignKey("crm_pipelines.id"), nullable=True, index=True)
    stage_id = Column(Integer, ForeignKey("crm_pipeline_stages.id"), nullable=True, index=True)

    name = Column(String(255), default="", nullable=False)
    status = Column(String(50), default="active", nullable=False)

    notes = Column(Text, default="")

    created_ts_ms = Column(BigInteger, default=0, index=True)

    # для merge
    merged_into_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    is_archived = Column(Boolean, default=False, nullable=False)

    company = relationship("Company", back_populates="clients")
    region = relationship("Region")
    pipeline = relationship("Pipeline")
    stage = relationship("PipelineStage")

    identities = relationship("ClientIdentity", back_populates="client")
    assignments = relationship("ClientAssignment", back_populates="client")

    def __repr__(self):
        return f"<Client id={self.id} company_id={self.company_id} name={self.name!r}>"


# ============================
#  CRM: CLIENT IDENTITY (каналы/контакты)
# ============================
class ClientIdentity(Base):
    __tablename__ = "client_identities"
    __table_args__ = (
        UniqueConstraint("company_id", "kind", "value", name="uq_client_identity_company_kind_value"),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)

    # kind: phone/email/whatsapp/instagram/telegram/other
    kind = Column(String(50), nullable=False, index=True)
    value = Column(String(255), nullable=False, index=True)

    is_primary = Column(Boolean, default=False, nullable=False)
    created_ts_ms = Column(BigInteger, default=0, index=True)

    client = relationship("Client", back_populates="identities")


# ============================
#  CRM: CLIENT ASSIGNMENT (клиент <-> менеджеры, M2M)
# ============================
class ClientAssignment(Base):
    __tablename__ = "client_assignments"
    __table_args__ = (
        UniqueConstraint("client_id", "user_id", name="uq_client_assignment"),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)

    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # role: primary/secondary/observer
    role = Column(String(50), default="primary", nullable=False)

    created_ts_ms = Column(BigInteger, default=0, index=True)

    client = relationship("Client", back_populates="assignments")
    user = relationship("User")


# ============================
#  CRM: SETTINGS (вкл/выкл автосоздание по каналам)
# ============================
class CompanyCRMSettings(Base):
    __tablename__ = "company_crm_settings"

    company_id = Column(Integer, ForeignKey("companies.id"), primary_key=True)

    auto_create_from_whatsapp = Column(Boolean, default=True, nullable=False)
    auto_create_from_instagram = Column(Boolean, default=True, nullable=False)
    auto_create_from_email = Column(Boolean, default=False, nullable=False)

    company = relationship("Company", back_populates="crm_settings")

# ============================
#  CRM: FIELD DEFINITIONS (конструктор полей)
# ============================
class CRMFieldDefinition(Base):
    __tablename__ = "crm_field_definitions"
    __table_args__ = (
        UniqueConstraint("company_id", "scope_type", "scope_id", "key", name="uq_crm_field_company_scope_key"),
    )

    id = Column(Integer, primary_key=True)

    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)

    # scope_type: "company" или "department"
    scope_type = Column(String(50), nullable=False, index=True)
    scope_id = Column(Integer, nullable=False, index=True)  # 0 для company, department_id для department

    # key: системный ключ поля (например "address", "debt_amount")
    key = Column(String(100), nullable=False, index=True)

    # title: отображаемое название в UI
    title = Column(String(255), nullable=False)

    # type: text/number/bool/date/select
    type = Column(String(50), default="text", nullable=False)

    required = Column(Boolean, default=False, nullable=False)
    is_enabled = Column(Boolean, default=True, nullable=False)

    order_index = Column(Integer, default=0, nullable=False)

    # для select: JSON строка вариантов (например ["VIP","New","Regular"])
    options_json = Column(Text, default="", nullable=False)

    created_ts_ms = Column(BigInteger, default=0, index=True)

    def __repr__(self):
        return f"<CRMFieldDefinition id={self.id} key={self.key!r} scope={self.scope_type}:{self.scope_id}>"


# ============================
#  CRM: FIELD VALUES (значения полей у клиента)
# ============================
class CRMFieldValue(Base):
    __tablename__ = "crm_field_values"
    __table_args__ = (
        UniqueConstraint("company_id", "client_id", "field_id", name="uq_crm_value_company_client_field"),
    )

    id = Column(Integer, primary_key=True)

    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    field_id = Column(Integer, ForeignKey("crm_field_definitions.id"), nullable=False, index=True)

    # хранение по типам
    value_text = Column(Text, default="", nullable=False)
    value_number = Column(Float, nullable=True)
    value_bool = Column(Boolean, nullable=True)
    value_ts_ms = Column(BigInteger, nullable=True)  # для date

    updated_ts_ms = Column(BigInteger, default=0, index=True)

    field = relationship("CRMFieldDefinition")

# ============================
#  TASKS (CRM)
# ============================

class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True)

    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)

    # задача может быть на клиента (обязательно по твоему запросу)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)

    # можно указать отдел (не обязательно)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True, index=True)

    # кто создал
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    # обязательное
    title = Column(String(255), nullable=False)

    # не обязательное
    description = Column(Text, default="")

    # даты
    start_ts_ms = Column(BigInteger, nullable=False, default=0, index=True)
    end_ts_ms = Column(BigInteger, nullable=True, index=True)  # может быть пустым

    # статус / срочность (оба не обязательны)
    # status: "open" | "in_progress" | "done" | "canceled"
    status = Column(String(50), default="open", nullable=False, index=True)

    # priority: "normal" | "urgent"
    priority = Column(String(50), default="normal", nullable=False, index=True)

    created_ts_ms = Column(BigInteger, default=0, index=True)
    updated_ts_ms = Column(BigInteger, default=0, index=True)

    client = relationship("Client")
    department = relationship("Department")
    created_by = relationship("User", foreign_keys=[created_by_user_id])

    assignees = relationship("TaskAssignee", back_populates="task", cascade="all, delete-orphan")


class TaskAssignee(Base):
    __tablename__ = "task_assignees"
    __table_args__ = (
        UniqueConstraint("task_id", "user_id", name="uq_task_assignee"),
    )

    id = Column(Integer, primary_key=True)

    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    created_ts_ms = Column(BigInteger, default=0, index=True)

    task = relationship("Task", back_populates="assignees")
    user = relationship("User")

# ============================
#  NOTES
# ============================

class Note(Base):
    __tablename__ = "notes"

    id = Column(Integer, primary_key=True)

    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)

    # заметка на клиента
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)

    # можно указать отдел (не обязательно)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True, index=True)

    # кто создал
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    # обязательное
    description = Column(Text, default="", nullable=False)

    type = Column(String(20), default="note", nullable=False)

    created_ts_ms = Column(BigInteger, default=0, index=True)
    updated_ts_ms = Column(BigInteger, default=0, index=True)

    client = relationship("Client")
    department = relationship("Department")
    created_by = relationship("User", foreign_keys=[created_by_user_id])

    assignees = relationship("NoteAssignee", back_populates="note", cascade="all, delete-orphan")


class NoteAssignee(Base):
    __tablename__ = "note_assignees"
    __table_args__ = (
        UniqueConstraint("note_id", "user_id", name="uq_note_assignee"),
    )

    id = Column(Integer, primary_key=True)

    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    note_id = Column(Integer, ForeignKey("notes.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    created_ts_ms = Column(BigInteger, default=0, index=True)

    note = relationship("Note", back_populates="assignees")
    user = relationship("User")

# ============================
#  INVENTORY / WAREHOUSE
# ============================

class InventoryRegion(Base):
    __tablename__ = "inventory_regions"
    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_inventory_region_company_name"),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)

    name = Column(String(255), nullable=False, index=True)
    is_enabled = Column(Boolean, default=True, nullable=False)

    created_ts_ms = Column(BigInteger, default=0, index=True)

    company = relationship("Company")


class InventoryCategory(Base):
    __tablename__ = "inventory_categories"
    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_inventory_category_company_name"),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)

    name = Column(String(255), nullable=False, index=True)
    parent_id = Column(Integer, ForeignKey("inventory_categories.id"), nullable=True, index=True)

    is_enabled = Column(Boolean, default=True, nullable=False)
    created_ts_ms = Column(BigInteger, default=0, index=True)

    company = relationship("Company")
    parent = relationship("InventoryCategory", remote_side=[id])


class Product(Base):
    __tablename__ = "inventory_products"
    __table_args__ = (
        UniqueConstraint("company_id", "product_no", name="uq_inventory_product_company_no"),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)

    # номер товара 1..N (внутри компании)
    product_no = Column(Integer, nullable=False, index=True)

    # опционально: категория
    category_id = Column(Integer, ForeignKey("inventory_categories.id"), nullable=True, index=True)

    # "product" или "service"
    kind = Column(String(50), default="product", nullable=False, index=True)

    title = Column(String(255), nullable=False, index=True)
    description = Column(Text, default="")

    # базовая цена (если регионов нет или цена общая)
    base_price = Column(Float, nullable=True)

    # медиа (опционально)
    main_image_file_id = Column(Integer, ForeignKey("stored_files.id"), nullable=True, index=True)
    main_video_file_id = Column(Integer, ForeignKey("stored_files.id"), nullable=True, index=True)

    is_enabled = Column(Boolean, default=True, nullable=False, index=True)

    created_ts_ms = Column(BigInteger, default=0, index=True)
    updated_ts_ms = Column(BigInteger, default=0, index=True)

    company = relationship("Company")
    category = relationship("InventoryCategory")
    main_image = relationship("StoredFile", foreign_keys=[main_image_file_id])
    main_video = relationship("StoredFile", foreign_keys=[main_video_file_id])

    region_prices = relationship("ProductRegionPrice", back_populates="product", cascade="all, delete-orphan")
    field_values = relationship("ProductFieldValue", back_populates="product", cascade="all, delete-orphan")


class ProductRegionPrice(Base):
    __tablename__ = "inventory_product_region_prices"
    __table_args__ = (
        UniqueConstraint("company_id", "product_id", "region_id", name="uq_inventory_price_company_product_region"),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)

    product_id = Column(Integer, ForeignKey("inventory_products.id"), nullable=False, index=True)
    region_id = Column(Integer, ForeignKey("inventory_regions.id"), nullable=False, index=True)

    price = Column(Float, nullable=False)

    created_ts_ms = Column(BigInteger, default=0, index=True)
    updated_ts_ms = Column(BigInteger, default=0, index=True)

    product = relationship("Product", back_populates="region_prices")
    region = relationship("InventoryRegion")

class ProductFile(Base):
    __tablename__ = "inventory_product_files"
    __table_args__ = (
        UniqueConstraint("company_id", "product_id", "file_id", name="uq_inventory_product_file"),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)

    product_id = Column(Integer, ForeignKey("inventory_products.id"), nullable=False, index=True)
    file_id = Column(Integer, ForeignKey("stored_files.id"), nullable=False, index=True)

    kind = Column(String(20), nullable=False, default="image")  # image | video
    sort_index = Column(Integer, default=0, nullable=False)
    is_main = Column(Boolean, default=False, nullable=False)

    created_ts_ms = Column(BigInteger, default=0, index=True)

    product = relationship("Product")
    file = relationship("StoredFile")

# ============================
#  FLEXIBLE FIELDS FOR PRODUCT
# ============================

class ProductFieldDefinition(Base):
    __tablename__ = "inventory_field_definitions"
    __table_args__ = (
        UniqueConstraint("company_id", "key", "scope_type", "scope_id", name="uq_inventory_field_company_key_scope"),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)

    # scope: company | category | region
    scope_type = Column(String(50), default="company", nullable=False, index=True)
    scope_id = Column(Integer, default=0, nullable=False, index=True)

    key = Column(String(120), nullable=False, index=True)      # tnved, esf_no, warehouse_code ...
    title = Column(String(255), nullable=False)                # "Код ТН ВЭД"
    type = Column(String(50), default="text", nullable=False)  # text|number|bool|date|select
    required = Column(Boolean, default=False, nullable=False)

    order_index = Column(Integer, default=0, nullable=False)
    options_json = Column(Text, default="")  # для select

    is_enabled = Column(Boolean, default=True, nullable=False, index=True)

    created_ts_ms = Column(BigInteger, default=0, index=True)
    updated_ts_ms = Column(BigInteger, default=0, index=True)


class ProductFieldValue(Base):
    __tablename__ = "inventory_field_values"
    __table_args__ = (
        UniqueConstraint("company_id", "product_id", "field_id", name="uq_inventory_value_company_product_field"),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)

    product_id = Column(Integer, ForeignKey("inventory_products.id"), nullable=False, index=True)
    field_id = Column(Integer, ForeignKey("inventory_field_definitions.id"), nullable=False, index=True)

    value_text = Column(Text, default="")
    value_number = Column(Float, nullable=True)
    value_bool = Column(Boolean, nullable=True)
    value_ts_ms = Column(BigInteger, nullable=True)

    created_ts_ms = Column(BigInteger, default=0, index=True)
    updated_ts_ms = Column(BigInteger, default=0, index=True)

    product = relationship("Product", back_populates="field_values")
    field = relationship("ProductFieldDefinition")

# ============================
#  WAREHOUSES / STOCK MOVEMENTS
# ============================

class Warehouse(Base):
    __tablename__ = "inventory_warehouses"
    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_inventory_warehouse_company_name"),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)

    # опционально привязка к региону
    region_id = Column(Integer, ForeignKey("inventory_regions.id"), nullable=True, index=True)

    name = Column(String(255), nullable=False, index=True)
    address = Column(Text, default="")

    is_enabled = Column(Boolean, default=True, nullable=False, index=True)
    created_ts_ms = Column(BigInteger, default=0, index=True)

    company = relationship("Company")
    region = relationship("InventoryRegion")


class StockMovement(Base):
    __tablename__ = "inventory_stock_movements"
    __table_args__ = (
        Index("ix_inv_mov_company_wh_prod_ts", "company_id", "warehouse_id", "product_id", "created_ts_ms"),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)

    warehouse_id = Column(Integer, ForeignKey("inventory_warehouses.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("inventory_products.id"), nullable=False, index=True)

    # IN | OUT | TRANSFER_IN | TRANSFER_OUT | ADJUST
    movement_type = Column(String(50), nullable=False, index=True)

    # количество (+ для IN/TRANSFER_IN, - для OUT/TRANSFER_OUT можно хранить как плюс и типом, но я храню qty всегда положит.)
    qty = Column(Float, nullable=False)

    # цена закупа/себестоимость (опционально)
    unit_cost = Column(Float, nullable=True)

    # комментарий/основание: "Продажа №...", "Приход накладная №..."
    reason = Column(Text, default="")

    # ссылки на внешние сущности (опционально)
    ref_type = Column(String(50), default="", index=True)  # "sale"|"purchase"|...
    ref_id = Column(Integer, nullable=True, index=True)

    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_ts_ms = Column(BigInteger, default=0, index=True)

    warehouse = relationship("Warehouse")
    product = relationship("Product")
    created_by = relationship("User", foreign_keys=[created_by_user_id])

# ============================
#  CRM: PIPELINES (FUNNELS)
# ============================

class Pipeline(Base):
    __tablename__ = "crm_pipelines"
    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_crm_pipeline_company_name"),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)

    name = Column(String(255), nullable=False)
    is_enabled = Column(Boolean, default=True, nullable=False)

    order_index = Column(Integer, default=0, nullable=False)

    created_ts_ms = Column(BigInteger, default=0, index=True)
    updated_ts_ms = Column(BigInteger, default=0, index=True)

    company = relationship("Company", back_populates="pipelines")
    stages = relationship("PipelineStage", back_populates="pipeline", cascade="all, delete-orphan")


class PipelineStage(Base):
    __tablename__ = "crm_pipeline_stages"
    __table_args__ = (
        UniqueConstraint("pipeline_id", "name", name="uq_crm_stage_pipeline_name"),
    )

    id = Column(Integer, primary_key=True)

    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    pipeline_id = Column(Integer, ForeignKey("crm_pipelines.id"), nullable=False, index=True)

    name = Column(String(255), nullable=False)
    is_won = Column(Boolean, default=False, nullable=False)   # "успех"
    is_lost = Column(Boolean, default=False, nullable=False)  # "отказ"

    order_index = Column(Integer, default=0, nullable=False)
    is_enabled = Column(Boolean, default=True, nullable=False)

    created_ts_ms = Column(BigInteger, default=0, index=True)
    updated_ts_ms = Column(BigInteger, default=0, index=True)

    pipeline = relationship("Pipeline", back_populates="stages")


# =====================================
#  CRM: CHANNEL ROUTING (канал -> воронка/этап)
# =====================================

class CRMChannelRoute(Base):
    __tablename__ = "crm_channel_routes"
    __table_args__ = (
        UniqueConstraint("company_id", "channel", name="uq_crm_route_company_channel"),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)

    # channel: "whatsapp" | "instagram" | "email" | "manual" | "other"
    channel = Column(String(50), nullable=False, index=True)

    pipeline_id = Column(Integer, ForeignKey("crm_pipelines.id"), nullable=True, index=True)
    stage_id = Column(Integer, ForeignKey("crm_pipeline_stages.id"), nullable=True, index=True)

    created_ts_ms = Column(BigInteger, default=0, index=True)
    updated_ts_ms = Column(BigInteger, default=0, index=True)

    company = relationship("Company", back_populates="channel_routes")
    pipeline = relationship("Pipeline")
    stage = relationship("PipelineStage")


# =====================================
#  Оплата Итого
# =====================================
class SaleState(Base):
    __tablename__ = "sale_states"

    id = Column(Integer, primary_key=True)

    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)

    total_amount = Column(Float, default=0.0, nullable=False)
    paid_amount = Column(Float, default=0.0, nullable=False)

    updated_ts_ms = Column(BigInteger, default=0, nullable=False)

    __table_args__ = (
        UniqueConstraint("company_id", "client_id", name="uq_sale_state_company_client"),
        Index("ix_sale_states_company_client", "company_id", "client_id"),
    )
    
# =====================================
#  Оплата Итого
# =====================================
class SaleServiceLine(Base):
    __tablename__ = "sale_service_lines"

    id = Column(Integer, primary_key=True)

    company_id = Column(Integer, nullable=False, index=True)
    client_id = Column(Integer, nullable=False, index=True)

    service_id = Column(Integer, nullable=False, index=True)
    qty = Column(Float, default=1.0, nullable=False)
    unit_price = Column(Float, default=0.0, nullable=False)

    created_ts_ms = Column(BigInteger, default=0, nullable=False)

# ============================
#  CRM Автоматизация (правила и логи)
# ============================

class AutomationRule(Base):
    __tablename__ = "crm_automation_rules"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)

    # example: "client.created", "client.moved"
    event_name = Column(String(80), nullable=False, index=True)

    title = Column(String(255), default="", nullable=False)

    enabled = Column(Boolean, default=True, nullable=False, index=True)
    priority = Column(Integer, default=100, nullable=False, index=True)

    # JSON string:
    # {"all":[{"eq":["stage_id",10]},{"exists":["client_id"]}]}
    conditions_json = Column(Text, default="{}", nullable=False)

    # JSON string:
    # [{"type":"assign_manager","mode":"round_robin","role":"Manager"}]
    actions_json = Column(Text, default="[]", nullable=False)

    stop_on_match = Column(Boolean, default=True, nullable=False)

    created_ts_ms = Column(BigInteger, default=0, index=True)
    updated_ts_ms = Column(BigInteger, default=0, index=True)

    __table_args__ = (
        Index("ix_auto_rules_company_event_prio", "company_id", "event_name", "priority"),
    )


class AutomationLog(Base):
    __tablename__ = "crm_automation_logs"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, nullable=False, index=True)
    rule_id = Column(Integer, nullable=True, index=True)

    event_name = Column(String(80), default="", index=True)
    ok = Column(Boolean, default=True, nullable=False, index=True)

    error = Column(Text, default="", nullable=False)
    context_json = Column(Text, default="{}", nullable=False)

    created_ts_ms = Column(BigInteger, default=0, index=True)

    __table_args__ = (
        Index("ix_auto_logs_company_ts", "company_id", "created_ts_ms"),
    )


class LeadRoundRobinState(Base):
    __tablename__ = "crm_lead_rr_state"
    __table_args__ = (
        UniqueConstraint("company_id", "key", name="uq_rr_state_company_key"),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, nullable=False, index=True)

    # key example: "pipe:1:stage:10:role:Manager:dep:0:region:0"
    key = Column(String(200), nullable=False, index=True)

    last_user_id = Column(Integer, nullable=True)
    updated_ts_ms = Column(BigInteger, default=0, index=True)

# NEW: отложенные действия автоматики
class AutomationJob(Base):
    __tablename__ = "automation_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, nullable=False, index=True)

    action_type = Column(String(64), nullable=False)          # например "move_stage"
    action_json = Column(Text, nullable=False, default="{}")  # параметры action
    ctx_json = Column(Text, nullable=False, default="{}")     # контекст (client_id и т.д.)

    run_at_ts_ms = Column(BigInteger, nullable=False, index=True)

    status = Column(String(16), nullable=False, default="pending")  # pending|done|failed
    error = Column(Text, nullable=True)

    created_ts_ms = Column(BigInteger, nullable=False, default=0)
    updated_ts_ms = Column(BigInteger, nullable=False, default=0)