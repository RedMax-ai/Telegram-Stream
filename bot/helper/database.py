import re
import os
import asyncio
import logging
from typing import List, Dict, Any, Optional
from pathlib import Path
from bot.config import Telegram

LOGGER = logging.getLogger(__name__)

# Check for MongoDB vs SQLite
USE_MONGO = bool(Telegram.DATABASE_URL and ("mongodb://" in Telegram.DATABASE_URL or "mongodb+srv://" in Telegram.DATABASE_URL))

if USE_MONGO:
    try:
        from motor.motor_asyncio import AsyncIOMotorClient
        from pymongo import DESCENDING
        from bson import ObjectId
    except ImportError:
        USE_MONGO = False


class SQLiteBackend:
    """
    ACID-compliant, high-performance SQLite backend.
    Uses parameterized SQL queries for complete injection security.
    """
    def __init__(self, db_path: Optional[str] = None):
        if not db_path:
            self.db_path = str(Path(__file__).resolve().parent.parent.parent / "surftg.db")
        else:
            self.db_path = db_path
        self._lock = asyncio.Lock()
        self._init_db()

    def _init_db(self):
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Files collection
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS files (
                chat_id TEXT NOT NULL,
                msg_id INTEGER NOT NULL,
                hash TEXT NOT NULL,
                title TEXT,
                size TEXT,
                type TEXT,
                PRIMARY KEY (chat_id, msg_id, hash)
            )
        """)
        
        # Playlist / folders collection
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS playlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                parent_folder TEXT NOT NULL,
                name TEXT NOT NULL,
                thumbnail TEXT,
                type TEXT NOT NULL,
                chat_id TEXT,
                file_id INTEGER,
                hash TEXT,
                size TEXT,
                file_type TEXT
            )
        """)
        
        # Config / key-value store
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        
        # Media cache records
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS media_cache (
                cache_key TEXT PRIMARY KEY,
                chat_id INTEGER,
                msg_id INTEGER,
                secure_hash TEXT,
                file_name TEXT,
                file_size INTEGER,
                mime_type TEXT,
                file_path TEXT,
                cached_path TEXT,
                access_count INTEGER DEFAULT 1,
                last_access TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                score REAL DEFAULT 0.0
            )
        """)
        try:
            cursor.execute("ALTER TABLE media_cache ADD COLUMN file_path TEXT")
        except Exception:
            pass
        
        # Create indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_title_chat ON files(title, chat_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_playlist_parent ON playlist(parent_folder, type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_cache_score ON media_cache(score)")
        
        conn.commit()
        conn.close()

    async def execute_query(self, query: str, params: tuple = (), commit: bool = False, fetch: str = None):
        import aiosqlite
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(query, params) as cursor:
                    if commit:
                        await db.commit()
                        return cursor.rowcount or cursor.lastrowid
                    if fetch == "one":
                        row = await cursor.fetchone()
                        return dict(row) if row else None
                    elif fetch == "all":
                        rows = await cursor.fetchall()
                        return [dict(r) for r in rows]
                    return None


class Database:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Database, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        
        self.is_mongo = USE_MONGO
        self._client = None
        self._client_loop = None
        self._db = None
        self.sqlite = SQLiteBackend() if not self.is_mongo else None
        self._initialized = True
        LOGGER.info(f"Database initialized using: {'MongoDB' if self.is_mongo else 'SQLite (surftg.db)'}")

    @property
    def mongo_client(self):
        if self.is_mongo:
            try:
                curr_loop = asyncio.get_running_loop()
            except RuntimeError:
                curr_loop = None
            if self._client is None or self._client_loop != curr_loop:
                from motor.motor_asyncio import AsyncIOMotorClient
                self._client_loop = curr_loop
                self._client = AsyncIOMotorClient(
                    Telegram.DATABASE_URL,
                    serverSelectionTimeoutMS=4000,
                    connectTimeoutMS=4000,
                    socketTimeoutMS=5000,
                    uuidRepresentation='standard'
                )
                self._db = self._client["surftg"]
        return self._client

    @property
    def db(self):
        if (self._db is None or self._client is None) and self.is_mongo:
            _ = self.mongo_client
        return self._db

    @property
    def collection(self):
        if self.is_mongo:
            return self.db["playlist"]
        return None

    @property
    def config(self):
        if self.is_mongo:
            return self.db["config"]
        return None

    @property
    def files(self):
        if self.is_mongo:
            return self.db["files"]
        return None

    async def create_indexes(self):
        if self.is_mongo:
            try:
                await asyncio.wait_for(asyncio.gather(
                    self.files.create_index([("title", "text"), ("chat_id", 1)]),
                    self.collection.create_index([("name", "text"), ("parent_folder", 1)])
                ), timeout=4.0)
            except Exception as e:
                LOGGER.warning(f"Mongo index creation notice: {e}")
        else:
            # Already created in SQLite init
            pass

    async def create_folder(self, parent_id, folder_name, thumbnail):
        if self.is_mongo:
            folder = {"parent_folder": parent_id, "name": folder_name,
                      "thumbnail": thumbnail, "type": "folder"}
            await self.collection.insert_one(folder)
        else:
            await self.sqlite.execute_query(
                "INSERT INTO playlist (parent_folder, name, thumbnail, type) VALUES (?, ?, ?, 'folder')",
                (str(parent_id), str(folder_name), str(thumbnail or '')),
                commit=True
            )

    async def delete(self, document_id):
        try:
            if self.is_mongo:
                from bson import ObjectId
                has_child_documents = await self.collection.count_documents({'parent_folder': document_id}) > 0
                if has_child_documents:
                    await self.collection.delete_many({'parent_folder': document_id})
                result = await self.collection.delete_one({'_id': ObjectId(document_id)})
                return result.deleted_count > 0
            else:
                doc_str = str(document_id)
                # Delete children
                await self.sqlite.execute_query(
                    "DELETE FROM playlist WHERE parent_folder = ?",
                    (doc_str,),
                    commit=True
                )
                # Delete item itself
                deleted = await self.sqlite.execute_query(
                    "DELETE FROM playlist WHERE id = ?",
                    (int(document_id) if str(document_id).isdigit() else -1,),
                    commit=True
                )
                return deleted > 0
        except Exception as e:
            LOGGER.error(f"Error in delete: {e}")
            return False

    async def edit(self, id, name, thumbnail):
        try:
            if self.is_mongo:
                from bson import ObjectId
                result = await self.collection.update_one(
                    {"_id": ObjectId(id)},
                    {"$set": {"name": name, "thumbnail": thumbnail}}
                )
                return result.modified_count > 0
            else:
                doc_id = int(id) if str(id).isdigit() else -1
                updated = await self.sqlite.execute_query(
                    "UPDATE playlist SET name = ?, thumbnail = ? WHERE id = ?",
                    (str(name), str(thumbnail or ''), doc_id),
                    commit=True
                )
                return updated > 0
        except Exception as e:
            LOGGER.error(f"Error in edit: {e}")
            return False

    async def search_DbFolder(self, query):
        if self.is_mongo:
            from pymongo import DESCENDING
            words = re.findall(r'\w+', query.lower())
            regex_pattern = '.*'.join(f'(?=.*{re.escape(word)})' for word in words)
            regex_query = {'$regex': f'.*{regex_pattern}.*', '$options': 'i'}
            myquery = {'type': 'folder', 'name': regex_query}
            cursor = self.collection.find(myquery).sort('_id', DESCENDING)
            mydoc = await cursor.to_list(length=None)
            return [{'_id': str(x['_id']), 'name': x['name']} for x in mydoc]
        else:
            words = [f"%{w}%" for w in re.findall(r'\w+', query.lower())]
            if not words:
                rows = await self.sqlite.execute_query(
                    "SELECT id, name FROM playlist WHERE type = 'folder' ORDER BY id DESC LIMIT 50",
                    fetch="all"
                )
            else:
                conditions = " AND ".join(["LOWER(name) LIKE ?" for _ in words])
                rows = await self.sqlite.execute_query(
                    f"SELECT id, name FROM playlist WHERE type = 'folder' AND {conditions} ORDER BY id DESC LIMIT 50",
                    tuple(words),
                    fetch="all"
                )
            return [{'_id': str(r['id']), 'name': r['name']} for r in rows]

    async def add_json(self, data):
        if not data:
            return
        if self.is_mongo:
            await self.collection.insert_many(data)
        else:
            for item in data:
                await self.sqlite.execute_query(
                    """INSERT INTO playlist 
                       (parent_folder, name, thumbnail, type, chat_id, file_id, hash, size, file_type) 
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(item.get('parent_folder', 'root')),
                        str(item.get('name', '')),
                        str(item.get('thumbnail', '')),
                        str(item.get('type', 'file')),
                        str(item.get('chat_id', '')),
                        int(item.get('file_id', 0)),
                        str(item.get('hash', '')),
                        str(item.get('size', '')),
                        str(item.get('file_type', ''))
                    ),
                    commit=True
                )

    async def get_Dbfolder(self, parent_id="root", page=1, per_page=50):
        if self.is_mongo:
            try:
                query = {"parent_folder": parent_id, "type": "folder"}
                cursor = self.collection.find(query)
                if parent_id != 'root':
                    offset = (int(page) - 1) * per_page
                    cursor = cursor.skip(offset).limit(per_page)
                docs = await asyncio.wait_for(cursor.to_list(length=per_page if parent_id != 'root' else 100), timeout=3.0)
                for d in docs:
                    d['_id'] = str(d['_id'])
                return docs
            except Exception as e:
                LOGGER.warning(f"get_Dbfolder Mongo notice: {e}")
                return []
        else:
            try:
                offset = (int(page) - 1) * per_page
                if parent_id == 'root':
                    rows = await asyncio.wait_for(self.sqlite.execute_query(
                        "SELECT id, parent_folder, name, thumbnail, type FROM playlist WHERE parent_folder = 'root' AND type = 'folder' ORDER BY id DESC",
                        fetch="all"
                    ), timeout=3.0)
                else:
                    rows = await asyncio.wait_for(self.sqlite.execute_query(
                        "SELECT id, parent_folder, name, thumbnail, type FROM playlist WHERE parent_folder = ? AND type = 'folder' ORDER BY id DESC LIMIT ? OFFSET ?",
                        (str(parent_id), per_page, offset),
                        fetch="all"
                    ), timeout=3.0)
                return [{'_id': str(r['id']), 'parent_folder': r['parent_folder'], 'name': r['name'], 'thumbnail': r['thumbnail'], 'type': r['type']} for r in (rows or [])]
            except Exception as e:
                LOGGER.warning(f"get_Dbfolder SQLite notice: {e}")
                return []

    async def get_dbFiles(self, parent_id=None, page=1, per_page=50):
        if self.is_mongo:
            from pymongo import DESCENDING
            query = {"parent_folder": parent_id, "type": "file"}
            offset = (int(page) - 1) * per_page
            cursor = self.collection.find(query).sort('file_id', DESCENDING).skip(offset).limit(per_page)
            docs = await cursor.to_list(length=per_page)
            for d in docs:
                d['_id'] = str(d['_id'])
            return docs
        else:
            offset = (int(page) - 1) * per_page
            rows = await self.sqlite.execute_query(
                """SELECT id, parent_folder, name, thumbnail, type, chat_id, file_id, hash, size, file_type 
                   FROM playlist WHERE parent_folder = ? AND type = 'file' 
                   ORDER BY file_id DESC LIMIT ? OFFSET ?""",
                (str(parent_id), per_page, offset),
                fetch="all"
            )
            return [{
                '_id': str(r['id']),
                'parent_folder': r['parent_folder'],
                'name': r['name'],
                'thumbnail': r['thumbnail'],
                'type': r['type'],
                'chat_id': r['chat_id'],
                'file_id': r['file_id'],
                'hash': r['hash'],
                'size': r['size'],
                'file_type': r['file_type']
            } for r in rows]

    async def get_info(self, id):
        if not id:
            return None
        if self.is_mongo:
            from bson import ObjectId
            try:
                if document := await self.collection.find_one({'_id': ObjectId(id)}):
                    return document.get('name', None)
            except Exception:
                pass
            return None
        else:
            row = await self.sqlite.execute_query(
                "SELECT name FROM playlist WHERE id = ?",
                (int(id) if str(id).isdigit() else -1,),
                fetch="one"
            )
            return row['name'] if row else None

    async def search_dbfiles(self, id, query, page=1, per_page=50):
        if self.is_mongo:
            from pymongo import DESCENDING
            words = re.findall(r'\w+', query.lower())
            regex_pattern = '.*'.join(f'(?=.*{re.escape(word)})' for word in words)
            regex_query = {'$regex': f'.*{regex_pattern}.*', '$options': 'i'}
            mquery = {'type': 'file', 'parent_folder': id, 'name': regex_query}
            offset = (int(page) - 1) * per_page
            cursor = self.collection.find(mquery).sort('file_id', DESCENDING).skip(offset).limit(per_page)
            docs = await cursor.to_list(length=per_page)
            for d in docs:
                d['_id'] = str(d['_id'])
            return docs
        else:
            words = [f"%{w}%" for w in re.findall(r'\w+', query.lower())]
            offset = (int(page) - 1) * per_page
            if not words:
                rows = await self.sqlite.execute_query(
                    """SELECT id, parent_folder, name, thumbnail, type, chat_id, file_id, hash, size, file_type 
                       FROM playlist WHERE parent_folder = ? AND type = 'file' 
                       ORDER BY file_id DESC LIMIT ? OFFSET ?""",
                    (str(id), per_page, offset),
                    fetch="all"
                )
            else:
                conditions = " AND ".join(["LOWER(name) LIKE ?" for _ in words])
                rows = await self.sqlite.execute_query(
                    f"""SELECT id, parent_folder, name, thumbnail, type, chat_id, file_id, hash, size, file_type 
                       FROM playlist WHERE parent_folder = ? AND type = 'file' AND {conditions}
                       ORDER BY file_id DESC LIMIT ? OFFSET ?""",
                    (str(id), *words, per_page, offset),
                    fetch="all"
                )
            return [{
                '_id': str(r['id']),
                'parent_folder': r['parent_folder'],
                'name': r['name'],
                'thumbnail': r['thumbnail'],
                'type': r['type'],
                'chat_id': r['chat_id'],
                'file_id': r['file_id'],
                'hash': r['hash'],
                'size': r['size'],
                'file_type': r['file_type']
            } for r in rows]

    async def update_config(self, theme=None, auth_channel=None):
        bot_id = Telegram.BOT_TOKEN.split(":", 1)[0] if Telegram.BOT_TOKEN else "default"
        if self.is_mongo:
            update_data = {}
            if theme is not None:
                update_data["theme"] = theme
            if auth_channel is not None:
                update_data["auth_channel"] = auth_channel
            config = await self.config.find_one({"_id": bot_id})
            if config is None:
                result = await self.config.insert_one(
                    {"_id": bot_id, **update_data})
                return result.inserted_id is not None
            else:
                result = await self.config.update_one({"_id": bot_id}, {
                    "$set": update_data})
                return result.modified_count > 0
        else:
            if theme is not None:
                await self.sqlite.execute_query(
                    "INSERT OR REPLACE INTO config (key, value) VALUES ('theme', ?)",
                    (str(theme),),
                    commit=True
                )
            if auth_channel is not None:
                await self.sqlite.execute_query(
                    "INSERT OR REPLACE INTO config (key, value) VALUES ('auth_channel', ?)",
                    (str(auth_channel),),
                    commit=True
                )
            return True

    async def get_variable(self, key):
        if self.is_mongo:
            try:
                bot_id = Telegram.BOT_TOKEN.split(":", 1)[0] if Telegram.BOT_TOKEN else "default"
                config = await asyncio.wait_for(self.config.find_one({"_id": bot_id}), timeout=2.5)
                return config.get(key) if config is not None else None
            except Exception as e:
                LOGGER.warning(f"get_variable({key}) Mongo notice: {e}")
                return None
        else:
            try:
                row = await asyncio.wait_for(self.sqlite.execute_query(
                    "SELECT value FROM config WHERE key = ?",
                    (str(key),),
                    fetch="one"
                ), timeout=2.5)
                return row['value'] if row else None
            except Exception as e:
                LOGGER.warning(f"get_variable({key}) SQLite notice: {e}")
                return None

    async def list_tgfiles(self, id, page=1, per_page=50):
        if self.is_mongo:
            try:
                from pymongo import DESCENDING
                query = {'chat_id': id}
                offset = (int(page) - 1) * per_page
                cursor = self.files.find(query).sort('msg_id', DESCENDING).skip(offset).limit(per_page)
                return await asyncio.wait_for(cursor.to_list(length=per_page), timeout=3.5)
            except Exception as e:
                LOGGER.warning(f"list_tgfiles Mongo notice: {e}")
                return []
        else:
            offset = (int(page) - 1) * per_page
            rows = await self.sqlite.execute_query(
                "SELECT chat_id, msg_id, hash, title, size, type FROM files WHERE chat_id = ? ORDER BY msg_id DESC LIMIT ? OFFSET ?",
                (str(id), per_page, offset),
                fetch="all"
            )
            return rows

    async def add_tgfiles(self, chat_id, file_id, hash, name, size, file_type):
        if self.is_mongo:
            if await self.files.find_one({"chat_id": chat_id, "hash": hash}):
                return
            file = {"chat_id": chat_id, "msg_id": file_id,
                    "hash": hash, "title": name, "size": size, "type": file_type}
            await self.files.insert_one(file)
        else:
            await self.sqlite.execute_query(
                "INSERT OR IGNORE INTO files (chat_id, msg_id, hash, title, size, type) VALUES (?, ?, ?, ?, ?, ?)",
                (str(chat_id), int(file_id), str(hash), str(name), str(size), str(file_type)),
                commit=True
            )

    async def search_tgfiles(self, id, query, page=1, per_page=50):
        if self.is_mongo:
            from pymongo import DESCENDING
            words = re.findall(r'\w+', query.lower())
            regex_pattern = '.*'.join(f'(?=.*{re.escape(word)})' for word in words)
            regex_query = {'$regex': f'.*{regex_pattern}.*', '$options': 'i'}
            mquery = {'chat_id': id, 'title': regex_query}
            offset = (int(page) - 1) * per_page
            cursor = self.files.find(mquery).sort('msg_id', DESCENDING).skip(offset).limit(per_page)
            return await cursor.to_list(length=per_page)
        else:
            words = [f"%{w}%" for w in re.findall(r'\w+', query.lower())]
            offset = (int(page) - 1) * per_page
            if not words:
                return await self.list_tgfiles(id, page, per_page)
            conditions = " AND ".join(["LOWER(title) LIKE ?" for _ in words])
            rows = await self.sqlite.execute_query(
                f"SELECT chat_id, msg_id, hash, title, size, type FROM files WHERE chat_id = ? AND {conditions} ORDER BY msg_id DESC LIMIT ? OFFSET ?",
                (str(id), *words, per_page, offset),
                fetch="all"
            )
            return rows

    async def add_btgfiles(self, data):
        if not data:
            return
        if self.is_mongo:
            await self.files.insert_many(data)
        else:
            for item in data:
                await self.add_tgfiles(
                    item.get('chat_id'),
                    item.get('msg_id'),
                    item.get('hash'),
                    item.get('title'),
                    item.get('size'),
                    item.get('type')
                )

    async def delete_file(self, chat_id, msg_id, hash):
        try:
            if self.is_mongo:
                result = await self.files.delete_one({
                    "chat_id": str(chat_id),
                    "msg_id": int(msg_id),
                    "hash": hash
                })
                return result.deleted_count > 0
            else:
                deleted = await self.sqlite.execute_query(
                    "DELETE FROM files WHERE chat_id = ? AND msg_id = ? AND hash = ?",
                    (str(chat_id), int(msg_id), str(hash)),
                    commit=True
                )
                return deleted > 0
        except Exception as e:
            LOGGER.error(f"Error deleting file: {e}")
            return False

    async def list_all_files(self, page=1, per_page=100):
        try:
            if self.is_mongo:
                from pymongo import DESCENDING
                offset = (int(page) - 1) * per_page
                cursor = self.files.find().sort('msg_id', DESCENDING).skip(offset).limit(per_page)
                return await cursor.to_list(length=per_page)
            else:
                offset = (int(page) - 1) * per_page
                rows = await self.sqlite.execute_query(
                    "SELECT chat_id, msg_id, hash, title, size, type FROM files ORDER BY rowid DESC LIMIT ? OFFSET ?",
                    (per_page, offset),
                    fetch="all"
                )
                return rows
        except Exception as e:
            LOGGER.error(f"Error listing files: {e}")
            return []
