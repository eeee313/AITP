import random
import string
from datetime import datetime

class KeyManager:
    def __init__(self, config):
        self.config = config
        if 'keys' not in self.config:
            self.config['keys'] = {}
        if 'claimed_keys' not in self.config:
            self.config['claimed_keys'] = {}
    
    def generate_key(self):
        """Generate a single random key"""
        parts = []
        for _ in range(4):
            part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
            parts.append(part)
        return '-'.join(parts)
    
    def generate_keys(self, count):
        """Generate multiple unique keys"""
        keys = []
        for _ in range(count):
            key = self.generate_key()
            while key in self.config['keys'] or key in self.config['claimed_keys']:
                key = self.generate_key()
            
            self.config['keys'][key] = {
                'created_at': datetime.now().isoformat(),
                'claimed': False,
                'claimed_by': None,
                'claimed_at': None
            }
            keys.append(key)
        
        self._save_config()
        return keys
    
    def claim_key(self, key, user_id, username):
        """Claim a key for a user"""
        if key not in self.config['keys']:
            return False
        
        if self.config['keys'][key]['claimed']:
            return False
        
        self.config['keys'][key]['claimed'] = True
        self.config['keys'][key]['claimed_by'] = user_id
        self.config['keys'][key]['claimed_at'] = datetime.now().isoformat()
        self.config['keys'][key]['username'] = username
        
        self.config['claimed_keys'][key] = {
            'user_id': user_id,
            'username': username,
            'claimed_at': datetime.now().isoformat(),
            'is_active': False
        }
        
        self._save_config()
        return True
    
    def list_keys(self):
        """List all available (unclaimed) keys"""
        available = []
        for key, data in self.config['keys'].items():
            if not data['claimed']:
                available.append(key)
        return available
    
    def has_claimed_key(self, user_id):
        """Check if a user has claimed a key"""
        for key, data in self.config['claimed_keys'].items():
            if data['user_id'] == user_id:
                return True
        return False
    
    def get_user_key(self, user_id):
        """Get the key claimed by a user"""
        for key, data in self.config['claimed_keys'].items():
            if data['user_id'] == user_id:
                return key
        return None
    
    def _save_config(self):
        """Save the config to file"""
        import json
        with open('config.json', 'w') as f:
            json.dump(self.config, f, indent=4)
