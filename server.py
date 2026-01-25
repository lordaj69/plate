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
# In production, use a real database (PostgreSQL, MongoDB, etc.)
customers = {}

def init_customers():
    """Initialize with test customer"""
    global customers
    
    # Load from environment if available
    customers_json = os.getenv('CUSTOMERS_CONFIG', '')
    if customers_json:
        try:
            customers = json.loads(customers_json)
            print(f"Loaded {len(customers)} customers from config")
            return
        except:
            pass
    
    # Default test customer
    customers['test_customer'] = {
        'webhook_url': 'https://webhook.site/test',  # Use webhook.site for testing
        'authorized_plates': ['KL07AB1234', 'KL07CD5678'],
        'cooldown_seconds': 10,
        'cooldown_end': 0,
        'created_at': datetime.now().isoformat()
    }
    print("Initialized with test customer")

# Initialize on startup
init_customers()

def clean_plate(text):
    """Remove spaces and special characters"""
    return re.sub(r'[^A-Z0-9]', '', str(text).upper())

def fuzzy_match(detected, authorized):
    """Check if plates match with tolerance for OCR errors"""
    detected = clean_plate(detected)
    authorized = clean_plate(authorized)
    
    # Exact match
    if detected == authorized:
        return True, 100
    
    # Partial match
    if len(detected) >= 6 and detected in authorized:
        return True, 80
    
    if len(authorized) >= 6 and authorized in detected:
        return True, 80
    
    # Similarity match
    if len(detected) > 0 and len(authorized) > 0:
        matches = sum(1 for a, b in zip(detected, authorized) if a == b)
        similarity = (matches / max(len(detected), len(authorized))) * 100
        if similarity >= 70:
            return True, similarity
    
    return False, 0

def is_authorized(customer_id, detected_plate):
    """Check if plate is authorized for customer"""
    if customer_id not in customers:
        return False, None, 0
    
    authorized_plates = customers[customer_id].get('authorized_plates', [])
    
    for auth_plate in authorized_plates:
        is_match, confidence = fuzzy_match(detected_plate, auth_plate)
        if is_match:
            return True, auth_plate, confidence
    
    return False, None, 0

def can_open_gate(customer_id):
    """Check if cooldown period has passed"""
    if customer_id not in customers:
        return False
    
    current_time = time.time()
    cooldown_end = customers[customer_id].get('cooldown_end', 0)
    
    return current_time > cooldown_end

def trigger_gate(customer_id, plate):
    """Send webhook to customer's hub"""
    if customer_id not in customers:
        return False
    
    webhook_url = customers[customer_id].get('webhook_url')
    if not webhook_url:
        return False
    
    try:
        response = requests.post(
            webhook_url,
            json={
                'plate': plate,
                'timestamp': datetime.now().isoformat(),
                'customer_id': customer_id
            },
            timeout=5
        )
        
        # Set cooldown
        cooldown_seconds = customers[customer_id].get('cooldown_seconds', 10)
        customers[customer_id]['cooldown_end'] = time.time() + cooldown_seconds
        
        return response.status_code in [200, 201, 204]
    except Exception as e:
        print(f"Error triggering gate for {customer_id}: {e}")
        return False

@app.route('/', methods=['GET'])
def home():
    """API info page"""
    return jsonify({
        'service': 'Gate Automation Cloud Server',
        'status': 'running',
        'timestamp': datetime.now().isoformat(),
        'customers': len(customers),
        'endpoints': {
            '/': 'GET - This info page',
            '/health': 'GET - Health check',
            '/detect': 'POST - Detect plate and trigger gate',
            '/add_customer': 'POST - Add new customer',
            '/list_customers': 'GET - List all customers'
        }
    })

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat()
    })

@app.route('/detect', methods=['POST'])
def detect_plate():
    """
    Main endpoint - receives image from ESP32-CAM or webcam
    
    POST JSON:
    {
        "image": "base64_encoded_jpeg",
        "customer_id": "customer_abc123"
    }
    """
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
        
        # Check API token
        if not PLATE_RECOGNIZER_TOKEN:
            return jsonify({'error': 'Server not configured - missing API token'}), 500
        
        # Decode base64 image
        try:
            image_bytes = base64.b64decode(image_b64)
        except Exception as e:
            return jsonify({'error': f'Invalid base64 image: {str(e)}'}), 400
        
        print(f"[{customer_id}] Processing image ({len(image_bytes)} bytes)")
        
        # Call Plate Recognizer API
        try:
            response = requests.post(
                'https://api.platerecognizer.com/v1/plate-reader/',
                headers={'Authorization': f'Token {PLATE_RECOGNIZER_TOKEN}'},
                files={'upload': image_bytes},
                timeout=15
            )
        except requests.Timeout:
            return jsonify({'error': 'Plate API timeout'}), 504
        except Exception as e:
            return jsonify({'error': f'Plate API error: {str(e)}'}), 500
        
        if response.status_code != 201:
            return jsonify({
                'error': 'Plate recognition failed',
                'api_status': response.status_code,
                'api_response': response.text
            }), 500
        
        api_result = response.json()
        detected_plates = []
        gate_triggered = False
        matched_plate = None
        
        # Process detected plates
        for result in api_result.get('results', []):
            plate = result.get('plate', '')
            confidence = result.get('score', 0)
            
            detected_plates.append({
                'plate': plate,
                'confidence': confidence
            })
            
            # Check authorization
            is_auth, auth_plate, match_conf = is_authorized(customer_id, plate)
            
            if is_auth and can_open_gate(customer_id) and not gate_triggered:
                # Trigger gate
                success = trigger_gate(customer_id, auth_plate)
                
                if success:
                    gate_triggered = True
                    matched_plate = auth_plate
                    print(f"[{customer_id}] ✓ Gate triggered for {auth_plate}")
        
        return jsonify({
            'status': 'success',
            'customer_id': customer_id,
            'timestamp': datetime.now().isoformat(),
            'detected_plates': detected_plates,
            'gate_triggered': gate_triggered,
            'matched_plate': matched_plate
        })
        
    except Exception as e:
        print(f"Error in /detect: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/add_customer', methods=['POST'])
def add_customer():
    """
    Add new customer
    
    POST JSON:
    {
        "customer_id": "customer_abc123",
        "webhook_url": "http://192.168.1.100:8123/api/webhook/gate",
        "authorized_plates": ["KL07AB1234"],
        "cooldown_seconds": 10
    }
    """
    try:
        data = request.get_json()
        
        customer_id = data.get('customer_id')
        webhook_url = data.get('webhook_url')
        authorized_plates = data.get('authorized_plates', [])
        cooldown_seconds = data.get('cooldown_seconds', 10)
        
        if not customer_id or not webhook_url:
            return jsonify({'error': 'customer_id and webhook_url required'}), 400
        
        customers[customer_id] = {
            'webhook_url': webhook_url,
            'authorized_plates': authorized_plates,
            'cooldown_seconds': cooldown_seconds,
            'cooldown_end': 0,
            'created_at': datetime.now().isoformat()
        }
        
        print(f"Added customer: {customer_id}")
        
        return jsonify({
            'status': 'success',
            'customer_id': customer_id,
            'message': 'Customer added successfully'
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/list_customers', methods=['GET'])
def list_customers():
    """List all customers (without sensitive data)"""
    customer_list = []
    for cid, data in customers.items():
        customer_list.append({
            'customer_id': cid,
            'plate_count': len(data.get('authorized_plates', [])),
            'created_at': data.get('created_at', 'unknown')
        })
    
    return jsonify({
        'total_customers': len(customers),
        'customers': customer_list
    })

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
