"""
Webcam Client for Railway Server Testing
Simulates ESP32-CAM but uses your computer's webcam

This sends images to YOUR Railway server for processing
"""

import cv2
import requests
import base64
import time
from datetime import datetime
import json

# ============= CONFIGURATION =============
# Your Railway server URL (get this after deploying)
RAILWAY_SERVER_URL = "https://your-app.railway.app"  # CHANGE THIS

# Customer ID for testing
CUSTOMER_ID = "test_customer"

# Motion simulation (manual or auto)
AUTO_SCAN = True  # True = auto scan every few seconds, False = manual with spacebar
SCAN_INTERVAL = 3  # seconds

# =========================================

class WebcamClient:
    def __init__(self, server_url, customer_id):
        self.server_url = server_url.rstrip('/')
        self.customer_id = customer_id
        self.last_scan_time = 0
        
        print("\n" + "="*60)
        print("WEBCAM → RAILWAY SERVER TEST CLIENT")
        print("="*60)
        print(f"Server URL: {self.server_url}")
        print(f"Customer ID: {self.customer_id}")
        print(f"Mode: {'Auto-scan' if AUTO_SCAN else 'Manual'}")
        if AUTO_SCAN:
            print(f"Scan interval: {SCAN_INTERVAL} seconds")
        else:
            print("Press SPACE to scan, 'q' to quit")
        print("="*60)
        
        # Test server connection
        self.test_connection()
    
    def test_connection(self):
        """Test if server is reachable"""
        print("\nTesting server connection...")
        try:
            response = requests.get(f"{self.server_url}/health", timeout=5)
            if response.status_code == 200:
                print("✓ Server is online and responding")
                data = response.json()
                print(f"  Status: {data.get('status')}")
                print(f"  Timestamp: {data.get('timestamp')}")
            else:
                print(f"✗ Server responded with status {response.status_code}")
        except Exception as e:
            print(f"✗ Cannot connect to server: {e}")
            print("\nMake sure:")
            print("1. You've deployed to Railway")
            print("2. Updated RAILWAY_SERVER_URL in this script")
            print("3. Server is running (check Railway dashboard)")
            return False
        
        return True
    
    def capture_and_encode(self, frame):
        """Capture frame and encode to base64 (like ESP32-CAM does)"""
        # Encode frame to JPEG
        _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        
        # Convert to base64
        image_b64 = base64.b64encode(buffer).decode('utf-8')
        
        return image_b64, len(buffer)
    
    def send_to_server(self, image_b64, image_size):
        """Send image to Railway server for processing"""
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Sending to server...")
        print(f"  Image size: {image_size:,} bytes")
        
        try:
            # Prepare payload (exactly like ESP32-CAM)
            payload = {
                "image": image_b64,
                "customer_id": self.customer_id
            }
            
            # Send POST request
            response = requests.post(
                f"{self.server_url}/detect",
                json=payload,
                timeout=15  # Plate API can take 5-10 seconds
            )
            
            if response.status_code == 200:
                result = response.json()
                self.display_result(result)
                return result
            else:
                print(f"  ✗ Server error: {response.status_code}")
                print(f"     {response.text}")
                return None
                
        except requests.Timeout:
            print("  ✗ Request timed out (server might be processing)")
        except Exception as e:
            print(f"  ✗ Error: {e}")
        
        return None
    
    def display_result(self, result):
        """Display server response"""
        status = result.get('status')
        detected = result.get('detected_plates', [])
        gate_triggered = result.get('gate_triggered', False)
        matched_plate = result.get('matched_plate')
        
        print(f"  ✓ Server processed successfully")
        
        if detected:
            print(f"  Detected {len(detected)} plate(s):")
            for plate_data in detected:
                plate = plate_data.get('plate')
                conf = plate_data.get('confidence', 0)
                print(f"    - {plate} (confidence: {conf:.2f})")
        else:
            print("  No plates detected")
        
        if gate_triggered:
            print("\n" + "="*60)
            print(f"🚪🚪🚪 GATE TRIGGERED FOR: {matched_plate} 🚪🚪🚪")
            print("="*60)
            print("(Server sent webhook to customer's hub)")
        else:
            if detected:
                print("  → Gate NOT triggered (plate not authorized)")
    
    def run_manual(self):
        """Manual mode - press space to scan"""
        cap = cv2.VideoCapture(0)
        
        if not cap.isOpened():
            print("Error: Cannot open webcam")
            return
        
        print("\nWebcam opened. Press SPACE to scan, 'q' to quit\n")
        
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            # Display live feed
            cv2.imshow('Webcam Feed - Press SPACE to scan', frame)
            
            key = cv2.waitKey(1) & 0xFF
            
            if key == ord(' '):
                # Capture and send
                image_b64, size = self.capture_and_encode(frame)
                self.send_to_server(image_b64, size)
            
            elif key == ord('q'):
                break
        
        cap.release()
        cv2.destroyAllWindows()
    
    def run_auto(self):
        """Auto mode - scan at intervals"""
        cap = cv2.VideoCapture(0)
        
        if not cap.isOpened():
            print("Error: Cannot open webcam")
            return
        
        print(f"\nWebcam opened. Auto-scanning every {SCAN_INTERVAL} seconds. Press 'q' to quit\n")
        
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            current_time = time.time()
            
            # Display live feed
            cv2.imshow('Webcam Feed - Auto Scanning', frame)
            
            # Auto-scan at interval
            if current_time - self.last_scan_time >= SCAN_INTERVAL:
                self.last_scan_time = current_time
                
                # Capture and send
                image_b64, size = self.capture_and_encode(frame)
                self.send_to_server(image_b64, size)
            
            # Check for quit
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
        
        cap.release()
        cv2.destroyAllWindows()
    
    def run(self):
        """Start the client"""
        if AUTO_SCAN:
            self.run_auto()
        else:
            self.run_manual()

def test_server_endpoints(server_url):
    """Test all server endpoints before starting"""
    print("\n" + "="*60)
    print("TESTING SERVER ENDPOINTS")
    print("="*60)
    
    # Test health
    print("\n1. Testing /health endpoint...")
    try:
        response = requests.get(f"{server_url}/health")
        print(f"   Status: {response.status_code}")
        print(f"   Response: {response.json()}")
    except Exception as e:
        print(f"   Error: {e}")
    
    # Test home
    print("\n2. Testing / endpoint...")
    try:
        response = requests.get(server_url)
        print(f"   Status: {response.status_code}")
        data = response.json()
        print(f"   Service: {data.get('service')}")
        print(f"   Customers: {data.get('customers')}")
    except Exception as e:
        print(f"   Error: {e}")
    
    # Test list customers
    print("\n3. Testing /list_customers endpoint...")
    try:
        response = requests.get(f"{server_url}/list_customers")
        print(f"   Status: {response.status_code}")
        data = response.json()
        print(f"   Total customers: {data.get('total_customers')}")
        for customer in data.get('customers', []):
            print(f"   - {customer['customer_id']}: {customer['plate_count']} plates")
    except Exception as e:
        print(f"   Error: {e}")
    
    print("\n" + "="*60)
    input("Press ENTER to start webcam client...")

def main():
    # Check configuration
    if RAILWAY_SERVER_URL == "https://your-app.railway.app":
        print("\n" + "!"*60)
        print("ERROR: Please update RAILWAY_SERVER_URL!")
        print("!"*60)
        print("\nSteps:")
        print("1. Deploy server.py to Railway")
        print("2. Get your Railway URL (e.g., https://gate-automation-production.up.railway.app)")
        print("3. Update RAILWAY_SERVER_URL in this script")
        print("4. Make sure PLATE_API_TOKEN is set in Railway environment variables")
        print()
        return
    
    # Test server first
    test_server_endpoints(RAILWAY_SERVER_URL)
    
    # Start client
    client = WebcamClient(RAILWAY_SERVER_URL, CUSTOMER_ID)
    client.run()

if __name__ == "__main__":
    main()
