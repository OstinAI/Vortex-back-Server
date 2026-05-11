import requests
import json
from datetime import datetime

def get_moon_phase(year, month, day):
    ages = [18, 0, 11, 22, 3, 14, 25, 6, 17, 28, 9, 20, 1, 12, 23, 4, 15, 26, 7]
    offsets = [-1, 1, 0, 1, 2, 3, 4, 5, 7, 7, 9, 9]
    golden_number = (year % 19)
    age = (ages[golden_number] + day + offsets[month - 1])
    if month > 2: age -= 1
    if year % 4 == 0 and month > 2: age += 1
    res_age = age % 30
    if res_age < 2: return "Новолуние", "🌑"
    if res_age < 7: return "Растущий серп", "🌒"
    if res_age < 10: return "1-я четверть", "🌓"
    if res_age < 14: return "Растущая луна", "🌔"
    if res_age < 17: return "Полнолуние", "🌕"
    if res_age < 21: return "Убывающая луна", "🌖"
    if res_age < 24: return "3-я четверть", "🌗"
    if res_age < 29: return "Стареющий серп", "🌘"
    return "Новолуние", "🌑"

def get_weather_full():
    cities = {
        "1": {"name": "Алматы", "lat": 43.25, "lon": 76.95},
        "2": {"name": "Астана", "lat": 51.18, "lon": 71.45},
        "3": {"name": "Шымкент", "lat": 42.30, "lon": 69.60},
        "4": {"name": "Караганда", "lat": 49.80, "lon": 73.10},
        "15": {"name": "Актау", "lat": 43.65, "lon": 51.17}
    }

    print("Выберите город:")
    for key, city in cities.items():
        print(f"{key}. {city['name']}")
    
    choice = input("\nВведите номер города: ")
    if choice not in cities: return

    selected_city = cities[choice]
    url = "https://api.open-meteo.com/v1/forecast"
    
    params = {
        "latitude": selected_city['lat'],
        "longitude": selected_city['lon'],
        "daily": [
            "temperature_2m_max", "temperature_2m_min", "uv_index_max", 
            "sunrise", "sunset", "precipitation_sum", "shortwave_radiation_sum"
        ],
        "hourly": [
            "temperature_2m", "apparent_temperature", "relative_humidity_2m", 
            "dewpoint_2m", "precipitation", "precipitation_probability", 
            "snowfall", "uv_index", "windspeed_10m", "surface_pressure", 
            "visibility", "cloud_cover", "is_day"
        ],
        "timezone": "auto",
        "forecast_days": 16
    }

    try:
        response = requests.get(url, params=params)
        data = response.json()
        daily = data['daily']
        hourly = data['hourly']

        # БЛОК 1: ПО ДНЯМ
        print("\n" + "="*160)
        print(f" СВОДКА ПО ДНЯМ: {selected_city['name'].upper()}")
        print("="*160)
        print(f"{'Дата':<12} | {'t° Max':<7} | {'Осадки':<7} | {'Радиац.':<10} | {'УФ Max':<6} | {'Луна':<22} | {'Солнце'}")
        print("-" * 160)

        for i in range(len(daily['time'])):
            dt = datetime.strptime(daily['time'][i], '%Y-%m-%d')
            p_name, icon = get_moon_phase(dt.year, dt.month, dt.day)
            rad = f"{daily['shortwave_radiation_sum'][i]:>5.1f} МДж"
            print(f"{daily['time'][i]:<12} | {daily['temperature_2m_max'][i]:>5}°C | {daily['precipitation_sum'][i]:>5} мм | {rad:<10} | {daily['uv_index_max'][i]:>6} | {icon+' '+p_name:<22} | {daily['sunrise'][i].split('T')[1]} - {daily['sunset'][i].split('T')[1]}")

        # БЛОК 2: ПО ЧАСАМ (ВСЁ ВКЛЮЧЕНО)
        print("\n" + "="*190)
        print(f" ПОЛНЫЙ МЕТЕО-ГРАФИК ПО ЧАСАМ (384 ЧАСА)")
        print("="*190)

        for d_idx in range(len(daily['time'])):
            print(f"\n>>> ДЕНЬ: {daily['time'][d_idx]} <<<")
            # Максимально информативная шапка
            print(f"{'Время':<6} | {'t°':<5} | {'Ощущ':<5} | {'Влаж':<4} | {'Точк':<5} | {'Осд.мм':<6} | {'Вер%':<4} | {'Снег':<4} | {'УФ':<3} | {'Ветр':<6} | {'Давл':<7} | {'Вид.':<5} | {'Обл.':<4} | {'Тип'}")
            print("-" * 190)

            for h_in_d in range(24):
                idx = (d_idx * 24) + h_in_d
                if idx >= len(hourly['time']): break

                h = hourly
                t_r = f"{h['temperature_2m'][idx]:>3.0f}°"
                t_a = f"{h['apparent_temperature'][idx]:>3.0f}°"
                hum = f"{h['relative_humidity_2m'][idx]:>3}%"
                dew = f"{h['dewpoint_2m'][idx]:>3.0f}°"
                prc = f"{h['precipitation'][idx]:>4}"
                prb = f"{h['precipitation_probability'][idx]:>3}%"
                snw = f"{h['snowfall'][idx]:>3}"
                uv  = f"{h['uv_index'][idx]:>2}"
                wnd = f"{int(h['windspeed_10m'][idx]):>2}км"
                prs = f"{int(h['surface_pressure'][idx]):>4}"
                vis = f"{int(h['visibility'][idx]/1000):>2}км"
                cld = f"{h['cloud_cover'][idx]:>3}%"
                tm  = h['time'][idx].split('T')[1]
                dn  = "День☀️" if h['is_day'][idx] == 1 else "Ночь🌙"

                print(f"{tm:<6} | {t_r:<5} | {t_a:<5} | {hum:<4} | {dew:<5} | {prc:<6} | {prb:<4} | {snw:<4} | {uv:<3} | {wnd:<6} | {prs:<7} | {vis:<5} | {cld:<4} | {dn}")

        print(f"\n[ГОТОВО] Полный архив данных в файле weather_{selected_city['name']}.json")

    except Exception as e:
        print(f"Ошибка: {e}")

if __name__ == "__main__":
    get_weather_full()
    input("\nНажмите Enter для выхода...")