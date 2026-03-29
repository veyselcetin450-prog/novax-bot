import os
import requests
import base64
import time
import threading
import schedule
from flask import Flask, request, jsonify
from anthropic import Anthropic

app = Flask(__name__)
client = Anthropic(api_key=os.environ.get("CLAUDE_API_KEY"))

INSTAGRAM_ACCESS_TOKEN = os.environ.get("INSTAGRAM_ACCESS_TOKEN")
INSTAGRAM_BUSINESS_ACCOUNT_ID = os.environ.get("INSTAGRAM_BUSINESS_ACCOUNT_ID")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

pending_replies = {}
pending_posts = {}
waiting_feedback = {}

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"})

def send_telegram_with_buttons(message, buttons):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "reply_markup": {"inline_keyboard": buttons},
        "parse_mode": "HTML"
    })

def send_telegram_photo_bytes_with_buttons(image_bytes, caption, buttons):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    response = requests.post(url, data={
        "chat_id": TELEGRAM_CHAT_ID,
        "caption": caption,
        "reply_markup": str({"inline_keyboard": buttons}),
        "parse_mode": "HTML"
    }, files={"photo": ("image.png", image_bytes, "image/png")})
    
    import json
    response_data = response.json()
    if not response_data.get("ok"):
        # JSON ile tekrar dene
        url2 = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        requests.post(url2, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "photo": "https://images.unsplash.com/photo-1509042239860-f550ce710b93?w=1080&q=80",
            "caption": caption + "\n\n⚠️ Görsel oluşturulamadı, varsayılan kullanıldı.",
            "reply_markup": {"inline_keyboard": buttons},
            "parse_mode": "HTML"
        })

def generate_image_with_gemini(prompt):
    """Gemini Imagen ile görsel üret"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-001:predict?key={GEMINI_API_KEY}"
    
    payload = {
        "instances": [{"prompt": prompt}],
        "parameters": {
            "sampleCount": 1,
            "aspectRatio": "1:1"
        }
    }
    
    response = requests.post(url, json=payload)
    data = response.json()
    
    if "predictions" in data and len(data["predictions"]) > 0:
        image_b64 = data["predictions"][0].get("bytesBase64Encoded", "")
        if image_b64:
            return base64.b64decode(image_b64)
    return None

def generate_post_and_image(feedback=None):
    """Post metni ve görsel üret"""
    import random
    topics = [
        "sabah kahvesi motivasyonu",
        "ders arası snack önerisi",
        "kampüs hayatı ve otomat",
        "sınav döneminde enerji",
        "yeni ürün tanıtımı"
    ]
    topic = random.choice(topics)

    user_content = f"Bugünkü konu: {topic}. Instagram postu yaz."
    if feedback:
        user_content += f"\n\nKullanıcı geri bildirimi: {feedback}"

    # Metin üret
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=400,
        system="""Sen ODTÜ KKK'daki NovaX otomat şirketinin sosyal medya yöneticisisin.
Instagram için Türkçe, enerjik ve genç bir dille post yazıyorsun.
Post metni + emoji + hashtag içermeli. Maksimum 150 kelime.
Ayrıca son satırda IMAGE_PROMPT: ile başlayan İngilizce bir görsel prompt yaz.
Örnek: IMAGE_PROMPT: A cozy vending machine with coffee and snacks in a university campus, warm lighting, modern design""",
        messages=[{"role": "user", "content": user_content}]
    )
    
    full_text = response.content[0].text
    
    # Metni ve görsel prompt'u ayır
    if "IMAGE_PROMPT:" in full_text:
        parts = full_text.split("IMAGE_PROMPT:")
        caption = parts[0].strip()
        image_prompt = parts[1].strip()
    else:
        caption = full_text
        image_prompt = f"Modern vending machine with coffee and snacks in METU university campus, {topic}, vibrant colors, professional photography"

    if feedback:
        image_prompt += f", {feedback}"

    # Görsel üret
    send_telegram("🎨 Gemini ile görsel oluşturuluyor...")
    image_bytes = generate_image_with_gemini(image_prompt)
    
    return caption, image_bytes

def send_post_to_telegram(caption, image_bytes, post_id, post_type="post"):
    pending_posts[post_id] = {
        "caption": caption,
        "image_bytes": image_bytes,
        "type": post_type
    }

    type_label = "📸 Post" if post_type == "post" else "📖 Story"
    telegram_caption = f"""{type_label} <b>Hazır!</b>

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

    if image_bytes:
        send_telegram_photo_bytes_with_buttons(image_bytes, telegram_caption, buttons)
    else:
        send_telegram_with_buttons(telegram_caption + "\n\n⚠️ Görsel oluşturulamadı.", buttons)

def publish_instagram_post(image_bytes, caption, is_story=False):
    """Görseli önce imgbb'ye yükle, sonra Instagram'a paylaş"""
    # imgbb'ye yükle (ücretsiz görsel hosting)
    imgbb_url = "https://api.imgbb.com/1/upload"
    image_b64 = base64.b64encode(image_bytes).decode()
    
    imgbb_response = requests.post(imgbb_url, data={
        "key": "your_imgbb_key",  # İsteğe bağlı
        "image": image_b64
    })
    
    # imgbb çalışmazsa Telegram'dan al
    if not imgbb_response.ok or "data" not in imgbb_response.json():
        # Geçici URL kullan
        image_url = "https://images.unsplash.com/photo-1509042239860-f550ce710b93?w=1080&q=80"
    else:
        image_url = imgbb_response.json()["data"]["url"]

    media_url = f"https://graph.facebook.com/v25.0/{INSTAGRAM_BUSINESS_ACCOUNT_ID}/media"
    
    payload = {
        "image_url": image_url,
        "caption": caption,
        "access_token": INSTAGRAM_ACCESS_TOKEN
    }
    
    if is_story:
        payload["media_type"] = "IMAGE"
        payload["is_carousel_item"] = False

    media_response = requests.post(media_url, json=payload).json()

    if "id" in media_response:
        creation_id = media_response["id"]
        publish_url = f"https://graph.facebook.com/v25.0/{INSTAGRAM_BUSINESS_ACCOUNT_ID}/media_publish"
        return requests.post(publish_url, json={
            "creation_id": creation_id,
            "access_token": INSTAGRAM_ACCESS_TOKEN
        }).json()
    return media_response

def generate_dm_reply(user_message, username):
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=500,
        system="""Sen ODTÜ KKK kampüsündeki NovaX otomat şirketinin müşteri hizmetleri asistanısın.
Kahve ve snack otomatları konusunda yardım ediyorsun.
Türkçe cevap ver, samimi ve yardımsever ol.
Eğer ürün çıkmadı, para iade gibi sorunlar varsa özür dile ve en kısa sürede çözüleceğini söyle.
Kısa ve net cevaplar ver.""",
        messages=[{"role": "user", "content": f"Müşteri @{username} şunu yazdı: {user_message}"}]
    )
    return response.content[0].text

def send_instagram_reply(recipient_id, message):
    url = f"https://graph.facebook.com/v25.0/me/messages"
    return requests.post(url, json={
        "recipient": {"id": recipient_id},
        "message": {"text": message},
        "access_token": INSTAGRAM_ACCESS_TOKEN
    }).json()

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

    message = data.get("message")
    if message:
        chat_id = str(message.get("chat", {}).get("id", ""))
        text = message.get("text", "")
        if chat_id == str(TELEGRAM_CHAT_ID) and chat_id in waiting_feedback:
            post_info = waiting_feedback.pop(chat_id)
            post_type = post_info.get("type", "post")
            send_telegram("⏳ Fikrinizle yeni içerik oluşturuluyor...")
            caption, image_bytes = generate_post_and_image(feedback=text)
            new_post_id = f"post_{int(time.time())}"
            send_post_to_telegram(caption, image_bytes, new_post_id, post_type)
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
                is_story = info.get("type") == "story"
                result = publish_instagram_post(info["image_bytes"], info["caption"], is_story)
                if "id" in result:
                    label = "Story" if is_story else "Post"
                    send_telegram(f"✅ {label} Instagram'da paylaşıldı!")
                else:
                    send_telegram(f"❌ Paylaşılamadı: {result}")

        elif callback_data.startswith("reject_post_"):
            post_id = callback_data.replace("reject_post_", "")
            pending_posts.pop(post_id, None)
            send_telegram("❌ İptal edildi.")

        elif callback_data.startswith("regen_post_"):
            old_id = callback_data.replace("regen_post_", "")
            old_info = pending_posts.pop(old_id, {})
            post_type = old_info.get("type", "post")
            send_telegram("⏳ Yeni içerik oluşturuluyor...")
            caption, image_bytes = generate_post_and_image()
            new_post_id = f"post_{int(time.time())}"
            send_post_to_telegram(caption, image_bytes, new_post_id, post_type)

        elif callback_data.startswith("feedback_post_"):
            chat_id = str(callback.get("message", {}).get("chat", {}).get("id", ""))
            post_id = callback_data.replace("feedback_post_", "")
            post_type = pending_posts.get(post_id, {}).get("type", "post")
            waiting_feedback[chat_id] = {"id": post_id, "type": post_type}
            send_telegram("💡 Fikrinizi yazın:\n\nÖrnek: 'daha enerjik olsun', 'kahve temalı yap', 'sınav dönemine uygun olsun'")

    return jsonify({"status": "ok"})

@app.route("/generate-post", methods=["GET"])
def trigger_post():
    send_telegram("⏳ Günlük post oluşturuluyor...")
    caption, image_bytes = generate_post_and_image()
    post_id = f"post_{int(time.time())}"
    send_post_to_telegram(caption, image_bytes, post_id, "post")
    return jsonify({"status": "Post Telegram'a gönderildi"})

@app.route("/generate-story", methods=["GET"])
def trigger_story():
    send_telegram("⏳ Günlük story oluşturuluyor...")
    caption, image_bytes = generate_post_and_image()
    post_id = f"story_{int(time.time())}"
    send_post_to_telegram(caption, image_bytes, post_id, "story")
    return jsonify({"status": "Story Telegram'a gönderildi"})

def daily_jobs():
    try:
        caption, image_bytes = generate_post_and_image()
        post_id = f"post_{int(time.time())}"
        send_post_to_telegram(caption, image_bytes, post_id, "post")
    except Exception as e:
        send_telegram(f"❌ Hata: {str(e)}")

def run_scheduler():
    schedule.every().day.at("10:00").do(daily_jobs)
    schedule.every().day.at("18:00").do(daily_jobs)
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

    threading.Thread(target=run_scheduler, daemon=True).start()
    send_telegram("🚀 NovaX Bot başlatıldı! Gemini görsel üretimi aktif.")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
