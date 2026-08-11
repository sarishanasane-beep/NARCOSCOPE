"""Controlled dictionaries used by the deterministic extraction engine.

These lists are intentionally curated. Extending them improves recall
without making AI mandatory.
"""

from __future__ import annotations

LOCATIONS: set[str] = {
    # Demo / primary cities
    "Mumbai", "Pune", "Nashik", "Nagpur", "Thane", "Goa", "Delhi", "New Delhi",
    # Indian states & union territories
    "Maharashtra", "Karnataka", "Gujarat", "Rajasthan", "Uttar Pradesh", "Madhya Pradesh",
    "Tamil Nadu", "Kerala", "Andhra Pradesh", "Telangana", "West Bengal", "Bihar",
    "Odisha", "Assam", "Punjab", "Haryana", "Chhattisgarh", "Jharkhand",
    "Uttarakhand", "Himachal Pradesh", "Arunachal Pradesh", "Manipur", "Meghalaya",
    "Mizoram", "Nagaland", "Tripura", "Sikkim", "Jammu and Kashmir", "Ladakh",
    "Andaman and Nicobar Islands", "Chandigarh", "Dadra and Nagar Haveli and Daman and Diu",
    "Lakshadweep", "Puducherry",
    # Major cities
    "Bengaluru", "Bangalore", "Hyderabad", "Chennai", "Kolkata", "Ahmedabad", "Surat",
    "Jaipur", "Lucknow", "Kanpur", "Agra", "Varanasi", "Indore", "Bhopal", "Patna",
    "Chandigarh", "Kochi", "Thiruvananthapuram", "Kozhikode", "Coimbatore", "Madurai",
    "Visakhapatnam", "Vijayawada", "Mangaluru", "Mysuru", "Kota", "Udaipur", "Jodhpur",
    "Amritsar", "Ludhiana", "Jalandhar", "Dehradun", "Shimla", "Guwahati", "Ranchi",
    "Raipur", "Bhubaneswar", "Panaji", "Aurangabad", "Solapur", "Kolhapur", "Amravati",
    "Jalgaon", "Ratnagiri", "Bandra", "Andheri", "Dadar", "Panvel", "Worli",
    "Nagpur Division", "Gurugram", "Noida", "Faridabad", "Ghaziabad", "Meerut",
    "Siliguri", "Durgapur", "Jamshedpur", "Bokaro", "Dhanbad", "Cuttack",
    "Mysore", "Hubballi", "Dharwad", "Belagavi", "Kalaburagi", "Tirupati", "Nellore",
    "Kakinada", "Rajahmundry", "Guntur", "Warangal", "Karimnagar", "Nizamabad",
    # Neighboring / regional
    "Kathmandu", "Colombo", "Dhaka", "Karachi", "Lahore", "Dubai", "Sharjah", "Abu Dhabi",
    "Doha", "Muscat", "Kuwait City", "Riyadh", "Jeddah", "Tehran", "Kabul",
    "Yangon", "Bangkok", "Singapore", "Kuala Lumpur", "Jakarta", "Manila",
    # Country-level
    "India", "Nepal", "Sri Lanka", "Bangladesh", "Pakistan", "China", "Myanmar",
    "Thailand", "Vietnam", "Indonesia", "Malaysia", "United Arab Emirates",
    "Saudi Arabia", "Oman", "Qatar", "Iran", "Afghanistan", "United States",
    "United Kingdom", "Canada", "Australia", "Germany", "France", "Netherlands",
    "South Africa", "Brazil", "Mexico", "Nigeria", "Russia", "Turkey", "Egypt",
}

# Known organizations / agencies (names + acronyms).
ORGANIZATIONS: set[str] = {
    "Narcotics Control Bureau", "NCB",
    "Directorate of Revenue Intelligence", "DRI",
    "Central Bureau of Investigation", "CBI",
    "Enforcement Directorate", "ED",
    "Mumbai Police", "Pune Police", "Nashik Police", "Maharashtra Police",
    "Bombay High Court", "High Court", "Supreme Court", "District Court",
    "Customs Department", "Customs", "Excise Department", "State Excise",
    "Anti-Terrorism Squad", "ATS", "Crime Branch", "CID", "NIA", "RAW", "IB",
    "Border Security Force", "BSF", "Coast Guard", "Indian Coast Guard",
    "Central Industrial Security Force", "CISF",
    "National Investigation Agency",
    "Blue Horizon Imports", "Silverline Traders", "Redline Logistics", "Greenway Exports",
    "United Nations Office on Drugs and Crime", "UNODC",
    "Interpol",
}

# Tokens that end an organization name.
ORG_SUFFIXES: set[str] = {
    "Department", "Bureau", "Agency", "Commission", "Force", "Police", "Administration",
    "Office", "Authority", "Board", "Court", "Corporation", "Ltd", "Inc", "Company",
    "Organization", "Society", "Trust", "Cell", "Unit", "Division", "Directorate",
    "Council", "Ministry", "Government", "Association", "Customs", "Excise", "Bank",
    "Foundation", "Institute", "Institution", "Committee", "Group", "Task Force",
    "Airlines", "Industries", "Enterprises", "Traders", "Exports", "Imports",
}

# Words that strongly suggest the preceding capitalized sequence is a person.
PERSON_CONTEXT_WORDS: set[str] = {
    "was", "were", "is", "are", "has", "had", "said", "told", "stated", "claimed",
    "alleged", "allegedly", "reportedly", "arrested", "questioned", "interrogated",
    "participated", "appeared", "resides", "resided", "involved", "named", "led",
    "operates", "seen", "coordinated", "supplied", "mentioned",
}

# Honorifics / titles that mark a person name.
PERSON_TITLE_PREFIXES: set[str] = {
    "mr", "mrs", "ms", "dr", "shri", "smt", "inspector", "sub-inspector", "psi",
    "asi", "pi", "acp", "dcp", "commissioner", "advocate", "judge", "constable",
    "head constable", "prof", "sir", "er",
}

# Leading words that should never start a captured entity name.
NAME_STOPWORDS: set[str] = {
    "the", "a", "an", "in", "on", "at", "of", "for", "with", "and", "or", "but",
    "during", "after", "before", "from", "to", "by", "into", "over", "under",
    "according", "following", "including", "near", "about", "against", "between",
}

# Words whose capitalized form is not a named entity start.
SENTENCE_START_STOPWORDS: set[str] = {
    "the", "a", "an", "this", "that", "these", "those", "it", "he", "she", "they",
    "we", "you", "i", "police", "authorities", "officers", "officials", "investigation",
    "operations", "communications", "documents", "records", "report", "reports",
    "following", "during", "according", "however", "although", "because", "but",
    "after", "before", "between", "further", "moreover", "meanwhile", "mumbai",
    "pune", "nashik", "delhi", "india", "maharashtra", "the", "an", "a", "fir",
    "case", "court", "hearing", "seizure", "arrest", "raid", "operation", "search",
    "evidence", "materials", "consignment", "substances", "information", "officer",
}

# Event keywords -> event type.
EVENT_KEYWORDS: dict[str, str] = {
    "arrested": "ARREST",
    "arrest": "ARREST",
    "arrests": "ARREST",
    "seized": "SEIZURE",
    "seizure": "SEIZURE",
    "seizures": "SEIZURE",
    "raided": "RAID",
    "raid": "RAID",
    "raids": "RAID",
    "operation": "OPERATION",
    "searched": "SEARCH",
    "search": "SEARCH",
    "intercepted": "INTERCEPTION",
    "interception": "INTERCEPTION",
    "interceptions": "INTERCEPTION",
    "investigation": "INVESTIGATION",
    "investigations": "INVESTIGATION",
    "court": "COURT_PROCEEDING",
    "proceeding": "COURT_PROCEEDING",
    "proceedings": "COURT_PROCEEDING",
    "hearing": "COURT_PROCEEDING",
    "trial": "COURT_PROCEEDING",
}

# Claim status keywords.
CLAIM_STATUS_KEYWORDS: dict[str, str] = {
    "alleged": "ALLEGED",
    "allegedly": "ALLEGED",
    "reportedly": "REPORTED",
    "officially stated": "OFFICIALLY_STATED",
    "according to officials": "OFFICIALLY_STATED",
    "court recorded": "COURT_RECORDED",
    "recorded by the court": "COURT_RECORDED",
    "officially confirmed": "OFFICIALLY_STATED",
}

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}
MONTH_ALTERNATION = "January|February|March|April|May|June|July|August|September|October|November|December"

# Location hierarchy hints (child -> parent) used by the demo seed.
DEMO_LOCATION_PARENTS: dict[str, str] = {
    "Pune": "Maharashtra",
    "Mumbai": "Maharashtra",
    "Nashik": "Maharashtra",
    "Thane": "Maharashtra",
    "Nagpur": "Maharashtra",
    "Aurangabad": "Maharashtra",
    "Solapur": "Maharashtra",
    "Kolhapur": "Maharashtra",
    "Amravati": "Maharashtra",
    "Jalgaon": "Maharashtra",
    "Ratnagiri": "Maharashtra",
    "Goa": "India",
    "Delhi": "India",
    "New Delhi": "India",
    "Maharashtra": "India",
    "Karnataka": "India",
    "Gujarat": "India",
    "Rajasthan": "India",
    "Kerala": "India",
    "Tamil Nadu": "India",
    "Punjab": "India",
    "Haryana": "India",
    "West Bengal": "India",
    "Bihar": "India",
    "Madhya Pradesh": "India",
    "Uttar Pradesh": "India",
    "Telangana": "India",
    "Andhra Pradesh": "India",
    "Odisha": "India",
    "Assam": "India",
    "Chhattisgarh": "India",
    "Jharkhand": "India",
    "Uttarakhand": "India",
    "Himachal Pradesh": "India",
    "Karnataka": "India",
}
