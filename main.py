import os
import requests
from flask import Flask, request, jsonify
from anthropic import Anthropic
import schedule
import time
import threading

app = Flask(__name__)
client = Anthropic(api_key=os.environ.get("CLAUDE_API_KEY"))

INSTAGRAM_ACCESS_TOKEN = os.environ.get("INSTAGRAM_ACCESS_TOKEN")
INSTAGRAM_BUSINESS_ACCOUNT_ID = os.environ.get("INSTAGRAM_BUSINESS_ACCOUNT_ID")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

pending_replies = {}
pending_posts = {}
waiting_feedback = {}  # Kullanıcıdan fikir bekleniyor mu?

IMAGE_URL = "https://images.unsplash.com/photo-1509042239860-f550ce710b93?w=1080&q=80"

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"})

def send_telegram_with_buttons(message, buttons):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    keyboard = {"inline_keyboard": buttons}
    requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "reply_markup": keyboard,
        "parse_mode": "HTML"
    })

def send_telegram_photo_with_buttons(image_url, caption, buttons):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    keyboard = {"inline_keyboard": buttons}
    response = requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "photo": image_url,
        "caption": caption,
        "reply_markup": keyboard,
        "parse_mode": "HTML"
    })
    if not response.json().get("ok"):
        send_telegram_with_buttons(f"🖼 Görsel yüklenemedi.\n\n{caption}", buttons)

def generate_post(feedback=None):
    topics = [
        "sabah kahvesi motivasyonu",
        "ders arası snack önerisi",
        "kampüs hayatı ve otomat",
        "sınav döneminde enerji",
        "yeni ürün tanıtımı"
    ]
    import random
    topic = random.choice(topics)

    user_content = f"Bugünkü konu: {topic}. Instagram postu yaz."
    if feedback:
        user_content += f"\n\nKullanıcı geri bildirimi: {feedback}"

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=300,
        system="""Sen ODTÜ KKK'daki NovaX otomat şirketinin sosyal medya yöneticisisin.
Instagram için Türkçe, enerjik ve genç bir dille post yazıyorsun.
Post metni + emoji + hashtag içermeli.
Maksimum 150 kelime.""",
        messages=[{"role": "user", "content": user_content}]
    )
    return response.content[0].text

def send_post_to_telegram(caption, post_id):
    pending_posts[post_id] = {"image_url": IMAGE_URL, "caption": caption}

    telegram_caption = f"""📸 <b>Günlük Post Hazır!</b>

📝 <b>İçerik:</b>
{caption}

Onaylıyor musunuz?"""

    buttons = [
        [
            {"text": "✅ Paylaş", "callback_data": f"approve_post_{post_id}"},
            {"text": "❌ İptal", "callback_data": f"reject_post_{post_id}"}
        ],
        [
            {"text": "🔄 Yeniden Oluştur", "callback_data": f"regen_post_{post_id}"},
            {"text": "💡 Fikir Ver", "callback_data": f"feedback_post_{post_id}"}
        ]
    ]
    send_telegram_photo_with_buttons(IMAGE_URL, telegram_caption, buttons)

def generate_dm_reply(user_message, username):
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=500,
        system="""Sen ODTÜ KKK kampüsündeki NovaX otomat şirketinin müşteri hizmetleri asistanısın.
Kahve ve snack otomatları konusunda yardım ediyorsun.
Türkçe cevap ver, samimi ve yardımsever ol.
Eğer ürün çıkmadı, para iade gibi sorunlar varsa özür dile ve en kısa sürede çözüleceğini söyle.
Acil durumlarda ekibimizin bilgilendirileceğini belirt.
Kısa ve net cevaplar ver.""",
        messages=[{"role": "user", "content": f"Müşteri @{username} şunu yazdı: {user_message}"}]
    )
    return response.content[0].text

def send_instagram_reply(recipient_id, message):
    url = f"https://graph.facebook.com/v25.0/me/messages"
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": message},
        "access_token": INSTAGRAM_ACCESS_TOKEN
    }
    return requests.post(url, json=payload).json()

def publish_instagram_post(image_url, caption):
    media_url = f"https://graph.facebook.com/v25.0/{INSTAGRAM_BUSINESS_ACCOUNT_ID}/media"
    media_response = requests.post(media_url, json={
        "image_url": image_url,
        "caption": caption,
        "access_token": INSTAGRAM_ACCESS_TOKEN
    }).json()

    if "id" in media_response:
        creation_id = media_response["id"]
        return requests.post(
            f"https://graph.facebook.com/v25.0/{INSTAGRAM_BUSINESS_ACCOUNT_ID}/media_publish",
            json={"creation_id": creation_id, "access_token": INSTAGRAM_ACCESS_TOKEN}
        ).json()
    return media_response

@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403

@app.route("/webhook", methods=["POST"])
def handle_webhook():
    data = request.json
    if data.get("object") == "instagram":
        for entry in data.get("entry", []):
            for messaging in entry.get("messaging", []):
                sender_id = messaging.get("sender", {}).get("id")
                message = messaging.get("message", {}).get("text", "")
                if message and sender_id:
                    user_info = requests.get(
                        f"https://graph.facebook.com/v25.0/{sender_id}",
                        params={"fields": "name,username", "access_token": INSTAGRAM_ACCESS_TOKEN}
                    ).json()
                    username = user_info.get("username", "kullanıcı")
                    reply = generate_dm_reply(message, username)
                    reply_id = f"reply_{sender_id}_{int(time.time())}"
                    pending_replies[reply_id] = {"sender_id": sender_id, "reply": reply}

                    buttons = [[
                        {"text": "✅ Onayla", "callback_data": f"approve_{reply_id}"},
                        {"text": "❌ Reddet", "callback_data": f"reject_{reply_id}"}
                    ]]
                    send_telegram_with_buttons(
                        f"📩 <b>Yeni Instagram DM!</b>\n👤 @{username}\n💬 {message}\n\n🤖 AI Cevabı:\n{reply}\n\nOnaylıyor musunuz?",
                        buttons
                    )
    return jsonify({"status": "ok"})

@app.route("/telegram-webhook", methods=["POST"])
def telegram_webhook():
    data = request.json

    # Kullanıcı feedback mesajı bekliyorsa
    message = data.get("message")
    if message:
        chat_id = str(message.get("chat", {}).get("id", ""))
        text = message.get("text", "")
        if chat_id == str(TELEGRAM_CHAT_ID) and chat_id in waiting_feedback:
            post_id = waiting_feedback.pop(chat_id)
            send_telegram("⏳ Fikrinizle yeni post oluşturuluyor...")
            new_caption = generate_post(feedback=text)
            new_post_id = f"post_{int(time.time())}"
            send_post_to_telegram(new_caption, new_post_id)
            return jsonify({"status": "ok"})

    callback = data.get("callback_query")
    if callback:
        callback_data = callback.get("data", "")

        if callback_data.startswith("approve_reply_"):
            reply_id = callback_data.replace("approve_", "")
            if reply_id in pending_replies:
                info = pending_replies.pop(reply_id)
                send_instagram_reply(info["sender_id"], info["reply"])
                send_telegram("✅ Cevap gönderildi!")

        elif callback_data.startswith("reject_reply_"):
            reply_id = callback_data.replace("reject_", "")
            pending_replies.pop(reply_id, None)
            send_telegram("❌ Cevap iptal edildi.")

        elif callback_data.startswith("approve_post_"):
            post_id = callback_data.replace("approve_post_", "")
            if post_id in pending_posts:
                info = pending_posts.pop(post_id)
                result = publish_instagram_post(info["image_url"], info["caption"])
                if "id" in result:
                    send_telegram("✅ Post Instagram'da paylaşıldı!")
                else:
                    send_telegram(f"❌ Post paylaşılamadı: {result}")

        elif callback_data.startswith("reject_post_"):
            post_id = callback_data.replace("reject_post_", "")
            pending_posts.pop(post_id, None)
            send_telegram("❌ Post iptal edildi.")

        elif callback_data.startswith("regen_post_"):
            send_telegram("⏳ Yeni post oluşturuluyor...")
            new_caption = generate_post()
            new_post_id = f"post_{int(time.time())}"
            send_post_to_telegram(new_caption, new_post_id)

        elif callback_data.startswith("feedback_post_"):
            chat_id = str(callback.get("message", {}).get("chat", {}).get("id", ""))
            waiting_feedback[chat_id] = f"post_{int(time.time())}"
            send_telegram("💡 Fikrinizi yazın (örn: 'daha kısa olsun', 'kahve temalı yap', 'daha eğlenceli olsun'):")

    return jsonify({"status": "ok"})

@app.route("/generate-post", methods=["GET"])
def trigger_post():
    caption = generate_post()
    post_id = f"post_{int(time.time())}"
    send_post_to_telegram(caption, post_id)
    return jsonify({"status": "Post onay için Telegram'a gönderildi"})

def daily_post_job():
    try:
        caption = generate_post()
        post_id = f"post_{int(time.time())}"
        send_post_to_telegram(caption, post_id)
    except Exception as e:
        send_telegram(f"❌ Post oluşturma hatası: {str(e)}")

def run_scheduler():
    schedule.every().day.at("10:00").do(daily_post_job)
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    railway_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")
    if railway_domain:
        requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook",
            params={"url": f"https://{railway_domain}/telegram-webhook"}
        )

    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()

    send_telegram("🚀 NovaX Bot başlatıldı!")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
