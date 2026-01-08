# streamlit_app.py
# Firecake Kassensystem (Streamlit) – gleiche Kernlogik wie Tkinter:
# - Users/Products/Orders/Kitchen-Queue als CSV (Semikolon) in GitHub Repo
# - Tabs: Kasse / Produkte / Benutzer / Statistik / Belegstation / Ofen
# - ESP: UI setzt Status; optionaler separater API-Server (siehe api_server.py) für /queue & /status

import os
import io
import csv
import json
import base64
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import List, Dict, Optional

import requests
import streamlit as st


# =======================
#   Konfiguration
# =======================

# GitHub Storage (CSV liegt im Repo)
# In Streamlit Cloud: Settings -> Secrets
# GITHUB_TOKEN = "ghp_..." (repo contents read/write)
# GITHUB_REPO  = "USERNAME/REPO"
# GITHUB_BRANCH = "main"
# DATA_DIR = "data_kasse"

DATA_DIR = st.secrets.get("DATA_DIR", "data_kasse")
USERS_CSV = f"{DATA_DIR}/users.csv"
PRODUCTS_CSV = f"{DATA_DIR}/products.csv"
ORDERS_CSV = f"{DATA_DIR}/orders.csv"
KITCHEN_QUEUE_CSV = f"{DATA_DIR}/kitchen_queue.csv"

GITHUB_TOKEN = st.secrets.get("GITHUB_TOKEN", "")
GITHUB_REPO = st.secrets.get("GITHUB_REPO", "")
GITHUB_BRANCH = st.secrets.get("GITHUB_BRANCH", "main")

# ESP / API
BELEG_IP = st.secrets.get("BELEG_IP", "192.168.178.95")
OFEN_IP  = st.secrets.get("OFEN_IP",  "192.168.178.96")
STATUS_TOKEN = st.secrets.get("STATUS_TOKEN", "firecake")

# Wenn du den separaten API-Server (api_server.py) nutzt und öffentlich hostest,
# kannst du diese URL ins ESP als callback_url geben.
PUBLIC_API_BASE = st.secrets.get("PUBLIC_API_BASE", "")  # z.B. "https://firecake-api.onrender.com"


# =======================
#   Datenmodelle
# =======================

@dataclass
class User:
    user_id: int
    name: str
    role: str = "kasse"
    active: bool = True


@dataclass
class Product:
    product_id: int
    name: str
    price: float
    active: bool = True
    image_path: str = ""  # optional: Pfad im Repo (z.B. "assets/img/flammkuchen.png")


@dataclass
class OrderItem:
    product_id: int
    name: str
    quantity: int
    price_single: float
    special: str = ""

    @property
    def total(self) -> float:
        return self.quantity * self.price_single


@dataclass
class Order:
    order_id: int
    timestamp: str
    user_name: str
    items: List[OrderItem] = field(default_factory=list)

    @property
    def total(self) -> float:
        return sum(i.total for i in self.items)


@dataclass
class KitchenItem:
    queue_id: int
    order_id: int
    product_name: str
    quantity: int
    special: str = ""
    status: str = "zu_belegen"   # "zu_belegen" -> "bereit_fuer_ofen" -> "fertig"
    timestamp: str = ""


# =======================
#   GitHub CSV Storage
# =======================

class GitHubCSVStore:
    """
    Speichert/liest Dateien im GitHub Repo via Contents API.
    -> CSV liegt "bei GitHub", wird bei jeder Änderung committed.
    """

    def __init__(self, token: str, repo: str, branch: str = "main"):
        self.token = token
        self.repo = repo
        self.branch = branch
        self.api = "https://api.github.com"

    def _headers(self):
        if not self.token:
            return {"Accept": "application/vnd.github+json"}
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def read_text(self, path: str) -> Optional[str]:
        url = f"{self.api}/repos/{self.repo}/contents/{path}"
        r = requests.get(url, headers=self._headers(), params={"ref": self.branch}, timeout=10)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        data = r.json()
        content = data.get("content", "")
        if not content:
            return ""
        raw = base64.b64decode(content).decode("utf-8")
        return raw

    def write_text(self, path: str, text: str, message: str = "Update CSV"):
        # Get SHA (if exists)
        url = f"{self.api}/repos/{self.repo}/contents/{path}"
        r0 = requests.get(url, headers=self._headers(), params={"ref": self.branch}, timeout=10)
        sha = None
        if r0.status_code == 200:
            sha = r0.json().get("sha")

        payload = {
            "message": message,
            "content": base64.b64encode(text.encode("utf-8")).decode("ascii"),
            "branch": self.branch,
        }
        if sha:
            payload["sha"] = sha

        r = requests.put(url, headers=self._headers(), json=payload, timeout=10)
        r.raise_for_status()

    def ensure_file(self, path: str, default_text: str, message: str = "Init CSV"):
        existing = self.read_text(path)
        if existing is None:
            self.write_text(path, default_text, message=message)


# =======================
#   Kassensystem-Kern
# =======================

class Kassensystem:
    def __init__(self, store: GitHubCSVStore):
        self.store = store
        self.products: List[Product] = []
        self.users: List[User] = []
        self.orders: List[Order] = []
        self.kitchen_queue: List[KitchenItem] = []
        self._init_files()
        self.load_all()

    def _init_files(self):
        # Users
        self.store.ensure_file(
            USERS_CSV,
            "user_id;name;role;active\n1;Admin;admin;True\n",
            message="Init users.csv",
        )
        # Products
        self.store.ensure_file(
            PRODUCTS_CSV,
            "product_id;name;price;active;image_path\n",
            message="Init products.csv",
        )
        # Orders
        self.store.ensure_file(
            ORDERS_CSV,
            "order_id;timestamp;user_name;items_json;total\n",
            message="Init orders.csv",
        )
        # Kitchen queue
        self.store.ensure_file(
            KITCHEN_QUEUE_CSV,
            "queue_id;order_id;product_name;quantity;special;status;timestamp\n",
            message="Init kitchen_queue.csv",
        )

    def load_all(self):
        self.load_users()
        self.load_products()
        self.load_orders()
        self.load_kitchen_queue()

    # ----- Users -----
    def load_users(self):
        self.users = []
        raw = self.store.read_text(USERS_CSV) or ""
        f = io.StringIO(raw)
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            if not row.get("user_id"):
                continue
            self.users.append(
                User(
                    user_id=int(row["user_id"]),
                    name=row["name"],
                    role=row.get("role", "kasse"),
                    active=(row.get("active", "True") == "True"),
                )
            )

    def save_users(self):
        out = io.StringIO()
        w = csv.DictWriter(out, fieldnames=["user_id", "name", "role", "active"], delimiter=";")
        w.writeheader()
        for u in self.users:
            w.writerow({"user_id": u.user_id, "name": u.name, "role": u.role, "active": str(u.active)})
        self.store.write_text(USERS_CSV, out.getvalue(), message="Update users.csv")

    def add_user(self, name: str, role: str = "kasse") -> User:
        new_id = max([u.user_id for u in self.users], default=0) + 1
        u = User(user_id=new_id, name=name, role=role, active=True)
        self.users.append(u)
        self.save_users()
        return u

    def set_user_active(self, user_id: int, active: bool):
        for u in self.users:
            if u.user_id == user_id:
                u.active = active
                self.save_users()
                return

    # ----- Products -----
    def load_products(self):
        self.products = []
        raw = self.store.read_text(PRODUCTS_CSV) or ""
        f = io.StringIO(raw)
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            if not row.get("product_id"):
                continue
            self.products.append(
                Product(
                    product_id=int(row["product_id"]),
                    name=row["name"],
                    price=float(row["price"]) if row.get("price") else 0.0,
                    active=(row.get("active", "True") == "True"),
                    image_path=row.get("image_path", ""),
                )
            )

    def save_products(self):
        out = io.StringIO()
        w = csv.DictWriter(out, fieldnames=["product_id", "name", "price", "active", "image_path"], delimiter=";")
        w.writeheader()
        for p in self.products:
            w.writerow(
                {
                    "product_id": p.product_id,
                    "name": p.name,
                    "price": f"{p.price:.2f}",
                    "active": str(p.active),
                    "image_path": p.image_path,
                }
            )
        self.store.write_text(PRODUCTS_CSV, out.getvalue(), message="Update products.csv")

    def add_product(self, name: str, price: float, image_path: str = "") -> Product:
        new_id = max([p.product_id for p in self.products], default=0) + 1
        p = Product(product_id=new_id, name=name, price=price, active=True, image_path=image_path)
        self.products.append(p)
        self.save_products()
        return p

    def activate_product(self, product_id: int):
        for p in self.products:
            if p.product_id == product_id:
                p.active = True
                self.save_products()
                return

    def deactivate_product(self, product_id: int):
        for p in self.products:
            if p.product_id == product_id:
                p.active = False
                self.save_products()
                return

    def delete_product(self, product_id: int):
        self.products = [p for p in self.products if p.product_id != product_id]
        self.save_products()

    # ----- Orders -----
    def load_orders(self):
        self.orders = []
        raw = self.store.read_text(ORDERS_CSV) or ""
        f = io.StringIO(raw)
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            if not row.get("order_id"):
                continue
            try:
                items_raw = json.loads(row.get("items_json", "[]") or "[]")
            except Exception:
                items_raw = []
            items: List[OrderItem] = []
            for d in items_raw:
                d = dict(d)
                d.pop("total", None)
                items.append(OrderItem(**d))
            self.orders.append(
                Order(
                    order_id=int(row["order_id"]),
                    timestamp=row.get("timestamp", ""),
                    user_name=row.get("user_name", ""),
                    items=items,
                )
            )

    def save_orders(self):
        out = io.StringIO()
        w = csv.DictWriter(out, fieldnames=["order_id", "timestamp", "user_name", "items_json", "total"], delimiter=";")
        w.writeheader()
        for o in self.orders:
            w.writerow(
                {
                    "order_id": o.order_id,
                    "timestamp": o.timestamp,
                    "user_name": o.user_name,
                    "items_json": json.dumps([asdict(i) for i in o.items], ensure_ascii=False),
                    "total": f"{o.total:.2f}",
                }
            )
        self.store.write_text(ORDERS_CSV, out.getvalue(), message="Update orders.csv")

    # ----- Kitchen Queue -----
    def load_kitchen_queue(self):
        self.kitchen_queue = []
        raw = self.store.read_text(KITCHEN_QUEUE_CSV) or ""
        f = io.StringIO(raw)
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            if not row.get("queue_id"):
                continue
            self.kitchen_queue.append(
                KitchenItem(
                    queue_id=int(row["queue_id"]),
                    order_id=int(row["order_id"]),
                    product_name=row.get("product_name", ""),
                    quantity=int(row.get("quantity", "0") or 0),
                    special=row.get("special", ""),
                    status=row.get("status", "zu_belegen"),
                    timestamp=row.get("timestamp", ""),
                )
            )

    def save_kitchen_queue(self):
        out = io.StringIO()
        w = csv.DictWriter(
            out,
            fieldnames=["queue_id", "order_id", "product_name", "quantity", "special", "status", "timestamp"],
            delimiter=";",
        )
        w.writeheader()
        for it in self.kitchen_queue:
            w.writerow(
                {
                    "queue_id": it.queue_id,
                    "order_id": it.order_id,
                    "product_name": it.product_name,
                    "quantity": it.quantity,
                    "special": it.special,
                    "status": it.status,
                    "timestamp": it.timestamp,
                }
            )
        self.store.write_text(KITCHEN_QUEUE_CSV, out.getvalue(), message="Update kitchen_queue.csv")

    def next_order_id(self) -> int:
        return max([o.order_id for o in self.orders], default=0) + 1

    def next_queue_id(self) -> int:
        return max([i.queue_id for i in self.kitchen_queue], default=0) + 1

    def get_kitchen_items_by_status(self, status: str) -> List[KitchenItem]:
        return [i for i in self.kitchen_queue if i.status == status]

    def update_kitchen_item_status(self, queue_id: int, new_status: str) -> bool:
        for i in self.kitchen_queue:
            if i.queue_id == queue_id:
                i.status = new_status
                self.save_kitchen_queue()
                return True
        return False

    def create_order(self, user_name: str, items: List[OrderItem]):
        order_id = self.next_order_id()
        ts = datetime.now().isoformat(timespec="seconds")
        order = Order(order_id=order_id, timestamp=ts, user_name=user_name, items=items)
        self.orders.append(order)
        self.save_orders()

        created_kis: List[KitchenItem] = []
        for it in items:
            ki = KitchenItem(
                queue_id=self.next_queue_id(),
                order_id=order_id,
                product_name=it.name,
                quantity=it.quantity,
                special=it.special or "",
                status="zu_belegen",
                timestamp=ts,
            )
            self.kitchen_queue.append(ki)
            created_kis.append(ki)

        self.save_kitchen_queue()
        return order, created_kis

    def get_stats(self) -> Dict:
        total_orders = len(self.orders)
        total_revenue = sum(o.total for o in self.orders)
        revenue_per_product: Dict[str, float] = {}
        qty_per_product: Dict[str, int] = {}

        for o in self.orders:
            for it in o.items:
                revenue_per_product[it.name] = revenue_per_product.get(it.name, 0.0) + it.total
                qty_per_product[it.name] = qty_per_product.get(it.name, 0) + it.quantity

        return {
            "total_orders": total_orders,
            "total_revenue": total_revenue,
            "revenue_per_product": revenue_per_product,
            "qty_per_product": qty_per_product,
        }


# =======================
#   ESP Push (wie vorher)
# =======================

def send_order_to_beleg(order: Order, created_kis: List[KitchenItem]) -> bool:
    url = f"http://{BELEG_IP}/order"
    callback_url = f"{PUBLIC_API_BASE}/status" if PUBLIC_API_BASE else ""
    payload = {
        "order_id": str(order.order_id),
        "items": [
            {
                "queue_id": ki.queue_id,
                "name": ki.product_name,
                "qty": ki.quantity,
                "special": ki.special,
                "timestamp": ki.timestamp,
            }
            for ki in created_kis
        ],
        "callback_url": callback_url,
        "token": STATUS_TOKEN,
    }
    try:
        r = requests.post(url, json=payload, timeout=2)
        return 200 <= r.status_code < 300
    except Exception:
        return False


def send_item_to_ofen(ki: KitchenItem) -> bool:
    url = f"http://{OFEN_IP}/order"
    callback_url = f"{PUBLIC_API_BASE}/status" if PUBLIC_API_BASE else ""
    payload = {
        "order_id": str(ki.order_id),
        "items": [
            {
                "queue_id": ki.queue_id,
                "name": ki.product_name,
                "qty": ki.quantity,
                "special": ki.special,
                "timestamp": ki.timestamp,
            }
        ],
        "callback_url": callback_url,
        "token": STATUS_TOKEN,
    }
    try:
        r = requests.post(url, json=payload, timeout=2)
        return 200 <= r.status_code < 300
    except Exception:
        return False


# =======================
#   UI Helpers
# =======================

def money(x: float) -> str:
    return f"{x:.2f} €"


def receipt_text(order: Order) -> str:
    width = 42

    def line(text: str = "", fill: str = " "):
        text = text[:width]
        return text + fill * max(0, width - len(text))

    lines = []
    lines.append(" FIRECAKE KASSE ".center(width, "-"))
    lines.append(line(order.timestamp))
    lines.append(line(f"Bediener: {order.user_name}"))
    lines.append("-" * width)

    for item in order.items:
        lines.append(line(item.name))
        left = f"{item.quantity} x {item.price_single:.2f} €"
        right = f"{item.total:.2f} €"
        if len(left) + 1 + len(right) <= width:
            spaces = width - len(left) - len(right)
            lines.append(left + " " * spaces + right)
        else:
            lines.append(line(left))
            lines.append(line(right))

        if item.special:
            lines.append(line(f"* {item.special}"))
        lines.append("")

    lines.append("-" * width)
    lines.append(f"SUMME: {order.total:.2f} €".rjust(width))
    lines.append("")
    lines.append(line(f"Bestell-Nr: {order.order_id}"))
    lines.append("")
    lines.append("Danke und guten Appetit!".center(width))
    lines.append("\n\n")
    return "\n".join(lines)


def repo_image_bytes(store: GitHubCSVStore, path: str) -> Optional[bytes]:
    """
    Lädt ein Bild aus dem Repo (image_path) und gibt bytes zurück.
    Unterstützt: PNG/JPG/GIF (Streamlit kann das anzeigen)
    """
    if not path:
        return None
    url = f"https://api.github.com/repos/{store.repo}/contents/{path}"
    r = requests.get(url, headers=store._headers(), params={"ref": store.branch}, timeout=10)
    if r.status_code != 200:
        return None
    j = r.json()
    content = j.get("content", "")
    if not content:
        return None
    return base64.b64decode(content)


# =======================
#   Streamlit App
# =======================

st.set_page_config(page_title="Firecake Kassensystem", page_icon="🔥", layout="wide")
st.warning("BUILD TEST: 2026-01-07 23:05", icon="🧪")

st.markdown("""
<style>
/* ✅ robust: trifft neue + alte Streamlit DOM-Struktur */
div[data-testid="stAppViewContainer"] .main .block-container,
section.main > div.block-container,
div.block-container {
  padding-top: 7rem !important;
  padding-bottom: 2rem !important;
}

/* optional: nur zum Debuggen sichtbar machen, dass CSS wirklich aktiv ist */
div[data-testid="stAppViewContainer"]::before{
  content:"CSS AKTIV";
  position: fixed;
  top: 0.35rem;
  left: 0.75rem;
  z-index: 9999999;
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(0,0,0,0.6);
}
</style>
""", unsafe_allow_html=True)




if not GITHUB_REPO:
    st.error("Secrets fehlen: Bitte GITHUB_REPO setzen (z.B. 'user/firecake').")
    st.stop()

store = GitHubCSVStore(GITHUB_TOKEN, GITHUB_REPO, GITHUB_BRANCH)
ks = Kassensystem(store)

if "cart" not in st.session_state:
    st.session_state.cart: List[OrderItem] = []
if "special" not in st.session_state:
    st.session_state.special = ""

tabs = st.tabs(["Kasse", "Produkte", "Benutzer", "Statistik", "Belegstation", "Ofen"])


# =======================
#   Kasse
# =======================
with tabs[0]:
    left, right = st.columns([1.2, 1])

    with left:
        st.markdown('<div class="fc-card">', unsafe_allow_html=True)
        st.markdown('<div class="fc-h">Kasse</div>', unsafe_allow_html=True)

        active_users = [u for u in ks.users if u.active]
        user_name = st.selectbox("Benutzer", [u.name for u in active_users] or ["Admin"], key="user_name")

        st.text_input("Sonderwunsch (für nächsten Artikel)", key="special")

        active_products = [p for p in ks.products if p.active]
        if not active_products:
            st.info("Keine aktiven Produkte vorhanden.")
        else:
            # Produktkarten in Grid
            cols = st.columns(4)
            for idx, p in enumerate(active_products):
                with cols[idx % 4]:
                    st.markdown('<div class="fc-card">', unsafe_allow_html=True)
                    img = repo_image_bytes(store, p.image_path) if p.image_path else None
                    if img:
                        st.image(img, use_container_width=True)
                    else:
                        st.caption("Kein Bild")

                    st.markdown(f"**{p.name}**")
                    st.markdown(f"<span class='fc-muted'>{money(p.price)}</span>", unsafe_allow_html=True)

                    if st.button("Hinzufügen", key=f"add_{p.product_id}"):
                        sp = (st.session_state.get("special_input", "") or "").strip()
                        # gleiche Logik: gleiche Produkt+Sonderwunsch wird hochgezählt
                        existing = next(
                            (i for i in st.session_state.cart if i.product_id == p.product_id and (i.special or "").strip() == sp),
                            None,
                        )
                        if existing:
                            existing.quantity += 1
                        else:
                            st.session_state.cart.append(
                                OrderItem(product_id=p.product_id, name=p.name, quantity=1, price_single=p.price, special=sp)
                            )
                        st.session_state["special_input"] = ""
                        st.success(f"{p.name} hinzugefügt")
                    st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)

    with right:
        st.markdown('<div class="fc-card">', unsafe_allow_html=True)
        st.markdown('<div class="fc-h">Warenkorb</div>', unsafe_allow_html=True)

        if not st.session_state.cart:
            st.caption("Noch leer.")
        else:
            total = sum(i.total for i in st.session_state.cart)
            st.metric("Gesamtsumme", money(total))

            # Tabelle
            cart_rows = []
            for i in st.session_state.cart:
                cart_rows.append(
                    {
                        "Artikel": i.name,
                        "Menge": i.quantity,
                        "Preis": f"{i.price_single:.2f}",
                        "Summe": f"{i.total:.2f}",
                        "Sonderwunsch": i.special,
                    }
                )
            st.dataframe(cart_rows, use_container_width=True, hide_index=True)

            c1, c2, c3 = st.columns(3)

            with c1:
                if st.button("−1 von markiertem", use_container_width=True):
                    st.warning("In Streamlit gibt’s keine Treeview-Selection wie Tkinter – nimm unten die Dropdown-Auswahl.")
            with c2:
                if st.button("Warenkorb leeren", use_container_width=True):
                    st.session_state.cart = []
                    st.rerun()

            with c3:
                if st.button("Bestellung aufgeben", type="primary", use_container_width=True):
                    order, created_kis = ks.create_order(user_name, st.session_state.cart)

                    ok_beleg = send_order_to_beleg(order, created_kis)
                    st.session_state.cart = []

                    st.success(f"Bestellung #{order.order_id} gespeichert" + ("" if ok_beleg else " (Belegstation nicht erreicht)"))

                    txt = receipt_text(order)
                    st.download_button(
                        "Bon herunterladen (.txt)",
                        data=txt.encode("utf-8"),
                        file_name=f"bon_{order.order_id}.txt",
                        mime="text/plain",
                        use_container_width=True,
                    )

        # Ersatz für Tkinter „-1“: Auswahl über Selectbox
        if st.session_state.cart:
            sel = st.selectbox(
                "Artikel zum Reduzieren auswählen",
                options=list(range(len(st.session_state.cart))),
                format_func=lambda ix: f"{st.session_state.cart[ix].name} | {st.session_state.cart[ix].quantity}x | {st.session_state.cart[ix].special}",
            )
            if st.button("Auswahl −1", use_container_width=True):
                it = st.session_state.cart[sel]
                if it.quantity > 1:
                    it.quantity -= 1
                else:
                    st.session_state.cart.pop(sel)
                st.rerun()

        st.markdown("</div>", unsafe_allow_html=True)


# =======================
#   Produkte
# =======================
with tabs[1]:
    st.markdown('<div class="fc-card">', unsafe_allow_html=True)
    st.markdown('<div class="fc-h">Produkte</div>', unsafe_allow_html=True)

    with st.form("add_product"):
        c1, c2, c3 = st.columns([2, 1, 2])
        name = c1.text_input("Name")
        price = c2.number_input("Preis (€)", min_value=0.0, step=0.5, format="%.2f")
        image_path = c3.text_input("Bildpfad im Repo (optional)", placeholder="z.B. assets/img/flammkuchen.png")
        submitted = st.form_submit_button("Speichern", type="primary")
        if submitted:
            if not name.strip():
                st.error("Bitte Produktname eingeben.")
            else:
                ks.add_product(name.strip(), float(price), image_path.strip())
                st.success("Produkt gespeichert.")
                st.rerun()

    st.divider()

    # Liste + Aktionen
    prod_rows = []
    for p in sorted(ks.products, key=lambda x: x.product_id):
        prod_rows.append(
            {
                "ID": p.product_id,
                "Name": p.name,
                "Preis": money(p.price),
                "Status": "aktiv" if p.active else "inaktiv",
                "Bild": p.image_path,
            }
        )
    st.dataframe(prod_rows, use_container_width=True, hide_index=True)

    ids = [p.product_id for p in ks.products] or [0]
    sel_id = st.selectbox("Produkt auswählen", ids, format_func=lambda pid: f"{pid}: {next((x.name for x in ks.products if x.product_id==pid), '')}")

    b1, b2, b3 = st.columns(3)
    with b1:
        if st.button("Deaktivieren", use_container_width=True):
            ks.deactivate_product(sel_id)
            st.rerun()
    with b2:
        if st.button("Aktivieren", use_container_width=True):
            ks.activate_product(sel_id)
            st.rerun()
    with b3:
        if st.button("Löschen", use_container_width=True):
            ks.delete_product(sel_id)
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)


# =======================
#   Benutzer
# =======================
with tabs[2]:
    st.markdown('<div class="fc-card">', unsafe_allow_html=True)
    st.markdown('<div class="fc-h">Benutzer</div>', unsafe_allow_html=True)

    with st.form("add_user"):
        c1, c2 = st.columns([2, 1])
        uname = c1.text_input("Name")
        role = c2.selectbox("Rolle", ["kasse", "admin"])
        submitted = st.form_submit_button("Speichern", type="primary")
        if submitted:
            if not uname.strip():
                st.error("Bitte Namen eingeben.")
            else:
                ks.add_user(uname.strip(), role)
                st.success("Benutzer gespeichert.")
                st.rerun()

    st.divider()

    user_rows = []
    for u in sorted(ks.users, key=lambda x: x.user_id):
        user_rows.append({"ID": u.user_id, "Name": u.name, "Rolle": u.role, "Status": "aktiv" if u.active else "inaktiv"})
    st.dataframe(user_rows, use_container_width=True, hide_index=True)

    ids = [u.user_id for u in ks.users] or [1]
    uid = st.selectbox("Benutzer auswählen", ids, format_func=lambda i: f"{i}: {next((x.name for x in ks.users if x.user_id==i), '')}")
    if st.button("Aktiv/Inaktiv umschalten", use_container_width=True):
        u = next((x for x in ks.users if x.user_id == uid), None)
        if u:
            ks.set_user_active(uid, not u.active)
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)


# =======================
#   Statistik
# =======================
with tabs[3]:
    st.markdown('<div class="fc-card">', unsafe_allow_html=True)
    st.markdown('<div class="fc-h">Statistik</div>', unsafe_allow_html=True)

    stats = ks.get_stats()
    c1, c2 = st.columns(2)
    c1.metric("Bestellungen", str(stats["total_orders"]))
    c2.metric("Gesamtumsatz", money(stats["total_revenue"]))

    st.divider()

    rows = []
    for name, rev in sorted(stats["revenue_per_product"].items(), key=lambda x: -x[1]):
        rows.append({"Produkt": name, "Menge": stats["qty_per_product"].get(name, 0), "Umsatz": money(rev)})
    st.subheader("Umsatz pro Produkt")
    st.dataframe(rows, use_container_width=True, hide_index=True)

    st.subheader("Bestellungen (Details)")
    o_rows = []
    for o in sorted(ks.orders, key=lambda x: x.order_id):
        o_rows.append({"ID": o.order_id, "Zeit": o.timestamp, "Benutzer": o.user_name, "Betrag": money(o.total)})
    st.dataframe(o_rows, use_container_width=True, hide_index=True)

    st.markdown("</div>", unsafe_allow_html=True)


# =======================
#   Belegstation (zu_belegen -> bereit_fuer_ofen)
# =======================
with tabs[4]:
    st.markdown('<div class="fc-card">', unsafe_allow_html=True)
    st.markdown('<div class="fc-h">Belegstation</div><div class="fc-muted">Offene Positionen (Status: zu_belegen)</div>', unsafe_allow_html=True)

    items = ks.get_kitchen_items_by_status("zu_belegen")
    rows = [{"#ID": it.queue_id, "Bestellung": it.order_id, "Artikel": it.product_name, "Menge": it.quantity, "Sonderwunsch": it.special, "Zeit": it.timestamp} for it in items]
    st.dataframe(rows, use_container_width=True, hide_index=True)

    ids = [it.queue_id for it in items]
    if ids:
        qid = st.selectbox("Position auswählen", ids, format_func=lambda i: f"#{i}")
        if st.button("Als belegt markieren → Ofen", type="primary", use_container_width=True):
            ks.update_kitchen_item_status(qid, "bereit_fuer_ofen")
            ki = next((x for x in ks.kitchen_queue if x.queue_id == qid), None)
            ok = send_item_to_ofen(ki) if ki else False
            st.success("Status gesetzt: bereit_fuer_ofen" + ("" if ok else " (Ofen nicht erreicht)"))
            st.rerun()
    else:
        st.caption("Keine offenen Positionen.")

    st.markdown("</div>", unsafe_allow_html=True)


# =======================
#   Ofen (bereit_fuer_ofen -> fertig)
# =======================
with tabs[5]:
    st.markdown('<div class="fc-card">', unsafe_allow_html=True)
    st.markdown('<div class="fc-h">Ofen</div><div class="fc-muted">Bereit zum Backen (Status: bereit_fuer_ofen)</div>', unsafe_allow_html=True)

    items = ks.get_kitchen_items_by_status("bereit_fuer_ofen")
    rows = [{"#ID": it.queue_id, "Bestellung": it.order_id, "Artikel": it.product_name, "Menge": it.quantity, "Sonderwunsch": it.special, "Zeit": it.timestamp} for it in items]
    st.dataframe(rows, use_container_width=True, hide_index=True)

    ids = [it.queue_id for it in items]
    if ids:
        qid = st.selectbox("Position auswählen", ids, format_func=lambda i: f"#{i}")
        if st.button("Als gebacken markieren ✓", type="primary", use_container_width=True):
            ks.update_kitchen_item_status(qid, "fertig")
            st.success("Status gesetzt: fertig")
            st.rerun()
    else:
        st.caption("Keine Positionen im Ofen.")

    st.markdown("</div>", unsafe_allow_html=True)
