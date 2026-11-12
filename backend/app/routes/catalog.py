"""Connect a website and bring its products into Dakbox."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import auth, catalog_import as ci, db, metacfg, shop_orders as so
from ..events import emit

router = APIRouter(prefix="/api/catalog", dependencies=[Depends(auth.current_user)])
MANAGE = Depends(auth.require("products.manage"))


class UrlBody(BaseModel):
    url: str = Field(min_length=1, max_length=500)


class ImportBody(UrlBody):
    defaultStock: int = Field(default=10, ge=0, le=10_000)
    confirmCurrency: bool = False


def _fail(e: ci.CatalogError) -> HTTPException:
    return HTTPException(409 if isinstance(e, ci.CurrencyChanged) else 400, str(e))


def _item(i: ci.Item) -> dict:
    return {"name": i.name, "variant": i.variant, "price": i.price, "image": i.image, "inStock": i.in_stock, "sku": i.sku}


@router.post("/discover", dependencies=[MANAGE])
async def discover(b: UrlBody):
    """Look at the website and say what can be imported. Saves nothing."""
    try:
        f = await ci.discover(b.url, fresh=True)
    except ci.CatalogError as e:
        raise _fail(e) from None
    usable = [i for i in f.items if i.price is not None]
    return {"kind": f.kind, "kindLabel": ci.KIND_LABEL[f.kind], "host": f.host, "url": f.url, "currency": f.currency, "total": len(f.items),
            "usable": len(usable), "outOfStock": sum(1 for i in usable if i.in_stock is False), "stockKnown": sum(1 for i in usable if i.qty is not None),
            "truncated": f.truncated, "warnings": f.warnings, "skippedPages": f.skipped, "items": [_item(i) for i in usable[:12]],
            "connected": bool(db.get("SELECT 1 FROM catalog_sources WHERE host=?", [f.host]))}


@router.post("/import", dependencies=[MANAGE])
async def import_(b: ImportBody):
    try:
        src, f, res = await ci.connect(b.url, b.defaultStock, b.confirmCurrency)
    except ci.CatalogError as e:
        raise _fail(e) from None
    auth.audit("catalog.import", f.host, f"{f.kind}: {ci._summary(res)}")
    emit("products")
    return {"ok": True, "source": src, **res}


@router.get("/sources")
async def sources():
    return {"items": [ci.source_view(r) for r in db.all("SELECT * FROM catalog_sources ORDER BY created_at")]}


@router.post("/sources/{sid}/sync", dependencies=[MANAGE])
async def sync(sid: str):
    src = db.get("SELECT * FROM catalog_sources WHERE id=?", [sid])
    if not src:
        raise HTTPException(404, "That website is not connected.")
    try:
        res = await ci.sync(src)
    except ci.CatalogError as e:
        raise _fail(e) from None
    auth.audit("catalog.sync", src["host"], ci._summary(res))
    emit("products")
    return {"ok": True, "source": ci.source_view(db.get("SELECT * FROM catalog_sources WHERE id=?", [sid])), **res}


@router.delete("/sources/{sid}", dependencies=[MANAGE])
async def disconnect(sid: str):
    src = db.get("SELECT * FROM catalog_sources WHERE id=?", [sid])
    if not src:
        raise HTTPException(404, "That website is not connected.")
    db.run("DELETE FROM catalog_sources WHERE id=?", [sid])
    auth.audit("catalog.disconnect", src["host"], "Stopped syncing. Imported products were kept.")
    return {"ok": True}


# ---------------------------------------------------------------- receiving the website's orders
def _src(sid: str):
    src = db.get("SELECT * FROM catalog_sources WHERE id=?", [sid])
    if not src:
        raise HTTPException(404, "That website is not connected.")
    return src


def _orders_setup(src) -> dict:
    pub = metacfg.public_url()
    secret = so.ensure_secret(src)
    src = db.get("SELECT * FROM catalog_sources WHERE id=?", [src["id"]])
    return {"kind": src["kind"], "host": src["host"], "path": so.webhook_path(src), "url": f"{pub or 'https://YOUR-PUBLIC-URL'}{so.webhook_path(src)}", "publicUrlSet": bool(pub),
            "secret": secret if src["kind"] != "shopify" else None,        # Shopify chooses its own: the owner pastes it here, and it is never shown again
            "secretSet": bool(secret), "notifySms": bool(src["order_sms"]), "ordersCount": src["orders_count"], "ordersAt": src["orders_at"], "ordersError": src["orders_error"]}


@router.get("/sources/{sid}/orders", dependencies=[MANAGE])
async def orders_setup(sid: str):
    return _orders_setup(_src(sid))


class OrdersBody(BaseModel):
    notifySms: bool | None = None
    signingSecret: str | None = Field(default=None, min_length=8, max_length=200)


@router.put("/sources/{sid}/orders", dependencies=[MANAGE])
async def orders_settings(sid: str, b: OrdersBody):
    src = _src(sid)
    if b.notifySms is not None:
        db.run("UPDATE catalog_sources SET order_sms=? WHERE id=?", [1 if b.notifySms else 0, sid])
        auth.audit("catalog.orders_sms", src["host"], "on" if b.notifySms else "off")
    if b.signingSecret is not None:
        if src["kind"] != "shopify":
            raise HTTPException(400, "Only Shopify chooses its own signing secret. Copy the secret shown here into the website instead.")
        from ..secrets_store import seal
        db.run("UPDATE catalog_sources SET order_secret=?, orders_error=NULL WHERE id=?", [seal(b.signingSecret.strip()), sid])
        auth.audit("catalog.orders_secret", src["host"], "Shopify signing secret saved")
    return _orders_setup(_src(sid))


@router.post("/sources/{sid}/orders/secret", dependencies=[MANAGE])
async def orders_new_secret(sid: str):
    """A new secret for the website to sign with. The old one stops working at once."""
    src = _src(sid)
    if src["kind"] == "shopify":
        raise HTTPException(400, "Shopify makes its own signing secret. Copy the new one from Shopify and paste it here.")
    db.run("UPDATE catalog_sources SET order_secret=NULL WHERE id=?", [sid])
    auth.audit("catalog.orders_secret", src["host"], "new secret")
    return _orders_setup(_src(sid))
