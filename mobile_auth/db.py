from pymongo import MongoClient
import os

MONGODB_URI = os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "entephoto-db")

client = MongoClient(MONGODB_URI)
db = client[MONGO_DB_NAME]

users_collection = db["users"]
folders_collection = db["folders"]
events_collection = db["events"]