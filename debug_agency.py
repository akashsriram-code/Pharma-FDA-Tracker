import requests

def get_agency_info(slug):
    url = f"https://www.federalregister.gov/api/v1/agencies/{slug}"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        print(f"Agency: {data.get('name')}")
        print(f"ID: {data.get('id')}")
        print(f"Parent ID: {data.get('parent_id')}")
    except Exception as e:
        print(f"Error: {e}")

print("Checking 'food-and-drug-administration'...")
get_agency_info('food-and-drug-administration')

print("\nChecking ID 193...")
# There is no direct ID lookup endpoint easily documented, but let's see if 224 is FDA
