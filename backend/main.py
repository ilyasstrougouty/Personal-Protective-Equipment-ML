from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from ultralytics import YOLO
from PIL import Image
import io
import cv2
import numpy as np

app = FastAPI()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize YOLO model
import os
# Base directory is the parent of the backend directory
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
model_path = os.path.join(base_dir, "models", "best.pt")
model = YOLO(model_path)

# Global Detection State
class DetectionState:
    def __init__(self):
        self.consecutive_violations = 100 # Start in strict mode (no free pass on startup)
        self.grace_period_limit = 8 # Number of frames to ignore violations after a safe frame

state = DetectionState()

@app.post("/detect")
async def detect(file: UploadFile = File(...)):
    # Read image file
    contents = await file.read()
    image = Image.open(io.BytesIO(contents))
    
    # Run inference
    results = model(image, conf=0.25)
    
    # Generate debug image with boxes
    plotted_image = results[0].plot() # numpy array (BGR)
    
    # Convert to base64
    import base64
    is_success, buffer = cv2.imencode(".jpg", plotted_image)
    encoded_img = base64.b64encode(buffer).decode('utf-8')

    # Process results
    detected_classes = []
    person_detected = False
    hardhat_detected = False
    vest_detected = False
    
    for result in results:
        for box in result.boxes:
            cls_id = int(box.cls[0])
            cls_name = model.names[cls_id]
            detected_classes.append(cls_name)
            
            if cls_name == "Person":
                person_detected = True
            elif cls_name == "Hardhat":
                hardhat_detected = True
            elif cls_name == "Safety Vest":
                vest_detected = True

    print(f"DEBUG: Detected: {detected_classes}") # Debug logging

    # Violation Check logic
    current_violations = []
    
    # Check for explicit violation classes
    for cls in detected_classes:
        if cls in ["NO-Hardhat", "NO-Safety Vest"]:
            current_violations.append(cls)
            
    # Strict Mode Check
    if person_detected:
        if not hardhat_detected:
            current_violations.append("Missing Hardhat")
        if not vest_detected:
            current_violations.append("Missing Safety Vest")
            
    # Remove duplicates
    current_violations = list(set(current_violations))

    # Smoothing / Grace Period Logic
    final_violations = []
    
    if not current_violations:
        # No violations found in this frame
        if person_detected:
            # Active confirmation of safety: Reset counter
            state.consecutive_violations = 0
            final_violations = []
        else:
            # No person detected (empty room or flicker)
            # Do NOT reset the counter. Maintain state.
            # But return SAFE for this frame since nobody is there.
            final_violations = []
    else:
        # Violation detected
        state.consecutive_violations += 1
        
        if state.consecutive_violations <= state.grace_period_limit:
            # We are within the grace period.
            # Mask the violation (return empty list)
            # This handles the "flickering" where vest disappears for a second
            print(f"DEBUG: Masking violation (Grace Period {state.consecutive_violations}/{state.grace_period_limit})")
            final_violations = []
        else:
            # Grace period detected or exceeded
            final_violations = current_violations

    response = {
        "items": final_violations,
        "debug_image": encoded_img
    }

    if final_violations:
        response["status"] = "VIOLATION"
        response["color"] = "red"
    else:
        response["status"] = "SAFE"
        response["color"] = "green"
        
    return response

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
