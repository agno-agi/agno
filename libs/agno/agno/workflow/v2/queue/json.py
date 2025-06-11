import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from agno.utils.log import logger
from agno.workflow.v2.queue.base import Queue, QueueItem


class JsonQueue(Queue):
    """JSON file-based queue implementation"""

    def __init__(self, queue_file: Optional[str] = None):
        """Initialize JSON queue

        Args:
            queue_file: Path to queue file. If None, uses default location.
        """
        if queue_file is None:
            queue_dir = Path("tmp/.agno")
            queue_dir.mkdir(parents=True, exist_ok=True)
            queue_file = queue_dir / "workflow_queue.json"

        self.queue_file = Path(queue_file)
        self.queue_file.parent.mkdir(parents=True, exist_ok=True)

        # Initialize empty queue if file doesn't exist
        if not self.queue_file.exists():
            self._save_queue([])

    def _load_queue(self) -> List[QueueItem]:
        """Load queue from JSON file"""
        try:
            if not self.queue_file.exists():
                return []

            with open(self.queue_file, "r") as f:
                data = json.load(f)
                return [QueueItem.from_dict(item) for item in data]
        except (json.JSONDecodeError, FileNotFoundError) as e:
            logger.warning(f"Failed to load queue: {e}. Starting with empty queue.")
            return []

    def _save_queue(self, queue_items: List[QueueItem]):
        """Save queue to JSON file"""
        try:
            data = [item.to_dict() for item in queue_items]
            with open(self.queue_file, "w") as f:
                json.dump(data, f, indent=2)
            logger.debug(f"Saved queue with {len(queue_items)} items")
        except Exception as e:
            logger.error(f"Failed to save queue: {e}")
            raise

    def submit(
        self,
        workflow_id: str,
        query: str,
        sequence_name: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> str:
        """Submit a workflow run to the queue"""
        run_id = str(uuid4())

        # Load existing queue
        queue_items = self._load_queue()

        # Create new queue item
        queue_item = QueueItem(
            run_id=run_id,
            workflow_id=workflow_id,
            query=query,
            sequence_name=sequence_name,
            user_id=user_id,
            session_id=session_id,
        )

        # Add to queue
        queue_items.append(queue_item)

        # Save queue
        self._save_queue(queue_items)

        logger.info(f"Submitted workflow run {run_id} to queue")
        return run_id

    def get_next_queued(self, workflow_id: str) -> Optional[QueueItem]:
        """Get the next queued item for a specific workflow"""
        queue_items = self._load_queue()

        # Find the first queued item for this workflow
        for item in queue_items:
            if item.workflow_id == workflow_id and item.status == "queued":
                return item

        return None

    def update_status(self, run_id: str, status: str) -> bool:
        """Update the status of a queued run"""
        queue_items = self._load_queue()

        # Find and update the item
        for item in queue_items:
            if item.run_id == run_id:
                item.status = status
                item.updated_at = datetime.now().isoformat()
                self._save_queue(queue_items)
                logger.debug(f"Updated run {run_id} status to {status}")
                return True

        logger.warning(f"Run {run_id} not found in queue")
        return False

    def get_all_queued(self) -> List[QueueItem]:
        """Get all queued items"""
        return self.get_by_status("queued")

    def get_by_status(self, status: str) -> List[QueueItem]:
        """Get all items with a specific status"""
        queue_items = self._load_queue()
        return [item for item in queue_items if item.status == status]

    def clear_completed(self) -> int:
        """Remove completed items from queue"""
        queue_items = self._load_queue()
        original_count = len(queue_items)

        # Keep only non-completed items
        filtered_items = [item for item in queue_items if item.status not in ["completed", "failed"]]

        self._save_queue(filtered_items)
        removed_count = original_count - len(filtered_items)

        if removed_count > 0:
            logger.info(f"Removed {removed_count} completed items from queue")

        return removed_count

    def get_stats(self) -> Dict[str, Any]:
        """Get queue statistics"""
        queue_items = self._load_queue()

        stats = {
            "total": len(queue_items),
            "by_status": {},
            "by_workflow": {},
        }

        for item in queue_items:
            # Count by status
            stats["by_status"][item.status] = stats["by_status"].get(item.status, 0) + 1

            # Count by workflow
            stats["by_workflow"][item.workflow_id] = stats["by_workflow"].get(item.workflow_id, 0) + 1

        return stats
