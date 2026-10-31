import asyncio
import json
import sqlite3
import requests
import websockets

# --- البيانات الأساسية ---
TELEGRAM_TOKEN = "9275712134:AAGuamkQZfgyAJ3ufdTlIUgCcdz6WAIzG5Q"
CHAT_ID = "7110219104"

API_KEY = "alch_Ca5bMPy5jcRT2M4l0mMZH"
ALCHEMY_WSS = f"wss://eth-mainnet.g.alchemy.com/v2/{API_KEY}"
ALCHEMY_HTTP = f"https://eth-mainnet.g.alchemy.com/v2/{API_KEY}"

WHALE_GIF_URL = "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExOHJ6YnRzcDNhZ3FhNHRhNmc5bnBsd3EzMGZkcnppcjB6anEyc3g0NSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/FaKV1CwBUZXGiN7agD/giphy.gif"

MIN_ETH_AMOUNT = 20.0
MIN_STABLECOIN_USD = 1000000.0

OFFSET_ID = 0
ETH_PRICE_USD = 3000.0

USDT_CONTRACT = "0xdac17f958d2ee523a2206206994597c13d831ec7"
USDC_CONTRACT = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"

KNOWN_LABELS = {
    "0x28c6c06298d514db089934071355e5743bf21d60": "Binance 14",
    "0x21a31ee1afc51d94c2efccaa3c09400015286722": "Binance Hot Wallet",
    "0x7160ec948a01de17336126376f0e37e67393d6ce": "Binance Cold Storage",
    "0x3f5ce5fbfe3e9af3971dd833d26ba9b5c936f0be": "Binance 3",
    "0xdfd5293d8e347dfee59e436926c617d2309cece7": "Binance 8",
    "0x503279367469222e9d2f2323a67d01e4a69d4c72": "Coinbase 1",
    "0x71676878b273b4e727e2b7e192c735d5069792fa": "Coinbase Prime",
    "0x2910543af39aba0cd09bfb2650210b2e76d6e0e7": "Kraken 1",
    "0x6cc5f688a315f3dc28a7781717a9a798a59fda7b": "OKX Hot Wallet",
    "0xf89d7b970d0379de3604f32c1c68f142277d70ec": "Bybit Hot Wallet",
    "0x7a250d5630b4cf539739df2c5dacb4c659f2488d": "Uniswap V2 Router"
}

EXCHANGE_NAMES = ["Binance", "Coinbase", "Kraken", "OKX", "Bybit", "Gate.io"]

# --- إعداد قاعدة البيانات ---
def init_db():
    conn = sqlite3.connect("crypto_bot.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tx_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tx_hash TEXT,
            asset TEXT,
            amount REAL,
            usd_value REAL,
            from_addr TEXT,
            to_addr TEXT,
            intent_type TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS watchlist (
            address TEXT PRIMARY KEY
        )
    ''')
    conn.commit()
    conn.close()

def log_transaction(tx_hash, asset, amount, usd_val, from_addr, to_addr, intent_type="NORMAL"):
    try:
        conn = sqlite3.connect("crypto_bot.db")
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO tx_history (tx_hash, asset, amount, usd_value, from_addr, to_addr, intent_type)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (tx_hash, asset, amount, usd_val, from_addr, to_addr, intent_type))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"خطأ حفظ بقاعدة البيانات: {e}")

def add_to_watchlist(address):
    try:
        conn = sqlite3.connect("crypto_bot.db")
        cursor = conn.cursor()
        cursor.execute('INSERT OR IGNORE INTO watchlist (address) VALUES (?)', (address.lower(),))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False

def remove_from_watchlist(address):
    try:
        conn = sqlite3.connect("crypto_bot.db")
        cursor = conn.cursor()
        cursor.execute('DELETE FROM watchlist WHERE address = ?', (address.lower(),))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False

def get_watchlist():
    try:
        conn = sqlite3.connect("crypto_bot.db")
        cursor = conn.cursor()
        cursor.execute('SELECT address FROM watchlist')
        rows = cursor.fetchall()
        conn.close()
        return [r[0] for r in rows]
    except Exception:
        return []

def get_db_stats():
    try:
        conn = sqlite3.connect("crypto_bot.db")
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*), SUM(usd_value) FROM tx_history')
        row = cursor.fetchone()
        conn.close()
        count = row[0] if row[0] else 0
        total_usd = row[1] if row[1] else 0.0
        return count, total_usd
    except Exception:
        return 0, 0.0

def calculate_whale_sentiment():
    """تحليل اتجاه السيولة خلال 24 ساعة وحساب نسبة التجميع مقابل التصريف"""
    try:
        conn = sqlite3.connect("crypto_bot.db")
        cursor = conn.cursor()
        cursor.execute('''
            SELECT intent_type, SUM(usd_value) 
            FROM tx_history 
            WHERE timestamp >= datetime('now', '-1 day') 
            GROUP BY intent_type
        ''')
        rows = cursor.fetchall()
        conn.close()

        deposits_usd = 0.0
        withdrawals_usd = 0.0

        for intent, total_usd in rows:
            if intent == "DEPOSIT":
                deposits_usd += total_usd or 0.0
            elif intent == "WITHDRAWAL":
                withdrawals_usd += total_usd or 0.0

        total_flow = deposits_usd + withdrawals_usd
        if total_flow == 0:
            return "⚖️ **حالة السوق:** لا توجد بيانات سيولة كافية لآخر 24 ساعة (محايد)."

        acc_ratio = (withdrawals_usd / total_flow) * 100
        dist_ratio = (deposits_usd / total_flow) * 100

        status = "🟢 **تجميع وتخزين صاعد (Accumulation)**" if acc_ratio >= 55 else (
            "🔻 **إيداع وتصريف هابط (Distribution)**" if dist_ratio >= 55 else "⚖️ **سيولة متوازنة (Neutral Market)**"
        )

        return (
            f"🧠 **مؤشر تحركات الحيتان (Whale Sentiment Index):**\n\n"
            f"{status}\n\n"
            f"🟢 **نسبة السحب والتجميع:** `{acc_ratio:.1f}%` (${withdrawals_usd:,.0f})\n"
            f"🔻 **نسبة الإيداع والبيع:** `{dist_ratio:.1f}%` (${deposits_usd:,.0f})\n"
            f"📊 **حجم السيولة المرصودة مؤخراً:** `${total_flow:,.2f}`"
        )
    except Exception as e:
        print(f"خطأ حساب المؤشر: {e}")
        return "❌ تعذر حساب مؤشر حركة الحيتان."

def get_fear_and_greed():
    try:
        res = requests.get("https://api.alternative.me/fng/", timeout=5).json()
        if "data" in res and len(res["data"]) > 0:
            val = res["data"][0]["value"]
            status = res["data"][0]["value_classification"]
            return f"🎭 **مؤشر الخوف والجشع للسوق (Fear & Greed):**\nالقيمـة: `{val}/100` ({status})"
    except Exception:
        pass
    return "❌ تعذر جلب مؤشر الخوف والجشع."

# --- أدوات واستعلامات البوت ---
def get_label(address):
    if not address:
        return "غير معروف"
    addr_lower = address.lower()
    return KNOWN_LABELS.get(addr_lower, f"`{address[:8]}...{address[-6:]}`")

def update_eth_price():
    global ETH_PRICE_USD
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd"
        res = requests.get(url, timeout=4).json()
        if "ethereum" in res:
            ETH_PRICE_USD = float(res["ethereum"]["usd"])
    except Exception as e:
        print(f"تعذر تحديث سعر ETH: {e}")

def send_telegram_menu():
    """إرسال القائمة الرئيسية بالأزرار التفاعلية (Inline Keyboards)"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    keyboard = {
        "inline_keyboard": [
            [{"text": "📊 أسعار السوق", "callback_data": "cmd_price"}, {"text": "⛽ رسوم الغاز", "callback_data": "cmd_gas"}],
            [{"text": "🧠 مؤشر الحيتان", "callback_data": "cmd_sentiment"}, {"text": "📈 إحصائيات الداتا بيز", "callback_data": "cmd_stats"}],
            [{"text": "👁️ المحافظ المراقبة", "callback_data": "cmd_watchlist"}]
        ]
    }
    payload = {
        "chat_id": CHAT_ID,
        "text": "🎛️ **لوحة التحكم والتفاعل لرادار الحيتان:**\nاختر من الأزرار أدناه للوصول السريع للخدمات:",
        "parse_mode": "Markdown",
        "reply_markup": keyboard
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"خطأ إرسال القائمة: {e}")

def send_telegram_animation(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendAnimation"
    payload = {"chat_id": CHAT_ID, "animation": WHALE_GIF_URL, "caption": text, "parse_mode": "Markdown"}
    try:
        res = requests.post(url, json=payload).json()
        if not res.get("ok"):
            send_telegram(text)
    except Exception:
        send_telegram(text)

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": True}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"خطأ إرسال تليجرام: {e}")

def get_gas_price():
    payload = {"jsonrpc": "2.0", "method": "eth_gasPrice", "params": [], "id": 1}
    try:
        res = requests.post(ALCHEMY_HTTP, json=payload).json()
        if "result" in res:
            wei = int(res["result"], 16)
            gwei = wei / 10**9
            return f"⛽ **رسوم الغاز الحالية (Gas Price):** `{gwei:,.2f} Gwei`"
    except Exception:
        pass
    return "❌ تعذر جلب رسوم الغاز حالياً."

def get_market_prices():
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=ethereum,bitcoin&vs_currencies=usd&include_24hr_change=true"
        res = requests.get(url, timeout=5).json()
        eth_p = res.get("ethereum", {}).get("usd", 0)
        eth_c = res.get("ethereum", {}).get("usd_24h_change", 0)
        btc_p = res.get("bitcoin", {}).get("usd", 0)
        btc_c = res.get("bitcoin", {}).get("usd_24h_change", 0)
        
        return (
            f"📊 **أسعار السوق الحالية:**\n\n"
            f"🔹 **ETH:** `${eth_p:,.2f}` (`{eth_c:+.2f}%`)\n"
            f"🔸 **BTC:** `${btc_p:,.2f}` (`{btc_c:+.2f}%`)"
        )
    except Exception:
        return "❌ تعذر جلب أسعار السوق."

def check_wallet_balance(address):
    update_eth_price()
    payload = {"jsonrpc": "2.0", "method": "eth_getBalance", "params": [address, "latest"], "id": 1}
    try:
        res = requests.post(ALCHEMY_HTTP, json=payload).json()
        if "result" in res:
            wei = int(res["result"], 16)
            eth_bal = wei / 10**18
            usd_val = eth_bal * ETH_PRICE_USD
            label = get_label(address)
            return (
                f"💼 **تقرير المحفظة الشامل:**\n\n"
                f"🏷️ **المالك/المنصة:** {label}\n"
                f"📌 **العنوان:** `{address}`\n"
                f"💰 **الرصيد:** `{eth_bal:,.4f} ETH` (≈ `${usd_val:,.2f}`)\n"
                f"📊 **سعر ETH الحالي:** `${ETH_PRICE_USD:,.2f}`"
            )
    except Exception as e:
        print(f"خطأ جلب الرصيد: {e}")
    return "❌ تعذر جلب البيانات. تأكد من صحة العنوان."

async def daily_report_loop():
    """ارسال تقرير تلقائي يومي ببيانات التحليل والسيولة"""
    while True:
        await asyncio.sleep(86400) # كل 24 ساعة
        sentiment = calculate_whale_sentiment()
        fg = get_fear_and_greed()
        count, total_usd = get_db_stats()
        report = (
            f"📅 **التقرير اليومي الشامل للرادار:**\n\n"
            f"{sentiment}\n\n"
            f"{fg}\n\n"
            f"📈 إجمالي العمليات المرصودة في التاريخ: `{count:,}` (${total_usd:,.0f})"
        )
        send_telegram(report)

async def update_price_loop():
    while True:
        update_eth_price()
        await asyncio.sleep(300)

async def handle_commands():
    global OFFSET_ID
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    
    while True:
        try:
            res = requests.get(url, params={"offset": OFFSET_ID + 1, "timeout": 5}).json()
            if res.get("ok") and res.get("result"):
                for update in res["result"]:
                    OFFSET_ID = update["update_id"]
                    
                    # معالجة الضغط على الأزرار التفاعلية (Callback Queries)
                    if "callback_query" in update:
                        cb = update["callback_query"]
                        cb_data = cb.get("data", "")
                        
                        if cb_data == "cmd_price":
                            send_telegram(get_market_prices())
                        elif cb_data == "cmd_gas":
                            send_telegram(get_gas_price())
                        elif cb_data == "cmd_sentiment":
                            s = calculate_whale_sentiment()
                            fg = get_fear_and_greed()
                            send_telegram(f"{s}\n\n{fg}")
                        elif cb_data == "cmd_stats":
                            count, total_usd = get_db_stats()
                            send_telegram(
                                f"📈 **إحصائيات المنظومة المباشرة:**\n\n"
                                f"🐋 عدد تحركات الحيتان المرصودة: `{count:,}`\n"
                                f"💵 إجمالي حجم السيولة المرصودة: `${total_usd:,.2f}`"
                            )
                        elif cb_data == "cmd_watchlist":
                            wl = get_watchlist()
                            if wl:
                                items = "\n".join([f"• `{a}`" for a in wl])
                                send_telegram(f"👁️ **قائمة المحافظ المراقبة مخصصاً:**\n\n{items}")
                            else:
                                send_telegram("ℹ️ قائمة المراقبة خالية حالياً.")

                    # معالجة الرسائل النصية
                    msg = update.get("message", {})
                    text = msg.get("text", "").strip()
                    
                    if text in ["/start", "/menu"]:
                        send_telegram_menu()
                    elif text.startswith("/check"):
                        parts = text.split()
                        if len(parts) > 1 and parts[1].startswith("0x"):
                            send_telegram(check_wallet_balance(parts[1]))
                        else:
                            send_telegram("❌ الصيغة الصحيحة:\n`/check 0xAddress`")
                    elif text.startswith("/watch"):
                        parts = text.split()
                        if len(parts) > 1 and parts[1].startswith("0x"):
                            addr = parts[1].lower()
                            add_to_watchlist(addr)
                            send_telegram(f"✅ تم إضافة المحفظة لقائمة المراقبة:\n`{addr}`")
                        else:
                            send_telegram("❌ الصيغة الصحيحة:\n`/watch 0xAddress`")
                    elif text.startswith("/unwatch"):
                        parts = text.split()
                        if len(parts) > 1 and parts[1].startswith("0x"):
                            addr = parts[1].lower()
                            remove_from_watchlist(addr)
                            send_telegram(f"🗑️ تم حذف المحفظة من المراقبة:\n`{addr}`")
                        else:
                            send_telegram("❌ الصيغة الصحيحة:\n`/unwatch 0xAddress`")
                    elif text == "/sentiment":
                        s = calculate_whale_sentiment()
                        fg = get_fear_and_greed()
                        send_telegram(f"{s}\n\n{fg}")
        except Exception as e:
            await asyncio.sleep(2)
        await asyncio.sleep(2)

async def listen_to_blockchain():
    print("🚀 جاري الاتصال بشبكة الإيثريوم...")
    update_eth_price()
    send_telegram(
        "⚡ **تم تفعيل لوحة التحكم التفاعلية ومؤشر حركة الحيتان!**\n"
        "أرسل `/start` أو `/menu` لفتح أزرار التحكم السريعة."
    )

    while True:
        try:
            async with websockets.connect(ALCHEMY_WSS) as ws:
                subscribe_message = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "eth_subscribe",
                    "params": ["alchemy_minedTransactions"]
                }
                await ws.send(json.dumps(subscribe_message))
                print("📡 تم الاتصال بالبث الحي بنجاح!")

                while True:
                    response = await ws.recv()
                    data = json.loads(response)
                    
                    if "params" in data and "result" in data["params"]:
                        tx = data["params"]["result"]["transaction"]
                        value_wei = int(tx.get("value", "0x0"), 16)
                        val_eth = value_wei / 10**18
                        
                        from_addr = tx.get("from", "").lower()
                        to_addr = tx.get("to", "").lower()
                        tx_hash = tx.get("hash", "")
                        
                        watchlist = get_watchlist()
                        
                        # 1. التتبع المخصص
                        if from_addr in watchlist or to_addr in watchlist:
                            msg = (
                                f"🚨 **تنبيه خاص: حركة محفظة مراقبة!** 👁️\n\n"
                                f"💰 **المبلغ:** `{val_eth:,.2f} ETH`\n"
                                f"📤 **من:** `{from_addr}`\n"
                                f"📥 **إلى:** `{to_addr}`\n\n"
                                f"🔗 [عرض المعاملة على Etherscan](https://etherscan.io/tx/{tx_hash})"
                            )
                            send_telegram(msg)

                        from_label = get_label(from_addr)
                        to_label = get_label(to_addr)
                        
                        # 2. تتبع ETH
                        if val_eth >= MIN_ETH_AMOUNT:
                            usd_val = val_eth * ETH_PRICE_USD
                            intent = "NORMAL"
                            intent_desc = "📊 تحويل عادي بين محافظ"
                            
                            if any(ex in to_label for ex in EXCHANGE_NAMES):
                                intent = "DEPOSIT"
                                intent_desc = "🔻 **إيداع بالمنصة** (مؤشر بيع)"
                            elif any(ex in from_label for ex in EXCHANGE_NAMES):
                                intent = "WITHDRAWAL"
                                intent_desc = "🟢 **سحب من المنصة** (مؤشر تجميع)"

                            log_transaction(tx_hash, "ETH", val_eth, usd_val, from_addr, to_addr, intent)

                            msg = (
                                f"🐋 **تنبيه حوت (ETH Alert)**\n\n"
                                f"💰 **المبلغ:** `{val_eth:,.2f} ETH` (≈ `${usd_val:,.2f}`)\n"
                                f"📤 **من:** {from_label}\n"
                                f"📥 **إلى:** {to_label}\n\n"
                                f"🎯 **التحليل:** {intent_desc}\n"
                                f"🔗 [عرض المعاملة على Etherscan](https://etherscan.io/tx/{tx_hash})"
                            )
                            print(f"🐋 حوت ETH! المبلغ: {val_eth:.2f} ETH (≈ ${usd_val:,.0f})")
                            send_telegram_animation(msg)
                            
                        # 3. تتبع USDT / USDC
                        input_data = tx.get("input", "")
                        if to_addr in [USDT_CONTRACT, USDC_CONTRACT] and len(input_data) == 138 and input_data.startswith("0xa9059cbb"):
                            try:
                                recipient = "0x" + input_data[34:74].lower()
                                raw_amount = int(input_data[74:], 16)
                                token_name = "USDT" if to_addr == USDT_CONTRACT else "USDC"
                                token_amount = raw_amount / 10**6
                                
                                if 1000000.0 <= token_amount <= 500000000.0:
                                    rec_label = get_label(recipient)
                                    intent = "NORMAL"
                                    if any(ex in rec_label for ex in EXCHANGE_NAMES):
                                        intent = "DEPOSIT"
                                    elif any(ex in from_label for ex in EXCHANGE_NAMES):
                                        intent = "WITHDRAWAL"

                                    log_transaction(tx_hash, token_name, token_amount, token_amount, from_addr, recipient, intent)
                                    
                                    msg = (
                                        f"💵 **تنبيه سيولة ضخمة ({token_name} Alert)** 🚀\n\n"
                                        f"💰 **المبلغ:** `${token_amount:,.2f} {token_name}`\n"
                                        f"📤 **من:** {from_label}\n"
                                        f"📥 **إلى:** {rec_label}\n\n"
                                        f"🔗 [عرض المعاملة على Etherscan](https://etherscan.io/tx/{tx_hash})"
                                    )
                                    print(f"💵 سيولة {token_name}! المبلغ: ${token_amount:,.0f}")
                                    send_telegram_animation(msg)
                            except Exception:
                                pass

        except Exception as e:
            print(f"⚠️ خطأ اتصال ({e})، إعادة المحاولة بعد 5 ثوانٍ...")
            await asyncio.sleep(5)

async def main():
    init_db()
    await asyncio.gather(
        listen_to_blockchain(),
        handle_commands(),
        update_price_loop(),
        daily_report_loop()
    )

if __name__ == "__main__":
    asyncio.run(main())
