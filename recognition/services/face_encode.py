

import face_recognition
import numpy as np





def encode_faces(image_path):
    """
    Returns all face encodings in an image
    """
    image = face_recognition.load_image_file(image_path)

    face_locations = face_recognition.face_locations(image)
    encodings = face_recognition.face_encodings(image, face_locations)

    return encodings