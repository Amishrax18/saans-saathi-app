# Saans Saathi (सांस साथी)

**Air apps tell you a number. Saans Saathi tells you what to do.**

A Hindi and English air-quality advisory for people who work outdoors in India: delivery riders, street vendors, teachers and parents. Built solo, in one weekend, on AWS, for the WeMakeDevs x AWS Bharat Builds Tour, Event 02: Environmental Hacks, Air track.

| | |
|---|---|
| **Live site** | https://staging.d19gh0lcd3h85t.amplifyapp.com |
| **Demo video (3 min)** | https://youtu.be/9nSuVczXidE |
| **Telegram bot** | https://t.me/SaansSaathi_bot |

---

## The problem

A rider in Delhi opens an air app and sees "AQI 310". That is a number, not a decision. They still have to guess: is it safe to work today, for how long, which mask, and is there a better time of day?

People who work outdoors cannot stay home on a bad air day. They need a plain instruction, in their own language, at the moment they decide.

## What it does

- **City search.** Any Indian city with live autocomplete, or use your location.
- **Live readings.** AQI, PM2.5, PM10, approximate CPCB AQI and GRAP stage.
- **Advice by role and health profile.** Rider, vendor, teacher or parent, with or without a health condition. Output: how long it is safe to stay outside, which mask, the best time of day, and tomorrow's warning.
- **English and Hindi**, with a spoken female voice from Amazon Polly (neural, Kajal).
- **Telegram bot.** Send a city name or location, `/compare` two cities, get voice replies, subscribe to alerts and get a 7:30 AM morning update.
- **Hourly alerts that do not cry wolf.** A school email goes out only after two consecutive readings above US AQI 150, with a dust-spike guard.
- **School Mode.** A Step Functions workflow checks 104 cities and emails schools one summary. Impossible values (AQI above 500) are filtered out and listed separately.
- **Impact numbers** and a **Punjab and Haryana fire card** (NASA FIRMS satellite detections).
- The page itself reacts to the air: the worse the AQI, the more dust fills the screen.

## What is different

| Most air apps | Saans Saathi |
|---|---|
| Show an AQI number | Gives an instruction: how long, which mask, when to go |
| One generic message | Advice by role (rider, vendor, teacher, parent) and health profile |
| English only | Hindi and English, text and spoken voice |
| Need a new app | Works in a browser and in Telegram, which people already use |
| One bad reading triggers panic | Alerts need two readings in a row, and impossible values are filtered |
| Hide where the data is weak | Labels advice as "Rule-based" and states the data limits openly |

## Architecture

All services run in **ap-south-1 (Mumbai)**.

![Saans Saathi architecture](docs/architecture.png)

## AWS services used

| Service | What it does here |
|---|---|
| **Amplify Hosting** | Serves the single-page site |
| **API Gateway (HTTP API)** | `/check` for the site and the Telegram webhook |
| **Lambda (Python 3.12)** | Four functions: air check and advice, Telegram bot, hourly alerts, school summary |
| **DynamoDB** | Stores checks, alert state, Telegram profiles and feedback |
| **Amazon Polly** | Hindi and English voice |
| **EventBridge Scheduler** | Hourly check and the 7:30 AM morning update |
| **Amazon SNS** | School email alerts |
| **Step Functions (Map state)** | School Mode over 104 cities, with Redrive after a failure |
| **CloudWatch** | Logs and metrics |

Data sources: Open-Meteo (geocoding, air quality, forecast) and NASA FIRMS (fire detections).

## What fought back

1. **An AQI of 721.** The site showed Noida at 721, but the scale ends at 500 and PM2.5 was only 98. The model's combined AQI mixes in gases and was spiking. Fix: the AQI is now **computed from PM2.5 and PM10 on the US EPA scale**, with a median over neighbouring grid points, and "500+" with a warning if a reading is ever out of range.
2. **Alerts that cry wolf.** One bad data point should not email a school. An alert now needs two readings in a row, and impossible values are filtered. Step Functions filtered 8 impossible readings in its first 104-city run.
3. **Permissions.** The first Step Functions run failed with an authorization error because the summary Lambda could not publish to SNS. Redrive let me fix IAM and continue without starting over.
4. **Bedrock was blocked** on my account, so the advice is rule-based and clearly labelled. I did not want to claim AI I could not use.
5. **A forgotten old Lambda** kept sending false emergency emails from an earlier test. I found it, removed its trigger and deleted it.

## Honest notes

- Air data is a **model estimate** from Open-Meteo (about 11 km grid), not a ground station. It can differ from CPCB monitors, and small towns are approximate.
- Advice is **rule-based**. It is not medical advice and not a government order. GRAP stages are approximate.
- Amazon Bedrock was configured but blocked at account level, so the project does **not** claim AI advice.
- The fire card shows satellite fire detections, not the cause of today's AQI.
- Impact numbers include the builder's own test checks.

## Repo layout

```
frontend/                   single-file site (HTML, CSS, vanilla JS)
backend/saans-api/          air check, advice, voice, stats, fires
backend/saans-telegram/     Telegram bot
backend/saans-alert/        hourly and morning alerts
backend/saans-school-summary/  Step Functions summary step
stepfunctions/              the 104-city input
docs/                       architecture diagram
```

## Deploy

Each folder in `backend/` is one Lambda (Python 3.12). Telegram needs the environment variables `BOT_TOKEN` and `WEBHOOK_SECRET`. The fires route needs a free NASA FIRMS key. No secrets are stored in this repo. The site is uploaded to Amplify as a zip.

## What I learned

I started this weekend with no AWS experience. I learned how Lambda, API Gateway and DynamoDB fit together, why IAM roles matter, how Step Functions makes a long job visible, and that a number you cannot trust is worse than no number.

---

*Built by Arjun Mishra*
