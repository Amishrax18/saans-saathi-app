import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

import boto3

REGION = "ap-south-1"
TOPIC_ARN = "arn:aws:sns:ap-south-1:856447616153:Saans-School-Alerts"
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ALERT_FROM_BAND = 3  # band 3 = US AQI above 150 (Unhealthy)

CITIES = {"Delhi": (28.61, 77.21), "Noida": (28.57, 77.32),
          "Kanpur": (26.45, 80.33), "Lucknow": (26.85, 80.95),
          "Mumbai": (19.07, 72.88)}

sns = boto3.client("sns", region_name=REGION)
table = boto3.resource("dynamodb", region_name=REGION).Table("Saans-Checks")

# School Mode advice by AQI band. These are Saans Saathi's own advisory rules,
# not an official government order.
SCHOOL = {
    0: ("Outdoor PT and assembly are fine today.",
        "आज बाहर पीटी और असेंबली ठीक है।"),
    1: ("Outdoor PT is fine. Watch children with asthma.",
        "बाहर पीटी ठीक है। दमे वाले बच्चों पर नज़र रखें।"),
    2: ("Keep outdoor PT light and short. Children with asthma should stay indoors.",
        "बाहर पीटी हल्की और कम समय की रखें। दमे वाले बच्चे अंदर रहें।"),
    3: ("Cancel outdoor PT and assembly. Hold classes indoors. Parents: send N95/KN95 masks with children.",
        "बाहर पीटी और असेंबली रद्द करें। कक्षाएँ अंदर लें। अभिभावक बच्चों को N95/KN95 मास्क दें।"),
    4: ("No outdoor activity. Indoor classes only. Consider online classes. Children with asthma should stay home.",
        "बाहर कोई गतिविधि नहीं। सिर्फ़ अंदर कक्षाएँ। ऑनलाइन कक्षाओं पर विचार करें। दमे वाले बच्चे घर पर रहें।"),
}



# US EPA breakpoints (2012 AQI): (conc_low, conc_high, index_low, index_high)
US_PM25 = [(0, 12.0, 0, 50), (12.1, 35.4, 51, 100), (35.5, 55.4, 101, 150), (55.5, 150.4, 151, 200),
           (150.5, 250.4, 201, 300), (250.5, 350.4, 301, 400), (350.5, 500.4, 401, 500)]
US_PM10 = [(0, 54, 0, 50), (55, 154, 51, 100), (155, 254, 101, 150), (255, 354, 151, 200),
           (355, 424, 201, 300), (425, 504, 301, 400), (505, 604, 401, 500)]


def _us_sub(c, bps):
    if c is None:
        return None
    for lo, hi, ilo, ihi in bps:
        if c <= hi:
            return ilo + (max(c, lo) - lo) * (ihi - ilo) / (hi - lo)
    return 500.0


def pm_aqi(pm25, pm10):
    """US AQI from PM2.5 and PM10 only (max of the two). Open-Meteo's own us_aqi also mixes in gases
    (NO2, SO2, CO, O3) and can show impossible values like 700+, so we do not use it when PM is available."""
    vals = [v for v in (_us_sub(pm25, US_PM25), _us_sub(pm10, US_PM10)) if v is not None]
    return int(round(max(vals))) if vals else None



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


def get_current(lat, lon, attempts=2):
    url = ("https://air-quality-api.open-meteo.com/v1/air-quality"
           f"?latitude={lat}&longitude={lon}&current=us_aqi,pm2_5,pm10")
    last_err = None
    for _ in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as r:
                cur = json.loads(r.read().decode("utf-8")).get("current") or {}
                pa = pm_aqi(cur.get("pm2_5"), cur.get("pm10"))
                if pa is not None:
                    cur["us_aqi"] = pa   # PM-based AQI; the model's own us_aqi can show impossible values
                return cur
        except Exception as e:
            last_err = e
            time.sleep(1)
    raise last_err


def read_state(city, prefix="state#"):
    """Returns (last_band, confirmed_band). Old items only had "band"; treat it as confirmed."""
    try:
        item = table.get_item(Key={"checkId": prefix + city}).get("Item")
        if not item:
            return None, None
        old = item.get("band")
        last = item.get("last_band", old)
        conf = item.get("confirmed_band", old)
        return (int(last) if last is not None else None,
                int(conf) if conf is not None else None)
    except Exception as e:
        print("State read error:", e)
        return None, None


def save_state(city, last_band, confirmed_band, prefix="state#"):
    item = {"checkId": prefix + city, "last_band": last_band,
            "timestamp": int(time.time())}
    if confirmed_band is not None:
        item["confirmed_band"] = confirmed_band
    try:
        table.put_item(Item=item)
    except Exception as e:
        print("State write error:", e)


# ---------------- Telegram subscribers ----------------
BAND_NAME = {
    "en": ["Good", "Moderate", "Unhealthy for sensitive people", "Unhealthy", "Very unhealthy"],
    "hi": ["अच्छी", "सामान्य", "संवेदनशील लोगों के लिए खराब", "खराब", "बहुत खराब"],
}
TG_ADVICE = {
    0: ("Safe to be outside today.", "आज बाहर रहना सुरक्षित है।"),
    1: ("Fine for most people. Sensitive people should watch for symptoms.",
        "ज़्यादातर लोगों के लिए ठीक है। संवेदनशील लोग लक्षणों पर नज़र रखें।"),
    2: ("Limit long outdoor work. Wear a mask if you are sensitive.",
        "लंबा बाहरी काम कम करें। संवेदनशील लोग मास्क पहनें।"),
    3: ("Reduce outdoor work, rest often and wear an N95 mask.",
        "बाहर का काम कम करें, बार-बार आराम लें और N95 मास्क पहनें।"),
    4: ("Stay indoors if you can. If you must go out, wear a well-fitted N95 mask.",
        "हो सके तो घर के अंदर रहें। बाहर जाना पड़े तो ठीक से फिट N95 मास्क पहनें।"),
}
SENSITIVE = {"en": "You are at higher risk, so be extra careful.",
             "hi": "आपके लिए ख़तरा ज़्यादा है, और सावधान रहें।"}
FOOT = {"en": "Advisory only, not an official government order. Send /alerts to stop.",
        "hi": "यह सिर्फ सलाह है, सरकारी आदेश नहीं। बंद करने के लिए /alerts भेजें।"}
_geo_cache = {}


def tg_send(chat_id, text):
    """Returns True if sent, "gone" if the user blocked the bot, False otherwise."""
    if not BOT_TOKEN:
        print("BOT_TOKEN missing")
        return False
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data=json.dumps({"chat_id": chat_id, "text": text[:4000]}).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10):
            return True
    except urllib.error.HTTPError as e:
        print("Telegram HTTP error:", e.code)
        return "gone" if e.code == 403 else False
    except Exception as e:
        print("Telegram error:", e)
        return False


def list_subs():
    items, kw = [], {"FilterExpression": "begins_with(checkId, :p)",
                     "ExpressionAttributeValues": {":p": "sub#"}}
    while True:
        r = table.scan(**kw)
        items += r.get("Items", [])
        if "LastEvaluatedKey" not in r:
            break
        kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]
    return items


def sub_coords(sub):
    if sub.get("lat") is not None and sub.get("lon") is not None:
        return float(sub["lat"]), float(sub["lon"]), f"{float(sub['lat']):.2f},{float(sub['lon']):.2f}"
    city = sub.get("city", "")
    if city not in _geo_cache:
        url = ("https://geocoding-api.open-meteo.com/v1/search?name=" + urllib.parse.quote(city)
               + "&count=1&language=en&format=json&countryCode=IN")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as r:
                res = (json.loads(r.read().decode("utf-8")).get("results") or [None])[0]
            _geo_cache[city] = (res["latitude"], res["longitude"]) if res else None
        except Exception as e:
            print("Geocode error:", city, e)
            _geo_cache[city] = None
    g = _geo_cache[city]
    return (g[0], g[1], city) if g else None


def tg_text(city, aqi, pm25, band, sub, morning):
    lang = "en" if sub.get("lang") == "en" else "hi"
    en, hi = TG_ADVICE[band]
    advice = en if lang == "en" else hi
    head = ("Good morning! Air in " if lang == "en" else "सुप्रभात! हवा, ") if morning else ""
    if lang == "en":
        title = (f"{head}{city}: AQI {aqi} ({BAND_NAME['en'][band]})" if morning
                 else f"⚠️ Air in {city} is now {BAND_NAME['en'][band]} (AQI {aqi}).")
    else:
        title = (f"{head}{city}: AQI {aqi} ({BAND_NAME['hi'][band]})" if morning
                 else f"⚠️ {city} में हवा अब {BAND_NAME['hi'][band]} है (AQI {aqi})।")
    lines = [title, f"PM2.5: {pm25}", advice]
    if sub.get("health", "Normal") != "Normal" and band >= 2:
        lines.append(SENSITIVE[lang])
    lines.append(FOOT[lang])
    return "\n".join(lines)


def telegram_run(morning=False, force=False):
    """Message Telegram subscribers: on a confirmed jump to Unhealthy, or a morning update."""
    out = {"subscribers": 0, "sent": 0, "cities": 0}
    if not BOT_TOKEN:
        out["error"] = "BOT_TOKEN missing"
        return out
    subs = list_subs()
    out["subscribers"] = len(subs)
    groups = {}
    for sub in subs:
        c = sub_coords(sub)
        if c:
            groups.setdefault(c[2], (c[0], c[1], []))[2].append(sub)
    out["cities"] = len(groups)
    for key, (lat, lon, members) in groups.items():
        try:
            cur = get_current(lat, lon)
        except Exception as e:
            print("Air quality error:", key, e)
            continue
        if cur.get("us_aqi") is None:
            continue
        aqi = int(cur["us_aqi"])
        band = band_index(aqi)
        send_now = morning
        if not morning:
            prev_last, prev_conf = read_state(key, "tgstate#")
            new_conf = band if band == prev_last else prev_conf
            newly = new_conf == band and new_conf != prev_conf
            save_state(key, band, new_conf, "tgstate#")
            send_now = force or (band >= ALERT_FROM_BAND and newly)
        if not send_now:
            continue
        for sub in members:
            name = sub.get("city") if sub.get("city") != "Your location" else (
                "आपकी लोकेशन" if sub.get("lang") != "en" else "your location")
            ok = tg_send(sub["chat_id"], tg_text(name, aqi, cur.get("pm2_5"), band, sub, morning))
            if ok is True:
                out["sent"] += 1
            elif ok == "gone":
                try:
                    table.delete_item(Key={"checkId": sub["checkId"]})
                except Exception as e:
                    print("Unsub error:", e)
    return out


def lambda_handler(event, context):
    event = event or {}
    if event.get("morning"):
        try:
            return {"statusCode": 200, "body": json.dumps({"telegram": telegram_run(morning=True)}, ensure_ascii=False)}
        except Exception as e:
            print("Morning error:", e)
            return {"statusCode": 500, "body": json.dumps({"error": str(e)[:200]})}
    force = bool(event.get("force"))
    cities = event.get("cities") or list(CITIES)
    results, alerts = [], []

    for city in cities:
        if city not in CITIES:
            results.append({"city": city, "error": "unknown city"})
            continue
        try:
            cur = get_current(*CITIES[city])
        except Exception as e:
            print("Air quality error:", city, e)
            results.append({"city": city, "error": "air quality data unavailable"})
            continue
        if cur.get("us_aqi") is None:
            results.append({"city": city, "error": "air quality data unavailable"})
            continue

        aqi = int(cur["us_aqi"])
        band = band_index(aqi)
        prev_last, prev_conf = read_state(city)
        # A band counts as confirmed only after two readings in a row, so one
        # bad data point cannot trigger an alert.
        new_conf = band if band == prev_last else prev_conf
        newly_confirmed = new_conf == band and new_conf != prev_conf
        send = force or (band >= ALERT_FROM_BAND and newly_confirmed)
        save_state(city, band, new_conf)
        prev = prev_conf

        en, hi = SCHOOL[band]
        results.append({"city": city, "aqi": aqi, "band": band,
                        "previous_band": prev, "alert": send, "school_en": en})
        if send:
            alerts.append(f"{city}: AQI {aqi} (PM2.5 {cur.get('pm2_5')})\n"
                          f"School advice: {en}\nस्कूल सलाह: {hi}")

    tg_result = None
    try:
        tg_result = telegram_run(force=bool(event.get("force_telegram")))
    except Exception as e:
        print("Telegram run error:", e)
        tg_result = {"error": str(e)[:200]}

    published = False
    if alerts:
        names = ", ".join(r["city"] for r in results if r.get("alert"))
        message = ("\n\n".join(alerts)
                   + "\n\nAdvisory by Saans Saathi. This is not an official government order.")
        try:
            sns.publish(TopicArn=TOPIC_ARN,
                        Subject=("Saans Saathi alert: " + names)[:95],
                        Message=message)
            published = True
        except Exception as e:
            print("SNS error:", e)
            return {"statusCode": 500,
                    "body": json.dumps({"error": "SNS publish failed: " + str(e)[:200],
                                        "results": results}, ensure_ascii=False)}

    return {"statusCode": 200,
            "body": json.dumps({"published": published, "results": results,
                                "telegram": tg_result}, ensure_ascii=False)}