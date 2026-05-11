# -*- coding: utf-8 -*-
import requests
from datetime import datetime

CITIES = {
    "1": {"name": "Алматы", "lat": 43.25, "lon": 76.95},
    "2": {"name": "Астана", "lat": 51.18, "lon": 71.45},
    "3": {"name": "Шымкент", "lat": 42.30, "lon": 69.60},
    "4": {"name": "Караганда", "lat": 49.80, "lon": 73.10},
    "15": {"name": "Актау", "lat": 43.65, "lon": 51.17}
}

def get_moon_phase_icon(dt):
    year, month, day = dt.year, dt.month, dt.day
    ages = [18, 0, 11, 22, 3, 14, 25, 6, 17, 28, 9, 20, 1, 12, 23, 4, 15, 26, 7]
    offsets = [-1, 1, 0, 1, 2, 3, 4, 5, 7, 7, 9, 9]
    golden_number = (year % 19)
    age = (ages[golden_number] + day + offsets[month - 1])
    if month > 2: age -= 1
    if year % 4 == 0 and month > 2: age += 1
    res_age = age % 30
    
    if res_age < 2: return "🌑"
    if res_age < 7: return "🌒"
    if res_age < 14: return "🌓"
    if res_age < 17: return "🌕"
    if res_age < 24: return "🌗"
    return "🌘"

def get_vortex_weather(city_id="1"):
    city = CITIES.get(str(city_id), CITIES["1"])
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": city['lat'],
        "longitude": city['lon'],
        "current_weather": True,
        "timezone": "auto"
    }
    try:
        res = requests.get(url, params=params, timeout=5).json()
        temp = res['current_weather']['temperature']
        icon = get_moon_phase_icon(datetime.now())
        # Возвращаем короткую строку для индикатора
        return f"{city['name'].upper()} {temp}°C {icon}"
    except:
        return "МЕТЕО-ДАННЫЕ ОФФЛАЙН"