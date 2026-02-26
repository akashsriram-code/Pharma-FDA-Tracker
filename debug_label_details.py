import requests
import json

def get_label_details(brand_name):
    url = f"https://api.fda.gov/drug/label.json?search=openfda.brand_name:\"{brand_name}\"&limit=1"
    try:
        response = requests.get(url, verify=False)
        data = response.json()
        if 'results' in data:
            result = data['results'][0]
            if 'recent_major_changes' in result:
                print(f"\n--- Recent Major Changes for {brand_name} ---")
                print(json.dumps(result['recent_major_changes'], indent=2))
            else:
                print(f"\nNo recent_major_changes found for {brand_name}")
                
            # Also check if we can find the actual text for these sections
            print(f"\n--- Top Level Keys ---")
            print(result.keys())
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    import urllib3
    urllib3.disable_warnings() 
    get_label_details("Eylea")
    get_label_details("Keytruda")
