import gradio as gr
import requests

API_URL = "http://localhost:5000/api/trucklist"  # Replace with your actual API URL

def get_truck_list():
    try:
        response = requests.get(API_URL)
        if response.status_cosde == 200:
            data = response.json()
            print(data)
            if data['status'] == '0':
                trucks = data['result']
                formatted_trucks = "\n".join([f"Name: {truck['name']}, Model: {truck['model']}, Number: {truck['number']}, Track Lifespan: {truck['track_lifespan']}, Crane Lifespan: {truck['crane_lifespan']}" for truck in trucks])
                return formatted_trucks
            else:
                return f"Error: {data['result']}"
        else:
            return f"Error: Unable to fetch data (Status Code: {response.status_code})"
    except Exception as e:
        return f"Error: {str(e)}"

iface = gr.Interface(fn=get_truck_list, inputs=[], outputs="text", live=True)

if __name__ == "__main__":
    iface.launch()
