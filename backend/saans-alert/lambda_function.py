import json
import time
import urllib.request

import boto3

REGION = "ap-south-1"
TOPIC_ARN =  "arn:aws:sns:ap-south-1:856447616153:Saans-School-Alerts"
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


def get_current(lat, lon, tries=3):
    """Fetch current air quality. Retries on timeouts / SSL errors."""
    url = ("https://air-quality-api.open-meteo.com/v1/air-quality"
           f"?latitude={lat}&longitude={lon}&current=us_aqi,pm2_5,pm10")
    last_err = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=6) as r:
                return json.loads(r.read().decode("utf-8")).get("current") or {}
        except Exception as e:
            last_err = e
            print("Air quality retry", attempt + 1, e)
            time.sleep(1.5 * (attempt + 1))
    raise last_err


def read_state(city):
    """Returns (last_reading_band, confirmed_band). Old items only had 'band' = confirmed."""
    try:
        item = table.get_item(Key={"checkId": "state#" + city}).get("Item")
    except Exception as e:
        print("State read error:", e)
        return None, None
    if not item:
        return None, None
    confirmed = item.get("confirmed", item.get("band"))
    reading = item.get("reading")
    return (int(reading) if reading is not None else None,
            int(confirmed) if confirmed is not None else None)


def write_state(city, reading, confirmed):
    try:
        item = {"checkId": "state#" + city, "reading": reading,
                "timestamp": int(time.time())}
        if confirmed is not None:
            item["confirmed"] = confirmed
        table.put_item(Item=item)
    except Exception as e:
        print("State write error:", e)


def lambda_handler(event, context):
    event = event or {}
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

        # Very high PM10 with moderate PM2.5 is usually a dust spike or bad model data
        # (we saw Noida at AQI ~490 this way). Do not alert on it and do not store it.
        pm25, pm10 = cur.get("pm2_5"), cur.get("pm10")
        if pm10 is not None and pm10 > 600 and (pm25 is None or pm25 < 250):
            results.append({"city": city, "aqi": aqi, "pm10": pm10, "pm2_5": pm25,
                            "alert": False, "suspect_data": True})
            continue
        prev_reading, prev_confirmed = read_state(city)

        # A band counts as real only when two hourly checks in a row agree.
        # This stops one-off glitches (like a single AQI 498) from sending alerts.
        confirmed = prev_confirmed
        if prev_reading is not None and band == prev_reading:
            confirmed = band
        changed = confirmed != prev_confirmed
        send = force or (changed and confirmed is not None and confirmed >= ALERT_FROM_BAND)
        write_state(city, band, confirmed)

        en, hi = SCHOOL[band]
        results.append({"city": city, "aqi": aqi, "band": band,
                        "previous_reading": prev_reading,
                        "confirmed_band": confirmed, "alert": send, "school_en": en})
        if send:
            alerts.append(f"{city}: AQI {aqi} (PM2.5 {cur.get('pm2_5')})\n"
                          f"School advice: {en}\nस्कूल सलाह: {hi}")

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
            "body": json.dumps({"published": published, "results": results}, ensure_ascii=False)}