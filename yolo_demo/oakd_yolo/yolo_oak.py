from ultralytics import YOLO
import cv2

model = YOLO("yolov8n.pt")

cap = cv2.VideoCapture(0)

while True:
    ret, frame = cap.read()
    if not ret:
        break

    results = model(frame, verbose=False)[0]

    # check for person
    person_detected = False

    for box in results.boxes:
        cls = int(box.cls[0])
        name = model.names[cls]

        if name == "person":
            person_detected = True

    if person_detected:
        print("🛑 BRAKE (person detected)")
    else:
        print("🟢 safe")

    cv2.imshow("YOLO", results.plot())

    if cv2.waitKey(1) == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()
