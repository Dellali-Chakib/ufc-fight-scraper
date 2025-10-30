# 🥊 UFC Fight Scraper

### 📘 Overview
**UFC Fight Scraper** is a Python-based asynchronous web scraper that collects **fighter statistics from [UFCStats.com](http://ufcstats.com)**.  
It compiles detailed information — such as striking accuracy, takedown defense, reach, stance, and recent fight history — for **every active and historical UFC fighter**, exporting all cleaned data into a structured CSV dataset.

The project was built to power **data-driven analytics and predictive modeling** for UFC fights (Phase 2 goal: building a machine learning model to predict fight outcomes).

---

## ⚙️ Features
- 🔄 **Fully Asynchronous (aiohttp + asyncio)** — fetches hundreds of fighter profiles concurrently  
- 🧹 **Data Cleaning & Standardization** — normalizes stats, converts units, percentages, and dates  
- 🧠 **Object-Oriented Design** — each fighter represented as a `Fighter` object with methods for conversion, validation, and classification  
- ⚖️ **Automatic Weight Class Categorization** — groups fighters by UFC divisions  
- 🚫 **Bad Sample Filtering** — excludes fighters with <3 UFC fights for better ML dataset quality  
- 📊 **CSV Output** — creates a clean `output.csv` with structured, analysis-ready fighter data  

---

## 🧩 Project Structure
ufc-fight-scraper/
│
├── stat_scraper.py # Main entry point; orchestrates full scraping pipeline
├── fighter_model.py # Fighter class for data transformation and validation
├── fighter_stats.py # Scrapes individual fighter stats (height, reach, record, etc.)
├── get_fighter_urls.py # Gathers all fighter profile URLs from UFCStats
├── clean_data.py # Cleans and normalizes raw scraped data
├── filter_data.py # Filters out incomplete or low-quality data
├── fighters_to_csv.py # Writes cleaned data to CSV (also integrated in main)
└── output.csv # Generated dataset (after running stat_scraper.py)

markdown
Copy code

---

## 🧠 How It Works
1. **Collect URLs**  
   `get_fighter_urls.py` asynchronously visits each letter (A–Z) page on UFCStats and extracts every fighter’s profile URL.

2. **Scrape Stats**  
   For each fighter page, `fighter_stats.py` collects detailed statistics: striking rates, takedown averages, stance, reach, record, DOB, etc.

3. **Clean & Structure**  
   `clean_data.py` sanitizes keys, trims whitespace, and removes non-alphabetic noise from dictionary keys.

4. **Instantiate Fighters**  
   Each cleaned record becomes a `Fighter` object (see `fighter_model.py`), automatically:
   - Converts height/weight to numeric values  
   - Converts percentages and dates  
   - Determines weight class  
   - Flags fighters with insufficient UFC experience

5. **Filter & Export**  
   Only valid fighters are exported to `output.csv` for machine learning or analytics.

---

## 🖥️ Installation

### 1️⃣ Clone the Repository
```bash
git clone https://github.com/Dellali-Chakib/ufc-fight-scraper.git
cd ufc-fight-scraper
2️⃣ Create and Activate a Virtual Environment
bash
Copy code
python -m venv venv
source venv/bin/activate   # macOS/Linux
venv\Scripts\activate      # Windows
3️⃣ Install Dependencies
bash
Copy code
pip install aiohttp beautifulsoup4 requests
🚀 Usage
Run the main scraper script:

bash
Copy code
python stat_scraper.py
This will:

Crawl all UFC fighter pages

Clean, filter, and process stats

Output output.csv in the project directory

🕒 Full scrape may take several minutes depending on connection speed and UFCStats server response.

📊 Example Output (CSV)
| Name | Height | Weight | Reach | Stance | SLpm | StrAcc | TDDef | Record | Weight Class | FightsInUFC | BadSample |
|------|---------|--------|--------|--------|-------|---------|--------|---------|---------------|-------------|
| Israel Adesanya | 76 | 185 | 80 | Switch | 4.02 | 0.48 | 0.76 | 24-5-0 | Middleweight | 15 | False |

🧭 Future Plans
🧠 Phase 2: Integrate with a predictive ML model (scikit-learn / PyTorch) for fight outcome prediction

📈 Add visualizations (strike accuracy trends, reach vs. win rate)

💾 Build a small API endpoint to serve fight stats dynamically

🕸️ Expand scraper to historical event data and fight-level stats

👨‍💻 Author
Yahia Chakib Dellali
Sophomore Computer Engineering @ UW–Madison
Building full-stack and data-driven sports analytics projects for portfolio and research.

📎 GitHub: Dellali-Chakib
