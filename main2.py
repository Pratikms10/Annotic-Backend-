import requests
import json

TOKEN = "JWT eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwiZXhwIoxNzgyODg2NTM3LCJqdGkiOiJjMjhmZjM3ODBiY2U0YzdlOTA2ZmVmN2EyMmY1ZjEwZiIsInVzZXJfaWQiOjI2MDh9._Niwm9MswKy90lt3PD8h-KYCt8VQyJnpoIDSVKYBhrc"
TASK_ID = 105008

r = requests.get(
    f"https://backend.annotic.in/task/105008/annotations/?enable_chitralekha_UI=true",
    headers={
        "Authorization": TOKEN,
        "Accept": "application/json",
        "Origin": "https://annotic.in",
        "Referer": "https://annotic.in/",
    }
)

print(r.status_code)
print(json.dumps(r.json(), indent=2))
