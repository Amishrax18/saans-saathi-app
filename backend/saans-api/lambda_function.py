import base64
import json
import time
import uuid
import urllib.parse
from xml.sax.saxutils import escape
import urllib.request

import boto3

REGION = "ap-south-1"
MODEL_ID = "apac.amazon.nova-lite-v1:0"

table = boto3.resource("dynamodb", region_name=REGION).Table("Saans-Checks")
bedrock = boto3.client("bedrock-runtime", region_name=REGION)
polly = boto3.client("polly", region_name=REGION)

HEADERS = {
    "Content-Type": "application/json; charset=utf-8",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "OPTIONS,GET",
}

# CPCB (India) AQI breakpoints: (conc_low, conc_high, index_low, index_high)
PM25_BP = [(0, 30, 0, 50), (30, 60, 51, 100), (60, 90, 101, 200),
           (90, 120, 201, 300), (120, 250, 301, 400), (250, 500, 401, 500)]
PM10_BP = [(0, 50, 0, 50), (50, 100, 51, 100), (100, 250, 101, 200),
           (250, 350, 201, 300), (350, 430, 301, 400), (430, 600, 401, 500)]

FALLBACK = {
    "en": [
        ["Safe to work outside today.", "Mask not needed."],
        ["You can work outside.", "Avoid heavy exertion if you have breathing trouble."],
        ["Do not stay outside more than 2-3 hours at a stretch.", "Wear an N95 or KN95 mask.", "Rest in the shade now and then."],
        ["Reduce outdoor work and rest every hour.", "Wear an N95 mask.", "Prefer afternoon over early morning or late evening."],
        ["Stay indoors unless necessary.", "If you must go out, wear an N95 mask.", "If you feel breathless, stop at once and see a doctor."],
    ],
    "hi": [
        ["आज बाहर काम करना सुरक्षित है.", "मास्क ज़रूरी नहीं."],
        ["बाहर काम कर सकते हैं.", "सांस में दिक्कत हो तो भारी मेहनत से बचें."],
        ["बाहर 2-3 घंटे से ज़्यादा लगातार न रहें.", "N95 या KN95 मास्क पहनें.", "बीच-बीच में छाँव में आराम करें."],
        ["बाहर का काम कम करें, हर घंटे आराम लें.", "N95 मास्क ज़रूर पहनें.", "सुबह-शाम की जगह दोपहर में काम करना बेहतर."],
        ["ज़रूरी न हो तो घर के अंदर रहें.", "बाहर जाना पड़े तो N95 मास्क पहनें.", "सांस फूले तो तुरंत रुकें और डॉक्टर से मिलें."],
    ],
}

LANG_RULE = {
    "en": "Reply in simple English.",
    "hi": "Reply only in simple Hindi written in Devanagari script.",
    "hinglish": "Reply in simple Hinglish (Roman Hindi).",
}


def http_json(url, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def get_coordinates(city):
    url = ("https://geocoding-api.open-meteo.com/v1/search?name="
           + urllib.parse.quote(city) + "&count=10&language=en&format=json&countryCode=IN")
    try:
        results = http_json(url).get("results") or []
    except Exception as e:
        print("Geocoding error:", e)
        return None
    if not results:
        return None
    # if the name is ambiguous, prefer the biggest place
    r = max(results, key=lambda x: x.get("population") or 0)
    return r["latitude"], r["longitude"], r.get("name", city)


def parse_coords(p):
    """Optional exact location from the website (lat, lon), only if inside India's bounding box."""
    try:
        lat = float(p.get("lat"))
        lon = float(p.get("lon"))
    except (TypeError, ValueError):
        return None
    if 6.0 <= lat <= 38.0 and 68.0 <= lon <= 98.0:
        return round(lat, 4), round(lon, 4)
    return None


def sub_index(conc, bps):
    if conc is None:
        return None
    for lo, hi, ilo, ihi in bps:
        if conc <= hi:
            return ilo + (max(conc, lo) - lo) * (ihi - ilo) / (hi - lo)
    return 500.0


def cpcb_aqi_approx(pm25, pm10):
    vals = [v for v in (sub_index(pm25, PM25_BP), sub_index(pm10, PM10_BP)) if v is not None]
    return int(round(max(vals))) if vals else None


def get_grap_stage(cpcb):
    if cpcb is None:
        return "Unknown"
    if cpcb > 450:
        return "GRAP Stage IV (Severe+)"
    if cpcb > 400:
        return "GRAP Stage III (Severe)"
    if cpcb > 300:
        return "GRAP Stage II (Very Poor)"
    if cpcb > 200:
        return "GRAP Stage I (Poor)"
    return "Below GRAP Stage I (CPCB AQI 200 or less)"


def band_index(aqi):
    if aqi <= 50:
        return 0
    if aqi <= 100:
        return 1
    if aqi <= 150:
        return 2
    if aqi <= 200:
        return 3
    return 4


def fallback_advice(aqi, health, lang):
    lines = list(FALLBACK["hi" if lang == "hi" else "en"][band_index(aqi)])
    if health.lower() not in ("normal", "general", "") and aqi > 100:
        lines.append("आपके लिए ख़तरा ज़्यादा है, और सावधान रहें." if lang == "hi"
                     else "You are at higher risk, so be extra careful.")
    return "\n".join(f"{i + 1}) {l}" for i, l in enumerate(lines))


def get_forecast(hourly, today):
    days = {}
    for t, v in zip(hourly.get("time", []), hourly.get("us_aqi", [])):
        if v is None:
            continue
        d = t[:10]
        days[d] = max(days.get(d, 0), int(v))
    return [{"date": d, "max_aqi": days[d]} for d in sorted(days) if d > today][:2]


def get_advice(city, aqi, pm25, pm10, cpcb, grap, role, health, tomorrow, lang):
    prompt = (
        "You are Saans Saathi, a health advisor in India.\n"
        f"City: {city}\nAQI now (US scale): {aqi}\nPM2.5: {pm25}\nPM10: {pm10}\n"
        f"Approximate Indian CPCB AQI: {cpcb}\nGRAP status: {grap}\n"
        f"Tomorrow's maximum AQI forecast (US scale): {tomorrow}\n"
        f"Person's work: {role}\nHealth condition: {health}\n\n"
        "Give exactly 5 short lines: 1) how long it is OK to stay outdoors today, "
        "2) which mask to wear, 3) when to stop and rest, "
        "4) one precaution for this health condition, "
        "5) what to prepare today based on tomorrow's forecast. "
        "Use only the numbers given above and do not invent medical facts. "
        "Keep the language very simple. " + LANG_RULE[lang]
    )
    try:
        r = bedrock.converse(
            modelId=MODEL_ID,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 400, "temperature": 0.3})
        return r["output"]["message"]["content"][0]["text"], "bedrock", None
    except Exception as e:
        err = str(e)[:300]
        print("Bedrock error:", err)
        return fallback_advice(aqi, health, lang), "fallback", err


def resp(code, body):
    return {"statusCode": code, "headers": HEADERS,
            "body": json.dumps(body, ensure_ascii=False)}



def tts_reply(p):
    """Female voice (Amazon Polly Kajal) for the website Listen button. Text parts are separated by '|'."""
    parts = [x.strip() for x in (p.get("text") or "").split("|") if x.strip()][:8]
    parts = [x[:220] for x in parts]
    if not parts or sum(len(x) for x in parts) > 700:
        return resp(400, {"error": "text missing or too long"})
    code = "hi-IN" if p.get("lang") == "hi" else "en-IN"
    ssml = ('<speak><prosody rate="88%">'
            + '<break time="450ms"/>'.join(escape(x) for x in parts)
            + "</prosody></speak>")
    try:
        r = polly.synthesize_speech(Text=ssml, TextType="ssml", OutputFormat="mp3",
                                    VoiceId="Kajal", Engine="neural", LanguageCode=code)
        audio = base64.b64encode(r["AudioStream"].read()).decode("ascii")
    except Exception as e:
        print("Polly error:", repr(e))
        return resp(502, {"error": "voice not available"})
    return resp(200, {"audio": audio, "mime": "audio/mpeg"})

def lambda_handler(event, context):
    p = (event or {}).get("queryStringParameters") or {}
    if p.get("tts"):
        return tts_reply(p)
    city_in = (p.get("city") or "Delhi").strip()[:60]
    role = (p.get("role") or "General").strip()[:60]
    health = (p.get("health") or "Normal").strip()[:60]
    lang = p.get("lang", "hinglish")
    if lang not in LANG_RULE:
        lang = "hinglish"

    exact = parse_coords(p)
    if exact:
        lat, lon = exact
        city = city_in
    else:
        geo = get_coordinates(city_in)
        if not geo:
            return resp(404, {"error": "City not found in India: " + city_in})
        lat, lon, city = geo

    url = ("https://air-quality-api.open-meteo.com/v1/air-quality"
           f"?latitude={lat}&longitude={lon}&current=us_aqi,pm2_5,pm10"
           "&hourly=us_aqi&forecast_days=3&timezone=Asia%2FKolkata")
    try:
        data = http_json(url)
    except Exception as e:
        print("Air quality error:", e)
        return resp(502, {"error": "Live air quality data is not available right now. Please try again."})
    cur = data.get("current") or {}
    if cur.get("us_aqi") is None:
        return resp(502, {"error": "Live air quality data is not available for this city right now."})

    aqi = int(cur["us_aqi"])
    pm25 = cur.get("pm2_5")
    pm10 = cur.get("pm10")
    cpcb = cpcb_aqi_approx(pm25, pm10)
    grap = get_grap_stage(cpcb)

    forecast = []
    try:
        forecast = get_forecast(data.get("hourly") or {}, (cur.get("time") or "")[:10])
    except Exception as e:
        print("Forecast error:", e)
    tomorrow = forecast[0]["max_aqi"] if forecast else None
    if tomorrow is None:
        trend = "unknown"
    elif tomorrow > aqi + 30:
        trend = "worse"
    elif tomorrow < aqi - 30:
        trend = "better"
    else:
        trend = "same"

    advice, source, err = get_advice(city, aqi, pm25, pm10, cpcb, grap, role, health, tomorrow, lang)

    check_id = str(uuid.uuid4())
    item = {"checkId": check_id, "timestamp": int(time.time()), "city": city,
            "role": role, "health": health, "aqi": aqi, "advice_source": source}
    if cpcb is not None:
        item["cpcb_aqi"] = cpcb
    saved = True
    try:
        table.put_item(Item=item)
    except Exception as e:
        print("DynamoDB error:", e)
        saved = False

    body = {
        "checkId": check_id, "city": city, "aqi": aqi, "pm25": pm25, "pm10": pm10,
        "cpcb_aqi_approx": cpcb, "grap_stage": grap,
        "grap_note": "Approximate: uses current hourly PM values. Official GRAP uses 24-hour average CPCB AQI.",
        "forecast": forecast, "tomorrow_max": tomorrow, "trend": trend,
        "role": role, "health": health,
        "advice": advice, "advice_source": source, "saved": saved,
    }
    if err:
        body["bedrock_error"] = err
    return resp(200, body)