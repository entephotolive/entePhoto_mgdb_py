

import numpy as np
import face_recognition

def match_faces(known_encodings, test_encoding):
    known = [np.frombuffer(enc, dtype=np.float64) for enc in known_encodings]
    results = face_recognition.compare_faces(known, test_encoding, tolerance=0.5)
    return results