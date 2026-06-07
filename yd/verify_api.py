import urllib.request
import json

url = "http://127.0.0.1:5000/api/info"
data = json.dumps({"url": "https://www.youtube.com/watch?v=vjj0-Rbq5xc"}).encode("utf-8") # The failing music video
req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")

try:
    with urllib.request.urlopen(req) as response:
        print(f"STATUS: {response.getcode()}")
        info = json.loads(response.read().decode("utf-8"))
        print(f"TITLE: {info.get('title')}")
        resolutions = info.get("resolutions", [])
        print("AVAILABLE RESOLUTIONS:")
        for r in resolutions:
            print(f" - {r['label']} ({r['note']})")
except Exception as e:
    print(f"FAILED: {e}")
