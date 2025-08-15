import os
import io
import tempfile
from typing import Optional, List, Dict, Any
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Body, HTTPException, Header
from pydantic import BaseModel

# --- Config from env ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
API_KEY            = os.getenv("API_KEY", "")  # اختیاری؛ اگر ست شد باید در هدر x-api-key هم بیاد

app = FastAPI(title="Orders Invoice API", version="1.0.0")

# ---------- Parsers (بر اساس کد خودت) ----------
def extract_orders(soup: BeautifulSoup):
    return soup.find_all("table", class_="wrapper")

def extract_order_data(order_soup: BeautifulSoup) -> Dict[str, Any]:
    def get_text_by_caption(caption: str) -> str:
        span = order_soup.find("span", string=caption)
        if span and span.parent:
            return span.parent.get_text(strip=True).replace(caption, "")
        return ""

    order_number = get_text_by_caption("شماره سفارش: ")
    order_date   = get_text_by_caption("تاریخ ثبت سفارش: ")
    full_name    = get_text_by_caption("نام و نام‌خانوادگی: ")
    phone        = get_text_by_caption("شماره تماس:")
    zipcode      = get_text_by_caption("کد پستی گیرنده:")
    address      = get_text_by_caption("آدرس گیرنده:")

    products = []
    products_table = order_soup.find("table", class_="products")
    if products_table:
        for row in products_table.find_all("tr"):
            tds = row.find_all("td")
            if len(tds) < 4:
                continue
            product_info = tds[1]
            if not product_info.find("h2"):
                continue
            try:
                name = product_info.find("h2").get_text(strip=True)
                attrs = product_info.find("span", class_="product-attrs")
                attrs = attrs.get_text(strip=True) if attrs else ""
                code = tds[2].find("span").get_text(strip=True) if tds[2].find("span") else ""
                quantity = tds[3].find("span").get_text(strip=True) if tds[3].find("span") else ""
                products.append({
                    "name": name,
                    "attrs": attrs,
                    "code": code,
                    "quantity": quantity
                })
            except:
                continue

    return {
        "order_number": order_number,
        "order_date": order_date,
        "full_name": full_name,
        "phone": phone,
        "zipcode": zipcode,
        "address": address,
        "products": products
    }

def generate_html_for_orders(orders_data: List[Dict[str, Any]]) -> str:
    all_orders_html = ""
    for i, order in enumerate(orders_data, start=1):
        product_rows = ""
        for p in order["products"]:
            product_rows += f"""
            <tr>
                <td>{p.get('name',"")}</td>
                <td>{p.get('attrs',"")}</td>
                <td>{p.get('code',"")}</td>
                <td>{p.get('quantity',"")}</td>
            </tr>
            """
        products_table = f"""
        <table class="products">
            <thead>
                <tr>
                    <th>نام محصول</th>
                    <th>ویژگی‌ها</th>
                    <th>کد</th>
                    <th>تعداد</th>
                </tr>
            </thead>
            <tbody>
                {product_rows}
            </tbody>
        </table>
        """
        order_html = f"""
        <section style="border:1px solid #ccc; margin-bottom:30px; padding:10px;">
            <h2>سفارش شماره {i}</h2>
            {products_table}
            <div><strong>شماره سفارش:</strong> {order.get('order_number','')}</div>
            <div><strong>تاریخ ثبت سفارش:</strong> {order.get('order_date','')}</div>
            <div><strong>نام و نام‌خانوادگی:</strong> {order.get('full_name','')}</div>
            <div><strong>شماره تماس:</strong> {order.get('phone','')}</div>
            <div><strong>کد پستی گیرنده:</strong> {order.get('zipcode','')}</div>
            <div><strong>آدرس گیرنده:</strong> {order.get('address','')}</div>
        </section>
        """
        all_orders_html += order_html

    return f"""
    <!DOCTYPE html>
    <html lang="fa">
    <head>
        <meta charset="UTF-8" />
        <title>فاکتورهای استخراج شده</title>
        <style>
            body {{
                direction: rtl;
                font-family: Tahoma, Arial, sans-serif;
                margin: 20px;
                font-size: 14px;
            }}
            table.products {{
                border-collapse: collapse;
                width: 100%;
                margin-top: 10px;
            }}
            table.products th, table.products td {{
                border: 1px solid #ccc;
                padding: 8px;
                text-align: right;
            }}
            table.products th {{
                background-color: #eee;
            }}
        </style>
    </head>
    <body>
        {all_orders_html}
    </body>
    </html>
    """

# ---------- Telegram ----------
def send_to_telegram(file_bytes: bytes, filename: str, caption: str = "📄 فاکتورهای سفارش‌ها آماده شد. لطفاً بررسی فرمایید.") -> Dict[str, Any]:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return {"ok": False, "error": "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set"}
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    files = {"document": (filename, io.BytesIO(file_bytes), "text/html; charset=utf-8")}
    data = {"chat_id": TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": "HTML"}
    resp = requests.post(url, data=data, files=files, timeout=60)
    try:
        j = resp.json()
    except:
        j = {"status_code": resp.status_code, "text": resp.text}
    return {"ok": resp.ok, "resp": j}

# ---------- Models ----------
class ProcessInput(BaseModel):
    url: Optional[str] = None     # یکی از این دو را بده
    html: Optional[str] = None
    send_to_telegram: bool = True
    return_html: bool = False
    filename: str = "all_orders.html"

# ---------- Routes ----------
@app.get("/")
def health():
    return {"ok": True, "service": "orders-invoice-api"}

@app.post("/process")
def process_orders(payload: ProcessInput, x_api_key: Optional[str] = Header(default=None)):
    # auth اختیاری
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

    # ورودی
    html = payload.html
    if payload.url:
        r = requests.get(payload.url, timeout=60)
        if r.status_code != 200:
            raise HTTPException(status_code=400, detail=f"Fetch failed: {r.status_code}")
        r.encoding = "utf-8"
        html = r.text

    if not html:
        raise HTTPException(status_code=400, detail="Provide 'url' or 'html'")

    soup = BeautifulSoup(html, "html.parser")
    orders_soups = extract_orders(soup)
    if not orders_soups:
        raise HTTPException(status_code=404, detail="No orders found")

    orders_data = [extract_order_data(osoup) for osoup in orders_soups]
    final_html = generate_html_for_orders(orders_data)

    # فایل نهایی
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tmp:
        tmp.write(final_html.encode("utf-8"))
        tmp_path = tmp.name

    tg_result = None
    if payload.send_to_telegram:
        with open(tmp_path, "rb") as f:
            tg_result = send_to_telegram(f.read(), payload.filename)

    # پاکسازی موقت (اختیاری: Koyeb کانتینر ephemeral است)
    try:
        os.remove(tmp_path)
    except:
        pass

    resp: Dict[str, Any] = {
        "ok": True,
        "orders": len(orders_data),
        "sent_to_telegram": bool(payload.send_to_telegram),
        "telegram_result": tg_result,
        "filename": payload.filename
    }
    if payload.return_html:
        resp["html"] = final_html  # اگر لازم داری در n8n مستقیم ذخیره کنی
    return resp

