from collections.abc import MutableMapping
from threading import RLock
from types import MappingProxyType
import copy


class ThreadSafeSessionState(MutableMapping):
	"""
	A thread-safe mapping wrapper for workflow_session_state.
	Provides minimal locking around writes and short locking for reads.
	"""

	def __init__(self, initial=None):
		self._data = dict(initial or {})
		self._lock = RLock()

	def __getitem__(self, key):
		with self._lock:
			return self._data[key]

	def __setitem__(self, key, value):
		with self._lock:
			self._data[key] = value

	def __delitem__(self, key):
		with self._lock:
			del self._data[key]

	def __iter__(self):
		with self._lock:
			return iter(list(self._data.keys()))

	def __len__(self):
		with self._lock:
			return len(self._data)

	def get_readonly_view(self):
		with self._lock:
			return MappingProxyType(self._data)

	def snapshot(self):
		with self._lock:
			return copy.deepcopy(self._data)

	def merge(self, other: dict):
		"""Atomically deep-merge another dict into state."""
		from agno.utils.merge_dict import merge_dictionaries
		with self._lock:
			merge_dictionaries(self._data, other or {}) 