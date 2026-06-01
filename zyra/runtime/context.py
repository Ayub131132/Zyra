from datetime import datetime
from typing import Any, Optional

class ZyraContext:
    def __init__(self, update, context, referrer=None):
        self._update = update
        self._context = context
        self._referrer = referrer
        
    @property
    def user(self):
        return self._update.effective_user if self._update else None

    @property
    def referrer(self):
        return self._referrer
        
    @property
    def chat(self):
        return self._update.effective_chat if self._update else None
        
    @property
    def message(self):
        return self._update.message if self._update else None
        
    @property
    def query(self):
        return self._update.callback_query if self._update else None
        
    @property
    def bot(self):
        return self._context.bot if self._context else None
        
    @property
    def chat_id(self):
        return self.chat.id if self.chat else None
        
    @property
    def now(self):
        return datetime.now()

    def get_member(self, obj_name: Optional[str], prop_name: str) -> Any:
        if obj_name is None:
            # Direct property access on ZyraContext
            if prop_name == 'referrer':
                return self.referrer
            return getattr(self, prop_name, None)
        
        if obj_name == 'user' and prop_name == 'referrer':
            return self.referrer

        obj = getattr(self, obj_name, None)
        if obj is None:
            return None
        return getattr(obj, prop_name, None)
