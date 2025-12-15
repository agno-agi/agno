# Multi-Agent A2A Trip Planner

Overview
- This directory contains three example agents: Weather, Airbnb, and a Trip Planner orchestrator that calls them via A2A.

Prerequisites
- Python 3.8+
- Install project dependencies (e.g., pip install -r requirements.txt) or your project's deps.
- Set any required API keys (OpenAI, OpenWeather) as environment variables if your setup expects them.

Run order (required)
1. Start the Weather Agent
   - File: weather_agent.py
   - Default port in file: 7770
   - Command:
     ```
     python weather_agent.py
     ```
2. Start the Airbnb Agent
   - File: airbnb_agent.py
   - Default port in file: 7774
   - Command:
     ```
     python airbnb_agent.py
     ```
3. Start the Trip Planner (orchestrator)
   - File: trip_planning_a2a_client.py
   - Default port in file: 7777
   - Command:
     ```
     python trip_planning_a2a_client.py
     ```
Notes on ports
- The trip planner runs on port 7777 and expects the Weather Agent at http://localhost:7770 and the Airbnb Agent at http://localhost:7774 (see WEATHER_URL and AIRBNB_URL in trip_planning_a2a_client.py).
- All agents run on separate ports, so no conflicts occur.
Testing the Trip Planner (example)
- Send an A2A JSON-RPC request to the Trip Planner service on port 7777 using the agent ID `trip_planner`.
- Example minimal payload (use curl or any HTTP client):
  ```
  curl -X POST http://localhost:7777/a2a/agents/trip_planner/v1/message:send \
    -H "Content-Type: application/json" \
    -d '{
      "id":"test",
      "jsonrpc":"2.0",
      "method":"message/send",
      "params":{"message":{"message_id":"abc-123","role":"user","parts":[{"text":"Plan a 3-day trip to Paris for 2 people next month."}]}}
    }'
  ```
Troubleshooting
- If you see connection errors, confirm each agent is running and the ports in trip_planning_a2a_client.py match the running services.
- Check console logs for the agent id used by each agent — A2A endpoints include the agent id path segment.
- If external API keys are required (OpenAI, OpenWeather), ensure they're configured correctly.
That's it — start Weather, then Airbnb, then Trip Planner; use the Trip Planner A2A endpoint to orchestrate requests.