import json

import boto3

REGION = "ap-south-1"
TOPIC_ARN = "arn:aws:sns:ap-south-1:856447616153:Saans-School-Alerts"
MAX_US_AQI = 500  # the US AQI scale ends at 500; anything above is bad data (dust spike / model glitch)
sns = boto3.client("sns", region_name=REGION)


def to_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def lambda_handler(event, context):
    """Gets the School Mode results of many cities from Step Functions and sends ONE summary alert."""
    results = (event or {}).get("results") or []
    with_aqi = [(r, to_int(r.get("aqi"))) for r in results if "aqi" in r]
    with_aqi = [(r, a) for r, a in with_aqi if a is not None]
    ok = [(r, a) for r, a in with_aqi if a <= MAX_US_AQI]
    suspect = [r.get("city") for r, a in with_aqi if a > MAX_US_AQI]
    failed = [r.get("city") for r in results if "aqi" not in r]

    alerts = sorted(((r, a) for r, a in ok if r.get("alert")), key=lambda x: -x[1])
    published = False
    if alerts:
        lines = [f"{r['city']}: AQI {a} - {r['decision']} / {r.get('decision_hi', '')}" for r, a in alerts]
        message = ("Saans Saathi School Mode: cities where air is unhealthy today "
                   f"({len(alerts)} of {len(ok)} checked)\n\n" + "\n".join(lines))
        if suspect:
            message += ("\n\nData looks wrong (AQI above 500, probably a dust spike or model error), so not used: "
                        + ", ".join(suspect))
        if failed:
            message += "\n\nNo live data for: " + ", ".join(failed)
        message += "\n\nAdvisory by Saans Saathi. This is not an official government order."
        sns.publish(TopicArn=TOPIC_ARN,
                    Subject=f"Saans Saathi School Mode: {len(alerts)} cities need action"[:95],
                    Message=message)
        published = True
    return {"checked": len(ok), "suspect_data": len(suspect), "no_data": len(failed),
            "alerting": len(alerts), "published": published}
