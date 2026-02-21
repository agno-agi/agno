-- <query name>championship_race_wins</query name>
-- <query description>
-- How many races did each championship winner win in their championship year?
-- Handles: position as TEXT in drivers_championship, date parsing in race_wins
-- </query description>
-- <query>
SELECT
    dc.year,
    dc.name AS champion_name,
    COUNT(rw.name) AS race_wins
FROM drivers_championship dc
JOIN race_wins rw
    ON dc.name = rw.name
    AND dc.year = EXTRACT(YEAR FROM TO_DATE(rw.date, 'DD Mon YYYY'))
WHERE dc.position = '1'  -- TEXT comparison for drivers_championship
GROUP BY dc.year, dc.name
ORDER BY dc.year DESC
LIMIT 50
-- </query>


-- <query name>constructor_wins_vs_position</query name>
-- <query description>
-- Compare constructor race wins vs championship position for a given year.
-- Handles: position as INTEGER in constructors_championship, date parsing in race_wins
-- </query description>
-- <query>
WITH race_wins_by_year AS (
    SELECT
        team,
        COUNT(*) AS wins
    FROM race_wins
    WHERE EXTRACT(YEAR FROM TO_DATE(date, 'DD Mon YYYY')) = 2019
    GROUP BY team
)
SELECT
    cc.position,
    cc.team,
    cc.points,
    COALESCE(rw.wins, 0) AS race_wins
FROM constructors_championship cc
LEFT JOIN race_wins_by_year rw ON cc.team = rw.team
WHERE cc.year = 2019
    AND cc.position <= 10  -- INTEGER comparison for constructors_championship
ORDER BY cc.position
-- </query>


-- <query name>driver_race_wins_all_time</query name>
-- <query description>
-- Most race wins by a driver (all time).
-- Simple aggregation on race_wins table.
-- </query description>
-- <query>
SELECT
    name AS driver,
    COUNT(*) AS total_wins
FROM race_wins
GROUP BY name
ORDER BY total_wins DESC
LIMIT 10
-- </query>


-- <query name>constructor_championships_all_time</query name>
-- <query description>
-- Which team won the most Constructors Championships?
-- Handles: position as INTEGER in constructors_championship
-- </query description>
-- <query>
SELECT
    team,
    COUNT(*) AS championship_wins
FROM constructors_championship
WHERE position = 1  -- INTEGER comparison
GROUP BY team
ORDER BY championship_wins DESC
LIMIT 10
-- </query>


-- <query name>driver_championships_all_time</query name>
-- <query description>
-- Which driver won the most World Championships?
-- Handles: position as TEXT in drivers_championship
-- </query description>
-- <query>
SELECT
    name AS driver,
    COUNT(*) AS championship_wins
FROM drivers_championship
WHERE position = '1'  -- TEXT comparison (note the quotes!)
GROUP BY name
ORDER BY championship_wins DESC
LIMIT 10
-- </query>


-- <query name>podium_finishes_by_driver</query name>
-- <query description>
-- Count podium finishes (1st, 2nd, 3rd) by driver.
-- Handles: position as TEXT in race_results with non-numeric values
-- </query description>
-- <query>
SELECT
    name AS driver,
    COUNT(*) AS podiums,
    SUM(CASE WHEN position = '1' THEN 1 ELSE 0 END) AS wins,
    SUM(CASE WHEN position = '2' THEN 1 ELSE 0 END) AS seconds,
    SUM(CASE WHEN position = '3' THEN 1 ELSE 0 END) AS thirds
FROM race_results
WHERE position IN ('1', '2', '3')  -- TEXT comparison
GROUP BY name
ORDER BY podiums DESC
LIMIT 10
-- </query>


-- <query name>retirements_by_year</query name>
-- <query description>
-- Count retirements per year.
-- Handles: non-numeric position values ('Ret') in race_results
-- </query description>
-- <query>
SELECT
    year,
    COUNT(*) AS retirements
FROM race_results
WHERE position = 'Ret'
GROUP BY year
ORDER BY year DESC
LIMIT 20
-- </query>


-- <query name>fastest_laps_at_venue</query name>
-- <query description>
-- Most fastest laps at a specific venue.
-- Uses fastest_laps table with driver_tag column.
-- </query description>
-- <query>
SELECT
    name AS driver,
    driver_tag,
    COUNT(*) AS fastest_lap_count
FROM fastest_laps
WHERE venue ILIKE '%Monaco%'
GROUP BY name, driver_tag
ORDER BY fastest_lap_count DESC
LIMIT 10
-- </query>


-- <query name>wins_by_venue</query name>
-- <query description>
-- Most wins at a specific venue.
-- Uses race_wins table with name_tag column (not driver_tag).
-- </query description>
-- <query>
SELECT
    name AS driver,
    name_tag,
    COUNT(*) AS wins
FROM race_wins
WHERE venue ILIKE '%Monaco%'
GROUP BY name, name_tag
ORDER BY wins DESC
LIMIT 10
-- </query>


-- <query name>team_points_comparison</query name>
-- <query description>
-- Compare two teams' championship points over a range of years.
-- </query description>
-- <query>
SELECT
    year,
    MAX(CASE WHEN team = 'Ferrari' THEN points END) AS ferrari_points,
    MAX(CASE WHEN team = 'Mercedes' THEN points END) AS mercedes_points
FROM constructors_championship
WHERE team IN ('Ferrari', 'Mercedes')
    AND year BETWEEN 2015 AND 2020
GROUP BY year
ORDER BY year
-- </query>


-- <query name>safe_position_filter</query name>
-- <query description>
-- Safely filter numeric positions from TEXT column.
-- Handles: mixed numeric and text values in race_results.position
-- </query description>
-- <query>
SELECT
    year,
    venue,
    name,
    position,
    points
FROM race_results
WHERE position ~ '^[0-9]+$'  -- Only numeric positions
    AND CAST(position AS INTEGER) <= 10  -- Safe to cast after regex check
    AND year = 2020
ORDER BY venue, CAST(position AS INTEGER)
LIMIT 50
-- </query>
