from ultralytics import YOLO
import os

model_path = os.path.join("models", "best.pt")
model = YOLO(model_path)
print("Model Classes:", model.names)
