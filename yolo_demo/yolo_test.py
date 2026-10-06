from ultralytics import YOLO

model = YOLO("yolov8n.pt")

results = model("bus.jpg", save=True)

print("Saved to runs/detect/")
