"""Golden set — 12+ test cases for the intake agent.

Tests both the LLM path (when GROQ_API_KEY is set) and the regex fallback.
Each case includes input text, expected extraction fields, and assertions.
"""

GOLDEN_SET = [
    {
        "name": "basic English SOS",
        "text": "6 people stuck near Kankarbagh school, water rising fast, 2 children",
        "expected": {
            "people_count": 6,
            "urgency": "HIGH",
            "has_children": True,
            "water_rising": True,
            "has_location": True,
        },
    },
    {
        "name": "Hinglish with family",
        "text": "hum log 5 log hain, paani tezi se badh raha hai, do bachche hain, school ke paas",
        "expected": {
            "people_count": 5,
            "urgency": "HIGH",
            "has_children": True,
            "water_rising": True,
            "has_location": True,
        },
    },
    {
        "name": "pregnant woman, high urgency",
        "text": "My wife is pregnant, water is rising near Rajendra Nagar, please send help",
        "expected": {
            "people_count": None,
            "urgency": "HIGH",
            "has_pregnant": True,
            "water_rising": True,
            "has_location": True,
        },
    },
    {
        "name": "elderly person, no location",
        "text": "I am alone, 70 years old, water is ankle deep and rising, I cannot walk properly",
        "expected": {
            "people_count": 1,
            "has_elderly": True,
            "water_rising": True,
            "has_location": False,
            "needs_review": True,
        },
    },
    {
        "name": "safe person, low urgency",
        "text": "We are safe on the rooftop, 4 of us, water is below our floor",
        "expected": {
            "people_count": 4,
            "urgency": "LOW",
            "water_rising": False,
        },
    },
    {
        "name": "garbled text",
        "text": "asdfghjkl 12345 !@#$%",
        "expected": {
            "people_count": None,
            "needs_review": True,
        },
    },
    {
        "name": "Hindi word numbers",
        "text": "hum paanch log hain, paani badh raha hai, bachche bhi hain",
        "expected": {
            "people_count": 5,
            "has_children": True,
            "water_rising": True,
        },
    },
    {
        "name": "multiple vulnerabilities",
        "text": "3 people: my elderly mother, my injured brother, and me. Water is rising fast near the bridge",
        "expected": {
            "people_count": 3,
            "has_elderly": True,
            "has_injured": True,
            "water_rising": True,
            "has_location": True,
        },
    },
    {
        "name": "Nepali-style message",
        "text": "hami 4 jana xau, pani badiraxa, school near ma xau, bacha haru chhan",
        "expected": {
            "people_count": 4,
            "water_rising": True,
            "has_location": True,
        },
    },
    {
        "name": "word number count",
        "text": "three of us are stuck near the temple, water is at our knees",
        "expected": {
            "people_count": 3,
            "water_rising": True,
            "has_location": True,
        },
    },
    {
        "name": "disabled person",
        "text": "I am in a wheelchair, water is entering my ground floor, I need help evacuating, 2 people total",
        "expected": {
            "people_count": 2,
            "has_disabled": True,
            "water_rising": True,
            "urgency": "HIGH",
        },
    },
    {
        "name": "empty message",
        "text": "",
        "expected": {
            "people_count": None,
            "needs_review": True,
        },
    },
    {
        "name": "Hindi with digits",
        "text": "6 log hain hum, paani tezi se badh raha hai, kankarbagh ke paas",
        "expected": {
            "people_count": 6,
            "water_rising": True,
            "has_location": True,
        },
    },
    {
        "name": "no water mentioned",
        "text": "5 people need food and water, near the school",
        "expected": {
            "people_count": 5,
            "water_rising": False,
            "has_location": True,
        },
    },
    {
        "name": "Maithili flood emergency",
        "text": "bagmati ke tatbandh toot gelai, 7 aadmi chat par fasal chi, 2 chhot bacha a garbhawati mahila chi, gaur hospital",
        "expected": {
            "people_count": 7,
            "has_children": True,
            "has_pregnant": True,
            "water_rising": True,
            "has_location": True,
        },
    },
    {
        "name": "Bhojpuri flood call",
        "text": "kamala nadi ufan par ba, 5 log baandh par fasal baadan, boodha babuji bimar baadan, janakpur road",
        "expected": {
            "people_count": 5,
            "has_elderly": True,
            "has_ill": True,
            "water_rising": True,
            "has_location": True,
        },
    },
]
