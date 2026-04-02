# 🎯 Autodarts Pro Analytics Pipeline

A fully automated, self-healing ETL (Extract, Transform, Load) data pipeline and interactive analytics dashboard for Autodarts. 

This project silently listens to your local Autodarts Hub, invisibly intercepts pristine match statistics directly from the Autodarts network, stores every throw (including exact X/Y coordinates) in a local SQLite database, and serves up a professional-grade interactive dashboard using Streamlit and Plotly.

## ✨ Features
* **Zero-Touch Automation:** Integrates directly into Darts-Hub as a Custom Profile. One click starts the caller, the data scraper, and the dashboard simultaneously.
* **Self-Healing Data Extraction:** No more expired API Bearer tokens. Uses Playwright to invisibly log into your account in the background and sniff the match JSON directly from the network traffic.
* **The "Pristine" Data Vault:** Parses the complex Autodarts JSON into a robust relational SQLite database (`schema.sql`), capturing match stats, leg stats, turns, and individual throw coordinates.
* **Interactive Dashboard:** A local web app built with Streamlit and Plotly featuring:
  * Accuracy Heatmaps based on actual dart X/Y coordinates.
  * Performance progression over time (3-Dart Avg, First 9 Avg, Checkout %).
  * Fatigue tracking (Average vs. Match Duration trendlines).
  * Breakdown of average pace per dart (Dart 1 vs Dart 2 vs Dart 3).
  * Contextual analysis (Averages when starting a leg vs. going second).

---

## 🛠️ Prerequisites
* **Python 3.8+** installed on your system.
* **Autodarts Hub** installed and running locally.
* An active Autodarts account.

---

## 🚀 Installation & Setup

**1. Install Dependencies**
Open your terminal in the project folder and install the required Python libraries:
```bash
pip install -r requirements.txt
```

**2. Install the Invisible Browser Engine**
Playwright requires a headless Chromium browser to intercept the data. Run this command once:
```bash
python -m playwright install chromium
```

**3. Configure your Credentials**
Create or edit the `config.json` file in the root directory. Add your Autodarts login credentials so the invisible browser can fetch your match history.
> ⚠️ **SECURITY WARNING:** Never upload `config.json` to a public GitHub repository! 

```json
{
  "websocket": "ws://localhost:8079/socket.io/?EIO=4&transport=websocket",
  "autodarts_email": "YOUR_EMAIL@example.com",
  "autodarts_password": "YOUR_PASSWORD"
}
```
*(Note: If you use the secure local websocket, change `ws://` to `wss://`)*

---

## 🎮 Running the Application (Darts-Hub Integration)

The best way to run this pipeline is by plugging it directly into the native **Darts-Hub** app using the included `launcher.bat` file.

1. Open **Darts-Hub**.
2. Select an empty **Custom Profile** slot on the left menu (e.g., `custom-1`).
3. Change the **Display Name** to `Autodarts Analytics` (or similar).
4. **Check the box** for *"Start this application when the profile is launched"*.
5. For **path-to-executable**, click **Browse** and select the `launcher.bat` file from this project folder.
6. Leave **arguments** completely empty.

Now, whenever you click **Start** on this profile, the backend pipeline will boot up silently in the background, and your web browser will automatically open to your local Analytics Dashboard! When you stop the profile, everything shuts down cleanly without leaving phantom processes in your RAM.

---

## 📁 Project Structure

* `dartstats.py`: The core pipeline. Connects to the local WebSocket, listens for `match-won`/`match-ended` events, and fires the Playwright network interceptor.
* `database.py`: The data transformer. Takes the raw intercepted JSON and safely maps it into the relational SQLite database.
* `schema.sql`: The database architecture. Contains the definitions for Matches, Legs, Turns, Throws, and Stat tables.
* `dashboard.py`: The Streamlit frontend. Queries the SQLite database to generate the interactive Plotly graphs and UI.
* `launcher.bat`: The master execution script. Runs the python background task and the Streamlit server simultaneously, designed specifically for Darts-Hub integration.
* `requirements.txt`: The list of required Python libraries for easy installation.

---

## 🧠 How it Works Under the Hood
Autodarts does not provide a public API key system. To get around this without requiring daily manual Bearer token updates, this script uses **Playwright**. 

When a match ends, the WebSocket alerts the script. Playwright then spawns a headless (invisible) Chrome browser, logs into `play.autodarts.io`, navigates to the specific match history page, and deploys a "dragnet wiretap" on its own network traffic. It catches the pristine `.json` payload as the Autodarts server sends it to the browser, saves it straight to RAM, pipes it into SQLite, and destroys the browser instance in seconds.

***

### Next Steps for You:
Save this text as **`README.md`** in your project folder. 

If you ever decide to upload this to GitHub, make sure you also create a file named `.gitignore` and put `config.json` and `dartstats.db` inside it, so you don't accidentally share your passwords and personal match database with the internet! 

You have built an incredible piece of software here. Go throw some darts and watch that heatmap light up!