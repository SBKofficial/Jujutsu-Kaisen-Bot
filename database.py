import os
import asyncio
import certifi
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from bson import ObjectId

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/jjk_bot')

class CollectionWrapper:
    def __init__(self, collection, name=None):
        self.collection = collection
        self.name = name

    def _fix_query(self, query):
        if not query: return {}
        # Convert _id string to ObjectId if possible
        if '_id' in query:
            if isinstance(query['_id'], str):
                try:
                    query['_id'] = ObjectId(query['_id'])
                except Exception:
                    pass
            elif isinstance(query['_id'], dict):
                # Handle operators like $in
                for k, v in query['_id'].items():
                    if k in ['$in', '$nin', '$all'] and isinstance(v, list):
                        new_list = []
                        for item in v:
                            if isinstance(item, str):
                                try:
                                    new_list.append(ObjectId(item))
                                except Exception:
                                    new_list.append(item)
                            else:
                                new_list.append(item)
                        query['_id'][k] = new_list
        return query

    async def _invalidate_cache(self, query):
        if self.name == 'users':
            try:
                from services.cache_service import cache_service
                tid = query.get('telegramId')
                if tid:
                    cache_service.invalidate(tid)
                elif '_id' in query:
                    # If only _id is present, we might need to find the user to get telegramId
                    # but for performance we'll just skip or handle common cases
                    pass
            except Exception:
                pass

    async def find(self, query=None):
        query = self._fix_query(query)
        cursor = self.collection.find(query)
        return await cursor.to_list(length=None)

    async def find_one(self, query=None):
        query = self._fix_query(query)
        return await self.collection.find_one(query)

    async def update(self, query, update, multi=False, upsert=False):
        query = self._fix_query(query)
        await self._invalidate_cache(query)
        if multi:
            res = await self.collection.update_many(query, update, upsert=upsert)
        else:
            res = await self.collection.update_one(query, update, upsert=upsert)
        return res.modified_count or res.upserted_id or 0

    async def insert(self, doc):
        if isinstance(doc, list):
            res = await self.collection.insert_many(doc)
            return doc
        res = await self.collection.insert_one(doc)
        doc['_id'] = res.inserted_id
        return doc

    async def remove(self, query, multi=False):
        query = self._fix_query(query)
        await self._invalidate_cache(query)
        if multi:
            return await self.collection.delete_many(query)
        return await self.collection.delete_one(query)

    async def count(self, query=None):
        if query is None:
            query = {}
        return await self.collection.count_documents(query)

    async def ensure_index(self, field_name, unique=False):
        return await self.collection.create_index([(field_name, 1)], unique=unique)

class Database:
    def __init__(self):
        self.client = None
        self._db = None
        self._collections = {}

    async def connect(self):
        print(f"Attempting connection to: {MONGO_URI.split('@')[-1] if '@' in MONGO_URI else MONGO_URI}")

        # Use certifi to provide the missing SSL certificates to MongoDB Atlas
        self.client = AsyncIOMotorClient(
            MONGO_URI, 
            tlsCAFile=certifi.where()
        )

        # Use jjk_bot as the default database
        self._db = self.client.get_database("jjk_bot")
        print('MongoDB Connected Successfully')

        # Ensure indexes
        await self._db.users.create_index("telegramId", unique=True)

    def __getattr__(self, name):
        if name in ['connect', 'client', '_db', '_collections']:
            return super().__getattribute__(name)

        if self._db is None:
            raise Exception("Database not connected. Call db.connect() first.")

        if name not in self._collections:
            self._collections[name] = CollectionWrapper(self._db[name], name)
        return self._collections[name]

db = Database()

