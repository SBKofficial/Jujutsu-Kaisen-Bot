import time

class CacheService:
    def __init__(self):
        self.user_cache = {}
        self.roster_cache = {}
        self.ttl = 300
        self.roster_ttl = 60

    def get_user(self, user_id):
        now = time.time()
        if user_id in self.user_cache and now < self.user_cache[user_id]['expires_at']:
            return self.user_cache[user_id]['data']
        return None

    def set_user(self, user_id, user):
        self.user_cache[user_id] = {
            "data": user,
            "expires_at": time.time() + self.ttl
        }

    def invalidate(self, user_id):
        if user_id in self.user_cache:
            del self.user_cache[user_id]

    def update_user(self, user_id, update_dict):
        now = time.time()
        if user_id in self.user_cache and now < self.user_cache[user_id]['expires_at']:
            cached_data = self.user_cache[user_id]['data']
            
            # Apply $set operator
            set_ops = update_dict.get('$set', {})
            for k, v in set_ops.items():
                self._set_nested(cached_data, k, v)
                
            # Apply $inc operator
            inc_ops = update_dict.get('$inc', {})
            for k, v in inc_ops.items():
                self._inc_nested(cached_data, k, v)
        else:
            # If not in cache or expired, just ignore (it will be fetched next time)
            pass

    def _set_nested(self, d, path, value):
        keys = path.split('.')
        for key in keys[:-1]:
            d = d.setdefault(key, {})
            if not isinstance(d, dict):
                return
        d[keys[-1]] = value

    def _inc_nested(self, d, path, value):
        keys = path.split('.')
        for key in keys[:-1]:
            d = d.setdefault(key, {})
            if not isinstance(d, dict):
                return
        last_key = keys[-1]
        try:
            d[last_key] = (d.get(last_key) or 0) + value
        except Exception:
            d[last_key] = value

    def get_roster(self, user_id):
        now = time.time()
        if user_id in self.roster_cache and now < self.roster_cache[user_id]['expires_at']:
            return self.roster_cache[user_id]['data']
        return None

    def set_roster(self, user_id, roster):
        self.roster_cache[user_id] = {
            "data": roster,
            "expires_at": time.time() + self.roster_ttl
        }

    def invalidate_roster(self, user_id):
        if user_id in self.roster_cache:
            del self.roster_cache[user_id]

cache_service = CacheService()
