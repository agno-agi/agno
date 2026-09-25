# Travel & Leisure Agent System

This project integrates multiple AI agents using **Agno** and **Google APIs** to create intelligent, map-aware travel itineraries.

## Features

* **Navigator Agent** → Provides routes, travel times, and transport options via Google Maps.
* **Attraction Finder** → Suggests top attractions, restaurants, and local experiences.
* **Itinerary Composer** → Combines all outputs into a balanced, day-by-day travel plan with realistic timings.

### Google Maps API Authentication Fix

Refer to the detailed guide in `docs/google_maps_auth_fix.md` (or this file) for resolving the `DefaultCredentialsError` by explicitly providing API key credentials to `places_v1.PlacesClient()`.

**Summary:**
Added API key–based authentication using

```python
credentials = api_key_credentials.Credentials(self.api_key)
self.places_client = places_v1.PlacesClient(credentials=credentials)
```

to replace the default ADC-based authentication.

### How to Get a Google Maps API Key

1. Go to **Google Cloud Console**
   [https://console.cloud.google.com/](https://developers.google.com/maps/documentation/javascript/get-api-key)

2. Click the project dropdown → **Create New Project**.

3. Open **APIs & Services → Library**.
   Enable the following APIs:

   * **Maps JavaScript API**
   * **Places API**
   * **Directions API**
   * **Geocoding API** (optional)

4. Open **APIs & Services → Credentials**.
   Click: **Create Credentials → API Key**

5. Copy the key and paste it in your `.env` file as:

   ```
   GOOGLE_MAPS_API_KEY=your_google_maps_key
   ```

6. (Recommended) Under **API Restrictions**, restrict usage only to Maps/Places APIs.

---

## Use

- To use Agno OS, go to os.agno.com and create an account
- In the UI, click on "Create your OS" and add your localhost endpoint
- All of your agents and teams will appear on the home page
- Access the agent at `http://localhost:7777`

---


## Setup

1. **Create and activate a virtual environment**

   ```bash
   python -m venv venv
   venv\Scripts\activate
   ```

2. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

3. **Set environment variables** in a `.env` file:

   ```
   GOOGLE_API_KEY=your_gemini_api_key
   GOOGLE_MAPS_API_KEY=your_google_maps_key
   ```

4. **Run the application**

   ```bash
   python agent.py
   ```

