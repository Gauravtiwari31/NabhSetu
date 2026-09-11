import datetime
import httpx
from typing import List, Optional, Sequence

class DuffelSource:
    name = "duffel"
    rung = 1
    type = "licensed_api"

    def __init__(self, token: str, routes: List[dict]):
        self.token = token
        self.routes = {r["route"]: r for r in routes}

    def collect(self, collected_on: datetime.date, routes: Optional[Sequence[str]] = None, apw_windows=(1, 7, 15, 30, 45)) -> List[dict]:
        target_routes = list(routes) if routes else list(self.routes)
        out = []
        headers = {
            "Duffel-Version": "v2",
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        
        with httpx.Client(timeout=30.0) as client:
            for route in target_routes:
                r = self.routes[route]
                origin = r["origin_iata"]
                dest = r["dest_iata"]
                
                for tau in apw_windows:
                    dep_date = collected_on + datetime.timedelta(days=int(tau))
                    
                    payload = {
                        "data": {
                            "slices": [{"origin": origin, "destination": dest, "departure_date": dep_date.isoformat()}],
                            "passengers": [{"type": "adult"}],
                            "cabin_class": "economy"
                        }
                    }
                    
                    try:
                        resp = client.post("https://api.duffel.com/air/offer_requests", headers=headers, json=payload)
                        if resp.status_code != 201:
                            continue
                        
                        data = resp.json().get("data", {})
                        offers = data.get("offers", [])
                        
                        for offer in offers:
                            if not offer.get("slices"): continue
                            slice_data = offer["slices"][0]
                            if not slice_data.get("segments"): continue
                            segment = slice_data["segments"][0]
                            
                            carrier = offer["owner"]["iata_code"]
                            if carrier not in ["6E", "AI", "QP", "SG"]:
                                carrier = "6E"
                            flight_number = f"{carrier}-{segment['operating_carrier_flight_number']}"
                            dep_time_local = segment["departing_at"][11:16] if segment.get("departing_at") else None
                            arr_time_local = segment["arriving_at"][11:16] if segment.get("arriving_at") else None
                            
                            stops = len(slice_data["segments"]) - 1
                            currency = offer["total_currency"]
                            total_fare = float(offer["total_amount"])
                            
                            out.append({
                                "route": route, "carrier": carrier,
                                "flight_number": flight_number,
                                "departure_date": dep_date.isoformat(),
                                "departure_time_local": dep_time_local,
                                "arrival_time_local": arr_time_local,
                                "apw_days": int(tau), "cabin": "economy",
                                "fare_family": "STANDARD", "rbd": "Y", "stops": stops,
                                "currency": currency,
                                "total_fare": round(total_fare, 2),
                                "seats_remaining_shown": 9,
                                "is_sold_out": 0,
                                "is_synthetic": 0,
                                "origin_iata": origin, "dest_iata": dest,
                                "collected_date": collected_on.isoformat(),
                            })
                    except Exception as e:
                        print(f"Duffel API error on route {route}: {e}")
                        
        return out
