"""
Gate Automation Cloud Server
Runs on Railway - handles plate recognition for all customers
"""

from flask import Flask, request, jsonify
import requests
import base64
from datetime import datetime
import os
import json
import time
import re

app = Flask(__name__)

# Environment variables
PLATE_RECOGNIZER_TOKEN = os.getenv('PLATE_API_TOKEN', '')

# In-memory customer database
customers = {}

def init_customers():
    global customers
    
    customers_json = os.getenv('CUSTOMERS_CONFIG', '')
    if customers_json:
        try:
            customers = json.loads(customers_json)
            print(f"Loaded {len(customers)} customers from config")
            return
        except Exception as e:
            print("Error parsing CUSTOMERS_CONFIG:", e)
    
    customers['test_customer'] = {
        'webhook_url': 'https://webhook.site/test',
        'authorized_plates': ['KL07AB1234', 'KL07CD5678','KL21S8086'],
        'cooldown_seconds': 10,
        'cooldown_end': 0,
        'created_at': datetime.now().isoformat()
    }
    print("Initialized with test_customer")

init_customers()

def clean_plate(text):
    return re.sub(r'[^A-Z0-9]', '', str(text).upper())

def fuzzy_match(detected, authorized):
    detected = clean_plate(detected)
    authorized = clean_plate(authorized)
    
    if detected == authorized:
        return True, 100
    
    if len(detected) >= 6 and detected in authorized:
        return True, 80
    
    if len(authorized) >= 6 and authorized in detected:
        return True, 80
    
    if len(detected) > 0 and len(authorized) > 0:
        matches = sum(1 for a, b in zip(detected, authorized) if a == b)
        similarity = (matches / max(len(detected), len(authorized))) * 100
        if similarity >= 70:
            return True, similarity
    
    return False, 0

def is_authorized(customer_id, detected_plate):
    if customer_id not in customers:
        return False, None, 0
    
    for auth_plate in customers[customer_id].get('authorized_plates', []):
        ok, conf = fuzzy_match(detected_plate, auth_plate)
        if ok:
            return True, auth_plate, conf
    return False, None, 0

def can_open_gate(customer_id):
    current_time = time.time()
    return current_time > customers[customer_id].get('cooldown_end', 0)

def trigger_gate(customer_id, plate):
    webhook_url = customers[customer_id].get('webhook_url')
    if not webhook_url:
        print(f"No webhook set for {customer_id}")
        return False
    
    try:
        response = requests.post(
            webhook_url,
            json={'plate': plate, 'timestamp': datetime.now().isoformat(), 'customer_id': customer_id},
            timeout=5
        )
        customers[customer_id]['cooldown_end'] = time.time() + customers[customer_id].get('cooldown_seconds', 10)
        return response.status_code in [200, 201, 204]
    except Exception as e:
        print(f"Error triggering gate for {customer_id}: {e}")
        return False

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})

@app.route('/detect', methods=['POST'])
def detect_plate():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No JSON data'}), 400
        
        image_b64 = data.get('image')
        customer_id = data.get('customer_id')

        if not image_b64:
            return jsonify({'error': 'No image provided'}), 400
        
        if not customer_id:
            return jsonify({'error': 'No customer_id provided'}), 400
        
        if customer_id not in customers:
            return jsonify({'error': 'Unknown customer_id'}), 404
        
        if not PLATE_RECOGNIZER_TOKEN:
            return jsonify({'error': 'Server missing PLATE_API_TOKEN'}), 500
        
        # Accept browser webcam format
        if image_b64.startswith("data:image"):
            image_b64 = image_b64.split(",")[1]

        try:
            image_bytes = base64.b64decode(image_b64)
        except Exception:
            return jsonify({'error': 'Base64 decode failed'}), 400
        
        print(f"[{customer_id}] Image received -> {len(image_bytes)} bytes")

        try:
            response = requests.post(
                'https://api.platerecognizer.com/v1/plate-reader/',
                headers={'Authorization': f'Token {PLATE_RECOGNIZER_TOKEN}'},
                files={'upload': ('frame.jpg', image_bytes, 'image/jpeg')},
                timeout=15
            )
        except requests.Timeout:
            return jsonify({'error': 'Plate API timeout'}), 504
        except Exception as e:
            return jsonify({'error': f'Plate API error: {str(e)}'}), 500
        
        if response.status_code not in [200, 201]:
            return jsonify({
                'error': 'Plate recognition failed',
                'api_status': response.status_code,
                'api_response': response.text
            }), 500
        
        api_result = response.json()
        detected_plates = []
        gate_triggered = False
        matched_plate = None
        
        for result in api_result.get('results', []):
            plate = result.get('plate', '')
            confidence = result.get('score', 0)
            detected_plates.append({'plate': plate, 'confidence': confidence})
            
            authorized, auth_plate, _ = is_authorized(customer_id, plate)
            if authorized and can_open_gate(customer_id) and not gate_triggered:
                success = trigger_gate(customer_id, auth_plate)
                gate_triggered = success
                matched_plate = auth_plate
                print(f"[{customer_id}] Gate opened for {auth_plate}")

        return jsonify({
            'status': 'success',
            'customer_id': customer_id,
            'timestamp': datetime.now().isoformat(),
            'detected_plates': detected_plates,
            'gate_triggered': gate_triggered,
            'matched_plate': matched_plate
        })

    except Exception as e:
        print("Error in /detect:", e)
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
