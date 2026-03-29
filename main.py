import os
import requests
import base64
import time
import threading
import schedule
from flask import Flask, request, jsonify
from anthropic import Anthropic
from openai import OpenAI

app = Flask(__name__)
claude = Anthropic(api_key=os.environ.get("CLAUDE_API_KEY"))
openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

INSTAGRAM_ACCESS_TOKEN = os.environ.get("INSTAGRAM_ACCESS_TOKEN")
INSTAGRAM_BUSINESS_ACCOUNT_ID = os.environ.get("INSTAGRAM_BUSINESS_ACCOUNT_ID")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
WEATHER_API_KEY = os.environ.get("WEATHER_API_KEY")
NEWS_API_KEY = os.environ.get("NEWS_API_KEY")

pending_replies = {}
pending_posts = {}
waiting_feedback = {}
conversation_history = []  # Sohbet geçmişi

NOVAX_SYSTEM = """Sen NovaX'in kişisel AI asistanısın. NovaX, ODTÜ KKK kampüsünde kahve ve snack otomatı işleten bir şirkettir.

GÖREVLER:
1. Instagram için post ve story içeriği üret
2. Haber ve hava durumu özetle
3. İşletme sahibiyle sohbet et, fikir ver, strateji öner

KİŞİLİK:
- Son derece sıcak, samimi ve arkadaşça konuş
- "Veysel" diye hitap et
- Emoji kullan ama abartma
- Türkçe konuş

NOVAX MARKA DEĞERLERİ:
- Öğrenci dostu ve pratiklik mesajı ver
- Enerjik ve modern dil kullan
- ODTÜ kampüs kültürüne uygun içerik üret
- Her içerikte NovaX markasını öne çıkar

INSTAGRAM İÇERİK STRATEJİSİ:
- Post: Bilgilendirici, eğlenceli, etkileşim odaklı
- Story: Enerjik, motivasyonel, günlük hayata dokunan
- Hashtagler Türkçe ve İngilizce karışık olsun
- Her içerikte "Öğrenci dostu" ve "Pratiklik" mesajı olsun"""

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

def send_telegram_photo_with_buttons(image_url, caption, buttons):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    response = requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "photo": image_url,
        "caption": caption,
        "reply_markup": {"inline_keyboard": buttons},
        "parse_mode": "HTML"
    })
    if not response.json().get("ok"):
        send_telegram_with_buttons(caption, buttons)

def get_weather():
    try:
        url = f"http://api.weatherapi.com/v1/current.json?key={WEATHER_API_KEY}&q=Ankara&lang=tr"
        data = requests.get(url).json()
        temp = data["current"]["temp_c"]
        feels = data["current"]["feelslike_c"]
        condition = data["current"]["condition"]["text"]
        humidity = data["current"]["humidity"]
        return f"🌤 <b>Ankara Hava Durumu</b>\n🌡 {temp}°C (Hissedilen: {feels}°C)\n☁️ {condition}\n💧 Nem: %{humidity}"
    except Exception as e:
        return f"⚠️ Hava durumu alınamadı: {str(e)}"

def get_economy_news():
    try:
        url = f"https://api.currentsapi.services/v1/latest-news?apiKey={NEWS_API_KEY}&language=tr&category=business"
        data = requests.get(url).json()
        news = data.get("news", [])[:3]
        if not news:
            # İngilizce dene
            url2 = f"https://api.currentsapi.services/v1/latest-news?apiKey={NEWS_API_KEY}&language=en&category=business,finance"
            data2 = requests.get(url2).json()
            news = data2.get("news", [])[:3]

        if not news:
            return "⚠️ Ekonomi haberleri alınamadı."

        result = "📈 <b>Küresel Ekonomi Haberleri</b>\n\n"
        for i, item in enumerate(news, 1):
            result += f"{i}. {item['title']}\n"
        return result
    except Exception as e:
        return f"⚠️ Haberler alınamadı: {str(e)}"

def generate_image_dalle(prompt):
    try:
        response = openai_client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size="1024x1024",
            quality="standard",
            n=1
        )
        return response.data[0].url
    except Exception as e:
        send_telegram(f"⚠️ Görsel oluşturulamadı: {str(e)}")
        return None

def chat_with_claude(user_message):
    global conversation_history
    conversation_history.append({"role": "user", "content": user_message})
    
    # Son 20 mesajı tut
    if len(conversation_history) > 20:
        conversation_history = conversation_history[-20:]

    response = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        system=NOVAX_SYSTEM,
        messages=conversation_history
    )
    
    reply = response.content[0].text
    conversation_history.append({"role": "assistant", "content": reply})
    return reply

def generate_post_content(feedback=None, content_type="post"):
    prompt = f"NovaX için bir Instagram {content_type} içeriği yaz."
    if content_type == "story":
        prompt += " Story için kısa, enerjik ve motivasyonel olsun. NovaX yazısı mutlaka geçsin. Öğrenci dostu ve pratiklik mesajı ver."
    else:
        prompt += " Post için bilgilendirici ve etkileşim odaklı olsun. Hashtagler ekle."
    
    if feedback:
        prompt += f"\n\nKullanıcı isteği: {feedback}"
    
    prompt += "\n\nAyrıca son satırda IMAGE_PROMPT: ile İngilizce görsel promptu yaz. Otomat makinesi mutlaka görselde bulunsun."

    response = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=500,
        system=NOVAX_SYSTEM,
        messages=[{"role": "user", "content": prompt}]
    )
    
    full_text = response.content[0].text
    
    if "IMAGE_PROMPT:" in full_text:
        parts = full_text.split("IMAGE_PROMPT:")
        caption = parts[0].strip()
        image_prompt = parts[1].strip()
    else:
        caption = full_text
        image_prompt = "Modern NovaX vending machine at METU university campus with coffee and snacks, vibrant energetic atmosphere, students around, professional photography"
    
    return caption, image_prompt

def send_content_to_telegram(caption, image_url, post_id, content_type="post"):
    pending_posts[post_id] = {
        "caption": caption,
        "image_url": image_url,
        "type": content_type
    }
    
    type_emoji = "📸" if content_type == "post" else "📖"
    type_label = "Post" if content_type == "post" else "Story"
    
    telegram_caption = f"""{type_emoji} <b>{type_label} Hazır!</b>

📝 <b>İçerik:</b>
{caption}

Onaylıyor musun?"""

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
    
    if image_url:
        send_telegram_photo_with_buttons(image_url, telegram_caption, buttons)
    else:
        send_telegram_with_buttons(telegram_caption, buttons)

def morning_briefing():
    send_telegram("☀️ <b>Günaydın Veysel! İşte sabah brifing'in:</b>")
    
    # Hava durumu
    weather = get_weather()
    send_telegram(weather)
    
    # Story oluştur
    send_telegram("📖 Bugünkü story hazırlanıyor...")
    caption, image_prompt = generate_post_content(content_type="story")
    image_url = generate_image_dalle(image_prompt)
    story_id = f"story_{int(time.time())}"
    send_content_to_telegram(caption, image_url, story_id, "story")

def afternoon_post():
    send_telegram("🌆 <b>Öğleden sonra post zamanı!</b>")
    caption, image_prompt = generate_post_content(content_type="post")
    image_url = generate_image_dalle(image_prompt)
    post_id = f"post_{int(time.time())}"
    send_content_to_telegram(caption, image_url, post_id, "post")

def economy_news_update():
    news = get_economy_news()
    send_telegram(news)

def publish_instagram(image_url, caption, is_story=False):
    media_url = f"https://graph.facebook.com/v25.0/{INSTAGRAM_BUSINESS_ACCOUNT_ID}/media"
    payload = {
        "image_url": image_url,
        "caption": caption,
        "access_token": INSTAGRAM_ACCESS_TOKEN
    }
    if is_story:
        payload["media_type"] = "IMAGE"

    media_response = requests.post(media_url, json=payload).json()
    if "id" in media_response:
        return requests.post(
            f"https://graph.facebook.com/v25.0/{INSTAGRAM_BUSINESS_ACCOUNT_ID}/media_publish",
            json={"creation_id": media_response["id"], "access_token": INSTAGRAM_ACCESS_TOKEN}
        ).json()
    return media_response

def generate_dm_reply(user_message, username):
    response = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=300,
        system="""Sen ODTÜ KKK'daki NovaX otomat şirketinin müşteri hizmetleri asistanısın.
Türkçe, samimi ve yardımsever cevap ver. Kısa ve net ol.""",
        messages=[{"role": "user", "content": f"Müşteri @{username}: {user_message}"}]
    )
    return response.content[0].text

def send_instagram_reply(recipient_id, message):
    return requests.post(
        f"https://graph.facebook.com/v25.0/me/messages",
        json={"recipient": {"id": recipient_id}, "message": {"text": message}, "access_token": INSTAGRAM_ACCESS_TOKEN}
    ).json()

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
                        params={"fields": "username", "access_token": INSTAGRAM_ACCESS_TOKEN}
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
                        f"📩 <b>Yeni DM!</b>\n👤 @{username}\n💬 {message}\n\n🤖 Cevap:\n{reply}",
                        buttons
                    )
    return jsonify({"status": "ok"})

@app.route("/telegram-webhook", methods=["POST"])
def telegram_webhook():
    data = request.json

    # Normal mesaj — sohbet modu
    message = data.get("message")
    if message:
        chat_id = str(message.get("chat", {}).get("id", ""))
        text = message.get("text", "")
        photo = message.get("photo")

        if chat_id != str(TELEGRAM_CHAT_ID):
            return jsonify({"status": "ok"})

        # Feedback bekleniyor mu?
        if chat_id in waiting_feedback and text:
            post_info = waiting_feedback.pop(chat_id)
            send_telegram("⏳ İsteğine göre yeni içerik hazırlanıyor...")
            caption, image_prompt = generate_post_content(feedback=text, content_type=post_info.get("type", "post"))
            image_url = generate_image_dalle(image_prompt)
            new_id = f"post_{int(time.time())}"
            send_content_to_telegram(caption, image_url, new_id, post_info.get("type", "post"))
            return jsonify({"status": "ok"})

        # Fotoğraf gönderildiyse — reklam görseli oluştur
        if photo:
            send_telegram("🎨 Görseliniz için reklam içeriği hazırlanıyor...")
            caption, image_prompt = generate_post_content(feedback="Gönderilen ürün görseline uygun reklam içeriği yaz")
            image_url = generate_image_dalle(f"Professional advertisement for NovaX vending machine product, {image_prompt}, marketing style")
            new_id = f"post_{int(time.time())}"
            send_content_to_telegram(caption, image_url, new_id, "post")
            return jsonify({"status": "ok"})

        # Normal sohbet
        if text and not text.startswith("/"):
            reply = chat_with_claude(text)
            send_telegram(reply)

    # Buton callback'leri
    callback = data.get("callback_query")
    if callback:
        callback_data = callback.get("data", "")

        if callback_data.startswith("approve_reply_"):
            reply_id = callback_data.replace("approve_", "")
            if reply_id in pending_replies:
                info = pending_replies.pop(reply_id)
                send_instagram_reply(info["sender_id"], info["reply"])
                send_telegram("✅ DM gönderildi!")

        elif callback_data.startswith("reject_reply_"):
            reply_id = callback_data.replace("reject_", "")
            pending_replies.pop(reply_id, None)
            send_telegram("❌ DM iptal edildi.")

        elif callback_data.startswith("approve_post_"):
            post_id = callback_data.replace("approve_post_", "")
            if post_id in pending_posts:
                info = pending_posts.pop(post_id)
                is_story = info.get("type") == "story"
                result = publish_instagram(info["image_url"], info["caption"], is_story)
                label = "Story" if is_story else "Post"
                if "id" in result:
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
            caption, image_prompt = generate_post_content(content_type=post_type)
            image_url = generate_image_dalle(image_prompt)
            new_id = f"post_{int(time.time())}"
            send_content_to_telegram(caption, image_url, new_id, post_type)

        elif callback_data.startswith("feedback_post_"):
            chat_id = str(callback.get("message", {}).get("chat", {}).get("id", ""))
            post_id = callback_data.replace("feedback_post_", "")
            post_type = pending_posts.get(post_id, {}).get("type", "post")
            waiting_feedback[chat_id] = {"id": post_id, "type": post_type}
            send_telegram("💡 Fikrni yaz, ona göre düzenleyeyim!\n\nÖrnek: 'daha enerjik olsun', 'sınav dönemi temalı yap'")

    return jsonify({"status": "ok"})

@app.route("/test-morning", methods=["GET"])
def test_morning():
    threading.Thread(target=morning_briefing).start()
    return jsonify({"status": "Sabah brifing başlatıldı"})

@app.route("/test-post", methods=["GET"])
def test_post():
    threading.Thread(target=afternoon_post).start()
    return jsonify({"status": "Post oluşturuluyor"})

@app.route("/test-news", methods=["GET"])
def test_news():
    threading.Thread(target=economy_news_update).start()
    return jsonify({"status": "Haberler gönderiliyor"})

def run_scheduler():
    schedule.every().day.at("08:00").do(lambda: threading.Thread(target=morning_briefing).start())
    schedule.every().day.at("12:00").do(lambda: threading.Thread(target=economy_news_update).start())
    schedule.every().day.at("17:00").do(lambda: threading.Thread(target=afternoon_post).start())
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
    send_telegram("🚀 NovaX AI Asistan aktif! Merhaba Veysel, bugün nasıl yardımcı olabilirim? 😊")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
