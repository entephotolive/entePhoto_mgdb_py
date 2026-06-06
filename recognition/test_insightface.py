# test_insightface.py

from insightface.app import FaceAnalysis
import cv2

app = FaceAnalysis(name="buffalo_l")
app.prepare(ctx_id=0)

img = cv2.imread("test.jpg")

faces = app.get(img)

print("Faces:", len(faces))

for face in faces:
    print(face.embedding.shape)