import requests

# Paste your actual session token here
TECHPORT_TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJUZWNoUG9ydCIsImV4cCI6MTc4MTgxNjkyMCwibmJmIjoxNzgxNzMwNTIwLCJTRVNTSU9OX0lEIjoicGJaT0dSS2VqUk5oWkt4SGZxcXBUZkJkS3F1dmc5SGZiYTBVIiwiRklOR0VSUFJJTlRfSEFTSCI6IkMwRjZEOUY3QjlCQ0ZEQTVGN0IyQTc0MkVFMkFGQ0JEMkI3NTJFNzUwQzNCQTQ5RDY4REJFMDBEOUQ2NDY3RDMifQ.w85FgqtqEwCmwf65laswOIhhHKiOTtEl3Hdveack260"
project_id = "95917"

# Clean target URL pointing to techport.nasa.gov
url = f"https://nasa.gov/{project_id}"

headers = {
    "Authorization": f"Bearer {TECHPORT_TOKEN}"
}

print(f"DEBUG: Executing request to: {url}")

try:
    response = requests.get(url, headers=headers)
    print(f"DEBUG: Status Code Received: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        print(f"\nSuccess! Project Title: {data['project']['title']}")
    else:
        print(f"Server Message: {response.text}")
except Exception as e:
    print(f"Network error occurred: {e}")
