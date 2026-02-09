import requests
import json
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def get_label(brand_name):
    url = f"https://api.fda.gov/drug/label.json?search=openfda.brand_name:{brand_name}&limit=1"
    try:
        response = requests.get(url, timeout=15, verify=False)
        data = response.json()
        
        if 'results' in data and data['results']:
            result = data['results'][0]
            print(f"--- Label for {brand_name} ---")
            print(f"Effective Time: {result.get('effective_time', 'N/A')}")
            print(f"Set ID: {result.get('set_id', 'N/A')}")
            print(f"OpenFDA: {result.get('openfda', {}).keys()}")
            
            if 'openfda' in result:
                print(f"SPL Set ID: {result['openfda'].get('spl_set_id', 'N/A')}")
            
            if 'recent_major_changes' in result:
                print("\n[Recent Major Changes Found]")
                changes = result['recent_major_changes']
                if isinstance(changes, list):
                    for change in changes:
                        print(f"  - {change}")
                else:
                    print(f"  - {changes}")
            else:
                print("\n[No Recent Major Changes Section]")
                
            if 'boxed_warning' in result:
                print("\n[Boxed Warning Found]")
                warning = result['boxed_warning']
                if isinstance(warning, list):
                    print(f"  {warning[0][:200]}...")
                else:
                    print(f"  {str(warning)[:200]}...")
            
    except Exception as e:
        print(f"Error: {e}")

print("Checking Keytruda...")
get_label('Keytruda')

print("\nChecking Humira...")
get_label('Humira')
