"""Bounded, isolated process-local conversation storage for the API."""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
from time import monotonic
from uuid import UUID, uuid4

from .chat import Session


class SessionMissing(Exception):
    pass


class SessionBusy(Exception):
    pass


class SessionCapacity(Exception):
    pass


@dataclass
class Entry:
    session: Session
    deadline: float
    created_at: datetime
    busy: bool = False


class SessionStore:
    def __init__(self, factory, *, ttl, capacity, clock=monotonic):
        self._factory = factory
        self._ttl = ttl
        self._capacity = capacity
        self._clock = clock
        self._entries = {}
        self._lock = Lock()

    @staticmethod
    def _utcnow():
        return datetime.now(timezone.utc)

    def _purge(self, now):
        for identifier, entry in list(self._entries.items()):
            if not entry.busy and entry.deadline <= now:
                del self._entries[identifier]

    def _get(self, identifier):
        self._purge(self._clock())
        entry = self._entries.get(identifier)
        if entry is None:
            raise SessionMissing()
        return entry

    def _view(self, identifier, entry):
        return {
            "session_id": identifier,
            "created_at": entry.created_at,
            "expires_at": self._utcnow() + timedelta(seconds=max(0, entry.deadline - self._clock())),
            "busy": entry.busy,
            "recent_messages": [{"role": role, "content": content} for role, content in entry.session.history],
        }

    def create(self):
        with self._lock:
            now = self._clock()
            self._purge(now)
            if len(self._entries) >= self._capacity:
                raise SessionCapacity()
            identifier = uuid4()
            entry = Entry(self._factory(), now + self._ttl, self._utcnow())
            self._entries[identifier] = entry
            return self._view(identifier, entry)

    def inspect(self, identifier: UUID):
        with self._lock:
            return self._view(identifier, self._get(identifier))

    def delete(self, identifier: UUID):
        with self._lock:
            self._get(identifier)
            del self._entries[identifier]

    def borrow(self, identifier: UUID):
        with self._lock:
            entry = self._get(identifier)
            if entry.busy:
                raise SessionBusy()
            snapshot = deepcopy(entry.session)
            entry.busy = True
            return entry, snapshot

    def commit(self, identifier: UUID, entry: Entry, snapshot: Session):
        with self._lock:
            if self._entries.get(identifier) is not entry:
                raise SessionMissing()
            entry.session = snapshot
            entry.deadline = self._clock() + self._ttl

    def release(self, identifier: UUID, entry: Entry):
        with self._lock:
            if self._entries.get(identifier) is entry:
                entry.busy = False
                self._purge(self._clock())
