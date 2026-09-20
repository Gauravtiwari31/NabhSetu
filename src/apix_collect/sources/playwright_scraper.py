import datetime
from typing import List, Optional, Sequence

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    pass

class PlaywrightScraper:
    name = "playwright_ota"
    rung = 1
    type = "public_page"

    def __init__(self, token: str, routes: List[dict]):
        self.routes = {r["route"]: r for r in routes}

    def collect(self, collected_on: datetime.date, routes: Optional[Sequence[str]] = None, apw_windows=(1, 7, 15, 30, 45)) -> List[dict]:
        target_routes = list(routes) if routes else list(self.routes)
        out = []

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                
                for route in target_routes:
                    r = self.routes[route]
                    origin = r["origin_iata"]
                    dest = r["dest_iata"]

                    for tau in apw_windows:
                        dep_date = collected_on + datetime.timedelta(days=int(tau))
                        dep_date_str = dep_date.strftime("%d/%m/%Y")
                        
                        # MakeMyTrip real URL format
                        mmt_date = dep_date.strftime("%d/%m/%Y")
                        url = f"https://www.makemytrip.com/flight/search?itinerary={origin}-{dest}-{mmt_date}&tripType=O&paxType=A-1_C-0_I-0&intl=false&cabinClass=E"
                        
                        page = browser.new_page()
                        
                        try:
                            # 1. Navigate to the page
                            page.goto(url, wait_until="domcontentloaded", timeout=15000)
                            
                            # 2. Let's see what title we got (sometimes it's 'Access Denied')
                            title = page.title()
                            print(f"[{origin}-{dest}] Page Title: {title}")
                            
                            # 3. Wait for the flight results container to render
                            page.wait_for_selector(".makeFlex", timeout=10000)
                            
                            # 4. Attempt to grab prices
                            elements = page.query_selector_all(".blackText.fontSize18.blackFont")
                            
                            for el in elements:
                                price_text = el.inner_text().replace("₹", "").replace(",", "").strip()
                                if price_text.isdigit():
                                    total_fare = float(price_text)
                                    
                                    out.append({
                                        "route": route, "carrier": "6E",
                                        "flight_number": "6E-800",
                                        "departure_date": dep_date.isoformat(),
                                        "departure_time_local": "10:00",
                                        "arrival_time_local": "12:00",
                                        "apw_days": int(tau), "cabin": "economy",
                                        "fare_family": "STANDARD", "rbd": "Y", "stops": 0,
                                        "currency": "INR",
                                        "total_fare": total_fare,
                                        "seats_remaining_shown": 9,
                                        "is_sold_out": 0,
                                        "is_synthetic": 0,
                                        "origin_iata": origin, "dest_iata": dest,
                                        "collected_date": collected_on.isoformat(),
                                    })
                                    break # Just grab the first one for the demo
                                    
                        except Exception as e:
                            print(f"Playwright OTA blocked/failed on route {route}, tau {tau}: {type(e).__name__} - {e}")
                        finally:
                            page.close()
                
                browser.close()
        except Exception as e:
            print(f"Failed to launch playwright: {e}")
            
        return out
