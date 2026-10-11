import json
import os
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import boto3

REGION = "ap-south-1"
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
API_URL = os.environ.get("API_URL", "https://9p18wspqok.execute-api.ap-south-1.amazonaws.com/check")

table = boto3.resource("dynamodb", region_name=REGION).Table("Saans-Checks")
polly = boto3.client("polly", region_name=REGION)

HEALTH = {"normal": "Normal", "asthma": "Asthma / breathing problem", "elderly": "Elderly",
          "child": "Child", "pregnant": "Pregnant"}
HEALTH_LABEL = {
    "en": {"normal": "Normal", "asthma": "Asthma", "elderly": "Elderly", "child": "Child", "pregnant": "Pregnant"},
    "hi": {"normal": "सामान्य", "asthma": "अस्थमा", "elderly": "बुज़ुर्ग", "child": "बच्चा", "pregnant": "गर्भवती"},
}
BANDS = {
    "en": ["Good", "Moderate", "Unhealthy for sensitive people", "Unhealthy", "Very unhealthy", "Hazardous"],
    "hi": ["अच्छी", "सामान्य", "संवेदनशील लोगों के लिए खराब", "खराब", "बहुत खराब", "खतरनाक"],
}
EMOJI = ["🟢", "🟡", "🟠", "🔴", "🟣", "🟤"]

TXT = {
    "en": {
        "start": ("Namaste! I am Saans Saathi 🌬️\n\nSend me the name of any Indian city or town, or share your "
                  "location (📎 > Location), and I will tell you how the air is and what to do today.\n\n"
                  "Commands:\n/compare Delhi Mumbai Pune - compare cities\n/alerts - your alert settings\n"
                  "/stats - bot stats\n/hi or /en - language\n\n"
                  "First choose your language and health profile below. Advisory only, not an official government order."),
        "wait": "Checking air...",
        "nocity": "I could not find that city in India. Please check the spelling and try again.",
        "fail": "Could not get air data right now. Please try again in a minute.",
        "lang": "Language set to English.", "health": "Health profile set: ",
        "aqi": "AQI (US scale)", "grap": "GRAP (approx.)", "adv": "Advice",
        "tom": "Tomorrow max AQI", "worse": "⚠️ Air will be worse tomorrow. Plan outdoor work early.",
        "better": "Air should improve tomorrow.", "same": "Air will be about the same tomorrow.",
        "src_rule": "rule-based", "src_ai": "AI, Amazon Bedrock",
        "spike": "⚠️ PM10 is extremely high. This may be a dust spike or bad data. Be careful and double-check.",
        "foot": "Not medical advice. Not an official government order.",
        "loc": "Your location", "safe": "⏱ Safe time outside", "mask": "😷 Mask",
        "unl": "no limit", "min": "min", "hr": "hr",
        "m_none": "not needed", "m_surg": "cloth/surgical is okay", "m_n95": "N95", "m_n95s": "N95, well fitted",
        "listen": "🔊 Listen", "subscribe": "🔔 Alert me", "unsub": "🔕 Stop alerts", "up": "👍 Helpful", "down": "👎 Not helpful",
        "thanks": "Thank you for your feedback!", "voice_fail": "Voice is not available right now. The text advice above is the same.",
        "subbed": "Done. I will message you here when the air in {c} becomes unhealthy (checked every hour), and send a short morning update at 7:30.",
        "unsubbed": "Alerts stopped.", "nosub": "You have no alerts set. Check a city and tap 🔔 Alert me.",
        "mysub": "Your alert city: {c}. Tap below to stop.", "nolast": "Please check a city first.",
        "cmp_help": "Use: /compare Delhi Mumbai Pune (2 to 5 cities)", "cmp_title": "Air quality compared (US AQI)",
        "stats": "Saans Saathi bot\nPeople: {u}\nAir checks: {c}\nAlerts set: {s}\nFeedback: 👍 {up}  👎 {dn}",
    },
    "hi": {
        "start": ("नमस्ते! मैं साँस साथी हूँ 🌬️\n\nकिसी भी भारतीय शहर या कस्बे का नाम भेजिए, या अपनी लोकेशन "
                  "शेयर कीजिए (📎 > Location)। मैं बताऊँगा कि हवा कैसी है और आज क्या करना चाहिए।\n\n"
                  "कमांड:\n/compare Delhi Mumbai Pune - शहरों की तुलना\n/alerts - आपके अलर्ट\n"
                  "/stats - बॉट के आँकड़े\n/hi या /en - भाषा\n\n"
                  "पहले नीचे से भाषा और सेहत चुनें। यह सिर्फ सलाह है, सरकारी आदेश नहीं।"),
        "wait": "हवा चेक हो रही है...",
        "nocity": "यह शहर भारत में नहीं मिला। स्पेलिंग जाँचकर फिर कोशिश करें।",
        "fail": "अभी हवा का डेटा नहीं मिल पाया। एक मिनट बाद फिर कोशिश करें।",
        "lang": "भाषा हिंदी कर दी गई।", "health": "सेहत प्रोफ़ाइल: ",
        "aqi": "AQI (US स्केल)", "grap": "GRAP (अंदाज़न)", "adv": "सलाह",
        "tom": "कल का ज़्यादा से ज़्यादा AQI", "worse": "⚠️ कल हवा और खराब होगी। बाहर का काम जल्दी निपटा लें।",
        "better": "कल हवा बेहतर हो सकती है।", "same": "कल हवा लगभग ऐसी ही रहेगी।",
        "src_rule": "नियम आधारित", "src_ai": "AI, Amazon Bedrock",
        "spike": "⚠️ PM10 बहुत ज़्यादा है। यह धूल का उछाल या गलत डेटा हो सकता है। सावधान रहें और दोबारा जाँचें।",
        "foot": "यह डॉक्टर की सलाह नहीं है। सरकारी आदेश नहीं है।",
        "loc": "आपकी लोकेशन", "safe": "⏱ बाहर रहने का सुरक्षित समय", "mask": "😷 मास्क",
        "unl": "कोई सीमा नहीं", "min": "मिनट", "hr": "घंटे",
        "m_none": "ज़रूरत नहीं", "m_surg": "कपड़े/सर्जिकल चलेगा", "m_n95": "N95", "m_n95s": "N95, ठीक से फिट करके",
        "listen": "🔊 सुनें", "subscribe": "🔔 अलर्ट चाहिए", "unsub": "🔕 अलर्ट बंद करें", "up": "👍 काम की", "down": "👎 काम की नहीं",
        "thanks": "फीडबैक के लिए धन्यवाद!", "voice_fail": "अभी आवाज़ उपलब्ध नहीं है। ऊपर लिखी सलाह वही है।",
        "subbed": "हो गया। {c} में हवा खराब होते ही मैं यहीं मैसेज करूँगा (हर घंटे जाँच), और सुबह 7:30 बजे छोटा अपडेट भेजूँगा।",
        "unsubbed": "अलर्ट बंद कर दिए।", "nosub": "आपका कोई अलर्ट सेट नहीं है। कोई शहर चेक करके 🔔 दबाएँ।",
        "mysub": "आपका अलर्ट शहर: {c}। बंद करने के लिए नीचे दबाएँ।", "nolast": "पहले कोई शहर चेक करें।",
        "cmp_help": "ऐसे लिखें: /compare Delhi Mumbai Pune (2 से 5 शहर)", "cmp_title": "हवा की तुलना (US AQI)",
        "stats": "साँस साथी बॉट\nलोग: {u}\nहवा की जाँच: {c}\nअलर्ट सेट: {s}\nफीडबैक: 👍 {up}  👎 {dn}",
    },
}


def band_index(a):
    return 0 if a <= 50 else 1 if a <= 100 else 2 if a <= 150 else 3 if a <= 200 else 4 if a <= 300 else 5


# ---------- Telegram helpers ----------
def tg(method, payload):
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",
        data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.read()


def send(chat_id, text, buttons=None):
    p = {"chat_id": chat_id, "text": text[:4000]}
    if buttons:
        p["reply_markup"] = {"inline_keyboard": buttons}
    try:
        tg("sendMessage", p)
    except Exception as e:
        print("send error:", e)


def answer_cb(cb_id, text=""):
    try:
        tg("answerCallbackQuery", {"callback_query_id": cb_id, "text": text[:180]})
    except Exception as e:
        print("answer error:", e)


def send_audio(chat_id, mp3, title):
    """Upload an mp3 with multipart/form-data (no extra libraries needed)."""
    b = uuid.uuid4().hex
    parts = []
    for k, v in (("chat_id", str(chat_id)), ("title", title), ("performer", "Saans Saathi")):
        parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode("utf-8"))
    parts.append((f'--{b}\r\nContent-Disposition: form-data; name="audio"; filename="saans.mp3"\r\n'
                  "Content-Type: audio/mpeg\r\n\r\n").encode("utf-8") + mp3 + b"\r\n")
    parts.append(f"--{b}--\r\n".encode("utf-8"))
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendAudio", data=b"".join(parts),
        headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


# ---------- storage ----------
def get_prefs(chat_id):
    try:
        it = table.get_item(Key={"checkId": f"tg#{chat_id}"}).get("Item") or {}
    except Exception as e:
        print("prefs read error:", e)
        it = {}
    return it.get("lang", "hi"), it.get("health", "Normal")


def save_prefs(chat_id, lang, health):
    try:
        table.put_item(Item={"checkId": f"tg#{chat_id}", "lang": lang, "health": health,
                             "updated": int(time.time())})
    except Exception as e:
        print("prefs write error:", e)


def save_last(chat_id, j, lat, lon):
    keep = {k: j.get(k) for k in ("city", "aqi", "advice")}
    keep["lat"], keep["lon"] = lat, lon
    try:
        table.put_item(Item={"checkId": f"tglast#{chat_id}", "data": json.dumps(keep, ensure_ascii=False)})
    except Exception as e:
        print("last write error:", e)


def load_last(chat_id):
    try:
        it = table.get_item(Key={"checkId": f"tglast#{chat_id}"}).get("Item")
        return json.loads(it["data"]) if it else None
    except Exception as e:
        print("last read error:", e)
        return None


def count_prefix(prefix, extra=None):
    n, kw = 0, {"FilterExpression": "begins_with(checkId, :p)",
                "ExpressionAttributeValues": {":p": prefix}, "ProjectionExpression": "checkId" + (", " + extra if extra else "")}
    items = []
    while True:
        r = table.scan(**kw)
        items += r.get("Items", [])
        if "LastEvaluatedKey" not in r:
            break
        kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]
    return items


# ---------- air quality ----------
def call_api(city, lang, health, lat=None, lon=None):
    q = {"city": city, "lang": lang, "health": health, "role": "General"}
    if lat is not None and lon is not None:
        q["lat"], q["lon"] = lat, lon
    req = urllib.request.Request(API_URL + "?" + urllib.parse.urlencode(q), headers={"User-Agent": "SaansSaathiBot"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, {}


def safe_line(aqi, health, lang):
    t = TXT[lang]
    sens = health != "Normal"
    if aqi <= 50: mins = None
    elif aqi <= 100: mins = 240 if sens else None
    elif aqi <= 150: mins = 90 if sens else 240
    elif aqi <= 200: mins = 45 if sens else 120
    elif aqi <= 300: mins = 20 if sens else 60
    else: mins = 0 if sens else 30
    if mins is None: st = t["unl"]
    elif mins >= 60: st = f"{mins // 60} {t['hr']}"
    else: st = f"{mins} {t['min']}"
    mk = (t["m_none"] if aqi <= 50 else (t["m_n95"] if sens else t["m_surg"]) if aqi <= 100
          else t["m_n95"] if aqi <= 200 else t["m_n95s"])
    return f"{t['safe']}: {st}\n{t['mask']}: {mk}"


def format_reply(j, lang, health):
    t = TXT[lang]
    b = band_index(j["aqi"])
    lines = [f"📍 {j['city']}", f"{EMOJI[b]} {t['aqi']}: {j['aqi']} ({BANDS[lang][b]})",
             f"PM2.5: {round(j['pm25'])}  |  PM10: {round(j['pm10'])} µg/m³",
             f"{t['grap']}: {j.get('grap_stage', '-')}", "", safe_line(j["aqi"], health, lang)]
    if j.get("pm10") and j["pm10"] > 600:
        lines += ["", t["spike"]]
    src = t["src_ai"] if j.get("advice_source") == "bedrock" else t["src_rule"]
    lines += ["", f"{t['adv']} ({src}):", j.get("advice", "")]
    fc = j.get("forecast") or []
    if fc:
        tr = j.get("trend", "same")
        lines += ["", f"{t['tom']}: {fc[0]['max_aqi']}", t["worse"] if tr == "worse" else t["better"] if tr == "better" else t["same"]]
    lines += ["", t["foot"]]
    return "\n".join(lines)


def result_buttons(lang, subscribed=False):
    t = TXT[lang]
    return [[{"text": t["listen"], "callback_data": "voice"},
             {"text": t["unsub"] if subscribed else t["subscribe"], "callback_data": "unsub" if subscribed else "sub"}],
            [{"text": t["up"], "callback_data": "fb|up"}, {"text": t["down"], "callback_data": "fb|down"}]]


def start_buttons(lang):
    hl = HEALTH_LABEL[lang]
    return [[{"text": "हिंदी", "callback_data": "lang|hi"}, {"text": "English", "callback_data": "lang|en"}],
            [{"text": hl[k], "callback_data": f"hl|{k}"} for k in ("normal", "asthma", "elderly")],
            [{"text": hl[k], "callback_data": f"hl|{k}"} for k in ("child", "pregnant")]]


def get_sub(chat_id):
    try:
        return table.get_item(Key={"checkId": f"sub#{chat_id}"}).get("Item")
    except Exception as e:
        print("sub read error:", e)
        return None


def check_city(chat_id, city, lang, health, lat=None, lon=None):
    t = TXT[lang]
    send(chat_id, t["wait"])
    try:
        status, j = call_api(city, lang, health, lat, lon)
    except Exception as e:
        print("api error:", e)
        send(chat_id, t["fail"])
        return
    if status == 404:
        send(chat_id, t["nocity"])
    elif status != 200 or "aqi" not in j:
        send(chat_id, t["fail"])
    else:
        save_last(chat_id, j, lat, lon)
        send(chat_id, format_reply(j, lang, health), result_buttons(lang, bool(get_sub(chat_id))))


# ---------- features ----------
def do_voice(chat_id, lang):
    t = TXT[lang]
    last = load_last(chat_id)
    if not last:
        send(chat_id, t["nolast"])
        return
    advice = " ".join(l.split(") ", 1)[-1] for l in (last.get("advice") or "").split("\n"))
    b = band_index(last["aqi"])
    if lang == "hi":
        text = f"{last['city']} में अभी AQI {last['aqi']} है। हवा {BANDS['hi'][b]} है। {advice}"
        code = "hi-IN"
    else:
        text = f"Air in {last['city']} right now: AQI {last['aqi']}, {BANDS['en'][b]}. {advice}"
        code = "en-IN"
    try:
        r = polly.synthesize_speech(Text=text[:2900], OutputFormat="mp3", VoiceId="Kajal",
                                    Engine="neural", LanguageCode=code)
        send_audio(chat_id, r["AudioStream"].read(), f"Saans Saathi: {last['city']}")
    except Exception as e:
        print("polly error:", repr(e))
        send(chat_id, t["voice_fail"])


def do_subscribe(chat_id, lang, health):
    t = TXT[lang]
    last = load_last(chat_id)
    if not last:
        send(chat_id, t["nolast"])
        return
    item = {"checkId": f"sub#{chat_id}", "chat_id": str(chat_id), "city": last["city"],
            "lang": lang, "health": health, "created": int(time.time())}
    if last.get("lat") is not None:
        item["lat"], item["lon"] = str(last["lat"]), str(last["lon"])
    try:
        table.put_item(Item=item)
        send(chat_id, t["subbed"].format(c=last["city"]))
    except Exception as e:
        print("sub write error:", e)
        send(chat_id, t["fail"])


def do_unsubscribe(chat_id, lang):
    t = TXT[lang]
    try:
        table.delete_item(Key={"checkId": f"sub#{chat_id}"})
    except Exception as e:
        print("unsub error:", e)
    send(chat_id, t["unsubbed"])


def do_feedback(chat_id, vote, last):
    try:
        table.put_item(Item={"checkId": f"fb#{uuid.uuid4()}", "chat_id": str(chat_id), "vote": vote,
                             "city": (last or {}).get("city", ""), "ts": int(time.time())})
    except Exception as e:
        print("feedback error:", e)


def do_compare(chat_id, args, lang, health):
    t = TXT[lang]
    cities = [c for c in args if c][:5]
    if len(cities) < 2:
        send(chat_id, t["cmp_help"])
        return
    send(chat_id, t["wait"])
    with ThreadPoolExecutor(max_workers=5) as ex:
        res = list(ex.map(lambda c: (c, call_api(c, lang, health)), cities))
    rows = [(j["city"], j["aqi"]) for c, (s, j) in res if s == 200 and "aqi" in j]
    if not rows:
        send(chat_id, t["fail"])
        return
    rows.sort(key=lambda x: x[1], reverse=True)
    lines = [t["cmp_title"], ""]
    for city, aqi in rows:
        b = band_index(aqi)
        lines.append(f"{EMOJI[b]} {city}: {aqi} ({BANDS[lang][b]})")
    send(chat_id, "\n".join(lines))


def do_stats(chat_id, lang):
    t = TXT[lang]
    try:
        users = len(count_prefix("tg#"))
        checks = len(count_prefix("tglast#"))
        subs = len(count_prefix("sub#"))
        fb = count_prefix("fb#", "vote")
        up = sum(1 for x in fb if x.get("vote") == "up")
        dn = sum(1 for x in fb if x.get("vote") == "down")
        send(chat_id, t["stats"].format(u=users, c=checks, s=subs, up=up, dn=dn))
    except Exception as e:
        print("stats error:", e)
        send(chat_id, t["fail"])


# ---------- routing ----------
def handle_callback(cb):
    chat_id = cb["message"]["chat"]["id"]
    data = cb.get("data", "")
    lang, health = get_prefs(chat_id)
    if data.startswith("lang|"):
        lang = data.split("|")[1] if data.split("|")[1] in ("hi", "en") else lang
        save_prefs(chat_id, lang, health)
        answer_cb(cb["id"], TXT[lang]["lang"])
    elif data.startswith("hl|"):
        key = data.split("|")[1]
        if key in HEALTH:
            save_prefs(chat_id, lang, HEALTH[key])
            answer_cb(cb["id"], TXT[lang]["health"] + HEALTH_LABEL[lang][key])
        else:
            answer_cb(cb["id"])
    elif data == "voice":
        answer_cb(cb["id"], "🔊")
        do_voice(chat_id, lang)
    elif data == "sub":
        answer_cb(cb["id"], "🔔")
        do_subscribe(chat_id, lang, health)
    elif data == "unsub":
        answer_cb(cb["id"], "🔕")
        do_unsubscribe(chat_id, lang)
    elif data.startswith("fb|"):
        do_feedback(chat_id, "up" if data.endswith("up") else "down", load_last(chat_id))
        answer_cb(cb["id"], TXT[lang]["thanks"])
    else:
        answer_cb(cb["id"])


def handle_update(upd):
    if upd.get("callback_query"):
        handle_callback(upd["callback_query"])
        return
    msg = upd.get("message") or upd.get("edited_message")
    if not msg:
        return
    chat_id = msg["chat"]["id"]
    lang, health = get_prefs(chat_id)
    t = TXT[lang]
    text = (msg.get("text") or "").strip()
    cmd = text.split()[0].split("@")[0].lower() if text.startswith("/") else ""
    args = text.split()[1:] if cmd else []

    if cmd in ("/start", "/help"):
        send(chat_id, t["start"], start_buttons(lang))
    elif cmd == "/hi":
        save_prefs(chat_id, "hi", health)
        send(chat_id, TXT["hi"]["lang"])
    elif cmd == "/en":
        save_prefs(chat_id, "en", health)
        send(chat_id, TXT["en"]["lang"])
    elif cmd == "/health":
        key = args[0].lower() if args else ""
        if key in HEALTH:
            save_prefs(chat_id, lang, HEALTH[key])
            send(chat_id, t["health"] + HEALTH_LABEL[lang][key])
        else:
            send(chat_id, t["start"], start_buttons(lang))
    elif cmd == "/compare":
        do_compare(chat_id, args, lang, health)
    elif cmd == "/alerts":
        sub = get_sub(chat_id)
        if sub:
            send(chat_id, t["mysub"].format(c=sub["city"]), [[{"text": t["unsub"], "callback_data": "unsub"}]])
        else:
            send(chat_id, t["nosub"])
    elif cmd == "/stats":
        do_stats(chat_id, lang)
    elif msg.get("location"):
        check_city(chat_id, t["loc"], lang, health, msg["location"]["latitude"], msg["location"]["longitude"])
    elif text and not cmd:
        check_city(chat_id, text[:60], lang, health)
    else:
        send(chat_id, t["start"], start_buttons(lang))


def lambda_handler(event, context):
    headers = {k.lower(): v for k, v in ((event or {}).get("headers") or {}).items()}
    if WEBHOOK_SECRET and headers.get("x-telegram-bot-api-secret-token") != WEBHOOK_SECRET:
        return {"statusCode": 403, "body": "forbidden"}
    try:
        handle_update(json.loads((event or {}).get("body") or "{}"))
    except Exception as e:
        print("handler error:", repr(e))
    return {"statusCode": 200, "body": "ok"}
