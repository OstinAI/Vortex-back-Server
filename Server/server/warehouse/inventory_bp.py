# -*- coding: utf-8 -*-
import time
from flask import Blueprint, jsonify, request
from sqlalchemy import or_
from db.models import Warehouse, StockMovement, Product, User
from db.models import ProductFile, StoredFile

from db.models import SaleServiceLine
from db.models import SaleState
from utils.security import token_required
from db.connection import get_session
from db.models import (
    InventoryRegion, InventoryCategory, Product, ProductRegionPrice,
    ProductFieldDefinition, ProductFieldValue,
    ClientAssignment, User,
    Warehouse, StockMovement
)

inventory_bp = Blueprint("inventory", __name__)

def _now_ms() -> int:
    return int(time.time() * 1000)

def _payload():
    return getattr(request, "user", None) or {}

def _company_id() -> int:
    p = _payload()
    return int(p.get("company_id") or p.get("companyId") or 0)

def _user_id() -> int:
    p = _payload()
    return int(p.get("user_id") or p.get("userId") or p.get("id") or 0)

def _role() -> str:
    p = _payload()
    return str(p.get("role") or "")

def _can_manage_inventory() -> bool:
    role = (_role() or "").strip().lower()
    return role in ("admin", "integrator", "warehousehead")

def _int_or_none(x):
    try:
        if x is None: return None
        return int(x)
    except:
        return None

def _clean_kind(v: str) -> str:
    v = (v or "").strip().lower()
    return v if v in ("product", "service") else "product"

def _clean_field_type(v: str) -> str:
    v = (v or "").strip().lower()
    allowed = {"text", "number", "bool", "date", "select"}
    return v if v in allowed else "text"

def _my_department_id(s, company_id: int, user_id: int) -> int:
    if company_id <= 0 or user_id <= 0:
        return 0
    u = s.query(User).filter_by(id=int(user_id), company_id=int(company_id)).first()
    return int(getattr(u, "department_id", 0) or 0) if u else 0

def _apply_acl_query_products(q, s, company_id: int, role: str, user_id: int, dep_id: int):
    """
    Доступ как в задачах/заметках:
    - Admin/Integrator/Director/President -> всё
    - Руководитель отдела (is_department_head=True) -> только свой отдел (по dep_id через создателя/назначенных нет, тут просто общий доступ на просмотр складских данных обычно всем)
    - User -> всё по компании (склад обычно общий). Если хочешь ограничить — скажи, сделаю.
    """
    role_norm = (role or "").strip().lower()
    if role_norm in ("admin", "integrator", "director", "president"):
        return q
    return q


# ============================
# REGIONS
# ============================

@inventory_bp.route("/regions", methods=["GET"])
@token_required
def list_regions():
    company_id = _company_id()
    s = get_session()
    try:
        rows = (
            s.query(InventoryRegion)
             .filter(InventoryRegion.company_id == company_id)
             .filter(InventoryRegion.is_enabled == True)
             .order_by(InventoryRegion.name.asc())
             .all()
        )
        items = [{"id": int(r.id), "name": r.name} for r in rows]
        return jsonify({"ok": True, "regions": items}), 200
    finally:
        s.close()

@inventory_bp.route("/regions", methods=["POST"])
@token_required
def create_region():
    company_id = _company_id()
    if not _can_manage_inventory():
        return jsonify({"ok": False, "message": "ACCESS_DENIED"}), 403

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "message": "NAME_REQUIRED"}), 400

    s = get_session()
    try:
        exists = (
            s.query(InventoryRegion)
             .filter(InventoryRegion.company_id == company_id, InventoryRegion.name == name)
             .first()
        )
        if exists:
            return jsonify({"ok": False, "message": "ALREADY_EXISTS"}), 400

        row = InventoryRegion(company_id=company_id, name=name, is_enabled=True, created_ts_ms=_now_ms())
        s.add(row)
        s.commit()
        return jsonify({"ok": True, "region": {"id": int(row.id), "name": row.name}}), 200
    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "CREATE_FAILED", "error": str(e)}), 500
    finally:
        s.close()

@inventory_bp.route("/regions/<int:region_id>", methods=["DELETE"])
@token_required
def delete_region(region_id: int):
    company_id = _company_id()
    if not _can_manage_inventory():
        return jsonify({"ok": False, "message": "ACCESS_DENIED"}), 403

    s = get_session()
    try:
        row = s.query(InventoryRegion).filter_by(company_id=company_id, id=int(region_id)).first()
        if not row:
            return jsonify({"ok": False, "message": "NOT_FOUND"}), 404

        row.is_enabled = False
        s.commit()
        return jsonify({"ok": True, "message": "DISABLED"}), 200
    finally:
        s.close()


# ============================
# CATEGORIES
# ============================

@inventory_bp.route("/categories", methods=["GET"])
@token_required
def list_categories():
    company_id = _company_id()
    s = get_session()
    try:
        rows = (
            s.query(InventoryCategory)
             .filter(InventoryCategory.company_id == company_id)
             .filter(InventoryCategory.is_enabled == True)
             .order_by(InventoryCategory.name.asc())
             .all()
        )
        items = [{
            "id": int(c.id),
            "name": c.name,
            "parent_id": int(c.parent_id) if c.parent_id else None
        } for c in rows]
        return jsonify({"ok": True, "categories": items}), 200
    finally:
        s.close()

@inventory_bp.route("/categories", methods=["POST"])
@token_required
def create_category():
    company_id = _company_id()
    if not _can_manage_inventory():
        return jsonify({"ok": False, "message": "ACCESS_DENIED"}), 403

   
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    parent_id = _int_or_none(data.get("parent_id"))

    if not name:
        return jsonify({"ok": False, "message": "NAME_REQUIRED"}), 400

    s = get_session()
    try:
        exists = (
            s.query(InventoryCategory)
             .filter(InventoryCategory.company_id == company_id, InventoryCategory.name == name)
             .first()
        )
        if exists:
            return jsonify({"ok": False, "message": "ALREADY_EXISTS"}), 400

        if parent_id:
            p = s.query(InventoryCategory).filter_by(company_id=company_id, id=int(parent_id)).first()
            if not p:
                return jsonify({"ok": False, "message": "PARENT_NOT_FOUND"}), 404

        row = InventoryCategory(
            company_id=company_id,
            name=name,
            parent_id=int(parent_id) if parent_id else None,
            is_enabled=True,
            created_ts_ms=_now_ms()
        )
        s.add(row)
        s.commit()
        return jsonify({"ok": True, "category": {"id": int(row.id), "name": row.name, "parent_id": row.parent_id}}), 200
    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "CREATE_FAILED", "error": str(e)}), 500
    finally:
        s.close()

@inventory_bp.route("/categories/<int:category_id>", methods=["DELETE"])
@token_required
def delete_category(category_id: int):
    company_id = _company_id()
    s = get_session()
    try:
        row = s.query(InventoryCategory).filter_by(company_id=company_id, id=int(category_id)).first()
        if not row:
            return jsonify({"ok": False, "message": "NOT_FOUND"}), 404

        row.is_enabled = False
        s.commit()
        return jsonify({"ok": True, "message": "DISABLED"}), 200
    finally:
        s.close()

@inventory_bp.route("/categories/<int:category_id>", methods=["POST"])
@token_required
def update_category(category_id: int):
    company_id = _company_id()
    if not _can_manage_inventory():
        return jsonify({"ok": False, "message": "ACCESS_DENIED"}), 403

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    parent_id = _int_or_none(data.get("parent_id"))

    if not name:
        return jsonify({"ok": False, "message": "NAME_REQUIRED"}), 400

    s = get_session()
    try:
        row = s.query(InventoryCategory).filter_by(company_id=company_id, id=int(category_id)).first()
        if not row or not row.is_enabled:
            return jsonify({"ok": False, "message": "NOT_FOUND"}), 404

        # дубль по имени (кроме самой себя)
        exists = (
            s.query(InventoryCategory)
             .filter(InventoryCategory.company_id == company_id)
             .filter(InventoryCategory.is_enabled == True)
             .filter(InventoryCategory.name == name)
             .filter(InventoryCategory.id != int(category_id))
             .first()
        )
        if exists:
            return jsonify({"ok": False, "message": "ALREADY_EXISTS"}), 400

        # parent (опционально)
        if parent_id:
            if int(parent_id) == int(category_id):
                return jsonify({"ok": False, "message": "BAD_PARENT_ID"}), 400
            p = s.query(InventoryCategory).filter_by(company_id=company_id, id=int(parent_id), is_enabled=True).first()
            if not p:
                return jsonify({"ok": False, "message": "PARENT_NOT_FOUND"}), 404
            row.parent_id = int(parent_id)
        elif "parent_id" in data:
            row.parent_id = None

        row.name = name

        if hasattr(row, "updated_ts_ms"):
            row.updated_ts_ms = _now_ms()

        s.commit()
        return jsonify({"ok": True, "category": {"id": int(row.id), "name": row.name, "parent_id": row.parent_id}}), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "UPDATE_FAILED", "error": str(e)}), 500
    finally:
        s.close()
        
# ============================
# PRODUCTS
# ============================

def _next_product_no(s, company_id: int) -> int:
    # max(product_no) + 1
    mx = s.query(Product.product_no).filter(Product.company_id == company_id).order_by(Product.product_no.desc()).first()
    return int(mx[0] or 0) + 1 if mx else 1

@inventory_bp.route("/products", methods=["GET"])
@token_required
def list_products():
    company_id = _company_id()
    role = _role()
    user_id = _user_id()

    category_id = _int_or_none(request.args.get("category_id"))
    region_id = _int_or_none(request.args.get("region_id"))
    qtxt = (request.args.get("q") or "").strip()
    limit = _int_or_none(request.args.get("limit")) or 200
    if limit < 1: limit = 1
    if limit > 500: limit = 500

    s = get_session()
    try:
        q = s.query(Product).filter(Product.company_id == company_id).filter(Product.is_enabled == True)

        dep_id = _my_department_id(s, company_id, user_id)
        q = _apply_acl_query_products(q, s, company_id, role, user_id, dep_id)

        if category_id:
            q = q.filter(Product.category_id == int(category_id))

        if qtxt:
            like = f"%{qtxt.lower()}%"
            q = q.filter(or_(Product.title.ilike(like), Product.description.ilike(like)))

        rows = q.order_by(Product.product_no.asc()).limit(int(limit)).all()

        items = []
        for p in rows:
            price = p.base_price
            if region_id:
                pr = (
                    s.query(ProductRegionPrice)
                     .filter_by(company_id=company_id, product_id=int(p.id), region_id=int(region_id))
                     .first()
                )
                if pr:
                    price = float(pr.price)

            items.append({
                "id": int(p.id),
                "product_no": int(p.product_no),
                "kind": p.kind or "product",
                "category_id": int(p.category_id) if p.category_id else None,
                "title": p.title or "",
                "description": p.description or "",
                "base_price": p.base_price,
                "price": price,
                "main_image_file_id": int(p.main_image_file_id) if p.main_image_file_id else None,
                "main_video_file_id": int(p.main_video_file_id) if p.main_video_file_id else None,
                "created_ts_ms": int(p.created_ts_ms or 0),
                "updated_ts_ms": int(p.updated_ts_ms or 0),
            })

        return jsonify({"ok": True, "products": items}), 200
    finally:
        s.close()

@inventory_bp.route("/products", methods=["POST"])
@token_required
def create_product():
    company_id = _company_id()
    if not _can_manage_inventory():
        return jsonify({"ok": False, "message": "ACCESS_DENIED"}), 403

    creator_id = _user_id()
    data = request.get_json(silent=True) or {}

    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"ok": False, "message": "TITLE_REQUIRED"}), 400

    kind = _clean_kind(data.get("kind"))
    description = data.get("description") or ""
    category_id = _int_or_none(data.get("category_id"))
    base_price = data.get("base_price")
    main_image_file_id = _int_or_none(data.get("main_image_file_id"))
    main_video_file_id = _int_or_none(data.get("main_video_file_id"))

    s = get_session()
    try:
        if category_id:
            cat = s.query(InventoryCategory).filter_by(company_id=company_id, id=int(category_id), is_enabled=True).first()
            if not cat:
                return jsonify({"ok": False, "message": "CATEGORY_NOT_FOUND"}), 404

        no = _next_product_no(s, company_id)
        now = _now_ms()

        row = Product(
            company_id=company_id,
            product_no=int(no),
            category_id=int(category_id) if category_id else None,
            kind=kind,
            title=title,
            description=str(description or ""),
            base_price=float(base_price) if base_price is not None else None,
            main_image_file_id=int(main_image_file_id) if main_image_file_id else None,
            main_video_file_id=int(main_video_file_id) if main_video_file_id else None,
            is_enabled=True,
            created_ts_ms=now,
            updated_ts_ms=now
        )
        s.add(row)
        s.commit()

        return jsonify({"ok": True, "product_id": int(row.id), "product_no": int(row.product_no)}), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "CREATE_FAILED", "error": str(e)}), 500
    finally:
        s.close()

@inventory_bp.route("/products/<int:product_id>", methods=["POST"])
@token_required
def update_product(product_id: int):
    company_id = _company_id()
    if not _can_manage_inventory():
        return jsonify({"ok": False, "message": "ACCESS_DENIED"}), 403

    data = request.get_json(silent=True) or {}

    s = get_session()
    try:
        p = s.query(Product).filter_by(company_id=company_id, id=int(product_id)).first()
        if not p or not p.is_enabled:
            return jsonify({"ok": False, "message": "NOT_FOUND"}), 404

        if "title" in data:
            t = (data.get("title") or "").strip()
            if not t:
                return jsonify({"ok": False, "message": "TITLE_REQUIRED"}), 400
            p.title = t

        if "description" in data:
            p.description = str(data.get("description") or "")

        if "kind" in data:
            p.kind = _clean_kind(data.get("kind"))

        if "category_id" in data:
            cid = _int_or_none(data.get("category_id"))
            if cid:
                cat = s.query(InventoryCategory).filter_by(company_id=company_id, id=int(cid), is_enabled=True).first()
                if not cat:
                    return jsonify({"ok": False, "message": "CATEGORY_NOT_FOUND"}), 404
                p.category_id = int(cid)
            else:
                p.category_id = None

        if "base_price" in data:
            v = data.get("base_price")
            p.base_price = float(v) if v is not None else None

        if "main_image_file_id" in data:
            v = _int_or_none(data.get("main_image_file_id"))
            p.main_image_file_id = int(v) if v else None

        if "main_video_file_id" in data:
            v = _int_or_none(data.get("main_video_file_id"))
            p.main_video_file_id = int(v) if v else None

        p.updated_ts_ms = _now_ms()
        s.commit()
        return jsonify({"ok": True}), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "UPDATE_FAILED", "error": str(e)}), 500
    finally:
        s.close()

@inventory_bp.route("/products/<int:product_id>", methods=["DELETE"])
@token_required
def delete_product(product_id: int):
    company_id = _company_id()
    if not _can_manage_inventory():
        return jsonify({"ok": False, "message": "ACCESS_DENIED"}), 403

    s = get_session()
    try:
        p = s.query(Product).filter_by(company_id=company_id, id=int(product_id)).first()
        if not p:
            return jsonify({"ok": False, "message": "NOT_FOUND"}), 404
        p.is_enabled = False
        p.updated_ts_ms = _now_ms()
        s.commit()
        return jsonify({"ok": True, "message": "DISABLED"}), 200
    finally:
        s.close()

@inventory_bp.route("/products/<int:product_id>/files", methods=["POST"])
@token_required
def attach_product_files(product_id: int):
    company_id = _company_id()
    if not _can_manage_inventory():
        return jsonify({"ok": False, "message": "ACCESS_DENIED"}), 403

    data = request.get_json(silent=True) or {}
    files = data.get("files") or []
    if not isinstance(files, list) or len(files) == 0:
        return jsonify({"ok": False, "message": "FILES_REQUIRED"}), 400

    s = get_session()
    try:
        p = s.query(Product).filter_by(company_id=company_id, id=int(product_id), is_enabled=True).first()
        if not p:
            return jsonify({"ok": False, "message": "PRODUCT_NOT_FOUND"}), 404

        img_count = s.query(ProductFile).filter_by(company_id=company_id, product_id=int(product_id), kind="image").count()
        vid_count = s.query(ProductFile).filter_by(company_id=company_id, product_id=int(product_id), kind="video").count()

        now = _now_ms()
        attached = []

        for item in files:
            fid = _int_or_none(item.get("file_id"))
            kind = (item.get("kind") or "image").strip().lower()
            sort_index = int(item.get("sort_index") or 0)
            is_main = bool(item.get("is_main", False))

            if not fid:
                continue
            if kind not in ("image", "video"):
                kind = "image"

            sf = s.query(StoredFile).filter_by(company_id=company_id, id=int(fid)).first()
            if not sf:
                continue

            exists = s.query(ProductFile).filter_by(company_id=company_id, product_id=int(product_id), file_id=int(fid)).first()
            if exists:
                continue

            if kind == "image":
                if img_count >= 10: 
                    continue
                img_count += 1
            else:
                if vid_count >= 3:
                    continue
                vid_count += 1

            if is_main:
                s.query(ProductFile).filter_by(company_id=company_id, product_id=int(product_id), kind=kind).update({"is_main": False})
                if kind == "image":
                    p.main_image_file_id = int(fid)
                else:
                    p.main_video_file_id = int(fid)

            row = ProductFile(
                company_id=company_id,
                product_id=int(product_id),
                file_id=int(fid),
                kind=kind,
                sort_index=int(sort_index),
                is_main=bool(is_main),
                created_ts_ms=now
            )
            s.add(row)
            s.flush()
            attached.append(int(row.id))

        p.updated_ts_ms = now
        s.commit()
        return jsonify({"ok": True, "attached_ids": attached}), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "ATTACH_FAILED", "error": str(e)}), 500
    finally:
        s.close()

@inventory_bp.route("/products/<int:product_id>/files", methods=["GET"])
@token_required
def list_product_files(product_id: int):
    company_id = _company_id()

    s = get_session()
    try:
        p = s.query(Product).filter_by(company_id=company_id, id=int(product_id), is_enabled=True).first()
        if not p:
            return jsonify({"ok": False, "message": "PRODUCT_NOT_FOUND"}), 404

        rows = (
            s.query(ProductFile, StoredFile)
            .join(StoredFile, StoredFile.id == ProductFile.file_id)
            .filter(ProductFile.company_id == company_id, ProductFile.product_id == int(product_id))
            .order_by(ProductFile.kind.asc(), ProductFile.is_main.desc(), ProductFile.sort_index.asc(), ProductFile.id.asc())
            .all()
        )

        out = []
        for pf, sf in rows:
            out.append({
                "id": int(pf.id),
                "file_id": int(pf.file_id),
                "kind": pf.kind or "image",             # image/video
                "sort_index": int(pf.sort_index or 0),
                "is_main": bool(pf.is_main),

                # доп. поля (чтобы на клиенте красиво показывать)
                "original_name": getattr(sf, "original_name", None) or getattr(sf, "name", None) or "",
                "size": int(getattr(sf, "size", 0) or 0),
            })

        return jsonify({"ok": True, "files": out}), 200
    finally:
        s.close()

@inventory_bp.route("/products/<int:product_id>/files/<int:file_id>", methods=["DELETE"])
@token_required
def delete_product_file(product_id: int, file_id: int):
    company_id = _company_id()
    if not _can_manage_inventory():
        return jsonify({"ok": False, "message": "ACCESS_DENIED"}), 403

    s = get_session()
    try:
        p = s.query(Product).filter_by(company_id=company_id, id=int(product_id), is_enabled=True).first()
        if not p:
            return jsonify({"ok": False, "message": "PRODUCT_NOT_FOUND"}), 404

        row = s.query(ProductFile).filter_by(company_id=company_id, product_id=int(product_id), file_id=int(file_id)).first()
        if not row:
            return jsonify({"ok": False, "message": "FILE_NOT_FOUND"}), 404

        kind = row.kind or "image"
        was_main = bool(row.is_main)

        s.delete(row)
        s.flush()

        # если удалили главный — сбросить main_*_file_id
        if was_main:
            if kind == "image":
                p.main_image_file_id = None
            else:
                p.main_video_file_id = None

            # назначим новый main (первый по sort_index)
            repl = (
                s.query(ProductFile)
                .filter_by(company_id=company_id, product_id=int(product_id), kind=kind)
                .order_by(ProductFile.sort_index.asc(), ProductFile.id.asc())
                .first()
            )
            if repl:
                repl.is_main = True
                if kind == "image":
                    p.main_image_file_id = int(repl.file_id)
                else:
                    p.main_video_file_id = int(repl.file_id)

        p.updated_ts_ms = _now_ms()
        s.commit()
        return jsonify({"ok": True}), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "DELETE_FAILED", "error": str(e)}), 500
    finally:
        s.close()

# ============================
# REGION PRICES
# ============================

@inventory_bp.route("/products/<int:product_id>/prices", methods=["POST"])
@token_required
def set_region_price(product_id: int):
    """
    POST /api/inventory/products/<id>/prices
    body: { "region_id": 2, "price": 12345 }
    """
    company_id = _company_id()
    data = request.get_json(silent=True) or {}
    region_id = _int_or_none(data.get("region_id"))
    price = data.get("price")

    if not region_id:
        return jsonify({"ok": False, "message": "REGION_ID_REQUIRED"}), 400
    if price is None:
        return jsonify({"ok": False, "message": "PRICE_REQUIRED"}), 400

    s = get_session()
    try:
        p = s.query(Product).filter_by(company_id=company_id, id=int(product_id), is_enabled=True).first()
        if not p:
            return jsonify({"ok": False, "message": "PRODUCT_NOT_FOUND"}), 404

        r = s.query(InventoryRegion).filter_by(company_id=company_id, id=int(region_id), is_enabled=True).first()
        if not r:
            return jsonify({"ok": False, "message": "REGION_NOT_FOUND"}), 404

        now = _now_ms()

        row = (
            s.query(ProductRegionPrice)
             .filter_by(company_id=company_id, product_id=int(product_id), region_id=int(region_id))
             .first()
        )
        if not row:
            row = ProductRegionPrice(
                company_id=company_id,
                product_id=int(product_id),
                region_id=int(region_id),
                price=float(price),
                created_ts_ms=now,
                updated_ts_ms=now
            )
            s.add(row)
        else:
            row.price = float(price)
            row.updated_ts_ms = now

        s.commit()
        return jsonify({"ok": True}), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "SAVE_FAILED", "error": str(e)}), 500
    finally:
        s.close()


# ============================
# FLEX FIELDS (DEFINITIONS)
# ============================

@inventory_bp.route("/fields", methods=["GET"])
@token_required
def list_product_fields():
    """
    GET /api/inventory/fields?category_id=...&region_id=...
    Возвращает: company + category + region
    """
    company_id = _company_id()
    category_id = _int_or_none(request.args.get("category_id"))
    region_id = _int_or_none(request.args.get("region_id"))

    s = get_session()
    try:
        rows = (
            s.query(ProductFieldDefinition)
             .filter(ProductFieldDefinition.company_id == company_id)
             .filter(ProductFieldDefinition.is_enabled == True)
             .all()
        )

        items = []
        for f in rows:
            st = (f.scope_type or "company").lower()
            sid = int(f.scope_id or 0)

            ok = False
            if st == "company" and sid == 0:
                ok = True
            elif st == "category" and category_id and sid == int(category_id):
                ok = True
            elif st == "region" and region_id and sid == int(region_id):
                ok = True

            if not ok:
                continue

            items.append({
                "id": int(f.id),
                "scope_type": f.scope_type,
                "scope_id": int(f.scope_id),
                "key": f.key,
                "title": f.title,
                "type": f.type,
                "required": bool(f.required),
                "order_index": int(f.order_index),
                "options_json": f.options_json or "",
            })

        items.sort(key=lambda x: (x["order_index"], x["id"]))
        return jsonify({"ok": True, "fields": items}), 200
    finally:
        s.close()

@inventory_bp.route("/fields", methods=["POST"])
@token_required
def upsert_product_field():
    """
    POST /api/inventory/fields
    body:
    {
      "id": optional,
      "scope_type": "company"|"category"|"region",
      "scope_id": 0|<category_id>|<region_id>,
      "key": "tnved",
      "title": "Код ТН ВЭД",
      "type": "text"|"number"|"bool"|"date"|"select",
      "required": false,
      "order_index": 0,
      "options_json": "[]"
    }
    """
    company_id = _company_id()
    role = (_role() or "").strip().lower()
    if role not in ("admin", "integrator", "director", "president"):
        return jsonify({"ok": False, "message": "ACCESS_DENIED"}), 403

    data = request.get_json(silent=True) or {}

    fid = _int_or_none(data.get("id"))
    scope_type = (data.get("scope_type") or "company").strip().lower()
    scope_id = int(data.get("scope_id") or 0)

    key = (data.get("key") or "").strip()
    title = (data.get("title") or "").strip()
    ftype = _clean_field_type(data.get("type"))
    required = bool(data.get("required", False))
    order_index = int(data.get("order_index") or 0)
    options_json = data.get("options_json") or ""

    if scope_type not in ("company", "category", "region"):
        return jsonify({"ok": False, "message": "BAD_SCOPE_TYPE"}), 400
    if scope_type == "company":
        scope_id = 0
    if scope_type in ("category", "region") and scope_id <= 0:
        return jsonify({"ok": False, "message": "SCOPE_ID_REQUIRED"}), 400
    if not key or not title:
        return jsonify({"ok": False, "message": "KEY_TITLE_REQUIRED"}), 400

    s = get_session()
    try:
        if fid:
            row = s.query(ProductFieldDefinition).filter_by(company_id=company_id, id=int(fid)).first()
            if not row:
                return jsonify({"ok": False, "message": "NOT_FOUND"}), 404
        else:
            row = ProductFieldDefinition(company_id=company_id, created_ts_ms=_now_ms())
            s.add(row)

        row.scope_type = scope_type
        row.scope_id = int(scope_id)
        row.key = key
        row.title = title
        row.type = ftype
        row.required = required
        row.order_index = order_index
        row.options_json = options_json
        row.is_enabled = True
        row.updated_ts_ms = _now_ms()

        s.commit()
        return jsonify({"ok": True, "field_id": int(row.id)}), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "UPSERT_FAILED", "error": str(e)}), 500
    finally:
        s.close()

@inventory_bp.route("/fields/<int:field_id>/disable", methods=["POST"])
@token_required
def disable_product_field(field_id: int):
    company_id = _company_id()
    role = (_role() or "").strip().lower()
    if role not in ("admin", "integrator", "director", "president"):
        return jsonify({"ok": False, "message": "ACCESS_DENIED"}), 403

    s = get_session()
    try:
        row = s.query(ProductFieldDefinition).filter_by(company_id=company_id, id=int(field_id)).first()
        if not row:
            return jsonify({"ok": False, "message": "NOT_FOUND"}), 404
        row.is_enabled = False
        row.updated_ts_ms = _now_ms()
        s.commit()
        return jsonify({"ok": True}), 200
    finally:
        s.close()


# ============================
# FLEX VALUES (PRODUCT CARD)
# ============================

@inventory_bp.route("/products/<int:product_id>/card", methods=["GET"])
@token_required
def get_product_card(product_id: int):
    """
    Возвращает:
    - product
    - fields (company + category + region optional via query)
    - values
    query: ?category_id=..&region_id=..
    """
    company_id = _company_id()
    category_id = _int_or_none(request.args.get("category_id"))
    region_id = _int_or_none(request.args.get("region_id"))

    s = get_session()
    try:
        p = s.query(Product).filter_by(company_id=company_id, id=int(product_id), is_enabled=True).first()
        if not p:
            return jsonify({"ok": False, "message": "PRODUCT_NOT_FOUND"}), 404

        # fields
        defs = (
            s.query(ProductFieldDefinition)
             .filter(ProductFieldDefinition.company_id == company_id)
             .filter(ProductFieldDefinition.is_enabled == True)
             .all()
        )

        fields = []
        field_ids = []
        for f in defs:
            st = (f.scope_type or "company").lower()
            sid = int(f.scope_id or 0)

            ok = False
            if st == "company" and sid == 0:
                ok = True
            elif st == "category" and category_id and sid == int(category_id):
                ok = True
            elif st == "region" and region_id and sid == int(region_id):
                ok = True

            if not ok:
                continue

            fields.append({
                "id": int(f.id),
                "key": f.key,
                "title": f.title,
                "type": f.type,
                "required": bool(f.required),
                "order_index": int(f.order_index),
                "options_json": f.options_json or "",
            })
            field_ids.append(int(f.id))

        fields.sort(key=lambda x: (x["order_index"], x["id"]))

        # values
        vals = []
        if field_ids:
            rows = (
                s.query(ProductFieldValue)
                 .filter(ProductFieldValue.company_id == company_id)
                 .filter(ProductFieldValue.product_id == int(p.id))
                 .filter(ProductFieldValue.field_id.in_(field_ids))
                 .all()
            )
            for v in rows:
                vals.append({
                    "field_id": int(v.field_id),
                    "value_text": v.value_text or "",
                    "value_number": v.value_number,
                    "value_bool": v.value_bool,
                    "value_ts_ms": v.value_ts_ms,
                })

        return jsonify({
            "ok": True,
            "product": {
                "id": int(p.id),
                "product_no": int(p.product_no),
                "kind": p.kind or "product",
                "category_id": int(p.category_id) if p.category_id else None,
                "title": p.title or "",
                "description": p.description or "",
                "base_price": p.base_price,
                "main_image_file_id": int(p.main_image_file_id) if p.main_image_file_id else None,
                "main_video_file_id": int(p.main_video_file_id) if p.main_video_file_id else None,
            },
            "fields": fields,
            "values": vals,
        }), 200
    finally:
        s.close()

@inventory_bp.route("/products/<int:product_id>/values", methods=["POST"])
@token_required
def save_product_values(product_id: int):
    """
    body:
    { "values": [ {"field_id": 10, "value": "123"}, {"field_id": 11, "value": 555} ] }
    """
    company_id = _company_id()
    data = request.get_json(silent=True) or {}
    values = data.get("values") or []

    s = get_session()
    try:
        p = s.query(Product).filter_by(company_id=company_id, id=int(product_id), is_enabled=True).first()
        if not p:
            return jsonify({"ok": False, "message": "PRODUCT_NOT_FOUND"}), 404

        defs = (
            s.query(ProductFieldDefinition)
             .filter_by(company_id=company_id, is_enabled=True)
             .all()
        )
        defs_map = {int(f.id): f for f in defs}

        now = _now_ms()

        for item in values:
            fid = int(item.get("field_id") or 0)
            if fid <= 0:
                continue
            fdef = defs_map.get(fid)
            if not fdef:
                continue

            v = item.get("value")

            row = (
                s.query(ProductFieldValue)
                 .filter_by(company_id=company_id, product_id=int(p.id), field_id=fid)
                 .first()
            )
            if not row:
                row = ProductFieldValue(company_id=company_id, product_id=int(p.id), field_id=fid, created_ts_ms=now)
                s.add(row)

            row.value_text = ""
            row.value_number = None
            row.value_bool = None
            row.value_ts_ms = None

            t = (fdef.type or "text").lower()

            if t in ("text", "select"):
                row.value_text = "" if v is None else str(v)
            elif t == "number":
                try:
                    row.value_number = float(v)
                except Exception:
                    row.value_number = None
            elif t == "bool":
                row.value_bool = bool(v)
            elif t == "date":
                try:
                    row.value_ts_ms = int(v)
                except Exception:
                    row.value_ts_ms = None
            else:
                row.value_text = "" if v is None else str(v)

            row.updated_ts_ms = now

        s.commit()
        return jsonify({"ok": True}), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "SAVE_FAILED", "error": str(e)}), 500
    finally:
        s.close()

# ============================
# WAREHOUSES
# ============================

@inventory_bp.route("/warehouses", methods=["GET"])
@token_required
def list_warehouses():
    company_id = _company_id()
    region_id = _int_or_none(request.args.get("region_id"))

    s = get_session()
    try:
        q = (
            s.query(Warehouse)
             .filter(Warehouse.company_id == company_id)
             .filter(Warehouse.is_enabled == True)
        )
        if region_id:
            q = q.filter(Warehouse.region_id == int(region_id))

        rows = q.order_by(Warehouse.name.asc()).all()

        items = []
        for w in rows:
            items.append({
                "id": int(w.id),
                "name": w.name or "",
                "region_id": int(w.region_id) if w.region_id else None,
                "address": w.address or ""
            })

        return jsonify({"ok": True, "warehouses": items}), 200
    finally:
        s.close()


@inventory_bp.route("/warehouses", methods=["POST"])
@token_required
def create_warehouse():
    company_id = _company_id()
    if not _can_manage_inventory():
        return jsonify({"ok": False, "message": "ACCESS_DENIED"}), 403

    data = request.get_json(silent=True) or {}

    name = (data.get("name") or "").strip()
    address = data.get("address") or ""
    region_id = _int_or_none(data.get("region_id"))

    if not name:
        return jsonify({"ok": False, "message": "NAME_REQUIRED"}), 400

    s = get_session()
    try:
        if region_id:
            r = s.query(InventoryRegion).filter_by(company_id=company_id, id=int(region_id), is_enabled=True).first()
            if not r:
                return jsonify({"ok": False, "message": "REGION_NOT_FOUND"}), 404

        exists = (
            s.query(Warehouse)
             .filter(Warehouse.company_id == company_id, Warehouse.name == name)
             .first()
        )
        if exists:
            return jsonify({"ok": False, "message": "ALREADY_EXISTS"}), 400

        row = Warehouse(
            company_id=company_id,
            name=name,
            address=str(address or ""),
            region_id=int(region_id) if region_id else None,
            is_enabled=True,
            created_ts_ms=_now_ms()
        )
        s.add(row)
        s.commit()

        return jsonify({"ok": True, "warehouse": {"id": int(row.id), "name": row.name}}), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "CREATE_FAILED", "error": str(e)}), 500
    finally:
        s.close()


@inventory_bp.route("/warehouses/<int:warehouse_id>", methods=["DELETE"])
@token_required
def disable_warehouse(warehouse_id: int):
    company_id = _company_id()
    if not _can_manage_inventory():
        return jsonify({"ok": False, "message": "ACCESS_DENIED"}), 403

    s = get_session()
    try:
        w = s.query(Warehouse).filter_by(company_id=company_id, id=int(warehouse_id)).first()
        if not w:
            return jsonify({"ok": False, "message": "NOT_FOUND"}), 404
        w.is_enabled = False
        s.commit()
        return jsonify({"ok": True, "message": "DISABLED"}), 200
    finally:
        s.close()


# ============================
# STOCK MOVEMENTS (IN/OUT/ADJUST/TRANSFER)
# ============================

def _clean_movement_type(v: str) -> str:
    v = (v or "").strip().upper()
    allowed = {"IN", "OUT", "ADJUST", "TRANSFER_IN", "TRANSFER_OUT"}
    return v if v in allowed else ""

def _float_or_none(x):
    try:
        if x is None:
            return None
        return float(x)
    except:
        return None

def _current_stock(s, company_id: int, warehouse_id: int, product_id: int) -> float:
    rows = (
        s.query(StockMovement.movement_type, StockMovement.qty)
         .filter(StockMovement.company_id == company_id)
         .filter(StockMovement.warehouse_id == int(warehouse_id))
         .filter(StockMovement.product_id == int(product_id))
         .all()
    )
    stock = 0.0
    for mt, qty in rows:
        q = float(qty or 0.0)
        mt = (mt or "").upper()
        if mt in ("IN", "TRANSFER_IN"):
            stock += q
        elif mt in ("OUT", "TRANSFER_OUT"):
            stock -= q
        elif mt == "ADJUST":
            # ADJUST: qty может быть положит или отриц, но мы храним qty положит. поэтому ADJUST делаем через reason: + или -
            # Упростим: если хочешь корректировку с +/-, просто используй IN или OUT.
            stock += q
    return float(stock)


@inventory_bp.route("/stock", methods=["GET"])
@token_required
def get_stock():
    """
    GET /api/inventory/stock?warehouse_id=1&product_id=2
    или
    GET /api/inventory/stock?warehouse_id=1  (все товары склада)
    """
    company_id = _company_id()
    warehouse_id = _int_or_none(request.args.get("warehouse_id"))
    product_id = _int_or_none(request.args.get("product_id"))

    if not warehouse_id:
        return jsonify({"ok": False, "message": "WAREHOUSE_ID_REQUIRED"}), 400

    s = get_session()
    try:
        w = s.query(Warehouse).filter_by(company_id=company_id, id=int(warehouse_id), is_enabled=True).first()
        if not w:
            return jsonify({"ok": False, "message": "WAREHOUSE_NOT_FOUND"}), 404

        if product_id:
            stock = _current_stock(s, company_id, int(warehouse_id), int(product_id))
            return jsonify({"ok": True, "warehouse_id": int(warehouse_id), "product_id": int(product_id), "stock": stock}), 200

        # все товары
        # берём движения и суммируем
        rows = (
            s.query(StockMovement.product_id, StockMovement.movement_type, StockMovement.qty)
             .filter(StockMovement.company_id == company_id)
             .filter(StockMovement.warehouse_id == int(warehouse_id))
             .all()
        )
        m = {}
        for pid, mt, qty in rows:
            pid = int(pid)
            q = float(qty or 0.0)
            mt = (mt or "").upper()
            if pid not in m:
                m[pid] = 0.0
            if mt in ("IN", "TRANSFER_IN"):
                m[pid] += q
            elif mt in ("OUT", "TRANSFER_OUT"):
                m[pid] -= q
            elif mt == "ADJUST":
                m[pid] += q

        items = [{"product_id": int(pid), "stock": float(val)} for pid, val in m.items()]
        items.sort(key=lambda x: x["product_id"])
        return jsonify({"ok": True, "warehouse_id": int(warehouse_id), "items": items}), 200
    finally:
        s.close()


@inventory_bp.route("/movements", methods=["POST"])
@token_required
def create_movement():
    """
    POST /api/inventory/movements
    body:
    {
      "warehouse_id": 1,
      "product_id": 2,
      "movement_type": "IN" | "OUT",
      "qty": 5,
      "unit_cost": 1200,
      "reason": "Приход накладная №10",
      "ref_type": "sale",
      "ref_id": 123
    }
    """
    company_id = _company_id()
    if not _can_manage_inventory():
        return jsonify({"ok": False, "message": "ACCESS_DENIED"}), 403

    user_id = _user_id()
    data = request.get_json(silent=True) or {}

    warehouse_id = _int_or_none(data.get("warehouse_id"))
    product_id = _int_or_none(data.get("product_id"))
    mt = _clean_movement_type(data.get("movement_type"))
    qty = _float_or_none(data.get("qty"))
    unit_cost = _float_or_none(data.get("unit_cost"))
    reason = data.get("reason") or ""
    ref_type = (data.get("ref_type") or "").strip()
    ref_id = _int_or_none(data.get("ref_id"))

    if not warehouse_id:
        return jsonify({"ok": False, "message": "WAREHOUSE_ID_REQUIRED"}), 400
    if not product_id:
        return jsonify({"ok": False, "message": "PRODUCT_ID_REQUIRED"}), 400
    if mt not in ("IN", "OUT"):
        return jsonify({"ok": False, "message": "BAD_MOVEMENT_TYPE"}), 400
    if qty is None or qty <= 0:
        return jsonify({"ok": False, "message": "QTY_REQUIRED"}), 400

    s = get_session()
    try:
        w = s.query(Warehouse).filter_by(company_id=company_id, id=int(warehouse_id), is_enabled=True).first()
        if not w:
            return jsonify({"ok": False, "message": "WAREHOUSE_NOT_FOUND"}), 404

        p = s.query(Product).filter_by(company_id=company_id, id=int(product_id), is_enabled=True).first()
        if not p:
            return jsonify({"ok": False, "message": "PRODUCT_NOT_FOUND"}), 404

        # 🚫 запрет складских операций для услуг
        pkind = (getattr(p, "kind", "") or "product").strip().lower()
        if pkind == "service":
            return jsonify({"ok": False, "message": "SERVICE_HAS_NO_STOCK"}), 400

        # если расход — проверим остаток
        if mt == "OUT":
            stock = _current_stock(s, company_id, int(warehouse_id), int(product_id))
            if stock < float(qty):
                return jsonify({"ok": False, "message": "NOT_ENOUGH_STOCK", "stock": float(stock)}), 400

        now = _now_ms()

        row = StockMovement(
            company_id=company_id,
            warehouse_id=int(warehouse_id),
            product_id=int(product_id),
            movement_type=mt,
            qty=float(qty),
            unit_cost=float(unit_cost) if unit_cost is not None else None,
            reason=str(reason or ""),
            ref_type=ref_type,
            ref_id=int(ref_id) if ref_id else None,
            created_by_user_id=int(user_id) if user_id else None,
            created_ts_ms=now
        )
        s.add(row)
        s.commit()

        return jsonify({"ok": True, "movement_id": int(row.id)}), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "CREATE_FAILED", "error": str(e)}), 500
    finally:
        s.close()

@inventory_bp.route("/movements", methods=["GET"])
@token_required
def list_movements():
    """
    GET /api/inventory/movements?warehouse_id=1&product_id=5&movement_type=OUT&limit=200
    """
    company_id = _company_id()

    warehouse_id = _int_or_none(request.args.get("warehouse_id"))
    product_id = _int_or_none(request.args.get("product_id"))
    movement_type = (request.args.get("movement_type") or "").strip().upper()

    limit = _int_or_none(request.args.get("limit")) or 200
    if limit < 1:
        limit = 1
    if limit > 500:
        limit = 500

    s = get_session()
    try:
        q = s.query(StockMovement).filter(StockMovement.company_id == int(company_id))

        if warehouse_id:
            q = q.filter(StockMovement.warehouse_id == int(warehouse_id))

        if product_id:
            q = q.filter(StockMovement.product_id == int(product_id))

        if movement_type:
            allowed = {"IN", "OUT", "TRANSFER_IN", "TRANSFER_OUT", "ADJUST"}
            if movement_type in allowed:
                q = q.filter(StockMovement.movement_type == movement_type)

        rows = (
            q.order_by(StockMovement.id.desc())
             .limit(int(limit))
             .all()
        )

        # подтягиваем названия склада/товара (чтобы Vortex сразу показывал)
        wh_ids = list({int(r.warehouse_id) for r in rows})
        pr_ids = list({int(r.product_id) for r in rows})
        us_ids = list({int(r.created_by_user_id) for r in rows if r.created_by_user_id})

        wh_map = {}
        if wh_ids:
            whs = s.query(Warehouse).filter(Warehouse.company_id == int(company_id), Warehouse.id.in_(wh_ids)).all()
            wh_map = {int(w.id): (w.name or "") for w in whs}

        pr_map = {}
        if pr_ids:
            prs = s.query(Product).filter(Product.company_id == int(company_id), Product.id.in_(pr_ids)).all()
            pr_map = {int(p.id): {"title": (p.title or ""), "product_no": int(p.product_no)} for p in prs}

        us_map = {}
        if us_ids:
            us = s.query(User).filter(User.company_id == int(company_id), User.id.in_(us_ids)).all()
            us_map = {int(u.id): (getattr(u, "full_name", None) or getattr(u, "name", None) or getattr(u, "username", None) or "") for u in us}

        items = []
        for r in rows:
            pid = int(r.product_id)
            wid = int(r.warehouse_id)
            uid = int(r.created_by_user_id) if r.created_by_user_id else None

            pinfo = pr_map.get(pid) or {"title": "", "product_no": 0}

            items.append({
                "id": int(r.id),
                "warehouse_id": wid,
                "warehouse_name": wh_map.get(wid, ""),
                "product_id": pid,
                "product_no": int(pinfo.get("product_no") or 0),
                "product_title": pinfo.get("title") or "",
                "movement_type": (r.movement_type or ""),
                "qty": float(r.qty or 0.0),
                "unit_cost": float(r.unit_cost) if r.unit_cost is not None else None,
                "reason": r.reason or "",
                "ref_type": r.ref_type or "",
                "ref_id": int(r.ref_id) if r.ref_id is not None else None,
                "created_by_user_id": uid,
                "created_by_name": us_map.get(uid, "") if uid else "",
                "created_ts_ms": int(r.created_ts_ms or 0),
            })

        return jsonify({"ok": True, "movements": items}), 200
    finally:
        s.close()


@inventory_bp.route("/transfer", methods=["POST"])
@token_required
def transfer_stock():
    """
    POST /api/inventory/transfer
    body:
    {
      "from_warehouse_id": 1,
      "to_warehouse_id": 2,
      "product_id": 5,
      "qty": 10,
      "reason": "Перемещение"
    }
    """
    company_id = _company_id()
    if not _can_manage_inventory():
        return jsonify({"ok": False, "message": "ACCESS_DENIED"}), 403

    user_id = _user_id()
    data = request.get_json(silent=True) or {}

    from_id = _int_or_none(data.get("from_warehouse_id"))
    to_id = _int_or_none(data.get("to_warehouse_id"))
    product_id = _int_or_none(data.get("product_id"))
    qty = _float_or_none(data.get("qty"))
    reason = data.get("reason") or "Transfer"

    if not from_id or not to_id or int(from_id) == int(to_id):
        return jsonify({"ok": False, "message": "BAD_WAREHOUSE_IDS"}), 400
    if not product_id:
        return jsonify({"ok": False, "message": "PRODUCT_ID_REQUIRED"}), 400
    if qty is None or qty <= 0:
        return jsonify({"ok": False, "message": "QTY_REQUIRED"}), 400

    s = get_session()
    try:
        wf = s.query(Warehouse).filter_by(company_id=company_id, id=int(from_id), is_enabled=True).first()
        wt = s.query(Warehouse).filter_by(company_id=company_id, id=int(to_id), is_enabled=True).first()
        if not wf or not wt:
            return jsonify({"ok": False, "message": "WAREHOUSE_NOT_FOUND"}), 404

        p = s.query(Product).filter_by(company_id=company_id, id=int(product_id), is_enabled=True).first()
        if not p:
            return jsonify({"ok": False, "message": "PRODUCT_NOT_FOUND"}), 404

        # 🚫 запрет складских операций для услуг
        pkind = (getattr(p, "kind", "") or "product").strip().lower()
        if pkind == "service":
            return jsonify({"ok": False, "message": "SERVICE_HAS_NO_STOCK"}), 400

        stock = _current_stock(s, company_id, int(from_id), int(product_id))
        if stock < float(qty):
            return jsonify({"ok": False, "message": "NOT_ENOUGH_STOCK", "stock": float(stock)}), 400

        now = _now_ms()

        out_row = StockMovement(
            company_id=company_id,
            warehouse_id=int(from_id),
            product_id=int(product_id),
            movement_type="TRANSFER_OUT",
            qty=float(qty),
            reason=str(reason or ""),
            ref_type="transfer",
            ref_id=None,
            created_by_user_id=int(user_id) if user_id else None,
            created_ts_ms=now
        )
        in_row = StockMovement(
            company_id=company_id,
            warehouse_id=int(to_id),
            product_id=int(product_id),
            movement_type="TRANSFER_IN",
            qty=float(qty),
            reason=str(reason or ""),
            ref_type="transfer",
            ref_id=None,
            created_by_user_id=int(user_id) if user_id else None,
            created_ts_ms=now
        )

        s.add(out_row)
        s.add(in_row)
        s.commit()

        return jsonify({"ok": True, "transfer": {"out_id": int(out_row.id), "in_id": int(in_row.id)}}), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "TRANSFER_FAILED", "error": str(e)}), 500
    finally:
        s.close()


# ============================
# SERVICES (Products with kind="service")
# ============================

@inventory_bp.route("/services", methods=["GET"])
@token_required
def list_services():
    company_id = _company_id()
    role = _role()
    user_id = _user_id()

    category_id = _int_or_none(request.args.get("category_id"))
    qtxt = (request.args.get("q") or "").strip()
    limit = _int_or_none(request.args.get("limit")) or 200
    if limit < 1: limit = 1
    if limit > 500: limit = 500

    s = get_session()
    try:
        q = (
            s.query(Product)
             .filter(Product.company_id == company_id)
             .filter(Product.is_enabled == True)
             .filter(Product.kind == "service")
        )

        dep_id = _my_department_id(s, company_id, user_id)
        q = _apply_acl_query_products(q, s, company_id, role, user_id, dep_id)

        if category_id:
            q = q.filter(Product.category_id == int(category_id))

        if qtxt:
            like = f"%{qtxt.lower()}%"
            q = q.filter(or_(Product.title.ilike(like), Product.description.ilike(like)))

        rows = q.order_by(Product.product_no.asc()).limit(int(limit)).all()

        items = []
        for p in rows:
            items.append({
                "id": int(p.id),
                "product_no": int(p.product_no),
                "kind": "service",
                "category_id": int(p.category_id) if p.category_id else None,
                "title": p.title or "",
                "description": p.description or "",
                "base_price": p.base_price,
                "main_image_file_id": int(p.main_image_file_id) if p.main_image_file_id else None,
                "main_video_file_id": int(p.main_video_file_id) if p.main_video_file_id else None,
                "created_ts_ms": int(p.created_ts_ms or 0),
                "updated_ts_ms": int(p.updated_ts_ms or 0),
            })

        return jsonify({"ok": True, "services": items}), 200
    finally:
        s.close()


@inventory_bp.route("/services", methods=["POST"])
@token_required
def create_service():
    company_id = _company_id()
    if not _can_manage_inventory():
        return jsonify({"ok": False, "message": "ACCESS_DENIED"}), 403

    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"ok": False, "message": "TITLE_REQUIRED"}), 400

    description = data.get("description") or ""
    category_id = _int_or_none(data.get("category_id"))
    base_price = data.get("base_price")
    main_image_file_id = _int_or_none(data.get("main_image_file_id"))
    main_video_file_id = _int_or_none(data.get("main_video_file_id"))

    s = get_session()
    try:
        if category_id:
            cat = (
                s.query(InventoryCategory)
                 .filter_by(company_id=company_id, id=int(category_id), is_enabled=True)
                 .first()
            )
            if not cat:
                return jsonify({"ok": False, "message": "CATEGORY_NOT_FOUND"}), 404

        no = _next_product_no(s, company_id)
        now = _now_ms()

        row = Product(
            company_id=company_id,
            product_no=int(no),
            category_id=int(category_id) if category_id else None,
            kind="service",
            title=title,
            description=str(description or ""),
            base_price=float(base_price) if base_price is not None else None,
            main_image_file_id=int(main_image_file_id) if main_image_file_id else None,
            main_video_file_id=int(main_video_file_id) if main_video_file_id else None,
            is_enabled=True,
            created_ts_ms=now,
            updated_ts_ms=now
        )
        s.add(row)
        s.commit()

        return jsonify({"ok": True, "service_id": int(row.id), "service_no": int(row.product_no)}), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "CREATE_FAILED", "error": str(e)}), 500
    finally:
        s.close()


@inventory_bp.route("/services/<int:service_id>", methods=["POST"])
@token_required
def update_service(service_id: int):
    company_id = _company_id()
    if not _can_manage_inventory():
        return jsonify({"ok": False, "message": "ACCESS_DENIED"}), 403

    data = request.get_json(silent=True) or {}

    s = get_session()
    try:
        p = s.query(Product).filter_by(company_id=company_id, id=int(service_id)).first()
        if not p or not p.is_enabled or (p.kind or "").lower() != "service":
            return jsonify({"ok": False, "message": "NOT_FOUND"}), 404

        if "title" in data:
            t = (data.get("title") or "").strip()
            if not t:
                return jsonify({"ok": False, "message": "TITLE_REQUIRED"}), 400
            p.title = t

        if "description" in data:
            p.description = str(data.get("description") or "")

        if "category_id" in data:
            cid = _int_or_none(data.get("category_id"))
            if cid:
                cat = (
                    s.query(InventoryCategory)
                     .filter_by(company_id=company_id, id=int(cid), is_enabled=True)
                     .first()
                )
                if not cat:
                    return jsonify({"ok": False, "message": "CATEGORY_NOT_FOUND"}), 404
                p.category_id = int(cid)
            else:
                p.category_id = None

        if "base_price" in data:
            v = data.get("base_price")
            p.base_price = float(v) if v is not None else None

        if "main_image_file_id" in data:
            v = _int_or_none(data.get("main_image_file_id"))
            p.main_image_file_id = int(v) if v else None

        if "main_video_file_id" in data:
            v = _int_or_none(data.get("main_video_file_id"))
            p.main_video_file_id = int(v) if v else None

        # всегда фиксируем kind (на всякий)
        p.kind = "service"
        p.updated_ts_ms = _now_ms()

        s.commit()
        return jsonify({"ok": True}), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "UPDATE_FAILED", "error": str(e)}), 500
    finally:
        s.close()


@inventory_bp.route("/services/<int:service_id>", methods=["DELETE"])
@token_required
def delete_service(service_id: int):
    company_id = _company_id()
    if not _can_manage_inventory():
        return jsonify({"ok": False, "message": "ACCESS_DENIED"}), 403

    s = get_session()
    try:
        p = s.query(Product).filter_by(company_id=company_id, id=int(service_id)).first()
        if not p or (p.kind or "").lower() != "service":
            return jsonify({"ok": False, "message": "NOT_FOUND"}), 404

        p.is_enabled = False
        p.updated_ts_ms = _now_ms()
        s.commit()
        return jsonify({"ok": True, "message": "DISABLED"}), 200
    finally:
        s.close()
        
@inventory_bp.route("/movements/sale/remove_one", methods=["POST"])
@token_required
def remove_one_sale_unit():
    """
    POST /api/inventory/movements/sale/remove_one
    body:
    {
      "warehouse_id": 1,
      "product_id": 2,
      "ref_id": 123
    }
    Уменьшает продажу (OUT) на 1 ед.
    """
    company_id = _company_id()
    if not _can_manage_inventory():
        return jsonify({"ok": False, "message": "ACCESS_DENIED"}), 403

    data = request.get_json(silent=True) or {}
    warehouse_id = _int_or_none(data.get("warehouse_id"))
    product_id = _int_or_none(data.get("product_id"))
    ref_id = _int_or_none(data.get("ref_id"))

    if not warehouse_id:
        return jsonify({"ok": False, "message": "WAREHOUSE_ID_REQUIRED"}), 400
    if not product_id:
        return jsonify({"ok": False, "message": "PRODUCT_ID_REQUIRED"}), 400
    if not ref_id:
        return jsonify({"ok": False, "message": "REF_ID_REQUIRED"}), 400

    s = get_session()
    try:
        row = (
            s.query(StockMovement)
             .filter(StockMovement.company_id == int(company_id))
             .filter(StockMovement.warehouse_id == int(warehouse_id))
             .filter(StockMovement.product_id == int(product_id))
             .filter(StockMovement.movement_type == "OUT")
             .filter(StockMovement.ref_type == "sale")
             .filter(StockMovement.ref_id == int(ref_id))
             .order_by(StockMovement.id.desc())
             .first()
        )
        if not row:
            return jsonify({"ok": False, "message": "NOT_FOUND"}), 404

        q = float(row.qty or 0.0)

        if q <= 1.0:
            s.delete(row)
        else:
            row.qty = q - 1.0

        s.commit()
        return jsonify({"ok": True}), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "REMOVE_FAILED", "error": str(e)}), 500
    finally:
        s.close()
        
@inventory_bp.route("/movements/sale/last_out", methods=["GET"])
@token_required
def sale_last_out():
    """
    GET /api/inventory/movements/sale/last_out?ref_id=123&product_id=5
    -> { ok:true, warehouse_id:1 }
    """
    company_id = _company_id()

    ref_id = _int_or_none(request.args.get("ref_id"))
    product_id = _int_or_none(request.args.get("product_id"))

    if not ref_id:
        return jsonify({"ok": False, "message": "REF_ID_REQUIRED"}), 400
    if not product_id:
        return jsonify({"ok": False, "message": "PRODUCT_ID_REQUIRED"}), 400

    s = get_session()
    try:
        row = (
            s.query(StockMovement)
             .filter(StockMovement.company_id == int(company_id))
             .filter(StockMovement.movement_type == "OUT")
             .filter(StockMovement.ref_type == "sale")
             .filter(StockMovement.ref_id == int(ref_id))
             .filter(StockMovement.product_id == int(product_id))
             .order_by(StockMovement.id.desc())
             .first()
        )
        if not row:
            return jsonify({"ok": False, "message": "NOT_FOUND"}), 404

        return jsonify({"ok": True, "warehouse_id": int(row.warehouse_id)}), 200
    finally:
        s.close()
        

@inventory_bp.route("/sales/pay", methods=["POST"])
@token_required
def sales_pay():
    company_id = _company_id()
    user_id = _user_id()  # если нужно потом — пока не используем

    data = request.get_json(silent=True) or {}
    client_id = _int_or_none(data.get("client_id"))
    paid = _float_or_none(data.get("paid"))
    total = _float_or_none(data.get("total"))

    if not client_id:
        return jsonify({"ok": False, "message": "CLIENT_ID_REQUIRED"}), 400
    if paid is None or paid < 0:
        return jsonify({"ok": False, "message": "PAID_REQUIRED"}), 400
    if total is None or total < 0:
        return jsonify({"ok": False, "message": "TOTAL_REQUIRED"}), 400

    s = get_session()
    try:
        row = (
            s.query(SaleState)
             .filter(SaleState.company_id == int(company_id))
             .filter(SaleState.client_id == int(client_id))
             .first()
        )
        if not row:
            row = SaleState(company_id=int(company_id), client_id=int(client_id))
            s.add(row)

        row.total_amount = float(total)
        row.paid_amount = float(paid)
        row.updated_ts_ms = _now_ms()

        s.commit()
        return jsonify({"ok": True}), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "SAVE_FAILED", "error": str(e)}), 500
    finally:
        s.close()
        

@inventory_bp.route("/sales/pay", methods=["GET"])
@token_required
def sales_pay_get():
    company_id = _company_id()
    client_id = _int_or_none(request.args.get("client_id"))
    if not client_id:
        return jsonify({"ok": False, "message": "CLIENT_ID_REQUIRED"}), 400

    s = get_session()
    try:
        row = (
            s.query(SaleState)
             .filter(SaleState.company_id == int(company_id))
             .filter(SaleState.client_id == int(client_id))
             .first()
        )
        if not row:
            return jsonify({"ok": True, "total": 0.0, "paid": 0.0}), 200

        return jsonify({
            "ok": True,
            "total": float(row.total_amount or 0.0),
            "paid": float(row.paid_amount or 0.0),
        }), 200
    finally:
        s.close()
        

@inventory_bp.route("/sales/plan/month", methods=["GET"])
@token_required
def sales_plan_month():
    company_id = _company_id()

    payload = getattr(request, "user", None) or {}
    role = str(payload.get("role") or "").strip().lower()
    current_user_id = int(payload.get("user_id") or payload.get("userId") or payload.get("id") or 0)

    is_full_access = role in ("admin", "integrator", "director", "president")

    now = time.localtime()
    month_start = int(time.mktime((now.tm_year, now.tm_mon, 1, 0, 0, 0, 0, 0, -1)) * 1000)

    if now.tm_mon == 12:
        next_year = now.tm_year + 1
        next_month = 1
    else:
        next_year = now.tm_year
        next_month = now.tm_mon + 1

    month_end = int(time.mktime((next_year, next_month, 1, 0, 0, 0, 0, 0, -1)) * 1000)

    s = get_session()
    try:
        # =========================================================
        # 1) ручные суммы сделки за месяц
        # =========================================================
        manual_map = {}

        sale_rows = (
            s.query(SaleState)
             .filter(SaleState.company_id == int(company_id))
             .filter(SaleState.updated_ts_ms >= month_start)
             .filter(SaleState.updated_ts_ms < month_end)
             .all()
        )

        for row in sale_rows:
            client_id = int(row.client_id or 0)
            if client_id <= 0:
                continue

            amount = float(row.total_amount or 0.0)

            if client_id not in manual_map:
                manual_map[client_id] = 0.0
            manual_map[client_id] += amount

        # =========================================================
        # 2) товары со склада за месяц
        # =========================================================
        goods_map = {}

        stock_rows = (
            s.query(StockMovement, Product)
             .join(Product, Product.id == StockMovement.product_id)
             .filter(StockMovement.company_id == int(company_id))
             .filter(StockMovement.movement_type == "OUT")
             .filter(StockMovement.ref_type == "sale")
             .filter(StockMovement.created_ts_ms >= month_start)
             .filter(StockMovement.created_ts_ms < month_end)
             .all()
        )

        for mv, product in stock_rows:
            client_id = int(mv.ref_id or 0)
            if client_id <= 0:
                continue

            qty = float(mv.qty or 0.0)

            unit_price = None
            if mv.unit_cost is not None:
                try:
                    unit_price = float(mv.unit_cost)
                except:
                    unit_price = None

            if unit_price is None:
                try:
                    unit_price = float(product.base_price or 0.0)
                except:
                    unit_price = 0.0

            amount = qty * unit_price

            if client_id not in goods_map:
                goods_map[client_id] = 0.0
            goods_map[client_id] += float(amount)

        # =========================================================
        # 3) услуги за месяц
        # =========================================================
        service_map = {}

        service_rows = (
            s.query(SaleServiceLine)
             .filter(SaleServiceLine.company_id == int(company_id))
             .filter(SaleServiceLine.created_ts_ms >= month_start)
             .filter(SaleServiceLine.created_ts_ms < month_end)
             .all()
        )

        for row in service_rows:
            client_id = int(row.client_id or 0)
            if client_id <= 0:
                continue

            qty = float(row.qty or 0.0)
            unit_price = float(row.unit_price or 0.0)
            amount = qty * unit_price

            if client_id not in service_map:
                service_map[client_id] = 0.0
            service_map[client_id] += float(amount)

        # =========================================================
        # 4) итог по клиенту:
        #    ручная сумма + товары + услуги
        # =========================================================
        client_ids = set()
        client_ids.update(manual_map.keys())
        client_ids.update(goods_map.keys())
        client_ids.update(service_map.keys())

        client_totals = {}

        for client_id in client_ids:
            manual_amount = float(manual_map.get(client_id, 0.0))
            goods_amount = float(goods_map.get(client_id, 0.0))
            service_amount = float(service_map.get(client_id, 0.0))

            client_totals[client_id] = manual_amount + goods_amount + service_amount

        # =========================================================
        # 5) назначение суммы менеджеру сделки
        # =========================================================
        manager_totals = {}
        manager_name_map = {}

        if client_totals:
            assignments = (
                s.query(ClientAssignment)
                 .filter(ClientAssignment.company_id == int(company_id))
                 .filter(ClientAssignment.client_id.in_(list(client_totals.keys())))
                 .order_by(ClientAssignment.client_id.asc(), ClientAssignment.id.asc())
                 .all()
            )

            by_client = {}
            for a in assignments:
                cid = int(a.client_id or 0)
                if cid <= 0:
                    continue
                if cid not in by_client:
                    by_client[cid] = []
                by_client[cid].append(a)

            picked_user_ids = set()

            for client_id, amount in client_totals.items():
                arr = by_client.get(int(client_id), [])
                if not arr:
                    continue

                picked = None

                for a in arr:
                    if str(a.role or "").strip().lower() == "responsible":
                        picked = a
                        break

                if picked is None:
                    picked = arr[0]

                uid = int(picked.user_id or 0)
                if uid <= 0:
                    continue

                picked_user_ids.add(uid)

                if is_full_access:
                    if uid not in manager_totals:
                        manager_totals[uid] = 0.0
                    manager_totals[uid] += float(amount)
                else:
                    if uid == int(current_user_id):
                        if uid not in manager_totals:
                            manager_totals[uid] = 0.0
                        manager_totals[uid] += float(amount)

            if picked_user_ids:
                users = (
                    s.query(User)
                     .filter(User.company_id == int(company_id))
                     .filter(User.id.in_(list(picked_user_ids)))
                     .all()
                )

                for u in users:
                    manager_name_map[int(u.id)] = (
                        getattr(u, "full_name", None)
                        or getattr(u, "name", None)
                        or getattr(u, "username", None)
                        or ""
                    )

        # =========================================================
        # 6) общий итог
        # =========================================================
        total_amount = 0.0

        if is_full_access:
            for amount in client_totals.values():
                total_amount += float(amount)
        else:
            total_amount = float(manager_totals.get(int(current_user_id), 0.0))

        managers = []
        for uid, amount in manager_totals.items():
            managers.append({
                "user_id": int(uid),
                "name": manager_name_map.get(int(uid), ""),
                "amount": float(amount),
            })

        managers.sort(key=lambda x: x["amount"], reverse=True)

        return jsonify({
            "ok": True,
            "year": int(now.tm_year),
            "month": int(now.tm_mon),
            "total": float(total_amount),
            "managers": managers
        }), 200

    except Exception as e:
        return jsonify({
            "ok": False,
            "message": "PLAN_MONTH_FAILED",
            "error": str(e)
        }), 500
    finally:
        s.close()


@inventory_bp.route("/sales/services", methods=["POST"])
@token_required
def sale_add_service():
    company_id = _company_id()
    data = request.get_json(silent=True) or {}

    client_id = _int_or_none(data.get("client_id"))
    service_id = _int_or_none(data.get("service_id"))
    qty = _float_or_none(data.get("qty")) or 1.0
    unit_price = _float_or_none(data.get("unit_price")) or 0.0

    if not client_id:
        return jsonify({"ok": False, "message": "CLIENT_ID_REQUIRED"}), 400
    if not service_id:
        return jsonify({"ok": False, "message": "SERVICE_ID_REQUIRED"}), 400
    if qty <= 0:
        return jsonify({"ok": False, "message": "QTY_REQUIRED"}), 400

    s = get_session()
    try:
        # проверим что это услуга
        p = s.query(Product).filter_by(company_id=company_id, id=int(service_id), is_enabled=True).first()
        if not p or (p.kind or "").lower() != "service":
            return jsonify({"ok": False, "message": "SERVICE_NOT_FOUND"}), 404

        row = SaleServiceLine(
            company_id=int(company_id),
            client_id=int(client_id),
            service_id=int(service_id),
            qty=float(qty),
            unit_price=float(unit_price),
            created_ts_ms=_now_ms()
        )
        s.add(row)
        s.commit()
        return jsonify({"ok": True, "id": int(row.id)}), 200
    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "CREATE_FAILED", "error": str(e)}), 500
    finally:
        s.close()
        

@inventory_bp.route("/sales/services", methods=["GET"])
@token_required
def sale_list_services():
    company_id = _company_id()
    client_id = _int_or_none(request.args.get("client_id"))
    limit = _int_or_none(request.args.get("limit")) or 200
    if limit < 1: limit = 1
    if limit > 500: limit = 500

    if not client_id:
        return jsonify({"ok": False, "message": "CLIENT_ID_REQUIRED"}), 400

    s = get_session()
    try:
        rows = (
            s.query(SaleServiceLine)
             .filter(SaleServiceLine.company_id == int(company_id))
             .filter(SaleServiceLine.client_id == int(client_id))
             .order_by(SaleServiceLine.id.desc())
             .limit(int(limit))
             .all()
        )

        # подтянем названия услуг
        service_ids = list({int(r.service_id) for r in rows})
        pmap = {}
        if service_ids:
            ps = (
                s.query(Product)
                 .filter(Product.company_id == int(company_id))
                 .filter(Product.id.in_(service_ids))
                 .all()
            )
            pmap = {int(p.id): p for p in ps}

        items = []
        for r in rows:
            p = pmap.get(int(r.service_id))
            items.append({
                "id": int(r.id),
                "client_id": int(r.client_id),
                "service_id": int(r.service_id),
                "title": (p.title if p else ""),
                "qty": float(r.qty or 0.0),
                "unit_price": float(r.unit_price or 0.0),
                "created_ts_ms": int(r.created_ts_ms or 0),
            })

        return jsonify({"ok": True, "items": items}), 200
    finally:
        s.close()
        
        

@inventory_bp.route("/sales/services/remove_one", methods=["POST"])
@token_required
def sale_remove_one_service():
    """
    POST /api/inventory/sales/services/remove_one
    body:
    {
      "client_id": 1,
      "service_id": 5
    }

    Уменьшает qty на 1.
    Если qty <= 1 — удаляет строку.
    """

    company_id = _company_id()
    data = request.get_json(silent=True) or {}

    client_id = _int_or_none(data.get("client_id"))
    service_id = _int_or_none(data.get("service_id"))

    if not client_id:
        return jsonify({"ok": False, "message": "CLIENT_ID_REQUIRED"}), 400
    if not service_id:
        return jsonify({"ok": False, "message": "SERVICE_ID_REQUIRED"}), 400

    s = get_session()
    try:
        row = (
            s.query(SaleServiceLine)
             .filter(SaleServiceLine.company_id == int(company_id))
             .filter(SaleServiceLine.client_id == int(client_id))
             .filter(SaleServiceLine.service_id == int(service_id))
             .order_by(SaleServiceLine.id.desc())
             .first()
        )

        if not row:
            return jsonify({"ok": False, "message": "NOT_FOUND"}), 404

        q = float(row.qty or 0.0)

        if q <= 1.0:
            s.delete(row)
        else:
            row.qty = q - 1.0

        s.commit()
        return jsonify({"ok": True}), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "REMOVE_FAILED", "error": str(e)}), 500
    finally:
        s.close()