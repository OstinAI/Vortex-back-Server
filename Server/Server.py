# -*- coding: utf-8 -*-
import base64
import hashlib
import time
from db.models import Client

from db.connection import init_db, get_session
from db.models import Company, User, MailAccount, WhatsAppNumber, Department, Region
from db.models import Pipeline, PipelineStage, CRMChannelRoute
from utils.hashing import hash_password
from utils.crypto import encrypt
from server.whatsapp.manager import wa_manager
from server.whatsapp.utils import normalize_phone
from server.Bot.greeting import set_greeting_settings

# ===========================================================
#  ХЕШИРОВАНИЕ КАК В КЛИЕНТЕ (SHA256 → Base64)
# ===========================================================
def make_client_hash(password: str) -> str:
    sha = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.b64encode(sha).decode("utf-8")


# ===========================================================
#  СОЗДАНИЕ ПОЛЬЗОВАТЕЛЯ
# ===========================================================
def create_user(company_name, username, role, real_password):
    session = get_session()
    try:
        company = session.query(Company).filter_by(name=company_name).first()
        if not company:
            company = Company(name=company_name, is_active=True)
            session.add(company)
            session.flush()

        client_hash = make_client_hash(real_password)
        password_hash, salt, iterations = hash_password(client_hash)

        user = User(
            username=username,
            company_id=company.id,
            role=role,
            password_hash=password_hash,
            salt=salt,
            iterations=iterations
        )
        session.add(user)
        session.commit()

        print(f"✅ Пользователь создан: id={user.id} ({username}) в компании {company_name}")
    finally:
        session.close()


# ===========================================================
#  СПИСОК КОМПАНИЙ
# ===========================================================
def list_companies():
    session = get_session()
    try:
        companies = session.query(Company).all()
        if not companies:
            print("⚠ Нет компаний в БД")
            return

        print("\n=== Компании ===")
        for c in companies:
            print(f"ID: {c.id} | Название: {c.name} | Активна: {c.is_active}")
    finally:
        session.close()


# ===========================================================
#  СПИСОК ПОЛЬЗОВАТЕЛЕЙ
# ===========================================================
def list_users():
    session = get_session()
    try:
        users = session.query(User).all()
        if not users:
            print("⚠ Нет пользователей в БД")
            return

        print("\n=== Пользователи ===")
        for u in users:
            company = session.query(Company).filter_by(id=u.company_id).first()
            cname = company.name if company else "???"

            print(f"""
-------------------------------------------
ID:            {u.id}
Логин:         {u.username}
Роль:          {u.role}
Компания:      {cname} (id={u.company_id})

ФИО:           {u.full_name}
Телефон:       {u.phone}
Email:         {u.email}

Дата рождения: {u.birth_date}
Дата найма:    {u.hire_date}

Должность:     {u.position}
Адрес:         {u.address}

Статус:        {u.status}
Заметки:       {u.notes}

Путь резюме:   {u.resume_path}
-------------------------------------------
""")
    finally:
        session.close()



# ===========================================================
#  УДАЛЕНИЕ ПОЛЬЗОВАТЕЛЯ
# ===========================================================
def delete_user(user_id):
    session = get_session()
    try:
        user = session.query(User).filter_by(id=user_id).first()
        if not user:
            print("❌ Пользователь не найден")
            return

        session.delete(user)
        session.commit()
        print(f"🗑 Пользователь {user.username} (id={user_id}) удалён")
    finally:
        session.close()


# ===========================================================
#  УДАЛЕНИЕ КОМПАНИИ
# ===========================================================
def delete_company(company_id):
    session = get_session()
    try:
        company = session.query(Company).filter_by(id=company_id).first()
        if not company:
            print("❌ Компания не найдена")
            return

        users = session.query(User).filter_by(company_id=company_id).all()
        if users:
            print("❌ Нельзя удалить компанию — есть пользователи")
            return

        session.delete(company)
        session.commit()
        print(f"🗑 Компания {company.name} (id={company_id}) удалена")
    finally:
        session.close()

# ===========================================================
#  ПРИВЯЗКА ПОЧТЫ К КОМПАНИИ
# ===========================================================
def setup_mail_for_company(company_name, email_addr, real_password):
    session = get_session()
    try:
        company = session.query(Company).filter_by(name=company_name).first()
        if not company:
            print("❌ Компания не найдена")
            return

        encrypted_password = encrypt(real_password)

        account = session.query(MailAccount)\
            .filter_by(company_id=company.id)\
            .first()

        if account:
            account.email = email_addr
            account.encrypted_password = encrypted_password
            print("🔁 Почта обновлена")
        else:
            account = MailAccount(
                company_id=company.id,
                email=email_addr,
                encrypted_password=encrypted_password,
                provider="mailru"
            )
            session.add(account)
            print("✅ Почта привязана")

        session.commit()
    finally:
        session.close()

# ===========================================================
#  УДАЛЕНИЕ ПРИВЯЗАННОЙ ПОЧТЫ У КОМПАНИИ
# ===========================================================
def remove_mail_for_company(company_name):
    session = get_session()
    try:
        company = session.query(Company).filter_by(name=company_name).first()
        if not company:
            print("❌ Компания не найдена")
            return

        acc = session.query(MailAccount).filter_by(company_id=company.id).first()
        if not acc:
            print("⚠ У компании нет привязанной почты")
            return

        session.delete(acc)
        session.commit()

        print(f"🗑 Почтовая интеграция удалена у компании {company_name}")

    finally:
        session.close()

# ===========================================================
#  СПИСОК WHATSAPP У КОМПАНИИ
# ===========================================================
def list_whatsapp(company_name):
    session = get_session()
    try:
        company = session.query(Company).filter_by(name=company_name).first()
        if not company:
            print("❌ Компания не найдена")
            return

        rows = session.query(WhatsAppNumber).filter_by(company_id=company.id).all()
        if not rows:
            print("❌ WhatsApp не привязан")
            return

        print("\n=== WhatsApp номера ===")
        for r in rows:
            print(f"📱 {r.phone} | active={r.is_active}")
    finally:
        session.close()


# ===========================================================
#  УДАЛЕНИЕ WHATSAPP У КОМПАНИИ
# ===========================================================
def delete_whatsapp(company_name, phone):
    phone = normalize_phone(phone)

    session = get_session()
    try:
        company = session.query(Company).filter_by(name=company_name).first()
        if not company:
            print("❌ Компания не найдена")
            return
    finally:
        session.close()

    wa_manager.remove_number_completely(company.id, phone)

    print("🗑 WhatsApp полностью удалён (сессия + БД + профиль)")

# ===========================================================
#  ОТДЕЛЫ: СОЗДАТЬ / СПИСОК / ПРИВЯЗАТЬ СОТРУДНИКА
# ===========================================================
def create_department(company_name: str, dept_name: str):
    session = get_session()
    try:
        company = session.query(Company).filter_by(name=company_name).first()
        if not company:
            print("❌ Компания не найдена")
            return

        dept_name = (dept_name or "").strip()
        if not dept_name:
            print("❌ Название отдела пустое")
            return

        exists = session.query(Department).filter_by(company_id=company.id, name=dept_name).first()
        if exists:
            print("⚠ Отдел уже существует:", dept_name)
            return

        dep = Department(company_id=company.id, name=dept_name)
        session.add(dep)
        session.commit()
        print(f"✅ Отдел создан: id={dep.id} | {dep.name} | company={company.name}")

    finally:
        session.close()


def list_departments(company_name: str):
    session = get_session()
    try:
        company = session.query(Company).filter_by(name=company_name).first()
        if not company:
            print("❌ Компания не найдена")
            return

        rows = session.query(Department).filter_by(company_id=company.id).order_by(Department.name.asc()).all()
        if not rows:
            print("⚠ У компании нет отделов")
            return

        print("\n=== Отделы компании:", company.name, "===")
        for d in rows:
            print(f"ID: {d.id} | {d.name}")

    finally:
        session.close()


def list_department_heads(company_name: str):
    session = get_session()
    try:
        company = session.query(Company).filter_by(name=company_name).first()
        if not company:
            print("❌ Компания не найдена")
            return

        deps = session.query(Department)\
            .filter_by(company_id=company.id)\
            .order_by(Department.name.asc())\
            .all()

        if not deps:
            print("⚠ У компании нет отделов")
            return

        print("\n=== Руководители отделов компании:", company.name, "===")

        for d in deps:
            head = session.query(User)\
                .filter_by(company_id=company.id,
                           department_id=d.id,
                           is_department_head=True)\
                .first()

            if head:
                print(f"ID отдела: {d.id} | {d.name} | Рук: {head.username} (id={head.id})")
            else:
                print(f"ID отдела: {d.id} | {d.name} | Рук: -")

    finally:
        session.close()


def assign_user_to_department(user_id: int, department_id: int):
    session = get_session()
    try:
        uid = int(user_id)
        did = int(department_id)

        user = session.query(User).filter_by(id=uid).first()
        if not user:
            print("❌ Пользователь не найден")
            return

        dep = session.query(Department).filter_by(id=did, company_id=user.company_id).first()
        if not dep:
            print("❌ Отдел не найден (или не принадлежит компании пользователя)")
            return

        user.department_id = dep.id
        session.commit()

        print(f"✅ Пользователь {user.username} (id={user.id}) привязан к отделу {dep.name} (id={dep.id})")

    finally:
        session.close()

# ===========================================================
#  РЕГИОНЫ: СОЗДАТЬ / СПИСОК / НАЗНАЧИТЬ ПОЛЬЗОВАТЕЛЮ
# ===========================================================
def create_region(company_name: str, region_name: str):
    session = get_session()
    try:
        company = session.query(Company).filter_by(name=company_name).first()
        if not company:
            print("❌ Компания не найдена")
            return

        region_name = (region_name or "").strip()
        if not region_name:
            print("❌ Название региона пустое")
            return

        exists = session.query(Region).filter_by(company_id=company.id, name=region_name).first()
        if exists:
            print("⚠ Регион уже существует:", region_name)
            return

        r = Region(company_id=company.id, name=region_name)
        session.add(r)
        session.commit()
        print(f"✅ Регион создан: id={r.id} | {r.name} | company={company.name}")
    finally:
        session.close()


def list_regions(company_name: str):
    session = get_session()
    try:
        company = session.query(Company).filter_by(name=company_name).first()
        if not company:
            print("❌ Компания не найдена")
            return

        rows = session.query(Region).filter_by(company_id=company.id).order_by(Region.name.asc()).all()
        if not rows:
            print("⚠ У компании нет регионов")
            return

        print("\n=== Регионы компании:", company.name, "===")
        for r in rows:
            print(f"ID: {r.id} | {r.name}")
    finally:
        session.close()


def assign_user_to_region(user_id: int, region_id: int):
    session = get_session()
    try:
        uid = int(user_id)
        rid = int(region_id)

        user = session.query(User).filter_by(id=uid).first()
        if not user:
            print("❌ Пользователь не найден")
            return

        region = session.query(Region).filter_by(id=rid, company_id=user.company_id).first()
        if not region:
            print("❌ Регион не найден (или не принадлежит компании пользователя)")
            return

        # many-to-many: добавляем если ещё нет
        if region not in user.regions:
            user.regions.append(region)
            session.commit()
            print(f"✅ Пользователь {user.username} (id={user.id}) добавлен в регион {region.name} (id={region.id})")
        else:
            print("⚠ Уже назначен на этот регион")
    finally:
        session.close()

def delete_region(company_name: str, region_id: int):
    session = get_session()
    try:
        company = session.query(Company).filter_by(name=company_name).first()
        if not company:
            print("❌ Компания не найдена")
            return

        rid = int(region_id)

        region = session.query(Region).filter_by(id=rid, company_id=company.id).first()
        if not region:
            print("❌ Регион не найден (или не принадлежит компании)")
            return

        # ВАЖНО: many-to-many — убираем связи с пользователями
        for u in list(region.users or []):
            try:
                u.regions.remove(region)
            except Exception:
                pass

        session.delete(region)
        session.commit()
        print(f"🗑 Регион удалён: id={rid}")

    finally:
        session.close()


def rename_region(company_name: str, region_id: int, new_name: str):
    session = get_session()
    try:
        company = session.query(Company).filter_by(name=company_name).first()
        if not company:
            print("❌ Компания не найдена")
            return

        rid = int(region_id)
        new_name = (new_name or "").strip()
        if not new_name:
            print("❌ Новое название пустое")
            return

        region = session.query(Region).filter_by(id=rid, company_id=company.id).first()
        if not region:
            print("❌ Регион не найден (или не принадлежит компании)")
            return

        # защита от дубля
        exists = session.query(Region).filter_by(company_id=company.id, name=new_name).first()
        if exists and int(exists.id) != int(region.id):
            print("❌ Регион с таким названием уже есть")
            return

        old = region.name
        region.name = new_name
        session.commit()
        print(f"✅ Регион переименован: id={region.id} | {old} -> {region.name}")

    finally:
        session.close()


def unassign_user_from_region(user_id: int, region_id: int):
    session = get_session()
    try:
        uid = int(user_id)
        rid = int(region_id)

        user = session.query(User).filter_by(id=uid).first()
        if not user:
            print("❌ Пользователь не найден")
            return

        region = session.query(Region).filter_by(id=rid, company_id=user.company_id).first()
        if not region:
            print("❌ Регион не найден (или не принадлежит компании пользователя)")
            return

        if region in (user.regions or []):
            user.regions.remove(region)
            session.commit()
            print(f"✅ Регион снят у пользователя: {user.username} (id={user.id}) -X- {region.name} (id={region.id})")
        else:
            print("⚠ У пользователя нет этого региона")

    finally:
        session.close()

# ===========================================================
#  ОТЧЁТ ПО КОМПАНИИ + ДОБАВИТЬ СОТРУДНИКА (с отделом/регионами)
# ===========================================================
def company_report(company_name: str):
    session = get_session()
    try:
        company = session.query(Company).filter_by(name=company_name).first()
        if not company:
            print("❌ Компания не найдена")
            return

        total_users = session.query(User).filter_by(company_id=company.id).count()
        total_deps = session.query(Department).filter_by(company_id=company.id).count()
        total_regions = session.query(Region).filter_by(company_id=company.id).count()

        print("\n==============================")
        print("ОТЧЁТ ПО КОМПАНИИ:", company.name)
        print("==============================")
        print(f"Company ID:   {company.id}")
        print(f"Активна:      {company.is_active}")
        print(f"Пользователи: {total_users}")
        print(f"Отделы:       {total_deps}")
        print(f"Регионы:      {total_regions}")

        # отделы + количество сотрудников
        deps = session.query(Department).filter_by(company_id=company.id).order_by(Department.name.asc()).all()
        if deps:
            print("\n--- Отделы (сотрудников) ---")
            for d in deps:
                cnt = session.query(User).filter_by(company_id=company.id, department_id=d.id).count()
                print(f"{d.id:>4} | {d.name} | users={cnt}")
        else:
            print("\n--- Отделы ---")
            print("Нет отделов")

        # регионы
        regs = session.query(Region).filter_by(company_id=company.id).order_by(Region.name.asc()).all()
        if regs:
            print("\n--- Регионы ---")
            for r in regs:
                print(f"{r.id:>4} | {r.name}")
        else:
            print("\n--- Регионы ---")
            print("Нет регионов")

        # пользователи с отделом и регионами
        users = session.query(User).filter_by(company_id=company.id).order_by(User.id.asc()).all()
        if users:
            print("\n--- Пользователи (отдел / регионы) ---")
            for u in users:
                dep_name = "-"
                if getattr(u, "department_id", None):
                    dep = session.query(Department).filter_by(id=u.department_id, company_id=company.id).first()
                    dep_name = dep.name if dep else "?"

                # регионы пользователя (many-to-many)
                try:
                    reg_names = [r.name for r in (u.regions or [])]
                except Exception:
                    reg_names = []

                regs_str = ", ".join(reg_names) if reg_names else "-"
                print(f"{u.id:>4} | {u.username:<15} | {u.role:<15} | dep={dep_name} | regions={regs_str}")

        print("==============================\n")

    finally:
        session.close()


def create_employee_with_dept_and_regions(company_name: str, username: str, role: str, real_password: str,
                                         department_id: int = 0, region_ids_csv: str = ""):
    session = get_session()
    try:
        company = session.query(Company).filter_by(name=company_name).first()
        if not company:
            print("❌ Компания не найдена")
            return

        # проверка уникальности логина в компании (если нужно)
        exists = session.query(User).filter_by(company_id=company.id, username=username).first()
        if exists:
            print("❌ Такой логин уже есть в компании")
            return

        # пароль
        client_hash = make_client_hash(real_password)
        password_hash, salt, iterations = hash_password(client_hash)

        user = User(
            username=username,
            company_id=company.id,
            role=role,
            password_hash=password_hash,
            salt=salt,
            iterations=iterations
        )

        # отдел (опционально)
        dept_id = int(department_id) if str(department_id).strip() else 0
        if dept_id > 0:
            dep = session.query(Department).filter_by(id=dept_id, company_id=company.id).first()
            if not dep:
                print("❌ Отдел не найден (или не принадлежит компании)")
                return
            user.department_id = dep.id

        session.add(user)
        session.flush()  # чтобы появился user.id

        # регионы (CSV "1,2,3")
        region_ids_csv = (region_ids_csv or "").strip()
        if region_ids_csv:
            parts = [p.strip() for p in region_ids_csv.split(",") if p.strip()]
            region_ids = []
            for p in parts:
                try:
                    region_ids.append(int(p))
                except Exception:
                    pass

            if region_ids:
                regs = session.query(Region).filter(Region.company_id == company.id, Region.id.in_(region_ids)).all()
                for r in regs:
                    if r not in user.regions:
                        user.regions.append(r)

        session.commit()
        print(f"✅ Сотрудник создан: id={user.id} | {user.username} | role={user.role} | company={company.name}")

    finally:
        session.close()

# ===========================================================
#  РОЛИ / БЛОКИРОВКИ: пользователь и компания
# ===========================================================
def change_user_role(user_id: int, new_role: str):
    session = get_session()
    try:
        uid = int(user_id)
        new_role = (new_role or "").strip()
        if not new_role:
            print("❌ Роль пустая")
            return

        user = session.query(User).filter_by(id=uid).first()
        if not user:
            print("❌ Пользователь не найден")
            return

        old = user.role
        user.role = new_role
        session.commit()
        print(f"✅ Роль изменена: id={user.id} | {user.username} | {old} -> {user.role}")
    finally:
        session.close()


def set_user_block(user_id: int, blocked: bool):
    session = get_session()
    try:
        uid = int(user_id)
        user = session.query(User).filter_by(id=uid).first()
        if not user:
            print("❌ Пользователь не найден")
            return

        # статус: active/blocked
        user.status = "blocked" if blocked else "active"
        session.commit()

        print(f"✅ Пользователь {user.username} (id={user.id}) статус -> {user.status}")
    finally:
        session.close()


def set_company_block(company_id: int, blocked: bool):
    session = get_session()
    try:
        cid = int(company_id)
        company = session.query(Company).filter_by(id=cid).first()
        if not company:
            print("❌ Компания не найдена")
            return

        company.is_active = False if blocked else True
        session.commit()

        state = "BLOCKED" if blocked else "ACTIVE"
        print(f"✅ Компания {company.name} (id={company.id}) -> {state}")
    finally:
        session.close()

# ===========================================================
#  CRM: ТЕСТ КАРТОЧЕК КЛИЕНТА
# ===========================================================
def crm_create_client(company_name: str, name: str):
    session = get_session()
    try:
        company = session.query(Company).filter_by(name=company_name).first()
        if not company:
            print("❌ Компания не найдена")
            return

        c = Client(
            company_id=company.id,
            name=name or "Без имени",
            status="active",
            created_ts_ms=int(time.time() * 1000),
        )
        session.add(c)
        session.commit()

        print(f"✅ Клиент создан: id={c.id} | name={c.name}")
    finally:
        session.close()


def crm_list_clients(company_name: str):
    session = get_session()
    try:
        company = session.query(Company).filter_by(name=company_name).first()
        if not company:
            print("❌ Компания не найдена")
            return

        rows = (
            session.query(Client)
            .filter_by(company_id=company.id, is_archived=False)
            .order_by(Client.id.asc())
            .all()
        )

        if not rows:
            print("⚠ Клиентов нет")
            return

        print("\n=== Клиенты компании:", company.name, "===")
        for c in rows:
            print(f"ID: {c.id} | {c.name} | status={c.status}")
    finally:
        session.close()


def crm_delete_client(client_id: int):
    session = get_session()
    try:
        c = session.query(Client).filter_by(id=int(client_id)).first()
        if not c:
            print("❌ Клиент не найден")
            return

        session.delete(c)
        session.commit()
        print(f"🗑 Клиент удалён: id={client_id}")
    finally:
        session.close()

# ===========================================================
#  CRM: ВОРОНКИ / ЭТАПЫ / МАРШРУТИЗАЦИЯ КАНАЛОВ
# ===========================================================

def crm_create_pipeline(company_name: str, pipeline_name: str, order_index: int = 0):
    session = get_session()
    try:
        company = session.query(Company).filter_by(name=company_name).first()
        if not company:
            print("❌ Компания не найдена")
            return

        name = (pipeline_name or "").strip()
        if not name:
            print("❌ Название воронки пустое")
            return

        exists = session.query(Pipeline).filter_by(company_id=company.id, name=name).first()
        if exists:
            print("⚠ Воронка уже существует:", name)
            return

        now = int(time.time() * 1000)
        p = Pipeline(
            company_id=company.id,
            name=name,
            order_index=int(order_index or 0),
            is_enabled=True,
            created_ts_ms=now,
            updated_ts_ms=now
        )
        session.add(p)
        session.commit()
        print(f"✅ Воронка создана: id={p.id} | {p.name} | company={company.name}")

    finally:
        session.close()


def crm_list_pipelines(company_name: str):
    session = get_session()
    try:
        company = session.query(Company).filter_by(name=company_name).first()
        if not company:
            print("❌ Компания не найдена")
            return

        rows = (
            session.query(Pipeline)
            .filter_by(company_id=company.id)
            .order_by(Pipeline.order_index.asc(), Pipeline.id.asc())
            .all()
        )

        if not rows:
            print("⚠ У компании нет воронок")
            return

        print("\n=== Воронки компании:", company.name, "===")
        for p in rows:
            print(f"ID: {p.id} | {p.name} | enabled={p.is_enabled} | order={p.order_index}")

    finally:
        session.close()


def crm_create_stage(company_name: str, pipeline_id: int, stage_name: str,
                     order_index: int = 0, is_won: bool = False, is_lost: bool = False):
    session = get_session()
    try:
        company = session.query(Company).filter_by(name=company_name).first()
        if not company:
            print("❌ Компания не найдена")
            return

        pid = int(pipeline_id)
        p = session.query(Pipeline).filter_by(company_id=company.id, id=pid).first()
        if not p:
            print("❌ Воронка не найдена")
            return

        name = (stage_name or "").strip()
        if not name:
            print("❌ Название этапа пустое")
            return

        exists = session.query(PipelineStage).filter_by(company_id=company.id, pipeline_id=pid, name=name).first()
        if exists:
            print("⚠ Этап уже существует:", name)
            return

        now = int(time.time() * 1000)
        st = PipelineStage(
            company_id=company.id,
            pipeline_id=pid,
            name=name,
            order_index=int(order_index or 0),
            is_won=bool(is_won),
            is_lost=bool(is_lost),
            is_enabled=True,
            created_ts_ms=now,
            updated_ts_ms=now
        )
        session.add(st)
        session.commit()

        print(f"✅ Этап создан: id={st.id} | {st.name} | pipeline={p.name} (id={p.id})")

    finally:
        session.close()


def crm_list_stages(company_name: str, pipeline_id: int):
    session = get_session()
    try:
        company = session.query(Company).filter_by(name=company_name).first()
        if not company:
            print("❌ Компания не найдена")
            return

        pid = int(pipeline_id)
        p = session.query(Pipeline).filter_by(company_id=company.id, id=pid).first()
        if not p:
            print("❌ Воронка не найдена")
            return

        rows = (
            session.query(PipelineStage)
            .filter_by(company_id=company.id, pipeline_id=pid)
            .order_by(PipelineStage.order_index.asc(), PipelineStage.id.asc())
            .all()
        )
        if not rows:
            print("⚠ У воронки нет этапов")
            return

        print("\n=== Этапы воронки:", p.name, f"(id={p.id}) ===")
        for st in rows:
            print(f"ID: {st.id} | {st.name} | won={st.is_won} | lost={st.is_lost} | enabled={st.is_enabled} | order={st.order_index}")

    finally:
        session.close()


def _norm_channel(ch: str) -> str:
    ch = (ch or "").strip().lower()
    if ch in ("wa", "whatsapp"):
        return "whatsapp"
    if ch in ("insta", "instagram"):
        return "instagram"
    if ch in ("mail", "email"):
        return "email"
    if ch in ("manual",):
        return "manual"
    return ch or "other"


def crm_set_channel_route(company_name: str, channel: str, pipeline_id: int | None, stage_id: int | None):
    session = get_session()
    try:
        company = session.query(Company).filter_by(name=company_name).first()
        if not company:
            print("❌ Компания не найдена")
            return

        ch = _norm_channel(channel)

        pid = int(pipeline_id) if pipeline_id else None
        sid = int(stage_id) if stage_id else None

        # валидация
        if pid is not None:
            p = session.query(Pipeline).filter_by(company_id=company.id, id=pid).first()
            if not p:
                print("❌ Воронка не найдена")
                return

        if sid is not None:
            st = session.query(PipelineStage).filter_by(company_id=company.id, id=sid).first()
            if not st:
                print("❌ Этап не найден")
                return
            if pid is not None and int(st.pipeline_id) != int(pid):
                print("❌ Этап не принадлежит выбранной воронке")
                return

        row = session.query(CRMChannelRoute).filter_by(company_id=company.id, channel=ch).first()
        now = int(time.time() * 1000)

        if not row:
            row = CRMChannelRoute(company_id=company.id, channel=ch, created_ts_ms=now, updated_ts_ms=now)
            session.add(row)

        row.pipeline_id = pid
        row.stage_id = sid
        row.updated_ts_ms = now

        session.commit()
        print(f"✅ Маршрут задан: channel={ch} | pipeline_id={pid} | stage_id={sid}")

    finally:
        session.close()


def crm_list_channel_routes(company_name: str):
    session = get_session()
    try:
        company = session.query(Company).filter_by(name=company_name).first()
        if not company:
            print("❌ Компания не найдена")
            return

        rows = (
            session.query(CRMChannelRoute)
            .filter_by(company_id=company.id)
            .order_by(CRMChannelRoute.channel.asc())
            .all()
        )

        if not rows:
            print("⚠ Маршрутизация каналов не настроена")
            return

        print("\n=== Маршрутизация каналов компании:", company.name, "===")
        for r in rows:
            print(f"channel={r.channel} | pipeline_id={r.pipeline_id} | stage_id={r.stage_id}")

    finally:
        session.close()

# ===========================================================
#  Бот 
# ===========================================================
def wa_set_greeting(company_name: str, wa_phone: str, text: str, enabled: bool = True):
    wa_phone = normalize_phone(wa_phone)

    session = get_session()
    try:
        company = session.query(Company).filter_by(name=company_name).first()
        if not company:
            print("❌ Компания не найдена")
            return

        # проверим что номер реально привязан
        row = session.query(WhatsAppNumber).filter_by(company_id=company.id, phone=wa_phone).first()
        if not row:
            print("❌ Этот WhatsApp номер не привязан к компании (wa_numbers)")
            return
    finally:
        session.close()

    ok, msg = set_greeting_settings(company.id, wa_phone, enabled, text)
    if ok:
        print("✅ Приветствие сохранено и включено" if enabled else "✅ Приветствие сохранено и выключено")
    else:
        print("❌ Ошибка:", msg)


def wa_connect_bot(company_name: str, wa_phone: str, block_new_chats: bool | None = None):
    wa_phone = normalize_phone(wa_phone)

    session = get_session()
    try:
        company = session.query(Company).filter_by(name=company_name).first()
        if not company:
            print("❌ Компания не найдена")
            return

        row = session.query(WhatsAppNumber).filter_by(company_id=company.id, phone=wa_phone).first()
        if not row:
            print("❌ Этот WhatsApp номер не привязан к компании (wa_numbers)")
            return

        if block_new_chats is None:
            block_new_chats = bool(getattr(row, "block_new_chats", True))
    finally:
        session.close()

    ok, msg = wa_manager.start_number(company.id, wa_phone, block_new_chats=block_new_chats)
    if ok:
        print(f"✅ WhatsApp бот запущен: company_id={company.id} phone={wa_phone} block_new_chats={block_new_chats}")
        print("ℹ Если требуется QR — открой Web/профиль Playwright как у тебя реализовано.")
    else:
        print("❌ Не удалось запустить WhatsApp:", msg)

# ===========================================================
#  МЕНЮ
# ===========================================================
def main():
    init_db()

    while True:
        print("""
            =========================
                Управление сервером
            =========================
            1) Создать пользователя
            2) Список пользователей
            3) Удалить пользователя

            4) Список компаний
            5) Удалить компанию

            6) Привязать почту Mail.ru к компании
            7) Удалить привязанную почту у компании

            8) Список WhatsApp компании
            9) Удалить WhatsApp у компании

            10) Создать отдел
            11) Список отделов компании
            12) Привязать сотрудника к отделу

            13) Создать регион
            14) Список регионов компании
            15) Назначить сотруднику регион

            16) Отчёт по компании (отделы/регионы/сотрудники)

            17) Добавить сотрудника (с отделом и регионами)

            18) Изменить роль сотрудника
            19) Заблокировать сотрудника
            20) Разблокировать сотрудника

            21) Заблокировать компанию
            22) Разблокировать компанию

            23) Список руководителей отделов
            24) Удалить регион
            25) Переименовать регион
            26) Снять регион у сотрудника

            30) CRM — создать клиента
            31) CRM — список клиентов
            32) CRM — удалить клиента

            40) CRM — создать воронку
            41) CRM — список воронок
            42) CRM — создать этап воронки
            43) CRM — список этапов воронки

            44) CRM — задать маршрут канала (канал -> воронка/этап)
            45) CRM — список маршрутов каналов

            60) WhatsApp — задать приветствие (текст + вкл/выкл)
            61) WhatsApp — подключить (запустить бота) к номеру

            0) Выход

            """)

        choice = input("Выберите действие: ").strip()

        if choice == "1":
            cname = input("Компания: ").strip() or "Default"
            login = input("Логин: ").strip() or "admin"
            role = input("Роль: ").strip() or "Integrator"
            pwd = input("Пароль: ").strip()
            create_user(cname, login, role, pwd)

        elif choice == "2":
            list_users()

        elif choice == "3":
            uid = input("ID пользователя: ").strip()
            delete_user(uid)

        elif choice == "4":
            list_companies()

        elif choice == "5":
            cid = input("ID компании: ").strip()
            delete_company(cid)

        elif choice == "6":
            cname = input("Компания: ").strip()
            email = input("Почта Mail.ru: ").strip()
            pwd = input("Пароль приложения Mail.ru: ").strip()
            setup_mail_for_company(cname, email, pwd)

        elif choice == "7":
             cname = input("Компания: ").strip()
             remove_mail_for_company(cname)

        elif choice == "8":
            cname = input("Компания: ").strip()
            list_whatsapp(cname)

        elif choice == "9":
            cname = input("Компания: ").strip()
            phone = input("Номер WhatsApp: ").strip()
            delete_whatsapp(cname, phone)

        elif choice == "0":
            print("Выход...")
            break

        elif choice == "10":
            cname = input("Компания: ").strip()
            dname = input("Название отдела: ").strip()
            create_department(cname, dname)

        elif choice == "11":
            cname = input("Компания: ").strip()
            list_departments(cname)

        elif choice == "12":
            uid = input("ID сотрудника: ").strip()
            did = input("ID отдела: ").strip()
            assign_user_to_department(uid, did)

        elif choice == "13":
            cname = input("Компания: ").strip()
            rname = input("Название региона: ").strip()
            create_region(cname, rname)

        elif choice == "14":
            cname = input("Компания: ").strip()
            list_regions(cname)

        elif choice == "15":
            uid = input("ID сотрудника: ").strip()
            rid = input("ID региона: ").strip()
            assign_user_to_region(uid, rid)

        elif choice == "16":
            cname = input("Компания: ").strip()
            company_report(cname)

        elif choice == "17":
            cname = input("Компания: ").strip()
            username = input("Логин: ").strip()
            role = input("Роль: ").strip() or "Manager"
            pwd = input("Пароль: ").strip()

            print("\n(Подсказка) Сначала посмотри отделы/регионы через 11 и 14 или через отчёт 16.\n")
            dept_id = input("ID отдела (0 = без отдела): ").strip() or "0"
            region_ids = input("ID регионов через запятую (например 1,2) или пусто: ").strip()

            create_employee_with_dept_and_regions(cname, username, role, pwd, dept_id, region_ids)

        elif choice == "18":
            uid = input("ID сотрудника: ").strip()
            role = input("Новая роль (например Admin/Manager/Integrator/President): ").strip()
            change_user_role(uid, role)

        elif choice == "19":
            uid = input("ID сотрудника: ").strip()
            set_user_block(uid, True)

        elif choice == "20":
            uid = input("ID сотрудника: ").strip()
            set_user_block(uid, False)

        elif choice == "21":
            cid = input("ID компании: ").strip()
            set_company_block(cid, True)

        elif choice == "22":
            cid = input("ID компании: ").strip()
            set_company_block(cid, False)

        elif choice == "23":
            cname = input("Компания: ").strip()
            list_department_heads(cname)

        elif choice == "24":
            cname = input("Компания: ").strip()
            rid = input("ID региона: ").strip()
            delete_region(cname, rid)

        elif choice == "25":
            cname = input("Компания: ").strip()
            rid = input("ID региона: ").strip()
            new_name = input("Новое название: ").strip()
            rename_region(cname, rid, new_name)

        elif choice == "26":
            uid = input("ID сотрудника: ").strip()
            rid = input("ID региона: ").strip()
            unassign_user_from_region(uid, rid)


        elif choice == "30":
            cname = input("Компания: ").strip()
            name = input("Имя клиента: ").strip()
            crm_create_client(cname, name)

        elif choice == "31":
            cname = input("Компания: ").strip()
            crm_list_clients(cname)

        elif choice == "32":
            cid = input("ID клиента: ").strip()
            crm_delete_client(cid)

        elif choice == "40":
            cname = input("Компания: ").strip()
            pname = input("Название воронки: ").strip()
            order_index = input("Порядок (число, по умолчанию 0): ").strip() or "0"
            crm_create_pipeline(cname, pname, int(order_index))

        elif choice == "41":
            cname = input("Компания: ").strip()
            crm_list_pipelines(cname)

        elif choice == "42":
            cname = input("Компания: ").strip()
            pid = input("ID воронки: ").strip()
            sname = input("Название этапа: ").strip()
            order_index = input("Порядок (число, по умолчанию 0): ").strip() or "0"
            is_won = (input("Это этап УСПЕХ? (y/n): ").strip().lower() == "y")
            is_lost = (input("Это этап ОТКАЗ? (y/n): ").strip().lower() == "y")
            crm_create_stage(cname, int(pid), sname, int(order_index), is_won, is_lost)

        elif choice == "43":
            cname = input("Компания: ").strip()
            pid = input("ID воронки: ").strip()
            crm_list_stages(cname, int(pid))

        elif choice == "44":
            cname = input("Компания: ").strip()
            ch = input("Канал (whatsapp/instagram/email/manual/other): ").strip()
            pid = input("pipeline_id (пусто = None): ").strip()
            sid = input("stage_id (пусто = None): ").strip()

            pipeline_id = int(pid) if pid.isdigit() else None
            stage_id = int(sid) if sid.isdigit() else None

            crm_set_channel_route(cname, ch, pipeline_id, stage_id)

        elif choice == "45":
            cname = input("Компания: ").strip()
            crm_list_channel_routes(cname)

        elif choice == "60":
            cname = input("Компания: ").strip()
            phone = input("Номер WhatsApp интеграции (wa_phone): ").strip()

            enabled_inp = input("Включить приветствие? (y/n, по умолчанию y): ").strip().lower()
            enabled = (enabled_inp != "n")

            print("Введите приветственный текст. Для окончания ввода: пустая строка.")
            lines = []
            while True:
                line = input()
                if line == "":
                    break
                lines.append(line)

            text = "\n".join(lines).strip()
            wa_set_greeting(cname, phone, text, enabled=enabled)

        elif choice == "61":
            cname = input("Компания: ").strip()
            phone = input("Номер WhatsApp интеграции (wa_phone): ").strip()

            bn = input("block_new_chats? (y/n, пусто = как в БД): ").strip().lower()
            if bn == "y":
                block_new_chats = True
            elif bn == "n":
                block_new_chats = False
            else:
                block_new_chats = None

            wa_connect_bot(cname, phone, block_new_chats=block_new_chats)

        else:
            print("❌ Неверный выбор")




if __name__ == "__main__":
    main()
