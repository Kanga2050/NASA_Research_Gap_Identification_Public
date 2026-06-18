import requests

# Paste your actual session token here
TECHPORT_TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJUZWNoUG9ydCIsImV4cCI6MTc4MTgxNjkyMCwibmJmIjoxNzgxNzMwNTIwLCJTRVNTSU9OX0lEIjoicGJaT0dSS2VqUk5oWkt4SGZxcXBUZkJkS3F1dmc5SGZiYTBVIiwiRklOR0VSUFJJTlRfSEFTSCI6IkMwRjZEOUY3QjlCQ0ZEQTVGN0IyQTc0MkVFMkFGQ0JEMkI3NTJFNzUwQzNCQTQ5RDY4REJFMDBEOUQ2NDY3RDMifQ.w85FgqtqEwCmwf65laswOIhhHKiOTtEl3Hdveack260"
project_id = "4780"

# Correct TechPort API endpoint
url = f"https://techport.nasa.gov/api/projects/{project_id}"

headers = {
    "Authorization": f"{TECHPORT_TOKEN}"
}

print(f"DEBUG: Executing request to: {url}")

try:
    response = requests.get(url, headers=headers)
    print(f"DEBUG: Status Code Received: {response.status_code}")
    
    if response.status_code != 200:
        print(f"Server Message: {response.text}")
        exit()

    data = response.json()
    project = data.get("project", {})
    print(f"\nSuccess! Project Title: {project.get('title')}")

    # Locate attached PDFs inside "projectDocuments"
    documents = project.get("projectDocuments", [])

    if not documents:
        print("\nNo documents found in this project.")
        exit()

    print("\nAvailable PDF Documents:")
    pdf_docs = [doc for doc in documents if doc.get("documentType") == "pdf"]

    if not pdf_docs:
        print("No PDF files found.")
        exit()

    for i, doc in enumerate(pdf_docs):
        print(f"{i+1}. {doc.get('title')}")

    # Prompt user for which PDF to download
    choice = input("\nEnter the number of the PDF you want to download (or 'all'): ").strip()

    if choice.lower() == "all":
        to_download = pdf_docs
    else:
        idx = int(choice) - 1
        to_download = [pdf_docs[idx]]

    print("\nDownloading selected PDF(s)...")

    for doc in to_download:
        url = doc.get("url")
        filename = doc.get("title").replace(" ", "_") + ".pdf"

        print(f"Downloading {filename} from {url} ...")
        pdf_response = requests.get(url)

        if pdf_response.status_code == 200:
            with open(filename, "wb") as f:
                f.write(pdf_response.content)
            print(f"Saved: {filename}")
        else:
            print(f"Failed to download {filename}: status {pdf_response.status_code}")

except Exception as e:
    print(f"Network error occurred: {e}")