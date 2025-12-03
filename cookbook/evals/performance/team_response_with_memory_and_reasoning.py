import asyncio
import random
import uuid

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.eval.performance import PerformanceEval
from agno.models.openai import OpenAIResponses
from agno.team.team import Team
from agno.tools.reasoning import ReasoningTools

users = [
    "abel@example.com",
    "ben@example.com",
    "charlie@example.com",
    "dave@example.com",
    "edward@example.com",
]

cities = [
    "New York",
    "Los Angeles",
    "Chicago",
    "Houston",
    "Miami",
    "San Francisco",
    "Seattle",
    "Boston",
    "Washington D.C.",
    "Atlanta",
    "Denver",
    "Las Vegas",
]


# Setup the database
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)


def get_weather(city: str) -> str:
    """Get detailed weather information for a city."""
    weather_conditions = {
        "New York": {
            "current": "Partly cloudy with scattered showers",
            "temperature": "72°F (22°C)",
            "humidity": "65%",
            "wind": "12 mph from the northwest",
            "visibility": "10 miles",
            "pressure": "30.15 inches",
            "uv_index": "Moderate (5)",
            "sunrise": "6:45 AM",
            "sunset": "7:30 PM",
            "forecast": {
                "today": "High 75°F, Low 58°F with afternoon thunderstorms",
                "tomorrow": "High 78°F, Low 62°F, mostly sunny",
                "weekend": "High 82°F, Low 65°F, clear skies",
            },
            "air_quality": "Good (AQI: 45)",
            "pollen_count": "Moderate",
            "marine_conditions": "Waves 2-3 feet, water temperature 68°F",
        },
        "Los Angeles": {
            "current": "Sunny and clear",
            "temperature": "85°F (29°C)",
            "humidity": "45%",
            "wind": "8 mph from the west",
            "visibility": "15 miles",
            "pressure": "30.05 inches",
            "uv_index": "Very High (9)",
            "sunrise": "6:30 AM",
            "sunset": "7:45 PM",
            "forecast": {
                "today": "High 88°F, Low 65°F, sunny throughout",
                "tomorrow": "High 86°F, Low 63°F, morning fog then sunny",
                "weekend": "High 90°F, Low 68°F, clear and warm",
            },
            "air_quality": "Moderate (AQI: 78)",
            "pollen_count": "High",
            "marine_conditions": "Waves 3-4 feet, water temperature 72°F",
        },
        "Chicago": {
            "current": "Overcast with light drizzle",
            "temperature": "58°F (14°C)",
            "humidity": "78%",
            "wind": "18 mph from the northeast",
            "visibility": "6 miles",
            "pressure": "29.85 inches",
            "uv_index": "Low (2)",
            "sunrise": "7:15 AM",
            "sunset": "6:45 PM",
            "forecast": {
                "today": "High 62°F, Low 48°F, rain likely",
                "tomorrow": "High 65°F, Low 52°F, partly cloudy",
                "weekend": "High 70°F, Low 55°F, sunny intervals",
            },
            "air_quality": "Good (AQI: 52)",
            "pollen_count": "Low",
            "marine_conditions": "Waves 4-6 feet, water temperature 55°F",
        },
        "Houston": {
            "current": "Hot and humid with scattered clouds",
            "temperature": "92°F (33°C)",
            "humidity": "75%",
            "wind": "10 mph from the southeast",
            "visibility": "8 miles",
            "pressure": "30.10 inches",
            "uv_index": "Extreme (11)",
            "sunrise": "6:45 AM",
            "sunset": "8:00 PM",
            "forecast": {
                "today": "High 94°F, Low 76°F, chance of afternoon storms",
                "tomorrow": "High 96°F, Low 78°F, hot and humid",
                "weekend": "High 98°F, Low 80°F, isolated thunderstorms",
            },
            "air_quality": "Moderate (AQI: 85)",
            "pollen_count": "Very High",
            "marine_conditions": "Waves 1-2 feet, water temperature 82°F",
        },
        "Miami": {
            "current": "Partly cloudy with high humidity",
            "temperature": "88°F (31°C)",
            "humidity": "82%",
            "wind": "15 mph from the east",
            "visibility": "12 miles",
            "pressure": "30.20 inches",
            "uv_index": "Very High (10)",
            "sunrise": "6:30 AM",
            "sunset": "8:15 PM",
            "forecast": {
                "today": "High 90°F, Low 78°F, afternoon showers likely",
                "tomorrow": "High 89°F, Low 77°F, partly sunny",
                "weekend": "High 92°F, Low 79°F, scattered thunderstorms",
            },
            "air_quality": "Good (AQI: 48)",
            "pollen_count": "Moderate",
            "marine_conditions": "Waves 2-3 feet, water temperature 85°F",
        },
        "San Francisco": {
            "current": "Foggy and cool",
            "temperature": "62°F (17°C)",
            "humidity": "85%",
            "wind": "20 mph from the west",
            "visibility": "3 miles",
            "pressure": "30.00 inches",
            "uv_index": "Low (3)",
            "sunrise": "6:45 AM",
            "sunset": "7:30 PM",
            "forecast": {
                "today": "High 65°F, Low 55°F, fog clearing by afternoon",
                "tomorrow": "High 68°F, Low 58°F, partly cloudy",
                "weekend": "High 72°F, Low 60°F, sunny and mild",
            },
            "air_quality": "Good (AQI: 42)",
            "pollen_count": "Low",
            "marine_conditions": "Waves 5-7 feet, water temperature 58°F",
        },
        "Seattle": {
            "current": "Light rain with overcast skies",
            "temperature": "55°F (13°C)",
            "humidity": "88%",
            "wind": "12 mph from the southwest",
            "visibility": "4 miles",
            "pressure": "29.95 inches",
            "uv_index": "Low (1)",
            "sunrise": "7:00 AM",
            "sunset": "6:30 PM",
            "forecast": {
                "today": "High 58°F, Low 48°F, rain throughout the day",
                "tomorrow": "High 62°F, Low 50°F, showers likely",
                "weekend": "High 65°F, Low 52°F, partly cloudy",
            },
            "air_quality": "Good (AQI: 38)",
            "pollen_count": "Low",
            "marine_conditions": "Waves 3-5 feet, water temperature 52°F",
        },
        "Boston": {
            "current": "Clear and crisp",
            "temperature": "68°F (20°C)",
            "humidity": "55%",
            "wind": "14 mph from the northwest",
            "visibility": "12 miles",
            "pressure": "30.25 inches",
            "uv_index": "Moderate (6)",
            "sunrise": "6:30 AM",
            "sunset": "7:15 PM",
            "forecast": {
                "today": "High 72°F, Low 58°F, sunny and pleasant",
                "tomorrow": "High 75°F, Low 62°F, mostly sunny",
                "weekend": "High 78°F, Low 65°F, clear skies",
            },
            "air_quality": "Good (AQI: 55)",
            "pollen_count": "Moderate",
            "marine_conditions": "Waves 2-4 feet, water temperature 62°F",
        },
        "Washington D.C.": {
            "current": "Partly sunny with mild temperatures",
            "temperature": "75°F (24°C)",
            "humidity": "60%",
            "wind": "10 mph from the west",
            "visibility": "10 miles",
            "pressure": "30.15 inches",
            "uv_index": "High (7)",
            "sunrise": "6:45 AM",
            "sunset": "7:30 PM",
            "forecast": {
                "today": "High 78°F, Low 62°F, partly cloudy",
                "tomorrow": "High 80°F, Low 65°F, sunny intervals",
                "weekend": "High 82°F, Low 68°F, clear and warm",
            },
            "air_quality": "Moderate (AQI: 72)",
            "pollen_count": "High",
            "marine_conditions": "Waves 1-2 feet, water temperature 70°F",
        },
        "Atlanta": {
            "current": "Warm and humid with scattered clouds",
            "temperature": "82°F (28°C)",
            "humidity": "70%",
            "wind": "8 mph from the south",
            "visibility": "9 miles",
            "pressure": "30.05 inches",
            "uv_index": "High (8)",
            "sunrise": "6:30 AM",
            "sunset": "8:00 PM",
            "forecast": {
                "today": "High 85°F, Low 68°F, chance of afternoon storms",
                "tomorrow": "High 87°F, Low 70°F, hot and humid",
                "weekend": "High 90°F, Low 72°F, isolated thunderstorms",
            },
            "air_quality": "Moderate (AQI: 68)",
            "pollen_count": "Very High",
            "marine_conditions": "Waves 1-2 feet, water temperature 75°F",
        },
        "Denver": {
            "current": "Sunny and dry",
            "temperature": "78°F (26°C)",
            "humidity": "25%",
            "wind": "15 mph from the west",
            "visibility": "20 miles",
            "pressure": "24.85 inches",
            "uv_index": "Very High (9)",
            "sunrise": "6:15 AM",
            "sunset": "7:45 PM",
            "forecast": {
                "today": "High 82°F, Low 55°F, sunny and clear",
                "tomorrow": "High 85°F, Low 58°F, mostly sunny",
                "weekend": "High 88°F, Low 62°F, clear skies",
            },
            "air_quality": "Good (AQI: 45)",
            "pollen_count": "Moderate",
            "marine_conditions": "N/A - Landlocked location",
        },
        "Las Vegas": {
            "current": "Hot and dry with clear skies",
            "temperature": "95°F (35°C)",
            "humidity": "15%",
            "wind": "12 mph from the southwest",
            "visibility": "25 miles",
            "pressure": "29.95 inches",
            "uv_index": "Extreme (11)",
            "sunrise": "6:00 AM",
            "sunset": "8:00 PM",
            "forecast": {
                "today": "High 98°F, Low 75°F, sunny and hot",
                "tomorrow": "High 100°F, Low 78°F, clear and very hot",
                "weekend": "High 102°F, Low 80°F, extreme heat",
            },
            "air_quality": "Moderate (AQI: 82)",
            "pollen_count": "Low",
            "marine_conditions": "N/A - Desert location",
        },
    }

    if city not in weather_conditions:
        return f"Weather data for {city} is not available in our database."

    weather = weather_conditions[city]

    return f"""
# Comprehensive Weather Report for {city}

## Current Conditions
- **Temperature**: {weather["temperature"]}
- **Conditions**: {weather["current"]}
- **Humidity**: {weather["humidity"]}
- **Wind**: {weather["wind"]}
- **Visibility**: {weather["visibility"]}
- **Pressure**: {weather["pressure"]}
- **UV Index**: {weather["uv_index"]}

## Daily Schedule
- **Sunrise**: {weather["sunrise"]}
- **Sunset**: {weather["sunset"]}

## Extended Forecast
- **Today**: {weather["forecast"]["today"]}
- **Tomorrow**: {weather["forecast"]["tomorrow"]}
- **Weekend**: {weather["forecast"]["weekend"]}

## Environmental Conditions
- **Air Quality**: {weather["air_quality"]}
- **Pollen Count**: {weather["pollen_count"]}
- **Marine Conditions**: {weather["marine_conditions"]}

## Weather Advisory
Based on current conditions, visitors to {city} should be prepared for {weather["current"].lower()}. The UV index of {weather["uv_index"]} indicates {"sun protection is essential" if "High" in weather["uv_index"] or "Very High" in weather["uv_index"] or "Extreme" in weather["uv_index"] else "moderate sun protection recommended"}. {"High humidity may make temperatures feel warmer than actual readings." if int(weather["humidity"].replace("%", "")) > 70 else "Comfortable humidity levels are expected."}

## Travel Recommendations
- **Best Time for Outdoor Activities**: {"Early morning or late afternoon to avoid peak heat" if int(weather["temperature"].split("°")[0]) > 85 else "Any time during daylight hours"}
- **Clothing Suggestions**: {"Light, breathable clothing recommended" if int(weather["temperature"].split("°")[0]) > 80 else "Comfortable clothing suitable for current temperatures"}
- **Hydration**: {"Stay well-hydrated due to high temperatures" if int(weather["temperature"].split("°")[0]) > 85 else "Normal hydration levels recommended"}

This comprehensive weather report provides all the essential information needed for planning activities and ensuring comfort during your visit to {city}.
"""


def get_activities(city: str) -> str:
    """Get detailed activity information for a city."""
    city_activities = {
        "New York": {
            "outdoor": [
                "Central Park walking tours and picnics",
                "Brooklyn Bridge sunset walks",
                "High Line elevated park exploration",
                "Battery Park waterfront activities",
                "Prospect Park nature trails",
                "Governors Island weekend visits",
                "Riverside Park cycling paths",
                "Bryant Park seasonal activities",
            ],
            "cultural": [
                "Metropolitan Museum of Art comprehensive tours",
                "Museum of Modern Art (MoMA) exhibitions",
                "American Museum of Natural History dinosaur exhibits",
                "Broadway theater performances",
                "Lincoln Center performing arts",
                "Guggenheim Museum architecture and art",
                "Whitney Museum of American Art",
                "Brooklyn Museum cultural exhibits",
            ],
            "entertainment": [
                "Times Square nightlife and entertainment",
                "Empire State Building observation deck",
                "Statue of Liberty and Ellis Island tours",
                "Rockefeller Center ice skating",
                "Madison Square Garden events",
                "Radio City Music Hall shows",
                "Carnegie Hall classical concerts",
                "Comedy Cellar stand-up comedy",
            ],
            "shopping": [
                "Fifth Avenue luxury shopping district",
                "SoHo boutique shopping experience",
                "Chelsea Market food and crafts",
                "Brooklyn Flea Market vintage finds",
                "Union Square Greenmarket farmers market",
                "Century 21 discount designer shopping",
                "Bergdorf Goodman luxury department store",
                "ABC Carpet & Home home decor",
            ],
            "dining": [
                "Katz's Delicatessen pastrami sandwiches",
                "Peter Luger Steak House classic steaks",
                "Joe's Pizza authentic New York slices",
                "Russ & Daughters Jewish delicatessen",
                "Gramercy Tavern farm-to-table dining",
                "Le Bernardin seafood excellence",
                "Momofuku Noodle Bar Asian fusion",
                "Magnolia Bakery cupcakes and desserts",
            ],
        },
        "Los Angeles": {
            "outdoor": [
                "Griffith Observatory hiking and city views",
                "Venice Beach boardwalk and muscle beach",
                "Runyon Canyon Park dog-friendly hiking",
                "Santa Monica Pier and beach activities",
                "Malibu beach surfing and swimming",
                "Echo Park Lake paddle boating",
                "Griffith Park horseback riding",
                "Topanga State Park wilderness trails",
            ],
            "cultural": [
                "Getty Center art museum and gardens",
                "Los Angeles County Museum of Art (LACMA)",
                "Hollywood Walk of Fame star hunting",
                "Universal Studios Hollywood theme park",
                "Warner Bros. Studio Tour",
                "Natural History Museum dinosaur exhibits",
                "California Science Center space shuttle",
                "The Broad contemporary art museum",
            ],
            "entertainment": [
                "Disneyland Resort theme park adventure",
                "Hollywood Bowl outdoor concerts",
                "Dodger Stadium baseball games",
                "Staples Center Lakers basketball",
                "Comedy Store stand-up comedy",
                "Roxy Theatre live music venue",
                "Greek Theatre outdoor amphitheater",
                "TCL Chinese Theatre movie premieres",
            ],
            "shopping": [
                "Rodeo Drive luxury shopping experience",
                "The Grove outdoor shopping center",
                "Melrose Avenue trendy boutiques",
                "Beverly Center mall shopping",
                "Abbot Kinney Boulevard unique shops",
                "Third Street Promenade Santa Monica",
                "Glendale Galleria shopping complex",
                "Fashion District wholesale shopping",
            ],
            "dining": [
                "In-N-Out Burger classic California burgers",
                "Pink's Hot Dogs Hollywood institution",
                "Philippe the Original French dip sandwiches",
                "Musso & Frank Grill classic Hollywood dining",
                "Nobu Los Angeles celebrity sushi spot",
                "Gjelina Venice Beach farm-to-table",
                "Animal Restaurant innovative cuisine",
                "Bottega Louie Italian pastries and dining",
            ],
        },
        "Chicago": {
            "outdoor": [
                "Millennium Park Cloud Gate sculpture",
                "Navy Pier lakefront entertainment",
                "Grant Park Buckingham Fountain",
                "Lincoln Park Zoo free admission",
                "Lake Michigan beach activities",
                "Chicago Riverwalk scenic strolls",
                "Maggie Daley Park family activities",
                "606 elevated trail cycling",
            ],
            "cultural": [
                "Art Institute of Chicago world-class art",
                "Field Museum natural history exhibits",
                "Shedd Aquarium marine life displays",
                "Adler Planetarium astronomy shows",
                "Museum of Science and Industry hands-on exhibits",
                "Chicago History Museum local heritage",
                "National Museum of Mexican Art",
                "DuSable Museum of African American History",
            ],
            "entertainment": [
                "Willis Tower Skydeck observation deck",
                "Wrigley Field Cubs baseball games",
                "United Center Bulls basketball",
                "Second City comedy theater",
                "Chicago Theatre historic venue",
                "Arie Crown Theater performances",
                "House of Blues live music",
                "Blue Man Group theatrical experience",
            ],
            "shopping": [
                "Magnificent Mile luxury shopping district",
                "Water Tower Place shopping center",
                "State Street retail corridor",
                "Oak Street designer boutiques",
                "Michigan Avenue shopping experience",
                "Wicker Park trendy shops",
                "Andersonville unique stores",
                "Lincoln Square German heritage shopping",
            ],
            "dining": [
                "Giordano's deep dish pizza",
                "Portillo's Chicago-style hot dogs",
                "Lou Malnati's authentic deep dish",
                "Al's Beef Italian beef sandwiches",
                "Billy Goat Tavern historic bar",
                "Girl & the Goat innovative cuisine",
                "Alinea molecular gastronomy",
                "Au Cheval gourmet burgers",
            ],
        },
        "Houston": {
            "outdoor": [
                "Buffalo Bayou Park urban nature trails",
                "Hermann Park Japanese Garden",
                "Discovery Green downtown activities",
                "Memorial Park extensive hiking trails",
                "Houston Arboretum nature education",
                "Rice University campus walking tours",
                "Sam Houston Park historic buildings",
                "Eleanor Tinsley Park bayou views",
            ],
            "cultural": [
                "Museum of Fine Arts Houston",
                "Houston Museum of Natural Science",
                "Children's Museum of Houston",
                "Contemporary Arts Museum Houston",
                "Holocaust Museum Houston",
                "Buffalo Soldiers National Museum",
                "Asia Society Texas Center",
                "Houston Center for Photography",
            ],
            "entertainment": [
                "Space Center Houston NASA exhibits",
                "Houston Zoo animal encounters",
                "Miller Outdoor Theatre free performances",
                "Toyota Center Rockets basketball",
                "Minute Maid Park Astros baseball",
                "NRG Stadium Texans football",
                "House of Blues Houston live music",
                "Jones Hall performing arts",
            ],
            "shopping": [
                "Galleria Mall luxury shopping complex",
                "River Oaks District upscale retail",
                "Rice Village boutique shopping",
                "Memorial City Mall family shopping",
                "Katy Mills outlet shopping",
                "Houston Premium Outlets",
                "Baybrook Mall suburban shopping",
                "Willowbrook Mall northwest shopping",
            ],
            "dining": [
                "Pappas Bros. Steakhouse premium steaks",
                "Killen's Barbecue Texas BBQ",
                "Ninfa's on Navigation Tex-Mex",
                "Goode Company Seafood Gulf Coast",
                "Hugo's upscale Mexican cuisine",
                "Uchi Houston sushi excellence",
                "Underbelly Houston Southern cuisine",
                "Truth BBQ award-winning barbecue",
            ],
        },
        "Miami": {
            "outdoor": [
                "South Beach Art Deco walking tours",
                "Vizcaya Museum and Gardens",
                "Biscayne Bay water activities",
                "Crandon Park beach and tennis",
                "Fairchild Tropical Botanic Garden",
                "Matheson Hammock Park natural areas",
                "Bill Baggs Cape Florida State Park",
                "Oleta River State Park kayaking",
            ],
            "cultural": [
                "Pérez Art Museum Miami contemporary art",
                "Vizcaya Museum and Gardens historic estate",
                "Frost Science Museum interactive exhibits",
                "HistoryMiami Museum local heritage",
                "Jewish Museum of Florida",
                "Coral Gables Museum architecture",
                "Lowe Art Museum University of Miami",
                "Bass Museum of Art contemporary",
            ],
            "entertainment": [
                "Wynwood Walls street art district",
                "Little Havana cultural experience",
                "Bayside Marketplace waterfront shopping",
                "American Airlines Arena Heat basketball",
                "Hard Rock Stadium Dolphins football",
                "Marlins Park baseball games",
                "Fillmore Miami Beach live music",
                "Adrienne Arsht Center performing arts",
            ],
            "shopping": [
                "Lincoln Road Mall outdoor shopping",
                "Brickell City Centre luxury retail",
                "Aventura Mall largest shopping center",
                "Bal Harbour Shops upscale boutiques",
                "Dolphin Mall outlet shopping",
                "Sawgrass Mills outlet complex",
                "Merrick Park Coral Gables shopping",
                "CocoWalk Coconut Grove retail",
            ],
            "dining": [
                "Joe's Stone Crab Miami Beach institution",
                "Versailles Restaurant Cuban cuisine",
                "Garcia's Seafood Grille fresh seafood",
                "Yardbird Southern Table & Bar",
                "Zuma Miami Japanese izakaya",
                "Nobu Miami Beach celebrity dining",
                "Prime 112 steakhouse excellence",
                "La Sandwicherie French sandwiches",
            ],
        },
        "San Francisco": {
            "outdoor": [
                "Golden Gate Bridge walking and cycling",
                "Alcatraz Island historic prison tour",
                "Fisherman's Wharf waterfront activities",
                "Golden Gate Park extensive gardens",
                "Lands End coastal hiking trails",
                "Twin Peaks panoramic city views",
                "Crissy Field beach and recreation",
                "Angel Island State Park hiking",
            ],
            "cultural": [
                "de Young Museum fine arts",
                "San Francisco Museum of Modern Art",
                "California Academy of Sciences",
                "Exploratorium interactive science",
                "Asian Art Museum comprehensive collection",
                "Legion of Honor European art",
                "Contemporary Jewish Museum",
                "Walt Disney Family Museum",
            ],
            "entertainment": [
                "Pier 39 sea lions and attractions",
                "Oracle Park Giants baseball",
                "Chase Center Warriors basketball",
                "AT&T Park waterfront stadium",
                "Fillmore Auditorium live music",
                "Warfield Theatre historic venue",
                "Great American Music Hall",
                "SFJAZZ Center jazz performances",
            ],
            "shopping": [
                "Union Square luxury shopping district",
                "Fisherman's Wharf tourist shopping",
                "Haight-Ashbury vintage clothing",
                "North Beach Italian neighborhood",
                "Chestnut Street boutique shopping",
                "Fillmore Street upscale retail",
                "Valencia Street Mission District",
                "Grant Avenue Chinatown shopping",
            ],
            "dining": [
                "Tartine Bakery artisanal breads",
                "Zuni Café California cuisine",
                "Swan Oyster Depot seafood counter",
                "House of Prime Rib classic steaks",
                "Gary Danko fine dining experience",
                "State Bird Provisions innovative",
                "Tadich Grill historic seafood",
                "Boudin Bakery sourdough bread",
            ],
        },
        "Seattle": {
            "outdoor": [
                "Pike Place Market waterfront activities",
                "Space Needle observation deck",
                "Olympic Sculpture Park waterfront art",
                "Discovery Park extensive hiking trails",
                "Green Lake Park walking and cycling",
                "Kerry Park panoramic city views",
                "Alki Beach West Seattle activities",
                "Washington Park Arboretum gardens",
            ],
            "cultural": [
                "Seattle Art Museum comprehensive collection",
                "Museum of Pop Culture (MoPOP)",
                "Chihuly Garden and Glass blown glass art",
                "Seattle Aquarium marine life",
                "Wing Luke Museum Asian American history",
                "Museum of Flight aviation history",
                "Frye Art Museum free admission",
                "Nordic Heritage Museum Scandinavian",
            ],
            "entertainment": [
                "CenturyLink Field Seahawks football",
                "T-Mobile Park Mariners baseball",
                "Climate Pledge Arena Kraken hockey",
                "Paramount Theatre historic venue",
                "Showbox at the Market live music",
                "Neptune Theatre University District",
                "Moore Theatre downtown venue",
                "Crocodile Café intimate music venue",
            ],
            "shopping": [
                "Pike Place Market local crafts and food",
                "Westlake Center downtown shopping",
                "University Village upscale retail",
                "Bellevue Square eastside shopping",
                "Northgate Mall north Seattle",
                "Southcenter Mall south Seattle",
                "Alderwood Mall north suburbs",
                "Redmond Town Center eastside retail",
            ],
            "dining": [
                "Pike Place Chowder award-winning chowder",
                "Canlis fine dining institution",
                "Salumi Artisan Cured Meats",
                "Tilth organic farm-to-table",
                "The Walrus and the Carpenter oysters",
                "Paseo Caribbean sandwiches",
                "Molly Moon's Homemade Ice Cream",
                "Top Pot Doughnuts hand-forged doughnuts",
            ],
        },
        "Boston": {
            "outdoor": [
                "Freedom Trail historic walking tour",
                "Boston Common and Public Garden",
                "Charles River Esplanade walking",
                "Boston Harbor Islands ferry trips",
                "Emerald Necklace park system",
                "Castle Island South Boston waterfront",
                "Arnold Arboretum Harvard University",
                "Jamaica Pond walking and boating",
            ],
            "cultural": [
                "Museum of Fine Arts Boston",
                "Isabella Stewart Gardner Museum",
                "Boston Tea Party Ships & Museum",
                "John F. Kennedy Presidential Library",
                "Museum of Science interactive exhibits",
                "New England Aquarium marine life",
                "Institute of Contemporary Art",
                "Boston Children's Museum family",
            ],
            "entertainment": [
                "Fenway Park Red Sox baseball",
                "TD Garden Celtics basketball",
                "Boston Symphony Orchestra",
                "Boston Opera House performances",
                "House of Blues Boston live music",
                "Paradise Rock Club intimate venue",
                "Orpheum Theatre historic venue",
                "Wang Theatre performing arts",
            ],
            "shopping": [
                "Faneuil Hall Marketplace historic shopping",
                "Newbury Street boutique shopping",
                "Copley Place luxury retail",
                "Prudential Center shopping complex",
                "Assembly Row outlet shopping",
                "Natick Mall suburban shopping",
                "Burlington Mall north suburbs",
                "South Shore Plaza south suburbs",
            ],
            "dining": [
                "Legal Sea Foods fresh seafood",
                "Union Oyster House historic restaurant",
                "Mike's Pastry Italian pastries",
                "Neptune Oyster fresh oysters",
                "Giacomo's Ristorante Italian cuisine",
                "Flour Bakery + Café artisanal pastries",
                "Santarpio's Pizza East Boston",
                "Kelly's Roast Beef North Shore",
            ],
        },
        "Washington D.C.": {
            "outdoor": [
                "National Mall monuments and memorials",
                "Tidal Basin cherry blossom viewing",
                "Rock Creek Park extensive trails",
                "Georgetown Waterfront Park",
                "East Potomac Park golf and recreation",
                "Kenilworth Aquatic Gardens",
                "C&O Canal National Historical Park",
                "Great Falls Park Virginia side",
            ],
            "cultural": [
                "Smithsonian Institution museums",
                "National Gallery of Art",
                "United States Holocaust Memorial Museum",
                "National Museum of African American History",
                "Library of Congress largest library",
                "National Archives historical documents",
                "International Spy Museum",
                "Newseum journalism museum",
            ],
            "entertainment": [
                "Capitol Building guided tours",
                "White House visitor center",
                "Arlington National Cemetery",
                "Kennedy Center performing arts",
                "National Theatre historic venue",
                "9:30 Club live music venue",
                "The Anthem waterfront venue",
                "Wolf Trap performing arts center",
            ],
            "shopping": [
                "Georgetown historic shopping district",
                "Union Market food and crafts",
                "Tysons Corner Center Virginia",
                "Pentagon City Mall Arlington",
                "Potomac Mills outlet shopping",
                "National Harbor waterfront retail",
                "CityCenterDC luxury shopping",
                "Eastern Market Capitol Hill",
            ],
            "dining": [
                "Ben's Chili Bowl Washington institution",
                "Old Ebbitt Grill historic restaurant",
                "Founding Farmers farm-to-table",
                "Rasika modern Indian cuisine",
                "Le Diplomate French bistro",
                "Rose's Luxury innovative American",
                "Komi Mediterranean fine dining",
                "Toki Underground ramen noodles",
            ],
        },
        "Atlanta": {
            "outdoor": [
                "Piedmont Park extensive recreation",
                "Atlanta BeltLine walking and cycling",
                "Stone Mountain Park hiking",
                "Chattahoochee River National Recreation Area",
                "Atlanta Botanical Garden",
                "Grant Park Zoo Atlanta",
                "Centennial Olympic Park",
                "Chastain Park amphitheater and trails",
            ],
            "cultural": [
                "High Museum of Art",
                "Atlanta History Center",
                "Martin Luther King Jr. National Historical Park",
                "Fernbank Museum of Natural History",
                "Center for Civil and Human Rights",
                "Atlanta Contemporary Art Center",
                "Michael C. Carlos Museum Emory",
                "Spelman College Museum of Fine Art",
            ],
            "entertainment": [
                "World of Coca-Cola museum",
                "Georgia Aquarium marine life",
                "Mercedes-Benz Stadium Falcons football",
                "Truist Park Braves baseball",
                "State Farm Arena Hawks basketball",
                "Fox Theatre historic venue",
                "Tabernacle live music venue",
                "Variety Playhouse intimate concerts",
            ],
            "shopping": [
                "Lenox Square luxury shopping",
                "Phipps Plaza upscale retail",
                "Atlantic Station mixed-use development",
                "Ponce City Market food hall and shops",
                "Krog Street Market food and retail",
                "Buckhead Village boutique shopping",
                "Virginia-Highland unique stores",
                "Little Five Points alternative shopping",
            ],
            "dining": [
                "The Varsity classic drive-in",
                "Mary Mac's Tea Room Southern cuisine",
                "Fox Bros. Bar-B-Q Texas-style barbecue",
                "Bacchanalia fine dining experience",
                "Miller Union farm-to-table",
                "Staplehouse innovative American",
                "Gunshow creative Southern cuisine",
                "Atlanta Fish Market fresh seafood",
            ],
        },
        "Denver": {
            "outdoor": [
                "Red Rocks Park and Amphitheatre",
                "Rocky Mountain National Park hiking",
                "Denver Botanic Gardens",
                "City Park walking and cycling",
                "Washington Park recreation",
                "Cherry Creek State Park",
                "Mount Evans Scenic Byway",
                "Garden of the Gods Colorado Springs",
            ],
            "cultural": [
                "Denver Art Museum",
                "Denver Museum of Nature & Science",
                "Clyfford Still Museum",
                "Museum of Contemporary Art Denver",
                "History Colorado Center",
                "Black American West Museum",
                "Mizel Museum Jewish culture",
                "Kirkland Museum of Fine & Decorative Art",
            ],
            "entertainment": [
                "Coors Field Rockies baseball",
                "Empower Field at Mile High Broncos football",
                "Ball Arena Nuggets basketball",
                "Red Rocks Amphitheatre concerts",
                "Ogden Theatre live music",
                "Bluebird Theatre intimate venue",
                "Fillmore Auditorium historic venue",
                "Paramount Theatre performing arts",
            ],
            "shopping": [
                "Cherry Creek Shopping Center",
                "Larimer Square historic shopping",
                "16th Street Mall pedestrian shopping",
                "Park Meadows Mall south Denver",
                "Flatiron Crossing Broomfield",
                "Aspen Grove Littleton",
                "Belmar Lakewood shopping",
                "Southlands Aurora retail",
            ],
            "dining": [
                "Casa Bonita Mexican restaurant",
                "Buckhorn Exchange historic steakhouse",
                "Snooze an A.M. Eatery breakfast",
                "Linger rooftop dining",
                "Root Down farm-to-table",
                "Fruition Restaurant fine dining",
                "Acorn at The Source market hall",
                "Work & Class contemporary American",
            ],
        },
        "Las Vegas": {
            "outdoor": [
                "Red Rock Canyon National Conservation Area",
                "Valley of Fire State Park",
                "Mount Charleston hiking",
                "Lake Mead National Recreation Area",
                "Springs Preserve desert gardens",
                "Floyd Lamb Park at Tule Springs",
                "Clark County Wetlands Park",
                "Sloan Canyon National Conservation Area",
            ],
            "cultural": [
                "The Mob Museum organized crime history",
                "Neon Museum vintage signs",
                "Discovery Children's Museum",
                "Las Vegas Natural History Museum",
                "Nevada State Museum",
                "Old Las Vegas Mormon Fort",
                "Atomic Testing Museum",
                "Las Vegas Art Museum",
            ],
            "entertainment": [
                "The Strip casino and resort hopping",
                "Fremont Street Experience",
                "Bellagio Fountains water show",
                "Cirque du Soleil performances",
                "High Roller observation wheel",
                "Stratosphere Tower thrill rides",
                "Downtown Container Park",
                "Area 15 immersive experiences",
            ],
            "shopping": [
                "Fashion Show Mall",
                "Forum Shops at Caesars",
                "Grand Canal Shoppes Venetian",
                "Miracle Mile Shops Planet Hollywood",
                "Town Square Las Vegas",
                "Las Vegas Premium Outlets North",
                "Las Vegas Premium Outlets South",
                "Meadows Mall local shopping",
            ],
            "dining": [
                "In-N-Out Burger California burgers",
                "Pizza Rock gourmet pizza",
                "Lotus of Siam Thai cuisine",
                "Bacchanal Buffet Caesars Palace",
                "Gordon Ramsay Hell's Kitchen",
                "Joël Robuchon fine dining",
                "Raku Japanese izakaya",
                "Echo & Rig Butcher and Steakhouse",
            ],
        },
    }

    if city not in city_activities:
        return f"Activity information for {city} is not available in our database."

    activities = city_activities[city]

    return f"""
# Comprehensive Activity Guide for {city}

## Outdoor Adventures & Recreation
{chr(10).join([f"- {activity}" for activity in activities["outdoor"]])}

## Cultural Experiences & Museums
{chr(10).join([f"- {activity}" for activity in activities["cultural"]])}

## Entertainment & Nightlife
{chr(10).join([f"- {activity}" for activity in activities["entertainment"]])}

## Shopping Destinations
{chr(10).join([f"- {activity}" for activity in activities["shopping"]])}

## Dining & Culinary Experiences
{chr(10).join([f"- {activity}" for activity in activities["dining"]])}

## Activity Recommendations by Interest

### For Nature Enthusiasts
The outdoor activities in {city} offer incredible opportunities to connect with nature. From urban parks to wilderness trails, visitors can enjoy hiking, cycling, water activities, and scenic viewpoints that showcase the city's natural beauty and diverse landscapes.

### For Culture & History Buffs
{city} boasts an impressive collection of museums, galleries, and cultural institutions that tell the story of the city's rich heritage and artistic achievements. From world-class art collections to interactive science exhibits, there's something to engage every cultural interest.

### For Entertainment Seekers
The entertainment scene in {city} is vibrant and diverse, offering everything from professional sports and live music venues to historic theaters and modern performance spaces. Whether you're looking for high-energy nightlife or family-friendly entertainment, the city delivers memorable experiences.

### For Shopping Enthusiasts
Shopping in {city} ranges from luxury boutiques and designer stores to unique local markets and outlet centers. Each shopping district offers its own character and specialties, making it easy to find everything from high-end fashion to one-of-a-kind souvenirs.

### For Food Lovers
The culinary scene in {city} reflects the city's diverse population and cultural influences. From iconic local institutions to innovative fine dining establishments, the city offers an exceptional range of dining experiences that showcase both traditional favorites and contemporary culinary creativity.

## Planning Your Visit
When planning activities in {city}, consider the weather conditions, seasonal events, and your personal interests. Many attractions offer advance booking options, and some museums have free admission days. The city's public transportation system makes it easy to explore different neighborhoods and experience the full range of activities available.

This comprehensive guide provides a starting point for discovering all that {city} has to offer, ensuring visitors can create memorable experiences tailored to their interests and preferences.
"""


weather_agent = Agent(
    id="weather_agent",
    model=OpenAIResponses(id="gpt-4o"),
    description="You are a helpful assistant that can answer questions about the weather.",
    instructions="Be concise, reply with one sentence.",
    tools=[ReasoningTools(add_instructions=True), get_weather],
    db=db,
    enable_user_memories=True,
    add_history_to_context=True,
    read_tool_call_history=False,
    stream=True,
    stream_events=True,
)

activities_agent = Agent(
    id="activities_agent",
    model=OpenAIResponses(id="gpt-4o"),
    description="You are a helpful assistant that can answer questions about activities in a city.",
    instructions="Be concise, reply with one sentence.",
    tools=[ReasoningTools(add_instructions=True), get_activities],
    db=db,
    enable_user_memories=True,
    add_history_to_context=True,
    read_tool_call_history=False,
    stream=True,
    stream_events=True,
)

team = Team(
    model=OpenAIResponses(id="gpt-4o"),
    members=[weather_agent, activities_agent],
    tools=[ReasoningTools(add_instructions=True)],
    instructions="Be concise, reply with one sentence.",
    db=db,
    markdown=True,
    add_datetime_to_context=True,
    enable_user_memories=True,
    share_member_interactions=False,
    add_history_to_context=True,
    read_chat_history=False,
    stream=True,
    stream_events=True,
)


async def run_team_for_user(user: str, print_responses: bool = False):
    # Make four requests to the team, to build up history
    random_city = random.choice(cities)
    session_id = f"session_{user}_{uuid.uuid4()}"

    _ = team.arun(input=f"I love {random_city}!", user_id=user, session_id=session_id)
    _ = team.arun(
        input=f"Create a report on the activities and weather in {random_city}.",
        user_id=user,
        session_id=session_id,
    )
    _ = team.arun(
        input=f"What else can you tell me about {random_city}?",
        user_id=user,
        session_id=session_id,
    )
    _ = team.arun(
        input=f"What other cities are similar to {random_city}?",
        user_id=user,
        session_id=session_id,
    )


async def run_team():
    tasks = []

    # Run all 5 users concurrently
    for user in users:
        tasks.append(run_team_for_user(user))
    await asyncio.gather(*tasks)

    return "Successfully ran team"


team_response_with_memory_impact = PerformanceEval(
    name="Team Memory Impact",
    func=run_team,
    num_iterations=5,
    warmup_runs=0,
    measure_runtime=False,
    debug_mode=True,
    memory_growth_tracking=True,
    top_n_memory_allocations=10,
)

if __name__ == "__main__":
    asyncio.run(
        team_response_with_memory_impact.arun(print_results=True, print_summary=True)
    )
